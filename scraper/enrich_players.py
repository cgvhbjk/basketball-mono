#!/usr/bin/env python3
"""
Enrich player profiles from external sources.

Usage:
  python enrich_players.py [--source 247|on3|passport] [--limit N] [--dry-run] [--clean-bad]

  --source 247      Search 247Sports for height, grad_year, high_school, hometown (default)
  --source on3      Search On3 for star rating, national rank, height, school
  --source passport Fetch The Passport profiles for 3SSB players (requires passport_id)
  --limit N         Max number of players to process (default 50)
  --dry-run         Print what would be updated without writing to the DB
  --clean-bad       Delete players with single-character first or last name first
"""
import asyncio
import argparse
import json
import logging
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from supabase import create_client
from basketball_scraper.config import settings

_CHECKPOINT_INTERVAL = 100
_CHECKPOINT_PATHS = {
    "on3": os.path.join(os.path.dirname(__file__), ".checkpoint_on3_enrich.json"),
    "247": os.path.join(os.path.dirname(__file__), ".checkpoint_247_enrich.json"),
}


def _load_checkpoint(source: str) -> set[str]:
    path = _CHECKPOINT_PATHS[source]
    try:
        with open(path) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_checkpoint(source: str, done: set[str]) -> None:
    # Atomic write: dump to a sibling temp file and rename. open("w") truncates
    # immediately, so a SIGKILL/power-loss between truncate and full write would
    # leave a partial JSON file that _load_checkpoint silently treats as "no
    # checkpoint" — meaning every already-processed player gets re-fetched.
    path = _CHECKPOINT_PATHS[source]
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(list(done), f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# Placeholder strings the scrapers sometimes write when a real value is
# missing — none of these are plausible person names.
_BAD_NAME_TOKENS = {
    "tbd", "tba", "n/a", "na", "none", "null", "unknown",
    "player", "coach", "test", "x", "y", "z", "?",
}


def _is_bad_name(s: str) -> bool:
    if not s:
        return True
    stripped = s.strip()
    if len(stripped) < 2:
        return True
    if not any(c.isalpha() for c in stripped):
        return True
    if stripped.lower() in _BAD_NAME_TOKENS:
        return True
    # All same character ("aaa", "....", "---") — but only flag length 3+,
    # since "JJ"/"AJ"/"CJ"/etc. are common real nicknames.
    if len(stripped) >= 3 and len(set(stripped.lower())) == 1:
        return True
    return False


def clean_bad_players(supabase, dry_run: bool = False) -> int:
    """Delete players with implausibly short or placeholder names (scraper artifacts)."""
    PAGE = 1000
    bad: list[dict] = []
    offset = 0
    while True:
        result = (
            supabase.table("players")
            .select("id, first_name, last_name")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        page = result.data or []
        if not page:
            break
        for r in page:
            if _is_bad_name(r["first_name"]) or _is_bad_name(r["last_name"]):
                bad.append(r)
        if len(page) < PAGE:
            break
        offset += PAGE

    if not bad:
        logger.info("No bad player records found")
        return 0

    # Show a sample so the user can sanity-check before we nuke anything.
    sample = bad[:20]
    logger.info(
        "Found %d bad player records. Sample: %s%s",
        len(bad),
        ", ".join(f"{r['first_name']!r}/{r['last_name']!r}" for r in sample),
        " ..." if len(bad) > len(sample) else "",
    )

    if dry_run:
        logger.info("Dry run — not deleting")
        return len(bad)

    logger.info("Deleting %d bad player records", len(bad))
    for r in bad:
        pid = r["id"]
        supabase.table("box_scores").delete().eq("player_id", pid).execute()
        supabase.table("player_season_stats").delete().eq("player_id", pid).execute()
        supabase.table("team_rosters").delete().eq("player_id", pid).execute()
        supabase.table("players").delete().eq("id", pid).execute()
    return len(bad)


async def run_on3(supabase, limit: int, dry_run: bool) -> None:
    from basketball_scraper.enrich_on3 import On3Enricher, REQUEST_DELAY

    done_ids = _load_checkpoint("on3")
    if done_ids:
        logger.info("Resuming from checkpoint — %d players already attempted", len(done_ids))

    # Pull candidate players page by page until we've found `limit` fresh ones,
    # rather than guessing fetch_limit = limit + len(done_ids). PostgREST caps
    # each request at 1000 rows, so a previous "limit + done" approach could
    # silently return a window that's entirely already-done and strand the
    # remaining fresh names off-page.
    PAGE = 1000
    MAX_SCAN = 20_000  # hard ceiling so a misconfigured run can't crawl forever
    players: list[dict] = []
    scanned = 0
    offset = 0
    while len(players) < limit and scanned < MAX_SCAN:
        result = (
            supabase.table("players")
            .select("id, first_name, last_name, height_inches, grad_year, high_school, national_rank")
            .or_("national_rank.is.null,height_inches.is.null")
            .order("last_name")
            .order("id")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        page = result.data or []
        if not page:
            break
        scanned += len(page)
        offset += PAGE
        for p in page:
            if p["id"] not in done_ids:
                players.append(p)
                if len(players) >= limit:
                    break
    logger.info(
        "Found %d players to enrich via On3 (%d skipped via checkpoint, scanned %d candidate rows)",
        len(players), len(done_ids), scanned,
    )

    updated = skipped = not_found = 0
    # try/finally so the checkpoint reflects everything actually processed —
    # without it, a crash or KeyboardInterrupt between checkpoint intervals
    # discards all in-memory progress and the next run redoes that work.
    try:
        async with On3Enricher() as enricher:
            for i, player in enumerate(players, 1):
                pid = player["id"]
                first, last = player["first_name"], player["last_name"]

                if _is_bad_name(first) or _is_bad_name(last):
                    logger.info("[%d/%d] Skipping %s %s (bad name)", i, len(players), first, last)
                    # Bad names won't change between runs, so checkpoint them permanently
                    done_ids.add(pid)
                    not_found += 1
                    continue

                logger.info("[%d/%d] Looking up %s %s on On3...", i, len(players), first, last)

                profile = await enricher.lookup(first, last)
                if profile is None:
                    # Don't checkpoint "not found" — On3 may index this player later
                    # and we want the next run to retry. (Bad-name skips above are
                    # the only permanent-skip case.)
                    not_found += 1
                    logger.info("  → not found")
                else:
                    patch: dict = {}
                    if profile.height_inches is not None and player["height_inches"] is None:
                        patch["height_inches"] = profile.height_inches
                    if profile.grad_year is not None and player["grad_year"] is None:
                        patch["grad_year"] = profile.grad_year
                    if profile.high_school is not None and player["high_school"] is None:
                        patch["high_school"] = profile.high_school
                    if profile.hometown:
                        patch["hometown"] = profile.hometown
                    if profile.star_rating:
                        patch["star_rating"] = profile.star_rating
                    if profile.national_rank:
                        patch["national_rank"] = profile.national_rank
                    if profile.state_rank:
                        patch["state_rank"] = profile.state_rank

                    if patch:
                        logger.info("  → patching: %s", patch)
                        if not dry_run:
                            supabase.table("players").update(patch).eq("id", pid).execute()
                        updated += 1
                    else:
                        skipped += 1
                        logger.info("  → no new data found")
                    done_ids.add(pid)

                if not dry_run and i % _CHECKPOINT_INTERVAL == 0:
                    _save_checkpoint("on3", done_ids)
                    logger.info("Checkpoint saved (%d/%d processed)", i, len(players))

                if i < len(players):
                    await asyncio.sleep(REQUEST_DELAY)
    finally:
        # Always flush the checkpoint, even on exception or Ctrl-C, so the
        # players we did successfully process don't get re-enriched next run.
        if not dry_run and done_ids:
            _save_checkpoint("on3", done_ids)

    logger.info(
        "On3 done. Updated: %d | No new data: %d | Not found: %d%s",
        updated, skipped, not_found,
        " (dry-run)" if dry_run else "",
    )


async def run_passport(supabase, limit: int, dry_run: bool) -> None:
    from basketball_scraper.enrich_passport import lookup_passport_profile, REQUEST_DELAY

    result = (
        supabase.table("players")
        .select("id, first_name, last_name, passport_id, height_inches, position, high_school")
        .not_.is_("passport_id", "null")
        .is_("height_inches", "null")
        .order("last_name")
        .limit(limit)
        .execute()
    )
    players = result.data or []
    logger.info("Found %d Passport players to enrich", len(players))

    updated = skipped = not_found = 0
    for i, player in enumerate(players, 1):
        pid = player["id"]
        passport_id = player["passport_id"]
        logger.info(
            "[%d/%d] Fetching Passport profile #%s for %s %s...",
            i, len(players), passport_id, player["first_name"], player["last_name"],
        )

        profile = await lookup_passport_profile(passport_id)
        if profile is None:
            not_found += 1
            logger.info("  → not found")
        else:
            patch: dict = {}
            if profile.height_inches is not None and player["height_inches"] is None:
                patch["height_inches"] = profile.height_inches
            if profile.position is not None and player["position"] is None:
                patch["position"] = profile.position
            if profile.high_school is not None and player["high_school"] is None:
                patch["high_school"] = profile.high_school
            if profile.hometown:
                patch["hometown"] = profile.hometown

            if patch:
                logger.info("  → patching: %s", patch)
                if not dry_run:
                    supabase.table("players").update(patch).eq("id", pid).execute()
                updated += 1
            else:
                skipped += 1
                logger.info("  → no new data found")

        if i < len(players):
            await asyncio.sleep(REQUEST_DELAY)

    logger.info(
        "Passport done. Updated: %d | No new data: %d | Not found: %d%s",
        updated, skipped, not_found,
        " (dry-run)" if dry_run else "",
    )


def _normalize_for_match(s: str) -> str:
    return " ".join(s.lower().split())


async def run_247(supabase, limit: int, dry_run: bool, extract_file: str | None) -> None:
    """Patch Supabase from a 247 JSONL extract.

    Web fetching now lives in the sports247 CLI (`extract` subcommand). This
    function is a database-only step: read the most-recent (or specified)
    JSONL extract, match each row by full name against players in the DB,
    and patch the existing columns where they're null.

    Matching is by lower-cased "first last" — 247 profile pages don't carry
    the Supabase UUID. A future migration could add `source_id_247`.
    """
    from basketball_scraper.sources.sports247 import storage

    path = Path(extract_file) if extract_file else storage.latest_path()
    if path is None or not path.exists():
        logger.error(
            "no 247 extract JSONL found. Run:\n"
            "  python -m basketball_scraper.sources.sports247 extract \\\n"
            "      --ranking-url <ranking-url> --limit %d", limit,
        )
        return

    logger.info("Reading 247 extracts from %s", path)
    extracts = list(storage.read_jsonl(path))
    by_name: dict[str, list] = {}
    for e in extracts:
        if e.name:
            by_name.setdefault(_normalize_for_match(e.name), []).append(e)
    logger.info("Loaded %d extracts (%d unique names)", len(extracts), len(by_name))

    done_ids = _load_checkpoint("247")
    if done_ids:
        logger.info("Resuming from checkpoint — %d players already attempted", len(done_ids))

    # Pull a window of candidate players that still have nulls in fields we
    # can patch from 247. Same paging pattern as run_on3.
    PAGE = 1000
    MAX_SCAN = 20_000
    players: list[dict] = []
    scanned = 0
    offset = 0
    while len(players) < limit and scanned < MAX_SCAN:
        result = (
            supabase.table("players")
            .select("id, first_name, last_name, height_inches, grad_year, high_school, hometown, star_rating, national_rank, state_rank")
            .or_("national_rank.is.null,height_inches.is.null,star_rating.is.null")
            .order("last_name")
            .order("id")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        page = result.data or []
        if not page:
            break
        scanned += len(page)
        offset += PAGE
        for p in page:
            if p["id"] not in done_ids:
                players.append(p)
                if len(players) >= limit:
                    break
    logger.info(
        "Found %d candidate players (%d skipped via checkpoint, scanned %d rows)",
        len(players), len(done_ids), scanned,
    )

    updated = skipped = not_found = 0
    try:
        for i, player in enumerate(players, 1):
            pid = player["id"]
            first, last = player["first_name"], player["last_name"]

            if _is_bad_name(first) or _is_bad_name(last):
                logger.info("[%d/%d] Skipping %s %s (bad name)", i, len(players), first, last)
                done_ids.add(pid)
                not_found += 1
                continue

            key = _normalize_for_match(f"{first} {last}")
            matches = by_name.get(key, [])
            if len(matches) != 1:
                not_found += 1
                if matches:
                    logger.info("[%d/%d] %s %s — ambiguous (%d 247 matches), skipping",
                                i, len(players), first, last, len(matches))
                else:
                    logger.info("[%d/%d] %s %s — no 247 extract found", i, len(players), first, last)
                continue

            profile = matches[0]
            patch: dict = {}
            if profile.height_inches is not None and player["height_inches"] is None:
                patch["height_inches"] = profile.height_inches
            if profile.class_year is not None and player["grad_year"] is None:
                patch["grad_year"] = profile.class_year
            if profile.high_school is not None and player["high_school"] is None:
                patch["high_school"] = profile.high_school
            if profile.hometown and not player.get("hometown"):
                ht = profile.hometown
                if ht.city and ht.state:
                    patch["hometown"] = f"{ht.city}, {ht.state}"
            if profile.stars is not None and not player.get("star_rating"):
                patch["star_rating"] = profile.stars
            if profile.national_rank is not None and not player.get("national_rank"):
                patch["national_rank"] = profile.national_rank
            if profile.state_rank is not None and not player.get("state_rank"):
                patch["state_rank"] = profile.state_rank

            if patch:
                logger.info("[%d/%d] %s %s → patching: %s", i, len(players), first, last, patch)
                if not dry_run:
                    supabase.table("players").update(patch).eq("id", pid).execute()
                updated += 1
            else:
                logger.info("[%d/%d] %s %s — extract had no fillable fields", i, len(players), first, last)
                skipped += 1
            done_ids.add(pid)

            if not dry_run and i % _CHECKPOINT_INTERVAL == 0:
                _save_checkpoint("247", done_ids)
                logger.info("Checkpoint saved (%d/%d processed)", i, len(players))
    finally:
        if not dry_run and done_ids:
            _save_checkpoint("247", done_ids)

    logger.info(
        "247Sports done. Updated: %d | No new data: %d | Not found: %d%s",
        updated, skipped, not_found,
        " (dry-run)" if dry_run else "",
    )


async def main(
    source: str,
    limit: int,
    dry_run: bool,
    clean_bad: bool,
    extract_file: str | None,
) -> None:
    supabase = create_client(settings.supabase_url, settings.supabase_service_key)

    if clean_bad:
        deleted = clean_bad_players(supabase, dry_run=dry_run)
        logger.info("Cleaned %d bad records%s", deleted, " (dry-run)" if dry_run else "")
        return

    if source == "passport":
        await run_passport(supabase, limit, dry_run)
    elif source == "on3":
        await run_on3(supabase, limit, dry_run)
    else:
        await run_247(supabase, limit, dry_run, extract_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["247", "on3", "passport"], default="247")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clean-bad", action="store_true")
    parser.add_argument(
        "--extract-file",
        default=None,
        help="(247 only) JSONL extract to read; defaults to the most recent under 247_extracts/.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.source, args.limit, args.dry_run, args.clean_bad, args.extract_file))
