"""
Delete all team-scoped data for one or more circuits, so they can be
re-scraped cleanly. Players are shared across circuits (merged by name /
passport_id) and are NOT deleted.

Cascade order (FK-safe):
  box_scores (by game_id for games involving the circuit's teams)
  player_season_stats (team_id)
  team_rosters (team_id)
  games (id)
  teams (id)

Usage (from scraper dir):
    python scripts/delete_circuit_data.py "UAA" "UAA Rise"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from supabase import create_client
from basketball_scraper.config import settings


def chunked(xs, n=100):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def main(circuit_names: list[str]) -> None:
    sb = create_client(settings.supabase_url, settings.supabase_service_key)
    name_to_id = {c["name"]: c["id"] for c in (sb.table("circuits").select("id, name").execute().data or [])}

    all_team_ids: list[str] = []
    for name in circuit_names:
        cid = name_to_id.get(name)
        if not cid:
            print(f"  {name}: UNKNOWN circuit, skipping")
            continue
        rows = sb.table("teams").select("id").eq("circuit_id", cid).execute().data or []
        ids = [r["id"] for r in rows]
        print(f"  {name}: {len(ids)} teams")
        all_team_ids.extend(ids)

    if not all_team_ids:
        print("Nothing to delete.")
        return

    # Games involving any target team (home OR away) — box scores hang off games.
    game_ids: set[str] = set()
    for chunk in chunked(all_team_ids):
        for side in ("home_team_id", "away_team_id"):
            try:
                rows = sb.table("games").select("id").in_(side, chunk).execute().data or []
                game_ids.update(r["id"] for r in rows)
            except Exception:
                pass
    game_id_list = list(game_ids)
    print(f"  {len(game_id_list)} games involve these teams")

    plan = [
        ("box_scores", "game_id", "box scores", game_id_list),
        ("player_season_stats", "team_id", "season stats", all_team_ids),
        ("team_rosters", "team_id", "roster rows", all_team_ids),
        ("games", "id", "games", game_id_list),
        ("teams", "id", "teams", all_team_ids),
    ]
    for table, key, label, ids in plan:
        if not ids:
            print(f"  skipped {label} (none)")
            continue
        n = 0
        for chunk in chunked(ids):
            res = sb.table(table).delete().in_(key, chunk).execute()
            n += len(res.data or [])
        print(f"  deleted {n} {label}")

    print("\nDone.")


if __name__ == "__main__":
    names = sys.argv[1:] or ["UAA", "UAA Rise"]
    print(f"Deleting circuit data for: {names}")
    main(names)
