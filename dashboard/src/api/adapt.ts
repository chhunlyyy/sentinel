// Converts the answers of the real server (wire.ts) into the view models of the screens (types.ts).
// Every function is total: a missing optional part of an answer gives an empty value, never an exception.
import type * as T from './types.ts';
import type * as W from './wire.ts';

const GATES = ['specification', 'gherkin'] as const;
type Gate = (typeof GATES)[number];

export const installation = (w: W.WInstallation): T.Installation => ({ version: w.version, path: w.install_path, python: w.python, method: w.method });

export const runtime = (w: W.WRuntime): T.Runtime => ({ pid: w.pid, port: w.port, started_at: w.started_at, projects: w.projects.map((p) => p.id) });

export const health = (w: W.WHealth): T.Health => ({
  ready: w.ready,
  checked_at: w.checked_at,
  checks: w.items.map((i) => ({ id: i.name, label: i.name, required: i.required, status: i.status as T.CheckStatus, message: i.message, fix: i.fix || null })),
});

export function readiness(w: W.WReadiness): T.Readiness {
  const items: T.ReadinessItem[] = w.items.map((i) => ({ id: i.name, status: i.status as T.ItemStatus, repo: i.repo ?? undefined, message: i.message, fix: i.fix || null }));
  for (const e of w.errors ?? []) items.push({ id: 'configuration', status: 'failed', message: `${e.path}: ${e.message}`, fix: null });
  const checked = w.items.map((i) => i.checked_at).filter(Boolean).sort();
  return { state: w.state as T.ReadinessState, workflow: w.workflow, checked_at: checked[checked.length - 1] ?? '', items };
}

export const repository = (w: W.WRepository): T.Repository => ({
  id: w.id,
  path: w.path,
  remote: w.remote,
  default_branch: w.default_branch,
  branch: w.current_branch,
  role: w.role,
  profile: w.profile,
  commands: Object.fromEntries(Object.entries(w.commands).map(([k, v]) => [k, v || null])),
  guidelines: w.guidelines,
  validation: w.validation.map((v) => ({ item: v.name, status: v.status as T.ItemStatus, fix: v.fix || null })),
});

const CATEGORY: Record<string, string> = {
  project: 'Project', repos: 'Repositories', providers: 'Providers', runners: 'Providers', agents: 'Agents', routing: 'Agents', single_model: 'Agents',
  workflow: 'Workflow and policies', policies: 'Workflow and policies', rules: 'Workflow and policies', tdd: 'TDD', verification: 'Verification',
  release_checks: 'Verification', qa: 'Verification', limits: 'Limits', state: 'Project', tracker: 'Project', shape: 'Project', version: 'Project',
};

const sourceOf = (s: string): T.ConfigValue['source'] => (s.startsWith('repo:') ? 'repo' : (s as T.ConfigValue['source']));

export const configuration = (w: W.WConfiguration): T.Configuration => ({
  sha256: w.sha256,
  values: w.items.map((i) => {
    const prev = i.overridden[i.overridden.length - 1];
    return {
      path: i.key,
      value: i.value,
      category: CATEGORY[i.key.split('.')[0]] ?? 'Other',
      source: sourceOf(i.source),
      repo: i.source.startsWith('repo:') ? i.source.slice(5) : undefined,
      overrides: prev ? { source: sourceOf(prev.source), value: prev.value } : undefined,
    };
  }),
});

export const configVersion = (w: W.WConfigVersion): T.ConfigVersion => ({
  version: w.id, sha256: w.sha256, author: w.author ?? '', channel: w.channel ?? '', at: w.created_at, comment: w.comment,
});

export const audit = (w: W.WAudit): T.AuditRow => ({
  id: w.id, project: w.project, actor: w.actor, channel: w.channel ?? '', action: w.action, target: w.target,
  before_sha256: w.before_sha, after_sha256: w.after_sha, reason: w.reason, at: w.at,
});

export const record = (d: Pick<W.WDecision, 'decision' | 'approver' | 'channel' | 'comment' | 'decided_at'> | { decision: string | null; approver: string | null; channel: string | null; comment: string | null; decided_at: string | null } | null | undefined): T.DecisionRecord | null =>
  d && d.decision ? { decision: d.decision, approver: d.approver ?? '', channel: d.channel ?? '', at: d.decided_at ?? '', comment: d.comment } : null;

