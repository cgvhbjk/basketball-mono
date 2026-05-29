"""CLI smoke tests — just confirm the parser wires up without importing settings."""
from basketball_scraper.cli import build_parser


def test_parser_lists_subcommands():
    p = build_parser()
    # The subparsers action carries the action group registry.
    sub = next(a for a in p._subparsers._actions if a.dest == "cmd")
    names = set(sub.choices.keys())
    assert {"ingest", "ingest-all", "list-circuits"} <= names


def test_ingest_subparser_requires_circuit():
    p = build_parser()
    # Missing --circuit → SystemExit.
    import pytest
    with pytest.raises(SystemExit):
        p.parse_args(["ingest"])


def test_ingest_subparser_accepts_known_circuit():
    p = build_parser()
    ns = p.parse_args(["ingest", "--circuit", "eybl", "--season", "2026", "--division", "17U"])
    assert ns.circuit == "eybl"
    assert ns.season == 2026
    assert ns.division == "17U"
    assert ns.playwright is False
