"""
READ-ONLY preview of the age_division backfill.

The scraper wrote per-player age into player_season_stats.age_division instead
of the team's competitive division. Result: filtering by "17U" on the
dashboard returns 0 UAA rows because every UAA stat row says "15U" while the
team itself is "17U".

This preview reports, per circuit, how many stat rows would be rewritten and
the (from -> to) transitions. No writes.

Run from the scraper directory:
    python scripts/preview_age_division_backfill.py
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from supabase import create_client
from basketball_scraper.config import settings


def chunked(xs, n=100):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main() -> None:
    sb = create_client(settings.supabase_url, settings.supabase_service_key)

    circuits = sb.table("circuits").select("id, name").execute().data or []

    grand_match = grand_mismatch = 0
    transitions: Counter[tuple[str, str]] = Counter()

    print("\n== AGE_DIVISION BACKFILL PREVIEW ==")
    for c in sorted(circuits, key=lambda x: x["name"]):
        teams = (
            sb.table("teams")
            .select("id, age_division")
            .eq("circuit_id", c["id"])
            .execute()
            .data
            or []
        )
        if not teams:
            continue
        tid_to_age = {t["id"]: t["age_division"] for t in teams}
        team_ids = list(tid_to_age.keys())

        match = mismatch = 0
        for chunk in chunked(team_ids):
            rows = (
                sb.table("player_season_stats")
                .select("team_id, age_division")
                .in_("team_id", chunk)
                .execute()
                .data
                or []
            )
            for r in rows:
                team_age = tid_to_age[r["team_id"]]
                stat_age = r.get("age_division")
                if stat_age == team_age:
                    match += 1
                else:
                    mismatch += 1
                    transitions[(stat_age or "(none)", team_age or "(none)")] += 1

        grand_match += match
        grand_mismatch += mismatch
        print(f"  {c['name']:10s}: {match:5d} already-correct  {mismatch:5d} would-update")

    print(f"\n  {'TOTAL':10s}: {grand_match:5d} already-correct  {grand_mismatch:5d} would-update")
    print("\n  Transitions (from -> to: count):")
    for (frm, to), n in sorted(transitions.items(), key=lambda x: -x[1]):
        print(f"    {frm:6s} -> {to:6s}  {n:5d}")

    print("\n(No writes performed. Run scripts/apply_age_division_backfill.py to execute.)")


if __name__ == "__main__":
    main()
