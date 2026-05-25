"""
On3 player profile enrichment — recruiting rankings and bio data.

Searches on3.com by player name and extracts star_rating, national_rank,
state_rank, height_inches, grad_year, and high_school.
"""
from __future__ import annotations
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.on3.com/search/?q={query}"
REQUEST_DELAY = 3.5  # seconds between requests


@dataclass
class On3Profile:
    height_inches: Optional[int] = None
    grad_year: Optional[int] = None
    high_school: Optional[str] = None
    hometown: Optional[str] = None
    star_rating: Optional[int] = None
    national_rank: Optional[int] = None
    state_rank: Optional[int] = None


_HEIGHT_RE = re.compile(r"(\d)[''\-](\d{1,2})")
_GRAD_RE = re.compile(r"\b(20(?:2[4-9]|3[0-2]))\b")
_RANK_RE = re.compile(r"#(\d+)")
_STARS_RE = re.compile(r"\b([1-5])-star\b", re.I)


async def lookup_player_profile(first: str, last: str) -> Optional[On3Profile]:
    query = f"{first} {last}".replace(" ", "+")
    url = SEARCH_URL.format(query=query)
    html = await _fetch_page(url)
    if not html:
        return None
    return _parse_first_match(html, first, last)


async def _fetch_page(url: str) -> Optional[str]:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(2.0)
            html = await page.content()
            await browser.close()
            return html
    except Exception as exc:
        logger.warning("Failed to load On3 page %s: %s", url, exc)
        return None


def _name_matches(text: str, first: str, last: str) -> bool:
    t = text.lower()
    return first.lower() in t and last.lower() in t


def _parse_first_match(html: str, first: str, last: str) -> Optional[On3Profile]:
    soup = BeautifulSoup(html, "html.parser")

    # On3 player links contain /player/ or /db/ in the href
    for link in soup.find_all("a", href=re.compile(r"/(?:player|db)/", re.I)):
        link_text = link.get_text(strip=True)
        if not _name_matches(link_text, first, last):
            continue

        # Walk up to find a card container with profile data
        container = link.parent
        for _ in range(8):
            if container is None:
                break
            t = container.get_text(" ", strip=True)
            if re.search(r"\d[''\-]\d", t) or re.search(r"[1-5]-star", t, re.I) or re.search(r"#\d+", t):
                break
            container = container.parent

        if container is None:
            continue

        text = container.get_text(" ", strip=True)
        profile = On3Profile()

        m = _HEIGHT_RE.search(text)
        if m:
            profile.height_inches = int(m.group(1)) * 12 + int(m.group(2))

        m = _GRAD_RE.search(text)
        if m:
            try:
                profile.grad_year = int(m.group(1))
            except Exception:
                pass

        m = _STARS_RE.search(text)
        if m:
            profile.star_rating = int(m.group(1))

        # National rank — first #N pattern
        ranks = _RANK_RE.findall(text)
        if ranks:
            profile.national_rank = int(ranks[0])
        if len(ranks) > 1:
            profile.state_rank = int(ranks[1])

        # High school — look for school-related elements
        for tag in container.find_all(["a", "span", "div"]):
            cls = " ".join(tag.get("class") or []).lower()
            if any(kw in cls for kw in ("school", "institution", "hs-")):
                val = tag.get_text(strip=True)
                if val and len(val) > 3:
                    profile.high_school = val
                    break

        # Hometown — City, ST pattern
        loc = re.search(r"\b([A-Z][a-zA-Z\s]+),\s*([A-Z]{2})\b", text)
        if loc:
            profile.hometown = loc.group(0)

        if any([profile.height_inches, profile.star_rating, profile.national_rank,
                profile.grad_year, profile.high_school]):
            return profile

        return On3Profile()

    logger.info("No On3 result matched for %s %s", first, last)
    return None
