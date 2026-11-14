CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE runs (
  id TEXT PRIMARY KEY, slug TEXT UNIQUE, request TEXT, type TEXT,
  tier INTEGER, initial_tier INTEGER, state TEXT,
  execution_status TEXT, acceptance_status TEXT,
  workflow_version TEXT, config_snapshot_id INTEGER,
  created_at TEXT, updated_at TEXT, finished_at TEXT, adhoc INTEGER,
  previous_state TEXT
);

CREATE TABLE run_repos (
  run_id TEXT, repo_id TEXT, baseline_sha TEXT, final_sha TEXT, branch TEXT,
  PRIMARY KEY (run_id, repo_id)
);

CREATE TABLE artifacts (
  id TEXT PRIMARY KEY, run_id TEXT, kind TEXT,
  version INTEGER, path TEXT, sha256 TEXT, created_at TEXT
);

CREATE TABLE approvals (
  id TEXT PRIMARY KEY, run_id TEXT, gate TEXT,
  artifact_id TEXT, version INTEGER, sha256 TEXT, state TEXT,
  decision TEXT, approver TEXT, channel TEXT, comment TEXT,
  decided_at TEXT, invalidated_at TEXT, invalidated_reason TEXT
);

CREATE TABLE tasks (
  id TEXT PRIMARY KEY, run_id TEXT, role TEXT, repo_id TEXT, cycle_id TEXT,
  state TEXT, provider TEXT, model TEXT, adapter TEXT, retry_of TEXT,
  task_path TEXT, result_artifact_id TEXT, error_code TEXT,
  created_at TEXT, started_at TEXT, finished_at TEXT,
  tokens INTEGER, cost REAL, seconds REAL
);

CREATE TABLE task_deps (
  task_id TEXT, depends_on TEXT, PRIMARY KEY (task_id, depends_on)
);

CREATE TABLE cycles (
  id TEXT PRIMARY KEY, run_id TEXT, behavior TEXT, state TEXT,
  red_task TEXT, green_task TEXT, refactor_task TEXT, accepted_at TEXT
);

CREATE TABLE evidence (
  id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, cycle_id TEXT,
  kind TEXT,
  command TEXT, cwd TEXT, exit_code INTEGER, classification TEXT,
  passed INTEGER, failed INTEGER, skipped INTEGER,
  output_artifact_id TEXT, started_at TEXT, finished_at TEXT, env TEXT
);

CREATE TABLE findings (
  id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, source TEXT,
  severity TEXT, location TEXT, text TEXT, state TEXT, routed_to TEXT
);

CREATE TABLE trace_links (
  run_id TEXT, from_kind TEXT, from_id TEXT, to_kind TEXT, to_id TEXT
);

CREATE TABLE config_versions (
  id INTEGER PRIMARY KEY, scope TEXT, content TEXT, sha256 TEXT,
  author TEXT, channel TEXT, created_at TEXT, comment TEXT
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, task_id TEXT,
  type TEXT, actor TEXT, payload TEXT, at TEXT
);

CREATE TABLE audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, channel TEXT, action TEXT,
  target TEXT, before_sha TEXT, after_sha TEXT, at TEXT
);

CREATE INDEX idx_events_run ON events(run_id);
CREATE INDEX idx_tasks_run ON tasks(run_id);

CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER events_no_replace BEFORE INSERT ON events
WHEN EXISTS (SELECT 1 FROM events WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'events is append-only'); END;
CREATE TRIGGER audit_no_replace BEFORE INSERT ON audit
WHEN EXISTS (SELECT 1 FROM audit WHERE id = NEW.id)
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
