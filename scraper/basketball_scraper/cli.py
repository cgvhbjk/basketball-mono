"""
Scraper CLI.

Examples
--------
Run a single circuit:

  python -m basketball_scraper ingest --circuit eybl --season 2026 --division 17U

Run multiple circuits in subprocesses:

  python -m basketball_scraper ingest-all --circuits eybl uaa 3ssb

List registered circuits:

  python -m basketball_scraper list-circuits

The CLI sets CIRCUIT/SEASON/AGE_DIVISION/USE_PLAYWRIGHT in the environment so
the pydantic settings layer picks them up; this lets the existing
`basketball_scraper.main` orchestration run unchanged.
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import subprocess
import sys
import time
from typing import Iterable

logger = logging.getLogger("scraper.cli")


def _set_env(circuit: str, season: int, division: str, playwright: bool) -> None:
    os.environ["CIRCUIT"] = circuit
    os.environ["SEASON"] = str(season)
    os.environ["AGE_DIVISION"] = division
    os.environ["USE_PLAYWRIGHT"] = "true" if playwright else "false"


def _all_circuit_keys() -> list[str]:
    # Import here to avoid loading settings (which needs SUPABASE_URL) just for --help.
    from .config import CIRCUIT_KEYS
    return list(CIRCUIT_KEYS)


def cmd_ingest(args: argparse.Namespace) -> int:
    _set_env(args.circuit, args.season, args.division, args.playwright)
    # Importing main.py here triggers settings reload from env.
    from .main import main as run
    asyncio.run(run())
    return 0


def cmd_ingest_all(args: argparse.Namespace) -> int:
    """Run each circuit in its own subprocess so a hang/crash in one doesn't take the rest down."""
    timeout = int(os.getenv("CIRCUIT_TIMEOUT_SECONDS", "3600"))
    failures: list[str] = []
    ran: list[str] = []
    for circuit in args.circuits:
        env = os.environ.copy()
        env["CIRCUIT"] = circuit
        env["SEASON"] = str(args.season)
        env["AGE_DIVISION"] = args.division
        env["USE_PLAYWRIGHT"] = "true" if args.playwright else "false"
        cmd = [sys.executable, "-m", "basketball_scraper", "ingest",
               "--circuit", circuit, "--season", str(args.season),
               "--division", args.division]
        if args.playwright:
            cmd.append("--playwright")
        logger.info(">>> %s", " ".join(cmd))
        if args.dry_run:
            continue
        start = time.monotonic()
        try:
            result = subprocess.run(cmd, env=env, timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.error("✗ %s TIMED OUT after %ds", circuit, timeout)
            failures.append(circuit)
            continue
        elapsed = time.monotonic() - start
        if result.returncode == 0:
            logger.info("✓ %s in %.0fs", circuit, elapsed)
            ran.append(circuit)
        else:
            logger.error("✗ %s exit %d after %.0fs", circuit, result.returncode, elapsed)
            failures.append(circuit)

    # Sweep cross-circuit Adidas duplicates whenever either Adidas circuit ran.
    # The other circuit's data may have been scraped in a previous run and still
    # be in the DB, so this fires even when only one Adidas circuit ran this batch.
    if not args.dry_run and ({"3ssb", "adidas_gold"} & set(ran)):
        _dedup_adidas(args.season)

    if failures:
        logger.error("failed circuits: %s", ", ".join(failures))
        return 1
    return 0


def _dedup_adidas(season: int) -> None:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        logger.warning("SUPABASE_URL/SUPABASE_SERVICE_KEY not set — skipping Adidas dedup")
        return
    from supabase import create_client
    from .upsert import dedup_adidas_cross_circuit
    dedup_adidas_cross_circuit(create_client(url, key), season)


def cmd_list_circuits(_: argparse.Namespace) -> int:
    for key in _all_circuit_keys():
        print(key)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="basketball_scraper",
        description="Boys grassroots basketball circuit scraper.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def _add_common(s: argparse.ArgumentParser) -> None:
        s.add_argument("--season", type=int, default=int(os.getenv("SEASON", "2026")))
        s.add_argument("--division", default=os.getenv("AGE_DIVISION", "17U"),
                       choices=["15U", "16U", "17U"])
        s.add_argument("--playwright", action="store_true",
                       help="Force Playwright for all requests in this run.")

    p_ing = sub.add_parser("ingest", help="Run a single circuit.")
    p_ing.add_argument("--circuit", required=True, choices=_all_circuit_keys())
    _add_common(p_ing)
    p_ing.set_defaults(func=cmd_ingest)

    p_all = sub.add_parser("ingest-all", help="Run every circuit (each in a subprocess).")
    p_all.add_argument("--circuits", nargs="+", default=_all_circuit_keys(),
                       choices=_all_circuit_keys(), metavar="CIRCUIT")
    p_all.add_argument("--dry-run", action="store_true")
    _add_common(p_all)
    p_all.set_defaults(func=cmd_ingest_all)

    p_list = sub.add_parser("list-circuits", help="Print registered circuit keys.")
    p_list.set_defaults(func=cmd_list_circuits)

    return p


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
