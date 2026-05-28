#!/usr/bin/env python3
"""
Enrich player profiles from external sources.

Usage:
  python enrich_players.py [--source on3|passport] [--limit N] [--dry-run] [--clean-bad]

  --source on3      Search On3 for star rating, national rank, height, school (default)
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

sys.path.insert(0, os.path.dirname(__file__))

from supabase import create_client
from basketball_scraper.config import settings

_CHECKPOINT_PATH = os.path.join(os.path.dirname(__file__), ".checkpoint_on3_enrich.json")
_CHECKPOINT_INTERVAL = 100


def _load_checkpoint() -> set[str]:
    try:
        with open(_CHECKPOINT_PATH) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_checkpoint(done: set[str]) -> None:
    # Atomic write: dump to a sibling temp file and rename. open("w") truncates
    # immediately, so a SIGKILL/power-loss between truncate and full write would
    # leave a partial JSON file that _load_checkpoint silently treats as "no
    # checkpoint" — meaning every already-processed player gets re-fetched.
    tmp_path = _CHECKPOINT_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(list(done), f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, _CHECKPOINT_PATH)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _is_bad_name(s: str) -> bool:
    if not s or len(s) < 2:
        return True
    return not any(c.isalpha() for c in s)


def clean_bad_players(supabase) -> int:
    """Delete players with implausibly short names (scraper artifacts)."""
    result = supabase.table("players").select("id, first_name, last_name").execute()
    bad_ids = [
        r["id"]
        for r in (result.data or [])
        if _is_bad_name(r["first_name"]) or _is_bad_name(r["last_name"])
    ]
    if not bad_ids:
        logger.info("No bad player records found")
        return 0

    logger.info("Deleting %d bad player records", len(bad_ids))
    for pid in bad_ids:
        supabase.table("player_season_stats").delete().eq("player_id", pid).execute()
        supabase.table("team_rosters").delete().eq("player_id", pid).execute()
        supabase.table("players").delete().eq("id", pid).execute()
    return len(bad_ids)


async def run_on3(supabase, limit: int, dry_run: bool) -> None:
    from basketball_scraper.enrich_on3 import On3Enricher, REQUEST_DELAY

    done_ids = _load_checkpoint()
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
                    _save_checkpoint(done_ids)
                    logger.info("Checkpoint saved (%d/%d processed)", i, len(players))

                if i < len(players):
                    await asyncio.sleep(REQUEST_DELAY)
    finally:
        # Always flush the checkpoint, even on exception or Ctrl-C, so the
        # players we did successfully process don't get re-enriched next run.
        if not dry_run and done_ids:
            _save_checkpoint(done_ids)

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


async def main(source: str, limit: int, dry_run: bool, clean_bad: bool) -> None:
    supabase = create_client(settings.supabase_url, settings.supabase_service_key)

    if clean_bad:
        deleted = clean_bad_players(supabase)
        logger.info("Cleaned %d bad records", deleted)
        if dry_run:
            return

    if source == "passport":
        await run_passport(supabase, limit, dry_run)
    else:
        await run_on3(supabase, limit, dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["on3", "passport"], default="on3")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clean-bad", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.source, args.limit, args.dry_run, args.clean_bad))
