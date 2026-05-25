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
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from supabase import create_client
from basketball_scraper.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def clean_bad_players(supabase) -> int:
    """Delete players with implausibly short names (scraper artifacts)."""
    result = supabase.table("players").select("id, first_name, last_name").execute()
    bad_ids = [
        r["id"]
        for r in (result.data or [])
        if len(r["first_name"]) < 2 or (r["last_name"] and len(r["last_name"]) < 2)
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
    from basketball_scraper.enrich_on3 import lookup_player_profile, REQUEST_DELAY

    result = (
        supabase.table("players")
        .select("id, first_name, last_name, height_inches, grad_year, high_school, national_rank")
        .or_("national_rank.is.null,height_inches.is.null")
        .order("last_name")
        .limit(limit)
        .execute()
    )
    players = result.data or []
    logger.info("Found %d players to enrich via On3", len(players))

    updated = skipped = not_found = 0
    for i, player in enumerate(players, 1):
        pid = player["id"]
        first, last = player["first_name"], player["last_name"]
        logger.info("[%d/%d] Looking up %s %s on On3...", i, len(players), first, last)

        profile = await lookup_player_profile(first, last)
        if profile is None:
            not_found += 1
            logger.info("  → not found")
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

        if i < len(players):
            await asyncio.sleep(REQUEST_DELAY)

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
            if profile.height_inches and not player["height_inches"]:
                patch["height_inches"] = profile.height_inches
            if profile.position and not player["position"]:
                patch["position"] = profile.position
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
