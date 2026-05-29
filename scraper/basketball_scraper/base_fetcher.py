"""
Fetcher contract + shared error types.

The actual concrete fetchers live in httpx_fetcher.py and playwright_fetcher.py.
Both call into `reliability.with_retries` and `DomainRateLimiter` so adapters
get retries and polite request pacing for free.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional

from .reliability import DomainRateLimiter
from .snapshots import Snapshot, Snapshotter


class FetchError(Exception):
    pass


class EmptyPageError(FetchError):
    """Raised when a page loads but contains no usable data (JS-rendered shell)."""


class BlockedError(FetchError):
    """Raised when a CDN (Incapsula, Cloudflare) blocks the request by IP or fingerprint."""


# Default polite intervals per host. Override at construction time.
_DEFAULT_DOMAIN_RATES: dict[str, float] = {
    "pointstreak.com":              1.0,
    "exposureevents.com":           0.5,
    "adidas3ssb.com":               0.75,
    "underarmournext.com":          0.75,
    "nxtprohoops.com":              0.5,
    "the-passport.com":             0.5,
}


class BaseFetcher(ABC):
    """
    Subclasses implement `_raw_get(url)` and return (bytes, content_type).
    All public methods funnel through it so retries, rate-limiting, and
    snapshotting are shared.
    """

    def __init__(
        self,
        *,
        rate_limiter: Optional[DomainRateLimiter] = None,
        snapshotter: Optional[Snapshotter] = None,
        adapter_name: str = "unknown",
    ) -> None:
        self._rate_limiter = rate_limiter or DomainRateLimiter(
            default_min_interval=0.5,
            per_host=dict(_DEFAULT_DOMAIN_RATES),
        )
        self._snapshotter = snapshotter
        self._adapter_name = adapter_name

    def with_adapter(self, adapter_name: str) -> "BaseFetcher":
        """Return self after rebinding the adapter tag used for snapshots."""
        self._adapter_name = adapter_name
        return self

    @abstractmethod
    async def _raw_get(self, url: str) -> tuple[bytes, str]:
        """Return (body_bytes, content_type) — concrete fetcher hook."""

    async def fetch_html(self, url: str) -> str:
        """Return the response body as text. Snapshots and rate-limits the call."""
        body, content_type = await self._fetch_with_snapshot(url, default_ct="text/html")
        return body.decode("utf-8", errors="replace")

    async def fetch_json(self, url: str) -> Any:
        """Return the parsed JSON body. Snapshots and rate-limits the call."""
        import json
        body, _ = await self._fetch_with_snapshot(url, default_ct="application/json")
        return json.loads(body.decode("utf-8", errors="replace"))

    async def _fetch_with_snapshot(self, url: str, *, default_ct: str) -> tuple[bytes, str]:
        await self._rate_limiter.acquire(url)
        body, content_type = await self._raw_get(url)
        content_type = content_type or default_ct
        if self._snapshotter is not None:
            self._snapshotter.record(
                adapter_name=self._adapter_name,
                source_url=url,
                content_type=content_type,
                payload=body,
            )
        return body, content_type

    async def close(self) -> None:
        pass


__all__ = [
    "BaseFetcher",
    "BlockedError",
    "EmptyPageError",
    "FetchError",
    "Snapshot",
]
