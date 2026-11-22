-- Sentinel 2.1: a task that hit a provider usage limit goes back to QUEUED and waits until retry_at.
-- Additive only. Rollback: restore the registry from a backup taken before the upgrade (older versions ignore these columns).
ALTER TABLE tasks ADD COLUMN retry_at TEXT;
ALTER TABLE tasks ADD COLUMN limit_reason TEXT;
ALTER TABLE tasks ADD COLUMN limit_hits INTEGER NOT NULL DEFAULT 0;