export function next(w: W.WNext | null | undefined, state?: string): T.NextStep | undefined {
  if (!w) return undefined;
  const command = w.command ?? w.resume_command ?? w.commands?.[0] ?? null;
  const kind = (['orchestrator', 'task', 'human', 'done', 'wait'].includes(w.kind) ? w.kind : 'wait') as T.NextStep['kind'];
  const gate: Gate | undefined = kind === 'human' ? ((w.state ?? state ?? '').startsWith('GHERKIN') ? 'gherkin' : 'specification') : undefined;
  return { kind, label: w.label ?? w.reason ?? w.kind, command, gate };
}

export function run(w: W.WRun): T.Run {
  const approvals = {} as T.Run['approvals'];
  for (const g of GATES) {
    const a = w.approvals?.[g];
    approvals[g] = a
      ? { gate: g, state: a.state, version: a.version, sha256: a.sha256, record: record(a) }
      : { gate: g, state: 'NOT_REQUESTED', version: null, sha256: null, record: null };
  }
  return {
    slug: w.slug, project: w.project, type: w.type, tier: w.tier, initial_tier: w.initial_tier, state: w.state, reason: w.reason,
    execution_status: w.execution_status, acceptance_status: w.acceptance_status, workflow_version: w.workflow_version === '0.1' ? '0.1' : '2',
    request: w.request ?? '', priority: w.priority, ticket: null, created_at: w.created_at, updated_at: w.updated_at,
    repos: (w.repos ?? []).map((r) => ({ id: r.repo_id, baseline_sha: r.baseline_sha ?? '', branch: r.branch ?? '', final_sha: r.final_sha })),
    approvals, task_counts: w.task_counts ?? {},
    config_snapshot: w.config_snapshot ? { version: w.config_snapshot.id, sha256: w.config_snapshot.sha256 } : null,
    next: next(w.next, w.state),
  };
}

const versionRow = (v: W.WVersion): T.VersionRow => ({
  version: v.version, sha256: v.sha256, decision: v.decision, reviewer: v.approver, channel: v.channel, at: v.decided_at, comment: v.comment,
  provenance: v.provenance ?? undefined,
});

const findings = (v: { errors: string[]; warnings: string[] }): T.Finding[] => [
  ...v.errors.map((message) => ({ severity: 'error', message })),
  ...v.warnings.map((message) => ({ severity: 'warning', message })),
];

export const specification = (w: W.WSpecification): T.SpecificationAnswer => ({
  version: w.version, sha256: w.sha256, state: w.approval_state ?? 'NOT_REQUESTED', text: w.text,
  validation: { ok: w.validation.errors.length === 0, findings: findings(w.validation) },
  previous_version: w.previous_version, diff_to_previous: w.diff, versions: w.versions.map(versionRow),
  decision: record(w.decision), requested_at: w.requested_at, knowledge_used: w.knowledge_used,
  provenance: w.provenance ?? undefined,
});

/** An earlier version is read only; its text comes from the versions route, its list from the current answer. */
export const specificationVersion = (w: W.WSpecVersion, current: W.WSpecification): T.SpecificationAnswer => {
  const matching = current.versions.find((v) => v.version === w.version);
  return {
    ...specification(current),
    version: w.version, sha256: w.sha256, text: w.text, state: 'EARLIER', previous_version: null, diff_to_previous: null, decision: null,
    provenance: matching?.provenance ?? (w.version === current.version ? current.provenance : undefined) ?? undefined,
  };
};

const TYPES = new Set(['unit', 'integration', 'e2e', 'contract', 'security', 'regression', 'performance']);

function featureName(text: string, path: string): string {
  const m = /^\s*Feature:\s*(.+)$/m.exec(text);
  return m ? m[1].trim() : path;
}

export function gherkin(w: W.WGherkin): T.GherkinAnswer {
  const features: T.GherkinFeature[] = w.files.map((f) => ({
    path: f.path,
    name: featureName(f.text, f.path),
    text: f.text,
    scenarios: w.scenarios
      .filter((s) => s.path === f.path)
      .map((s) => {
        const tags = s.tags.map((t) => t.replace(/^@/, ''));
        return {
          name: s.name,
          ac: tags.find((t) => t.startsWith('AC-')) ?? '',
          type: tags.find((t) => TYPES.has(t)) ?? '',
          priority: tags.find((t) => /^P\d$/.test(t)) ?? '',
          tags,
          cov: tags.filter((t) => t.startsWith('cov-')),
        };
      }),
  }));
  return {
    version: w.version, sha256: w.sha256, state: w.approval_state ?? 'NOT_REQUESTED', features,
    coverage: w.coverage.rows.map((r) => ({
      category: r.category, scenarios: r.scenarios, reason: r.reason || null,
      status: r.state === 'covered' ? 'covered' : r.state === 'not_applicable' ? 'not_applicable' : 'missing',
    })),
    validation: { ok: w.validation.errors.length === 0, findings: findings(w.validation) },
    versions: w.versions.map(versionRow), decision: record(w.decision), requested_at: w.requested_at,
    knowledge_used: w.knowledge_used,
  };
}

