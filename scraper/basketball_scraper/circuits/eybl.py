"""
EYBL scraper — Nike Elite Youth Basketball League (boys, 15U / 16U / 17U).

Source
------
Cerebro Widget tRPC API (see `cerebro.py`). One LeaguesList call resolves
the EYBL UUID for the requested division; everything else hangs off the
shared CerebroLeagueScraper base.

The legacy Pointstreak backend at `nikeeyb.wtthoops.pointstreak.com` is no
longer the primary source — Cerebro is faster, richer (per-game box scores,
advanced stats), and covers all three age divisions under one umbrella.
"""
from .cerebro import CerebroLeagueScraper


class EYBLScraper(CerebroLeagueScraper):
    circuit_name = "EYBL"
    circuit_org = "Nike"
    _LEAGUE_NAME_PREFIX = "EYBL"
