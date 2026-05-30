"""
PlaywrightFetcher — headless Chromium for JS-rendered pages.

Side effect: logs all XHR/fetch network requests at INFO so devs can identify
hidden JSON endpoints and promote them to HttpxFetcher (the JSON-first path).
"""
from __future__ import annotations
import logging
from playwright.async_api import async_playwright, Page, Request, Error as PWError

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
        # When set, wait for this CSS selector to appear before reading content.
        # Lets callers ride through a JS bot-challenge that 202s a placeholder
        # shell and only renders real markup (e.g. roster links) once it passes.
        self._wait_selector: str | None = None

    def set_wait_selector(self, selector: str | None) -> None:
        self._wait_selector = selector

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
                # SPA / CDN-challenge sites (e.g. UA Next, which 202s then runs a
                # JS challenge that re-navigates) keep changing the page after
                # domcontentloaded, so content() races with an in-flight
                # navigation ("page is navigating and changing the content").
                # Let the network settle, then poll content() across navigations
                # until the frame is stable. networkidle can legitimately time
                # out on keepalive/long-poll pages, so that failure is non-fatal.
                # Prefer waiting on the real content marker: it rides through
                # the bot-challenge shell and means we can read immediately.
                # Fall back to networkidle only when no selector is given —
                # UA Next pings analytics on a keepalive, so networkidle never
                # settles and would burn the full timeout on every page.
                if self._wait_selector:
                    try:
                        await page.wait_for_selector(self._wait_selector, timeout=self._timeout_ms)
                    except PWError:
                        pass  # genuinely-empty page (e.g. team with no roster) — proceed
                else:
                    try:
                        await page.wait_for_load_state("networkidle", timeout=self._timeout_ms)
                    except PWError:
                        pass
                html = None
                for _ in range(6):
                    try:
                        html = await page.content()
                        break
                    except PWError:
                        try:
                            await page.wait_for_load_state("load", timeout=5_000)
                        except PWError:
                            await page.wait_for_timeout(1_000)
                if html is None:
                    html = await page.content()  # final try — let it raise if still racing
            finally:
                await context.close()

            if response and response.status >= 400:
                raise BlockedError(f"HTTP {response.status} from {url}")
            if _INCAPSULA_MARKER in html:
                raise BlockedError(f"Incapsula block page from {url}")
            return html.encode("utf-8"), "text/html"

        # Playwright errors are usually transient (timeouts, navigation aborts).
        # CDN blocks raise BlockedError — never retry those.
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
