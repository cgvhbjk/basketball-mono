"""
Cerebro Widget — shared client for Nike boys leagues (EYBL + EYCL, 15U–17U).

Source
------
`https://cerebro-widget.vercel.app/api/trpc/<Router.Procedure>` — a tRPC
gateway used by the Nike EYBL stats widgets. The men's pipeline uses it
for both EYBL and EYCL boys: a single LeaguesList call enumerates all six
boys leagues by name, and every other endpoint addresses them by UUID.

Key procedures (GET, batched)
-----------------------------
    RouterCerebroLeagues.LeaguesList
        input: {overallId}                 → list of leagues with id, name, alias
    RouterCerebroTeams.TeamsList
        input: {overallId, leagueId?, page?, pageSize?}
                                            → all teams under the umbrella; each
                                              row carries its own league_id so
                                              we filter client-side
    RouterCerebroPlayers.PlayersList
        input: {overallId, leagueId?, teamId?, page?, pageSize?}
                                            → roster + per-game + per-40 + advanced stats
    RouterCerebroPlayer.PlayerRead
        input: {id}                         → single-player bio + season totals
    RouterCerebroPlayer.PlayerXEventsList
        input: {playerId}                   → per-session aggregates
    RouterCerebroPlayer.PlayerXGamesList
        input: {playerId}                   → per-game box score totals
    RouterCerebroEvents.EventsList
        input: {overallId, pageSize?}       → calendar (boys + girls + non-Nike)
    RouterCerebroGames.GamesList
        input: {overallId, eventId?}        → games for an event + scores +
                                              Google Drive PDF box score link

Boys filter
-----------
Cerebro hosts more than Nike boys data — events include girls sessions,
NCAA, and European leagues — so the adapter MUST filter:
- Events:  `event.gender != "F"`
- Leagues: `league.name` matches an `EYBL ...` / `EYCL ...` pattern.

Overall ID
----------
`overallId=260104` is Nike's umbrella identifier (covers EYBL + EYCL). It's
stable across sessions but env-overridable for safety.
"""
from __future__ import annotations
import json
import logging
import os
import re
import urllib.parse
from typing import Any, Optional

from .base_circuit import BaseCircuit
from ..models import BoxScore, Event, Game, Player, RosterEntry, SeasonStats, Team

logger = logging.getLogger(__name__)

CEREBRO_BASE = "https://cerebro-widget.vercel.app/api/trpc"
DEFAULT_OVERALL_ID = os.environ.get("CEREBRO_OVERALL_ID", "260104")


# ----------------------------------------------------------------
# tRPC client
# ----------------------------------------------------------------

def _trpc_input(payload: dict[str, Any]) -> str:
    """Encode a single-procedure tRPC input.

    Shape: input={"0":{"json": <payload>}}, URL-encoded.
    """
    wrapped = {"0": {"json": payload}}
    return urllib.parse.quote(json.dumps(wrapped, separators=(",", ":")), safe="")


async def _trpc_get(fetcher, procedure: str, payload: dict[str, Any]) -> Any:
    """
    Call a single tRPC procedure. Returns the unwrapped `result.data.json`
    payload, or None on shape mismatch.

    Goes through fetcher.fetch_json so retries, rate-limiting, and snapshots
    happen at the same layer as every other circuit.
    """
    url = f"{CEREBRO_BASE}/{procedure}?batch=1&input={_trpc_input(payload)}"
    data = await fetcher.fetch_json(url)
    if not isinstance(data, list) or not data:
        return None
    try:
        return data[0]["result"]["data"]["json"]
    except (KeyError, TypeError):
        logger.warning("Cerebro: unexpected response shape for %s: %r", procedure, data)
        return None


