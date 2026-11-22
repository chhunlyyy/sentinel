// The fake API keeps its data in the view-model form of src/api/types.ts (easy to edit from tests) and answers in the
// form of the real server (src/api/wire.ts). Every function returns a wire type, so the compiler ties the answers
// to wire.ts, and fixtures/check.ts compares them with the answers recorded from the real server.
import type * as T from '../src/api/types.ts';
import type * as W from '../src/api/wire.ts';
import type { ProjectData, RunData } from './db.ts';
import { sampleKnowledgeUsed } from './knowledge-fixtures.ts';

export const installation = (i: T.Installation): W.WInstallation => ({ version: i.version, install_path: i.path, python: i.python, method: i.method });

export const runtime = (r: T.Runtime): W.WRuntime => ({
  pid: r.pid, port: r.port, started_at: r.started_at, version: '1.1.0', user: { name: 'dev', role: 'admin' }, projects: r.projects.map((id) => ({ id, name: id })),
});

export const health = (h: T.Health): W.WHealth => ({
  ready: h.ready,
  checked_at: h.checked_at,
  items: h.checks.map((c) => ({ name: c.id, required: c.required, status: c.status, message: c.message, fix: c.fix ?? '' })),
});

export const projects = (list: T.Project[]) =>
  list.map((p) => ({ id: p.id, name: p.name, path: p.path, added_at: '2026-11-14T00:00:00Z', status: p.status, ...(p.reason ? { reason: p.reason } : {}), active_runs: p.active_runs }));

export const readiness = (pid: string, r: T.Readiness): W.WReadiness => ({
  project: pid,
  workflow: r.workflow,
  state: r.state,
  // an invalid configuration is reported as schema errors with a path, never as items
  errors: r.state === 'invalid_configuration' ? r.items.filter((i) => i.path).map((i) => ({ path: i.path!, message: i.message ?? '' })) : [],
  items: r.items.filter((i) => r.state !== 'invalid_configuration' || !i.path).map((i) => ({
    name: i.id, repo: i.repo ?? null, required: i.status === 'failed' || i.status === 'not_configured', status: i.status, message: i.message ?? '', fix: i.fix ?? '', checked_at: r.checked_at,
  })),
});

export const repository = (r: T.Repository): W.WRepository => ({
  id: r.id, path: r.path, remote: r.remote, default_branch: r.default_branch, current_branch: r.branch, role: r.role, profile: r.profile,
  commands: { build: '', test: '', lint: '', typecheck: '', mutate: '', ...Object.fromEntries(Object.entries(r.commands).map(([k, v]) => [k, v ?? ''])) },
  guidelines: r.guidelines,
  validation: r.validation.map((v) => ({ name: v.item, status: v.status, message: '', fix: v.fix ?? '' })),
});

export const configuration = (pid: string, c: T.Configuration): W.WConfiguration => ({
  project: pid,
  sha256: c.sha256,
  global_file: null,
  items: c.values.map((v) => ({
    key: v.path, value: v.value, source: v.source === 'repo' ? `repo:${v.repo ?? ''}` : v.source,
    overridden: v.overrides ? [{ source: v.overrides.source, value: v.overrides.value }] : [],
  })),
});

export const configVersion = (v: T.ConfigVersion): W.WConfigVersion => ({
  id: v.version, scope: 'workspace', sha256: v.sha256, author: v.author, channel: v.channel, created_at: v.at, comment: v.comment,
});

export const audit = (pid: string, a: T.AuditRow): W.WAudit => ({
  id: a.id, project: pid, actor: a.actor, channel: a.channel, action: a.action, target: a.target, before_sha: a.before_sha256, after_sha: a.after_sha256, reason: a.reason, at: a.at,
  row_sha: String(a.id).padStart(64, '0'), chain_sha: String(a.id).padStart(64, 'f'),
});

