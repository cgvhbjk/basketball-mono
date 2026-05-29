"""
Pytest config — adds the scraper package root to sys.path and provides a
fixture that points at the on-disk HTML/JSON fixtures.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Settings expects SUPABASE_URL / SUPABASE_SERVICE_KEY at import time — set
# benign defaults so importing the package in tests doesn't blow up.
os.environ.setdefault("SUPABASE_URL", "http://test")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
