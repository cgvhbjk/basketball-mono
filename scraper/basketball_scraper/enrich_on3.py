"""
On3 player profile enrichment — recruiting rankings and bio data.

Searches on3.com by player name and extracts star_rating, national_rank,
state_rank, height_inches, grad_year, and high_school.

Preferred usage (one browser shared across all lookups):
    async with On3Enricher() as enricher:
        profile = await enricher.lookup("LeBron", "James")

Standalone usage (fresh browser per call — slow):
    profile = await lookup_player_profile("LeBron", "James")
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, BrowserContext
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.on3.com/rivals/search/?searchText={query}"
REQUEST_DELAY = 2.0  # seconds between requests (used by callers)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class On3Profile:
    height_inches: Optional[int] = None
    grad_year: Optional[int] = None
    high_school: Optional[str] = None
    hometown: Optional[str] = None
    star_rating: Optional[int] = None
    national_rank: Optional[int] = None
    state_rank: Optional[int] = None


_HEIGHT_RE = re.compile(r"([4-8])['''](\d{1,2})")
_GRAD_RE = re.compile(r"\b(20(?:2[4-9]|3[0-2]))\b")
_RANK_RE = re.compile(r"#(\d+)")
_STARS_RE = re.compile(r"\b([1-5])-star\b", re.I)
_PROFILE_HREF_RE = re.compile(r"/(?:player|db|recruit)/[a-z0-9\-]+/?", re.I)


class On3Enricher:
    """
    Manages a shared Playwright browser session across many On3 lookups.
    Must be used as an async context manager so the browser is properly closed.
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self) -> "On3Enricher":
        # If anything between launch() and the final assignment raises, Python
        # skips __aexit__, leaving the Chromium process and Playwright driver
        # orphaned. Wrap the partial setup so we can clean up before re-raising.
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            self._context = await self._browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 800},
            )
        except Exception:
            await self._cleanup()
            raise
        return self

    async def _cleanup(self) -> None:
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def __aexit__(self, *_: Any) -> None:
        await self._cleanup()

    async def lookup(self, first: str, last: str) -> Optional[On3Profile]:
        if self._context is None:
            raise RuntimeError("On3Enricher must be used as an async context manager")
        query = f"{first}+{last}"
        url = SEARCH_URL.format(query=query)
        html = await self._fetch(url)
        if not html:
            return None
        profile = _parse_search_results(html, first, last)
        if profile is None:
            logger.info("On3: no match for %s %s", first, last)
        return profile

    async def _fetch(self, url: str) -> Optional[str]:
        assert self._context is not None
        page = await self._context.new_page()
        try:
            await Stealth().apply_stealth_async(page)
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await asyncio.sleep(3.0)
            return await page.content()
        except Exception as exc:
            logger.warning("On3 fetch failed %s: %s", url, exc)
            return None
        finally:
            await page.close()


async def lookup_player_profile(first: str, last: str) -> Optional[On3Profile]:
    """Standalone lookup — creates a fresh browser per call. Use On3Enricher for batches."""
    async with On3Enricher() as enricher:
        return await enricher.lookup(first, last)


# ----------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------

def _name_matches(text: str, first: str, last: str) -> bool:
    if len(first) < 2 or len(last) < 2:
        return False
    t = text.lower()
    return first.lower() in t and last.lower() in t


def _parse_search_results(html: str, first: str, last: str) -> Optional[On3Profile]:
    soup = BeautifulSoup(html, "html.parser")

    # 1. Try Next.js __NEXT_DATA__ — most reliable since it's structured JSON
    script = soup.find("script", id="__NEXT_DATA__")
    if script and script.string:
        try:
            data = json.loads(script.string)
            profile = _extract_from_next_data(data, first, last)
            if profile is not None:
                return profile
        except Exception as exc:
            logger.debug("On3 __NEXT_DATA__ parse failed: %s", exc)

    # 2. Fall back to DOM scraping
    profile = _parse_dom(soup, first, last)
    if profile is None:
        logger.debug("On3 DOM fallback: no match in %d chars of HTML", len(html))
    return profile


def _extract_from_next_data(data: Any, first: str, last: str) -> Optional[On3Profile]:
    candidates: list[dict] = []
    _collect_player_dicts(data, candidates, first, last)
    for obj in candidates:
        profile = _player_dict_to_profile(obj)
        if any([profile.height_inches, profile.star_rating, profile.national_rank, profile.grad_year]):
            return profile
    return None


