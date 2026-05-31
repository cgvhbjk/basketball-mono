#!/usr/bin/env python3
"""
Import On3 *Industry* recruiting rankings and join them onto our players.

Why this exists
---------------
The per-player On3 search (`enrich_players.py --source on3`) walks all 8,800+
DB names one at a time. That's slow, mostly misses (On3 only ranks notable
recruits), and — worst — its name-only search happily matched retired NBA
players and football namesakes. This flips the direction:

  1. Pull On3's ranked set per grad year. Every row there is already
     basketball + class-scoped and carries stars / national / state rank.
  2. Index it by name (+ class year).
  3. Match against our DB and patch the null columns. Ranked players who
     aren't in our DB are discarded — we only enrich who we already have.

Usage:
  python scripts/import_on3_rankings.py [--years 2025 2026 2027 ...] \
      [--dry-run] [--limit-pages N]
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from typing import Any, Optional

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client
from basketball_scraper.config import settings
from basketball_scraper.enrich_on3 import _ascii_fold, _fetch_httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("import_on3_rankings")

RANKING_URL = "https://www.on3.com/db/rankings/industry-player/basketball/{year}/"
PAGE_DELAY = 1.5  # seconds between ranking-page fetches (polite)
DEFAULT_YEARS = [2025, 2026, 2027, 2028, 2029]


_SUFFIX_TOKENS = {"jr", "sr", "ii", "iii", "iv", "v"}


def _norm_name(s: str) -> str:
    return " ".join(_ascii_fold(s).split())


def _match_key(s: str) -> str:
    """A name key that tolerates suffixes and middle names: drop Jr/Sr/III-style
    tokens and any middle tokens, keying on first + last token only. So DB
    'Charles Stewart Jr' and ranked 'Charles Stewart' collapse to 'charles
    stewart'. Collisions (two real people, same first+last) are still resolved
    downstream by grad year, and refused when that can't disambiguate."""
    toks = [t for t in _ascii_fold(s).replace(".", " ").split() if t and t not in _SUFFIX_TOKENS]
    if not toks:
        return ""
    if len(toks) == 1:
        return toks[0]
    return f"{toks[0]} {toks[-1]}"


def _stars_from_ratings(ratings: Any) -> Optional[int]:
    """On3 ranking rows carry a ratings[] list of {type, stars, ...}. Prefer the
    Industry rating (this is the industry ranking page); fall back to the first
    rating that has a plausible star value."""
    if not isinstance(ratings, list):
        return None
    industry = [r for r in ratings if isinstance(r, dict) and r.get("type") == "Industry"]
    for r in industry + [r for r in ratings if isinstance(r, dict)]:
        v = r.get("stars")
        if isinstance(v, int) and 1 <= v <= 5:
            return v
    return None


def _entry_to_record(entry: dict) -> Optional[dict]:
    person = entry.get("person") or {}
    name = person.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    hs = person.get("highSchool")
    hs_name = hs.get("name") if isinstance(hs, dict) else (hs if isinstance(hs, str) else None)

    def _pos_int(*keys: str, src: dict = entry) -> Optional[int]:
        for k in keys:
            v = src.get(k)
            if isinstance(v, int) and v > 0:
                return v
        return None

    height = person.get("height")
    height_inches = height if isinstance(height, int) and 48 <= height <= 108 else None

    cy = person.get("classYear")
    grad_year = cy if isinstance(cy, int) and 2020 <= cy <= 2035 else None

    return {
        "name": name.strip(),
        "norm": _norm_name(name),
        "key": _match_key(name),
        "grad_year": grad_year,
        "national_rank": _pos_int("overallRank", "consensusOverallRank"),
        "state_rank": _pos_int("stateRank", "consensusStateRank"),
        "position_rank": _pos_int("positionRank", "consensusPositionRank"),
        "stars": _stars_from_ratings(entry.get("ratings")),
        "height_inches": height_inches,
        "high_school": hs_name if isinstance(hs_name, str) and len(hs_name) > 2 else None,
        "hometown": person.get("homeTownName") if isinstance(person.get("homeTownName"), str) else None,
    }


