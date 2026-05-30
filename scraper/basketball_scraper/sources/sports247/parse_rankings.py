"""
247Sports ranking-list parser.

Input: a single ranking page (e.g. /season/2026-basketball/recruitrankings/).
Output: an iterator of (profile_url, seed_meta) pairs.

Pagination strategy: prefer `<link rel="next">` / `<a rel="next">`; if neither
exists, increment `?Page=N` (or `?page=N`) while the next page yields rows
with new player IDs. The caller drives the loop (we don't fetch here — that's
fetch.py's job — we just hand back the next URL).
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import Iterator, Optional
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_PLAYER_HREF_RE = re.compile(r"/player/[^/]+-(\d+)/?", re.I)
_RANK_RE = re.compile(r"\b(\d{1,4})\b")


@dataclass
class Seed:
    profile_url: str
    player_id: str
    rank: Optional[int]
    name: Optional[str]


def iter_seeds(html: str, base_url: str) -> Iterator[Seed]:
    """Yield seeds from a single ranking page in document order.

    Dedups within this call by player_id. Callers that span multiple pages
    should maintain their own seen-set.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    for a in soup.find_all("a", href=_PLAYER_HREF_RE):
        m = _PLAYER_HREF_RE.search(a.get("href", ""))
        if not m:
            continue
        player_id = m.group(1)
        if player_id in seen:
            continue
        seen.add(player_id)

        href = a["href"]
        if href.startswith("/"):
            href = urljoin(base_url, href)

        # Rank is usually the leading number in the row; look at the closest
        # row-like ancestor (tr, li, or article).
        row = a.find_parent(["tr", "li", "article", "div"])
        rank: Optional[int] = None
        if row:
            row_text = row.get_text(" ", strip=True)
            m = _RANK_RE.search(row_text)
            if m:
                n = int(m.group(1))
                if 0 < n <= 9_999:
                    rank = n

        name = a.get_text(strip=True) or None
        yield Seed(profile_url=href, player_id=player_id, rank=rank, name=name)


def next_page_url(html: str, current_url: str) -> Optional[str]:
    """Return the URL of the next ranking page, or None if this is the last.

    Strategy in order:
      1. <link rel="next" href="…">
      2. <a rel="next" href="…">
      3. Increment ?Page=N / ?page=N param in `current_url`.
    """
    soup = BeautifulSoup(html, "html.parser")

    link = soup.find("link", rel="next")
    if link and link.get("href"):
        return urljoin(current_url, link["href"])

    a = soup.find("a", rel="next")
    if a and a.get("href"):
        return urljoin(current_url, a["href"])

    parsed = urlparse(current_url)
    qs = dict(parse_qsl(parsed.query))
    page_key = next((k for k in ("Page", "page") if k in qs), None)
    if page_key:
        try:
            qs[page_key] = str(int(qs[page_key]) + 1)
        except ValueError:
            return None
    else:
        qs["Page"] = "2"
    return urlunparse(parsed._replace(query=urlencode(qs)))
