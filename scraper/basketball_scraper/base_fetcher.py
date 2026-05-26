from abc import ABC, abstractmethod


class FetchError(Exception):
    pass


class EmptyPageError(FetchError):
    """Raised when a page loads but contains no usable data (JS-rendered shell)."""
    pass


class BlockedError(FetchError):
    """Raised when a CDN (Incapsula, Cloudflare) blocks the request by IP or fingerprint."""
    pass


class BaseFetcher(ABC):
    @abstractmethod
    async def fetch_html(self, url: str) -> str:
        """Return the full HTML string for the given URL."""

    async def close(self) -> None:
        pass
