CREATE TABLE kb_jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  run_slug TEXT,
  state TEXT NOT NULL CHECK (state IN ('queued','running','done','failed')),
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_kb_jobs_state ON kb_jobs(state);
