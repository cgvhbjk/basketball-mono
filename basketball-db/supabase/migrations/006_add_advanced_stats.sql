-- ================================================================
-- 006 — Capture every stat field exposed by the upstream sources
-- ================================================================
-- Adds columns surfaced in the May 2026 audit of Cerebro / Adidas /
-- UAA APIs. Every column is nullable so adapters that don't have a
-- given field simply leave it null.
--
-- Source-by-source mapping (see docs/sources.md):
--   Cerebro PlayersList     → ft_pct, date_of_birth, nationality
--   Cerebro PlayerXGamesList→ defensive_rebounds (per-game in box_scores)
--   Adidas 3SSB API         → ft_pct, dreb, fpg, three_pm_pg, plus_minus, events_played
--   Adidas team summary     → wins, losses
--   UAA HTML tables         → ft_pct, fgm, fga, three_pm/pa, ftm, fta, dreb, tov, pf, mpg
-- ----------------------------------------------------------------

-- ---- player_season_stats: per-game volume + efficiency ----
ALTER TABLE player_season_stats
  ADD COLUMN IF NOT EXISTS ft_pct          NUMERIC(5, 4),
  ADD COLUMN IF NOT EXISTS dreb            NUMERIC(5, 2),    -- defensive rebounds per game
  ADD COLUMN IF NOT EXISTS fpg             NUMERIC(5, 2),    -- personal fouls per game
  ADD COLUMN IF NOT EXISTS three_pm_pg     NUMERIC(5, 2),    -- 3PT made per game
  ADD COLUMN IF NOT EXISTS three_pa_pg     NUMERIC(5, 2),    -- 3PT attempts per game
  ADD COLUMN IF NOT EXISTS fgm_pg          NUMERIC(5, 2),    -- field goals made per game
  ADD COLUMN IF NOT EXISTS ftm_pg          NUMERIC(5, 2),    -- free throws made per game
  ADD COLUMN IF NOT EXISTS plus_minus      NUMERIC(6, 2),    -- season net +/-
  ADD COLUMN IF NOT EXISTS events_played   INT;              -- number of tournaments / sessions

-- ---- players: biographical fields exposed by some sources ----
ALTER TABLE players
  ADD COLUMN IF NOT EXISTS date_of_birth   DATE,
  ADD COLUMN IF NOT EXISTS nationality     TEXT;

-- ---- teams: record exposed by Adidas summary ----
ALTER TABLE teams
  ADD COLUMN IF NOT EXISTS wins            INT,
  ADD COLUMN IF NOT EXISTS losses          INT;

-- ---- box_scores: split rebounds into offensive + defensive ----
-- We already store `offensive_rebounds`; add `defensive_rebounds` so the
-- two split cleanly. `rebounds` (total) stays as-is.
ALTER TABLE box_scores
  ADD COLUMN IF NOT EXISTS defensive_rebounds INT;
