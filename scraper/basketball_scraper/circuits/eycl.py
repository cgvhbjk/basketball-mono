"""
EYCL scraper — Nike Elite Youth Champions League (girls, 17U).
Data source: nikegirlseybl.com

Stats are served by a Position Sports JavaScript widget embedded on
nikegirlseybl.com/live-stats-champions-league. No public API endpoint has
been identified for Position Sports — the widget loads data entirely client-side
and the backend URL is not exposed in the page source.

What IS scrapable without further reverse-engineering:
  - Team names from nikegirlseybl.com/eybl-champions-league-teams (SSR HTML)
  - Roster info from individual team pages at /[team-name]-{season} (SSR HTML)

To implement stats, open the Position Sports widget in DevTools → Network tab,
filter by XHR/Fetch, and identify the API endpoint it calls. Then promote that
URL pattern here and implement _parse_player_stats() accordingly.
"""
import logging
import re
from bs4 import BeautifulSoup

from .base_circuit import BaseCircuit
from ..models import Team, Player, RosterEntry, SeasonStats

logger = logging.getLogger(__name__)

BASE_URL = "https://nikegirlseybl.com"
TEAMS_PATH = "/eybl-champions-league-teams"


class EYCLScraper(BaseCircuit):
    circuit_name = "EYCL"
    circuit_org = "Nike"
    circuit_gender = "girls"

    async def fetch_teams(self) -> list[Team]:
        url = f"{BASE_URL}{TEAMS_PATH}"
        logger.info("Fetching EYCL teams from %s", url)
        html = await self.fetcher.fetch_html(url)
        return _parse_teams(html, self.season, self.age_division)

    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]:
        # Team pages follow the pattern /[team-slug]-{season}
        url = f"{BASE_URL}/{team.source_id}-{self.season}"
        try:
            html = await self.fetcher.fetch_html(url)
        except Exception as exc:
            logger.warning("Could not fetch EYCL team page for %s: %s", team.name, exc)
            return []
        return _parse_roster(html, team.source_id)

    async def fetch_stats(self, team: Team) -> list[SeasonStats]:
        raise NotImplementedError(
            "EYCL stats require the Position Sports API endpoint, which is not yet identified. "
            "Open nikegirlseybl.com/live-stats-champions-league in DevTools → Network → XHR "
            "and capture the API URL to implement this method."
        )


# ----------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------

def _parse_teams(html: str, season: int, age_division: str) -> list[Team]:
    """
    The Champions League teams page lists team names as links or headings.
    Uses the URL slug as source_id since no numeric ID is exposed.
    """
    soup = BeautifulSoup(html, "html.parser")
    teams: list[Team] = []
    seen: set[str] = set()

    # Team links typically point to /[team-slug]-{year}
    pattern = re.compile(rf"^/{re.escape(str(season))}$|^/[a-z0-9-]+-{season}$")
    for link in soup.find_all("a", href=True):
        href = link["href"].rstrip("/")
        # Match links ending in -YEAR (e.g. /aebl-2026)
        if not re.search(rf"-{season}$", href):
            continue
        slug = href.lstrip("/").replace(f"-{season}", "")
        if not slug or slug in seen:
            continue
        seen.add(slug)
        name = link.get_text(strip=True)
        if not name:
            continue
        teams.append(Team(source_id=slug, name=name, age_division=age_division, season=season))

    logger.info("Parsed %d EYCL teams", len(teams))
    return teams


def _parse_roster(html: str, team_source_id: str) -> list[tuple[Player, RosterEntry]]:
    """
    Individual team pages on nikegirlseybl.com (Squarespace) list players
    in a simple table or list with columns: #, Name, Position, School.
    Adjust selectors if the actual page structure differs.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[Player, RosterEntry]] = []
    seen: set[str] = set()

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).upper() for th in table.find_all("th")]
        name_idx = next((i for i, h in enumerate(headers) if "NAME" in h), None)
        if name_idx is None:
            continue
        num_idx = next((i for i, h in enumerate(headers) if "#" in h or "NO" in h or "NUM" in h), None)
        pos_idx = next((i for i, h in enumerate(headers) if "POS" in h), None)
        school_idx = next((i for i, h in enumerate(headers) if "SCHOOL" in h or "HS" in h), None)

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) <= name_idx:
                continue
            full_name = cells[name_idx].get_text(strip=True)
            if not full_name or full_name in seen:
                continue
            seen.add(full_name)

            parts = full_name.split(None, 1)
            first = parts[0] if parts else full_name
            last = parts[1] if len(parts) > 1 else ""

            jersey = cells[num_idx].get_text(strip=True) if num_idx is not None and num_idx < len(cells) else None
            position = cells[pos_idx].get_text(strip=True) if pos_idx is not None and pos_idx < len(cells) else None
            high_school = cells[school_idx].get_text(strip=True) if school_idx is not None and school_idx < len(cells) else None

            pid = re.sub(r"[^a-z0-9]", "", full_name.lower())
            results.append((
                Player(source_id=pid, first_name=first, last_name=last, high_school=high_school),
                RosterEntry(
                    source_team_id=team_source_id,
                    source_player_id=pid,
                    jersey_number=jersey,
                    position=position,
                ),
            ))
        break

    return results