export const workflow = (w: W.WWorkflow): T.Workflow => ({
  nodes: w.nodes.map((n) => ({ ...n })),
  edges: w.edges,
  gates: w.gates.map((g) => ({ gate: g.gate as Gate, state: g.state, version: g.version })),
});

function evidenceStatus(e: W.WEvidence): string {
  if (e.verdict) return e.verdict === 'pass' ? 'passed' : e.verdict === 'fail' ? 'failed' : e.verdict;
  if (e.exit_code === null || e.exit_code === undefined) return 'not_run';
  return e.exit_code === 0 ? 'passed' : 'failed';
}

export function evidence(list: W.WEvidence[], tdd: W.WTdd, wf: W.WWorkflow): T.Evidence[] {
  const cycles = new Map(tdd.cycles.map((c) => [c.id, c]));
  const nodes = new Map(wf.nodes.map((n) => [n.id, n]));
  return list.map((e) => {
    const node = e.task_id ? nodes.get(e.task_id) : undefined;
    return {
      id: e.id, kind: e.kind, repo: e.repo_id ?? (e.cycle_id ? cycles.get(e.cycle_id)?.repo : null) ?? node?.repo ?? null, status: evidenceStatus(e),
      command: e.command, exit_code: e.exit_code, passed: e.passed, failed: e.failed, classification: e.classification,
      started_at: e.started_at, finished_at: e.finished_at, provider: e.provider ?? node?.provider ?? null, model: e.model ?? node?.model ?? null,
      files: [], output_artifact: e.output_artifact_id,
    };
  });
}

export function tdd(w: W.WTdd, wf: W.WWorkflow, ver: W.WVerification): T.TddAnswer {
  const nodes = new Map(wf.nodes.map((n) => [n.id, n]));
  const ev = evidence(ver.evidence, w, wf);  // cycle evidence and the evidence of verification rounds
  const cycles: T.Cycle[] = w.cycles.map((c) => ({
    id: c.id, behavior: c.behavior, repo: c.repo ?? '', state: c.state,
    phases: (['red', 'green', 'refactor'] as const).map((phase) => {
      const tid = c.phase_tasks[phase];
      const node = tid ? nodes.get(tid) : undefined;
      const ids = new Set(c.evidence_ids);
      return {
        phase, task_id: tid, state: node?.state ?? 'PENDING', attempt: node?.attempt ?? 0,
        evidence_ids: ver.evidence.filter((e) => ids.has(e.id) && ((tid && e.task_id === tid) || (phase === 'red' && !e.task_id))).map((e) => e.id),
      };
    }),
  }));
  return { cycles, evidence: ev };
}

/** The view that shows a reason the engine computed (reasons are plain text, e.g. "cycles incomplete: login"). */
function reasonView(text: string): T.VerificationAnswer['acceptance']['reasons'][number]['view'] {
  if (/^cycles incomplete/.test(text)) return 'tdd';
  if (/^scope exceeded/.test(text)) return 'changes';
  return 'verification';
}

export function verification(w: W.WVerification, tddAnswer: W.WTdd, wf: W.WWorkflow): T.VerificationAnswer {
  const rows = w.evidence.filter((e) => !e.cycle_id && (e.round === null || e.round === undefined || e.round === w.round));
  // the server gives the round number only; its time is when the first check of the round started
  const started = rows.map((r) => r.started_at).filter((t): t is string => !!t).sort()[0] ?? '';
  return {
    round: typeof w.round === 'number' ? { number: w.round, at: started } : null,
    rows: evidence(rows, tddAnswer, wf),
    missing: (w.missing ?? []).map((m) => {
      const [repo, ...kind] = m.split(' ');
      return { repo, kind: kind.join(' '), reason: 'no evidence row' };
    }),
    acceptance: {
      computed: w.acceptance.acceptance_status,
      reasons: (w.acceptance.reasons ?? []).map((r) => ({ text: String(r), view: reasonView(String(r)) })),
    },
    acceptance_record: w.acceptance_record ? { ...w.acceptance_record } : null,
  };
}

