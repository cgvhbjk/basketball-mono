"""
Made Hoops adapter (boys) — placeholder.

Source strategy
---------------
madehoops.com is a Next.js site. Most data pages call internal API routes
under /api/ — capture them by running the relevant page through
PlaywrightFetcher (which logs XHR/fetch traffic at INFO).

Status: scaffolded only.
"""
from __future__ import annotations
from .base_circuit import BaseCircuit
from ..models import Team, Player, RosterEntry, SeasonStats


class MadeHoopsScraper(BaseCircuit):
    circuit_name = "Made Hoops"
    circuit_org = "Made Hoops"
    source_strategy = "json"

    async def fetch_teams(self) -> list[Team]:
        raise NotImplementedError(
            "Made Hoops adapter is scaffolding only. See module docstring."
        )

    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]:
        raise NotImplementedError

    async def fetch_stats(self, team: Team) -> list[SeasonStats]:
        raise NotImplementedError
