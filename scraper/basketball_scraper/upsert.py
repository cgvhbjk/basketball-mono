"""
Supabase upsert helpers.
Uses the service-role key — bypasses RLS for write access.
"""
from __future__ import annotations
import logging
from typing import Any
from supabase import Client

logger = logging.getLogger(__name__)

_BIO_FIELDS = ("height_inches", "position", "high_school", "grad_year", "hometown", "passport_id")


def upsert_rows(client: Client, table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
    if not rows:
        return
    result = client.table(table).upsert(rows, on_conflict=on_conflict).execute()
    logger.info("Upserted %d rows into %s", len(rows), table)
    return result


def get_circuit_id(client: Client, circuit_name: str) -> str:
    result = client.table("circuits").select("id").eq("name", circuit_name).single().execute()
    if not result.data:
        raise ValueError(f"Circuit '{circuit_name}' not found in DB. Run 002_seed_circuits.sql first.")
    return result.data["id"]


def _data(result) -> dict | None:
    """Safely extract .data from a supabase result that may be None."""
    return result.data if result is not None else None


def get_or_create_team(client: Client, team_data: dict[str, Any]) -> str:
    """Return existing team id or insert and return new id."""
    result = (
        client.table("teams")
        .select("id")
        .eq("circuit_id", team_data["circuit_id"])
        .eq("name", team_data["name"])
        .eq("season", team_data["season"])
        .maybe_single()
        .execute()
    )
    data = _data(result)
    if data:
        return data["id"]
    insert = client.table("teams").insert(team_data).execute()
    return insert.data[0]["id"]


def get_or_create_player(client: Client, player_data: dict[str, Any]) -> str:
    """
    Match on (first_name, last_name, high_school, grad_year).
    Returns existing id or inserts a new player.
    On match, only patches bio fields that are currently null in the DB
    so subsequent scraper runs never overwrite canonical values.
    """
    query = (
        client.table("players")
        .select("id, " + ", ".join(_BIO_FIELDS))
        .eq("first_name", player_data["first_name"])
        .eq("last_name", player_data["last_name"])
    )
    if player_data.get("high_school"):
        query = query.eq("high_school", player_data["high_school"])
    if player_data.get("grad_year"):
        query = query.eq("grad_year", player_data["grad_year"])

    result = query.maybe_single().execute()
    data = _data(result)
    if data:
        pid = data["id"]
        patch = {
            k: player_data[k]
            for k in _BIO_FIELDS
            if player_data.get(k) is not None and data.get(k) is None
        }
        if patch:
            client.table("players").update(patch).eq("id", pid).execute()
        return pid
    insert = client.table("players").insert(player_data).execute()
    return insert.data[0]["id"]


def patch_player_bio_nulls(client: Client, player_id: str, bio: dict[str, Any]) -> None:
    """Patch bio fields for a player by DB UUID, only filling columns that are currently null."""
    if not bio:
        return
    keys = ", ".join(k for k in _BIO_FIELDS if k in bio)
    if not keys:
        return
    current = client.table("players").select(keys).eq("id", player_id).single().execute()
    if not current.data:
        return
    null_patch = {k: v for k, v in bio.items() if current.data.get(k) is None}
    if null_patch:
        client.table("players").update(null_patch).eq("id", player_id).execute()
