"""
CLI for the 247Sports extractor.

Two subcommands:

  extract — seed from a ranking list URL, fetch each player profile (with
            cache + rate limit + robots gate), parse, and append to JSONL.

  parse   — read a single HTML file from disk (--html) and print one
            ProfileExtract as JSON. This is the escape hatch when a URL is
            disallowed: save the page in a browser and parse offline.

Run with:
  python -m basketball_scraper.sources.sports247 <subcommand> [args]
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .compliance import DisallowedURL, RobotsGuard
from .fetch import CachingFetcher, PermanentFetchError, USER_AGENT
from .parse_profile import parse_player_profile
from .parse_rankings import iter_seeds, next_page_url
from .storage import default_path, write_jsonl

logger = logging.getLogger(__name__)


async def _cmd_extract(args: argparse.Namespace) -> int:
    guard = RobotsGuard(ua=USER_AGENT)
    fetcher = CachingFetcher(guard=guard)
    out_path = Path(args.out) if args.out else default_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    seen_player_ids: set[str] = set()
    extracted = 0
    current_url = args.ranking_url

    try:
        while current_url and extracted < args.limit:
            logger.info("fetching ranking page: %s", current_url)
            try:
                # Ranking pages get a shorter cache window — they update more often.
                ranking_html_bytes = await fetcher.get(current_url, max_age=24 * 3600)
            except DisallowedURL as exc:
                print(str(exc), file=sys.stderr)
                return 1
            except PermanentFetchError as exc:
                print(_blocked_message(str(exc)), file=sys.stderr)
                return 2
            ranking_html = ranking_html_bytes.decode("utf-8", errors="replace")

            page_yielded = 0
            for seed in iter_seeds(ranking_html, current_url):
                if seed.player_id in seen_player_ids:
                    continue
                if extracted >= args.limit:
                    break
                seen_player_ids.add(seed.player_id)
                page_yielded += 1

                try:
                    body = await fetcher.get(seed.profile_url)
                except DisallowedURL as exc:
                    logger.warning("skipping disallowed profile %s: %s", seed.profile_url, exc)
                    continue
                except PermanentFetchError as exc:
                    logger.warning("skipping blocked profile %s: %s", seed.profile_url, exc)
                    continue

                profile = parse_player_profile(body.decode("utf-8", errors="replace"), seed.profile_url)
                write_jsonl([profile], out_path)
                extracted += 1
                logger.info(
                    "[%d/%d] %s — natl=%s state=%s stars=%s(%s)",
                    extracted, args.limit, profile.name or seed.player_id,
                    profile.national_rank, profile.state_rank,
                    profile.stars, profile.stars_source,
                )

            if page_yielded == 0:
                # No new IDs on this page — stop paginating to avoid loops.
                logger.info("no new players on this page — stopping pagination")
                break

            current_url = next_page_url(ranking_html, current_url)
    finally:
        await fetcher.close()

    logger.info("done. %d profiles written to %s", extracted, out_path)
    return 0


def _cmd_parse(args: argparse.Namespace) -> int:
    path = Path(args.html)
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    html = path.read_text(encoding="utf-8", errors="replace")
    source_url = args.source_url or ""
    profile = parse_player_profile(html, source_url)
    print(profile.model_dump_json(indent=2))
    return 0


def _cmd_parse_dir(args: argparse.Namespace) -> int:
    """Walk a directory of saved 247 profile HTML files and append each
    parsed ProfileExtract to a JSONL. This is the documented offline path
    for when the live `extract` subcommand is blocked by 247's bot shield.

    Source URLs are taken from the filename if it looks like a 247 player
    URL pattern, else left empty. To bind a file to a specific URL, name
    the file `<slug>-<id>.html` (the parser uses the trailing id).
    """
    src_dir = Path(args.dir)
    if not src_dir.is_dir():
        print(f"not a directory: {src_dir}", file=sys.stderr)
        return 1
    out_path = Path(args.out) if args.out else default_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    for html_path in sorted(src_dir.glob("*.html")):
        html = html_path.read_text(encoding="utf-8", errors="replace")
        synthetic_url = f"https://247sports.com/player/{html_path.stem}/"
        profile = parse_player_profile(html, synthetic_url)
        write_jsonl([profile], out_path)
        written += 1
        logger.info(
            "%s — natl=%s state=%s stars=%s(%s)",
            html_path.name, profile.national_rank, profile.state_rank,
            profile.stars, profile.stars_source,
        )
    logger.info("wrote %d profiles to %s", written, out_path)
    return 0


def _blocked_message(detail: str) -> str:
    return (
        f"247Sports refused the request: {detail}\n"
        "\n"
        "247 actively blocks automated clients (even headless Chrome) at\n"
        "the CDN edge. Per the project's compliance constraints, we do NOT\n"
        "attempt to evade this.\n"
        "\n"
        "Offline path (the documented workaround):\n"
        "  1. Open the page in your normal browser.\n"
        "  2. Save the full HTML (Cmd+S → Webpage, HTML Only).\n"
        "  3. Drop all saved files into one directory.\n"
        "  4. Run:\n"
        "       python -m basketball_scraper.sources.sports247 parse-dir \\\n"
        "           --dir <directory> [--out 247_extracts/<date>_247.jsonl]\n"
        "  5. Then: python enrich_players.py --source 247\n"
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m basketball_scraper.sources.sports247")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ex = sub.add_parser("extract", help="Seed from a ranking URL and extract profiles to JSONL.")
    p_ex.add_argument("--ranking-url", required=True)
    p_ex.add_argument("--limit", type=int, default=50)
    p_ex.add_argument("--out", default=None, help="Output JSONL path (default: 247_extracts/<today>_247.jsonl)")
    p_ex.set_defaults(func=_cmd_extract)

    p_pa = sub.add_parser("parse", help="Parse a single saved HTML file and print a ProfileExtract.")
    p_pa.add_argument("--html", required=True)
    p_pa.add_argument("--source-url", default=None)
    p_pa.set_defaults(func=_cmd_parse)

    p_pd = sub.add_parser(
        "parse-dir",
        help="Batch-parse a directory of saved 247 profile HTML files into JSONL.",
    )
    p_pd.add_argument("--dir", required=True, help="Directory of *.html files.")
    p_pd.add_argument("--out", default=None, help="Output JSONL (default: 247_extracts/<today>_247.jsonl)")
    p_pd.set_defaults(func=_cmd_parse_dir)

    args = parser.parse_args(argv)
    func = args.func
    if asyncio.iscoroutinefunction(func):
        return asyncio.run(func(args))
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