async def _paginate(
    fetcher, procedure: str, base_payload: dict[str, Any], list_key: str, page_size: int = 200
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = {**base_payload, "page": page, "pageSize": page_size}
        resp = await _trpc_get(fetcher, procedure, payload)
        if not isinstance(resp, dict):
            break
        items = resp.get(list_key) or []
        out.extend(items)
        pag = resp.get("pagination") or {}
        total_pages = int(pag.get("totalPages") or 0)
        if not items or page >= total_pages:
            break
        page += 1
    return out


# ----------------------------------------------------------------
# Adapter base
# ----------------------------------------------------------------

# Maps the pipeline's age_division to the Cerebro league-name suffix.
_DIVISION_TO_SUFFIX = {"15U": "15U", "16U": "16U", "17U": "17U"}


class CerebroLeagueScraper(BaseCircuit):
    """
    Base adapter for any league hosted under the same Cerebro overall id.
    Subclasses set `_LEAGUE_NAME_PREFIX` (e.g. "EYBL" or "EYCL") and the
    pipeline's `circuit_name`. Everything else is shared.
    """

    source_strategy = "json"
    _LEAGUE_NAME_PREFIX: str = ""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._overall_id = os.environ.get(
            f"{self.circuit_name.upper().replace(' ', '_')}_OVERALL_ID",
            DEFAULT_OVERALL_ID,
        )
        # Cached after first lookup.
        self._league_id: Optional[str] = None
        # Cached per-team rosters so fetch_stats doesn't re-paginate.
        self._roster_cache: dict[str, list[tuple[Player, RosterEntry, SeasonStats]]] = {}
        self._teams_cache: Optional[list[dict[str, Any]]] = None
        # Raw PlayerXGamesList records, keyed by player source_id. Populated
        # during _load_team_players when CEREBRO_AGGREGATE_PER_GAME != "0";
        # consumed by main.py for box_scores upserts.
        self._player_games_cache: dict[str, list[dict[str, Any]]] = {}

    # ----- league resolution -----

    async def _resolve_league_id(self) -> str:
        if self._league_id:
            return self._league_id
        # Allow an explicit override before hitting the network.
        env_key = f"{self.circuit_name.upper().replace(' ', '_')}_LEAGUE_ID"
        override = os.environ.get(env_key)
        if override:
            self._league_id = override
            return override

        resp = await _trpc_get(
            self.fetcher,
            "RouterCerebroLeagues.LeaguesList",
            {"overallId": self._overall_id},
        )
        leagues = (resp or {}).get("leagues") or []
        suffix = _DIVISION_TO_SUFFIX.get(self.age_division, self.age_division)
        wanted_name = f"{self._LEAGUE_NAME_PREFIX} {suffix}"  # eg. "EYBL 17U"
        for L in leagues:
            if (L.get("name") or "").strip().upper() == wanted_name.upper():
                self._league_id = L["id"]
                logger.info("Cerebro: resolved %s → leagueId=%s", wanted_name, self._league_id)
                return self._league_id
        names = [L.get("name") for L in leagues]
        raise RuntimeError(
            f"Cerebro: league {wanted_name!r} not found under overallId={self._overall_id}. "
            f"Available: {names}"
        )

    # ----- required per-team interface -----

    async def _fetch_teams_raw(self) -> list[dict[str, Any]]:
        if self._teams_cache is not None:
            return self._teams_cache
        league_id = await self._resolve_league_id()
        # TeamsList ignores leagueId server-side (returns everything under
        # the umbrella) — filter client-side by team.league_id.
        all_teams = await _paginate(
            self.fetcher,
            "RouterCerebroTeams.TeamsList",
            {"overallId": self._overall_id},
            list_key="teams",
        )
        self._teams_cache = [t for t in all_teams if (t.get("league_id") or "") == league_id]
        return self._teams_cache

    async def fetch_teams(self) -> list[Team]:
        raw = await self._fetch_teams_raw()
        teams: list[Team] = []
        for t in raw:
            name = (t.get("name") or "").strip()
            if not name:
                continue
            teams.append(Team(
                source_id=t["id"],
                name=name,
                age_division=self.age_division,
                season=self.season,
            ))
        logger.info("Cerebro %s: %d teams", self.circuit_name, len(teams))
        return teams

    async def _load_team_players(self, team_source_id: str) -> list[tuple[Player, RosterEntry, SeasonStats]]:
        if team_source_id in self._roster_cache:
            return self._roster_cache[team_source_id]
        league_id = await self._resolve_league_id()
        rows = await _paginate(
            self.fetcher,
            "RouterCerebroPlayers.PlayersList",
            {"overallId": self._overall_id, "leagueId": league_id, "teamId": team_source_id},
            list_key="players",
            page_size=99,  # widget's default — keeps responses small
        )
        parsed = [
            t for t in (_parse_player_row(r, self.season, self.age_division, team_source_id) for r in rows)
            if t is not None
        ]

        # Enrich SeasonStats with fga/fta/oreb by pulling per-game logs.
        # The raw per-game rows are also retained on the cache for
        # box-score ingestion in main.py.
        # Disable with CEREBRO_AGGREGATE_PER_GAME=0 if speed matters more than
        # shot-volume fields and box scores.
        if os.environ.get("CEREBRO_AGGREGATE_PER_GAME", "1") != "0":
            enriched: list[tuple[Player, RosterEntry, SeasonStats]] = []
            for player, roster_entry, stats in parsed:
                if not stats.games_played:
                    enriched.append((player, roster_entry, stats))
                    self._player_games_cache[player.source_id] = []
                    continue
                games, agg = await self._fetch_per_game(player.source_id)
                self._player_games_cache[player.source_id] = games
                update: dict[str, Optional[float]] = {
                    k: agg[k] for k in (
                        "fga", "fta", "oreb", "dreb",
                        "fpg", "fgm_pg", "ftm_pg",
                        "three_pm_pg", "three_pa_pg",
                    )
                    if agg.get(k) is not None
                }
                # mpg from per-game logs is more authoritative than the
                # PlayersList total_minutes/gp derivation when both exist.
                if agg.get("mpg") is not None:
                    update["mpg"] = agg["mpg"]
                if update:
                    stats = stats.model_copy(update=update)
                enriched.append((player, roster_entry, stats))
            parsed = enriched

        self._roster_cache[team_source_id] = parsed
        return parsed

    async def _fetch_per_game(
        self, player_source_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Optional[float]]]:
        """
        Call PlayerXGamesList once and return (raw_rows, season_averages).

        Raw rows feed box-score upserts; averages feed SeasonStats.
        """
        resp = await _trpc_get(
            self.fetcher,
            "RouterCerebroPlayer.PlayerXGamesList",
            {"playerId": player_source_id},
        )
        games = (resp or {}).get("playerGames") or []
        return games, aggregate_per_game_stats(games)

    def get_cached_player_games(self, player_source_id: str) -> list[dict[str, Any]]:
        """Return the raw per-game records pulled during _load_team_players (if any)."""
        return self._player_games_cache.get(player_source_id, [])

    async def get_player_box_scores(self, player_source_id: str) -> list[BoxScore]:
        """
        Return BoxScore models for this player. Uses cached PlayerXGamesList
        rows when available (the common path: main.py runs box-score ingestion
        after fetch_stats has already paginated the same data). Falls back to
        a direct fetch only if the cache is empty.
        """
        rows = self._player_games_cache.get(player_source_id)
        if rows is None:
            rows, _ = await self._fetch_per_game(player_source_id)
        out: list[BoxScore] = []
        for r in rows:
            box = parse_box_score(r, player_source_id)
            if box is not None:
                out.append(box)
        return out

    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]:
        entries = await self._load_team_players(team.source_id)
        return [(p, re) for p, re, _ in entries]

    async def fetch_stats(self, team: Team) -> list[SeasonStats]:
        entries = await self._load_team_players(team.source_id)
        return [s for _, _, s in entries]

    # ----- optional event / game / box-score interface -----

    async def list_events(self) -> list[Event]:
        league_id = await self._resolve_league_id()
        resp = await _trpc_get(
            self.fetcher,
            "RouterCerebroEvents.EventsList",
            {"overallId": self._overall_id, "pageSize": 500},
        )
        rows = (resp or {}).get("events") or []
        events: list[Event] = []
        # Match boys events that name this circuit's division — Cerebro tags
        # girls with "(Girls)" in the name and gender="F"; double-check both.
        # We also keep events that don't carry an explicit league link if their
        # name matches "<prefix> (<division>)".
        division_token = self.age_division.replace("U", "U)")  # "17U)"
        for r in rows:
            if (r.get("gender") or "").upper() == "F":
                continue
            name = r.get("name") or ""
            if self._LEAGUE_NAME_PREFIX.upper() not in name.upper():
                continue
            if division_token not in name and self.age_division not in name:
                continue
            events.append(Event(
                source_id=r["id"],
                circuit=self.circuit_name,
                name=name,
                location=r.get("location"),
                start_date=_parse_iso_date(r.get("startDate")),
                end_date=_parse_iso_date(r.get("endDate")),
            ))
        _ = league_id  # league_id is reserved for future per-league filtering
        return events

    async def list_games(self, event_source_id: str) -> list[Game]:
        resp = await _trpc_get(
            self.fetcher,
            "RouterCerebroGames.GamesList",
            {"overallId": self._overall_id, "eventId": event_source_id},
        )
        rows = (resp or {}).get("games") or []
        games: list[Game] = []
        for r in rows:
            games.append(Game(
                source_id=r["id"],
                source_event_id=r.get("event_id") or event_source_id,
                source_home_team_id=r.get("team_one_id"),
                source_away_team_id=r.get("team_two_id"),
                home_score=r.get("team_one_score"),
                away_score=r.get("team_two_score"),
                played_at=_parse_iso_datetime(r.get("game_date"), r.get("start_time")),
                status="final" if r.get("team_one_score") is not None else None,
            ))
        return games

    async def get_box_score(self, game_source_id: str) -> list[BoxScore]:
        # Cerebro's per-game box score lives on the player; the game endpoint
        # itself only returns a Google-Drive PDF link. The pipeline already
        # exposes per-game data via PlayerXGamesList — surface it here too.
        # NOTE: this path is intentionally NOT a player-iteration loop because
        # that would be O(roster). Box-score backfill jobs should walk
        # PlayerXGamesList for each player as part of a dedicated task.
        logger.info(
            "Cerebro: get_box_score(%s) — no native per-game endpoint. Use "
            "PlayerXGamesList per player (see _load_player_games).", game_source_id,
        )
        return []

    async def _load_player_games(self, player_source_id: str) -> list[BoxScore]:
        """Convenience for backfill jobs — per-game box scores for one player."""
        resp = await _trpc_get(
            self.fetcher,
            "RouterCerebroPlayer.PlayerXGamesList",
            {"playerId": player_source_id},
        )
        rows = (resp or {}).get("playerGames") or []
        out: list[BoxScore] = []
        for r in rows:
            out.append(BoxScore(
                source_game_id=r.get("game_id"),
                source_player_id=player_source_id,
                source_team_id=r.get("team_id"),
                minutes=_to_float(r.get("minutes")),
                points=_to_int(r.get("pts")),
                rebounds=_to_int(r.get("reb")),
                offensive_rebounds=_to_int(r.get("orb")),
                assists=_to_int(r.get("ast")),
                steals=_to_int(r.get("stl")),
                blocks=_to_int(r.get("blk")),
                turnovers=_to_int(r.get("tov")),
                fouls=_to_int(r.get("pf")),
                fgm=_to_int(r.get("fgm")),
                fga=_to_int(r.get("fga")),
                three_pm=_to_int(r.get("three_pm")),
                three_pa=_to_int(r.get("three_pa")),
                ftm=_to_int(r.get("ftm")),
                fta=_to_int(r.get("fta")),
            ))
        return out


