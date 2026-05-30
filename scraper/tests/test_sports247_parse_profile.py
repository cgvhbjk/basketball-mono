"""Profile-page parser tests against saved 247Sports fixtures."""
from basketball_scraper.sources.sports247.parse_profile import (
    parse_player_profile,
    parse_highschool_profile,
)


def test_starred_prospect_extracts_all_visible_fields(fixtures_dir):
    html = (fixtures_dir / "sports247_profile_player.html").read_text()
    p = parse_player_profile(
        html, source_url="https://247sports.com/player/cj-rosser-46151476/"
    )
    assert p.player_id == "46151476"
    assert p.name == "CJ Rosser"
    assert p.national_rank == 14
    assert p.state_rank == 2
    assert p.position_rank == 3
    assert p.class_year == 2026
    assert p.hometown and p.hometown.city == "Atlanta" and p.hometown.state == "GA"
    assert p.high_school == "Wheeler High School"
    assert p.position == "PG"
    assert p.height_inches == 75 and p.height_raw == "6-3"
    assert p.weight_lbs == 185
    assert p.offers_count == 27
    assert p.visits_count == 5
    assert p.commitment_status == "Uncommitted"
    assert p.commitment_team is None


def test_starred_prospect_reads_stars_from_icons(fixtures_dir):
    html = (fixtures_dir / "sports247_profile_player.html").read_text()
    p = parse_player_profile(html, source_url="https://247sports.com/player/cj-rosser-46151476/")
    assert p.stars == 4
    assert p.stars_source == "icons"
    assert p.composite_rating == 0.9712


def test_unranked_highschool_variant_falls_back_to_composite(fixtures_dir):
    html = (fixtures_dir / "sports247_profile_highschool.html").read_text()
    p = parse_highschool_profile(
        html,
        source_url="https://247sports.com/player/marcus-lee-46151590/high-school-99999/",
    )
    assert p.name == "Marcus Lee"
    # National + position rank are em-dashes → null
    assert p.national_rank is None
    assert p.position_rank is None
    # State rank still parses
    assert p.state_rank == 48
    # 0.8450 lands in the 3-star band per the documented thresholds
    assert p.stars == 3
    assert p.stars_source == "composite_threshold"
    assert p.composite_rating == 0.8450
    # Commitment team surfaces from the meta card
    assert p.commitment_team == "Duke"


def test_missing_height_does_not_raise():
    html = "<html><body><h1>Anon Prospect</h1><dl><dt>Position</dt><dd>SG</dd></dl></body></html>"
    p = parse_player_profile(html, source_url="https://247sports.com/player/anon-1/")
    assert p.height_inches is None
    assert p.height_raw is None
    assert p.weight_lbs is None
    assert p.stars_source == "unknown"
