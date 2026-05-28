"""
PlaywrightFetcher — headless Chromium for JS-rendered pages.

Side effect: logs all XHR/fetch network requests to stdout so you can
identify hidden JSON endpoints and promote them to HttpxFetcher calls.
"""
import logging
from playwright.async_api import async_playwright, Page, Request

from .base_fetcher import BaseFetcher, BlockedError

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_INCAPSULA_MARKER = "_Incapsula_Resource"


class PlaywrightFetcher(BaseFetcher):
    def __init__(self, wait_until: str = "domcontentloaded", timeout_ms: int = 45_000) -> None:
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

    async def fetch_html(self, url: str) -> str:
        await self._ensure_browser()
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

        # Raise on HTTP errors or Incapsula IP-reputation blocks so callers
        # see a real error rather than silently receiving a block page.
        if response and response.status >= 400:
            raise BlockedError(f"HTTP {response.status} from {url}")
        # The _Incapsula_Resource string only appears in the JS that the block
        # interstitial loads. Don't gate on page size — newer Imperva templates
        # ship full-page challenges that comfortably exceed any small threshold.
        if _INCAPSULA_MARKER in html:
            raise BlockedError(f"Incapsula block page from {url}")

        return html

    def _log_xhr(self, request: Request) -> None:
        if request.resource_type in ("xhr", "fetch"):
            logger.info("[XHR captured] %s %s", request.method, request.url)

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