/** requirement -> acceptance criterion -> scenario -> cycle (files, evidence), built from the flat links of the server. */
export function trace(w: W.WTrace, wf: W.WTdd, ver: W.WVerification, ch: W.WChanges): T.TraceAnswer {
  const out = (from: string, to: string, id: string) => w.links.filter((l) => l.from_kind === from && l.to_kind === to && l.from_id === id).map((l) => l.to_id);
  const reqIds = Array.from(new Set(w.links.filter((l) => l.from_kind === 'req').map((l) => l.from_id)));
  const requirements: T.TraceAnswer['requirements'] = reqIds.map((id) => ({
    id,
    acs: out('req', 'ac', id).map((ac) => ({
      id: ac,
      scenarios: out('ac', 'scenario', ac).map((sc) => {
        const cycleId = out('scenario', 'cycle', sc)[0];
        const cycle = cycleId ? wf.cycles.find((c) => c.id === cycleId) : undefined;
        const files = cycle ? ch.repos.flatMap((r) => r.files.filter((f) => f.cycles.includes(cycle.id)).map((f) => ({ repo: r.repo, path: f.path }))) : [];
        const evs = cycle ? ver.evidence.filter((e) => e.cycle_id === cycle.id).map((e) => ({ id: e.id, kind: e.kind, passed: e.exit_code === 0 })) : [];
        return { id: sc, name: sc.includes(' :: ') ? sc.split(' :: ').slice(1).join(' :: ') : sc, cycle: cycle ? { id: cycle.id, files, evidence: evs } : null };
      }),
    })),
  }));
  const failures = ver.evidence.filter((e) => e.exit_code !== null && e.exit_code !== 0 && e.classification !== 'valid_red' && e.classification !== 'expected_failure')
    .map((e) => ({ text: `evidence "${e.kind}" of cycle "${e.cycle_id ?? 'none'}" failed (${e.classification ?? 'no classification'})`, evidence_id: e.id }));
  return { requirements, gaps: w.gaps.map((g) => `${g.kind}: ${g.id}`), failures, acceptance: { state: ver.acceptance.acceptance_status } };
}

export const changes = (w: W.WChanges): T.ChangesAnswer => ({
  repos: w.repos.map((r) => ({
    id: r.repo, branch: r.branch ?? '', base: r.base_sha ?? '', head: r.head_sha ?? '', files_count: r.files.length,
    additions: r.files.reduce((n, f) => n + f.additions, 0), deletions: r.files.reduce((n, f) => n + f.deletions, 0),
    files: r.files.map((f) => ({ path: f.path, status: f.status, additions: f.additions, deletions: f.deletions, cycles: f.cycles, tasks: f.tasks })),
  })),
});

export const diff = (w: W.WDiff): T.DiffAnswer => ({
  repo: w.repo, path: w.path, binary: w.binary, truncated: w.truncated,
  hunks: w.hunks.map((h) => ({
    header: h.header,
    lines: (h.lines ?? []) as T.DiffLine[],
    rows: h.rows?.map((r) => {
      const same = r.old && r.new && r.old.text === r.new.text;
      if (same) {
        const ctx = (side: NonNullable<typeof r.old>): T.DiffLine => ({ type: 'ctx', old: r.old!.n, new: r.new!.n, text: side.text });
        return { left: ctx(r.old!), right: ctx(r.new!) };
      }
      return {
        left: r.old ? { type: 'del' as const, old: r.old.n, new: null, text: r.old.text } : null,
        right: r.new ? { type: 'add' as const, old: null, new: r.new.n, text: r.new.text } : null,
      };
    }),
  })),
});

export function report(w: W.WReport): T.ReportAnswer {
  const env = w as { sha256?: unknown; report?: unknown };
  if (typeof env.sha256 === 'string' && env.report && typeof env.report === 'object') return { sha256: env.sha256, report: env.report as Record<string, unknown> };
  return { sha256: null, report: w as Record<string, unknown> };
}

export function decision(w: W.WRun, gate: Gate): T.ApprovalDecisionAnswer {
  const r = run(w);
  const a = r.approvals[gate];
  const rec = a.record ?? { decision: '', approver: '', channel: '', at: '', comment: null };
  return { approval: { ...rec, gate, state: a.state, version: a.version ?? 0, sha256: a.sha256 ?? '' }, run: r };
}

/** The answer to POST acceptance is the run; the record of the decision is read from the verification answer. */
export function acceptance(w: W.WRun): T.AcceptanceAnswer {
  return { run: run(w) };
}


