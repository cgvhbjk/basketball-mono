export type Json = string | number | boolean | null | { [key: string]: Json } | Json[]

export interface Database {
  public: {
    Tables: {
      circuits: {
        Row: Circuit
        Insert: CircuitInsert
        Update: CircuitUpdate
      }
      teams: {
        Row: Team
        Insert: TeamInsert
        Update: TeamUpdate
      }
      players: {
        Row: Player
        Insert: PlayerInsert
        Update: PlayerUpdate
      }
      team_rosters: {
        Row: TeamRoster
        Insert: TeamRosterInsert
        Update: TeamRosterUpdate
      }
      player_season_stats: {
        Row: PlayerSeasonStats
        Insert: PlayerSeasonStatsInsert
        Update: PlayerSeasonStatsUpdate
      }
    }
  }
}

export interface GlobalWatchlistRow {
  id: string
  player_id: string
  scout_name: string
  notes: string
  status: string | null
  starred_at: string
  updated_at: string
}

export type GlobalWatchlistInsert = Omit<GlobalWatchlistRow, 'id' | 'starred_at' | 'updated_at'> & {
  id?: string
  starred_at?: string
  updated_at?: string
}

export type GlobalWatchlistUpdate = Partial<GlobalWatchlistInsert>

// ----------------------------------------------------------------
// circuits
// ----------------------------------------------------------------
export interface Circuit {
  id: string
  name: string
  org: string
  updated_at: string
}

export type CircuitInsert = Omit<Circuit, 'id' | 'updated_at'> & {
  id?: string
  updated_at?: string
}

export type CircuitUpdate = Partial<CircuitInsert>

// ----------------------------------------------------------------
// teams
// ----------------------------------------------------------------
export type AgeDivision = '15U' | '16U' | '17U'

export interface Team {
  id: string
  circuit_id: string
  name: string
  city: string | null
  state: string | null
  age_division: AgeDivision
  season: number
  updated_at: string
}

export type TeamInsert = Omit<Team, 'id' | 'updated_at'> & {
  id?: string
  updated_at?: string
}

export type TeamUpdate = Partial<TeamInsert>

// ----------------------------------------------------------------
// players
// ----------------------------------------------------------------
export interface Player {
  id: string
  first_name: string
  last_name: string
  height_inches: number | null
  weight_lbs: number | null
  grad_year: number | null
  hometown: string | null
  high_school: string | null
  canonical_id: string | null
  position: string | null
  passport_id: string | null
  star_rating: number | null
  national_rank: number | null
  state_rank: number | null
  updated_at: string
}

export type PlayerInsert = Omit<Player, 'id' | 'updated_at'> & {
  id?: string
  updated_at?: string
}

export type PlayerUpdate = Partial<PlayerInsert>

// ----------------------------------------------------------------
// team_rosters
// ----------------------------------------------------------------
export interface TeamRoster {
  team_id: string
  player_id: string
  season: number
  jersey_number: string | null
  position: string | null
}

export type TeamRosterInsert = TeamRoster
export type TeamRosterUpdate = Partial<TeamRoster>

// ----------------------------------------------------------------
// player_season_stats
// ----------------------------------------------------------------
export interface PlayerSeasonStats {
  id: string
  player_id: string
  team_id: string
  season: number
  age_division: AgeDivision | null
  games_played: number | null
  ppg: number | null
  rpg: number | null
  apg: number | null
  spg: number | null
  bpg: number | null
  fg_pct: number | null
  three_pt_pct: number | null
  fga: number | null
  oreb: number | null
  tpg: number | null
  fta: number | null
  mpg: number | null
  updated_at: string
}

export type PlayerSeasonStatsInsert = Omit<PlayerSeasonStats, 'id' | 'updated_at'> & {
  id?: string
  updated_at?: string
}

export type PlayerSeasonStatsUpdate = Partial<PlayerSeasonStatsInsert>

// ----------------------------------------------------------------
// Joined view type used by the dashboard query
// ----------------------------------------------------------------
export interface PlayerStatsRow extends PlayerSeasonStats {
  players: Pick<Player, 'first_name' | 'last_name' | 'height_inches' | 'weight_lbs' | 'grad_year' | 'hometown' | 'high_school' | 'position' | 'star_rating' | 'national_rank' | 'state_rank'>
  teams: Pick<Team, 'name' | 'city' | 'state'> & {
    circuits: Pick<Circuit, 'name' | 'org'>
  }
}
