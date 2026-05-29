"""Tests for retry + rate-limit primitives."""
import asyncio
import time

import pytest

from basketball_scraper.reliability import DomainRateLimiter, with_retries


@pytest.mark.asyncio
async def test_rate_limiter_enforces_minimum_interval():
    limiter = DomainRateLimiter(default_min_interval=0.05)
    await limiter.acquire("https://example.com/a")
    t0 = time.monotonic()
    await limiter.acquire("https://example.com/b")
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.04  # allow a tiny slop


@pytest.mark.asyncio
async def test_rate_limiter_per_host_override_wins():
    # Two hosts: one rate-limited slow, one not present at all (uses default).
    limiter = DomainRateLimiter(
        default_min_interval=0.0,
        per_host={"slow.example.com": 0.05},
    )
    await limiter.acquire("https://slow.example.com/a")
    t0 = time.monotonic()
    await limiter.acquire("https://slow.example.com/b")
    slow = time.monotonic() - t0

    await limiter.acquire("https://fast.example.com/a")
    t0 = time.monotonic()
    await limiter.acquire("https://fast.example.com/b")
    fast = time.monotonic() - t0

    assert slow >= 0.04
    assert fast < slow


@pytest.mark.asyncio
async def test_with_retries_succeeds_after_transient_failure():
    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    out = await with_retries(flaky, retries=3, base_delay=0.001, retryable=(RuntimeError,))
    assert out == "ok"
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_with_retries_raises_after_exhausting():
    async def always_fails() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError):
        await with_retries(always_fails, retries=2, base_delay=0.001, retryable=(ValueError,))


@pytest.mark.asyncio
async def test_with_retries_does_not_swallow_unlisted_exceptions():
    async def boom() -> None:
        raise TypeError("not retryable")

    with pytest.raises(TypeError):
        await with_retries(boom, retries=3, base_delay=0.001, retryable=(ValueError,))