export const runSummary = (s: T.RunSummary) => ({
  slug: s.slug, type: s.type, tier: s.tier, state: s.state, execution_status: s.execution_status, acceptance_status: s.acceptance_status,
  workflow_version: s.workflow_version, priority: null, requested_tier: null, origin: null, driver: "cli", paused: false, created_at: s.updated_at, updated_at: s.updated_at,
});

const approval = (a: T.ApprovalState): W.WApproval => ({
  state: a.state, version: a.version ?? 0, sha256: a.sha256 ?? '', decision: a.record?.decision ?? null, approver: a.record?.approver ?? null,
  channel: a.record?.channel ?? null, comment: a.record?.comment ?? null, decided_at: a.record?.at ?? null,
});

export function next(n: T.NextStep, run: T.Run): W.WNext {
  const base = { run: run.slug, state: run.state };
  switch (n.kind) {
    case 'orchestrator':
      return { kind: 'orchestrator', ...base, label: n.label, resume_command: n.command ?? undefined };
    case 'human':
      return { kind: 'human', ...base, reason: n.label, commands: [`sentinel review ${run.slug} ${n.gate === 'gherkin' ? 'gherkin' : 'spec'}`] };
    case 'task':
      return { kind: 'task', ...base, label: n.label, command: n.command ?? undefined, task: 't-next', role: 'tdd_red', adapter: 'cli', provider: 'fake' };
    case 'wait':
      return { kind: 'wait', ...base, reason: n.label };
    default:
      return { kind: 'done', ...base, reason: n.label };
  }
}

export function run(d: T.Run, nextStep?: T.NextStep): W.WRun {
  const legacy = d.workflow_version === '0.1';
  const approvals: W.WRun['approvals'] = {};
  if (!legacy) {
    for (const g of ['specification', 'gherkin'] as const) if (d.approvals[g].state !== 'NOT_REQUESTED') approvals[g] = approval(d.approvals[g]);
  }
  return {
    slug: d.slug, project: d.project, request: d.request, type: d.type, tier: d.tier, initial_tier: d.initial_tier, state: d.state, reason: d.reason ?? null,
    execution_status: d.execution_status, acceptance_status: d.acceptance_status, workflow_version: d.workflow_version, priority: d.priority, requested_tier: null,
    origin: null, driver: "cli", paused: false, created_at: d.created_at, updated_at: d.updated_at, finished_at: null,
    repos: d.repos.map((r) => ({ repo_id: r.id, baseline_sha: r.baseline_sha, branch: r.branch, final_sha: r.final_sha })),
    approvals,
    config_snapshot: d.config_snapshot ? { id: d.config_snapshot.version, scope: 'workspace', sha256: d.config_snapshot.sha256, created_at: d.created_at } : null,
    task_counts: d.task_counts,
    next: legacy || !nextStep ? null : next(nextStep, d),
  };
}

const decision = (r: T.DecisionRecord | null): W.WDecision | null =>
  r ? { decision: r.decision, approver: r.approver, channel: r.channel, comment: r.comment, decided_at: r.at } : null;

const versions = (list: T.VersionRow[], at: string): W.WVersion[] =>
  list.map((v) => ({ version: v.version, sha256: v.sha256, created_at: at, decision: v.decision, approver: v.reviewer, channel: v.channel, decided_at: v.at, comment: v.comment, provenance: v.provenance }));

const validation = (v: { findings: T.Finding[] }) => ({
  errors: v.findings.filter((f) => f.severity === 'error').map((f) => f.message),
  warnings: v.findings.filter((f) => f.severity !== 'error').map((f) => f.message),
});

export const specification = (s: T.SpecificationAnswer, list: T.VersionRow[], runState: string): W.WSpecification => ({
  version: s.version, sha256: s.sha256, approval_state: s.state, run_state: runState, text: s.text, validation: validation(s.validation), diff: s.diff_to_previous,
  previous_version: s.previous_version, versions: versions(list, s.requested_at ?? ''), decision: decision(s.decision), requested_at: s.requested_at,
  knowledge_used: s.knowledge_used ?? sampleKnowledgeUsed(),
  provenance: s.provenance,
});

