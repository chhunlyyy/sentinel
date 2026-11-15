ALTER TABLE evidence ADD COLUMN round INTEGER;
ALTER TABLE evidence ADD COLUMN name TEXT;
ALTER TABLE evidence ADD COLUMN detail TEXT;
CREATE TABLE verification_rounds (
  id TEXT PRIMARY KEY, run_id TEXT, round INTEGER, started_at TEXT, finished_at TEXT,
  interrupted INTEGER NOT NULL DEFAULT 0, passed INTEGER, summary TEXT, owner_pid INTEGER, owner_started_at TEXT,
  UNIQUE (run_id, round)
);
CREATE INDEX idx_vrounds_run ON verification_rounds(run_id);
ALTER TABLE run_repos ADD COLUMN baseline_dirty TEXT;
ALTER TABLE runs ADD COLUMN watched_baseline TEXT;
ALTER TABLE findings ADD COLUMN category TEXT;
ALTER TABLE findings ADD COLUMN cycle_id TEXT;
ALTER TABLE findings ADD COLUMN decided_by TEXT;
ALTER TABLE findings ADD COLUMN comment TEXT;
ALTER TABLE artifacts ADD COLUMN scrubbed INTEGER;
ALTER TABLE artifacts ADD COLUMN original_sha256 TEXT;
