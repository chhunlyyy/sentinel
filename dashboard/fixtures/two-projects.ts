import type * as T from '../src/api/types.ts';
import type * as W from '../src/api/wire.ts';
import { analyticsSmall } from './reports.ts';
import type { Db, ProjectData, RunData } from './db.ts';
import { G1, H1, H2, REPORT } from './constants.ts';

const sha = (prefix: string, fill: string) => prefix + fill.repeat((64 - prefix.length) / fill.length);

export const health = (): T.Health => ({
  ready: true,
  checked_at: '2026-11-14T09:00:00Z',
  checks: [
    { id: 'python', label: 'python', required: true, status: 'passed', message: 'python 3.12.3', fix: null },
    { id: 'git', label: 'git', required: true, status: 'passed', message: 'git 2.45', fix: null },
    { id: 'jsonschema', label: 'jsonschema', required: true, status: 'passed', message: 'jsonschema installed', fix: null },
    { id: 'provider', label: 'provider', required: false, status: 'passed', message: 'codex found', fix: null },
    { id: 'registry_writable', label: 'registry_writable', required: true, status: 'passed', message: '.sentinel/ is writable', fix: null },
  ],
});

const node = (id: string, role: string, state: string, extra: Partial<T.WorkflowNode> = {}): T.WorkflowNode => ({
  id, role, repo: 'backend', state, adapter: 'cli', provider: 'codex', model: 'gpt-5', attempt: 1, retry_of: null, error_code: null,
  started_at: '2026-11-14T09:01:10Z', finished_at: null, seconds: 42, tokens: 1200, cost: 0.12, label: null, reasons: {}, ...extra,
});

const repoCommit = (id: string) => ({ id, baseline_sha: 'abc1234', branch: `sentinel/leave-${id}`, final_sha: null });

const runDetail = (slug: string, project: string, over: Partial<T.Run> = {}): T.Run => ({
  slug, project, type: 'feature', tier: 3, initial_tier: 2, state: 'EXECUTING', reason: null, execution_status: 'running', acceptance_status: 'pending',
  workflow_version: '2', request: 'Show the remaining leave balance', priority: 'high', ticket: 'HR-7',
  created_at: '2026-11-14T08:10:00Z', updated_at: '2026-11-14T09:12:00Z',
  repos: [repoCommit('backend'), repoCommit('frontend')],
  approvals: {
    specification: { gate: 'specification', state: 'APPROVED', version: 2, sha256: H2 },
    gherkin: { gate: 'gherkin', state: 'APPROVED', version: 1, sha256: G1 },
  },
  task_counts: { COMPLETED: 2, RUNNING: 2 },
  ...over,
});

const SPEC_TEXT = `# Specification: Leave balance

## Requirements
REQ-LEAVE-01 The employee sees the remaining leave balance.
REQ-LEAVE-02 Carry-over days are added at year end.

## Acceptance criteria
AC-LEAVE-01a Opening the balance page shows the remaining days.
AC-LEAVE-02 Carry-over is capped at five days.
`;

const SPEC_DIFF = `--- version 1
+++ version 2
@@ requirements @@
 REQ-LEAVE-01 The employee sees the remaining leave balance.
-REQ-LEAVE-02 Carry-over is not handled.
+REQ-LEAVE-02 Carry-over days are added at year end.
`;

const specAnswer = (over: Partial<T.SpecificationAnswer> = {}): T.SpecificationAnswer => ({
  version: 2, sha256: H2, state: 'APPROVED', text: SPEC_TEXT,
  validation: { ok: true, findings: [{ severity: 'warning', message: 'AC-LEAVE-02 has no example' }] },
  previous_version: 1, diff_to_previous: SPEC_DIFF, versions: [], decision: null, requested_at: '2026-11-14T09:10:00Z', ...over,
});

const specVersions = (): T.VersionRow[] => [
  { version: 1, sha256: H1, decision: 'changes', reviewer: 'dev', channel: 'tty', at: '2026-11-14T08:30:00Z', comment: 'Add the carry-over rule' },
  { version: 2, sha256: H2, decision: null, reviewer: null, channel: null, at: null, comment: null },
];

