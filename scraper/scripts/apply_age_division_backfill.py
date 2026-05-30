"""
Destructive: set player_season_stats.age_division = teams.age_division for
every stat row where the two disagree. Groups by team so each UPDATE rewrites
all of a team's rows in one call.

Run from the scraper directory:
    python scripts/apply_age_division_backfill.py

Run scripts/preview_age_division_backfill.py first.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from supabase import create_client
from basketball_scraper.config import settings


def chunked(xs, n=100):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main() -> None:
    sb = create_client(settings.supabase_url, settings.supabase_service_key)

    teams = sb.table("teams").select("id, age_division").execute().data or []

    # Group teams by their age_division so we issue one UPDATE per (division,
    # team-batch) instead of per-team.
    by_age: dict[str, list[str]] = {}
    for t in teams:
        by_age.setdefault(t["age_division"], []).append(t["id"])

    grand_updated = 0
    for age, team_ids in by_age.items():
        if not age:
            continue
        n = 0
        for chunk in chunked(team_ids):
            # Only rewrite rows whose age_division is currently wrong — this
            # keeps the update count honest and skips already-correct rows.
            res = (
                sb.table("player_season_stats")
                .update({"age_division": age})
                .in_("team_id", chunk)
                .neq("age_division", age)
                .execute()
            )
            n += len(res.data or [])
        print(f"  {age:6s}: {n:5d} rows rewritten across {len(team_ids)} teams")
        grand_updated += n

    print(f"\nTotal rows updated: {grand_updated}")


if __name__ == "__main__":
    main()
