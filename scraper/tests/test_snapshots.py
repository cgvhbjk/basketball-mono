"""Tests for the raw-payload Snapshotter."""
from pathlib import Path

from basketball_scraper.snapshots import Snapshotter, _slugify_url


def test_slugify_url_keeps_path_and_query(tmp_path):
    slug = _slugify_url("https://example.com/widgets/v1/teamroster?id=1&divisionteamid=42")
    assert "widgets-v1-teamroster" in slug
    assert "id-1" in slug
    assert "divisionteamid-42" in slug


def test_snapshotter_writes_file_and_dedups_same_checksum(tmp_path: Path):
    s = Snapshotter(root=tmp_path)
    snap1 = s.record(
        adapter_name="eybl",
        source_url="https://example.com/page?x=1",
        content_type="text/html",
        payload=b"<html>hi</html>",
    )
    assert Path(snap1.payload_path).exists()
    assert Path(snap1.payload_path).read_bytes() == b"<html>hi</html>"
    assert snap1.size_bytes == len(b"<html>hi</html>")

    # Same payload → same file (idempotent).
    snap2 = s.record(
        adapter_name="eybl",
        source_url="https://example.com/page?x=1",
        content_type="text/html",
        payload=b"<html>hi</html>",
    )
    assert snap2.payload_path == snap1.payload_path
    assert snap2.checksum == snap1.checksum


def test_snapshotter_distinct_payloads_yield_distinct_files(tmp_path: Path):
    s = Snapshotter(root=tmp_path)
    a = s.record(
        adapter_name="eybl",
        source_url="https://example.com/page",
        content_type="text/html",
        payload=b"first",
    )
    b = s.record(
        adapter_name="eybl",
        source_url="https://example.com/page",
        content_type="text/html",
        payload=b"second",
    )
    assert a.payload_path != b.payload_path
    assert a.checksum != b.checksum


def test_snapshotter_uses_extension_by_content_type(tmp_path: Path):
    s = Snapshotter(root=tmp_path)
    html = s.record(adapter_name="x", source_url="https://e.com/a", content_type="text/html", payload=b"")
    js = s.record(adapter_name="x", source_url="https://e.com/b", content_type="application/json", payload=b"{}")
    assert html.payload_path.endswith(".html")
    assert js.payload_path.endswith(".json")


def test_prune_noop_when_under_cap(tmp_path: Path):
    s = Snapshotter(root=tmp_path, max_bytes=1024 * 1024)  # 1 MB cap
    s.record(adapter_name="x", source_url="https://e.com/a", content_type="text/html", payload=b"hi")
    deleted, freed = s.prune()
    assert (deleted, freed) == (0, 0)


def test_prune_evicts_oldest_first(tmp_path: Path):
    import os, time
    s = Snapshotter(root=tmp_path, max_bytes=500)

    # Write three 200-byte files with distinct mtimes (oldest first).
    paths: list[Path] = []
    for i, payload in enumerate([b"A" * 200, b"B" * 200, b"C" * 200]):
        snap = s.record(
            adapter_name="x",
            source_url=f"https://e.com/{i}",
            content_type="text/html",
            payload=payload,
        )
        p = Path(snap.payload_path)
        # Force a stable mtime so the test isn't FS-resolution sensitive.
        atime = mtime = time.time() - (3 - i) * 10
        os.utime(p, (atime, mtime))
        paths.append(p)

    # All three present.
    assert all(p.exists() for p in paths)

    deleted, freed = s.prune()
    # 600 total bytes vs 500 cap → must evict at least one (the oldest).
    assert deleted >= 1
    assert freed >= 200
    assert not paths[0].exists()           # oldest gone
    assert paths[-1].exists()              # newest survives


def test_prune_disabled_when_max_bytes_zero(tmp_path: Path):
    s = Snapshotter(root=tmp_path, max_bytes=0)
    s.record(adapter_name="x", source_url="https://e.com/a", content_type="text/html", payload=b"x" * 10_000)
    deleted, _ = s.prune()
    assert deleted == 0
