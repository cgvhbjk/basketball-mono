"""Compliance gate tests — robots.txt + allow-list + cache reuse."""
import asyncio
from pathlib import Path

import pytest

from basketball_scraper.sources.sports247.compliance import DisallowedURL, RobotsGuard
from basketball_scraper.sources.sports247.fetch import CachingFetcher


def _robots_fixture(fixtures_dir: Path) -> str:
    return (fixtures_dir / "sports247_robots.txt").read_text()


def test_disallowed_json_path_raises(fixtures_dir):
    guard = RobotsGuard(ua="test-ua", fixture=_robots_fixture(fixtures_dir))
    with pytest.raises(DisallowedURL):
        asyncio.run(guard.ensure_allowed("https://247sports.com/api/players.json"))


def test_non_247_host_raises(fixtures_dir):
    guard = RobotsGuard(ua="test-ua", fixture=_robots_fixture(fixtures_dir))
    with pytest.raises(DisallowedURL):
        asyncio.run(guard.ensure_allowed("https://on3.com/player/cj-rosser/"))


def test_player_profile_url_is_allowed(fixtures_dir):
    guard = RobotsGuard(ua="test-ua", fixture=_robots_fixture(fixtures_dir))
    assert asyncio.run(guard.is_allowed("https://247sports.com/player/cj-rosser-46151476/")) is True


def test_caching_fetcher_serves_second_request_from_disk(fixtures_dir, tmp_path):
    """Pre-seed the cache so the second `get()` returns from disk without
    launching a browser. The on-disk cache is the same code path whether
    populated by a previous GET or by this test — we only care that a
    fresh entry inside `max_age` skips the network."""
    guard = RobotsGuard(ua="test-ua", fixture=_robots_fixture(fixtures_dir))
    fetcher = CachingFetcher(guard=guard, cache_dir=tmp_path / "cache")

    url = "https://247sports.com/player/cj-rosser-46151476/"
    payload = b"<html><body>cached body</body></html>"
    import time, json
    body_path, meta_path = fetcher._paths(url)
    body_path.write_bytes(payload)
    meta_path.write_text(json.dumps({"url": url, "fetched_at": time.time()}))

    async def run() -> bytes:
        result = await fetcher.get(url)
        await fetcher.close()
        return result

    assert asyncio.run(run()) == payload
    # If the cache had been bypassed, `_ensure_browser` would have launched
    # Chromium — this assertion catches that regression.
    assert fetcher._browser is None