const scenario = (ac: string, name: string, type: string, priority: string, cov: string[]): T.GherkinScenario => ({ name, ac, type, priority, tags: [`@${ac}`, `@${type}`, `@${priority}`], cov: cov.map((c) => `cov-${c}`) });

const CATEGORIES = ['happy-path', 'invalid-input', 'missing-fields', 'boundary', 'empty-null', 'authn', 'authz', 'data-integrity', 'duplicate', 'concurrency', 'errors', 'external-failure', 'db-failure', 'regression', 'perf-security'];

const gherkinAnswer = (): T.GherkinAnswer => ({
  version: 1, sha256: G1, state: 'APPROVED', requested_at: '2026-11-14T09:50:00Z', decision: null, versions: [],
  validation: { ok: true, findings: [] },
  features: [
    {
      path: 'leave_balance.feature', name: 'Leave balance',
      scenarios: [
        scenario('AC-LEAVE-01a', 'Show the remaining balance', 'e2e', 'P1', ['happy-path']),
        scenario('AC-LEAVE-01b', 'Balance of a new employee', 'unit', 'P2', ['happy-path', 'empty-null']),
        scenario('AC-LEAVE-01c', 'Unknown employee', 'integration', 'P2', ['invalid-input', 'missing-fields', 'authz']),
      ],
    },
    {
      path: 'leave_limits.feature', name: 'Leave limits',
      scenarios: [
        scenario('AC-LEAVE-02a', 'Carry-over cap', 'unit', 'P1', ['happy-path', 'boundary']),
        scenario('AC-LEAVE-02b', 'Two requests at once', 'integration', 'P2', ['duplicate', 'data-integrity', 'errors', 'external-failure', 'regression', 'perf-security', 'authn']),
      ],
    },
  ],
  coverage: CATEGORIES.map((category) => {
    if (category === 'concurrency') return { category, status: 'missing' as const, scenarios: 0, reason: null };
    if (category === 'db-failure') return { category, status: 'not_applicable' as const, scenarios: 0, reason: 'no database' };
    return { category, status: 'covered' as const, scenarios: category === 'happy-path' ? 3 : 1, reason: null };
  }),
});

const evidence = (id: string, over: Partial<T.Evidence> = {}): T.Evidence => ({
  id, kind: 'test', repo: 'backend', status: 'passed', command: './gradlew test', exit_code: 0, passed: 4, failed: 0, classification: 'expected_pass',
  started_at: '2026-11-14T09:06:00Z', finished_at: '2026-11-14T09:06:30Z', provider: 'codex', model: 'gpt-5',
  files: [{ path: 'src/main/Leave.java', sha256: sha('b2c3d4e5', 'ab') }], output_artifact: 'a-out1', ...over,
});

const phase = (phase: 'red' | 'green' | 'refactor', task: string, ev: string) => ({ phase, task_id: task, state: 'COMPLETED', attempt: 1, evidence_ids: [ev] });