async def fetch_year(year: int, limit_pages: Optional[int]) -> list[dict]:
    """Page through one grad year's industry ranking, returning flat records."""
    records: list[dict] = []
    page = 1
    page_count = None
    while True:
        url = RANKING_URL.format(year=year) + f"?page={page}"
        html = await _fetch_httpx(url)
        if not html or "__NEXT_DATA__" not in html:
            logger.warning("year %d page %d: no payload — stopping", year, page)
            break
        script = BeautifulSoup(html, "html.parser").find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            logger.warning("year %d page %d: __NEXT_DATA__ missing/empty — stopping", year, page)
            break
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("year %d page %d: bad JSON (%s) — stopping", year, page, exc)
            break
        pdata = data.get("props", {}).get("pageProps", {}).get("playerData", {})
        # Years On3 hasn't ranked yet return playerData as [] (a list), not a
        # dict — treat that as "no more data" rather than crashing.
        if not isinstance(pdata, dict):
            logger.info("year %d: no ranking published — skipping", year)
            break
        lst = pdata.get("list") or []
        if not lst:
            break
        for entry in lst:
            rec = _entry_to_record(entry)
            if rec:
                records.append(rec)
        if page_count is None:
            page_count = (pdata.get("pagination", {}).get("pagination", {}) or {}).get("pageCount")
            total = (pdata.get("pagination", {}).get("pagination", {}) or {}).get("count")
            logger.info("year %d: %s ranked players across %s pages", year, total, page_count)
        if limit_pages and page >= limit_pages:
            break
        if page_count and page >= page_count:
            break
        page += 1
        await asyncio.sleep(PAGE_DELAY)
    logger.info("year %d: collected %d records", year, len(records))
    return records


def _fetch_all_db_players(supabase) -> list[dict]:
    PAGE = 1000
    out: list[dict] = []
    offset = 0
    while True:
        res = (
            supabase.table("players")
            .select("id, first_name, last_name, grad_year, height_inches, "
                    "high_school, hometown, star_rating, national_rank, state_rank")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        page = res.data or []
        out.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    return out


def _build_index(records: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        idx[r["key"]].append(r)
    return idx


def _pick_match(candidates: list[dict], db_grad_year: Optional[int]) -> Optional[dict]:
    """Resolve a DB player to a single ranked record. If the name maps to one
    ranked player, take it. If it maps to several (same name, different
    classes), disambiguate by the DB grad year; if that can't, refuse rather
    than guess wrong."""
    if len(candidates) == 1:
        return candidates[0]
    if db_grad_year is not None:
        yr = [c for c in candidates if c["grad_year"] == db_grad_year]
        if len(yr) == 1:
            return yr[0]
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, nargs="+", default=DEFAULT_YEARS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-pages", type=int, default=None,
                        help="Cap ranking pages per year (debugging).")
    args = parser.parse_args()

    # 1. Pull the ranked set.
    all_records: list[dict] = []
    for year in args.years:
        all_records.extend(asyncio.run(fetch_year(year, args.limit_pages)))
    logger.info("Total ranked records pulled: %d across years %s", len(all_records), args.years)

    index = _build_index(all_records)
    logger.info("Indexed %d unique ranked names", len(index))

    # 2. Pull our players and join.
    supabase = create_client(settings.supabase_url, settings.supabase_service_key)
    players = _fetch_all_db_players(supabase)
    logger.info("DB players: %d", len(players))

    patch_fields = [
        ("star_rating", "stars"),
        ("national_rank", "national_rank"),
        ("state_rank", "state_rank"),
        ("height_inches", "height_inches"),
        ("grad_year", "grad_year"),
        ("high_school", "high_school"),
        ("hometown", "hometown"),
    ]

    matched = updated = ambiguous = no_fill = 0
    for p in players:
        first = (p.get("first_name") or "").strip()
        last = (p.get("last_name") or "").strip()
        if len(first) < 2 or len(last) < 2:
            continue
        key = _match_key(f"{first} {last}")
        candidates = index.get(key)
        if not candidates:
            continue
        rec = _pick_match(candidates, p.get("grad_year"))
        if rec is None:
            ambiguous += 1
            logger.info("AMBIGUOUS %s %s — %d ranked rows, no grad-year tiebreak",
                        first, last, len(candidates))
            continue
        matched += 1

        patch: dict = {}
        for db_col, rec_key in patch_fields:
            val = rec.get(rec_key)
            if val is not None and p.get(db_col) is None:
                patch[db_col] = val
        if not patch:
            no_fill += 1
            continue
        logger.info("MATCH %s %s (cls %s, #%s) → %s",
                    first, last, rec.get("grad_year"), rec.get("national_rank"), patch)
        if not args.dry_run:
            supabase.table("players").update(patch).eq("id", p["id"]).execute()
        updated += 1

    logger.info(
        "Done. matched=%d updated=%d already-full=%d ambiguous=%d%s",
        matched, updated, no_fill, ambiguous,
        " (dry-run)" if args.dry_run else "",
    )


if __name__ == "__main__":
    main()
