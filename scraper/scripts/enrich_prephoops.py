#!/usr/bin/env python3
"""
Enrich players from PrepHoops' full public player database.

PrepHoops (prephoops.com) exposes /wp-json/wp/v2/players — ~176k player
profiles, no paywall, no bot wall. Each profile's `acf_data` carries bio
(height / position / high school / state / class) AND rankings
(national_rank / state_ranking). We paginate the WHOLE database (it's only
~9 KB per 100 records with nested field selection), build a local name
index, and join our players onto it.

Why the full DB, not /{year}-rankings/ boards or ?search=:
  - the boards only list ~500 nationally-ranked players (tiny overlap);
  - the ?search= endpoint is fuzzy and misses players who are demonstrably
    in the database (it can't find Beckham Black, who sits on a board).
Bulk pagination is the only reliable way to see the true overlap.

Matching: suffix/middle-name-tolerant key (first+last token). PrepHoops'
DB is historical, so we keep only current-window classes and disambiguate
same-name collisions by the DB grad year — refusing when we can't, to avoid
patching the wrong same-name kid. Patches are NULL-only, so On3 industry
ranks already set are never clobbered.

Compliance: on-disk page cache, polite per-request delay + jitter, contact
UA. The API is public; no auth, no paywalled content.

Usage:
  python scripts/enrich_prephoops.py [--dry-run] [--no-cache] [--max-pages N]
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client
from basketball_scraper.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("enrich_prephoops")

API = "https://prephoops.com/wp-json/wp/v2/players"
PER_PAGE = 100
ACF_FIELDS = (
    "acf_data.full_name,acf_data.class,acf_data.height,acf_data.position,"
    "acf_data.high_school,acf_data.alt_high_school,acf_data.state,"
    "acf_data.national_rank,acf_data.state_ranking"
)
CONTACT = os.getenv("SCRAPER_CONTACT_EMAIL", "scraper@local")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (compliance-contact: {CONTACT})"
)
REQUEST_DELAY = 0.3
CACHE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / ".cache" / "prephoops_db"
# Our players are current recruits; PrepHoops' DB goes back to ~2010. Keep
# only the current window so historical namesakes don't pollute the index.
CURRENT_MIN, CURRENT_MAX = 2024, 2032

_SUFFIX_TOKENS = {"jr", "sr", "ii", "iii", "iv", "v"}
_HEIGHT_RE = re.compile(r"(\d)\s*['’]\s*(\d{1,2})")
_TAG_RE = re.compile(r"<[^>]+>")


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower().strip()


def _match_key(s: str) -> str:
    toks = [t for t in _fold(s).replace(".", " ").split() if t and t not in _SUFFIX_TOKENS]
    if not toks:
        return ""
    return toks[0] if len(toks) == 1 else f"{toks[0]} {toks[-1]}"


def _int_or_none(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    # str.isdigit() is True for unicode oddities like '2029⁹' (superscript),
    # which int() then rejects — so pull the first run of ASCII digits only.
    if isinstance(v, str):
        m = re.search(r"[0-9]{1,6}", v)
        if m:
            return int(m.group())
    return None


def _height_inches(v: Any) -> Optional[int]:
    if not isinstance(v, str):
        return None
    m = _HEIGHT_RE.search(v)
    if not m:
        return None
    h = int(m.group(1)) * 12 + int(m.group(2))
    return h if 48 <= h <= 108 else None


def _high_school(acf: dict) -> Optional[str]:
    alt = acf.get("alt_high_school")
    if isinstance(alt, str) and len(alt.strip()) > 2:
        return alt.strip()
    raw = acf.get("high_school")
    if isinstance(raw, str):
        txt = _TAG_RE.sub("", raw).strip()
        if len(txt) > 2:
            return txt
    return None


def _record(acf: dict) -> Optional[dict]:
    name = acf.get("full_name")
    if not isinstance(name, str) or not name.strip():
        return None
    cy = _int_or_none(acf.get("class"))
    if cy is None or not (CURRENT_MIN <= cy <= CURRENT_MAX):
        return None
    pos = acf.get("position")
    return {
        "key": _match_key(name),
        "grad_year": cy,
        "height_inches": _height_inches(acf.get("height")),
        "position": pos if isinstance(pos, str) and pos else None,
        "high_school": _high_school(acf),
        "national_rank": _int_or_none(acf.get("national_rank")),
        "state_rank": _int_or_none(acf.get("state_ranking")),
    }


def _data_richness(r: dict) -> int:
    return sum(r.get(k) is not None for k in ("national_rank", "state_rank", "height_inches", "position", "high_school"))


async def fetch_page(client: httpx.AsyncClient, page: int, use_cache: bool) -> Optional[list]:
    cp = CACHE_DIR / f"page-{page}.json"
    if use_cache and cp.exists():
        try:
            return json.loads(cp.read_text())
        except Exception:
            pass
    try:
        r = await client.get(API, params={"per_page": PER_PAGE, "page": page, "_fields": ACF_FIELDS},
                             headers={"User-Agent": USER_AGENT})
    except Exception as exc:
        logger.warning("page %d failed: %s", page, exc)
        return None
    if r.status_code != 200:
        return None
    data = json.loads(r.text)
    if not isinstance(data, list):
        return None
    if use_cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cp.write_text(r.text)
    return data


async def build_index(use_cache: bool, max_pages: Optional[int]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = defaultdict(list)
    kept = scanned = 0
    async with httpx.AsyncClient(timeout=40, follow_redirects=True) as client:
        # discover total pages
        head = await client.get(API, params={"per_page": PER_PAGE, "page": 1, "_fields": "id"},
                                headers={"User-Agent": USER_AGENT})
        total_pages = int(head.headers.get("X-WP-TotalPages", "0")) or 1760
        if max_pages:
            total_pages = min(total_pages, max_pages)
        logger.info("PrepHoops DB: %s players, %d pages", head.headers.get("X-WP-Total"), total_pages)
        for page in range(1, total_pages + 1):
            cached = (CACHE_DIR / f"page-{page}.json").exists()
            data = await fetch_page(client, page, use_cache)
            if not data:
                continue
            for e in data:
                scanned += 1
                rec = _record(e.get("acf_data") or {})
                if rec and rec["key"]:
                    index[rec["key"]].append(rec)
                    kept += 1
            if page % 200 == 0:
                logger.info("  page %d/%d — scanned %d, kept %d current-window", page, total_pages, scanned, kept)
            if not (use_cache and cached):
                await asyncio.sleep(REQUEST_DELAY + random.uniform(0, 0.1))
    logger.info("Indexed %d current-window PrepHoops players (%d unique name keys)", kept, len(index))
    return index


def _pick(cands: list[dict], db_grad_year: Optional[int]) -> Optional[dict]:
    if len(cands) == 1:
        return cands[0]
    if db_grad_year is not None:
        yr = [c for c in cands if c["grad_year"] == db_grad_year]
        if len(yr) == 1:
            return yr[0]
        if len(yr) > 1:
            cands = yr  # narrow to the right class, then fall through
    # Multiple same-name, same-class (or no DB year) — refuse rather than guess.
    return None


def _fetch_players(sb) -> list[dict]:
    out, off = [], 0
    while True:
        pg = (
            sb.table("players")
            .select("id, first_name, last_name, grad_year, height_inches, position, "
                    "high_school, national_rank, state_rank")
            .range(off, off + 999).execute().data
        )
        out.extend(pg)
        if len(pg) < 1000:
            break
        off += 1000
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--max-pages", type=int, default=None, help="Cap pages (debugging).")
    args = ap.parse_args()
    use_cache = not args.no_cache

    index = await build_index(use_cache, args.max_pages)

    sb = create_client(settings.supabase_url, settings.supabase_service_key)
    players = _fetch_players(sb)
    logger.info("DB players: %d", len(players))

    cols = ["height_inches", "position", "high_school", "grad_year", "national_rank", "state_rank"]
    in_ph = matched = bio_filled = rank_filled = ambiguous = 0
    for p in players:
        first, last = (p.get("first_name") or "").strip(), (p.get("last_name") or "").strip()
        if len(first) < 2 or len(last) < 2:
            continue
        cands = index.get(_match_key(f"{first} {last}"))
        if not cands:
            continue
        in_ph += 1
        rec = _pick(cands, p.get("grad_year"))
        if rec is None:
            ambiguous += 1
            continue
        matched += 1
        patch = {c: rec[c] for c in cols if rec.get(c) is not None and p.get(c) is None}
        if patch:
            if patch.keys() & {"national_rank", "state_rank"}:
                rank_filled += 1
            if patch.keys() & {"height_inches", "position", "high_school", "grad_year"}:
                bio_filled += 1
            if not args.dry_run:
                sb.table("players").update(patch).eq("id", p["id"]).execute()

    logger.info(
        "Done. our players present in PrepHoops=%d | uniquely matched=%d | "
        "bio filled=%d | rank filled=%d | ambiguous(same-name)=%d%s",
        in_ph, matched, bio_filled, rank_filled, ambiguous,
        " (dry-run)" if args.dry_run else "",
    )


if __name__ == "__main__":
    asyncio.run(main())
