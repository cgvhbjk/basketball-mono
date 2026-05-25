-- Enrichment fields: player bio and recruiting data
ALTER TABLE players
  ADD COLUMN IF NOT EXISTS position TEXT,
  ADD COLUMN IF NOT EXISTS passport_id TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS star_rating SMALLINT CHECK (star_rating BETWEEN 1 AND 5),
  ADD COLUMN IF NOT EXISTS national_rank INT,
  ADD COLUMN IF NOT EXISTS state_rank INT;
