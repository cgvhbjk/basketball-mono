"""
PUMA scraper — PUMA PRO16 / NXTPRO basketball circuit (boys, 17U).
Data source: nxtprohoops.com

Individual player stats and full rosters are behind a paid membership wall
($20/month per region or $50/month national) on nxtprohoops.com. No public
player stats API has been identified.

What IS publicly accessible:
  - Team standings (W/L records) at /standings/17u/
  - Team names in the PRO16 and NXTPRO leagues

To implement full roster/stats scraping, either:
  a) Subscribe and scrape the members-only pages (requires auth cookie)
  b) Identify a third-party source that aggregates PUMA stats (e.g.
     thecircuithoops.com cites Synergy data for PUMA coverage)
"""
import logging
import re
from bs4 import BeautifulSoup

from .base_circuit import BaseCircuit
from ..models import Team, Player, RosterEntry, SeasonStats

logger = logging.getLogger(__name__)

BASE_URL = "https://nxtprohoops.com"
STANDINGS_PATH = "/standings/17u/"


class PUMAScraper(BaseCircuit):
    circuit_name = "PUMA"
    circuit_org = "PUMA"
    circuit_gender = "boys"

    async def fetch_teams(self) -> list[Team]:
        url = f"{BASE_URL}{STANDINGS_PATH}"
        logger.info("Fetching PUMA teams from %s", url)
        html = await self.fetcher.fetch_html(url)
        return _parse_teams(html, self.season, self.age_division)

    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]:
        raise NotImplementedError(
            "PUMA roster data requires a paid nxtprohoops.com membership. "
            "See puma.py module docstring for options to implement this."
        )

    async def fetch_stats(self, team: Team) -> list[SeasonStats]:
        raise NotImplementedError(
            "PUMA player stats require a paid nxtprohoops.com membership. "
            "See puma.py module docstring for options to implement this."
        )


# ----------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------

def _parse_teams(html: str, season: int, age_division: str) -> list[Team]:
    """
    Standings page lists teams with W/L records in a server-rendered table.
    Team names are the only data publicly available; no numeric IDs are exposed.
    """
    soup = BeautifulSoup(html, "html.parser")
    teams: list[Team] = []
    seen: set[str] = set()

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).upper() for th in table.find_all("th")]
        name_col = next((i for i, h in enumerate(headers) if "TEAM" in h or "NAME" in h), None)
        if name_col is None:
            # Try first column heuristic
            name_col = 0

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells or name_col >= len(cells):
                continue
            name = cells[name_col].get_text(strip=True)
            if not name or name in seen:
                continue
            seen.add(name)
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            teams.append(Team(source_id=slug, name=name, age_division=age_division, season=season))

    logger.info("Parsed %d PUMA teams from standings", len(teams))
    return teams
