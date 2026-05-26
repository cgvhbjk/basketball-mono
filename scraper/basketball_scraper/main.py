"""
Entry point: python -m basketball_scraper.main

Reads CIRCUIT, SEASON, AGE_DIVISION from .env, dispatches to the correct
circuit scraper, then orchestrates teams → rosters → stats → upsert.

A checkpoint file (.checkpoint_<circuit>_<season>_<division>.json) is written
after each team completes so the run can resume after a crash without
re-scraping already-processed teams.
"""
import asyncio
import json
import logging
import os
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

_CHECKPOINT_DIR = os.path.dirname(os.path.dirname(__file__))


def _checkpoint_path(circuit: str, season: int, division: str) -> str:
    return os.path.join(_CHECKPOINT_DIR, f".checkpoint_{circuit}_{season}_{division}.json")


def _load_checkpoint(path: str) -> set[str]:
    try:
        with open(path) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_checkpoint(path: str, done: set[str]) -> None:
    with open(path, "w") as f:
        json.dump(list(done), f)


async def main() -> None:
    circuit_key = settings.circuit
    if circuit_key not in REGISTRY:
        raise ValueError(f"Unknown circuit '{circuit_key}'. Choose from: {list(REGISTRY)}")

    supabase = create_client(settings.supabase_url, settings.supabase_service_key)

    if settings.use_playwright:
        fetcher = PlaywrightFetcher()
        logger.info("USE_PLAYWRIGHT=true — using Playwright for all requests")
    else:
        fetcher = HttpxFetcher()
        logger.info("Trying httpx fetcher first (Playwright fallback enabled)")

    circuit_id_db = get_circuit_id(supabase, REGISTRY[circuit_key].circuit_name)
    scraper = REGISTRY[circuit_key](fetcher, supabase, settings.season, settings.age_division)

    checkpoint_path = _checkpoint_path(circuit_key, settings.season, settings.age_division)
    done_team_ids: set[str] = _load_checkpoint(checkpoint_path)
    if done_team_ids:
        logger.info("Resuming from checkpoint — %d teams already done", len(done_team_ids))

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
            team_id_map[team.source_id] = get_or_create_team(supabase, team_row)

        # ---- Per-team: roster → players → stats → bio-sync ----
        player_id_map: dict[str, str] = {}
        total_roster = total_stats = 0
        # Both Adidas circuits share the-passport.com IDs; store them so
        # get_or_create_player can merge by passport_id across circuits.
        store_passport = REGISTRY[circuit_key].circuit_org == "Adidas"

        for i, team in enumerate(teams, 1):
            if team.source_id in done_team_ids:
                logger.info("[%d/%d] Skipping %s (checkpoint)", i, len(teams), team.name)
                continue

            logger.info("[%d/%d] Processing %s", i, len(teams), team.name)
            db_team_id = team_id_map[team.source_id]

            # Roster + players
            entries = await scraper.fetch_roster(team)
            roster_rows = []
            team_players = []  # (Player, db_player_id) — reused for bio-sync after fetch_stats

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
                    "passport_id": player.source_id if store_passport else None,
                }
                db_player_id = get_or_create_player(supabase, player_row)
                player_id_map[player.source_id] = db_player_id
                team_players.append((player, db_player_id))

                if db_team_id:
                    roster_rows.append({
                        "team_id": db_team_id,
                        "player_id": db_player_id,
                        "season": settings.season,
                        "jersey_number": roster_entry.jersey_number,
                        "position": roster_entry.position,
                    })

            deduped_roster = list(
                {(r["team_id"], r["player_id"], r["season"]): r for r in roster_rows}.values()
            )
            upsert_rows(supabase, "team_rosters", deduped_roster, "team_id,player_id,season")
            total_roster += len(deduped_roster)

            # Stats — fetch_stats may enrich Player objects in-place (e.g. EYBL)
            raw_stats = await scraper.fetch_stats(team)
            stats_rows = []
            for s in raw_stats:
                db_player_id = player_id_map.get(s.source_player_id)
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

            deduped_stats = list(
                {(r["player_id"], r["team_id"], r["season"]): r for r in stats_rows}.values()
            )
            upsert_rows(supabase, "player_season_stats", deduped_stats, "player_id,team_id,season")
            total_stats += len(deduped_stats)

            # Bio-sync: flush fields enriched during fetch_stats (uses already-fetched Player objects)
            for player, db_id in team_players:
                bio = {
                    k: getattr(player, k)
                    for k in ("height_inches", "position", "grad_year", "high_school", "hometown")
                    if getattr(player, k) is not None
                }
                if bio:
                    patch_player_bio_nulls(supabase, db_id, bio)

            done_team_ids.add(team.source_id)
            _save_checkpoint(checkpoint_path, done_team_ids)
            logger.info("Checkpoint: %d/%d teams done", len(done_team_ids), len(teams))

        logger.info("Done. Teams: %d | Roster entries: %d | Stat rows: %d",
                    len(teams), total_roster, total_stats)

        # Clear checkpoint on clean completion
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    finally:
        await fetcher.close()


if __name__ == "__main__":
    asyncio.run(main())