const leaveBalance = (): RunData => ({
  detail: runDetail('leave-balance', 'digital-hr'),
  next: { kind: 'orchestrator', label: 'waiting for AI tool', command: '/sentinel resume leave-balance' },
  specification: { current: specAnswer(), versions: specVersions(), oldVersions: { '1': specAnswer({ version: 1, sha256: H1, state: 'CHANGES_REQUESTED', previous_version: null, diff_to_previous: null, text: '# Specification: Leave balance (draft)\nREQ-LEAVE-01 only.\n' }) } },
  gherkin: gherkinAnswer(),
  workflow: {
    nodes: [
      node('t-spec1', 'specifier', 'COMPLETED', { finished_at: '2026-11-14T09:02:00Z' }),
      node('t-red2', 'tdd_red', 'COMPLETED', { finished_at: '2026-11-14T09:04:00Z' }),
      node('t-green1', 'tdd_green', 'RUNNING'),
      node('t-doc1', 'doc', 'RUNNING'),
    ],
    edges: [{ from: 't-spec1', to: 't-red2' }, { from: 't-red2', to: 't-green1' }, { from: 't-spec1', to: 't-doc1' }],
    gates: [{ gate: 'specification', state: 'APPROVED', version: 2 }, { gate: 'gherkin', state: 'APPROVED', version: 1 }],
  },
  tdd: {
    cycles: [
      { id: 'remaining', behavior: 'Shows the remaining leave balance', repo: 'backend', state: 'CYCLE_ACCEPTED', phases: [phase('red', 't-rem-red', 'e-rem-red'), phase('green', 't-rem-green', 'e-rem-green'), phase('refactor', 't-rem-ref', 'e-rem-ref')] },
      { id: 'carry', behavior: 'Adds carry-over days', repo: 'backend', state: 'REJECTED', phases: [{ phase: 'red', task_id: 't-car-red', state: 'COMPLETED', attempt: 1, evidence_ids: ['e-car-red'] }, { phase: 'green', task_id: 't-car-green', state: 'FAILED', attempt: 3, evidence_ids: [] }, { phase: 'refactor', task_id: null, state: 'PENDING', attempt: 0, evidence_ids: [] }] },
      { id: 'accrual', behavior: 'Accrues leave monthly', repo: 'backend', state: 'GREEN_RUNNING', phases: [{ phase: 'red', task_id: 't-acc-red', state: 'COMPLETED', attempt: 1, evidence_ids: ['e-acc-red'] }, { phase: 'green', task_id: 't-acc-green', state: 'RUNNING', attempt: 1, evidence_ids: [] }, { phase: 'refactor', task_id: null, state: 'PENDING', attempt: 0, evidence_ids: [] }] },
    ],
    evidence: [
      evidence('e-rem-red', {
        status: 'failed', exit_code: 1, passed: 1, failed: 3, classification: 'expected_failure', started_at: '2026-11-14T09:05:00Z', finished_at: '2026-11-14T09:05:40Z',
        files: [{ path: 'src/test/LeaveTest.java', sha256: sha('a1b2c3d4', 'ef') }], output_artifact: 'a-out1',
      }),
      evidence('e-rem-green'), evidence('e-rem-ref'), evidence('e-car-red', { status: 'failed', exit_code: 1, passed: 0, failed: 2 }), evidence('e-acc-red', { status: 'failed', exit_code: 1, passed: 0, failed: 1 }),
    ],
  },
  verification: {
    round: { number: 2, at: '2026-11-14T09:20:00Z' },
    rows: [
      evidence('e-ver-test', { passed: 42, failed: 0, started_at: '2026-11-14T09:20:10Z', output_artifact: 'a-out2' }),
      evidence('e-ver-lint', { kind: 'lint', status: 'not_configured', command: null, exit_code: null, passed: null, failed: null, output_artifact: null, files: [], started_at: null, finished_at: null }),
      evidence('e-ver-build', { kind: 'build', status: 'disabled', command: null, exit_code: null, passed: null, failed: null, output_artifact: null, files: [], started_at: null, finished_at: null }),
    ],
    missing: [{ repo: 'frontend', kind: 'test', reason: 'no evidence row' }],
    acceptance: { computed: 'pending', reasons: [] },
    acceptance_record: null,
  },
  trace: {
    requirements: [
      {
        id: 'REQ-LEAVE-01',
        acs: [{ id: 'AC-LEAVE-01a', scenarios: [{ id: 's1', name: 'Show the remaining balance', cycle: { id: 'remaining', files: [{ repo: 'backend', path: 'src/main/Leave.java' }], evidence: [{ id: 'e-rem-red', kind: 'test', passed: false }, { id: 'e-rem-green', kind: 'test', passed: true }] } }] }],
      },
    ],
    gaps: [], failures: [], acceptance: { state: 'pending' },
  },
  changes: {
    repos: [{
      id: 'backend', branch: 'feature/leave', base: 'abc1234', head: 'def5678', files_count: 2, additions: 14, deletions: 3,
      files: [
        { path: 'src/main/Leave.java', status: 'modified', additions: 10, deletions: 3, cycles: ['remaining'], tasks: ['t-rem-green'] },
        { path: 'src/test/LeaveTest.java', status: 'added', additions: 4, deletions: 0, cycles: ['remaining'], tasks: ['t-rem-red'] },
      ],
    }],
  },
  diffs: {
    'backend:src/main/Leave.java': {
      binary: false, truncated: false,
      hunks: [{
        header: '@@ -10,4 +10,5 @@',
        lines: [
          { type: 'ctx', old: 10, new: 10, text: 'public class Leave {' },
          { type: 'del', old: 11, new: null, text: '    int days = 0;' },
          { type: 'add', old: null, new: 11, text: '    int remaining = 0;' },
          { type: 'add', old: null, new: 12, text: '    int carried = 0;' },
          { type: 'ctx', old: 12, new: 13, text: '}' },
        ],
      }],
    },
  },
  artifacts: {
    'a-out1': { content: 'FAILED LeaveTest.remaining\n1 passed, 3 failed\n', sha256: sha('11111111', 'aa') },
    'a-out2': { content: 'BUILD SUCCESSFUL\n42 tests passed\n', sha256: sha('22222222', 'bb') },
  },
  logs: { 't-green1': { lines: ['starting green phase', 'running tests', 'tests passed'], running: true }, 't-doc1': { lines: ['writing docs'], running: true } },
  report: null,
});

