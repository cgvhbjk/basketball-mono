"""
PlaywrightFetcher — headless Chromium for JS-rendered pages.

Side effect: logs all XHR/fetch network requests at INFO so devs can identify
hidden JSON endpoints and promote them to HttpxFetcher (the JSON-first path).
"""
from __future__ import annotations
import logging
from playwright.async_api import async_playwright, Page, Request

from .base_fetcher import BaseFetcher, BlockedError
from .reliability import with_retries

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_INCAPSULA_MARKER = "_Incapsula_Resource"


class PlaywrightFetcher(BaseFetcher):
    def __init__(
        self,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 45_000,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._wait_until = wait_until
        self._timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self) -> None:
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )

    async def _raw_get(self, url: str) -> tuple[bytes, str]:
        await self._ensure_browser()

        async def _do() -> tuple[bytes, str]:
            context = await self._browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 800},
            )
            page: Page = await context.new_page()
            page.on("request", self._log_xhr)

            try:
                response = await page.goto(url, wait_until=self._wait_until, timeout=self._timeout_ms)
                html = await page.content()
            finally:
                await context.close()

            if response and response.status >= 400:
                raise BlockedError(f"HTTP {response.status} from {url}")
            if _INCAPSULA_MARKER in html:
                raise BlockedError(f"Incapsula block page from {url}")
            return html.encode("utf-8"), "text/html"

        # Playwright errors are usually transient (timeouts, navigation aborts).
        # CDN blocks raise BlockedError — never retry those.
        from playwright.async_api import Error as PWError
        return await with_retries(
            _do,
            retries=2,
            retryable=(PWError, TimeoutError),
        )

    def _log_xhr(self, request: Request) -> None:
        if request.resource_type in ("xhr", "fetch"):
            logger.info("[XHR captured] %s %s", request.method, request.url)

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