export const specVersion = (s: T.SpecificationAnswer): W.WSpecVersion => ({ version: s.version, sha256: s.sha256, text: s.text, provenance: s.provenance ?? null });

export function gherkin(g: T.GherkinAnswer, runState: string): W.WGherkin {
  const files = g.features.map((f) => ({
    path: f.path,
    text: `Feature: ${f.name}\n\n${f.scenarios.map((s) => `  Scenario: ${s.name}\n    Given x\n`).join('\n')}`,
  }));
  return {
    version: g.version, sha256: g.sha256, approval_state: g.state, run_state: runState, files,
    scenarios: g.features.flatMap((f) => f.scenarios.map((s, i) => ({ line: 3 + i * 3, name: s.name, path: f.path, tags: [s.ac, s.type, s.priority, ...s.cov] }))),
    coverage: {
      rows: g.coverage.map((c) => ({ category: c.category, reason: c.reason ?? '', scenarios: c.scenarios, state: c.status, status: c.status === 'covered' ? `covered by ${c.scenarios} scenarios` : c.status })),
      summary: '', warnings: g.coverage.filter((c) => c.status === 'missing').map((c) => `${c.category}: missing`),
    },
    validation: validation(g.validation), diff: null, previous_version: null, versions: versions(g.versions, g.requested_at ?? ''), decision: decision(g.decision), requested_at: g.requested_at,
    knowledge_used: g.knowledge_used ?? sampleKnowledgeUsed(),
  };
}

export const workflow = (w: T.Workflow, d: T.Run): W.WWorkflow => ({
  nodes: w.nodes.map((n) => ({
    id: n.id, role: n.role, repo: n.repo, state: n.state, adapter: n.adapter, provider: n.provider, model: n.model, attempt: n.attempt, retry_of: n.retry_of,
    error_code: n.error_code, started_at: n.started_at, finished_at: n.finished_at, seconds: n.seconds, label: n.label ?? null,
  })),
  edges: w.edges,
  gates: w.gates.map((g) => ({ gate: g.gate, state: g.state, version: g.version ?? 0, sha256: d.approvals[g.gate].sha256 ?? '' })),
});

export const tdd = (t: T.TddAnswer): W.WTdd => ({
  cycles: t.cycles.map((c) => ({
    id: c.id, repo: c.repo, behavior: c.behavior, state: c.state, red_method: 'test_file', exception: null,
    phase_tasks: { red: c.phases[0]?.task_id ?? null, green: c.phases[1]?.task_id ?? null, refactor: c.phases[2]?.task_id ?? null },
    evidence_ids: c.phases.flatMap((p) => p.evidence_ids),
  })),
});

const evidence = (e: T.Evidence, cycle: T.Cycle | undefined, taskId: string | null): W.WEvidence => ({
  id: e.id, task_id: taskId, cycle_id: cycle?.id ?? null, kind: e.kind, command: e.command, exit_code: e.exit_code, classification: e.classification,
  passed: e.passed, failed: e.failed, skipped: null, output_artifact_id: e.output_artifact, started_at: e.started_at, finished_at: e.finished_at,
  repo_id: e.repo, provider: e.provider, model: e.model, name: null, round: null, verdict: null,
});

const rowVerdict = (e: T.Evidence): string => (e.status === 'passed' ? 'pass' : e.status === 'failed' ? 'fail' : e.status);

