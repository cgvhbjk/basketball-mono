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
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, BrowserContext
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.on3.com/rivals/search/?searchText={query}"
REQUEST_DELAY = 2.0  # seconds between requests (used by callers)
_HTTPX_TIMEOUT = 20.0

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

# On3's search index spans every sport and every era. Our DB is current
# high-school basketball recruits, so a bare name match happily grabs a
# retired NBA player (LaMarcus Aldridge), a football Edge prospect, or a
# 2002-class namesake — and _profile_score then *prefers* those because
# established players carry the richest bios. Gate every candidate on
# sport == basketball AND a current-ish class year before it's even a
# contender.
_MIN_GRAD_YEAR = 2024
_MAX_GRAD_YEAR = 2035


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

    async def lookup(
        self, first: str, last: str, grad_year: Optional[int] = None
    ) -> Optional[On3Profile]:
        if self._context is None:
            raise RuntimeError("On3Enricher must be used as an async context manager")
        query = f"{first}+{last}"
        url = SEARCH_URL.format(query=query)

        # On3 ships __NEXT_DATA__ inline on SSR, so the fast path is plain
        # httpx — Playwright was getting Cloudflare-flagged in production and
        # returning shells without the JSON payload. Fall back to a real
        # browser only if httpx returns empty / non-JSON HTML.
        html = await _fetch_httpx(url)
        source = "httpx"
        if not _has_next_data(html):
            logger.info("On3 httpx empty for %s %s — falling back to Playwright", first, last)
            html = await self._fetch_playwright(url)
            source = "playwright"

        if not html:
            logger.info("On3 fetch failed for %s %s (source=%s)", first, last, source)
            return None
        if not _has_next_data(html):
            logger.info("On3 no __NEXT_DATA__ for %s %s (source=%s, len=%d)",
                        first, last, source, len(html))
            return None

        profile = _parse_search_results(html, first, last, grad_year)
        if profile is None:
            logger.info("On3: no match for %s %s (source=%s)", first, last, source)
        return profile

    async def _fetch_playwright(self, url: str) -> Optional[str]:
        assert self._context is not None
        page = await self._context.new_page()
        try:
            await Stealth().apply_stealth_async(page)
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await asyncio.sleep(3.0)
            return await page.content()
        except Exception as exc:
            logger.warning("On3 playwright fetch failed %s: %s", url, exc)
            return None
        finally:
            await page.close()


async def _fetch_httpx(url: str) -> Optional[str]:
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTPX_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                logger.info("On3 httpx %s -> %d", url, r.status_code)
                return None
            return r.text
    except Exception as exc:
        logger.warning("On3 httpx fetch failed %s: %s", url, exc)
        return None


def _has_next_data(html: Optional[str]) -> bool:
    return bool(html) and "__NEXT_DATA__" in html


async def lookup_player_profile(
    first: str, last: str, grad_year: Optional[int] = None
) -> Optional[On3Profile]:
    """Standalone lookup — creates a fresh browser per call. Use On3Enricher for batches."""
    async with On3Enricher() as enricher:
        return await enricher.lookup(first, last, grad_year)


def _candidate_grad_year(obj: dict) -> Optional[int]:
    """Read a plausible class/grad year off a search-result dict, if present."""
    for key in ("classYear", "gradYear", "graduationYear", "year"):
        val = obj.get(key)
        if isinstance(val, bool):  # bool is an int subclass — skip
            continue
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.strip().isdigit():
            return int(val.strip())
    return None


def _is_basketball_recruit(obj: dict) -> bool:
    """True only for current-era basketball players. On3 search results carry
    a `sport` dict and a `classYear`; both must say 'a basketball recruit
    graduating in the current window' or this is a wrong-sport / wrong-era
    namesake we must not match."""
    sport = obj.get("sport")
    sport_name = sport.get("name") if isinstance(sport, dict) else sport
    if not isinstance(sport_name, str) or sport_name.strip().lower() != "basketball":
        return False
    gy = _candidate_grad_year(obj)
    if gy is None or not (_MIN_GRAD_YEAR <= gy <= _MAX_GRAD_YEAR):
        return False
    return True


# ----------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------

def _ascii_fold(s: str) -> str:
    """Lowercase + drop diacritics so 'José' matches 'Jose'."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    ).lower()


def _name_matches(text: str, first: str, last: str) -> bool:
    if len(first) < 2 or len(last) < 2:
        return False
    t = _ascii_fold(text)
    return _ascii_fold(first) in t and _ascii_fold(last) in t


def _parse_search_results(
    html: str, first: str, last: str, grad_year: Optional[int] = None
) -> Optional[On3Profile]:
    soup = BeautifulSoup(html, "html.parser")

    # 1. Try Next.js __NEXT_DATA__ — most reliable since it's structured JSON
    script = soup.find("script", id="__NEXT_DATA__")
    if script and script.string:
        try:
            data = json.loads(script.string)
            profile = _extract_from_next_data(data, first, last, grad_year)
            if profile is not None:
                return profile
        except Exception as exc:
            logger.debug("On3 __NEXT_DATA__ parse failed: %s", exc)

    # 2. Fall back to DOM scraping
    profile = _parse_dom(soup, first, last)
    if profile is None:
        logger.debug("On3 DOM fallback: no match in %d chars of HTML", len(html))
    return profile


def _profile_score(p: On3Profile) -> int:
    """Rank candidate profiles by how much recruiting data they carry. Names
    can resolve to multiple on3 records (e.g. LeBron James returns the pro
    AND Bronny) — we want the one with star ratings and ranks, not the
    elder with only a height. Higher is better."""
    score = 0
    if p.star_rating is not None:
        score += 8
    if p.national_rank is not None:
        score += 4
    if p.state_rank is not None:
        score += 2
    if p.grad_year is not None:
        score += 4
    if p.high_school:
        score += 1
    if p.height_inches is not None:
        score += 1
    if p.hometown:
        score += 1
    return score


def _extract_from_next_data(
    data: Any, first: str, last: str, grad_year: Optional[int] = None
) -> Optional[On3Profile]:
    candidates: list[dict] = []
    _collect_player_dicts(data, candidates, first, last)
    best: Optional[On3Profile] = None
    best_score = -1
    for obj in candidates:
        profile = _player_dict_to_profile(obj)
        score = _profile_score(profile)
        # When the DB knows the player's class, prefer the candidate whose
        # On3 class year matches it — disambiguates same-name same-sport kids
        # across recruiting years (e.g. the 2025 vs 2020 Cameron Boozer rows).
        if grad_year is not None and _candidate_grad_year(obj) == grad_year:
            score += 20
        if score > best_score:
            best = profile
            best_score = score
    return best


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
        # Name match alone is not enough — only a current basketball recruit is
        # a valid candidate, else namesakes from other sports/eras win.
        if _name_matches(name_vals, first, last) and _is_basketball_recruit(node):
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
