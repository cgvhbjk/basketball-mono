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

_BIO_FIELDS = (
    "height_inches", "position", "high_school", "grad_year", "hometown",
    "passport_id", "date_of_birth", "nationality",
)
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

    # 2. Name-based lookup with bio compatibility check.
    # Sort by id so the "first match" picked below is deterministic across runs —
    # otherwise two homonym players (e.g. two "John Smith"s with null bios) could
    # have stats routed to either one depending on Supabase row order.
    result = _execute(
        client.table("players")
        .select("id, " + ", ".join(_BIO_FIELDS))
        .eq("first_name", player_data["first_name"])
        .eq("last_name", player_data["last_name"])
        .order("id")
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


def _paginate(make_query, page_size: int = 1000, order_col: str = "id") -> list[dict]:
    """Fetch all rows from a PostgREST query, paginating past the 1000-row default cap.

    PostgREST does not guarantee a stable row order without an ORDER BY, so without
    one the page boundaries can shift between requests (under concurrent writes)
    and silently miss or duplicate rows. We force `.order(order_col)` here so all
    callers get a stable scan; pass a different column if the table lacks `id`.
    """
    rows: list[dict] = []
    offset = 0
    while True:
        page = _execute(
            make_query().order(order_col).range(offset, offset + page_size - 1)
        ).data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


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

    gold_team_ids = list({r["id"] for r in gold_teams})
    ssb_team_ids  = list({r["id"] for r in ssb_teams})

    # Find players who have stats in both circuits this season.
    # Paginate — PostgREST caps each request at 1000 rows by default, and Adidas
    # circuits routinely yield tens of thousands of stats rows per season.
    # Pull the numeric stats too so we can verify Gold and 3SSB really do match
    # before deleting; if they ever diverge (e.g. one tier reports a subset),
    # silently deleting the Gold row would lose real data.
    _MATCH_FIELDS = ("games_played", "ppg", "rpg", "apg", "spg", "bpg", "fg_pct", "three_pt_pct")
    _select_cols = "id,player_id,team_id," + ",".join(_MATCH_FIELDS)
    gold_stats = _paginate(lambda: (
        client.table("player_season_stats").select(_select_cols)
        .eq("season", season)
        .in_("team_id", gold_team_ids)
    ))
    ssb_by_player: dict[str, dict] = {}
    for r in _paginate(lambda: (
        client.table("player_season_stats").select(_select_cols)
        .eq("season", season)
        .in_("team_id", ssb_team_ids)
    )):
        # If a player somehow has multiple 3SSB rows, keep the first — they
        # should already be deduped upstream by team/season.
        ssb_by_player.setdefault(r["player_id"], r)

    def _matches(gold: dict, ssb: dict) -> bool:
        for f in _MATCH_FIELDS:
            gv, sv = gold.get(f), ssb.get(f)
            if gv is None and sv is None:
                continue
            if gv is None or sv is None:
                return False
            # Tolerate tiny float drift from independent rounding
            if abs(float(gv) - float(sv)) > 0.05:
                return False
        return True

    to_delete: list[str] = []
    diverged = 0
    for g in gold_stats:
        ssb = ssb_by_player.get(g["player_id"])
        if ssb is None:
            continue
        if _matches(g, ssb):
            to_delete.append(g["id"])
        else:
            diverged += 1

    if diverged:
        logger.warning(
            "Skipped %d Gold rows that have a 3SSB row but with diverging stats (season %d) — "
            "left in place; inspect manually if this number is high",
            diverged, season,
        )

    if to_delete:
        # Delete in batches of 100 to keep the URL short for the .in_() filter
        for i in range(0, len(to_delete), 100):
            batch = to_delete[i:i + 100]
            _execute(client.table("player_season_stats").delete().in_("id", batch))
        logger.info(
            "Removed %d Gold stats rows that duplicated 3SSB entries (season %d)",
            len(to_delete), season,
        )
    else:
        logger.info("No cross-circuit Adidas duplicates found for season %d", season)


def get_or_create_event(client: Client, event_data: dict[str, Any]) -> str:
    """
    Resolve or insert an event row, keyed by (circuit_id, name, season).

    The unique constraint matches migration 005: UNIQUE (circuit_id, name, season).
    """
    result = _execute(
        client.table("events")
        .select("id")
        .eq("circuit_id", event_data["circuit_id"])
        .eq("name", event_data["name"])
        .eq("season", event_data["season"])
        .maybe_single()
    )
    data = _data(result)
    if data:
        return data["id"]
    insert = _execute(client.table("events").insert(event_data))
    return insert.data[0]["id"]


def upsert_games(client: Client, rows: list[dict[str, Any]]) -> dict[str, str]:
    """
    Upsert game rows and return a {source_id_marker: db_uuid} map.

    Because the `games` table has no native source-id column (rows are keyed
    by event/home/away/played_at) we do a select-then-insert per game and
    return the resulting UUID indexed by the caller-supplied "source_marker"
    key on each row. The marker key is popped before the insert.

    Each input dict must have:
      - source_marker (str)  — opaque identifier, returned in the map
      - event_id (UUID or None)
      - home_team_id (UUID or None)
      - away_team_id (UUID or None)
      - played_at, home_score, away_score, status (any/optional)
    """
    if not rows:
        return {}

    out: dict[str, str] = {}
    for row in rows:
        marker = row.pop("source_marker")
        # We treat (event_id, home_team_id, away_team_id, played_at) as the
        # de-facto natural key — re-running the scraper for the same source
        # row should reuse the same UUID rather than insert a duplicate.
        q = client.table("games").select("id")
        for col in ("event_id", "home_team_id", "away_team_id", "played_at"):
            v = row.get(col)
            if v is None:
                q = q.is_(col, "null")
            else:
                q = q.eq(col, v)
        result = _execute(q.maybe_single())
        data = _data(result)
        if data:
            game_id = data["id"]
            # Patch score/status if they were unknown when the row was first
            # inserted (forfeit/postponed/etc. resolves over time).
            patch = {k: row[k] for k in ("home_score", "away_score", "status") if row.get(k) is not None}
            if patch:
                _execute(client.table("games").update(patch).eq("id", game_id))
        else:
            insert = _execute(client.table("games").insert(row))
            game_id = insert.data[0]["id"]
        out[marker] = game_id
    logger.info("Upserted %d games", len(out))
    return out


def upsert_box_scores(client: Client, rows: list[dict[str, Any]]) -> None:
    """
    Upsert box-score rows. Each row must already have resolved DB UUIDs in
    game_id / player_id / team_id; the unique constraint is (game_id, player_id).
    """
    if not rows:
        return
    # Chunk to keep request bodies reasonable; 4k rows in one upsert is too big.
    BATCH = 500
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        _execute(client.table("box_scores").upsert(chunk, on_conflict="game_id,player_id"))
    logger.info("Upserted %d box score rows", len(rows))


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
