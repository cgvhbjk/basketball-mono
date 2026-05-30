"""Quick smoke test for the On3 enricher — hits a small set of known names
and prints what came back. Not wired into CI.

    python -m basketball_scraper.scripts.smoke_on3
"""
from __future__ import annotations
import asyncio
import logging

from basketball_scraper.enrich_on3 import On3Enricher

# Mix of well-known prospects + a current pro. If the enricher returns at
# least 3/5 with ranks or stars, the matcher is healthy.
SAMPLES = [
    ("Cooper", "Flagg"),
    ("Bronny", "James"),
    ("AJ", "Dybantsa"),
    ("Cameron", "Boozer"),
    ("Tre", "Johnson"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    async with On3Enricher() as enricher:
        for first, last in SAMPLES:
            profile = await enricher.lookup(first, last)
            print(f"{first} {last:>14} -> {profile}")


if __name__ == "__main__":
    asyncio.run(main())
