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
  driver: string;
  paused: boolean;
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
  /** TDD-09: "test_file", or "qa_scenario" when QA scenarios replaced the test file */
  red_method: string;
  exception: { rule: string; replaced: string; by: string; repo: string } | null;
  phase_tasks: { red: string | null; green: string | null; refactor: string | null };
  evidence_ids: string[];
}

export interface WVerificationCycle {
  id: string;
  repo: string | null;
  behavior: string;
  state: string;
  red_method: string;
  exception: { rule: string; replaced: string; by: string; repo: string } | null;
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
  cycles: WVerificationCycle[];
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

/** GET /notifications: computed from the events table, newest first. `unread` counts every project, not only this page. */
export interface WNotification {
  id: string;
  project: string;
  run: string;
  level: string;
  text: string;
  link: string;
  at: string;
  read_at: string | null;
}

export interface WNotifications {
  items: WNotification[];
  next: string | null;
  unread: number;
  unavailable: { project: string; reason: string }[];
}

/** A metric that cannot be computed: never a zero. */
export interface WNullMetric {
  value: null;
  reason: string;
}

export interface WSpread {
  count: number;
  median: number;
  p90: number;
}

export interface WCostTotal {
  value: number;
  partial: boolean;
  reported_tasks: number;
  unreported_tasks: number;
}

/** GET /reports/analytics. Each metric is its value, or a WNullMetric with the reason. */
export interface WAnalytics {
  range: { from: string | null; to: string | null };
  runs: { total: number; by_state: Record<string, number>; by_type: Record<string, number> };
  lead_time_seconds: WSpread | WNullMetric;
  acceptance_rate: { value: number; accepted: number; decided: number } | WNullMetric;
  approval_wait_seconds: Record<string, WSpread | WNullMetric> | WNullMetric;
  tasks: { by_role: Record<string, { count: number; median_seconds: number | null }> } | WNullMetric;
  retries: { total: number } | WNullMetric;
  provider_failure_rate: Record<string, { value: number; failures: number; tasks: number } | WNullMetric>;
  cost: { total: WCostTotal | WNullMetric; partial: boolean; by_task: Record<string, number>; by_role: Record<string, number>; by_provider: Record<string, number> };
  tdd: { cycles: { total: number; accepted: number; rejected: Record<string, number> } } | WNullMetric;
  verification: {
    pass_rate: Record<string, { value: number; passed: number; total: number }> | WNullMetric;
    first_attempt_pass_rate: { value: number; passed_first: number; verified: number } | WNullMetric;
  };
  rework: { spec_revisions: number; gherkin_revisions: number; changes_requested: number; findings_routed: number } | WNullMetric;
}

// ---- Factory (W4) ----

/** Station states returned per run in GET /api/v1/projects/{pid}/factory */
export type WStationState = 'done' | 'working' | 'waiting' | 'paused' | 'limit' | 'queued' | 'next' | 'todo';

export interface WFactoryAgent {
  task: string;
  role: string;
  runner: string;
  model: string | null;
  adapter: string;
  started_at: string;
}

export interface WFactoryLane {
  cycle: string;
  name: string;
  repo: string;
  state: string;
  red: WStationState;
  green: WStationState;
  refactor: WStationState;
}

export interface WFactoryRun {
  slug: string;
  title: string;
  type: string;
  driver: string;
  paused: boolean;
  state: string;
  tier: number | null;
  station: string;
  stations: Record<string, WStationState>;
  next_station: string | null;
  agents: Record<string, WFactoryAgent[]>;
  lanes: WFactoryLane[];
  attention: { kind: 'needs_human' | 'blocked'; reason: string } | null;
  /** set while the current station waits for a provider usage limit to end (station state `limit`) */
  limit?: WFactoryLimitWait | null;
  pending_notes: number;
  created_at: string;
  updated_at: string;
}

export interface WFactoryLimitWait {
  station: string;
  task: string;
  role: string;
  runner: string;
  /** ISO time the task starts again */
  retry_at: string;
  reason: string | null;
}

export interface WFactoryQueueItem {
  slug: string;
  title: string;
  position: number;
  reason: string;
}

export interface WFactoryLimits {
  driver: string;
  max_tasks_per_project: number;
  max_agents: number;
  running_in_project: number;
  running_total: number;
}

export interface WFactoryWho {
  role: string;
  runner: string;
  model: string | null;
}

export interface WFactoryActivity {
  at: string;
  run: string;
  station: string;
  text: string;
}

export interface WFactoryStatus {
  paused: boolean;
  paused_at: string | null;
  running_total: number;
  max_agents: number;
}

export interface WFactory {
  project: string;
  factory_paused: boolean;
  /** agent stations (triage, spec, gherkin, build, knowledge) from the routing config; a station without a route is absent */
  who: Record<string, WFactoryWho>;
  /** newest first, at most 20 */
  activity: WFactoryActivity[];
  generated_at: string;
  stations: string[];
  limits: WFactoryLimits;
  runs: WFactoryRun[];
  queue: WFactoryQueueItem[];
  /** roles that block engine-driven runs (empty when routing is fine or the driver is not `engine`) */
  routing?: { problems: string[] };
}

export interface WRoutingFixRow {
  role: string;
  text: string;
  current: { runner: string | null; model: string | null };
  suggested: { runner: string; model: string | null };
}

export interface WRoutingFix {
  project: string;
  applies: boolean;
  problems: WRoutingFixRow[];
  changes: { path: string; value: unknown }[];
}

export interface WDetectItem {
  path: string;
  is_git: boolean;
  current_branch: string | null;
  default_branch: string | null;
  local_branches: string[];
  profile: string;
  commands: Record<string, string>;
  tracked_branches: string[];
}

export interface WDetect {
  items: WDetectItem[];
}

export interface WSharedTest {
  ok: boolean;
  read: boolean;
  write: boolean | 'unknown';
  refs: number;
  error?: string;
}

export interface WRoutingSuggest {
  roles: Record<string, { runner: string; model: string | null }>;
  items: { role: string; runner: string; model: string | null }[];
}

export interface WConfigFormField {
  path: string;
  type: string;
  enum?: string[] | null;
  default?: unknown;
  value?: unknown;
  help?: string;
  editable?: boolean;
}

export interface WConfigFormSection {
  id: string;
  title: string;
  fields: WConfigFormField[];
}

export interface WConfigForm {
  project: string;
  sha256: string;
  sections: WConfigFormSection[];
  fields: WConfigFormField[];
}

export interface WConfigPreview {
  project: string;
  valid: boolean;
  diff: string;
  changes: { path: string; value: unknown }[];
}

export interface WConfigSave {
  ok: boolean;
  project: string;
  sha256: string;
  diff: string;
}

export interface WKnowledgeStatus {
  enabled: boolean;
  records: { total: number; active: number; dropped: number };
  cursors: Record<string, string>;
  by_repo: Record<string, number>;
  jobs?: { running: number; queued: number; failed: number; last_job?: string } | null;
  module_summaries?: { total?: number; stale?: number } | number;
  tracked_branches?: number | string[];
}

export interface WKnowledgeRecord {
  key: string;
  repo?: string;
  provenance?: string;
  path?: string;
  title?: string;
  summary?: string;
  reached?: string;
  files?: string[];
  date?: string;
  meta?: Record<string, unknown>;
  body?: string;
}

export interface WKnowledgeRecords {
  items: WKnowledgeRecord[];
  next: string | null;
  total: number;
}

export interface WKnowledgeCiTemplate {
  repo: string;
  profile: string;
  branches: string[];
  template: string;
  filename: string;
}

export interface WKnowledgeJob {
  ok: boolean;
  job: string;
  state: string;
}

export interface WKnowledgeBackfillEstimate {
  token: string;
  estimate: Record<string, Record<string, number>>;
  total: number;
  since?: string;
  repo?: string;
}

export interface WKnowledgeBackfill {
  ok: boolean;
  job: string;
  state: 'queued';
  estimated: number | null;
}

