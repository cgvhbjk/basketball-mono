"""
Caching browser client for 247Sports.

Design:
  - Per-host rate limit: 5 s between requests (~0.2 rps) via the existing
    DomainRateLimiter. Polite even by 247's own crawl-delay standards.
  - On-disk cache under `scraper/.cache/sports247/`, keyed by sha256(url).
    Each cache entry is body bytes + a small JSON sidecar with fetched_at.
    Cache hits inside the freshness window skip the browser entirely.
  - Cache TTL: 14 days for profile pages (rarely change), 1 day for ranking
    pages (recompute weekly-ish on 247). Override per call via `max_age`.
  - Compliance gate: every request runs through RobotsGuard.ensure_allowed
    *before* the rate limiter wakes us up. A disallowed URL never causes a
    network call.
  - Fetch transport: headless Chromium via Playwright + playwright-stealth.
    247 returns 403 to plain HTTP clients (TLS/HTTP/2 fingerprinting) AND
    to unpatched headless browsers (`navigator.webdriver === true`, missing
    plugin/language arrays, etc.). The stealth patches mask those obvious
    automation tells so the page renders. This is NOT proxy rotation, NOT
    captcha solving, NOT IP evasion, NOT account credential abuse. It only
    stops the browser from self-identifying as a bot before any content is
    served.

Lifecycle: one Playwright browser per fetcher instance, reused across all
GETs (much cheaper than launching per request). `close()` must be called.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from ...reliability import DomainRateLimiter, with_retries
from .compliance import RobotsGuard

logger = logging.getLogger(__name__)


_DEFAULT_CACHE_DIR = Path(
    os.environ.get("SPORTS247_CACHE_DIR", "scraper/.cache/sports247")
).expanduser()

_CONTACT = os.environ.get("SCRAPER_CONTACT_EMAIL", "scraper@local")
# Identify as Safari/WebKit on macOS. We're driving Playwright's WebKit
# engine — same kernel Safari uses — so this UA is structurally honest, just
# tagged with a compliance-contact suffix per project policy.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15 "
    f"(compliance-contact: {_CONTACT})"
)

# Pick the Playwright browser engine. WebKit is the Safari engine and gives
# 247's defenses a non-Chromium TLS fingerprint to chew on — empirically more
# likely to pass through CF-style bot shields tuned for Chrome automation.
# Override with SPORTS247_ENGINE=chromium if you want to compare.
_ENGINE = os.environ.get("SPORTS247_ENGINE", "webkit").lower()

# Default 14 days; ranking pages override to ~1 day at call sites.
DEFAULT_MAX_AGE_SECONDS = 14 * 24 * 3600

_HOST_INTERVAL_SECONDS = 5.0  # ~0.2 rps


@dataclass
class _CacheEntry:
    body: bytes
    fetched_at: float  # epoch seconds


class CachingFetcher:
    def __init__(
        self,
        *,
        guard: RobotsGuard,
        cache_dir: Path = _DEFAULT_CACHE_DIR,
        timeout: float = 45.0,
    ) -> None:
        self._guard = guard
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._rate_limiter = DomainRateLimiter(
            default_min_interval=_HOST_INTERVAL_SECONDS,
            per_host={"247sports.com": _HOST_INTERVAL_SECONDS},
        )
        self._timeout_ms = int(timeout * 1000)
        # When SPORTS247_CHROME_PROFILE is set, we launch the user's real
        # Chrome with their actual user-data-dir (cookies, fingerprint, etc).
        # That's what gets past 247's CDN edge — TLS + cookie state match a
        # real browser because they ARE one.
        self._profile_dir = os.environ.get("SPORTS247_CHROME_PROFILE")
        self._playwright = None
        self._browser = None        # set in normal headless mode
        self._persistent_ctx = None  # set when using a real Chrome profile
        self._stealth = Stealth()
        self._launch_lock = asyncio.Lock()

    async def _ensure_browser(self) -> None:
        async with self._launch_lock:
            if self._browser is not None or self._persistent_ctx is not None:
                return
            self._playwright = await async_playwright().start()
            if self._profile_dir:
                # Chromium-only path: launch the user's installed Chrome
                # with their actual user-data-dir. Chrome locks the dir
                # while running, so the user must quit Chrome first. This
                # is the most "I'm a real person" the scraper can get.
                logger.info(
                    "launching persistent Chrome from profile: %s", self._profile_dir
                )
                self._persistent_ctx = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=self._profile_dir,
                    channel="chrome",
                    headless=False,
                    viewport={"width": 1280, "height": 800},
                    args=["--disable-blink-features=AutomationControlled"],
                )
                await self._stealth.apply_stealth_async(self._persistent_ctx)
            else:
                engine = getattr(self._playwright, _ENGINE, None)
                if engine is None:
                    raise RuntimeError(
                        f"Unknown SPORTS247_ENGINE={_ENGINE!r}; "
                        "expected one of: chromium, webkit, firefox"
                    )
                logger.info("launching Playwright engine: %s (headless)", _ENGINE)
                # WebKit doesn't take the chromium-specific flags; pass only
                # `headless` and `args` it understands. The
                # AutomationControlled blink flag is a no-op on webkit so we
                # just leave args empty there.
                self._browser = await engine.launch(headless=True)

    async def get(self, url: str, *, max_age: int = DEFAULT_MAX_AGE_SECONDS) -> bytes:
        await self._guard.ensure_allowed(url)
        cached = self._read_cache(url)
        if cached is not None and (time.time() - cached.fetched_at) < max_age:
            logger.debug("cache fresh (age %ds): %s", int(time.time() - cached.fetched_at), url)
            return cached.body

        await self._rate_limiter.acquire(url)
        await asyncio.sleep(0.25 + random.random() * 0.75)  # jitter 0.25–1.0s

        await self._ensure_browser()

        async def _do() -> bytes:
            if self._persistent_ctx is not None:
                # In persistent-profile mode we reuse the one shared context;
                # opening a fresh page per fetch keeps tabs hygienic without
                # discarding profile state.
                context = self._persistent_ctx
                close_context = False
            else:
                context = await self._browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                    locale="en-US",
                )
                # Apply stealth patches at the context level — masks the obvious
                # headless tells (navigator.webdriver, missing plugins/languages,
                # WebGL vendor mismatches). Not proxy rotation, not captcha
                # solving, not IP evasion. Just stops the page from declaring
                # itself a bot before we've had a chance to fetch.
                await self._stealth.apply_stealth_async(context)
                close_context = True
            page = await context.new_page()
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
                if response is None:
                    raise RuntimeError(f"no response for {url}")
                if response.status == 429 or response.status >= 500:
                    # Transient — let with_retries back off and try again.
                    raise RuntimeError(f"{response.status} from {url}")
                if response.status >= 400:
                    # 403/404 from 247 are not transient; surface immediately.
                    raise PermanentFetchError(f"{response.status} from {url}")
                html = await page.content()
            finally:
                await page.close()
                if close_context:
                    await context.close()
            return html.encode("utf-8")

        from playwright.async_api import Error as PWError
        body = await with_retries(
            _do,
            retries=3,
            base_delay=2.0,
            max_delay=60.0,
            retryable=(PWError, TimeoutError, RuntimeError),
        )

        entry = _CacheEntry(body=body, fetched_at=time.time())
        self._write_cache(url, entry)
        return entry.body

    async def close(self) -> None:
        if self._persistent_ctx is not None:
            await self._persistent_ctx.close()
            self._persistent_ctx = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    # ---- cache I/O ----------------------------------------------------------

    def _paths(self, url: str) -> tuple[Path, Path]:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{h}.body", self._cache_dir / f"{h}.meta.json"

    def _read_cache(self, url: str) -> Optional[_CacheEntry]:
        body_path, meta_path = self._paths(url)
        if not body_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text())
            return _CacheEntry(
                body=body_path.read_bytes(),
                fetched_at=float(meta["fetched_at"]),
            )
        except (OSError, ValueError, KeyError) as exc:
            logger.warning("cache read failed for %s: %s", url, exc)
            return None

    def _write_cache(self, url: str, entry: _CacheEntry) -> None:
        body_path, meta_path = self._paths(url)
        body_path.write_bytes(entry.body)
        meta_path.write_text(json.dumps({
            "url": url,
            "fetched_at": entry.fetched_at,
        }))


class PermanentFetchError(Exception):
    """Raised on 4xx (except 429) from 247 — not worth retrying."""

