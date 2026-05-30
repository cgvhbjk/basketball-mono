"""
JSONL I/O for ProfileExtract.

We append every parsed profile to `247_extracts/{YYYY-MM-DD}_247.jsonl`. One
file per UTC day, append-only — that gives a chronological audit trail and
keeps each file small enough to skim by hand. Downstream consumers (e.g.
enrich_players.py) read the *latest* file unless told otherwise.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .models import ProfileExtract

logger = logging.getLogger(__name__)


DEFAULT_DIR = Path("scraper/247_extracts")


def default_path(directory: Path = DEFAULT_DIR, *, when: Optional[datetime] = None) -> Path:
    when = when or datetime.now(timezone.utc)
    return directory / f"{when:%Y-%m-%d}_247.jsonl"


def write_jsonl(extracts: Iterable[ProfileExtract], path: Path) -> int:
    """Append `extracts` to `path` (one JSON object per line). Returns count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as f:
        for extract in extracts:
            # Pydantic v2: model_dump_json handles datetime, nested models.
            f.write(extract.model_dump_json())
            f.write("\n")
            n += 1
    logger.info("wrote %d profile extracts to %s", n, path)
    return n


def read_jsonl(path: Path) -> Iterator[ProfileExtract]:
    """Yield ProfileExtract rows from `path`. Skips blank lines."""
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield ProfileExtract.model_validate(json.loads(line))
            except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
                logger.warning("skipping malformed line in %s: %s", path, exc)


def read_latest(directory: Path = DEFAULT_DIR) -> Iterator[ProfileExtract]:
    """Yield rows from the most-recent JSONL file under `directory`.

    Returns an empty iterator if the directory doesn't exist or has no
    matching files — callers expecting data should check `latest_path`.
    """
    path = latest_path(directory)
    if path is None:
        return iter(())
    return read_jsonl(path)


def latest_path(directory: Path = DEFAULT_DIR) -> Optional[Path]:
    if not directory.exists():
        return None
    files = sorted(directory.glob("*_247.jsonl"))
    return files[-1] if files else None
