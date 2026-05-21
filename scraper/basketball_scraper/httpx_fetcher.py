import httpx
from .base_fetcher import BaseFetcher, EmptyPageError

# Markers that indicate a real data page vs a JS-rendered shell
_DATA_MARKERS = ["<table", "<tr", "data-player", "data-team"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class HttpxFetcher(BaseFetcher):
    def __init__(self, timeout: float = 20.0) -> None:
        self._client = httpx.AsyncClient(headers=HEADERS, timeout=timeout, follow_redirects=True)

    async def fetch_html(self, url: str) -> str:
        response = await self._client.get(url)
        response.raise_for_status()
        html = response.text
        if not any(marker in html for marker in _DATA_MARKERS):
            raise EmptyPageError(f"No data markers found — page may be JS-rendered: {url}")
        return html

    async def close(self) -> None:
        await self._client.aclose()
