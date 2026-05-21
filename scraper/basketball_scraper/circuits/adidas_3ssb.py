"""
Adidas 3SSB scraper — 3 Stripes Series Basketball (boys, 17U, Platinum tier).
Data source: adidas3ssb.com (WordPress + "OGP" stats plugin; JS-rendered table)

The stats table is populated by client-side JS so standard httpx won't work.
This scraper drives Playwright directly for pagination (the Next button triggers
an AJAX re-render that can't be replicated via URL params).

Strategy: load all stats pages once → cache by team slug → serve fetch_teams,
fetch_roster, fetch_stats from cache.

Season note: adidas3ssb.com uses the spring event calendar year (e.g. 2025 for
spring-2025 events). Adjust ADIDAS_SEASON_OFFSET if the site's year convention
doesn't match self.season (EYBL uses the ending calendar year).
"""
import asyncio
import logging
import re
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .base_circuit import BaseCircuit
from ..models import Team, Player, RosterEntry, SeasonStats

logger = logging.getLogger(__name__)

BASE_URL = "https://adidas3ssb.com"
ADIDAS_SEASON_OFFSET = 0  # set to -1 if self.season=2026 but site shows season=2025


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class Adidas3SSBScraper(BaseCircuit):
    circuit_name = "3SSB"
    circuit_org = "Adidas"
    circuit_gender = "boys"
    _PLAY_LEVELS = ["Platinum"]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # {team_slug: [(player, roster_entry, stats), ...]}
        self._cache: dict[str, list[tuple[Player, RosterEntry, SeasonStats]]] | None = None

    def _adidas_season(self) -> int:
        return self.season + ADIDAS_SEASON_OFFSET

    async def _load_cache(self) -> dict[str, list[tuple[Player, RosterEntry, SeasonStats]]]:
        by_team: dict[str, list] = {}
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            for level in self._PLAY_LEVELS:
                url = (
                    f"{BASE_URL}/stats/players/table"
                    f"?season={self._adidas_season()}&brand=10001&division=17U"
                    f"&playLevel={level}&gender=MALE&minGames=1"
                    f"&sortBy=ppg&sortOrder=desc"
                )
                logger.info("Adidas 3SSB loading playLevel=%s from %s", level, url)
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)

                try:
                    await page.wait_for_selector(
                        "table.ogp-stats-table tbody tr, table tbody tr td a", timeout=15_000
                    )
                except Exception:
                    logger.warning("Adidas stats table did not appear for playLevel=%s", level)
                    await page.close()
                    continue

                # Determine total pages from pagination widget
                total_pages = 1
                pag = await page.query_selector(".ogp-pagination")
                if pag:
                    tp_attr = await pag.get_attribute("data-total-pages")
                    if tp_attr and tp_attr.isdigit():
                        total_pages = int(tp_attr)
                logger.info("playLevel=%s has %d page(s)", level, total_pages)

                for page_num in range(1, total_pages + 1):
                    html = await page.content()
                    entries = _parse_stats_page(
                        html, self.season, self.age_division
                    )
                    for player, roster_entry, stats in entries:
                        team_slug = roster_entry.source_team_id
                        by_team.setdefault(team_slug, []).append((player, roster_entry, stats))

                    if page_num < total_pages:
                        # Click the Next button and wait for new rows
                        clicked = False
                        for selector in (
                            ".ogp-pagination a.next:not(.disabled)",
                            ".ogp-pagination a:has-text('Next')",
                        ):
                            btn = page.locator(selector).first
                            if await btn.count() > 0:
                                await btn.click()
                                await asyncio.sleep(1.0)
                                clicked = True
                                break
                        if not clicked:
                            logger.warning("Could not find Next button on page %d", page_num)
                            break

                await page.close()
            await browser.close()

        logger.info(
            "Adidas 3SSB loaded %d teams, %d total player entries",
            len(by_team),
            sum(len(v) for v in by_team.values()),
        )
        return by_team

    async def _get_cache(self) -> dict[str, list[tuple[Player, RosterEntry, SeasonStats]]]:
        if self._cache is None:
            self._cache = await self._load_cache()
        return self._cache

    async def fetch_teams(self) -> list[Team]:
        cache = await self._get_cache()
        teams: list[Team] = []
        seen_names: dict[str, str] = {}  # team_slug → canonical name
        for team_slug, entries in cache.items():
            if not entries:
                continue
            # Recover team name from the first entry's roster_entry source_team_id label.
            # We stored the original name on the RosterEntry via a sidecar attribute;
            # fall back to de-slugging if needed.
            first_re = entries[0][1]
            raw_name = getattr(first_re, "_team_name", None) or team_slug.replace("-", " ").title()
            teams.append(Team(
                source_id=team_slug,
                name=raw_name,
                age_division=self.age_division,
                season=self.season,
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


def _parse_stats_page(
    html: str, season: int, age_division: str
) -> list[tuple[Player, RosterEntry, SeasonStats]]:
    """
    Parse one page of the ogp-stats-table.

    Player cell structure:
      <td>
        <img ...>
        <a href="https://the-passport.com/players/11511/jalen-davis">Jalen Davis</a>
        Slow Grind Elite
      </td>
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[Player, RosterEntry, SeasonStats]] = []

    # Find the stats table — look for one with a GP header
    target_table = None
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

        player_name = passport_link.get_text(strip=True)
        # Text after the <a> tag is the team name
        link_next = passport_link.next_sibling
        team_name = link_next.strip() if link_next and isinstance(link_next, str) else ""
        if not team_name:
            team_name = player_cell.get_text(separator=" ", strip=True)
            team_name = team_name.replace(player_name, "").strip()

        team_slug = _slug(team_name) if team_name else "unknown"

        parts = player_name.split(None, 1)
        first = parts[0] if parts else player_name
        last = parts[1] if len(parts) > 1 else ""

        gp = safe_int(cell_text(cells, "GP"))
        if not gp:
            continue

        roster_entry = RosterEntry(
            source_team_id=team_slug,
            source_player_id=pid,
        )
        # Stash the human-readable team name so fetch_teams can use it
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
                spg=safe_float(cell_text(cells, "SPG")),
                bpg=safe_float(cell_text(cells, "BPG")),
                fg_pct=safe_float(cell_text(cells, "FG%")),
                three_pt_pct=safe_float(cell_text(cells, "3P%")),
            ),
        ))

    return results
