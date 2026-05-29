"""
Retry + rate-limit primitives used by fetchers.

Kept dependency-free (only asyncio + stdlib) so any adapter can import these
without pulling in httpx or playwright.
"""
from __future__ import annotations
import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, TypeVar
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ----------------------------------------------------------------
# Per-domain rate limiter
# ----------------------------------------------------------------

@dataclass
class _DomainState:
    min_interval: float
    next_allowed: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class DomainRateLimiter:
    """
    Enforce a minimum interval between requests per host.

    Usage:
        limiter = DomainRateLimiter(default_min_interval=0.5)
        await limiter.acquire(url)
        # ... do request ...

    Per-host overrides accept a host substring → seconds-between-requests. The
    longest matching substring wins, so 'nikeeyb.hoopstats.pointstreak.com'
    beats a generic 'pointstreak.com' rule.
    """

    def __init__(
        self,
        default_min_interval: float = 0.5,
        per_host: dict[str, float] | None = None,
    ) -> None:
        self._default = default_min_interval
        self._per_host = dict(per_host or {})
        self._state: dict[str, _DomainState] = {}
        self._registry_lock = asyncio.Lock()

    def _resolve_interval(self, host: str) -> float:
        best: tuple[int, float] | None = None
        for pattern, interval in self._per_host.items():
            if pattern in host:
                if best is None or len(pattern) > best[0]:
                    best = (len(pattern), interval)
        return best[1] if best else self._default

    async def _get(self, host: str) -> _DomainState:
        async with self._registry_lock:
            state = self._state.get(host)
            if state is None:
                state = _DomainState(min_interval=self._resolve_interval(host))
                self._state[host] = state
            return state

    async def acquire(self, url: str) -> None:
        host = urlparse(url).netloc or url
        state = await self._get(host)
        async with state.lock:
            now = time.monotonic()
            wait = state.next_allowed - now
            if wait > 0:
                await asyncio.sleep(wait)
            state.next_allowed = time.monotonic() + state.min_interval


# ----------------------------------------------------------------
# Retry with exponential backoff
# ----------------------------------------------------------------

async def with_retries(
    fn: Callable[[], Awaitable[T]],
    *,
    retries: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable: Iterable[type[BaseException]] = (Exception,),
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """
    Call `fn()` with exponential backoff + jitter.

    The default `retryable=(Exception,)` retries everything; pass a narrower
    tuple at call sites that can distinguish transient vs. permanent errors
    (eg. exclude `BlockedError` so CDN blocks abort immediately).
    """
    retryable_t = tuple(retryable)
    last_exc: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return await fn()
        except retryable_t as exc:
            last_exc = exc
            if attempt >= retries:
                break
            delay = min(max_delay, base_delay * (2 ** attempt))
            delay = delay * (0.5 + random.random())  # jitter: 0.5×–1.5×
            if on_retry:
                on_retry(attempt + 1, exc, delay)
            else:
                logger.warning(
                    "retry %d/%d after %.1fs: %s",
                    attempt + 1, retries, delay, exc,
                )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
