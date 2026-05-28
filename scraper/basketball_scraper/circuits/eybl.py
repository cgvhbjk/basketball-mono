"""
EYBL scraper — Nike Elite Youth Basketball League (boys, 17U).
Data source: Pointstreak platform (nikeeyb.hoopstats.pointstreak.com)

URL patterns:
  Teams:         /teamlist.html?leagueid=1366&seasonid={seasonid}
  Player list:   /playerlist.html?leagueid=1366&seasonid={seasonid}&letter={A-Z}
  Player detail: /player.html?playerid={id}&seasonid={seasonid}
  Stats leaders: /stats.html?leagueid=1366&seasonid={seasonid}

Season IDs: 544 was found to be an old season (~2020) based on the players
it returned (Moses Moody, James Wiseman, etc. — current NBA players).
The correct 2026 season ID is unknown because Pointstreak blocks this IP
via Incapsula (edet=16 = IP reputation block).

To find the correct season ID:
  1. Use a different IP / VPN, or
  2. Check nikeeybl.com/live-statistics and inspect the Pointstreak embed URL
  3. Update SEASON_ID below and re-run: python run_all.py --circuits eybl
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
from string import ascii_uppercase
from bs4 import BeautifulSoup
from supabase import Client

from .base_circuit import BaseCircuit
from ..base_fetcher import BaseFetcher
from ..models import Team, Player, RosterEntry, SeasonStats

logger = logging.getLogger(__name__)

BASE_URL   = "http://nikeeyb.hoopstats.pointstreak.com"
LEAGUE_ID  = 1366
# 544 was confirmed to be ~2020 data. The correct current ID must be supplied via env
# until we can verify it (see module docstring). Refuse to run with a stale ID rather
# than silently writing decade-old NBA players into the current season.
SEASON_ID  = int(os.environ.get("EYBL_SEASON_ID", "0"))


class EYBLScraper(BaseCircuit):
    circuit_name = "EYBL"
    circuit_org = "Nike"
    circuit_gender = "boys"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Cache all players keyed by team source_id — loaded once on first call
        self._all_players: dict[str, list[tuple[Player, RosterEntry]]] | None = None

    async def fetch_teams(self) -> list[Team]:
        if SEASON_ID == 0:
            raise RuntimeError(
                "EYBL_SEASON_ID env var is not set. The previously-hardcoded ID (544) "
                "returns ~2020 data; running the scraper without a verified current ID "
                "would pollute the DB with NBA-era players. See the module docstring."
            )
        url = f"{BASE_URL}/teamlist.html?leagueid={LEAGUE_ID}&seasonid={SEASON_ID}"
        logger.info("Fetching EYBL teams from %s", url)
        html = await self.fetcher.fetch_html(url)
        return _parse_teams(html, self.season, self.age_division)

    async def _load_all_players(self) -> dict[str, list[tuple[Player, RosterEntry]]]:
        """Fetch all 26 letter pages once; bucket results by team source_id."""
        by_team: dict[str, list[tuple[Player, RosterEntry]]] = {}
        for letter in ascii_uppercase:
            await asyncio.sleep(0.5)
            url = f"{BASE_URL}/playerlist.html?leagueid={LEAGUE_ID}&seasonid={SEASON_ID}&letter={letter}"
            html = await self.fetcher.fetch_html(url)
            for player, roster_entry in _parse_player_list(html):
                by_team.setdefault(roster_entry.source_team_id, []).append((player, roster_entry))
        logger.info("Loaded %d players total", sum(len(v) for v in by_team.values()))
        return by_team

    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]:
        if self._all_players is None:
            self._all_players = await self._load_all_players()
        return self._all_players.get(team.source_id, [])

    async def fetch_stats(self, team: Team) -> list[SeasonStats]:
        roster = await self.fetch_roster(team)
        results: list[SeasonStats] = []
        for player, roster_entry in roster:
            await asyncio.sleep(0.5)
            pid = roster_entry.source_player_id
            url = f"{BASE_URL}/player.html?playerid={pid}&seasonid={SEASON_ID}"
            try:
                html = await self.fetcher.fetch_html(url)
            except Exception as exc:
                logger.warning("Skipping player %s stats — fetch failed: %s", pid, exc)
                continue
            # Parse bio alongside stats from the same page
            _enrich_player_bio(html, player)
            stats = _parse_player_stats(html, pid, team.source_id, self.season, self.age_division)
            if stats:
                results.append(stats)
        return results


# ----------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------

_HEIGHT_RE = re.compile(r"([4-8])[‘’’](\d{1,2})")
_GRAD_RE = re.compile(r"\b(20(?:2[4-9]|3[0-2]))\b")


def _enrich_player_bio(html: str, player: Player) -> None:
    """
    Parse height, position, grad year, and high school from a Pointstreak
    player detail page and write them directly onto the Player model in-place.
    Only fills fields that are still None so existing data is not overwritten.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    if player.height_inches is None:
        m = _HEIGHT_RE.search(text)
        if m:
            h = int(m.group(1)) * 12 + int(m.group(2))
            if 48 <= h <= 108:  # 4'0" – 9'0", reject obvious parsing garbage
                player.height_inches = h

    if player.grad_year is None:
        m = _GRAD_RE.search(text)
        if m:
            try:
                player.grad_year = int(m.group(1))
            except Exception:
                pass

    # Pointstreak bio rows use <td> labels like "Position" and "School"
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True).lower()
        value = cells[1].get_text(strip=True)
        if not value:
            continue
        if player.position is None and "position" in label:
            player.position = value
        if player.high_school is None and label in ("school", "high school", "hs"):
            player.high_school = value


