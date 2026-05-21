"""
PlaywrightFetcher — headless Chromium for JS-rendered pages.

Side effect: logs all XHR/fetch network requests to stdout so you can
identify hidden JSON endpoints and promote them to HttpxFetcher calls.
"""
import logging
from playwright.async_api import async_playwright, Page, Request

from .base_fetcher import BaseFetcher

logger = logging.getLogger(__name__)


class PlaywrightFetcher(BaseFetcher):
    def __init__(self, wait_until: str = "domcontentloaded", timeout_ms: int = 45_000) -> None:
        self._wait_until = wait_until
        self._timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self) -> None:
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)

    async def fetch_html(self, url: str) -> str:
        await self._ensure_browser()
        context = await self._browser.new_context()
        page: Page = await context.new_page()

        page.on("request", self._log_xhr)

        await page.goto(url, wait_until=self._wait_until, timeout=self._timeout_ms)
        html = await page.content()
        await context.close()
        return html

    def _log_xhr(self, request: Request) -> None:
        if request.resource_type in ("xhr", "fetch"):
            logger.info("[XHR captured] %s %s", request.method, request.url)

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
