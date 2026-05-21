#!/usr/bin/env python3
"""
Enrich player profiles from 247Sports.

Usage:
  python enrich_players.py [--limit N] [--dry-run] [--clean-bad]

  --limit N     Max number of players to process (default 50)
  --dry-run     Print what would be updated without writing to the DB
  --clean-bad   Delete players with single-character first or last name
                before running enrichment (fixes the "c, s" corruption)
"""
import asyncio
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from supabase import create_client
from basketball_scraper.config import settings
from basketball_scraper.enrich_247 import lookup_player_profile, REQUEST_DELAY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def clean_bad_players(supabase) -> int:
    """Delete players with implausibly short names (scraper artifacts)."""
    result = (
        supabase.table("players")
        .select("id, first_name, last_name")
        .execute()
    )
    bad_ids = [
        r["id"]
        for r in (result.data or [])
        if len(r["first_name"]) < 2 or (r["last_name"] and len(r["last_name"]) < 2)
    ]
    if not bad_ids:
        logger.info("No bad player records found")
        return 0

    logger.info("Deleting %d bad player records: %s", len(bad_ids), bad_ids)
    for pid in bad_ids:
        supabase.table("player_season_stats").delete().eq("player_id", pid).execute()
        supabase.table("team_rosters").delete().eq("player_id", pid).execute()
        supabase.table("players").delete().eq("id", pid).execute()
    return len(bad_ids)


async def main(limit: int, dry_run: bool, clean_bad: bool) -> None:
    supabase = create_client(settings.supabase_url, settings.supabase_service_key)

    if clean_bad:
        deleted = clean_bad_players(supabase)
        logger.info("Cleaned %d bad records%s", deleted, " (dry-run skipped)" if dry_run else "")
        if dry_run:
            return

    # Fetch players missing profile data (height as the primary signal)
    result = (
        supabase.table("players")
        .select("id, first_name, last_name, height_inches, grad_year, high_school")
        .is_("height_inches", "null")
        .order("last_name")
        .limit(limit)
        .execute()
    )
    players = result.data or []
    logger.info("Found %d players to enrich", len(players))

    updated = skipped = not_found = 0

    for i, player in enumerate(players, 1):
        pid = player["id"]
        first = player["first_name"]
        last = player["last_name"]

        logger.info("[%d/%d] Looking up %s %s ...", i, len(players), first, last)

        profile = await lookup_player_profile(first, last)

        if profile is None:
            not_found += 1
            logger.info("  → request failed (skipping)")
        else:
            patch: dict = {}
            if profile.height_inches and not player["height_inches"]:
                patch["height_inches"] = profile.height_inches
            if profile.grad_year and not player["grad_year"]:
                patch["grad_year"] = profile.grad_year
            if profile.high_school and not player["high_school"]:
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
        "Done. Updated: %d | No new data: %d | Not found: %d%s",
        updated, skipped, not_found,
        " (dry-run — no writes)" if dry_run else "",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich player profiles from 247Sports")
    parser.add_argument("--limit", type=int, default=50, help="Max players to process")
    parser.add_argument("--dry-run", action="store_true", help="Print results without updating DB")
    parser.add_argument("--clean-bad", action="store_true", help="Delete corrupt player records first")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.dry_run, args.clean_bad))
