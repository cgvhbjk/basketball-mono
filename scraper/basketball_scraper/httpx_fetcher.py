"""
HttpxFetcher — plain HTTP(S) with retries + per-domain rate limiting.

Raises EmptyPageError when the body looks like a JS-rendered shell so the
caller can fall back to PlaywrightFetcher.
"""
from __future__ import annotations
import logging
import httpx

from .base_fetcher import BaseFetcher, EmptyPageError, BlockedError
from .reliability import with_retries

logger = logging.getLogger(__name__)

# Markers that indicate a real data page vs a JS-rendered shell. We only
# enforce these for HTML content; JSON responses skip the check.
#
# Pointstreak templates omit <table> tags (links live in divs), and other
# circuits surface their data via vendor-specific URL params, so the marker
# list combines structural ("<table") and link-shape ("teamid=", "spid=")
# signals. A real data page hits at least one; a JS shell or block page
# hits none.
_HTML_DATA_MARKERS = [
    "<table",
    "<tr",
    "<tbody",
    "data-player",
    "data-team",
    "teamid=",     # Pointstreak
    "playerid=",   # Pointstreak
    "stid=",       # UAA underarmournext.com
    "spid=",       # UAA underarmournext.com
    "the-passport.com/players/",  # Adidas 3SSB / OGP
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
}


class HttpxFetcher(BaseFetcher):
    def __init__(self, timeout: float = 20.0, **kwargs) -> None:
        super().__init__(**kwargs)
        self._client = httpx.AsyncClient(headers=HEADERS, timeout=timeout, follow_redirects=True)

    async def _raw_get(self, url: str) -> tuple[bytes, str]:
        async def _do() -> tuple[bytes, str]:
            response = await self._client.get(url)
            if response.status_code in (403, 503) and "incapsula" in response.text.lower():
                raise BlockedError(f"Incapsula block ({response.status_code}) from {url}")
            response.raise_for_status()
            ct = response.headers.get("content-type", "")
            body = response.content
            if "html" in ct.lower():
                # Scan the full body — Pointstreak templates put a large CSS
                # block before the first <table, so any partial-body check
                # gives false positives.
                text = body.decode("utf-8", "ignore")
                if not any(m in text for m in _HTML_DATA_MARKERS):
                    raise EmptyPageError(f"No data markers in HTML body: {url}")
            return body, ct

        # Don't retry permanent CDN blocks or empty-shell pages — both will
        # keep failing identically; let the caller swap fetchers.
        return await with_retries(
            _do,
            retries=3,
            retryable=(httpx.RemoteProtocolError, httpx.ConnectError, httpx.NetworkError, httpx.TimeoutException, httpx.HTTPStatusError),
        )

    async def close(self) -> None:
        await self._client.aclose()
