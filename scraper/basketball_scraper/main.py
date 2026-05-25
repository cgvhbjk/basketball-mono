"""
Entry point: python -m basketball_scraper.main

Reads CIRCUIT, SEASON, AGE_DIVISION from .env, dispatches to the correct
circuit scraper, then orchestrates teams → rosters → stats → upsert.
"""
import asyncio
import logging
from supabase import create_client

from .config import settings
from .base_fetcher import EmptyPageError
from .httpx_fetcher import HttpxFetcher
from .playwright_fetcher import PlaywrightFetcher
from .upsert import get_circuit_id, get_or_create_team, get_or_create_player, upsert_rows, patch_player_bio_nulls
from .circuits.eybl import EYBLScraper
from .circuits.eycl import EYCLScraper
from .circuits.adidas_3ssb import Adidas3SSBScraper
from .circuits.adidas_gold import AdidasGoldScraper
from .circuits.uaa import UAAScraper
from .circuits.uaa_rise import UAARiseScraper
from .circuits.puma import PUMAScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REGISTRY = {
    "eybl":        EYBLScraper,
    "eycl":        EYCLScraper,
    "3ssb":        Adidas3SSBScraper,
    "adidas_gold": AdidasGoldScraper,
    "uaa":         UAAScraper,
    "uaa_rise":    UAARiseScraper,
    "puma":        PUMAScraper,
}


async def main() -> None:
    circuit_key = settings.circuit
    if circuit_key not in REGISTRY:
        raise ValueError(f"Unknown circuit '{circuit_key}'. Choose from: {list(REGISTRY)}")

    supabase = create_client(settings.supabase_url, settings.supabase_service_key)

    # Probe with httpx first; fall back to Playwright if the page is a JS shell
    if settings.use_playwright:
        fetcher = PlaywrightFetcher()
        logger.info("USE_PLAYWRIGHT=true — using Playwright for all requests")
    else:
        fetcher = HttpxFetcher()
        logger.info("Trying httpx fetcher first (Playwright fallback enabled)")

    circuit_id_db = get_circuit_id(supabase, REGISTRY[circuit_key].circuit_name)

    scraper = REGISTRY[circuit_key](fetcher, supabase, settings.season, settings.age_division)

    try:
        # ---- Teams ----
        try:
            teams = await scraper.fetch_teams()
        except EmptyPageError as e:
            if settings.use_playwright:
                raise
            logger.warning("httpx returned empty page — switching to Playwright. %s", e)
            await fetcher.close()
            fetcher = PlaywrightFetcher()
            scraper.fetcher = fetcher
            teams = await scraper.fetch_teams()

        # Map source_id → db team UUID
        team_id_map: dict[str, str] = {}
        for team in teams:
            team_row = {
                "circuit_id": circuit_id_db,
                "name": team.name,
                "city": team.city,
                "state": team.state,
                "age_division": team.age_division,
                "season": team.season,
            }
            db_id = get_or_create_team(supabase, team_row)
            team_id_map[team.source_id] = db_id

        # ---- Rosters + Players ----
        player_id_map: dict[str, str] = {}
        roster_rows: list[dict] = []

        for team in teams:
            entries = await scraper.fetch_roster(team)
            for player, roster_entry in entries:
                player_row = {
                    "first_name": player.first_name,
                    "last_name": player.last_name,
                    "height_inches": player.height_inches,
                    "weight_lbs": player.weight_lbs,
                    "grad_year": player.grad_year,
                    "hometown": player.hometown,
                    "high_school": player.high_school,
                    "position": player.position,
                    # Store Passport ID for 3SSB players so we can enrich from the-passport.com
                    "passport_id": player.source_id if REGISTRY[circuit_key].circuit_name == "3SSB" else None,
                }
                db_player_id = get_or_create_player(supabase, player_row)
                player_id_map[player.source_id] = db_player_id

                db_team_id = team_id_map.get(roster_entry.source_team_id)
                if db_team_id:
                    roster_rows.append({
                        "team_id": db_team_id,
                        "player_id": db_player_id,
                        "season": settings.season,
                        "jersey_number": roster_entry.jersey_number,
                        "position": roster_entry.position,
                    })

        roster_by_key = {
            (r["team_id"], r["player_id"], r["season"]): r for r in roster_rows
        }
        deduped_roster_rows = list(roster_by_key.values())
        logger.info("Roster rows before dedup: %d, after: %d", len(roster_rows), len(deduped_roster_rows))
        upsert_rows(supabase, "team_rosters", deduped_roster_rows, "team_id,player_id,season")

        # ---- Stats ----
        stats_rows: list[dict] = []
        for team in teams:
            raw_stats = await scraper.fetch_stats(team)
            for s in raw_stats:
                db_player_id = player_id_map.get(s.source_player_id)
                db_team_id = team_id_map.get(s.source_team_id)
                if not db_player_id or not db_team_id:
                    continue
                stats_rows.append({
                    "player_id": db_player_id,
                    "team_id": db_team_id,
                    "season": s.season,
                    "age_division": s.age_division,
                    "games_played": s.games_played,
                    "ppg": s.ppg,
                    "rpg": s.rpg,
                    "apg": s.apg,
                    "spg": s.spg,
                    "bpg": s.bpg,
                    "fg_pct": s.fg_pct,
                    "three_pt_pct": s.three_pt_pct,
                })

        stats_by_key = {
            (r["player_id"], r["team_id"], r["season"]): r for r in stats_rows
        }
        deduped_stats_rows = list(stats_by_key.values())
        logger.info("Stat rows before dedup: %d, after: %d", len(stats_rows), len(deduped_stats_rows))
        upsert_rows(supabase, "player_season_stats", deduped_stats_rows, "player_id,team_id,season")

        # Bio-sync: flush bio fields enriched during fetch_stats back to the DB.
        # Some circuits (e.g. EYBL) only have per-player bio on individual stat pages
        # that are fetched after the roster upsert, so Player objects are mutated
        # in-place during fetch_stats but the original player_row dicts are already gone.
        # This pass uses the cached (now-enriched) Player objects + player_id_map to patch
        # only null DB columns.
        bio_synced = 0
        for team in teams:
            for player, _ in await scraper.fetch_roster(team):
                db_id = player_id_map.get(player.source_id)
                if db_id is None:
                    continue
                bio = {
                    k: getattr(player, k)
                    for k in ("height_inches", "position", "grad_year", "high_school", "hometown")
                    if getattr(player, k) is not None
                }
                if bio:
                    patch_player_bio_nulls(supabase, db_id, bio)
                    bio_synced += 1
        logger.info("Bio sync: %d players checked", bio_synced)

        logger.info("Done. Teams: %d | Roster entries: %d | Stat rows: %d",
                    len(teams), len(deduped_roster_rows), len(deduped_stats_rows))

    finally:
        await fetcher.close()


if __name__ == "__main__":
    asyncio.run(main())
