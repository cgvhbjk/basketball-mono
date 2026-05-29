-- ============================================================
-- 005_boys_only_and_unified_schema.sql
--
-- 1) The pipeline is now boys-only. Drop the `gender` column from `circuits`
--    and fix the EYCL row so it represents the boys Nike EYCL circuit.
--
-- 2) Add unified schema tables for events, games, box scores, and raw source
--    snapshots so adapters can ingest schedule + box-score data without each
--    circuit reinventing its own storage layout.
--
-- All tables have RLS enabled with a public read policy, matching the
-- conventions in 001_initial_schema.sql.
-- ============================================================

-- ----------------------------------------------------------------
-- 1) Boys-only
-- ----------------------------------------------------------------

-- Repoint EYCL to the boys circuit BEFORE dropping the column so anyone
-- inspecting the DB at this exact migration boundary sees the corrected value.
UPDATE circuits SET gender = 'boys' WHERE name = 'EYCL';

ALTER TABLE circuits DROP COLUMN IF EXISTS gender;

-- ----------------------------------------------------------------
-- 2) Events
-- One row per circuit event (tournament / session)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  circuit_id   UUID NOT NULL REFERENCES circuits (id),
  name         TEXT NOT NULL,
  location     TEXT,
  start_date   DATE,
  end_date     DATE,
  season       INT  NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (circuit_id, name, season)
);

CREATE INDEX IF NOT EXISTS idx_events_circuit ON events (circuit_id);
CREATE INDEX IF NOT EXISTS idx_events_season  ON events (season);

CREATE TRIGGER trg_events_updated_at
  BEFORE UPDATE ON events
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE events ENABLE ROW LEVEL SECURITY;
CREATE POLICY events_public_read ON events FOR SELECT USING (true);

-- ----------------------------------------------------------------
-- 3) Games
-- One row per game; either team may be null when only one side has been
-- scraped or when the game is a placeholder for a future matchup.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS games (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id      UUID REFERENCES events (id),
  home_team_id  UUID REFERENCES teams (id),
  away_team_id  UUID REFERENCES teams (id),
  played_at     TIMESTAMPTZ,
  home_score    INT,
  away_score    INT,
  status        TEXT,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_games_event     ON games (event_id);
CREATE INDEX IF NOT EXISTS idx_games_home_team ON games (home_team_id);
CREATE INDEX IF NOT EXISTS idx_games_away_team ON games (away_team_id);

CREATE TRIGGER trg_games_updated_at
  BEFORE UPDATE ON games
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE games ENABLE ROW LEVEL SECURITY;
CREATE POLICY games_public_read ON games FOR SELECT USING (true);

-- ----------------------------------------------------------------
-- 4) Box scores
-- One row per (player, game). Stored as game totals (not per-game averages).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS box_scores (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id             UUID NOT NULL REFERENCES games (id),
  player_id           UUID NOT NULL REFERENCES players (id),
  team_id             UUID NOT NULL REFERENCES teams (id),
  minutes             NUMERIC(5, 1),
  points              INT,
  rebounds            INT,
  offensive_rebounds  INT,
  assists             INT,
  steals              INT,
  blocks              INT,
  turnovers           INT,
  fouls               INT,
  fgm                 INT,
  fga                 INT,
  three_pm            INT,
  three_pa            INT,
  ftm                 INT,
  fta                 INT,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (game_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_box_player ON box_scores (player_id);
CREATE INDEX IF NOT EXISTS idx_box_team   ON box_scores (team_id);

CREATE TRIGGER trg_box_scores_updated_at
  BEFORE UPDATE ON box_scores
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE box_scores ENABLE ROW LEVEL SECURITY;
CREATE POLICY box_scores_public_read ON box_scores FOR SELECT USING (true);

-- ----------------------------------------------------------------
-- 5) Source snapshots
-- Index of raw HTML/JSON payloads written to object storage. Lets us
-- re-parse historical data after a site changes layout, and lets us
-- diff snapshots to detect upstream schema drift.
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_snapshots (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  adapter_name  TEXT NOT NULL,
  source_url    TEXT NOT NULL,
  content_type  TEXT NOT NULL,
  checksum      TEXT NOT NULL,
  payload_path  TEXT NOT NULL,
  size_bytes    BIGINT,
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (adapter_name, source_url, checksum)
);

CREATE INDEX IF NOT EXISTS idx_snap_adapter ON source_snapshots (adapter_name);
CREATE INDEX IF NOT EXISTS idx_snap_url     ON source_snapshots (source_url);

ALTER TABLE source_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY source_snapshots_public_read ON source_snapshots FOR SELECT USING (true);

-- ----------------------------------------------------------------
-- 6) Source ID alias mapping
-- Lets us track multiple external IDs per canonical player/team
-- (e.g. ExposureEvents Id, Passport ID, Pointstreak ID for the same player).
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_aliases (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type   TEXT NOT NULL CHECK (entity_type IN ('player', 'team', 'event', 'game')),
  entity_id     UUID NOT NULL,
  source        TEXT NOT NULL,  -- adapter or platform name (eg. 'exposure_events', 'pointstreak', 'passport')
  source_id     TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (entity_type, source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_source_aliases_entity ON source_aliases (entity_type, entity_id);

ALTER TABLE source_aliases ENABLE ROW LEVEL SECURITY;
CREATE POLICY source_aliases_public_read ON source_aliases FOR SELECT USING (true);
