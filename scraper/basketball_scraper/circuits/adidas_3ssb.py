"""
Adidas 3SSB scraper — 3 Stripes Series Basketball (boys).

Source-strategy ladder
----------------------
1. JSON-first (default).
   The site's stats table is backed by a WordPress AJAX endpoint exposed by
   the `adidas-stats-wp` plugin (action: ogp_get_player_stats_table). We
   hit it directly with httpx and paginate — no browser required.

       URL    : https://adidas3ssb.com/wp-admin/admin-ajax.php
       params : action=ogp_get_player_stats_table
                nonce=<extracted-from-stats-page>
                season=<starting-calendar-year>   (e.g. 2025 = "2025–26")
                brandNumber=10001                 (Platinum / 3SSB)
                                 =10003           (Gold)
                playLevel=Platinum | Gold
                division=15U|16U|17U
                gender=MALE                       (boys-only enforced)
                minGames=1
                sortBy=ppg&sortOrder=desc
                page=N&limit=25

   The nonce is short-lived and per-session — we read it from the rendered
   `ogpStats = {...}` global on the stats page once per run.

2. Playwright fallback.
   Kept for the case where the AJAX schema changes or the nonce probe
   breaks. The fallback walks the rendered table the old way (button-driven
   pagination), still feeding snapshots into the shared Snapshotter.

Field mapping (JSON → SeasonStats)
----------------------------------
    playerNumber → source_id        teamSlug/teamName → team identity
    gamesPlayed  → games_played     ppg / rpg / apg / spg / bpg / tpg
    fgPct        → fg_pct           threePointPct → three_pt_pct
    orpg         → oreb             threePg → (not currently stored)
    fpg          → (not currently stored)

Season semantics
----------------
The Adidas API uses the STARTING calendar year ("2025" for spring-2025
events that are part of the 2025–26 cycle). The pipeline elsewhere uses
the ending year, so we pass `self.season - 1`. Override with
ADIDAS_SEASON_OFFSET if a future season convention changes.
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
from typing import Any, Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from .base_circuit import BaseCircuit
from ..models import Team, Player, RosterEntry, SeasonStats

logger = logging.getLogger(__name__)

BASE_URL = "https://adidas3ssb.com"
STATS_PAGE_PATH = "/stats/players/table"
ADMIN_AJAX = f"{BASE_URL}/wp-admin/admin-ajax.php"

# 2025 -> "2025-26". self.season is the ending year, so default offset is -1.
ADIDAS_SEASON_OFFSET = int(os.environ.get("ADIDAS_SEASON_OFFSET", "-1"))

# Brand numbers per the live filter bar's data-brand attribute.
_BRAND_PLATINUM = 10001
_BRAND_GOLD     = 10003


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class Adidas3SSBScraper(BaseCircuit):
    circuit_name = "3SSB"
    circuit_org = "Adidas"
    source_strategy = "json"
    # (brandNumber, playLevel) pairs — Gold subclass overrides.
    _BRAND_LEVELS: tuple[tuple[int, str], ...] = ((_BRAND_PLATINUM, "Platinum"),)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # {team_slug: [(player, roster_entry, stats), ...]}
        self._cache: dict[str, list[tuple[Player, RosterEntry, SeasonStats]]] | None = None
        self._cache_lock = asyncio.Lock()

    def _adidas_season(self) -> int:
        return self.season + ADIDAS_SEASON_OFFSET

    # ------------------------------------------------------------------
    # JSON-first path
    # ------------------------------------------------------------------

    async def _read_nonce(self) -> Optional[str]:
        """Fetch the rendered stats page and extract the per-session ogpStats nonce."""
        html = await self.fetcher.fetch_html(f"{BASE_URL}{STATS_PAGE_PATH}")
        m = re.search(r'"nonce"\s*:\s*"([a-f0-9]+)"', html)
        if not m:
            logger.warning("Adidas 3SSB: could not find ogpStats nonce in stats page")
            return None
        return m.group(1)

    async def _fetch_json_page(
        self,
        *,
        nonce: str,
        brand_number: int,
        play_level: str,
        page: int,
        limit: int = 25,
    ) -> Optional[dict[str, Any]]:
        params = {
            "action": "ogp_get_player_stats_table",
            "nonce": nonce,
            "season": self._adidas_season(),
            "brandNumber": brand_number,
            "playLevel": play_level,
            "division": self.age_division,
            "gender": "MALE",  # boys-only
            "minGames": 1,
            "sortBy": "ppg",
            "sortOrder": "desc",
            "page": page,
            "limit": limit,
        }
        # urlencode so any value with a space/&/= (or a future param) is escaped
        # rather than producing a malformed query; dict order is preserved.
        url = f"{ADMIN_AJAX}?{urlencode(params)}"
        try:
            data = await self.fetcher.fetch_json(url)
        except Exception as exc:
            logger.warning("Adidas 3SSB JSON page=%d failed: %s", page, exc)
            return None
        if not isinstance(data, dict) or not data.get("success"):
            return None
        return data.get("data") or {}

    async def _try_json_first(self) -> Optional[dict[str, list[tuple[Player, RosterEntry, SeasonStats]]]]:
        nonce = await self._read_nonce()
        if not nonce:
            return None

        by_team: dict[str, list] = {}
        season, age_div = self.season, self.age_division

        for brand, level in self._BRAND_LEVELS:
            page = 1
            while True:
                payload = await self._fetch_json_page(
                    nonce=nonce, brand_number=brand, play_level=level, page=page,
                )
                if payload is None:
                    return None
                rows = payload.get("data") or []
                for player, roster_entry, stats in _parse_stats_json(rows, season, age_div):
                    by_team.setdefault(roster_entry.source_team_id, []).append(
                        (player, roster_entry, stats)
                    )
                pag = payload.get("pagination") or {}
                if not pag.get("hasNext") or page >= int(pag.get("totalPages") or 0):
                    break
                page += 1
                await asyncio.sleep(0.3)

        if not by_team:
            return None
        logger.info(
            "Adidas 3SSB JSON: %d teams, %d player rows across %d brand/level pair(s)",
            len(by_team), sum(len(v) for v in by_team.values()), len(self._BRAND_LEVELS),
        )
        return by_team

    # ------------------------------------------------------------------
    # Playwright fallback (kept verbatim in shape for safety)
    # ------------------------------------------------------------------

    async def _load_cache_via_playwright(self) -> dict[str, list[tuple[Player, RosterEntry, SeasonStats]]]:
        from playwright.async_api import async_playwright

        by_team: dict[str, list] = {}
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            for brand, level in self._BRAND_LEVELS:
                url = (
                    f"{BASE_URL}/stats/players/table"
                    f"?season={self._adidas_season()}&brand={brand}&division={self.age_division}"
                    f"&playLevel={level}&gender=MALE&minGames=1"
                    f"&sortBy=ppg&sortOrder=desc"
                )
                logger.info("Adidas 3SSB Playwright fallback %s/%s: %s", brand, level, url)
                page = await browser.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    try:
                        await page.wait_for_selector(
                            "table.ogp-stats-table tbody tr, table tbody tr td a", timeout=15_000
                        )
                    except Exception:
                        logger.warning("Adidas stats table did not appear")
                        continue

                    total_pages = 1
                    page_info_el = await page.query_selector(".ogp-page-info")
                    if page_info_el:
                        m = re.search(r"of\s+(\d+)", await page_info_el.inner_text())
                        if m:
                            total_pages = int(m.group(1))

                    for page_num in range(1, total_pages + 1):
                        html = await page.content()
                        self._snapshot(url, page_num, html)
                        for player, roster_entry, stats in _parse_stats_page(
                            html, self.season, self.age_division
                        ):
                            by_team.setdefault(roster_entry.source_team_id, []).append(
                                (player, roster_entry, stats)
                            )
                        if page_num < total_pages:
                            clicked = False
                            for sel in ("button.ogp-page-next:not([disabled])", ".ogp-page-next"):
                                btn = page.locator(sel).first
                                if await btn.count() > 0:
                                    await btn.click()
                                    await asyncio.sleep(2.0)
                                    clicked = True
                                    break
                            if not clicked:
                                break
                finally:
                    await page.close()
            await browser.close()
        return by_team

    def _snapshot(self, base_url: str, page_num: int, html: str) -> None:
        snapshotter = getattr(self.fetcher, "_snapshotter", None)
        if snapshotter is None:
            return
        try:
            snapshotter.record(
                adapter_name=self.circuit_name,
                source_url=f"{base_url}&page={page_num}",
                content_type="text/html",
                payload=html.encode("utf-8"),
            )
        except Exception as exc:
            logger.debug("snapshot write failed: %s", exc)

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    async def _load_cache(self) -> dict[str, list[tuple[Player, RosterEntry, SeasonStats]]]:
        result = await self._try_json_first()
        if result is not None:
            return result
        logger.info("Adidas 3SSB JSON path empty/failed — falling back to Playwright")
        return await self._load_cache_via_playwright()

    async def _get_cache(self) -> dict[str, list[tuple[Player, RosterEntry, SeasonStats]]]:
        async with self._cache_lock:
            if self._cache is None:
                self._cache = await self._load_cache()
        return self._cache

    async def fetch_teams(self) -> list[Team]:
        cache = await self._get_cache()
        teams: list[Team] = []
        for team_slug, entries in cache.items():
            if not entries:
                continue
            first_re = entries[0][1]
            raw_name = getattr(first_re, "_team_name", None) or team_slug.replace("-", " ").title()
            wins = getattr(first_re, "_team_wins", None)
            losses = getattr(first_re, "_team_losses", None)
            teams.append(Team(
                source_id=team_slug,
                name=raw_name,
                age_division=self.age_division,
                season=self.season,
                wins=int(wins) if wins is not None else None,
                losses=int(losses) if losses is not None else None,
            ))
        logger.info("Adidas 3SSB returning %d teams", len(teams))
        return teams

    async def fetch_roster(self, team: Team) -> list[tuple[Player, RosterEntry]]:
        cache = await self._get_cache()
        return [(p, re) for p, re, _ in cache.get(team.source_id, [])]

    async def fetch_stats(self, team: Team) -> list[SeasonStats]:
        cache = await self._get_cache()
        return [s for _, _, s in cache.get(team.source_id, [])]


# ----------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------

_PASSPORT_RE = re.compile(r"the-passport\.com/players/(\d+)/")


def _stat(d: dict, *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


def _parse_stats_json(
    rows: list[dict] | dict, season: int, age_division: str
) -> list[tuple[Player, RosterEntry, SeasonStats]]:
    """
    Parse rows returned by ogp_get_player_stats_table.

    Field names are camelCase (firstName, lastName, gamesPlayed, ppg, ...).
    `playerNumber` is the stable Passport ID; `teamSlug` already kebab-cases
    the team name so we use it directly instead of re-slugging.

    Also accepts envelope shapes used elsewhere (`{"players": [...]}`,
    `{"data": [...]}`) so tests / older payloads still parse.
    """
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("players") or rows.get("results") or []
    results: list[tuple[Player, RosterEntry, SeasonStats]] = []

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        pid = _stat(row, "playerNumber", "passport_id", "passportId", "id", "playerId")
        if not pid:
            continue
        first = _stat(row, "firstName", "first_name") or ""
        last  = _stat(row, "lastName", "last_name") or ""
        full = _stat(row, "name", "fullName")
        if not first and full:
            parts = str(full).split(None, 1)
            first, last = parts[0], (parts[1] if len(parts) > 1 else "")

        team_name = _stat(row, "teamName", "team_name", "team") or ""
        team_slug = _stat(row, "teamSlug", "team_slug") or (_slug(str(team_name)) if team_name else "unknown")

        gp = _stat(row, "gamesPlayed", "games_played", "gp")
        if not gp:
            continue

        position_list = row.get("positions") or []
        position = position_list[0].replace("_", " ").title() if position_list else None

        roster_entry = RosterEntry(
            source_team_id=str(team_slug),
            source_player_id=str(pid),
            position=position,
        )
        # Stash for fetch_teams() to recover the display name + W/L.
        roster_entry._team_name = str(team_name)  # type: ignore[attr-defined]
        roster_entry._team_wins = _stat(row, "wins")  # type: ignore[attr-defined]
        roster_entry._team_losses = _stat(row, "losses")  # type: ignore[attr-defined]

        results.append((
            Player(
                source_id=str(pid),
                first_name=str(first),
                last_name=str(last),
                position=position,
            ),
            roster_entry,
            SeasonStats(
                source_player_id=str(pid),
                source_team_id=str(team_slug),
                season=season,
                age_division=age_division,
                games_played=int(gp),
                ppg=_stat(row, "ppg"),
                rpg=_stat(row, "rpg"),
                apg=_stat(row, "apg"),
                spg=_stat(row, "spg", "stlpg"),
                bpg=_stat(row, "bpg", "blkpg"),
                tpg=_stat(row, "tpg", "topg"),
                fg_pct=_stat(row, "fgPct", "fg_pct"),
                three_pt_pct=_stat(row, "threePointPct", "three_pt_pct", "tpPct", "fg3Pct"),
                ft_pct=_stat(row, "ftPct", "ft_pct"),
                # Per-game splits from the OGP feed.
                oreb=_stat(row, "orpg", "oreb"),
                dreb=_stat(row, "drpg", "dreb"),
                fpg=_stat(row, "fpg"),
                three_pm_pg=_stat(row, "threePg", "three_pm_pg"),
                plus_minus=_stat(row, "plusMinus", "plus_minus"),
                events_played=_stat(row, "eventsPlayed", "events_played"),
                # Adidas doesn't expose FGA/FTA/MPG — these stay None even
                # when the request looked for legacy alias keys.
                fga=_stat(row, "fga", "fgapg"),
                fta=_stat(row, "fta", "ftapg"),
                mpg=_stat(row, "mpg", "minpg"),
            ),
        ))
    return results


def parse_stats_page(html: str, season: int, age_division: str) -> list[tuple[Player, RosterEntry, SeasonStats]]:
    """Public wrapper for HTML-fallback tests."""
    return _parse_stats_page(html, season, age_division)


def _parse_stats_page(
    html: str, season: int, age_division: str
) -> list[tuple[Player, RosterEntry, SeasonStats]]:
    """HTML fallback parser — used when Playwright walks the rendered table."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[Player, RosterEntry, SeasonStats]] = []

    target_table = None
    headers: list[str] = []
    for tbl in soup.find_all("table"):
        ths = [th.get_text(strip=True).upper() for th in tbl.find_all("th")]
        if "GP" in ths and "PPG" in ths:
            target_table = tbl
            headers = ths
            break
    if not target_table:
        return results

    idx = {h: i for i, h in enumerate(headers)}

    def safe_float(val: str | None) -> float | None:
        if not val:
            return None
        try:
            return float(val.replace("%", "").strip())
        except ValueError:
            return None

    def safe_int(val: str | None) -> int | None:
        if not val:
            return None
        try:
            return int(val.strip())
        except ValueError:
            return None

    def cell_text(cells, name: str) -> str | None:
        i = idx.get(name)
        return cells[i].get_text(strip=True) if i is not None and i < len(cells) else None

    for row in target_table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        player_cell = cells[0]
        passport_link = player_cell.find("a", href=_PASSPORT_RE)
        if not passport_link:
            continue
        pid_m = _PASSPORT_RE.search(passport_link["href"])
        if not pid_m:
            continue
        pid = pid_m.group(1)
        name_span = passport_link.find("span", class_="ogp-name-full")
        player_name = name_span.get_text(strip=True) if name_span else (
            passport_link.find("span") or passport_link
        ).get_text(strip=True)
        small_tag = player_cell.find("small", class_="ogp-table-sub")
        team_name = small_tag.get_text(strip=True) if small_tag else ""
        team_slug = _slug(team_name) if team_name else "unknown"
        parts = player_name.split(None, 1)
        first = parts[0] if parts else player_name
        last = parts[1] if len(parts) > 1 else ""
        gp = safe_int(cell_text(cells, "GP"))
        if not gp:
            continue
        roster_entry = RosterEntry(source_team_id=team_slug, source_player_id=pid)
        roster_entry._team_name = team_name  # type: ignore[attr-defined]
        results.append((
            Player(source_id=pid, first_name=first, last_name=last),
            roster_entry,
            SeasonStats(
                source_player_id=pid,
                source_team_id=team_slug,
                season=season,
                age_division=age_division,
                games_played=gp,
                ppg=safe_float(cell_text(cells, "PPG")),
                rpg=safe_float(cell_text(cells, "RPG")),
                apg=safe_float(cell_text(cells, "APG")),
                spg=safe_float(cell_text(cells, "SPG") or cell_text(cells, "STL")),
                bpg=safe_float(cell_text(cells, "BPG") or cell_text(cells, "BLK")),
                fg_pct=safe_float(cell_text(cells, "FG%")),
                three_pt_pct=safe_float(cell_text(cells, "3P%")),
                tpg=safe_float(cell_text(cells, "TPG")),
                mpg=safe_float(cell_text(cells, "MPG") or cell_text(cells, "MIN")),
                fga=safe_float(cell_text(cells, "FGA") or cell_text(cells, "FGAPG")),
                fta=safe_float(cell_text(cells, "FTA") or cell_text(cells, "FTAPG")),
                oreb=safe_float(
                    cell_text(cells, "OREB") or cell_text(cells, "OREBPG") or cell_text(cells, "ORPG")
                ),
            ),
        ))
    return results
