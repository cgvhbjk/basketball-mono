"""Tests for the Cerebro tRPC response parsers."""
from basketball_scraper.circuits.cerebro import (
    aggregate_per_game_stats,
    parse_box_score,
    parse_player_row,
    _trpc_input,
)


def test_trpc_input_encodes_single_procedure_envelope():
    enc = _trpc_input({"overallId": "260104"})
    # URL-encoded, but should round-trip through a decoder.
    import json, urllib.parse
    obj = json.loads(urllib.parse.unquote(enc))
    assert obj == {"0": {"json": {"overallId": "260104"}}}


def test_parse_player_row_keeps_real_position_and_drops_unknown():
    row = {
        "id": "abc",
        "name": "Jane Doe",
        "position": "Unknown Position",
        "teamId": "team-1",
        "games_played": 3,
        "pts_per_game": 12.0,
    }
    p, re, s = parse_player_row(row, season=2026, age_division="17U")
    assert p.position is None
    assert s.games_played == 3
    assert s.ppg == 12.0
    assert re.source_team_id == "team-1"


def test_parse_player_row_normalizes_height_and_weight():
    row = {
        "id": "x", "name": "Big Guy", "teamId": "t",
        "heightInches": 80, "weightLb": 210, "games_played": 5,
        "pts_per_game": 8.0, "fg_pct": 0.5,
    }
    p, _, _ = parse_player_row(row, 2026, "17U")
    assert p.height_inches == 80
    assert p.weight_lbs == 210


def test_parse_player_row_rejects_implausible_height():
    row = {
        "id": "x", "name": "Glitch",
        "teamId": "t", "heightInches": 9, "games_played": 1,
    }
    p, _, _ = parse_player_row(row, 2026, "17U")
    assert p.height_inches is None


def test_parse_player_row_skips_when_id_missing():
    row = {"name": "Anon", "teamId": "t", "games_played": 1}
    assert parse_player_row(row, 2026, "17U") is None


def test_parse_player_row_team_id_falls_back_to_argument():
    row = {"id": "p", "name": "First Last", "games_played": 4, "pts_per_game": 10}
    p, re, s = parse_player_row(row, 2026, "17U", team_source_id="explicit-team")
    assert re.source_team_id == "explicit-team"
    assert s.source_team_id == "explicit-team"


def test_parse_player_row_handles_no_games_played():
    row = {"id": "p", "name": "Bench Warmer", "teamId": "t"}
    p, re, s = parse_player_row(row, 2026, "17U")
    # Stats row still produced so the player shows up on the roster, just empty.
    assert s.games_played is None
    assert s.ppg is None


def test_parse_player_row_derives_mpg_from_total_minutes():
    row = {
        "id": "p", "name": "Active Guy", "teamId": "t",
        "games_played": 11, "total_minutes": 45,
    }
    _, _, s = parse_player_row(row, 2026, "17U")
    assert s.games_played == 11
    assert s.mpg is not None
    assert abs(s.mpg - (45 / 11)) < 1e-9


def test_aggregate_per_game_stats_averages_across_games():
    games = [
        {"fga": 10, "fta": 4, "orb": 2, "drb": 5, "minutes": 28, "pf": 2, "fgm": 5, "ftm": 3, "three_pm": 1, "three_pa": 3},
        {"fga": 8,  "fta": 0, "orb": 1, "drb": 4, "minutes": 22, "pf": 1, "fgm": 4, "ftm": 0, "three_pm": 0, "three_pa": 2},
        {"fga": 12, "fta": 6, "orb": 3, "drb": 6, "minutes": 30, "pf": 3, "fgm": 6, "ftm": 5, "three_pm": 2, "three_pa": 4},
    ]
    agg = aggregate_per_game_stats(games)
    assert abs(agg["fga"] - 10.0) < 1e-9
    assert abs(agg["fta"] - (10 / 3)) < 1e-9
    assert abs(agg["oreb"] - 2.0) < 1e-9
    assert abs(agg["dreb"] - 5.0) < 1e-9
    assert abs(agg["mpg"] - (80 / 3)) < 1e-9
    assert abs(agg["fpg"] - 2.0) < 1e-9
    assert abs(agg["fgm_pg"] - 5.0) < 1e-9
    assert abs(agg["ftm_pg"] - (8 / 3)) < 1e-9
    assert abs(agg["three_pm_pg"] - 1.0) < 1e-9
    assert abs(agg["three_pa_pg"] - 3.0) < 1e-9


def test_aggregate_per_game_stats_returns_none_for_missing_field():
    # No `orb`/`drb`/`pf` in any record → those aggregates stay None.
    games = [{"fga": 5, "fta": 2, "minutes": 20}, {"fga": 7, "fta": 1, "minutes": 18}]
    agg = aggregate_per_game_stats(games)
    assert agg["oreb"] is None
    assert agg["dreb"] is None
    assert agg["fpg"] is None
    assert agg["fga"] == 6.0


def test_aggregate_per_game_stats_empty_input():
    agg = aggregate_per_game_stats([])
    # Every expected key is present and None.
    assert set(agg.keys()) == {
        "fga", "fta", "oreb", "dreb", "mpg", "fpg",
        "fgm_pg", "ftm_pg", "three_pm_pg", "three_pa_pg",
    }
    assert all(v is None for v in agg.values())


def test_parse_box_score_extracts_all_fields():
    rec = {
        "game_id": "g-1", "team_id": "t-1", "opp_team_id": "t-2",
        "minutes": 28.5,
        "pts": 18, "reb": 7, "orb": 2, "ast": 4, "stl": 2, "blk": 1, "tov": 3, "pf": 2,
        "fgm": 7, "fga": 14, "three_pm": 2, "three_pa": 5, "ftm": 2, "fta": 2,
    }
    box = parse_box_score(rec, player_source_id="p-1")
    assert box is not None
    assert box.source_game_id == "g-1"
    assert box.source_player_id == "p-1"
    assert box.source_team_id == "t-1"
    assert box.minutes == 28.5
    assert box.points == 18
    assert box.rebounds == 7
    assert box.offensive_rebounds == 2
    assert box.fga == 14 and box.fgm == 7
    assert box.three_pa == 5 and box.three_pm == 2
    assert box.fta == 2 and box.ftm == 2


def test_parse_box_score_returns_none_without_game_id():
    rec = {"team_id": "t-1", "pts": 10}
    assert parse_box_score(rec, player_source_id="p-1") is None


def test_parse_box_score_returns_none_without_team_id():
    rec = {"game_id": "g-1", "pts": 10}
    assert parse_box_score(rec, player_source_id="p-1") is None


def test_parse_box_score_captures_defensive_rebounds():
    rec = {"game_id": "g-1", "team_id": "t-1", "orb": 2, "drb": 5, "reb": 7}
    box = parse_box_score(rec, player_source_id="p-1")
    assert box.offensive_rebounds == 2
    assert box.defensive_rebounds == 5
    assert box.rebounds == 7


def test_parse_player_row_captures_ft_pct_and_dob_and_nationality():
    row = {
        "id": "p", "name": "Bio Guy", "teamId": "t",
        "games_played": 8, "ft_pct": 0.85,
        "dateOfBirth": "2008-04-12T00:00:00Z",
        "nationality": "USA",
    }
    p, _, s = parse_player_row(row, 2026, "17U")
    assert s.ft_pct == 0.85
    assert p.date_of_birth is not None
    assert p.date_of_birth.year == 2008 and p.date_of_birth.month == 4
    assert p.nationality == "USA"
