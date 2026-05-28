"""
EYCL scraper — Nike Elite Youth Champions League (girls, 17U).
Data source: basketball.exposureevents.com (ExposureEvents platform)

The EYCL site (nikegirlseybl.com) embeds an ExposureEvents widget.
The widget exposes three endpoints we use:
  1. Teams HTML  : /262129/2026-eycl-regular-season/teams (browser-rendered, no auth)
  2. Roster JSON : /widgets/v1/teamroster?id={EVENT_ID}&divisionteamid={id}
  3. Player HTML : /widgets/v1/player?eventid={EVENT_ID}&playerid={id}

Player HTML → Table 0 has per-game averages (PPG, RPG, APG, MPG).
              Table 1 has per-game box scores with a Totals row we use
              to compute FGA/G, FTA/G, and TPG.
"""
from __future__ import annotations
import asyncio
import logging
import re
from typing import Optional
import httpx
from bs4 import BeautifulSoup

from .base_circuit import BaseCircuit
from ..models import Team, Player, RosterEntry, SeasonStats

logger = logging.getLogger(__name__)

_BASE = "https://basketball.exposureevents.com"
_EVENT_ID = 262129  # 2026 EYCL Regular Season

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.9",
    "Referer": "https://nikegirlseybl.com/",
}


class EYCLScraper(BaseCircuit):
    circuit_name = "EYCL"
    circuit_org = "Nike"
    circuit_gender = "girls"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # team source_id (str divisionteamid) → list of ExposureEvents player IDs
        self._team_player_ids: dict[str, list[int]] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def fetch_teams(self) -> list[Team]:
        url = f"{_BASE}/{_EVENT_ID}/2026-eycl-regular-season/teams"
        logger.info("Fetching EYCL teams from %s", url)
        html = await self.fetcher.fetch_html(url)
        return _parse_teams(html, self.season, self.age_division)

    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]:
        url = (
            f"{_BASE}/widgets/v1/teamroster"
            f"?id={_EVENT_ID}&divisionteamid={team.source_id}&responsive=true"
        )
        try:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Could not fetch EYCL roster for team %s: %s", team.name, exc)
            return []

        results = _parse_roster_json(data, team.source_id)
        # Cache player IDs so fetch_stats can look them up
        self._team_player_ids[team.source_id] = [
            int(r["Id"]) for r in (data.get("Results") or []) if r.get("Id")
        ]
        return results

    async def fetch_stats(self, team: Team) -> list[SeasonStats]:
        player_ids = self._team_player_ids.get(team.source_id, [])
        if not player_ids:
            logger.warning("No player IDs cached for EYCL team %s — skipping stats", team.name)
            return []

        results: list[SeasonStats] = []
        for pid in player_ids:
            url = (
                f"{_BASE}/widgets/v1/player"
                f"?eventid={_EVENT_ID}&playerid={pid}&responsive=true"
            )
            try:
                html = await self.fetcher.fetch_html(url)
            except Exception as exc:
                logger.warning("Could not fetch EYCL stats for player %d: %s", pid, exc)
                continue

            stats = _parse_player_stats(html, str(pid), team.source_id, self.season, team.age_division)
            if stats:
                results.append(stats)

            await asyncio.sleep(0.3)  # polite crawl rate

        return results


# ------------------------------------------------------------------
# Parsers
# ------------------------------------------------------------------

def _parse_teams(html: str, season: int, age_division: str) -> list[Team]:
    soup = BeautifulSoup(html, "html.parser")
    teams: list[Team] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        # Match /262129/2026-eycl-regular-season/teams/slug?divisionteamid=XXXX
        m = re.search(r"divisionteamid=(\d+)", href)
        if not m:
            continue
        dtid = m.group(1)
        if dtid in seen:
            continue
        seen.add(dtid)
        name = link.get_text(strip=True)
        if not name:
            continue
        # Detect real division from suffix ("All Iowa Attack 16 EYCL" → "16U")
        # before stripping so the Team gets the correct age_division.
        div_match = re.search(r'\b(\d+)\s+EYCL\s*$', name, flags=re.IGNORECASE)
        detected_division = f"{div_match.group(1)}U" if div_match else age_division
        name = re.sub(r'\s+\d+\s+EYCL\s*$', '', name, flags=re.IGNORECASE).strip()
        teams.append(Team(
            source_id=dtid,
            name=name,
            age_division=detected_division,
            season=season,
        ))

    logger.info("Parsed %d EYCL teams", len(teams))
    return teams


def _parse_roster_json(data: dict, team_source_id: str) -> list[tuple[Player, RosterEntry]]:
    results: list[tuple[Player, RosterEntry]] = []
    seen: set[int] = set()

    for r in data.get("Results") or []:
        pid = r.get("Id")
        if not pid or pid in seen:
            continue
        seen.add(pid)

        first = (r.get("FirstName") or "").strip()
        last = (r.get("LastName") or "").strip()
        if not first and not last:
            continue

        height_raw = r.get("Height")
        height_inches: Optional[int] = None
        if height_raw:
            m = re.match(r"(\d+)['\-](\d+)", str(height_raw))
            if m:
                h = int(m.group(1)) * 12 + int(m.group(2))
                if 48 <= h <= 108:  # 4'0" – 9'0", reject parse garbage / typos
                    height_inches = h

        grad_year: Optional[int] = None
        gy = r.get("GraduationYear")
        if gy:
            try:
                gy_int = int(str(gy).strip())
                if 2024 <= gy_int <= 2032:
                    grad_year = gy_int
            except ValueError:
                pass

        source_id = str(pid)
        results.append((
            Player(
                source_id=source_id,
                first_name=first,
                last_name=last,
                height_inches=height_inches,
                position=r.get("Position") or None,
                high_school=r.get("School") or None,
                grad_year=grad_year,
                hometown=r.get("HomeTown") or None,
            ),
            RosterEntry(
                source_team_id=team_source_id,
                source_player_id=source_id,
                jersey_number=r.get("Number") or None,
                position=r.get("Position") or None,
            ),
        ))

    return results


