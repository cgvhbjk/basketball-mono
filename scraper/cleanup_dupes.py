#!/usr/bin/env python3
"""
One-time cleanup for duplicate players and cross-circuit Adidas stats.

Run after the 3ssb + adidas_gold scrapers have completed with the new code.

Two passes:
  1. Player-level: merge players who share the same passport_id but have
     different case (e.g. "Demarion Lee" vs "DeMarion Lee" from old/new parsers).
  2. Stats-level: remove Gold-circuit stats rows for players who already have
     3SSB stats for the same season (Adidas shows cumulative totals in every tier).
"""
import logging
import os
import sys
from collections import Counter

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from basketball_scraper.upsert import dedup_adidas_cross_circuit, _execute

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def merge_passport_dupes(client) -> None:
    """
    Find players that share the same passport_id (one canonical, one stale from
    old parser). Redirect all stats + roster rows to the canonical record, then
    delete the stale one.
    """
    # All players with a passport_id
    result = _execute(
        client.table("players")
        .select("id,first_name,last_name,passport_id,created_at")
        .not_.is_("passport_id", "null")
        .order("passport_id")
    )
    rows = result.data or []

    # Group by passport_id; keep the one with the most-recently-correct name
    # (assumed to be the record created/updated by the new scraper run).
    by_passport: dict[str, list[dict]] = {}
    for r in rows:
        by_passport.setdefault(r["passport_id"], []).append(r)

    merged = 0
    for passport_id, group in by_passport.items():
        if len(group) < 2:
            continue
        # Pick the most recently created record as canonical; fall back to longest
        # last_name when created_at is unavailable. This prefers the record written
        # by the new scraper run (correct casing) over the stale old-parser record.
        canonical = max(group, key=lambda r: (
            len(r.get("last_name") or ""),
            r.get("created_at") or "",
        ))
        stale = [r for r in group if r["id"] != canonical["id"]]
        for s in stale:
            logger.info(
                "Merging stale player %s (%s %s) → canonical %s (%s %s)",
                s["id"], s["first_name"], s["last_name"],
                canonical["id"], canonical["first_name"], canonical["last_name"],
            )
            # Redirect stats rows
            _execute(
                client.table("player_season_stats")
                .update({"player_id": canonical["id"]})
                .eq("player_id", s["id"])
            )
            # Redirect roster rows
            _execute(
                client.table("team_rosters")
                .update({"player_id": canonical["id"]})
                .eq("player_id", s["id"])
            )
            # Delete stale player
            _execute(client.table("players").delete().eq("id", s["id"]))
            merged += 1

    logger.info("Merged %d stale player duplicate(s)", merged)


def merge_name_dupes(client) -> None:
    """
    Find players with NO passport_id whose (first_name, last_name) case-insensitively
    matches a player WHO has a passport_id. Redirect their rows and delete them.
    """
    # All players without passport_id
    no_passport = (_execute(
        client.table("players")
        .select("id,first_name,last_name")
        .is_("passport_id", "null")
    ).data or [])

    # All players with passport_id, keyed by lowercased name
    with_passport = (_execute(
        client.table("players")
        .select("id,first_name,last_name,passport_id")
        .not_.is_("passport_id", "null")
    ).data or [])
    name_counts: Counter = Counter(
        (r["first_name"].lower(), r["last_name"].lower()) for r in with_passport
    )
    canonical_by_name: dict = {}
    warned: set = set()
    for r in with_passport:
        key = (r["first_name"].lower(), r["last_name"].lower())
        if name_counts[key] == 1:
            canonical_by_name[key] = r
        elif key not in warned:
            logger.warning(
                "Ambiguous name '%s %s': %d passport players share this name — skipping name-merge",
                r["first_name"], r["last_name"], name_counts[key],
            )
            warned.add(key)

    merged = 0
    for stale in no_passport:
        key = (stale["first_name"].lower(), stale["last_name"].lower())
        canonical = canonical_by_name.get(key)
        if not canonical:
            continue
        logger.info(
            "Name-merge stale %s (%s %s) → canonical %s (%s %s)",
            stale["id"], stale["first_name"], stale["last_name"],
            canonical["id"], canonical["first_name"], canonical["last_name"],
        )
        # Find which (team_id, season) combos the canonical already covers.
        existing = _execute(
            client.table("player_season_stats")
            .select("team_id,season")
            .eq("player_id", canonical["id"])
        ).data or []
        existing_keys = {(r["team_id"], r["season"]) for r in existing}

        stale_stats = _execute(
            client.table("player_season_stats")
            .select("id,team_id,season")
            .eq("player_id", stale["id"])
        ).data or []

        for row in stale_stats:
            if (row["team_id"], row["season"]) in existing_keys:
                # Canonical already has this row — just delete the stale one.
                _execute(client.table("player_season_stats").delete().eq("id", row["id"]))
            else:
                _execute(
                    client.table("player_season_stats")
                    .update({"player_id": canonical["id"]})
                    .eq("id", row["id"])
                )

        # Same treatment for roster rows
        existing_rosters = {(r["team_id"], r["season"]) for r in (
            _execute(client.table("team_rosters").select("team_id,season").eq("player_id", canonical["id"])).data or []
        )}
        stale_rosters = _execute(
            client.table("team_rosters").select("team_id,player_id,season").eq("player_id", stale["id"])
        ).data or []
        for row in stale_rosters:
            if (row["team_id"], row["season"]) in existing_rosters:
                _execute(
                    client.table("team_rosters").delete()
                    .eq("player_id", stale["id"])
                    .eq("team_id", row["team_id"])
                    .eq("season", row["season"])
                )
            else:
                _execute(
                    client.table("team_rosters")
                    .update({"player_id": canonical["id"]})
                    .eq("player_id", stale["id"])
                    .eq("team_id", row["team_id"])
                    .eq("season", row["season"])
                )

        _execute(client.table("players").delete().eq("id", stale["id"]))
        merged += 1

    logger.info("Name-merged %d stale player duplicate(s)", merged)


def main() -> None:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    client = create_client(url, key)

    logger.info("=== Pass 1: merge passport_id duplicates ===")
    merge_passport_dupes(client)

    logger.info("=== Pass 2: merge name-only duplicates ===")
    merge_name_dupes(client)

    logger.info("=== Pass 3: remove cross-circuit Adidas stats duplicates ===")
    dedup_adidas_cross_circuit(client, season=2026)

    logger.info("Done.")


if __name__ == "__main__":
    main()
