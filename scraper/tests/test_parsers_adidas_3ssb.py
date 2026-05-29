"""Regression tests for the Adidas 3SSB HTML parser using a saved fixture."""
from basketball_scraper.circuits.adidas_3ssb import (
    parse_stats_page,
    _parse_stats_json,
    _slug,
)


def test_slug_kebab_cases_team_name():
    assert _slug("Slow Grind Elite") == "slow-grind-elite"
    assert _slug("Team Final") == "team-final"


def test_parse_stats_page_extracts_two_eligible_players(fixtures_dir):
    html = (fixtures_dir / "adidas_3ssb_stats_page.html").read_text()
    rows = parse_stats_page(html, season=2026, age_division="17U")

    # Zero-GP and no-passport-link rows are skipped.
    assert len(rows) == 2

    p1, re1, s1 = rows[0]
    assert p1.first_name == "Jalen"
    assert p1.last_name == "Davis"
    assert re1.source_team_id == "slow-grind-elite"
    assert s1.games_played == 14
    assert s1.ppg == 22.4
    # FG% on the source is 52.3 (0–100 scale); the model normalizes to 0–1.
    assert s1.fg_pct == 0.523

    p2, _, s2 = rows[1]
    # Apostrophes in the name span survive parsing.
    assert p2.last_name == "O'Brien"
    assert s2.bpg == 1.9


def test_parse_stats_json_handles_players_envelope():
    data = {
        "players": [
            {
                "id": 999,
                "first_name": "Casey",
                "last_name": "Jones",
                "team_name": "EYBL Boys 17U",
                "games_played": 15,
                "ppg": 19.4,
                "rpg": 5.2,
                "apg": 3.0,
                "fg_pct": 0.51,
            },
            {
                "id": None,  # ignored
                "first_name": "Skip",
                "team_name": "x",
            },
        ]
    }
    rows = _parse_stats_json(data, season=2026, age_division="17U")
    assert len(rows) == 1
    _, re, stats = rows[0]
    assert re.source_team_id == "eybl-boys-17u"
    assert stats.ppg == 19.4
    assert stats.fg_pct == 0.51


def test_parse_stats_json_captures_full_field_inventory():
    """All fields the live OGP feed exposes should be captured."""
    data = [
        {
            "playerNumber": 11511,
            "firstName": "Jalen",
            "lastName": "Davis",
            "teamSlug": "slow-grind-elite-17u",
            "teamName": "Slow Grind Elite",
            "gamesPlayed": 8,
            "eventsPlayed": 1,
            "wins": 3,
            "losses": 5,
            "ppg": 24.125,
            "rpg": 5.375,
            "apg": 4.625,
            "spg": 2.625,
            "bpg": 0.375,
            "tpg": 1.375,
            "fgPct": 0.47015,
            "threePointPct": 0.26087,
            "ftPct": 0.8871,
            "orpg": 1.625,
            "drpg": 3.75,
            "fpg": 1.375,
            "threePg": 1.5,
            "plusMinus": 0,
            "positions": ["COMBO_GUARD"],
        }
    ]
    rows = _parse_stats_json(data, season=2026, age_division="17U")
    assert len(rows) == 1
    p, re, s = rows[0]
    assert s.ft_pct == 0.8871
    assert s.dreb == 3.75
    assert s.oreb == 1.625
    assert s.fpg == 1.375
    assert s.three_pm_pg == 1.5
    assert s.plus_minus == 0
    assert s.events_played == 1
    # Wins/losses are stashed on roster_entry for fetch_teams to consume.
    assert getattr(re, "_team_wins") == 3
    assert getattr(re, "_team_losses") == 5
    assert p.position == "Combo Guard"


def test_parse_stats_json_tolerates_top_level_list():
    data = [
        {
            "passportId": 1,
            "name": "Alpha Beta",
            "team": "Hoops",
            "gp": 8,
            "ppg": 10.0,
        }
    ]
    rows = _parse_stats_json(data, season=2026, age_division="17U")
    assert len(rows) == 1
    p, _, s = rows[0]
    assert p.first_name == "Alpha"
    assert p.last_name == "Beta"
    assert s.games_played == 8
