CREATE TABLE changed_files (
  id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, cycle_id TEXT, repo_id TEXT, path TEXT,
  before_sha256 TEXT, after_sha256 TEXT, phase TEXT
);
CREATE INDEX idx_changed_files_task ON changed_files(task_id);
ALTER TABLE evidence ADD COLUMN output_sha256 TEXT;
ALTER TABLE evidence ADD COLUMN repo_sha TEXT;
ALTER TABLE evidence ADD COLUMN provider TEXT;
ALTER TABLE evidence ADD COLUMN model TEXT;
ALTER TABLE evidence ADD COLUMN failing TEXT;
ALTER TABLE evidence ADD COLUMN verdict TEXT;
ALTER TABLE evidence ADD COLUMN reason TEXT;
ALTER TABLE cycles ADD COLUMN repo_id TEXT;
ALTER TABLE cycles ADD COLUMN retry_of TEXT;
ALTER TABLE cycles ADD COLUMN reason TEXT;
CREATE INDEX idx_changed_files_cycle ON changed_files(cycle_id);
