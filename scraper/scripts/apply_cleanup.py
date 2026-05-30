"""
Destructive cleanup, per user confirmation.

Two actions:
  1. Delete the 5 (circuit, age_division) combos listed in DELETE_TARGETS,
     cascading box_scores → player_season_stats → team_rosters → teams.
     Players themselves stay — they may appear in other (circuit, age).
  2. NULL the 5 columns listed in CLEAR_COLUMNS across all `players` rows.

Run from the scraper directory:
    python scripts/apply_cleanup.py

Has no dry-run flag by design — use scripts/preview_cleanup.py first.
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

    # ---- 1. Collect every team_id we're deleting ----
    all_team_ids: list[str] = []
    for circ, age in DELETE_TARGETS:
        cid = name_to_id.get(circ)
        if not cid:
            print(f"  {circ:8s} {age}: UNKNOWN circuit, skipping")
            continue
        rows = (
            sb.table("teams")
            .select("id")
            .eq("circuit_id", cid)
            .eq("age_division", age)
            .execute()
            .data
            or []
        )
        all_team_ids.extend(r["id"] for r in rows)
    print(f"Collected {len(all_team_ids)} teams to delete")

    if all_team_ids:
        # ---- 2. Find games involving any target team (home OR away) ----
        # These games contain box scores from BOTH teams; deleting only
        # target-team box scores leaves opponents' box scores referencing
        # the game we want to drop, so we have to find game ids first and
        # delete every box score on those games.
        game_ids: set[str] = set()
        for chunk in chunked(all_team_ids):
            for side in ("home_team_id", "away_team_id"):
                rows = sb.table("games").select("id").in_(side, chunk).execute().data or []
                game_ids.update(r["id"] for r in rows)
        print(f"  found {len(game_ids)} games involving target teams")

        # ---- 3. Cascade delete in FK-safe order ----
        #   box_scores (by game_id — catches opponents too)
        #   player_season_stats (team_id)
        #   team_rosters (team_id)
        #   games (id)
        #   teams (id)
        game_id_list = list(game_ids)
        plan = [
            ("box_scores", "game_id", "box scores", game_id_list),
            ("player_season_stats", "team_id", "season stats", all_team_ids),
            ("team_rosters", "team_id", "roster rows", all_team_ids),
            ("games", "id", "games", game_id_list),
            ("teams", "id", "teams", all_team_ids),
        ]
        for table, key, label, ids in plan:
            if not ids:
                print(f"  skipped {label} (no ids)")
                continue
            n = 0
            for chunk in chunked(ids):
                try:
                    res = sb.table(table).delete().in_(key, chunk).execute()
                    n += len(res.data or [])
                except Exception as exc:
                    print(f"  {label}: failed on chunk ({exc})")
                    raise
            print(f"  deleted {n} {label}")

    # ---- 3. Clear the columns ----
    print("\nClearing player columns:")
    patch = {col: None for col in CLEAR_COLUMNS}
    # Supabase requires a filter on UPDATE — `not.is_(id, null)` matches all.
    res = sb.table("players").update(patch).not_.is_("id", "null").execute()
    print(f"  {len(res.data or [])} player rows updated → {list(CLEAR_COLUMNS)} set NULL")

    print("\nDone.")


if __name__ == "__main__":
    main()
