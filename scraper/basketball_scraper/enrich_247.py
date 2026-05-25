"""
247Sports player profile enrichment.

Searches by player name on 247Sports and extracts height, grad_year,
high_school, and hometown. Requires Playwright (JS-rendered pages).
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

SEARCH_URL = "https://247sports.com/search/?query={query}"
REQUEST_DELAY = 2.5  # seconds between requests — be polite


@dataclass
class PlayerProfile:
    height_inches: Optional[int] = None
    grad_year: Optional[int] = None
    high_school: Optional[str] = None
    hometown: Optional[str] = None


async def lookup_player_profile(first: str, last: str) -> Optional[PlayerProfile]:
    """
    Search 247Sports for a player by name and return available profile data.
    Returns None if the player is not found or the request fails.
    """
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
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()
            await page.goto(url, wait_until="load", timeout=30_000)
            await asyncio.sleep(1.5)  # extra wait for React hydration
            html = await page.content()
            await browser.close()
            return html
    except Exception as exc:
        logger.warning("Failed to load 247Sports page %s: %s", url, exc)
        return None


def _name_matches(text: str, first: str, last: str) -> bool:
    t = text.lower()
    return first.lower() in t and last.lower() in t


def _parse_height(text: str) -> Optional[int]:
    m = re.search(r"(\d)['’\-](\d{1,2})", text)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    return None


def _parse_grad_year(text: str) -> Optional[int]:
    for m in re.finditer(r"\b(20(2[4-9]|3[0-2]))\b", text):
        return int(m.group(1))
    return None


def _parse_first_match(html: str, first: str, last: str) -> Optional[PlayerProfile]:
    soup = BeautifulSoup(html, "html.parser")

    # 247Sports player links all contain /Player/ in the href
    for link in soup.find_all("a", href=re.compile(r"/Player/", re.I)):
        if not _name_matches(link.get_text(strip=True), first, last):
            continue

        # Walk up to find a container that has height/year data
        container = link.parent
        for _ in range(7):
            if container is None:
                break
            t = container.get_text(" ", strip=True)
            if re.search(r"\d['’\-]\d", t) or re.search(r"20(2[4-9]|3[0-2])", t):
                break
            container = container.parent

        if container is None:
            continue

        text = container.get_text(" ", strip=True)
        profile = PlayerProfile(
            height_inches=_parse_height(text),
            grad_year=_parse_grad_year(text),
        )

        # High school: look for an element whose class mentions "school" or "hs"
        hs_elem = container.find(
            lambda tag: tag.name in ("a", "span", "div")
            and any(
                kw in " ".join(tag.get("class") or []).lower()
                for kw in ("school", "-hs", "institution", "commit")
            )
        )
        if hs_elem:
            val = hs_elem.get_text(strip=True)
            if val and len(val) > 3 and val.lower() not in ("n/a", "—", "-"):
                profile.high_school = val

        # Hometown: look for city/state pattern near the player card
        loc_match = re.search(r"\b([A-Z][a-zA-Z\s]+),\s*([A-Z]{2})\b", text)
        if loc_match:
            profile.hometown = loc_match.group(0)

        if profile.height_inches or profile.grad_year or profile.high_school:
            return profile

        # Name matched but no data — return empty profile so caller can mark as checked
        return PlayerProfile()

    logger.info("No 247Sports result matched for %s %s", first, last)
    return None
