-- Sentinel 2.1: record input and output tokens per agent task.
-- Additive only. Rollback: restore the registry from a backup taken before the upgrade (older versions ignore these columns).
ALTER TABLE tasks ADD COLUMN input_tokens INTEGER;
ALTER TABLE tasks ADD COLUMN output_tokens INTEGER;
