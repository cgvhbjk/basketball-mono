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
from .base_fetcher import EmptyPageError, BlockedError
from .httpx_fetcher import HttpxFetcher
from .playwright_fetcher import PlaywrightFetcher
from .snapshots import Snapshotter
from .upsert import (
    get_circuit_id,
    get_or_create_event,
    get_or_create_player,
    get_or_create_team,
    patch_player_bio_nulls,
    upsert_box_scores,
    upsert_games,
    upsert_rows,
)
from .circuits.eybl import EYBLScraper
from .circuits.eycl import EYCLScraper
from .circuits.adidas_3ssb import Adidas3SSBScraper
from .circuits.adidas_gold import AdidasGoldScraper
from .circuits.uaa import UAAScraper
from .circuits.uaa_rise import UAARiseScraper
from .circuits.hoop_group import HoopGroupScraper
from .circuits.made_hoops import MadeHoopsScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REGISTRY = {
    "eybl":        EYBLScraper,
    "eycl":        EYCLScraper,
    "3ssb":        Adidas3SSBScraper,
    "adidas_gold": AdidasGoldScraper,
    "uaa":         UAAScraper,
    "uaa_rise":    UAARiseScraper,
    # Scaffolded adapters — implementations pending source discovery.
    "hoop_group":  HoopGroupScraper,
    "made_hoops":  MadeHoopsScraper,
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

    # Snapshotter captures every fetched HTML/JSON body keyed by adapter name +
    # sha256 so we can replay parsers against historical data even after a
    # source changes its layout.
    snapshotter = Snapshotter() if settings.enable_snapshots else None

    if settings.use_playwright:
        fetcher = PlaywrightFetcher(snapshotter=snapshotter, adapter_name=circuit_key)
        logger.info("USE_PLAYWRIGHT=true — using Playwright for all requests")
    else:
        fetcher = HttpxFetcher(snapshotter=snapshotter, adapter_name=circuit_key)
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
            fetcher = PlaywrightFetcher(snapshotter=snapshotter, adapter_name=circuit_key)
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
                "wins": team.wins,
                "losses": team.losses,
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
            try:
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
                        "date_of_birth": player.date_of_birth.isoformat() if player.date_of_birth else None,
                        "nationality": player.nationality,
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
                        "ft_pct": s.ft_pct,
                        "fga": s.fga,
                        "oreb": s.oreb,
                        "dreb": s.dreb,
                        "tpg": s.tpg,
                        "fta": s.fta,
                        "mpg": s.mpg,
                        "fpg": s.fpg,
                        "three_pm_pg": s.three_pm_pg,
                        "three_pa_pg": s.three_pa_pg,
                        "fgm_pg": s.fgm_pg,
                        "ftm_pg": s.ftm_pg,
                        "plus_minus": s.plus_minus,
                        "events_played": s.events_played,
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
            except BlockedError:
                # CDN/Incapsula blocks are circuit-wide — let the outer handler abort.
                raise
            except Exception as exc:
                # Isolate per-team failures (bad parse, transient HTTP error,
                # one Pydantic ValidationError) so the rest of the circuit still
                # runs. The team stays out of the checkpoint so a retry picks it up.
                logger.exception("Team %s (%s) failed — skipping: %s", team.name, team.source_id, exc)
                continue

        # ---- Optional: events / games / box scores ----
        # Adapters that don't expose schedule data return empty lists, so this
        # whole pass is a no-op for them. Skipped on Adidas, UAA, Prep Hoops
        # (Prep Hoops will be wired in a follow-up since it carries games but
        # not box scores).
        event_count = game_count = box_count = 0
        try:
            events = await scraper.list_events()
        except Exception as exc:
            logger.warning("list_events() failed for %s: %s — skipping schedule pass", circuit_key, exc)
            events = []

        if events:
            event_db_ids: dict[str, str] = {}
            for ev in events:
                ev_row = {
                    "circuit_id": circuit_id_db,
                    "name": ev.name,
                    "season": settings.season,
                    "location": ev.location,
                    "start_date": ev.start_date.isoformat() if ev.start_date else None,
                    "end_date": ev.end_date.isoformat() if ev.end_date else None,
                }
                event_db_ids[ev.source_id] = get_or_create_event(supabase, ev_row)
            event_count = len(event_db_ids)
            logger.info("Upserted %d events", event_count)

            game_db_ids: dict[str, str] = {}
            for ev_source_id, ev_db_id in event_db_ids.items():
                games = await scraper.list_games(ev_source_id)
                rows: list[dict] = []
                for g in games:
                    rows.append({
                        "source_marker": g.source_id,
                        "event_id": ev_db_id,
                        "home_team_id": team_id_map.get(g.source_home_team_id) if g.source_home_team_id else None,
                        "away_team_id": team_id_map.get(g.source_away_team_id) if g.source_away_team_id else None,
                        "played_at": g.played_at.isoformat() if g.played_at else None,
                        "home_score": g.home_score,
                        "away_score": g.away_score,
                        "status": g.status,
                    })
                # Skip rows where neither team resolves — box scores can't FK them.
                rows = [r for r in rows if r["home_team_id"] or r["away_team_id"]]
                game_db_ids.update(upsert_games(supabase, rows))
            game_count = len(game_db_ids)

            # Per-player box scores. Cerebro pulls these from cache (no extra
            # network calls); other adapters with get_player_box_scores
            # implementations will fetch fresh.
            box_rows: list[dict] = []
            for player_source_id, db_player_id in player_id_map.items():
                try:
                    boxes = await scraper.get_player_box_scores(player_source_id)
                except Exception as exc:
                    logger.warning("get_player_box_scores(%s) failed: %s", player_source_id, exc)
                    continue
                for b in boxes:
                    db_game_id = game_db_ids.get(b.source_game_id)
                    db_team_id = team_id_map.get(b.source_team_id)
                    if not db_game_id or not db_team_id:
                        continue
                    box_rows.append({
                        "game_id": db_game_id,
                        "player_id": db_player_id,
                        "team_id": db_team_id,
                        "minutes": b.minutes,
                        "points": b.points,
                        "rebounds": b.rebounds,
                        "offensive_rebounds": b.offensive_rebounds,
                        "defensive_rebounds": b.defensive_rebounds,
                        "assists": b.assists,
                        "steals": b.steals,
                        "blocks": b.blocks,
                        "turnovers": b.turnovers,
                        "fouls": b.fouls,
                        "fgm": b.fgm,
                        "fga": b.fga,
                        "three_pm": b.three_pm,
                        "three_pa": b.three_pa,
                        "ftm": b.ftm,
                        "fta": b.fta,
                    })
            upsert_box_scores(supabase, box_rows)
            box_count = len(box_rows)

        logger.info(
            "Done. Teams: %d | Roster entries: %d | Stat rows: %d | Events: %d | Games: %d | Box scores: %d",
            len(teams), total_roster, total_stats, event_count, game_count, box_count,
        )

        # Clear checkpoint on clean completion
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)

    except BlockedError as e:
        logger.error("Circuit blocked (CDN/Incapsula): %s — aborting circuit run", e)
        raise
    finally:
        await fetcher.close()
        # Keep the snapshot dir under its size cap so it doesn't grow without
        # bound across many runs. No-op when snapshots are disabled or the
        # cap is set to 0.
        if snapshotter is not None:
            snapshotter.prune()


if __name__ == "__main__":
    asyncio.run(main())
