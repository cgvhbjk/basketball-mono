-- ================================================================
-- 007 — Global (shared) watchlist
-- ================================================================
-- The dashboard already has a per-device localStorage watchlist.
-- This adds a second, server-backed list scouts share. There's no
-- auth in the dashboard today, so entries are tagged with a free-text
-- `scout_name` (typed once and saved in localStorage on the client).
-- Read+write policies are public — the project is intentionally
-- single-team, all-trusted.
-- ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS global_watchlist (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  player_id   UUID NOT NULL REFERENCES players (id) ON DELETE CASCADE,
  scout_name  TEXT NOT NULL,
  notes       TEXT NOT NULL DEFAULT '',
  status      TEXT,
  starred_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (player_id, scout_name)
);

CREATE INDEX idx_global_watchlist_player ON global_watchlist (player_id);
CREATE INDEX idx_global_watchlist_scout  ON global_watchlist (scout_name);

CREATE TRIGGER trg_global_watchlist_updated_at
  BEFORE UPDATE ON global_watchlist
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE global_watchlist ENABLE ROW LEVEL SECURITY;
CREATE POLICY global_watchlist_public_read   ON global_watchlist FOR SELECT USING (true);
CREATE POLICY global_watchlist_public_insert ON global_watchlist FOR INSERT WITH CHECK (true);
CREATE POLICY global_watchlist_public_update ON global_watchlist FOR UPDATE USING (true) WITH CHECK (true);
CREATE POLICY global_watchlist_public_delete ON global_watchlist FOR DELETE USING (true);

-- Status label vocabulary, shared across scouts.
CREATE TABLE IF NOT EXISTS global_watchlist_status_options (
  label TEXT PRIMARY KEY
);

INSERT INTO global_watchlist_status_options (label) VALUES ('In Progress')
  ON CONFLICT (label) DO NOTHING;

ALTER TABLE global_watchlist_status_options ENABLE ROW LEVEL SECURITY;
CREATE POLICY gwso_public_read   ON global_watchlist_status_options FOR SELECT USING (true);
CREATE POLICY gwso_public_insert ON global_watchlist_status_options FOR INSERT WITH CHECK (true);
CREATE POLICY gwso_public_delete ON global_watchlist_status_options FOR DELETE USING (true);
