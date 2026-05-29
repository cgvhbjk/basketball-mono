"""
EYCL scraper — Nike Elite Youth Champions League (BOYS, 15U / 16U / 17U).

This adapter is for the boys EYCL ONLY. The previous version of this file
targeted nikegirlseybl.com / ExposureEvents (the girls Champions League);
that source has been removed because the men's pipeline is boys-only.

Source
------
Cerebro Widget tRPC API (see `cerebro.py`). One LeaguesList call resolves
the boys EYCL UUID for the requested division; everything else hangs off
the shared CerebroLeagueScraper base.
"""
from .cerebro import CerebroLeagueScraper


class EYCLScraper(CerebroLeagueScraper):
    circuit_name = "EYCL"
    circuit_org = "Nike"
    _LEAGUE_NAME_PREFIX = "EYCL"