/** Every task named by a TDD phase is also a node of the workflow, as on the real server. */
function withPhaseNodes(data: RunData): RunData {
  const have = new Set(data.workflow.nodes.map((n) => n.id));
  for (const c of data.tdd.cycles) {
    for (const p of c.phases) {
      if (p.task_id && !have.has(p.task_id)) {
        have.add(p.task_id);
        data.workflow.nodes.push(node(p.task_id, `tdd_${p.phase}`, p.state, { attempt: p.attempt, repo: c.repo }));
      }
    }
  }
  return data;
}

const leaveForm = (): RunData => {
  const base = withPhaseNodes(leaveBalance());
  return {
    ...base,
    detail: runDetail('leave-form', 'digital-hr', { state: 'COMPLETED', execution_status: 'completed', acceptance_status: 'pending', tier: 2, request: 'Add the leave form', task_counts: { COMPLETED: 6 } }),
    next: { kind: 'human', label: 'Final acceptance is needed', command: null },
    workflow: { ...base.workflow, nodes: base.workflow.nodes.map((n) => ({ ...n, state: 'COMPLETED', finished_at: '2026-11-14T09:30:00Z' })) },
    verification: { ...base.verification, acceptance: { computed: 'accepted', reasons: [] }, missing: [] },
    report: { sha256: REPORT, report: { run: 'leave-form', result: 'COMPLETED', tests: { passed: 42, failed: 0 } } },
  };
};

const taxForm = (): RunData => {
  const base = withPhaseNodes(leaveBalance());
  return {
    ...base,
    detail: runDetail('tax-form', 'payroll', { state: 'COMPLETED', execution_status: 'completed', request: 'Add the tax form', repos: [repoCommit('payroll-api')], task_counts: { COMPLETED: 4 } }),
    next: { kind: 'done', label: 'Nothing to do', command: null },
  };
};

const oldFix = (): RunData => {
  const base = withPhaseNodes(leaveBalance());
  return {
    ...base,
    detail: runDetail('old-fix', 'digital-hr', { workflow_version: '0.1', state: 'EXECUTING', tier: null, initial_tier: null, request: 'Fix the old thing', task_counts: {} }),
    next: { kind: 'done', label: 'Legacy run', command: null },
  };
};

