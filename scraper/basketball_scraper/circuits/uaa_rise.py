"""
UAA Rise scraper — Under Armour Association Rise (boys, 17U).
Second tier of the UA circuit; shares the same underarmournext.com platform
and URL structure as UAA — only the hub page differs.
"""
from .uaa import UAAScraper


class UAARiseScraper(UAAScraper):
    circuit_name = "UAA Rise"
    circuit_org = "Under Armour"
    _HUB_PATH = "/basketball/boys-rise/"
