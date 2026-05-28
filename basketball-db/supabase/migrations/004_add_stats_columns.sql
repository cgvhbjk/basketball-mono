-- ============================================================
-- 004_add_stats_columns.sql
-- Add extended per-game stat columns to player_season_stats.
-- All nullable — circuits that don't expose these will leave them NULL.
-- ============================================================

ALTER TABLE player_season_stats
  ADD COLUMN IF NOT EXISTS fga  NUMERIC(5, 1),
  ADD COLUMN IF NOT EXISTS oreb NUMERIC(5, 1),
  ADD COLUMN IF NOT EXISTS tpg  NUMERIC(5, 1),
  ADD COLUMN IF NOT EXISTS fta  NUMERIC(5, 1),
  ADD COLUMN IF NOT EXISTS mpg  NUMERIC(5, 1);