export const summary = (d: T.Run): T.RunSummary => ({
  slug: d.slug, type: d.type, tier: d.tier, state: d.state, execution_status: d.execution_status, acceptance_status: d.acceptance_status,
  workflow_version: d.workflow_version, updated_at: d.updated_at,
});

const repo = (id: string, over: Partial<T.Repository>): T.Repository => ({
  id, path: `/ws/digital-hr/${id}`, remote: null, default_branch: 'main', branch: 'main', role: id, profile: 'node',
  commands: { build: null, test: null, lint: null }, guidelines: null,
  validation: ['path', 'git', 'branch', 'profile'].map((item) => ({ item, status: 'passed' as const })), ...over,
});

const config = (): T.Configuration => ({
  sha256: sha('3c3c3c3c', 'dd'),
  values: [
    { path: 'project.name', value: 'digital-hr', category: 'Project', source: 'project' },
    { path: 'repos.backend.commands.test', value: './gradlew test', category: 'Repositories', source: 'repo', repo: 'backend' },
    { path: 'providers.default', value: 'codex', category: 'Providers', source: 'global' },
    { path: 'agents.specifier.model', value: 'gpt-5', category: 'Agents', source: 'default' },
    { path: 'workflow.default', value: 'feature', category: 'Workflow and policies', source: 'default' },
    { path: 'tdd.max_cycles', value: 5, category: 'TDD', source: 'default' },
    { path: 'verification.required', value: ['test'], category: 'Verification', source: 'project' },
    { path: 'limits.max_retries', value: 3, category: 'Limits', source: 'default' },
    { path: 'notifications.desktop', value: true, category: 'Other', source: 'default' },
    { path: 'limits.task_timeout', value: 1200, category: 'Limits', source: 'project', overrides: { source: 'global', value: 900 } },
  ],
});

const history = (): T.Page<T.ConfigVersion> => ({
  next: null,
  items: [
    { version: 3, sha256: sha('3c3c3c3c', 'dd'), author: 'dev', channel: 'dashboard', at: '2026-11-14T07:00:00Z', comment: 'raise timeout' },
    { version: 2, sha256: sha('2b2b2b2b', 'cc'), author: 'dev', channel: 'tty', at: '2026-11-12T08:00:00Z', comment: 'add frontend' },
    { version: 1, sha256: sha('1a2b3c4d', 'ee'), author: 'dev', channel: 'tty', at: '2026-11-10T08:00:00Z', comment: 'first snapshot' },
  ],
});

const readyReadiness = (): T.Readiness => ({
  state: 'ready', workflow: null, checked_at: '2026-11-14T09:00:00Z',
  items: [{ id: 'git', status: 'passed', message: 'git repositories found' }, { id: 'test_command', status: 'passed', repo: 'backend', message: 'executable found' }],
});

const digitalHrData = (runs: T.RunSummary[]): ProjectData => ({
  readiness: { default: readyReadiness() },
  repositories: {
    next: null,
    items: [
      repo('backend', { remote: 'git@example.com:hr/backend.git', branch: 'feature/leave', role: 'backend', profile: 'spring-gradle', commands: { build: './gradlew build', test: './gradlew test', lint: './gradlew check' }, guidelines: 'CLAUDE.md' }),
      repo('frontend', { remote: 'git@example.com:hr/frontend.git', role: 'frontend', profile: 'nextjs', commands: { build: 'npm run build', test: 'npm test', lint: 'npm run lint' }, guidelines: 'AGENTS.md' }),
    ],
  },
  configuration: config(),
  history: history(),
  diffs: {},
  audit: [
    { id: 3, actor: 'dev', channel: 'dashboard', action: 'cancel', target: 'leave-balance', before_sha256: sha('aaaaaaaa', '00'), after_sha256: sha('bbbbbbbb', '00'), reason: 'wrong ticket', at: '2026-11-14T09:40:00Z' },
    { id: 2, actor: 'dev', channel: 'tty', action: 'approve', target: 'leave-balance#specification', before_sha256: null, after_sha256: H2, reason: null, at: '2026-11-14T09:30:00Z' },
    { id: 1, actor: 'dev', channel: 'tty', action: 'run_created', target: 'leave-balance', before_sha256: null, after_sha256: null, reason: null, at: '2026-11-14T08:10:00Z' },
  ],
  runs,
});

