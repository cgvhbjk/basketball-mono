"""
Raw source-payload snapshots.

Every adapter fetch routes its bytes through a Snapshotter so we keep an
immutable record of what each site returned. Snapshots live in the
filesystem (default: ./snapshots/) and are optionally indexed in the
`source_snapshots` Supabase table (see migration 005).

Why
---
- A site can change layout overnight and silently break a parser. Replaying
  parsers against saved snapshots reproduces historical bugs (and validates
  fixes) without re-hitting the site.
- It also gives the data team an offline corpus for regression tests
  (see tests/fixtures/).

File layout
-----------
{root}/{adapter}/{YYYY}/{MM}/{DD}/{checksum_prefix}__{slug}.{ext}

Slug is derived from the URL path so the same URL always lands in the same
file (until checksum changes — content-addressed dedup).
"""
from __future__ import annotations
import dataclasses
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = Path(os.environ.get("SCRAPER_SNAPSHOT_DIR", "snapshots")).expanduser()

# Default cap = 5 GB. Override with SCRAPER_SNAPSHOT_MAX_BYTES (bytes) or set
# to 0 to disable pruning. 5 GB holds ~10–20 full historical scraper runs.
_DEFAULT_MAX_BYTES = int(os.environ.get("SCRAPER_SNAPSHOT_MAX_BYTES", str(5 * 1024 ** 3)))


@dataclasses.dataclass
class Snapshot:
    adapter_name: str
    source_url: str
    content_type: str
    checksum: str
    payload_path: str
    size_bytes: int
    fetched_at: datetime


_EXT_BY_CONTENT_TYPE = {
    "text/html": "html",
    "application/json": "json",
    "application/xml": "xml",
    "text/plain": "txt",
}


def _ext_for(content_type: str) -> str:
    base = content_type.split(";", 1)[0].strip().lower()
    return _EXT_BY_CONTENT_TYPE.get(base, "bin")


_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _slugify_url(url: str, *, max_len: int = 80) -> str:
    parts = urlparse(url)
    raw = (parts.path + "_" + parts.query).strip("/_")
    slug = _SLUG_RE.sub("-", raw).strip("-")
    return (slug or "root")[:max_len]


class Snapshotter:
    """
    Writes raw response payloads to disk content-addressed by sha256.

    Same checksum → same file, never rewritten. `record()` returns a Snapshot
    pointing at the on-disk path; callers may then upsert into Supabase via
    `upsert.upsert_source_snapshot`.

    Disk usage is bounded by `max_bytes` — call `prune()` after a scraper run
    to LRU-evict the oldest files until the on-disk total drops back under
    the cap. Pass max_bytes=0 to disable.
    """

    def __init__(
        self,
        root: Path | str | None = None,
        max_bytes: int | None = None,
    ) -> None:
        self.root = Path(root) if root else _DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = _DEFAULT_MAX_BYTES if max_bytes is None else max_bytes

    def record(
        self,
        *,
        adapter_name: str,
        source_url: str,
        content_type: str,
        payload: bytes,
        fetched_at: Optional[datetime] = None,
    ) -> Snapshot:
        fetched_at = fetched_at or datetime.now(timezone.utc)
        checksum = hashlib.sha256(payload).hexdigest()
        ext = _ext_for(content_type)
        slug = _slugify_url(source_url)

        ts = fetched_at
        target_dir = self.root / adapter_name / f"{ts:%Y}" / f"{ts:%m}" / f"{ts:%d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{checksum[:12]}__{slug}.{ext}"

        # Idempotent: same checksum → same path, only write if absent.
        if not path.exists():
            path.write_bytes(payload)
        else:
            logger.debug("snapshot cache hit: %s", path)

        return Snapshot(
            adapter_name=adapter_name,
            source_url=source_url,
            content_type=content_type,
            checksum=checksum,
            payload_path=str(path),
            size_bytes=len(payload),
            fetched_at=fetched_at,
        )

    def prune(self) -> tuple[int, int]:
        """
        LRU-evict snapshot files until on-disk total ≤ self.max_bytes.

        Returns (files_deleted, bytes_freed). No-op when max_bytes <= 0.
        Robust to unlink failures (logs at debug, keeps going) so a single
        readonly file doesn't abort the whole sweep.
        """
        if self.max_bytes <= 0 or not self.root.exists():
            return 0, 0

        files: list[tuple[float, int, Path]] = []
        total = 0
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, p))
            total += st.st_size

        if total <= self.max_bytes:
            return 0, 0

        # Oldest first.
        files.sort(key=lambda t: t[0])
        deleted = freed = 0
        target = self.max_bytes
        for _, size, path in files:
            if total <= target:
                break
            try:
                path.unlink()
                total -= size
                freed += size
                deleted += 1
            except OSError as exc:
                logger.debug("snapshot prune: failed to unlink %s: %s", path, exc)

        logger.info(
            "snapshot prune: removed %d files (%.1f MB), %.1f MB remaining (cap %.1f MB)",
            deleted, freed / (1024 ** 2), total / (1024 ** 2), self.max_bytes / (1024 ** 2),
        )
        return deleted, freed
