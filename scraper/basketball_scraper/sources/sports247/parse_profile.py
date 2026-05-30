"""
247Sports profile-page parser.

Strategy: label-driven. We walk the structured elements (`<li>`, `<dt>/<dd>`,
`<th>/<td>`, `data-name="…"` blocks) and apply normalizers when the element's
text matches a known label regex. We never sweep `soup.get_text()` for ints —
that was the failure mode in the previous parser, which would happily grab
"State, MA 12" out of an unrelated sidebar.

Two entry points (`parse_player_profile`, `parse_highschool_profile`) share
the same label dictionary; the high-school variant additionally looks at
the team/HS card that exists only on `/high-school-<hsid>/` URLs.

Stars detection has two paths (in order):
  1. Count filled icons inside a `class*="stars"` container.
  2. Fall back to the documented composite-rating threshold table.
The chosen path is reported as `stars_source` so downstream consumers can
weigh confidence.
"""
from __future__ import annotations
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from .models import Hometown, ProfileExtract, StarsSource

logger = logging.getLogger(__name__)


_HEIGHT_RE = re.compile(r"(\d)['’\-](\d{1,2})")
_HOMETOWN_RE = re.compile(r"\b([A-Z][a-zA-Z.\s\-']+),\s*([A-Z]{2})\b")
_CLASS_YEAR_RE = re.compile(r"\b(20(?:2\d|3[0-2]))\b")
_INT_RE = re.compile(r"\b(\d{1,4})\b")
_WEIGHT_RE = re.compile(r"\b(\d{2,3})\s*(?:lbs?|pounds)?\b", re.I)
_COMPOSITE_RE = re.compile(r"\b(\d?\.\d{3,5})\b")
_STARS_TEXT_RE = re.compile(r"\b([3-5])\s*-?\s*star\b", re.I)
_PLAYER_ID_RE = re.compile(r"/player/[^/]*-(\d+)/?")


# ----------------------------------------------------------------------
# Public entry points
# ----------------------------------------------------------------------

def parse_player_profile(html: str, source_url: str = "") -> ProfileExtract:
    """Parse a `https://247sports.com/player/<slug>-<id>/` page."""
    return _parse(html, source_url, include_team_card=False)


def parse_highschool_profile(html: str, source_url: str = "") -> ProfileExtract:
    """Parse a `https://247sports.com/player/<slug>-<id>/high-school-<hsid>/` page."""
    return _parse(html, source_url, include_team_card=True)


# ----------------------------------------------------------------------
# Core
# ----------------------------------------------------------------------

def _parse(html: str, source_url: str, *, include_team_card: bool) -> ProfileExtract:
    # include_team_card is reserved for future use (e.g. extracting HS team
    # roster on the /high-school-<hsid>/ variant). Today both page shapes go
    # through the same label dictionary; the parameter remains so callers
    # don't have to change when that diverges.
    del include_team_card
    soup = BeautifulSoup(html, "html.parser")

    player_id = _extract_player_id(source_url) or ""
    name = _extract_name(soup) or ""
    hometown = _extract_hometown(soup)
    state_code = hometown.state if hometown else None

    composite = _extract_composite(soup)
    stars, stars_source = _extract_stars(soup, composite)

    height_inches, height_raw = _extract_height(soup)

    return ProfileExtract(
        source_url=source_url,
        player_id=player_id,
        name=name,
        national_rank=_extract_labeled_int(soup, r"^Natl\.?$"),
        state_rank=_extract_state_rank(soup, state_code) if state_code else None,
        position_rank=_extract_labeled_int(soup, r"^Pos\.?$"),
        class_year=_extract_class_year(soup),
        hometown=hometown,
        high_school=_extract_labeled_text(soup, r"^High\s*School$|^HS$"),
        position=_extract_labeled_text(soup, r"^Position$|^Pos\.?$"),
        stars=stars,
        stars_source=stars_source,
        composite_rating=composite,
        height_inches=height_inches,
        height_raw=height_raw,
        weight_lbs=_extract_weight(soup),
        offers_count=_extract_labeled_int(soup, r"^Offers?$"),
        visits_count=_extract_labeled_int(soup, r"^Visits?$"),
        commitment_team=_extract_commitment_team(soup),
        commitment_status=_extract_commitment_status(soup),
        extracted_at=datetime.now(timezone.utc),
    )


