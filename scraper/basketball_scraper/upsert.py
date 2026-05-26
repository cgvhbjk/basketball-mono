"""
Supabase upsert helpers.
Uses the service-role key — bypasses RLS for write access.
"""
from __future__ import annotations
import logging
import time
from typing import Any
from supabase import Client

logger = logging.getLogger(__name__)

_BIO_FIELDS = ("height_inches", "position", "high_school", "grad_year", "hometown", "passport_id")
_RETRIES = 6
_BACKOFF = 5.0  # seconds; wait doubles each attempt: 5, 10, 20, 40, 80


def _execute(query, retries: int = _RETRIES, backoff: float = _BACKOFF):
    """Call .execute() on a postgrest query builder, retrying on transient network errors."""
    import httpx
    for attempt in range(retries):
        try:
            return query.execute()
        except (httpx.RemoteProtocolError, httpx.ConnectError,
                httpx.NetworkError, httpx.TimeoutException) as exc:
            if attempt == retries - 1:
                raise
            wait = backoff * (2 ** attempt)
            logger.warning("Supabase request failed (%s), retry %d/%d in %.0fs",
                           exc, attempt + 1, retries - 1, wait)
            time.sleep(wait)


def upsert_rows(client: Client, table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
    if not rows:
        return
    result = _execute(client.table(table).upsert(rows, on_conflict=on_conflict))
    logger.info("Upserted %d rows into %s", len(rows), table)
    return result


def get_circuit_id(client: Client, circuit_name: str) -> str:
    result = _execute(client.table("circuits").select("id").eq("name", circuit_name).single())
    if not result.data:
        raise ValueError(f"Circuit '{circuit_name}' not found in DB. Run 002_seed_circuits.sql first.")
    return result.data["id"]


def _data(result) -> dict | None:
    """Safely extract .data from a supabase result that may be None."""
    return result.data if result is not None else None


def get_or_create_team(client: Client, team_data: dict[str, Any]) -> str:
    """Return existing team id or insert and return new id."""
    result = _execute(
        client.table("teams")
        .select("id")
        .eq("circuit_id", team_data["circuit_id"])
        .eq("name", team_data["name"])
        .eq("season", team_data["season"])
        .maybe_single()
    )
    data = _data(result)
    if data:
        return data["id"]
    insert = _execute(client.table("teams").insert(team_data))
    return insert.data[0]["id"]


def _player_compatible(row: dict, player_data: dict) -> bool:
    """True if an existing DB row is compatible with incoming player data (null fields match anything)."""
    for key in ("high_school", "grad_year"):
        incoming = player_data.get(key)
        existing = row.get(key)
        if incoming and existing and incoming != existing:
            return False
    return True


def get_or_create_player(client: Client, player_data: dict[str, Any]) -> str:
    """
    Look up player by passport_id (if present) or by (first_name, last_name).
    Passport_id lookup runs first — it's a stable unique key that survives name corrections.
    On match, patches any null bio fields and corrects the stored name if it changed.
    Null name/bio fields on either side are treated as wildcards (no false duplicates).
    """
    # 1. Passport-id lookup — avoids INSERT collisions when a name was previously stored wrong
    if player_data.get("passport_id"):
        result = _execute(
            client.table("players")
            .select("id, first_name, last_name, " + ", ".join(_BIO_FIELDS))
            .eq("passport_id", player_data["passport_id"])
            .maybe_single()
        )
        existing = _data(result)
        if existing:
            pid = existing["id"]
            patch: dict[str, Any] = {}
            # Correct stale name (e.g. from a previously broken parser)
            if player_data.get("first_name") and existing.get("first_name") != player_data["first_name"]:
                patch["first_name"] = player_data["first_name"]
            if player_data.get("last_name") and existing.get("last_name") != player_data["last_name"]:
                patch["last_name"] = player_data["last_name"]
            patch.update({
                k: player_data[k]
                for k in _BIO_FIELDS
                if player_data.get(k) is not None and existing.get(k) is None
            })
            if patch:
                _execute(client.table("players").update(patch).eq("id", pid))
            return pid

    # 2. Name-based lookup with bio compatibility check
    result = _execute(
        client.table("players")
        .select("id, " + ", ".join(_BIO_FIELDS))
        .eq("first_name", player_data["first_name"])
        .eq("last_name", player_data["last_name"])
        .limit(10)
    )
    rows = result.data or []
    matches = [r for r in rows if _player_compatible(r, player_data)]
    if len(matches) > 1:
        logger.warning(
            "Multiple player rows matched (%s %s) — using first. Check for duplicates.",
            player_data["first_name"], player_data["last_name"],
        )
    data = matches[0] if matches else None
    if data:
        pid = data["id"]
        patch = {
            k: player_data[k]
            for k in _BIO_FIELDS
            if player_data.get(k) is not None and data.get(k) is None
        }
        if patch:
            _execute(client.table("players").update(patch).eq("id", pid))
        return pid
    insert = _execute(client.table("players").insert(player_data))
    return insert.data[0]["id"]


def dedup_adidas_cross_circuit(client: Client, season: int) -> None:
    """
    Remove Gold-circuit stats rows for players who already have identical stats
    under 3SSB for the same season. Adidas shows cumulative season totals in
    every tier a player competed in, so a player who played Platinum events also
    appears in the Gold table with the exact same numbers.
    """
    # Collect Gold team_ids and 3SSB team_ids for this season
    gold_teams = _execute(
        client.table("teams").select("id")
        .eq("season", season)
        .in_("circuit_id",
             [r["id"] for r in (_execute(
                 client.table("circuits").select("id").eq("name", "Gold")
             ).data or [])])
    ).data or []
    ssb_teams = _execute(
        client.table("teams").select("id")
        .eq("season", season)
        .in_("circuit_id",
             [r["id"] for r in (_execute(
                 client.table("circuits").select("id").eq("name", "3SSB")
             ).data or [])])
    ).data or []

    if not gold_teams or not ssb_teams:
        return

    gold_team_ids = {r["id"] for r in gold_teams}
    ssb_team_ids  = {r["id"] for r in ssb_teams}

    # Find players who have stats in both circuits this season
    gold_stats = _execute(
        client.table("player_season_stats").select("id,player_id,team_id")
        .eq("season", season)
        .in_("team_id", list(gold_team_ids))
    ).data or []
    ssb_player_ids = {
        r["player_id"] for r in (_execute(
            client.table("player_season_stats").select("player_id")
            .eq("season", season)
            .in_("team_id", list(ssb_team_ids))
        ).data or [])
    }

    to_delete = [r["id"] for r in gold_stats if r["player_id"] in ssb_player_ids]
    if to_delete:
        _execute(client.table("player_season_stats").delete().in_("id", to_delete))
        logger.info(
            "Removed %d Gold stats rows that duplicated 3SSB entries (season %d)",
            len(to_delete), season,
        )
    else:
        logger.info("No cross-circuit Adidas duplicates found for season %d", season)


def patch_player_bio_nulls(client: Client, player_id: str, bio: dict[str, Any]) -> None:
    """Patch bio fields for a player by DB UUID, only filling columns that are currently null."""
    if not bio:
        return
    keys = ", ".join(k for k in _BIO_FIELDS if k in bio)
    if not keys:
        return
    current = _execute(client.table("players").select(keys).eq("id", player_id).single())
    if not current.data:
        return
    null_patch = {k: v for k, v in bio.items() if current.data.get(k) is None}
    if null_patch:
        _execute(client.table("players").update(null_patch).eq("id", player_id))
