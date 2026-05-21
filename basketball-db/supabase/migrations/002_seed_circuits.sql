-- ============================================================
-- 002_seed_circuits.sql
-- Seed all 7 target circuits — Phase 2 scrapers can start
-- inserting teams immediately without any schema changes.
-- ============================================================

INSERT INTO circuits (id, name, gender, org) VALUES
  (gen_random_uuid(), 'EYBL',     'boys',  'Nike'),
  (gen_random_uuid(), 'EYCL',     'girls', 'Nike'),
  (gen_random_uuid(), '3SSB',     'boys',  'Adidas'),
  (gen_random_uuid(), 'Gold',     'boys',  'Adidas'),
  (gen_random_uuid(), 'UAA',      'boys',  'Under Armour'),
  (gen_random_uuid(), 'UAA Rise', 'boys',  'Under Armour'),
  (gen_random_uuid(), 'PUMA',     'boys',  'PUMA')
ON CONFLICT DO NOTHING;