# ----------------------------------------------------------------
# Parsers (exposed for tests)
# ----------------------------------------------------------------

def _to_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(v: Any):
    if not v:
        return None
    from datetime import date
    try:
        parsed = date.fromisoformat(str(v)[:10])
    except ValueError:
        return None
    # Cerebro stores 1900-01-01 as a "DOB unknown" sentinel. Treat as None
    # so we don't flood the DB with players "born in 1900". Any pre-1990
    # date for a recruit is implausible by the same logic.
    if parsed.year < 1990:
        return None
    return parsed


def _parse_iso_datetime(d: Any, t: Any):
    if not d:
        return None
    from datetime import datetime
    ds = str(d)[:10]
    ts = str(t)[:8] if t else "00:00:00"
    try:
        return datetime.fromisoformat(f"{ds}T{ts}")
    except ValueError:
        return None


def _split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split(None, 1)
    return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "")


def parse_player_row(
    row: dict[str, Any], season: int, age_division: str, team_source_id: Optional[str] = None
) -> Optional[tuple[Player, RosterEntry, SeasonStats]]:
    """Public wrapper for tests."""
    return _parse_player_row(row, season, age_division, team_source_id)


def _parse_player_row(
    row: dict[str, Any], season: int, age_division: str, team_source_id: Optional[str]
) -> Optional[tuple[Player, RosterEntry, SeasonStats]]:
    pid = row.get("id") or row.get("playerId")
    if not pid:
        return None
    first, last = _split_name(row.get("name") or "")
    if not first and not last:
        return None
    tid = team_source_id or row.get("teamId")
    if not tid:
        return None

    height = row.get("heightInches")
    if isinstance(height, (int, float)) and not (48 <= height <= 108):
        height = None

    raw_pos = row.get("position")
    position = None if (not raw_pos or raw_pos == "Unknown Position") else raw_pos

    player = Player(
        source_id=str(pid),
        first_name=first,
        last_name=last,
        height_inches=int(height) if height else None,
        weight_lbs=_to_int(row.get("weightLb")),
        position=position,
        hometown=row.get("hometown"),
        high_school=row.get("highSchool"),
        date_of_birth=_parse_iso_date(row.get("dateOfBirth")),
        nationality=row.get("nationality") or None,
    )
    roster_entry = RosterEntry(
        source_team_id=str(tid),
        source_player_id=str(pid),
        position=position,
    )
    gp = _to_int(row.get("games_played"))
    if not gp:
        # Roster row with no games yet — keep the player but skip stats.
        stats_obj = SeasonStats(
            source_player_id=str(pid),
            source_team_id=str(tid),
            season=season,
            age_division=age_division,
        )
    else:
        # mpg is derivable from PlayersList: total_minutes / games_played.
        # fga / fta / oreb are NOT in PlayersList — they get filled in later
        # by _aggregate_per_game_stats from PlayerXGamesList (when enabled).
        total_minutes = _to_float(row.get("total_minutes"))
        mpg = (total_minutes / gp) if (total_minutes is not None and gp) else None
        stats_obj = SeasonStats(
            source_player_id=str(pid),
            source_team_id=str(tid),
            season=season,
            age_division=age_division,
            games_played=gp,
            ppg=_to_float(row.get("pts_per_game")),
            rpg=_to_float(row.get("reb_per_game")),
            apg=_to_float(row.get("ast_per_game")),
            spg=_to_float(row.get("stl_per_game")),
            bpg=_to_float(row.get("blk_per_game")),
            tpg=_to_float(row.get("tov_per_game")),
            fg_pct=_to_float(row.get("fg_pct")),
            three_pt_pct=_to_float(row.get("three_pt_pct")),
            ft_pct=_to_float(row.get("ft_pct")),
            mpg=mpg,
        )
    return player, roster_entry, stats_obj


