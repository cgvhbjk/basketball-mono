"""
Supabase upsert helpers.
Uses the service-role key — bypasses RLS for write access.
"""
import logging
from typing import Any
from supabase import Client

logger = logging.getLogger(__name__)


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
    """
    query = (
        client.table("players")
        .select("id")
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
        return data["id"]
    insert = client.table("players").insert(player_data).execute()
    return insert.data[0]["id"]
