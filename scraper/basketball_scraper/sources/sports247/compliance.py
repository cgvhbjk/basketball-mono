"""
Compliance gates for the 247Sports extractor.

Two layers:
  1. Hard-coded host allow-list — only 247sports.com (and www) pass.
  2. robots.txt — fetched once per process, parsed with stdlib
     urllib.robotparser. 247's robots Disallows *.json so JSON endpoints
     never reach the wire even if a caller constructs a URL pointing at one.

There is no `--respect-robots=false` flag. The compliance switch is the
absence of a bypass; if a URL is refused, use the offline `parse` subcommand
on a manually-saved HTML file instead.
"""
from __future__ import annotations
import logging
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)


_ALLOWED_HOSTS = {"247sports.com", "www.247sports.com"}
_ROBOTS_URL = "https://247sports.com/robots.txt"


class DisallowedURL(Exception):
    """Raised when a URL is blocked by allow-list or robots.txt.

    The message is plain-English so the CLI can print it and exit 1.
    """


class RobotsGuard:
    """Allow-list + robots.txt check.

    `fixture` lets tests inject pinned robots.txt content so the suite never
    hits the network. Production code constructs without a fixture and the
    guard fetches once on first `is_allowed()` call.
    """

    def __init__(self, ua: str, *, fixture: Optional[str] = None) -> None:
        self._ua = ua
        self._fixture = fixture
        self._parser: Optional[RobotFileParser] = None

    async def is_allowed(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        if host not in _ALLOWED_HOSTS:
            return False
        # 247's robots.txt Disallows *.json. Python's urllib.robotparser
        # honors `*` wildcards inconsistently across versions, so we treat
        # the JSON-suffix block as a hardcoded rule on top of the parser
        # check — belt and braces, since this is the user-spec line we
        # promised to honor unconditionally.
        path = urlparse(url).path.lower()
        if path.endswith(".json"):
            return False
        parser = await self._get_parser()
        return parser.can_fetch(self._ua, url)

    async def ensure_allowed(self, url: str) -> None:
        """Raise DisallowedURL if `is_allowed(url)` would be False.

        Centralizes the error-message wording so the CLI can catch one
        exception type instead of branching on bool returns.
        """
        if not await self.is_allowed(url):
            raise DisallowedURL(
                f"URL refused by compliance guard: {url}\n"
                "  Save the page manually in a browser and run the offline parser:\n"
                "    python -m basketball_scraper.sources.sports247 parse --html <path>"
            )

    async def _get_parser(self) -> RobotFileParser:
        if self._parser is not None:
            return self._parser
        parser = RobotFileParser()
        parser.set_url(_ROBOTS_URL)
        if self._fixture is not None:
            parser.parse(self._fixture.splitlines())
        else:
            # Fetch synchronously through httpx — robots is small and we only
            # do this once per process. Using urllib's built-in read() would
            # bypass our UA + timeout controls.
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(_ROBOTS_URL, headers={"User-Agent": self._ua})
                    resp.raise_for_status()
                    parser.parse(resp.text.splitlines())
            except Exception as exc:
                # If robots.txt can't be loaded, fail closed: treat everything
                # as disallowed. This is stricter than RFC 9309 (which says
                # 5xx → assume allowed) but matches "compliance-first" intent.
                logger.warning("robots.txt fetch failed (%s) — failing closed", exc)
                parser.parse(["User-agent: *", "Disallow: /"])
        self._parser = parser
        return parser
