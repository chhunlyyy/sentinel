-- One independent query per metric of the "analytics-small" registry fixture (all-time over version 2 runs).
-- tests/test_analytics.py compares each answer with the value of analytics.compute (AC-ANL-01b).
-- name: runs.total
SELECT COUNT(*) FROM runs WHERE workflow_version = '2';
-- name: runs.finished
SELECT COUNT(*) FROM runs WHERE workflow_version = '2' AND finished_at IS NOT NULL;
-- name: lead_time.median
SELECT AVG(secs) FROM (SELECT (julianday(finished_at) - julianday(created_at)) * 86400.0 AS secs FROM runs
  WHERE workflow_version = '2' AND finished_at IS NOT NULL ORDER BY secs
  LIMIT 2 - (SELECT COUNT(*) FROM runs WHERE workflow_version = '2' AND finished_at IS NOT NULL) % 2
  OFFSET (SELECT (COUNT(*) - 1) / 2 FROM runs WHERE workflow_version = '2' AND finished_at IS NOT NULL));
-- name: acceptance.accepted
SELECT COUNT(*) FROM runs WHERE workflow_version = '2' AND state = 'COMPLETED' AND acceptance_status = 'accepted';
-- name: acceptance.decided
SELECT COUNT(*) FROM runs WHERE workflow_version = '2' AND state = 'COMPLETED' AND acceptance_status IN ('accepted', 'rejected');
-- name: tasks.total
SELECT COUNT(*) FROM tasks WHERE run_id IN (SELECT id FROM runs WHERE workflow_version = '2');
-- name: retries.total
SELECT COUNT(*) FROM tasks WHERE retry_of IS NOT NULL AND run_id IN (SELECT id FROM runs WHERE workflow_version = '2');
-- name: provider.codex.failures
SELECT COUNT(*) FROM tasks WHERE provider = 'codex' AND state = 'FAILED' AND error_code = 'E_PROVIDER'
  AND run_id IN (SELECT id FROM runs WHERE workflow_version = '2');
-- name: provider.codex.finished
SELECT COUNT(*) FROM tasks WHERE provider = 'codex' AND state IN ('COMPLETED', 'FAILED')
  AND run_id IN (SELECT id FROM runs WHERE workflow_version = '2');
-- name: cost.total
SELECT SUM(cost) FROM tasks WHERE run_id IN (SELECT id FROM runs WHERE workflow_version = '2');
-- name: cost.reported
SELECT COUNT(cost) FROM tasks WHERE run_id IN (SELECT id FROM runs WHERE workflow_version = '2');
-- name: verification.lint.passed
SELECT COUNT(*) FROM evidence WHERE round IS NOT NULL AND kind = 'lint' AND verdict = 'pass';
-- name: verification.test.total
SELECT COUNT(*) FROM evidence WHERE round IS NOT NULL AND kind = 'test' AND verdict IN ('pass', 'fail');
-- name: rework.spec_revisions
SELECT COUNT(*) FROM (SELECT run_id FROM artifacts WHERE kind = 'spec' GROUP BY run_id HAVING COUNT(*) > 1);
-- name: rework.findings_routed
SELECT COUNT(*) FROM events WHERE type = 'finding.routed';