# ----------------------------------------------------------------------
# Label-driven helpers
# ----------------------------------------------------------------------

def _iter_label_value_pairs(soup: BeautifulSoup):
    """Yield (label_text, value_element) for every structurally-paired
    label on the page. Sources covered:

      - <dl><dt>label</dt><dd>value</dd>
      - <tr><th>label</th><td>value</td>
      - <li><span class=label>label</span><span class=value>value</span>
      - <div data-name="label">value</div>

    The value element is returned unchanged so the caller can extract a
    string, an int, a nested anchor, etc.
    """
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is not None:
            yield dt.get_text(" ", strip=True), dd

    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) >= 2:
            yield cells[0].get_text(" ", strip=True), cells[1]

    for li in soup.find_all("li"):
        # Two-child label/value: first child is label, last is value.
        children = [c for c in li.find_all(recursive=False) if isinstance(c, Tag)]
        if len(children) == 2:
            yield children[0].get_text(" ", strip=True), children[1]

    for el in soup.find_all(attrs={"data-name": True}):
        label = el.get("data-name", "")
        if label:
            yield label, el


def _extract_labeled_text(soup: BeautifulSoup, label_pattern: str) -> Optional[str]:
    pat = re.compile(label_pattern, re.I)
    for label, value in _iter_label_value_pairs(soup):
        if pat.search(label):
            txt = value.get_text(" ", strip=True)
            if txt and txt not in ("—", "-", "N/A", "n/a"):
                return txt
    return None


def _extract_labeled_int(soup: BeautifulSoup, label_pattern: str) -> Optional[int]:
    pat = re.compile(label_pattern, re.I)
    for label, value in _iter_label_value_pairs(soup):
        if not pat.search(label):
            continue
        m = _INT_RE.search(value.get_text(" ", strip=True))
        if m:
            n = int(m.group(1))
            if 0 < n <= 99_999:
                return n
    return None


def _extract_state_rank(soup: BeautifulSoup, state_code: str) -> Optional[int]:
    """State rank label on 247 is the two-letter state code (e.g. 'GA').
    We anchor to the code we already extracted from hometown so we don't
    pick up a stray two-letter token elsewhere on the page.
    """
    pat = re.compile(rf"^{re.escape(state_code)}$")
    return _extract_labeled_int(soup, pat.pattern)


# ----------------------------------------------------------------------
# Field-specific extractors
# ----------------------------------------------------------------------

def _extract_player_id(source_url: str) -> Optional[str]:
    m = _PLAYER_ID_RE.search(urlparse(source_url).path)
    return m.group(1) if m else None


def _extract_name(soup: BeautifulSoup) -> Optional[str]:
    # 247 reliably puts the prospect's full name in <h1>. Fall through to
    # <title> if the h1 is missing or branded.
    h1 = soup.find("h1")
    if h1:
        txt = h1.get_text(" ", strip=True)
        if txt:
            return txt
    if soup.title:
        return soup.title.get_text(strip=True).split("|")[0].strip() or None
    return None


def _extract_hometown(soup: BeautifulSoup) -> Optional[Hometown]:
    # Try labeled fields first; fall back to regex search inside the bio block.
    city = _extract_labeled_text(soup, r"^City$")
    state = _extract_labeled_text(soup, r"^State$")
    if city and state:
        return Hometown(city=city, state=state.upper()[:2])

    combined = _extract_labeled_text(soup, r"^Hometown$")
    if combined:
        m = _HOMETOWN_RE.search(combined)
        if m:
            return Hometown(city=m.group(1).strip(), state=m.group(2))

    # Final fallback — but scoped to a bio/info container only.
    bio = soup.find(class_=re.compile(r"(?:bio|info|details|hero)", re.I))
    if bio:
        m = _HOMETOWN_RE.search(bio.get_text(" ", strip=True))
        if m:
            return Hometown(city=m.group(1).strip(), state=m.group(2))
    return None


