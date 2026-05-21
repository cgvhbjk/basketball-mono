-- ============================================================
-- 001_initial_schema.sql
-- Unified Amateur Basketball Database — Phase 1
-- ============================================================

-- Shared trigger function: keeps updated_at current on every UPDATE
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------
-- circuits
-- One row per shoe-circuit (EYBL, UAA, 3SSB, etc.)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS circuits (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name       TEXT NOT NULL,
  gender     TEXT NOT NULL CHECK (gender IN ('boys', 'girls')),
  org        TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_circuits_updated_at
  BEFORE UPDATE ON circuits
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE circuits ENABLE ROW LEVEL SECURITY;
CREATE POLICY circuits_public_read ON circuits FOR SELECT USING (true);

-- ----------------------------------------------------------------
-- teams
-- One row per team per circuit per season
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teams (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  circuit_id   UUID NOT NULL REFERENCES circuits (id),
  name         TEXT NOT NULL,
  city         TEXT,
  state        TEXT,
  age_division TEXT NOT NULL CHECK (age_division IN ('15U', '16U', '17U')),
  season       INT  NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_teams_circuit ON teams (circuit_id);
CREATE INDEX idx_teams_season  ON teams (season);

CREATE TRIGGER trg_teams_updated_at
  BEFORE UPDATE ON teams
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
CREATE POLICY teams_public_read ON teams FOR SELECT USING (true);

-- ----------------------------------------------------------------
-- players
-- Canonical player records (circuit-agnostic)
-- canonical_id: self-reference for future identity resolution
--   across circuits — leave NULL on first ingest
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS players (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  first_name   TEXT NOT NULL,
  last_name    TEXT NOT NULL,
  height_inches INT,
  weight_lbs   INT,
  grad_year    INT  CHECK (grad_year BETWEEN 2024 AND 2032),
  hometown     TEXT,
  high_school  TEXT,
  canonical_id UUID REFERENCES players (id),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_players_grad_year ON players (grad_year);

CREATE TRIGGER trg_players_updated_at
  BEFORE UPDATE ON players
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE players ENABLE ROW LEVEL SECURITY;
CREATE POLICY players_public_read ON players FOR SELECT USING (true);

-- ----------------------------------------------------------------
-- team_rosters
-- Junction: player <-> team per season
-- Composite PK includes season so a player can appear on
-- different teams across years without conflict
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_rosters (
  team_id       UUID NOT NULL REFERENCES teams   (id),
  player_id     UUID NOT NULL REFERENCES players (id),
  season        INT  NOT NULL,
  jersey_number TEXT,
  position      TEXT,
  PRIMARY KEY (team_id, player_id, season)
);

ALTER TABLE team_rosters ENABLE ROW LEVEL SECURITY;
CREATE POLICY team_rosters_public_read ON team_rosters FOR SELECT USING (true);

-- ----------------------------------------------------------------
-- player_season_stats
-- Aggregated season stats per player per team per season
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS player_season_stats (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  player_id     UUID NOT NULL REFERENCES players (id),
  team_id       UUID NOT NULL REFERENCES teams   (id),
  season        INT  NOT NULL,
  age_division  TEXT CHECK (age_division IN ('15U', '16U', '17U')),
  games_played  INT,
  ppg           NUMERIC(5, 1),
  rpg           NUMERIC(5, 1),
  apg           NUMERIC(5, 1),
  spg           NUMERIC(5, 1),
  bpg           NUMERIC(5, 1),
  fg_pct        NUMERIC(5, 3),
  three_pt_pct  NUMERIC(5, 3),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (player_id, team_id, season)
);

CREATE INDEX idx_stats_player ON player_season_stats (player_id);
CREATE INDEX idx_stats_team   ON player_season_stats (team_id);
CREATE INDEX idx_stats_season ON player_season_stats (season);

CREATE TRIGGER trg_stats_updated_at
  BEFORE UPDATE ON player_season_stats
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE player_season_stats ENABLE ROW LEVEL SECURITY;
CREATE POLICY stats_public_read ON player_season_stats FOR SELECT USING (true);
