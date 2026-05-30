"""
READ-ONLY preview before any DB mutation. Run before `apply_cleanup.py`.

Reports two things the user asked about:

  1. For each (circuit, age_division) targeted for deletion, the row counts
     that would cascade out — teams, rosters, stats, box scores. No writes.
  2. Dry-run of the column clear: how many rows in `players` currently have
     non-null values in grad_year / height_inches / national_rank /
     state_rank / star_rating. The UPDATE itself is NOT executed here.

Run from the scraper directory:
    python scripts/preview_cleanup.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from supabase import create_client
from basketball_scraper.config import settings


DELETE_TARGETS = [
    ("EYCL", "15U"),
    ("EYCL", "16U"),
    ("EYBL", "15U"),
    ("3SSB", "15U"),
    ("3SSB", "16U"),
]

CLEAR_COLUMNS = ("grad_year", "height_inches", "national_rank", "state_rank", "star_rating")


def chunked(xs, n=100):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main() -> None:
    sb = create_client(settings.supabase_url, settings.supabase_service_key)

    circuits = sb.table("circuits").select("id, name").execute().data or []
    name_to_id = {c["name"]: c["id"] for c in circuits}

    print("\n== DELETE PREVIEW ==")
    grand_teams = grand_rosters = grand_stats = grand_box = 0
    for circ, age in DELETE_TARGETS:
        cid = name_to_id.get(circ)
        if not cid:
            print(f"  {circ:8s} {age}: UNKNOWN circuit")
            continue
        teams = sb.table("teams").select("id").eq("circuit_id", cid).eq("age_division", age).execute().data or []
        team_ids = [t["id"] for t in teams]
        if not team_ids:
            print(f"  {circ:8s} {age}: 0 teams")
            continue

        roster_n = stats_n = box_n = 0
        for chunk in chunked(team_ids):
            roster_n += sb.table("team_rosters").select("team_id", count="exact").in_("team_id", chunk).limit(1).execute().count or 0
            stats_n  += sb.table("player_season_stats").select("id", count="exact").in_("team_id", chunk).limit(1).execute().count or 0
            try:
                box_n += sb.table("box_scores").select("id", count="exact").in_("team_id", chunk).limit(1).execute().count or 0
            except Exception:
                # box_scores may use source_team_id (string) not team_id (uuid)
                # in the older schema. Apply step handles both.
                pass

        print(f"  {circ:8s} {age}: {len(team_ids):3d} teams · {roster_n:5d} rosters · {stats_n:5d} stats · {box_n:4d} box-scores")
        grand_teams += len(team_ids)
        grand_rosters += roster_n
        grand_stats += stats_n
        grand_box += box_n

    print(f"  {'TOTAL':12s}: {grand_teams:3d} teams · {grand_rosters:5d} rosters · {grand_stats:5d} stats · {grand_box:4d} box-scores")

    print("\n== COLUMN CLEAR DRY-RUN ==")
    total_players = sb.table("players").select("id", count="exact").limit(1).execute().count or 0
    print(f"  Total players: {total_players}")
    for col in CLEAR_COLUMNS:
        nn = sb.table("players").select("id", count="exact").not_.is_(col, "null").limit(1).execute().count or 0
        pct = (nn / total_players * 100) if total_players else 0
        print(f"  {col:15s}  non-null in {nn:5d} rows ({pct:5.1f}%)")

    print("\n(No writes performed. Run scripts/apply_cleanup.py to execute.)")


if __name__ == "__main__":
    main()
