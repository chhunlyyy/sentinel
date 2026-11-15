// Shapes of the answers of the real Phase F and Phase G server, as recorded by tests/test_dashboard_fixtures.py
// (dashboard/fixtures/recorded/*.json). types.ts holds the view models the screens use; adapt.ts converts.

export interface WInstallation {
  version: string;
  install_path: string;
  python: string;
  method: string;
}

export interface WRuntime {
  pid: number;
  port: number;
  started_at: string;
  version: string;
  user: { name: string; role: string };
  projects: { id: string; name: string }[];
}

export interface WHealthItem {
  name: string;
  required: boolean;
  status: string;
  message: string;
  fix: string;
}

export interface WHealth {
  items: WHealthItem[];
  ready: boolean;
  checked_at: string;
}

export interface WReadinessItem {
  name: string;
  repo: string | null;
  required: boolean;
  status: string;
  message: string;
  fix: string;
  checked_at: string;
}

export interface WReadiness {
  project: string;
  workflow: string | null;
  state: string;
  items: WReadinessItem[];
  errors: { path: string; message: string }[];
}

export interface WRepository {
  id: string;
  path: string;
  remote: string | null;
  default_branch: string | null;
  current_branch: string | null;
  role: string;
  profile: string;
  commands: Record<string, string>;
  guidelines: string | null;
  validation: { name: string; status: string; message: string; fix: string }[];
}

export interface WConfigItem {
  key: string;
  value: unknown;
  source: string;
  overridden: { source: string; value: unknown }[];
}

export interface WConfiguration {
  project: string;
  sha256: string;
  items: WConfigItem[];
  global_file: string | null;
}

export interface WConfigVersion {
  id: number;
  scope: string;
  sha256: string;
  author: string | null;
  channel: string | null;
  created_at: string;
  comment: string | null;
}

export interface WApproval {
  state: string;
  version: number;
  sha256: string;
  decision: string | null;
  approver: string | null;
  channel: string | null;
  comment: string | null;
  decided_at: string | null;
}

export interface WNext {
  kind: string;
  run?: string;
  state?: string;
  label?: string;
  reason?: string;
  command?: string;
  commands?: string[];
  resume_command?: string;
  task?: string;
  role?: string;
  adapter?: string;
  provider?: string;
}

export interface WRun {
  slug: string;
  project: string;
  request: string | null;
  type: string | null;
  tier: number | null;
  initial_tier: number | null;
  state: string;
  reason: string | null;
  execution_status: string;
  acceptance_status: string;
  workflow_version: string;
  priority: string | null;
  requested_tier: number | null;
  origin: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  repos: { repo_id: string; baseline_sha: string | null; branch: string | null; final_sha: string | null }[];
  approvals: { specification?: WApproval; gherkin?: WApproval };
  config_snapshot: { id: number; scope: string; sha256: string; created_at: string } | null;
  task_counts: Record<string, number>;
  next: WNext | null;
}

export interface WDecision {
  decision: string;
  approver: string | null;
  channel: string | null;
  comment: string | null;
  decided_at: string | null;
}

export interface WVersion {
  version: number;
  sha256: string;
  created_at: string;
  decision: string | null;
  approver: string | null;
  channel: string | null;
  decided_at: string | null;
  comment: string | null;
}

interface WReview {
  version: number;
  sha256: string;
  approval_state: string | null;
  run_state: string;
  validation: { errors: string[]; warnings: string[] };
  diff: string | null;
  previous_version: number | null;
  versions: WVersion[];
  decision: WDecision | null;
  requested_at: string | null;
}

export interface WSpecification extends WReview {
  text: string;
}

export interface WSpecVersion {
  version: number;
  sha256: string;
  text: string;
}

export interface WGherkin extends WReview {
  files: { path: string; text: string }[];
  scenarios: { line: number; name: string; path: string; tags: string[] }[];
  coverage: { rows: { category: string; reason: string; scenarios: number; state: string; status: string }[]; summary: string; warnings: string[] };
}

export interface WNode {
  id: string;
  role: string;
  repo: string | null;
  state: string;
  adapter: string;
  provider: string | null;
  model: string | null;
  attempt: number;
  retry_of: string | null;
  error_code: string | null;
  started_at: string | null;
  finished_at: string | null;
  seconds: number | null;
  label: string | null;
}

export interface WWorkflow {
  nodes: WNode[];
  edges: { from: string; to: string }[];
  gates: { gate: string; state: string; version: number; sha256: string }[];
}

export interface WCycle {
  id: string;
  repo: string | null;
  behavior: string;
  state: string;
  phase_tasks: { red: string | null; green: string | null; refactor: string | null };
  evidence_ids: string[];
}

export interface WTdd {
  cycles: WCycle[];
}

export interface WEvidence {
  id: string;
  task_id: string | null;
  cycle_id: string | null;
  kind: string;
  command: string | null;
  exit_code: number | null;
  classification: string | null;
  passed: number | null;
  failed: number | null;
  skipped: number | null;
  output_artifact_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  repo_id: string | null;
  provider: string | null;
  model: string | null;
  name: string | null;
  round: number | null;
  verdict: string | null;
}

export interface WVerification {
  /** the latest finished verification round, null before one finished */
  round: number | null;
  /** checks the round planned but left no row for, as "repo kind[ name]" */
  missing: string[];
  evidence: WEvidence[];
  acceptance_record: { decision: string; approver: string; channel: string; at: string; comment: string | null } | null;
  acceptance: { execution_status: string; acceptance_status: string; reasons: unknown[] };
}

export interface WTrace {
  links: { from_kind: string; from_id: string; to_kind: string; to_id: string }[];
  gaps: { kind: string; id: string }[];
}

export interface WChanges {
  slug: string;
  repos: {
    repo: string;
    base_sha: string | null;
    branch: string | null;
    head_sha: string | null;
    files: { path: string; status: string; additions: number; deletions: number; binary: boolean; tasks: string[]; cycles: string[] }[];
  }[];
}

export interface WDiff {
  repo: string;
  path: string;
  mode: string;
  status: string;
  additions: number;
  deletions: number;
  binary: boolean;
  truncated: boolean;
  hunks: {
    header: string;
    old_start: number;
    new_start: number;
    /** mode inline */
    lines?: { type: string; old: number | null; new: number | null; text: string }[];
    /** mode split: paired old and new lines */
    rows?: { old: { n: number | null; text: string } | null; new: { n: number | null; text: string } | null }[];
  }[];
}

export interface WLog {
  task_id: string;
  lines: string[];
  next_offset: number;
  running: boolean;
}

export interface WApprovalItem {
  artifact_id: string;
  gate: string;
  project: string;
  requested_at: string;
  sha256: string;
  slug: string;
  state: string;
  version: number;
}

export interface WAudit {
  id: number;
  project: string;
  actor: string;
  channel: string | null;
  action: string;
  target: string;
  before_sha: string | null;
  after_sha: string | null;
  reason: string | null;
  at: string;
  row_sha: string | null;
  chain_sha: string | null;
}

export interface WConfigDiff {
  a: string;
  b: string;
  identical: boolean;
  diff: string;
}

/** GET /report: the report document with the sha256 a human types the first 8 characters of to accept the run. */
export type WReport = { sha256: string; report: Record<string, unknown> };
