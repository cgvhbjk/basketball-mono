"""Tests for normalized data models."""
from basketball_scraper.models import Player, SeasonStats, _parse_height


def test_parse_height_feet_dash_inches():
    assert _parse_height("6-3") == 75


def test_parse_height_with_apostrophe():
    assert _parse_height("6'3") == 75


def test_parse_height_pure_inches():
    assert _parse_height("78") == 78


def test_parse_height_unparseable_returns_none():
    assert _parse_height("tall") is None


def test_player_normalizes_height_raw():
    p = Player(source_id="1", first_name="A", last_name="B", height_raw="6-7")
    assert p.height_inches == 79


def test_player_height_inches_wins_when_both_given():
    p = Player(source_id="1", first_name="A", last_name="B", height_raw="6-7", height_inches=80)
    assert p.height_inches == 80


def test_player_rejects_grad_year_outside_window():
    p = Player(source_id="1", first_name="A", last_name="B", grad_year=2010)
    assert p.grad_year is None


def test_player_accepts_grad_year_string():
    p = Player(source_id="1", first_name="A", last_name="B", grad_year="2027")
    assert p.grad_year == 2027


def test_season_stats_normalizes_percent_above_one():
    s = SeasonStats(source_player_id="1", source_team_id="t1", season=2026, fg_pct=52.0)
    assert s.fg_pct == 0.52


def test_season_stats_keeps_percent_already_fraction():
    s = SeasonStats(source_player_id="1", source_team_id="t1", season=2026, fg_pct=0.41)
    assert s.fg_pct == 0.41


def test_season_stats_preserves_one_hundred_percent_fraction():
    s = SeasonStats(source_player_id="1", source_team_id="t1", season=2026, fg_pct=1.0)
    assert s.fg_pct == 1.0
