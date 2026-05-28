#!/usr/bin/env python3
"""
Run all circuit scrapers for a given season and age division.

Usage:
  python run_all.py
  python run_all.py --season 2026 --division 17U
  python run_all.py --circuits eybl uaa uaa_rise   # subset only
  python run_all.py --playwright                   # force Playwright for all
  python run_all.py --dry-run                      # print commands without running

Each circuit runs in its own subprocess so a failure in one does not
affect the others. Credentials are read from .env as usual.
"""
import argparse
import logging
import os
import subprocess
import sys
import time

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ALL_CIRCUITS = ["eybl", "eycl", "3ssb", "adidas_gold", "uaa", "uaa_rise", "puma"]


def run_circuit(circuit: str, season: int, division: str, playwright: bool, dry_run: bool) -> bool:
    env = os.environ.copy()
    env["CIRCUIT"] = circuit
    env["SEASON"] = str(season)
    env["AGE_DIVISION"] = division
    env["USE_PLAYWRIGHT"] = "true" if playwright else "false"

    cmd = [sys.executable, "-m", "basketball_scraper.main"]
    logger.info(">>> %s  CIRCUIT=%s SEASON=%s AGE_DIVISION=%s", " ".join(cmd), circuit, season, division)

    if dry_run:
        return True

    start = time.monotonic()
    result = subprocess.run(cmd, env=env, cwd=os.path.dirname(os.path.abspath(__file__)))
    elapsed = time.monotonic() - start

    if result.returncode == 0:
        logger.info("✓ %-15s completed in %.0fs", circuit, elapsed)
        return True
    else:
        logger.error("✗ %-15s FAILED (exit %d) after %.0fs", circuit, result.returncode, elapsed)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all basketball circuit scrapers")
    parser.add_argument("--season", type=int, default=int(os.getenv("SEASON", "2026")))
    parser.add_argument(
        "--division",
        default=os.getenv("AGE_DIVISION", "17U"),
        choices=["15U", "16U", "17U"],
    )
    parser.add_argument(
        "--circuits",
        nargs="+",
        default=ALL_CIRCUITS,
        choices=ALL_CIRCUITS,
        metavar="CIRCUIT",
        help=f"Circuits to run (default: all). Choices: {', '.join(ALL_CIRCUITS)}",
    )
    parser.add_argument("--playwright", action="store_true", help="Force Playwright for all circuits")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    args = parser.parse_args()

    logger.info(
        "Running %d circuit(s) | season=%d | division=%s%s",
        len(args.circuits), args.season, args.division,
        " [DRY RUN]" if args.dry_run else "",
    )

    results: dict[str, bool] = {}
    total_start = time.monotonic()

    for circuit in args.circuits:
        results[circuit] = run_circuit(
            circuit, args.season, args.division, args.playwright, args.dry_run
        )

    elapsed = time.monotonic() - total_start
    passed = sum(results.values())
    failed = len(results) - passed

    logger.info("")
    logger.info("=" * 50)
    logger.info("Summary  (%d passed, %d failed, %.0fs total)", passed, failed, elapsed)
    logger.info("=" * 50)
    for circuit, ok in results.items():
        logger.info("  %-15s %s", circuit, "OK" if ok else "FAILED")

    # Whenever either Adidas circuit ran this invocation, sweep for cross-circuit
    # duplicates. The other circuit's data may have been scraped in a previous run
    # and still be in the DB — running dedup only when BOTH ran in the SAME
    # invocation would leave residual duplicates.
    adidas_any_ran = results.get("3ssb") or results.get("adidas_gold")
    if adidas_any_ran and not args.dry_run:
        _dedup_adidas(args.season)

    if failed:
        sys.exit(1)


def _dedup_adidas(season: int) -> None:
    from supabase import create_client
    from basketball_scraper.upsert import dedup_adidas_cross_circuit
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        logger.warning("SUPABASE_URL/SUPABASE_SERVICE_KEY not set — skipping Adidas dedup")
        return
    client = create_client(url, key)
    dedup_adidas_cross_circuit(client, season)


if __name__ == "__main__":
    main()