export function digitalHrFactory(): W.WFactory {
  const lane = (cycle: string, name: string, state: string, red: W.WStationState, green: W.WStationState, refactor: W.WStationState): W.WFactoryLane => (
    { cycle, name, repo: 'backend', state, red, green, refactor }
  );
  return {
    project: 'digital-hr',
    factory_paused: false,
    who: {
      triage: { role: 'triage', runner: 'agy', model: 'gemini-3.8-flash' },
      spec: { role: 'specifier', runner: 'claude', model: 'sonnet-4.6' },
      gherkin: { role: 'gherkin', runner: 'agy', model: 'gemini-3.8-flash-high' },
      build: { role: 'coder', runner: 'claude', model: 'sonnet-4.6' },
      knowledge: { role: 'knowledge', runner: 'agy', model: 'gemini-3.8-flash' },
    },
    activity: [
      { at: '2026-11-21T10:45:14.000000Z', run: 'leave-balance', station: 'build', text: 'build \u00b7 green: engine checking write scope backend/src/main/**' },
      { at: '2026-11-21T10:44:58.000000Z', run: 'audit-log-filter', station: 'triage', text: 'read knowledge/repos/frontend/summary.md' },
      { at: '2026-11-21T10:44:55.000000Z', run: 'leave-balance', station: 'build', text: '1 failing -> 0 failing (./gradlew test)' },
      { at: '2026-11-21T10:44:31.000000Z', run: 'audit-log-filter', station: 'triage', text: 'started \u00b7 agy \u00b7 gemini-3.8-flash' },
      { at: '2026-11-21T10:41:07.000000Z', run: 'leave-balance', station: 'build', text: 'B1 Export as CSV: refactor done' },
      { at: '2026-11-21T10:24:52.000000Z', run: 'payroll-rounding', station: 'gate_spec', text: 'waiting for you \u00b7 sha256 4f1c09ab...' },
    ],
    generated_at: '2026-11-21T10:45:20.123456Z',
    stations: ['intake', 'triage', 'spec', 'gate_spec', 'gherkin', 'gate_gherkin', 'build', 'verify', 'report', 'gate_accept', 'knowledge'],
    limits: { driver: 'engine', max_tasks_per_project: 3, max_agents: 4, running_in_project: 2, running_total: 3 },
    budget: {
      reached: false,
      tokens_today: 0,
      cost_today: 0.0,
      tokens_per_day: null,
      usd_per_day: null,
      reason: null,
      resets_at: null,
    },
    runs: [
      {
        slug: 'leave-balance',
        title: 'Leave balance export',
        type: 'feature',
        driver: 'engine',
        paused: false,
        state: 'EXECUTING',
        tier: 3,
        station: 'build',
        stations: {
          intake: 'done', triage: 'done', spec: 'done', gate_spec: 'done',
          gherkin: 'done', gate_gherkin: 'done',
          build: 'working', verify: 'next', report: 'todo', gate_accept: 'todo', knowledge: 'todo',
        },
        next_station: 'verify',
        agents: {
          build: [{ task: 't-0123456789ab', role: 'tdd_green', runner: 'claude', model: 'sonnet-4.6', adapter: 'cli', started_at: '2026-11-21T10:41:40.000000Z' }],
        },
        lanes: [
          lane('c-0123456789aa', 'Export as CSV', 'DONE', 'done', 'done', 'done'),
          lane('c-0123456789ab', 'Filter by dept', 'GREEN_RUNNING', 'done', 'working', 'todo'),
          lane('c-0123456789ac', 'HR only', 'QUEUED', 'todo', 'todo', 'todo'),
        ],
        attention: null,
        limit: null,
        task_usage: {},
        pending_notes: 0,
        created_at: '2026-11-21T09:58:00.000000Z',
        updated_at: '2026-11-21T10:45:14.000000Z',
      },
      {
        slug: 'payroll-rounding',
        title: 'Fix payroll rounding',
        type: 'bugfix',
        driver: 'engine',
        paused: false,
        state: 'WAITING_FOR_SPEC_APPROVAL',
        tier: 2,
        station: 'gate_spec',
        stations: {
          intake: 'done', triage: 'done', spec: 'done', gate_spec: 'waiting',
          gherkin: 'next', gate_gherkin: 'todo',
          build: 'todo', verify: 'todo', report: 'todo', gate_accept: 'todo', knowledge: 'todo',
        },
        next_station: 'gherkin',
        agents: {},
        lanes: [],
        attention: null,
        limit: null,
        task_usage: {},
        pending_notes: 0,
        created_at: '2026-11-21T10:10:00.000000Z',
        updated_at: '2026-11-21T10:24:52.000000Z',
      },
      {
        slug: 'audit-log-filter',
        title: 'Audit log filter',
        type: 'feature',
        driver: 'engine',
        paused: false,
        state: 'TRIAGE',
        tier: null,
        station: 'triage',
        stations: {
          intake: 'done', triage: 'working', spec: 'next', gate_spec: 'todo',
          gherkin: 'todo', gate_gherkin: 'todo',
          build: 'todo', verify: 'todo', report: 'todo', gate_accept: 'todo', knowledge: 'todo',
        },
        next_station: 'spec',
        agents: {
          triage: [{ task: 't-0123456789ad', role: 'triage', runner: 'agy', model: 'gemini-3.8-flash', adapter: 'cli', started_at: '2026-11-21T10:44:31.000000Z' }],
        },
        lanes: [],
        attention: null,
        limit: null,
        task_usage: {},
        pending_notes: 0,
        created_at: '2026-11-21T10:44:20.000000Z',
        updated_at: '2026-11-21T10:44:58.000000Z',
      },
    ],
    queue: [
      { slug: 'payroll-export', title: 'Export payroll as CSV', position: 1, reason: 'the project limit of 3 running tasks is reached' },
      { slug: 'holiday-calendar', title: 'Holiday calendar sync', position: 2, reason: 'the project limit of 3 running tasks is reached' },
    ],
    routing: { problems: [] },
  };
}