def parse_box_score(
    rec: dict[str, Any], player_source_id: str
) -> Optional[BoxScore]:
    """
    Convert a single PlayerXGamesList record into a BoxScore.

    Returns None if the record lacks a game_id (can't be joined back to a game
    row, so unusable).
    """
    game_id = rec.get("game_id")
    if not game_id:
        return None
    team_id = rec.get("team_id")
    if not team_id:
        return None
    return BoxScore(
        source_game_id=str(game_id),
        source_player_id=str(player_source_id),
        source_team_id=str(team_id),
        minutes=_to_float(rec.get("minutes")),
        points=_to_int(rec.get("pts")),
        rebounds=_to_int(rec.get("reb")),
        offensive_rebounds=_to_int(rec.get("orb")),
        defensive_rebounds=_to_int(rec.get("drb")),
        assists=_to_int(rec.get("ast")),
        steals=_to_int(rec.get("stl")),
        blocks=_to_int(rec.get("blk")),
        turnovers=_to_int(rec.get("tov")),
        fouls=_to_int(rec.get("pf")),
        fgm=_to_int(rec.get("fgm")),
        fga=_to_int(rec.get("fga")),
        three_pm=_to_int(rec.get("three_pm")),
        three_pa=_to_int(rec.get("three_pa")),
        ftm=_to_int(rec.get("ftm")),
        fta=_to_int(rec.get("fta")),
    )


