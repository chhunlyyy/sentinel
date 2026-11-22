-- Sentinel 2.1: record provenance for artifacts (e.g. "imported from a session")
-- Additive only. Rollback: restore the registry from a backup taken before the upgrade (older versions ignore this column).
ALTER TABLE artifacts ADD COLUMN provenance TEXT;
