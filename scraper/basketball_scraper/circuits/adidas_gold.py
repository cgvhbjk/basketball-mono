"""
Adidas Gold scraper — 3Stripes Gold Basketball (boys, 17U).
Second tier of the Adidas circuit; same adidas3ssb.com platform as 3SSB.
Covers the Select and Stripes play levels (below Platinum/3SSB).
"""
from .adidas_3ssb import Adidas3SSBScraper


class AdidasGoldScraper(Adidas3SSBScraper):
    circuit_name = "Gold"
    circuit_org = "Adidas"
    # Gold tier sits under brandNumber=10003 with playLevel=Gold in the live
    # adidas-stats-wp API (verified May 2026: 1,259 17U players returned).
    _BRAND_LEVELS = ((10003, "Gold"),)