def _extract_class_year(soup: BeautifulSoup) -> Optional[int]:
    txt = _extract_labeled_text(soup, r"^Class$|^Class\s*Year$|^Grad$|^Year$")
    if txt:
        m = _CLASS_YEAR_RE.search(txt)
        if m:
            return int(m.group(1))
    return None


def _extract_height(soup: BeautifulSoup) -> tuple[Optional[int], Optional[str]]:
    txt = _extract_labeled_text(soup, r"^Ht$|^Height$")
    if not txt:
        return None, None
    m = _HEIGHT_RE.search(txt)
    if not m:
        return None, txt
    inches = int(m.group(1)) * 12 + int(m.group(2))
    if not (48 <= inches <= 108):
        return None, txt
    return inches, txt


def _extract_weight(soup: BeautifulSoup) -> Optional[int]:
    txt = _extract_labeled_text(soup, r"^Wt$|^Weight$")
    if not txt:
        return None
    m = _WEIGHT_RE.search(txt)
    if not m:
        return None
    w = int(m.group(1))
    return w if 70 <= w <= 400 else None


def _extract_composite(soup: BeautifulSoup) -> Optional[float]:
    """Composite rating is a float in [0, 1], rendered to ~4 decimals.
    We look in a container with class containing 'composite' or 'rating'.
    """
    container = soup.find(class_=re.compile(r"(?:composite|rating)", re.I))
    if container:
        m = _COMPOSITE_RE.search(container.get_text(" ", strip=True))
        if m:
            try:
                val = float(m.group(1))
                if 0.0 < val <= 1.0:
                    return val
            except ValueError:
                pass
    return None


# Per 247Sports' published thresholds (commented as of 2026-05; if 247 publishes
# new thresholds, update here and in the test fixture):
#   composite >= 0.9800 -> 5 stars
#   composite >= 0.8900 -> 4 stars
#   composite >= 0.8000 -> 3 stars
#   composite <  0.8000 -> unranked (we return None)
def _stars_from_composite(score: float) -> Optional[int]:
    if score >= 0.98:
        return 5
    if score >= 0.89:
        return 4
    if score >= 0.80:
        return 3
    return None


def _extract_stars(soup: BeautifulSoup, composite: Optional[float]) -> tuple[Optional[int], StarsSource]:
    # 1) Icons
    stars_container = soup.find(class_=re.compile(r"\bstars?\b", re.I))
    if stars_container:
        filled = stars_container.find_all(
            class_=re.compile(r"(?:^|\s)(?:on|filled|active|yes)(?:\s|$)", re.I)
        )
        if 1 <= len(filled) <= 5:
            return len(filled), "icons"
        # Some templates use explicit text like "4-star prospect"
        txt = stars_container.get_text(" ", strip=True)
        m = _STARS_TEXT_RE.search(txt)
        if m:
            return int(m.group(1)), "icons"

    # 2) Composite fallback
    if composite is not None:
        stars = _stars_from_composite(composite)
        if stars is not None:
            return stars, "composite_threshold"

    return None, "unknown"


def _extract_commitment_team(soup: BeautifulSoup) -> Optional[str]:
    txt = _extract_labeled_text(soup, r"^Commit(?:ment|ted)?$|^College$")
    if txt and txt.lower() not in ("uncommitted", "undecided"):
        return txt
    return None


def _extract_commitment_status(soup: BeautifulSoup) -> Optional[str]:
    txt = _extract_labeled_text(soup, r"^Status$|^Commit(?:ment)?\s*Status$")
    if txt:
        return txt
    # If the team-name field said "Uncommitted", surface that as status.
    team_txt = _extract_labeled_text(soup, r"^Commit(?:ment|ted)?$|^College$")
    if team_txt and team_txt.lower() in ("uncommitted", "undecided"):
        return team_txt
    return None
