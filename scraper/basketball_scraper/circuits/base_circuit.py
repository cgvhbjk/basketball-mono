from abc import ABC, abstractmethod
from supabase import Client
from ..base_fetcher import BaseFetcher
from ..models import Team, Player, RosterEntry, SeasonStats


class BaseCircuit(ABC):
    """
    Interface every circuit scraper must implement.
    Subclasses receive a fetcher (httpx or Playwright) and a Supabase client.
    """

    circuit_name: str  # must match the `name` column in the circuits table
    circuit_org: str
    circuit_gender: str

    def __init__(self, fetcher: BaseFetcher, supabase: Client, season: int, age_division: str) -> None:
        self.fetcher = fetcher
        self.supabase = supabase
        self.season = season
        self.age_division = age_division

    @abstractmethod
    async def fetch_teams(self) -> list[Team]:
        """Return all teams for this circuit/season."""

    @abstractmethod
    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]:
        """Return players + their roster entry for the given team."""

    @abstractmethod
    async def fetch_stats(self, team: Team) -> list[SeasonStats]:
        """Return season stats for all players on the given team."""

    async def run(self) -> None:
        """Orchestrate: teams → rosters → stats → upsert."""
        raise NotImplementedError(
            f"{self.__class__.__name__}.run() is not implemented. "
            "See main.py for the full orchestration loop."
        )
