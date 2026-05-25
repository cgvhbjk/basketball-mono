"""
The Passport player profile enrichment.

For 3SSB players whose passport_id is stored in the DB, fetches
https://the-passport.com/players/{id}/ and extracts any available
bio data (position, height, grad year, high school).
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

BASE_URL = "https://the-passport.com/players/{pid}/"
REQUEST_DELAY = 2.0

_HEIGHT_RE = re.compile(r"(\d)[''\-](\d{1,2})")
_GRAD_RE = re.compile(r"\b(20(?:2[4-9]|3[0-2]))\b")


@dataclass
class PassportProfile:
    height_inches: Optional[int] = None
    grad_year: Optional[int] = None
    high_school: Optional[str] = None
    position: Optional[str] = None
    hometown: Optional[str] = None


async def lookup_passport_profile(passport_id: str) -> Optional[PassportProfile]:
    url = BASE_URL.format(pid=passport_id)
    html = await _fetch_page(url)
    if not html:
        return None
    return _parse_profile(html)


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
            await asyncio.sleep(1.5)
            html = await page.content()
            await browser.close()
            return html
    except Exception as exc:
        logger.warning("Failed to load Passport page %s: %s", url, exc)
        return None


def _parse_profile(html: str) -> Optional[PassportProfile]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    profile = PassportProfile()

    m = _HEIGHT_RE.search(text)
    if m:
        profile.height_inches = int(m.group(1)) * 12 + int(m.group(2))

    m = _GRAD_RE.search(text)
    if m:
        try:
            profile.grad_year = int(m.group(1))
        except Exception:
            pass

    # Look for label/value pairs in definition lists, tables, or dt/dd
    for row in soup.find_all(["tr", "li", "div"]):
        label_elem = row.find(["th", "dt", "span", "label"])
        if not label_elem:
            continue
        label = label_elem.get_text(strip=True).lower()
        value_elem = label_elem.find_next_sibling()
        value = value_elem.get_text(strip=True) if value_elem else ""
        if not value:
            continue
        if profile.position is None and "position" in label:
            profile.position = value
        if profile.high_school is None and "school" in label:
            profile.high_school = value
        if profile.hometown is None and ("city" in label or "hometown" in label):
            profile.hometown = value

    if any([profile.height_inches, profile.grad_year, profile.high_school, profile.position]):
        return profile
    return None
