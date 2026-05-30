"""
UAA scraper — Under Armour Association (boys, 17U).
Data source: underarmournext.com

URL patterns:
  Teams hub:  /basketball/boys-uaa/
  Team stats: /basketball/teams?stid={stid}&c={year}boys
  Player bio: /basketball/players?spid={spid}&c={year}boys

Stats on the team page are SEASON TOTALS; PPG/RPG/APG/SPG/BPG are
computed by dividing each counting stat by GP.
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
from bs4 import BeautifulSoup

from .base_circuit import BaseCircuit
from ..base_fetcher import EmptyPageError
from ..models import Team, Player, RosterEntry, SeasonStats

logger = logging.getLogger(__name__)

BASE_URL = "https://underarmournext.com"


class UAAScraper(BaseCircuit):
    circuit_name = "UAA"
    circuit_org = "Under Armour"
    _HUB_PATH = "/basketball/boys-uaa/"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._team_html: dict[str, str] = {}

    def _cohort(self) -> str:
        return f"{self.season}boys"

    def _wait_for(self, selector: str | None) -> None:
        """Tell a Playwright fetcher to wait for this content marker before
        reading the page — rides through the JS bot-challenge that otherwise
        yields an empty shell. No-op for the httpx fetcher."""
        setter = getattr(self.fetcher, "set_wait_selector", None)
        if setter:
            setter(selector)

    async def _get_team_html(self, stid: str) -> str:
        if stid not in self._team_html:
            await asyncio.sleep(0.5)
            url = f"{BASE_URL}/basketball/teams?stid={stid}&c={self._cohort()}"
            # Team pages list players via spid links; wait for those so we don't
            # parse the challenge shell.
            self._wait_for('a[href*="spid="]')
            try:
                html = await self.fetcher.fetch_html(url)
            except EmptyPageError:
                from ..playwright_fetcher import PlaywrightFetcher
                if not isinstance(self.fetcher, PlaywrightFetcher):
                    logger.info("UAA team pages are JS-rendered — switching fetcher to Playwright")
                    await self.fetcher.close()
                    self.fetcher = PlaywrightFetcher()
                self._wait_for('a[href*="spid="]')
                html = await self.fetcher.fetch_html(url)
            self._team_html[stid] = html
        return self._team_html[stid]

    async def fetch_teams(self) -> list[Team]:
        url = f"{BASE_URL}{self._HUB_PATH}"
        logger.info("Fetching %s teams from %s", self.circuit_name, url)
        # Hub lists teams via stid links — wait for them past the challenge.
        self._wait_for('a[href*="stid="]')
        html = await self.fetcher.fetch_html(url)
        return _parse_teams(html, self.season, self.age_division)

    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]:
        html = await self._get_team_html(team.source_id)
        entries = _parse_roster(html, team.source_id)
        # Per-player bio pages are one extra JS-rendered fetch each — the slow
        # part of a UAA run. They only fill grad_year/height/position/hometown,
        # so SCRAPER_SKIP_BIOS=1 skips them when only teams/rosters/stats matter.
        if os.getenv("SCRAPER_SKIP_BIOS") == "1":
            return entries
        # Enrich each player with bio data from their individual profile page
        for player, roster_entry in entries:
            await asyncio.sleep(0.3)
            url = f"{BASE_URL}/basketball/players?spid={roster_entry.source_player_id}&c={self._cohort()}"
            try:
                bio_html = await self.fetcher.fetch_html(url)
                _enrich_player_bio(bio_html, player, self.season)
            except Exception as exc:
                logger.debug("Bio fetch failed for %s: %s", roster_entry.source_player_id, exc)
        return entries

    async def fetch_stats(self, team: Team) -> list[SeasonStats]:
        html = await self._get_team_html(team.source_id)
        # Use the team's own division (parsed from the hub heading), not the
        # run-config default — a program fields separate 15U/16U/17U squads.
        return _parse_stats(html, team.source_id, self.season, team.age_division)


# ----------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------

_STID_RE = re.compile(r"stid=([a-f0-9]{24})")
_SPID_RE = re.compile(r"spid=([a-f0-9]{24})")
# Hub groups teams under headings like "Boys 17U" / "Boys 16U" / "Boys 15U".
# A single program (e.g. B. Maze Elite) appears once per division with a
# distinct stid, so the division must come from the heading, not run config.
_DIVISION_HEADING_RE = re.compile(r"Boys\s*(1[567]U)", re.I)
_JERSEY_RE = re.compile(r"^#(\d+)\s*(.*)")
_HEIGHT_RE = re.compile(r"([4-8])['''](\d{1,2})")
_YEAR_RE = re.compile(r"\b(20(?:2[4-9]|3[0-2]))\b")
_GRAD_LABELS = ("class", "grad", "grad year", "graduation", "year")


def _parse_grad(value: str, season: int) -> int | None:
    """Extract a graduation year from a labeled field value. A U15/U16/U17
    player can't have graduated in or before the season they played, so
    anything ≤ season is rejected as bogus (usually the cohort year)."""
    m = _YEAR_RE.search(value)
    if not m:
        return None
    n = int(m.group(1))
    if n <= season:
        return None
    return n


def _enrich_player_bio(html: str, player: Player, season: int) -> None:
    """Parse height, position, grad year, high school from a UAA player profile page."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    if player.height_inches is None:
        m = _HEIGHT_RE.search(text)
        if m:
            h = int(m.group(1)) * 12 + int(m.group(2))
            if 48 <= h <= 108:
                player.height_inches = h

    # UA Next bio pages use <dl>/<dt>/<dd> or <th>/<td> pairs.
    # Only match explicit paired elements — a page-wide year regex would pick
    # up the cohort label ("2025 boys") in the page chrome, not the player's
    # actual grad year. If labels aren't present, leave grad_year null so the
    # downstream enrichers (on3, 247) can fill it in.
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        label = dt.get_text(strip=True).lower()
        value = dd.get_text(strip=True)
        if not value:
            continue
        if player.position is None and label in ("position", "pos"):
            player.position = value
        if player.high_school is None and label in ("school", "high school", "hs"):
            player.high_school = value
        if player.hometown is None and "hometown" in label:
            player.hometown = value
        if player.grad_year is None and label in _GRAD_LABELS:
            g = _parse_grad(value, season)
            if g is not None:
                player.grad_year = g

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True).lower()
        value = cells[1].get_text(strip=True)
        if not value:
            continue
        if player.position is None and label in ("position", "pos"):
            player.position = value
        if player.high_school is None and label in ("school", "high school", "hs"):
            player.high_school = value
        if player.hometown is None and "hometown" in label:
            player.hometown = value
        if player.grad_year is None and label in _GRAD_LABELS:
            g = _parse_grad(value, season)
            if g is not None:
                player.grad_year = g


