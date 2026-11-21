ALTER TABLE runs ADD COLUMN driver TEXT NOT NULL DEFAULT 'cli' CHECK (driver IN ('engine', 'ai-tool', 'cli'));
ALTER TABLE runs ADD COLUMN paused INTEGER NOT NULL DEFAULT 0;
UPDATE runs SET driver = 'ai-tool' WHERE origin = 'dashboard';
CREATE TABLE run_notes (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES runs(id),
  text TEXT NOT NULL,
  author TEXT,
  channel TEXT,
  created_at TEXT NOT NULL,
  consumed_at TEXT,
  consumed_by TEXT
);
CREATE INDEX idx_run_notes_run ON run_notes(run_id, consumed_at);
