import { createClient } from "@/lib/supabase/server";
import type { PlayerStatsRow } from "@/types/database";

export interface PlayersFilter {
  season?: number;
  ageDivision?: string;
  circuitName?: string;
}

export async function getPlayersWithStats(filter: PlayersFilter = {}): Promise<PlayerStatsRow[]> {
  const supabase = createClient();

  let query = supabase
    .from("player_season_stats")
    .select(`
      *,
      players (
        first_name,
        last_name,
        height_inches,
        grad_year,
        hometown,
        high_school
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
    `)
    .order("ppg", { ascending: false });

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

  let rows = (data ?? []) as unknown as PlayerStatsRow[];

  // Filter by circuit name in-memory (nested FK filter not supported in Supabase JS client)
  if (filter.circuitName) {
    rows = rows.filter((r) => r.teams?.circuits?.name === filter.circuitName);
  }

  return rows;
}

export async function getAvailableSeasons(): Promise<number[]> {
  const supabase = createClient();
  const { data } = await supabase
    .from("player_season_stats")
    .select("season")
    .order("season", { ascending: false });

  return [...new Set((data ?? []).map((r) => r.season))];
}

export async function getAvailableCircuits(): Promise<string[]> {
  const supabase = createClient();
  const { data } = await supabase
    .from("circuits")
    .select("name")
    .order("name");

  return (data ?? []).map((r) => r.name);
}
