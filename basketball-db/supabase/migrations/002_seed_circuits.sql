-- ============================================================
-- 002_seed_circuits.sql
-- Seed the boys grassroots circuits the pipeline ingests.
-- EYCL is the boys Nike Elite Youth Champions League (NOT the girls one).
-- The `gender` column was dropped in 005; older snapshots of this file
-- inserted it explicitly.
-- ============================================================

INSERT INTO circuits (id, name, gender, org) VALUES
  (gen_random_uuid(), 'EYBL',     'boys',  'Nike'),
  (gen_random_uuid(), 'EYCL',     'boys',  'Nike'),
  (gen_random_uuid(), '3SSB',     'boys',  'Adidas'),
  (gen_random_uuid(), 'Gold',     'boys',  'Adidas'),
  (gen_random_uuid(), 'UAA',      'boys',  'Under Armour'),
  (gen_random_uuid(), 'UAA Rise', 'boys',  'Under Armour'),
  (gen_random_uuid(), 'PUMA',     'boys',  'PUMA')
ON CONFLICT DO NOTHING;
