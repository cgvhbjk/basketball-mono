"""
Adapter contract that every circuit implements.

Backwards-compatible: only `fetch_teams`, `fetch_roster`, and `fetch_stats`
are required (those are the existing per-circuit obligations). The other
methods — events / games / box scores — are optional hooks. Adapters that
expose schedule data override them; adapters that only have aggregate
season stats inherit the default no-ops.

Putting parsing inside the adapter (and ONLY inside the adapter) is the rule:
the orchestration in `main.py` should only see normalized models, never raw
HTML/JSON. New circuits should fit by adding a single adapter file.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from supabase import Client

from ..base_fetcher import BaseFetcher
from ..models import BoxScore, Event, Game, Player, RosterEntry, SeasonStats, Team


class BaseCircuit(ABC):
    """
    All circuit adapters share this interface. Subclasses MUST set
    `circuit_name` (and ideally `circuit_org`); both are surfaced in logs
    and used to look up the circuits row in Supabase.
    """

    circuit_name: str  # must match the `name` column in the circuits table
    circuit_org: str = "unknown"
    # The men's pipeline is boys-only — there is no gender field anywhere.

    # Source-strategy declaration. Adapters set this so `main.py` can log a
    # one-line summary of how the data was obtained. Values: "json", "html",
    # "playwright", "hybrid".
    source_strategy: str = "html"

    def __init__(self, fetcher: BaseFetcher, supabase: Client, season: int, age_division: str) -> None:
        self.fetcher = fetcher.with_adapter(self.circuit_name)
        self.supabase = supabase
        self.season = season
        self.age_division = age_division

    # ------------------------------------------------------------------
    # Required: per-team scrape (the existing pipeline)
    # ------------------------------------------------------------------

    @abstractmethod
    async def fetch_teams(self) -> list[Team]:
        """Return all teams for this circuit/season."""

    @abstractmethod
    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]:
        """Return players + their roster entry for the given team."""

    @abstractmethod
    async def fetch_stats(self, team: Team) -> list[SeasonStats]:
        """Return season stats for all players on the given team."""

    # ------------------------------------------------------------------
    # Optional: event / game / box-score scrape
    #
    # Default no-ops so adapters can opt into schedule ingestion only when
    # the source actually exposes it. main.py checks for non-empty returns.
    # ------------------------------------------------------------------

    async def list_events(self) -> list[Event]:
        return []

    async def get_event(self, event_source_id: str) -> Event | None:
        return None

    async def list_games(self, event_source_id: str) -> list[Game]:
        return []

    async def get_game(self, game_source_id: str) -> Game | None:
        return None

    async def get_box_score(self, game_source_id: str) -> list[BoxScore]:
        return []

    async def get_player_box_scores(self, player_source_id: str) -> list[BoxScore]:
        """
        Return per-game box scores for a single player. Default no-op.

        Cerebro-backed circuits override this. Other adapters skip box-score
        ingestion entirely (main.py treats `[]` as "this adapter has nothing").
        """
        return []

    async def run(self) -> None:
        """Orchestration is centralized in main.py — subclasses don't override this."""
        raise NotImplementedError(
            f"{self.__class__.__name__}.run() is not implemented. "
            "See main.py for the full orchestration loop."
        )
