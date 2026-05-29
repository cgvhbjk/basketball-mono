"""
Hoop Group adapter (boys) — placeholder.

Source strategy
---------------
hoopgroup.com publishes event recaps; live stats are syndicated through
ScoreBreak / The Circuit Hoops. The most reliable structured source is
likely the Synergy feed used by thecircuithoops.com for box scores —
investigate that endpoint first.

Status: scaffolded only.
"""
from __future__ import annotations
from .base_circuit import BaseCircuit
from ..models import Team, Player, RosterEntry, SeasonStats


class HoopGroupScraper(BaseCircuit):
    circuit_name = "Hoop Group"
    circuit_org = "Hoop Group"
    source_strategy = "html"

    async def fetch_teams(self) -> list[Team]:
        raise NotImplementedError(
            "Hoop Group adapter is scaffolding only. See module docstring."
        )

    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]:
        raise NotImplementedError

    async def fetch_stats(self, team: Team) -> list[SeasonStats]:
        raise NotImplementedError