def _parse_teams(html: str, season: int, age_division: str) -> list[Team]:
    """
    Pointstreak teamlist page: table rows contain team name and link
    with teamid parameter.
    """
    soup = BeautifulSoup(html, "html.parser")
    teams: list[Team] = []

    for link in soup.find_all("a", href=re.compile(r"teamid=(\d+)")):
        m = re.search(r"teamid=(\d+)", link["href"])
        if not m:
            continue
        team_id = m.group(1)
        name = link.get_text(strip=True)
        if not name:
            continue
        teams.append(Team(
            source_id=team_id,
            name=name,
            age_division=age_division,
            season=season,
        ))

    # Deduplicate by source_id (links may appear multiple times)
    seen: set[str] = set()
    unique: list[Team] = []
    for t in teams:
        if t.source_id not in seen:
            seen.add(t.source_id)
            unique.append(t)

    logger.info("Parsed %d teams", len(unique))
    return unique


def _parse_player_list(html: str) -> list[tuple[Player, RosterEntry]]:
    """
    Pointstreak playerlist page: table rows contain player name link
    (with playerid) and team name link (with teamid).
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[Player, RosterEntry]] = []

    # Target only the main stats table — avoids alphabet-nav and other tables
    table = soup.find("table", class_=lambda c: c and "nova-stats-table" in c)
    if not table:
        return results

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        player_link = cells[0].find("a", href=re.compile(r"playerid=(\d+)"))
        team_link   = cells[2].find("a", href=re.compile(r"teamid=(\d+)"))

        if not player_link or not team_link:
            continue

        pid = re.search(r"playerid=(\d+)", player_link["href"]).group(1)
        tid = re.search(r"teamid=(\d+)",   team_link["href"]).group(1)

        full_name = player_link.get_text(strip=True)
        parts = full_name.split(None, 1)
        first = parts[0] if parts else full_name
        last  = parts[1] if len(parts) > 1 else ""

        if len(first) < 2 or (last and len(last) < 2):
            continue

        position = cells[1].get_text(strip=True) or None

        player = Player(
            source_id=pid,
            first_name=first,
            last_name=last,
        )
        roster_entry = RosterEntry(
            source_team_id=tid,
            source_player_id=pid,
            position=position,
        )
        results.append((player, roster_entry))

    return results


def _parse_player_stats(
    html: str,
    player_id: str,
    team_id: str,
    season: int,
    age_division: str,
) -> SeasonStats | None:
    """
    Pointstreak player detail page has two relevant tables:
      Table 0: PER | PPG | RPG | APG  (season averages)
      Table 4: Season | Team | GP | FGM-FGA | FG% | 3PM-3PA | 3P% | ...
               One row per session played; FGM-FGA values are per-game averages.
    """
    soup = BeautifulSoup(html, "html.parser")

    def safe_float(val: str | None) -> float | None:
        if not val:
            return None
        try:
            return float(val.replace("%", "").strip())
        except ValueError:
            return None

    # --- Pass 1: season-averages table (PPG / RPG / APG / SPG / BPG) ---
    ppg = rpg = apg = spg = bpg = None
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).upper() for th in table.find_all("th")]
        if "PPG" in headers and "RPG" in headers and "APG" in headers:
            idx = {h: i for i, h in enumerate(headers)}
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if not cells:
                    continue

                def _p1_cell(name: str) -> str | None:
                    i = idx.get(name)
                    return cells[i].get_text(strip=True) if i is not None and i < len(cells) else None

                ppg = safe_float(_p1_cell("PPG"))
                rpg = safe_float(_p1_cell("RPG"))
                apg = safe_float(_p1_cell("APG"))
                spg = safe_float(_p1_cell("SPG"))
                bpg = safe_float(_p1_cell("BPG"))
                break
            break

    # --- Pass 2: per-session table (GP / FGM-FGA / 3PM-3PA) ---
    # FGM-FGA are per-game averages; multiply by GP to reconstruct totals,
    # then aggregate across sessions for overall FG% / 3P%.
    total_gp = 0
    total_fgm = total_fga = 0.0
    total_3pm = total_3pa = 0.0

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).upper() for th in table.find_all("th")]
        if "GP" not in headers or "FGM-FGA" not in headers:
            continue
        idx = {h: i for i, h in enumerate(headers)}

        def _cell(cells, name: str) -> str:
            i = idx.get(name)
            return cells[i].get_text(strip=True) if i is not None and i < len(cells) else ""

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue
            gp_raw = _cell(cells, "GP")
            if not gp_raw.isdigit():
                continue
            gp = int(gp_raw)
            total_gp += gp
            if "FGM-FGA" in idx:
                parts = _cell(cells, "FGM-FGA").split("-")
                if len(parts) == 2:
                    try:
                        total_fgm += float(parts[0]) * gp
                        total_fga += float(parts[1]) * gp
                    except ValueError:
                        pass
            if "3PM-3PA" in idx:
                parts = _cell(cells, "3PM-3PA").split("-")
                if len(parts) == 2:
                    try:
                        total_3pm += float(parts[0]) * gp
                        total_3pa += float(parts[1]) * gp
                    except ValueError:
                        pass
        break

    if total_gp == 0 and ppg is None:
        return None

    return SeasonStats(
        source_player_id=player_id,
        source_team_id=team_id,
        season=season,
        age_division=age_division,
        games_played=total_gp or None,
        ppg=ppg,
        rpg=rpg,
        apg=apg,
        spg=spg,
        bpg=bpg,
        fg_pct=(total_fgm / total_fga) if total_fga > 0 else None,
        three_pt_pct=(total_3pm / total_3pa) if total_3pa > 0 else None,
    )