export function twoProjects(): Db {
  const lb = withPhaseNodes(leaveBalance());
  const lf = leaveForm();
  const tf = taxForm();
  const of = oldFix();
  return {
    installation: { version: '1.1.0', path: '/home/dev/.local/share/uv/tools/sentinel', python: '3.12.3', method: 'uv tool' },
    runtime: { pid: 4242, port: 47831, started_at: '2026-11-14T08:00:00Z', projects: ['digital-hr', 'payroll'] },
    health: health(),
    projects: [
      { id: 'digital-hr', name: 'digital-hr', path: '/ws/digital-hr', status: 'available', reason: null, active_runs: 2 },
      { id: 'payroll', name: 'payroll', path: '/ws/payroll', status: 'available', reason: null, active_runs: 0 },
    ],
    projectData: {
      'digital-hr': digitalHrData([summary(lb.detail), summary(lf.detail), summary(of.detail)]),
      payroll: {
        ...digitalHrData([summary(tf.detail)]),
        repositories: { next: null, items: [repo('payroll-api', { path: '/ws/payroll/payroll-api', role: 'backend', profile: 'node', commands: { build: 'npm run build', test: 'npm test', lint: null } })] },
        audit: [],
      },
    },
    runs: { 'digital-hr/leave-balance': lb, 'digital-hr/leave-form': lf, 'digital-hr/old-fix': of, 'payroll/tax-form': tf },
    notifications: [],
    analytics: { 'digital-hr': analyticsSmall(), payroll: analyticsSmall() },
    factory: { 'digital-hr': digitalHrFactory() },
  };
}

export { runDetail, leaveBalance, digitalHrData, readyReadiness, repo };