_PER_GAME_RAW_FIELDS = ("fga", "fta", "orb", "drb", "minutes", "pf", "fgm", "ftm", "three_pm", "three_pa")
_PER_GAME_OUT_KEYS = {
    "fga": "fga", "fta": "fta", "orb": "oreb", "drb": "dreb",
    "minutes": "mpg", "pf": "fpg", "fgm": "fgm_pg", "ftm": "ftm_pg",
    "three_pm": "three_pm_pg", "three_pa": "three_pa_pg",
}


def aggregate_per_game_stats(player_games: list[dict[str, Any]]) -> dict[str, Optional[float]]:
    """
    Reduce a player's per-game records (PlayerXGamesList) to season per-game
    averages for every counting stat the source exposes per-game but the
    PlayersList aggregate endpoint does not.

    Returned keys: fga, fta, oreb, dreb, mpg, fpg, fgm_pg, ftm_pg,
    three_pm_pg, three_pa_pg. Missing source fields → None.
    """
    out: dict[str, Optional[float]] = {v: None for v in _PER_GAME_OUT_KEYS.values()}
    if not player_games:
        return out
    sums = {k: 0.0 for k in _PER_GAME_RAW_FIELDS}
    counts = {k: 0 for k in _PER_GAME_RAW_FIELDS}
    for g in player_games:
        for k in _PER_GAME_RAW_FIELDS:
            v = g.get(k)
            if v is not None:
                sums[k] += float(v)
                counts[k] += 1
    # Average each field over the games that actually report it, not over the
    # full game count. Dividing by every game would treat a missing (unreported)
    # field as a recorded zero — understating derived per-game rates like mpg and
    # in turn inflating the dashboard's per-40 conversion (stat / mpg × 40).
    for raw_key, out_key in _PER_GAME_OUT_KEYS.items():
        out[out_key] = (sums[raw_key] / counts[raw_key]) if counts[raw_key] else None
    return out
