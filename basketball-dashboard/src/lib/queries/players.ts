import { createClient } from "@/lib/supabase/server";
import type { PlayerStatsRow } from "@/types/database";

export interface PlayersFilter {
  season?: number;
  ageDivision?: string;
  circuitName?: string;
}

const PLAYER_STATS_SELECT = `
  *,
  players (
    first_name,
    last_name,
    height_inches,
    weight_lbs,
    grad_year,
    hometown,
    high_school,
    position,
    star_rating,
    national_rank,
    state_rank
  ),
  teams (
    name,
    city,
    state,
    circuits (
      name,
      org
    )
  )
`;

// PostgREST caps any single response at the project's `db.max_rows` (1000 by
// default), so a one-shot `.limit(10000)` is silently truncated and the table
// loses every row past the cap. Page through the full set instead, ordered by
// a stable unique key (`id`) so pages can't overlap or gap. The client re-sorts
// for display, so server-side order only needs to be deterministic — and using
// `id` also sidesteps the old `ppg DESC` ordering, which put NULL-ppg roster
// rows first (Postgres orders DESC NULLS FIRST) and let them eat the budget.
const PAGE_SIZE = 1000;

export async function getPlayersWithStats(filter: PlayersFilter = {}): Promise<PlayerStatsRow[]> {
  const supabase = await createClient();

  const rows: PlayerStatsRow[] = [];
  for (let from = 0; ; from += PAGE_SIZE) {
    let query = supabase
      .from("player_season_stats")
      .select(PLAYER_STATS_SELECT)
      .order("id", { ascending: true })
      .range(from, from + PAGE_SIZE - 1);

    if (filter.season) {
      query = query.eq("season", filter.season);
    }
    if (filter.ageDivision) {
      query = query.eq("age_division", filter.ageDivision);
    }

    const { data, error } = await query;
    if (error) {
      throw new Error(`Failed to fetch player stats: ${error.message}`);
    }

    const batch = (data ?? []) as unknown as PlayerStatsRow[];
    rows.push(...batch);
    if (batch.length < PAGE_SIZE) break;
  }

  // Filter by circuit name in-memory (nested FK filter not supported in Supabase JS client)
  if (filter.circuitName) {
    return rows.filter((r) => r.teams?.circuits?.name === filter.circuitName);
  }

  return rows;
}

export async function getAvailableSeasons(): Promise<number[]> {
  const supabase = await createClient();
  // Page through season values: a single unbounded select is capped at
  // `db.max_rows`, and ordered season-desc that cap can be filled entirely by
  // the newest season — silently dropping older seasons from the dropdown.
  const seasons = new Set<number>();
  for (let from = 0; ; from += PAGE_SIZE) {
    const { data, error } = await supabase
      .from("player_season_stats")
      .select("season")
      .order("season", { ascending: false })
      .range(from, from + PAGE_SIZE - 1);
    if (error) break;
    const batch = (data ?? []) as { season: number }[];
    for (const r of batch) seasons.add(r.season);
    if (batch.length < PAGE_SIZE) break;
  }
  return [...seasons].sort((a, b) => b - a);
}

export async function getAvailableCircuits(): Promise<string[]> {
  const supabase = await createClient();
  const { data } = await supabase
    .from("circuits")
    .select("name")
    .order("name");

  return ((data ?? []) as { name: string }[]).map((r) => r.name);
}
