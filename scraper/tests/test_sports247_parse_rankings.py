"""Ranking-page seed extraction tests."""
from basketball_scraper.sources.sports247.parse_rankings import iter_seeds, next_page_url


def test_seeds_extracted_in_order_with_dedup(fixtures_dir):
    html = (fixtures_dir / "sports247_rankings_page1.html").read_text()
    seeds = list(iter_seeds(html, "https://247sports.com/season/2026-basketball/recruitrankings/"))
    # 3 distinct players; the duplicate CJ Rosser headshot link is deduped.
    assert [s.player_id for s in seeds] == ["46151400", "46151476", "46151590"]
    assert seeds[0].profile_url.endswith("/player/aj-walker-46151400/")
    assert seeds[1].name == "CJ Rosser"


def test_next_page_link_detected(fixtures_dir):
    html = (fixtures_dir / "sports247_rankings_page1.html").read_text()
    nxt = next_page_url(html, "https://247sports.com/season/2026-basketball/recruitrankings/")
    assert nxt == "https://247sports.com/season/2026-basketball/recruitrankings/?Page=2"


def test_next_page_increments_when_no_link_present():
    html = "<html><body>nothing here</body></html>"
    nxt = next_page_url(html, "https://247sports.com/x/?Page=3")
    assert nxt and "Page=4" in nxt