export function verification(r: RunData): W.WVerification {
  const cycleOf = (id: string) => r.tdd.cycles.find((c) => c.phases.some((p) => p.evidence_ids.includes(id)));
  const taskOf = (id: string) => cycleOf(id)?.phases.find((p) => p.evidence_ids.includes(id))?.task_id ?? null;
  const v = r.verification;
  return {
    cycles: r.tdd.cycles.map((c) => ({ id: c.id, repo: c.repo, behavior: c.behavior, state: c.state, red_method: 'test_file', exception: null })),
    round: v.round ? v.round.number : null,
    missing: v.missing.map((m) => `${m.repo ?? ''} ${m.kind}`.trim()),
    evidence: [
      ...r.tdd.evidence.map((e) => evidence(e, cycleOf(e.id), taskOf(e.id))),
      ...v.rows.map((e) => ({ ...evidence(e, undefined, null), round: v.round ? v.round.number : null, verdict: rowVerdict(e) })),
    ],
    acceptance_record: v.acceptance_record ? { decision: v.acceptance_record.decision, approver: v.acceptance_record.approver, channel: v.acceptance_record.channel, at: v.acceptance_record.at, comment: v.acceptance_record.comment } : null,
    acceptance: {
      execution_status: r.detail.execution_status, acceptance_status: v.acceptance.computed,
      reasons: v.acceptance.reasons.map((x) => x.text),
    },
  };
}

export function trace(r: RunData): W.WTrace {
  const links: W.WTrace['links'] = [];
  for (const req of r.trace.requirements) {
    for (const ac of req.acs) {
      links.push({ from_kind: 'req', from_id: req.id, to_kind: 'ac', to_id: ac.id });
      for (const sc of ac.scenarios) {
        const id = `features/${ac.id.toLowerCase()}.feature :: ${sc.name}`;
        links.push({ from_kind: 'ac', from_id: ac.id, to_kind: 'scenario', to_id: id });
        if (sc.cycle) links.push({ from_kind: 'scenario', from_id: id, to_kind: 'cycle', to_id: sc.cycle.id });
      }
    }
  }
  return { links, gaps: r.trace.gaps.map((g) => ({ kind: 'ac_without_scenario', id: g })) };
}

export const changes = (slug: string, c: T.ChangesAnswer): W.WChanges => ({
  slug,
  repos: c.repos.map((r) => ({
    repo: r.id, base_sha: r.base, branch: r.branch, head_sha: r.head,
    files: r.files.map((f) => ({ path: f.path, status: f.status, additions: f.additions, deletions: f.deletions, binary: false, tasks: f.tasks, cycles: f.cycles })),
  })),
});

function pairRows(lines: T.DiffLine[]): NonNullable<W.WDiff['hunks'][number]['rows']> {
  const rows: NonNullable<W.WDiff['hunks'][number]['rows']> = [];
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (l.type === 'ctx') {
      rows.push({ old: { n: l.old, text: l.text }, new: { n: l.new, text: l.text } });
      i += 1;
      continue;
    }
    const dels: T.DiffLine[] = [];
    const adds: T.DiffLine[] = [];
    while (i < lines.length && lines[i].type === 'del') dels.push(lines[i++]);
    while (i < lines.length && lines[i].type === 'add') adds.push(lines[i++]);
    for (let k = 0; k < Math.max(dels.length, adds.length); k++) {
      rows.push({ old: dels[k] ? { n: dels[k].old, text: dels[k].text } : null, new: adds[k] ? { n: adds[k].new, text: adds[k].text } : null });
    }
  }
  return rows;
}

export const diff = (repo: string, path: string, d: { binary: boolean; truncated: boolean; hunks: T.DiffAnswer['hunks'] }, mode = 'inline'): W.WDiff => ({
  repo, path, mode, status: 'modified',
  additions: d.hunks.reduce((n, h) => n + h.lines.filter((l) => l.type === 'add').length, 0),
  deletions: d.hunks.reduce((n, h) => n + h.lines.filter((l) => l.type === 'del').length, 0),
  binary: d.binary, truncated: d.truncated,
  hunks: d.hunks.map((h) => (mode === 'split' ? { header: h.header, old_start: 1, new_start: 1, rows: pairRows(h.lines) } : { header: h.header, old_start: 1, new_start: 1, lines: h.lines })),
});

export const log = (taskId: string, lines: string[], total: number, from: number, running: boolean): W.WLog => ({ task_id: taskId, lines: lines.slice(from), next_offset: total, running });

export const configDiff = (a: string, b: string, text: string): W.WConfigDiff => ({ a, b, identical: text === '', diff: text });

export type { ProjectData };