def _parse_teams(html: str, season: int, age_division: str) -> list[Team]:
    """Parse all teams from the hub, tagging each with the division of the
    "Boys NNU" heading it appears under. `age_division` is only a fallback for
    links that precede any heading (page chrome). Each squad has its own stid,
    so divisions of the same program stay distinct."""
    soup = BeautifulSoup(html, "html.parser")
    teams: list[Team] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=_STID_RE):
        m = _STID_RE.search(link["href"])
        if not m:
            continue
        stid = m.group(1)
        if stid in seen:
            continue
        seen.add(stid)
        name = link.get_text(strip=True)
        if not name:
            continue
        heading = link.find_previous(string=_DIVISION_HEADING_RE)
        division = (
            _DIVISION_HEADING_RE.search(heading).group(1).upper()
            if heading
            else age_division
        )
        teams.append(Team(source_id=stid, name=name, age_division=division, season=season))
    by_div: dict[str, int] = {}
    for t in teams:
        by_div[t.age_division] = by_div.get(t.age_division, 0) + 1
    logger.info("Parsed %d UAA teams by division: %s", len(teams), by_div)
    return teams


def _split_name(raw: str) -> tuple[str | None, str, str]:
    """Return (jersey, first_name, last_name) from '#0 David Lunn' style text."""
    m = _JERSEY_RE.match(raw.strip())
    if m:
        jersey, name = m.group(1), m.group(2).strip()
    else:
        jersey, name = None, raw.strip()
    parts = name.split(None, 1)
    return jersey, (parts[0] if parts else name), (parts[1] if len(parts) > 1 else "")