def _safe_float(s: str | None) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.replace("%", "").strip())
    except ValueError:
        return None


def _safe_int(s: str | None) -> Optional[int]:
    if not s:
        return None
    try:
        return int(s.strip())
    except ValueError:
        return None


def _parse_player_stats(
    html: str,
    source_player_id: str,
    source_team_id: str,
    season: int,
    age_division: str,
) -> Optional[SeasonStats]:
    """
    Parse a player's ExposureEvents widget page.

    Table 0 (summary): PPG | RPG | APG | MPG
    Table 1 (per-game): Date | Opponent | FGM-FGA | FG% | 3PM-3PA | 3FG% |
                        FTM-FTA | FT% | REB | PF | PTS | AST | TO | BLK | STL | MIN
                        [+ Totals row at the bottom]
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    ppg = rpg = apg = mpg = None
    fga = fta = tpg = fg_pct = three_pt_pct = None
    spg = bpg = None
    gp: Optional[int] = None

    # Table 0 — summary averages
    if tables:
        t0 = tables[0]
        headers = [th.get_text(strip=True).upper() for th in t0.find_all("th")]
        rows = t0.find_all("tr")
        data_rows = [r for r in rows if r.find("td")]
        if data_rows:
            cells = data_rows[0].find_all("td")
            idx = {h: i for i, h in enumerate(headers)}
            def _cell(h: str) -> str | None:
                i = idx.get(h)
                return cells[i].get_text(strip=True) if i is not None and i < len(cells) else None
            ppg = _safe_float(_cell("PPG"))
            rpg = _safe_float(_cell("RPG"))
            apg = _safe_float(_cell("APG"))
            mpg = _safe_float(_cell("MPG"))

    # Table 1 — per-game box scores + Totals row
    if len(tables) > 1:
        t1 = tables[1]
        # Only grab headers from the first row to avoid capturing the Totals row's <th> values
        first_row = t1.find("tr")
        headers1 = [th.get_text(strip=True).upper() for th in (first_row.find_all("th") if first_row else [])]
        idx1 = {h: i for i, h in enumerate(headers1)}

        # Skip the header row (first row); count every other row that's not the
        # Totals row as a game. ExposureEvents sometimes renders rows with <th>
        # cells instead of <td>, so accept both — otherwise game_rows stays 0 and
        # the totals_row stats below get silently dropped.
        all_rows = t1.find_all("tr")
        totals_row = None
        game_rows = 0
        for row in all_rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            row_text = row.get_text(" ", strip=True)
            if "Totals" in row_text or "TOTALS" in row_text:
                totals_row = cells
            else:
                game_rows += 1

        gp = game_rows if game_rows > 0 else None

        if totals_row and gp:
            def _tcell(h: str) -> str | None:  # type: ignore[misc]
                i = idx1.get(h)
                return totals_row[i].get_text(strip=True) if i is not None and i < len(totals_row) else None

            # FGM-FGA column has format "59-143"
            fgm_fga = _tcell("FGM-FGA")
            if fgm_fga and "-" in fgm_fga:
                _, fga_total = fgm_fga.rsplit("-", 1)
                fga_total_int = _safe_int(fga_total)
                if fga_total_int is not None and gp:
                    fga = round(fga_total_int / gp, 1)

            # FTM-FTA column has format "36-49"
            ftm_fta = _tcell("FTM-FTA")
            if ftm_fta and "-" in ftm_fta:
                _, fta_total = ftm_fta.rsplit("-", 1)
                fta_total_int = _safe_int(fta_total)
                if fta_total_int is not None and gp:
                    fta = round(fta_total_int / gp, 1)

            # TO column
            to_total = _safe_int(_tcell("TO"))
            if to_total is not None and gp:
                tpg = round(to_total / gp, 1)

            # STL / BLK columns
            stl_total = _safe_int(_tcell("STL"))
            if stl_total is not None and gp:
                spg = round(stl_total / gp, 1)

            blk_total = _safe_int(_tcell("BLK"))
            if blk_total is not None and gp:
                bpg = round(blk_total / gp, 1)

            # Percentages from totals row (already computed by the site).
            # Use `> 1` to match models.normalize_pct so v==1.0 (1-of-1 = 100% as
            # a fraction) is preserved instead of being scaled to 1%.
            fg_pct_str = _tcell("FG%")
            if fg_pct_str:
                v = _safe_float(fg_pct_str)
                if v is not None:
                    fg_pct = v / 100 if v > 1 else v

            three_pct_str = _tcell("3FG%")
            if three_pct_str:
                v = _safe_float(three_pct_str)
                if v is not None:
                    three_pt_pct = v / 100 if v > 1 else v

    if ppg is None and gp is None:
        return None

    return SeasonStats(
        source_player_id=source_player_id,
        source_team_id=source_team_id,
        season=season,
        age_division=age_division,
        games_played=gp,
        ppg=ppg,
        rpg=rpg,
        apg=apg,
        spg=spg,
        bpg=bpg,
        mpg=mpg,
        fga=fga,
        fta=fta,
        tpg=tpg,
        fg_pct=fg_pct,
        three_pt_pct=three_pt_pct,
    )