def _collect_player_dicts(
    node: Any, out: list[dict], first: str, last: str, depth: int = 0
) -> None:
    if depth > 15:
        return
    if isinstance(node, dict):
        name_vals = " ".join(
            str(node.get(f, ""))
            for f in ("name", "playerName", "fullName", "firstName", "lastName")
        )
        if _name_matches(name_vals, first, last):
            out.append(node)
        for v in node.values():
            _collect_player_dicts(v, out, first, last, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _collect_player_dicts(item, out, first, last, depth + 1)


def _player_dict_to_profile(obj: dict) -> On3Profile:
    profile = On3Profile()

    # On3 /rivals/search/ returns height as an integer in inches at top level.
    for key in ("height", "heightDisplay", "heightInches"):
        val = obj.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)) and 48 <= val <= 108:
            profile.height_inches = int(val)
            break
        if isinstance(val, str):
            m = _HEIGHT_RE.search(val)
            if m:
                h = int(m.group(1)) * 12 + int(m.group(2))
                if 48 <= h <= 108:
                    profile.height_inches = h
                    break

    for key in ("classYear", "gradYear", "graduationYear", "year"):
        val = obj.get(key)
        if isinstance(val, int) and 2024 <= val <= 2032:
            profile.grad_year = val
            break
        if isinstance(val, str):
            m = _GRAD_RE.match(val.strip())
            if m:
                try:
                    profile.grad_year = int(val.strip())
                    break
                except ValueError:
                    pass

    # Rankings live inside obj["rating"] as consensusStars / consensusNationalRank /
    # consensusStateRank in the new /rivals/search/ API. Older API variants may
    # return "rating" as a plain integer — handle both shapes.
    rating_raw = obj.get("rating")
    rating_sub = rating_raw if isinstance(rating_raw, dict) else {}
    for key in ("stars", "starRating"):
        val = obj.get(key)
        if isinstance(val, int) and 1 <= val <= 5:
            profile.star_rating = val
            break
    if profile.star_rating is None:
        # Accept float too — On3 half-star UIs sometimes surface 4.5 in the API.
        # Exclude bool since `isinstance(True, int)` is True in Python.
        if (
            isinstance(rating_raw, (int, float))
            and not isinstance(rating_raw, bool)
            and 1 <= rating_raw <= 5
        ):
            profile.star_rating = int(rating_raw)
        else:
            val = rating_sub.get("consensusStars")
            if (
                isinstance(val, (int, float))
                and not isinstance(val, bool)
                and 1 <= val <= 5
            ):
                profile.star_rating = int(val)

    for key in ("nationalRank", "nationalRating", "ranking", "rank"):
        val = obj.get(key)
        if isinstance(val, int) and val > 0:
            profile.national_rank = val
            break
    if profile.national_rank is None:
        val = rating_sub.get("consensusNationalRank")
        if isinstance(val, int) and val > 0:
            profile.national_rank = val

    for key in ("stateRank", "stateRating"):
        val = obj.get(key)
        if isinstance(val, int) and val > 0:
            profile.state_rank = val
            break
    if profile.state_rank is None:
        val = rating_sub.get("consensusStateRank")
        if isinstance(val, int) and val > 0:
            profile.state_rank = val

    for key in ("school", "highSchool", "highSchoolName", "currentSchool", "schoolName"):
        val = obj.get(key)
        if isinstance(val, str) and len(val) > 3:
            profile.high_school = val
            break
        if isinstance(val, dict):
            name = val.get("name") or val.get("schoolName") or ""
            if isinstance(name, str) and len(name) > 3:
                profile.high_school = name
                break

    # On3 /rivals/search/ has "homeTownName": "City, ST" (string) and "hometown" (dict).
    for key in ("homeTownName", "hometown", "city", "location"):
        val = obj.get(key)
        if isinstance(val, str) and len(val) > 2:
            profile.hometown = val
            break

    return profile


def _parse_dom(soup: BeautifulSoup, first: str, last: str) -> Optional[On3Profile]:
    for link in soup.find_all("a", href=_PROFILE_HREF_RE):
        link_text = link.get_text(separator=" ", strip=True)
        if not _name_matches(link_text, first, last):
            continue

        container = link.parent
        for _ in range(12):
            if container is None:
                break
            t = container.get_text(" ", strip=True)
            if (
                _HEIGHT_RE.search(t)
                or re.search(r"[1-5]-star", t, re.I)
                or _RANK_RE.search(t)
                or _GRAD_RE.search(t)
            ):
                break
            container = container.parent

        if container is None:
            continue

        text = container.get_text(" ", strip=True)
        profile = On3Profile()

        m = _HEIGHT_RE.search(text)
        if m:
            h = int(m.group(1)) * 12 + int(m.group(2))
            if 48 <= h <= 108:
                profile.height_inches = h

        m = _GRAD_RE.search(text)
        if m:
            try:
                profile.grad_year = int(m.group(1))
            except Exception:
                pass

        m = _STARS_RE.search(text)
        if m:
            profile.star_rating = int(m.group(1))

        ranks = _RANK_RE.findall(text)
        if ranks:
            profile.national_rank = int(ranks[0])
        if len(ranks) > 1:
            profile.state_rank = int(ranks[1])

        for tag in container.find_all(["a", "span", "div"]):
            cls = " ".join(tag.get("class") or []).lower()
            if any(kw in cls for kw in ("school", "institution", "hs-", "highschool")):
                val = tag.get_text(strip=True)
                if val and len(val) > 3:
                    profile.high_school = val
                    break

        loc = re.search(r"\b([A-Z][a-zA-Z\s]+),\s*([A-Z]{2})\b", text)
        if loc:
            profile.hometown = loc.group(0)

        if any([profile.height_inches, profile.star_rating, profile.national_rank,
                profile.grad_year, profile.high_school]):
            return profile

        return On3Profile()

    return None