def _parse_roster(html: str, team_source_id: str) -> list[tuple[Player, RosterEntry]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[Player, RosterEntry]] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=_SPID_RE):
        m = _SPID_RE.search(link["href"])
        if not m:
            continue
        spid = m.group(1)
        if spid in seen:
            continue
        seen.add(spid)
        jersey, first, last = _split_name(link.get_text(strip=True))
        if len(first) < 2 or (last and len(last) < 2):
            continue
        results.append((
            Player(source_id=spid, first_name=first, last_name=last),
            RosterEntry(source_team_id=team_source_id, source_player_id=spid, jersey_number=jersey),
        ))
    return results


def _safe_int(val: str | None) -> int | None:
    if not val:
        return None
    try:
        return int(val.strip())
    except ValueError:
        return None


def _safe_float(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(val.replace("%", "").strip())
    except ValueError:
        return None


def _per_game(total: int | None, gp: int) -> float | None:
    if total is None:
        return None
    return round(total / gp, 1)


def _parse_stats(
    html: str, team_source_id: str, season: int, age_division: str
) -> list[SeasonStats]:
    """
    Find the player stats table (has GP + PTS headers) and compute per-game
    averages from season totals.
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[SeasonStats] = []

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).upper() for th in table.find_all("th")]
        if "GP" not in headers or "PTS" not in headers:
            continue
        idx = {h: i for i, h in enumerate(headers)}

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue
            spid_link = cells[0].find("a", href=_SPID_RE) if cells else None
            if not spid_link:
                continue
            m = _SPID_RE.search(spid_link["href"])
            if not m:
                continue
            spid = m.group(1)

            def cell(*names: str) -> str | None:
                for name in names:
                    i = idx.get(name)
                    if i is not None and i < len(cells):
                        v = cells[i].get_text(strip=True)
                        if v:
                            return v
                return None

            gp = _safe_int(cell("GP"))
            if not gp:
                continue

            results.append(SeasonStats(
                source_player_id=spid,
                source_team_id=team_source_id,
                season=season,
                age_division=age_division,
                games_played=gp,
                ppg=_per_game(_safe_int(cell("PTS")), gp),
                rpg=_per_game(_safe_int(cell("REB")), gp),
                apg=_per_game(_safe_int(cell("AST")), gp),
                spg=_per_game(_safe_int(cell("STL")), gp),
                bpg=_per_game(_safe_int(cell("BLK")), gp),
                tpg=_per_game(_safe_int(cell("TO", "TOV")), gp),
                fpg=_per_game(_safe_int(cell("PF", "FOULS")), gp),
                fg_pct=_safe_float(cell("FG%")),
                three_pt_pct=_safe_float(cell("3FG%", "3P%")),
                ft_pct=_safe_float(cell("FT%")),
                oreb=_per_game(_safe_int(cell("OREB", "OR")), gp),
                dreb=_per_game(_safe_int(cell("DREB", "DR")), gp),
                fga=_per_game(_safe_int(cell("FGA")), gp),
                fgm_pg=_per_game(_safe_int(cell("FGM")), gp),
                fta=_per_game(_safe_int(cell("FTA")), gp),
                ftm_pg=_per_game(_safe_int(cell("FTM")), gp),
                three_pa_pg=_per_game(_safe_int(cell("3FGA", "3PA")), gp),
                three_pm_pg=_per_game(_safe_int(cell("3FGM", "3PM")), gp),
                mpg=_per_game(_safe_int(cell("MIN")), gp),
            ))
        break

    return results
