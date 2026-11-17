// View models of the screens. The answers of the real server are typed in wire.ts (recorded from the
// Phase F and G server by tests/test_dashboard_fixtures.py); adapt.ts converts them to these types.

export interface ErrorEnvelope {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

export interface Page<T> {
  items: T[];
  next: string | null;
}

export interface SessionAnswer {
  csrf: string;
}

export interface Installation {
  version: string;
  path: string;
  python: string;
  method: string;
}

export interface Runtime {
  pid: number;
  port: number;
  started_at: string;
  projects: string[];
}

export type CheckStatus = 'passed' | 'failed' | 'warning' | 'not_configured';

export interface HealthCheck {
  id: string;
  label: string;
  required: boolean;
  status: CheckStatus;
  message: string;
  fix: string | null;
}

export interface Health {
  ready: boolean;
  checks: HealthCheck[];
  checked_at: string;
}

export interface Project {
  id: string;
  name: string;
  path: string;
  status: 'available' | 'unavailable';
  reason?: string | null;
  active_runs: number;
}

export type ReadinessState = 'ready' | 'ready_with_warnings' | 'needs_configuration' | 'invalid_configuration' | 'connection_unavailable';
export type ItemStatus = 'passed' | 'failed' | 'warning' | 'not_configured' | 'not_checked' | 'unknown' | 'unreachable';

export interface ReadinessItem {
  id: string;
  status: ItemStatus;
  repo?: string;
  path?: string;
  message?: string;
  fix?: string | null;
}

export interface Readiness {
  state: ReadinessState;
  workflow: string | null;
  checked_at: string;
  items: ReadinessItem[];
}

export interface RepoValidation {
  item: string;
  status: ItemStatus;
  fix?: string | null;
}

export interface Repository {
  id: string;
  path: string;
  remote: string | null;
  default_branch: string | null;
  branch: string | null;
  role: string;
  profile: string;
  commands: Record<string, string | null>;
  guidelines: string | null;
  validation: RepoValidation[];
}

export interface ConfigValue {
  path: string;
  value: unknown;
  category: string;
  source: 'default' | 'global' | 'project' | 'repo';
  repo?: string;
  overrides?: { source: 'default' | 'global' | 'project' | 'repo'; value: unknown };
}

export interface Configuration {
  sha256: string;
  values: ConfigValue[];
}

export interface ConfigVersion {
  version: number;
  sha256: string;
  author: string;
  channel: string;
  at: string;
  comment: string | null;
}

export interface ConfigDiff {
  a: string;
  b: string;
  diff: string;
}

export interface AuditRow {
  id: number;
  actor: string;
  channel: string;
  action: string;
  target: string;
  before_sha256: string | null;
  after_sha256: string | null;
  project?: string;
  reason: string | null;
  at: string;
}

export interface RunSummary {
  slug: string;
  type: string | null;
  tier: number | null;
  state: string;
  execution_status: string;
  acceptance_status: string;
  workflow_version: '2' | '0.1';
  updated_at: string;
  project?: string;
}

export interface ApprovalState {
  gate: 'specification' | 'gherkin';
  state: string;
  version: number | null;
  sha256: string | null;
  record?: DecisionRecord | null;
}

export interface DecisionRecord {
  decision: string;
  approver: string;
  channel: string;
  at: string;
  comment: string | null;
}

export interface NextStep {
  kind: 'orchestrator' | 'task' | 'human' | 'done' | 'wait';
  label: string;
  command?: string | null;
  gate?: 'specification' | 'gherkin';
  version?: number;
}

export interface Run {
  slug: string;
  project: string;
  type: string | null;
  tier: number | null;
  initial_tier: number | null;
  state: string;
  reason?: string | null;
  execution_status: string;
  acceptance_status: string;
  workflow_version: '2' | '0.1';
  request: string;
  priority: string | null;
  ticket: string | null;
  created_at: string;
  updated_at: string;
  repos: { id: string; baseline_sha: string; branch: string; final_sha: string | null }[];
  approvals: { specification: ApprovalState; gherkin: ApprovalState };
  task_counts: Record<string, number>;
  config_snapshot?: { version: number; sha256: string } | null;
  next?: NextStep;
}

export interface WorkflowNode {
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
  tokens?: number | null;
  cost?: number | null;
  label?: string | null;
  reasons?: Record<string, string>;
}

export interface Workflow {
  nodes: WorkflowNode[];
  edges: { from: string; to: string }[];
  gates: { gate: 'specification' | 'gherkin'; state: string; version: number | null }[];
}

export interface LogAnswer {
  lines: string[];
  next_offset: number;
  running: boolean;
}

export interface Finding {
  severity: string;
  message: string;
}

export interface VersionRow {
  version: number;
  sha256: string;
  decision: string | null;
  reviewer: string | null;
  channel: string | null;
  at: string | null;
  comment: string | null;
}

export interface SpecificationAnswer {
  version: number;
  sha256: string;
  state: string;
  text: string;
  validation: { ok: boolean; findings: Finding[] };
  previous_version: number | null;
  diff_to_previous: string | null;
  versions: VersionRow[];
  decision: DecisionRecord | null;
  requested_at: string | null;
}

export interface GherkinScenario {
  name: string;
  ac: string;
  type: string;
  priority: string;
  tags: string[];
  cov: string[];
}

export interface GherkinFeature {
  path: string;
  name: string;
  scenarios: GherkinScenario[];
}

export interface CoverageRow {
  category: string;
  status: 'covered' | 'not_applicable' | 'missing';
  scenarios: number;
  reason: string | null;
}

export interface GherkinAnswer {
  version: number;
  sha256: string;
  state: string;
  features: GherkinFeature[];
  coverage: CoverageRow[];
  validation: { ok: boolean; findings: Finding[] };
  versions: VersionRow[];
  decision: DecisionRecord | null;
  requested_at: string | null;
}

export interface ApprovalListItem {
  project: string;
  slug: string;
  gate: 'specification' | 'gherkin';
  version: number;
  sha256: string;
  requested_at: string;
}

export interface ApprovalDecisionAnswer {
  approval: DecisionRecord & { gate: string; state: string; version: number; sha256: string };
  run: Run;
}

export interface AcceptanceAnswer {
  run: Run;
}

export interface Evidence {
  id: string;
  kind: string;
  repo: string | null;
  status: string;
  command: string | null;
  exit_code: number | null;
  passed: number | null;
  failed: number | null;
  classification: string | null;
  started_at: string | null;
  finished_at: string | null;
  provider: string | null;
  model: string | null;
  files: { path: string; sha256: string }[];
  output_artifact: string | null;
}

export interface Cycle {
  id: string;
  behavior: string;
  repo: string;
  state: string;
  phases: { phase: 'red' | 'green' | 'refactor'; task_id: string | null; state: string; attempt: number; evidence_ids: string[] }[];
}

export interface TddAnswer {
  cycles: Cycle[];
  evidence: Evidence[];
}

export interface VerificationAnswer {
  round: { number: number; at: string } | null;
  rows: Evidence[];
  missing: { repo: string | null; kind: string; reason: string }[];
  acceptance: { computed: string; reasons: { text: string; view: 'tdd' | 'verification' | 'trace' | 'changes' }[] };
  /** the human's decision on the computed acceptance; null while pending */
  acceptance_record: DecisionRecord | null;
}

export interface ReportAnswer {
  sha256: string | null;
  report: Record<string, unknown>;
}

export interface ChangeFile {
  path: string;
  status: string;
  additions: number;
  deletions: number;
  cycles: string[];
  tasks: string[];
}

export interface ChangesAnswer {
  repos: { id: string; branch: string; base: string; head: string; files_count: number; additions: number; deletions: number; files: ChangeFile[] }[];
}

export interface DiffLine {
  type: 'add' | 'del' | 'ctx';
  old: number | null;
  new: number | null;
  text: string;
}

export interface DiffAnswer {
  repo: string;
  path: string;
  binary: boolean;
  truncated: boolean;
  /** inline mode fills lines; split mode (paired by the server) fills rows */
  hunks: { header: string; lines: DiffLine[]; rows?: { left: DiffLine | null; right: DiffLine | null }[] }[];
}

export interface TraceAnswer {
  requirements: {
    id: string;
    acs: {
      id: string;
      scenarios: {
        id: string;
        name: string;
        cycle: { id: string; files: { repo: string; path: string }[]; evidence: { id: string; kind: string; passed: boolean }[] } | null;
      }[];
    }[];
  }[];
  gaps: string[];
  failures: { text: string; evidence_id?: string }[];
  acceptance: { state: string } | null;
}

export interface StreamEnvelope {
  id: number;
  type: string;
  at: string;
  project: string;
  run: string | null;
  task: string | null;
  actor: { kind: string; name: string | null; channel: string };
  payload: Record<string, unknown>;
}
