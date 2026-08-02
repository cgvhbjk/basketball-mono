"""
The Passport player profile enrichment.

For 3SSB players whose passport_id is stored in the DB, fetches
https://the-passport.com/players/{id}/{slug}/overview and extracts any
available bio data (position, height, grad year, hometown). Passport's
"School" stat is a city/state pair rather than an actual school name, so
it's mapped to hometown, not high_school.
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

# The site's router requires a slug + tab segment after the id (e.g.
# /players/145364/aiden-allaire/overview) — a bare /players/{id}/ 404s. The
# slug itself isn't validated server-side, so any placeholder resolves the
# same profile.
BASE_URL = "https://the-passport.com/players/{pid}/profile/overview"
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
            # Heavily client-rendered (Next.js/React) profile — domcontentloaded fires
            # long before the stat rows hydrate from a loading skeleton (~8s observed).
            # networkidle never fires here: the page polls auth-refresh endpoints
            # continuously (401s, since we're not logged in), so wait on a concrete
            # element instead — "Career Stats" renders on every profile's Overview
            # tab regardless of whether the player has bio fields filled in.
            try:
                await page.get_by_text("Career Stats").first.wait_for(timeout=20_000)
            except Exception:
                logger.warning("Career Stats never appeared for %s — parsing whatever loaded", url)
            html = await page.content()
            await browser.close()
            return html
    except Exception as exc:
        logger.warning("Failed to load Passport page %s: %s", url, exc)
        return None


def _parse_profile(html: str) -> Optional[PassportProfile]:
    soup = BeautifulSoup(html, "html.parser")
    profile = PassportProfile()

    # Look for label/value pairs. The site (as of its 2026-07 Next.js rebuild)
    # renders stat rows as a leaf <div>School</div> immediately followed by a
    # sibling <div>value</div> — no th/dt/span/label anywhere, and critically
    # no wrapping <tr>/<li>/<dl> to scope the pair either. Candidates must be
    # leaf elements (no nested tags) — otherwise an ancestor container (e.g.
    # the whole "Height | Class | School" bar) matches as "the label" with
    # its entire concatenated text, which then false-positives on every
    # keyword check at once. Doing this before the whole-page regex fallback
    # matters too: the page has plenty of unrelated 4-digit years and
    # height-shaped strings floating around (nav, footer, other players'
    # cards), so a labeled hit should always win over a blind text scan.
    for label_elem in soup.find_all(["th", "dt", "span", "label", "div"]):
        if label_elem.find(True) is not None:
            continue  # not a leaf — skip containers
        label = label_elem.get_text(strip=True).lower()
        if not label:
            continue
        value_elem = label_elem.find_next_sibling()
        value = value_elem.get_text(strip=True) if value_elem else ""
        if not value:
            continue
        if profile.position is None and "position" in label:
            profile.position = value
        # Passport's "School" stat is actually a city/state pair (e.g. "Poway,
        # CA"), not a school name — confirmed across multiple profiles. Map it
        # to hometown, not high_school, so we don't write locations into a
        # column meant for actual school names.
        if profile.hometown is None and ("school" in label or "city" in label or "hometown" in label):
            profile.hometown = value
        if profile.grad_year is None and "class" in label:
            m = _GRAD_RE.search(value)
            if m:
                profile.grad_year = int(m.group(1))
        if profile.height_inches is None and "height" in label:
            m = _HEIGHT_RE.search(value)
            if m:
                profile.height_inches = int(m.group(1)) * 12 + int(m.group(2))

    # Fallback: whole-page regex scan, only for whatever the labeled pass missed.
    text = soup.get_text(" ", strip=True)
    if profile.height_inches is None:
        m = _HEIGHT_RE.search(text)
        if m:
            profile.height_inches = int(m.group(1)) * 12 + int(m.group(2))
    if profile.grad_year is None:
        m = _GRAD_RE.search(text)
        if m:
            profile.grad_year = int(m.group(1))

    if any([profile.height_inches, profile.grad_year, profile.high_school, profile.position]):
        return profile
    return None
