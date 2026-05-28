"""
Adidas Gold scraper — 3Stripes Gold Basketball (boys, 17U).
Second tier of the Adidas circuit; same adidas3ssb.com platform as 3SSB.
Covers the Select and Stripes play levels (below Platinum/3SSB).
"""
from .adidas_3ssb import Adidas3SSBScraper


class AdidasGoldScraper(Adidas3SSBScraper):
    circuit_name = "Gold"
    circuit_org = "Adidas"
    circuit_gender = "boys"
    # adidas3ssb.com's playLevel filter takes Platinum / Select / Stripes; per the
    # docstring, Gold covers Select + Stripes (below Platinum/3SSB).
    _PLAY_LEVELS = ["Select", "Stripes"]
