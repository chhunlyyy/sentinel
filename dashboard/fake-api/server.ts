// Fake Sentinel API for the dashboard e2e tests. It follows plan/v1.1/phaseF (routes, envelopes, cookie, CSRF,
// security headers, SSE) and answers from the hand-written fixtures. The /__control routes exist only here.
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import { CSRF, SESSION, TOKEN } from '../fixtures/constants.ts';
import type { Db, RunData } from '../fixtures/db.ts';
import { freshInstall } from '../fixtures/fresh-install.ts';
import * as E from '../fixtures/encode.ts';
import { applyPreset } from '../fixtures/presets.ts';
import { summary, twoProjects, payrollRounding } from '../fixtures/two-projects.ts';
import {
  SAMPLE_KNOWLEDGE_RECORDS,
  sampleKnowledgeStatus,
  sampleKnowledgeRelated,
  sampleKnowledgeCiTemplate,
  sampleRoutingSuggest,
  routingFix,
  sampleDetect,
  sampleConfigForm,
} from '../fixtures/knowledge-fixtures.ts';



const PORT = Number(process.env.FAKE_API_PORT ?? 47831);
const ROOT = new URL('..', import.meta.url).pathname;
const DIST = join(ROOT, process.env.DASHBOARD_OUT_DIR ?? '../sentinel/dashboard_dist');

let db: Db = twoProjects();

interface Rule {
  method?: string;
  path: string;
  status?: number;
  body?: unknown;
  rawBody?: string;
  contentType?: string;
  delayMs?: number;
  drop?: boolean;
  hang?: boolean;
  times?: number;
  passthrough?: boolean;
}
let rules: Rule[] = [];
let log: { n: number; t: number; method: string; path: string; search: string; headers: Record<string, string>; body: unknown }[] = [];
let sentEvents: { id: string; t: number }[] = [];
let streams = new Set<ServerResponse>();
let refuseUntil = 0;
let eventSeq = 100;
let chatFail = false;
let runChats: Record<string, { id: string; role: 'user' | 'orchestrator'; text: string; at: string; status: 'done' | 'pending' | 'failed'; error?: string }[]> = {};
let heartbeat: ReturnType<typeof setInterval> | null = null;

interface FactoryState {
  paused: boolean;
  paused_at: string | null;
  running_total: number;
  max_agents: number;
}
let factoryState: FactoryState = {
  paused: false,
  paused_at: null,
  running_total: 1,
  max_agents: 4,
};

function getFactoryStatus() {
  let maxAgents = 4;
  let running = 0;
  if (db.factory) {
    for (const f of Object.values(db.factory)) {
      if (f.limits?.max_agents && f.limits.max_agents > maxAgents) maxAgents = f.limits.max_agents;
      if (typeof f.limits?.running_total === 'number') running = Math.max(running, f.limits.running_total);
    }
  }
  return {
    paused: factoryState.paused,
    paused_at: factoryState.paused_at,
    running_total: running || factoryState.running_total || 1,
    max_agents: maxAgents || factoryState.max_agents || 4,
  };
}

// ---- providers, orchestrator, agents, folders and project creation (state of the fake only) ----

interface AgentCfg {
  agents: Record<string, { runner?: string; model?: string }>;
  providers: { default: string | null; fallback: string[]; disabled: string[] };
  single_model: boolean;
  rev: number;
}
interface Ext {
  installed: Record<string, string | null>;
  orchestrator: string | null;
  global: AgentCfg;
  projects: Record<string, AgentCfg>;
  /** directory tree of the fake machine: path to child names */
  tree: Record<string, string[]>;
  git: Set<string>;
  workspaces: Set<string>;
}

const emptyCfg = (): AgentCfg => ({ agents: {}, providers: { default: null, fallback: [], disabled: [] }, single_model: false, rev: 1 });

function freshExt(): Ext {
  return {
    installed: { claude: '/usr/local/bin/claude', codex: '/usr/bin/codex', gemini: null, agy: null },
    orchestrator: null,
    global: { ...emptyCfg(), agents: { qa: { runner: 'codex' } } },
    projects: {},
    tree: {
      '/': ['home'],
      '/home': ['dev'],
      '/home/dev': ['projects', 'Documents', '.cache'],
      '/home/dev/projects': ['payroll', 'hr-backend', 'hr-frontend', 'legacy'],
      '/home/dev/projects/payroll': [],
      '/home/dev/projects/hr-backend': [],
      '/home/dev/projects/hr-frontend': [],
      '/home/dev/projects/legacy': [],
      '/home/dev/Documents': [],
    },
    git: new Set(['/home/dev/projects/hr-backend', '/home/dev/projects/hr-frontend']),
    workspaces: new Set(['/home/dev/projects/legacy']),
  };
}

const ROLES = ['specifier', 'test_designer', 'tdd_red', 'qa_red', 'tdd_green', 'tdd_refactor', 'reviewer', 'qa', 'retrospective'];
const PROVIDERS = [
  { id: 'claude', label: 'Claude Code', command: 'claude', capabilities: { model_select: true, resume: true, json_output: true }, models: [{ id: 'opus', label: 'Opus' }, { id: 'sonnet', label: 'Sonnet' }, { id: 'haiku', label: 'Haiku' }] },
  { id: 'codex', label: 'Codex CLI', command: 'codex', capabilities: { model_select: true, resume: true, json_output: true }, models: [] },
  { id: 'gemini', label: 'Gemini CLI', command: 'gemini', capabilities: { model_select: true, resume: false, json_output: true }, models: [{ id: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' }, { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' }] },
  { id: 'agy', label: 'Antigravity (agy)', command: 'agy', capabilities: { model_select: false, resume: false, json_output: false }, models: [] },
];
const PROFILES = [
  { id: 'generic', label: 'Generic', detect: [] },
  { id: 'node', label: 'Node', detect: ['package.json'] },
  { id: 'python', label: 'Python', detect: ['pyproject.toml'] },
];

let ext = freshExt();

const cfgSha = (pid: string, c: AgentCfg) => createHash('sha256').update(`${pid}:${c.rev}:${JSON.stringify([c.agents, c.providers, c.single_model])}`).digest('hex');

class ApiErr extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const SECURITY = { 'Content-Security-Policy': "default-src 'self'; frame-ancestors 'none'", 'X-Content-Type-Options': 'nosniff' };

function send(res: ServerResponse, status: number, body: unknown, extra: Record<string, string> = {}) {
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...SECURITY, ...extra });
  res.end(text);
}

function sendError(res: ServerResponse, e: ApiErr) {
  send(res, e.status, { error: { code: e.code, message: e.message, details: e.details } });
}

async function readBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(c as Buffer);
  const text = Buffer.concat(chunks).toString('utf8');
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

// ---- control routes (test only) ----

function setPath(root: unknown, path: (string | number)[], value: unknown) {
  let cur = root as Record<string | number, unknown>;
  for (let i = 0; i < path.length; i++) {
    const seg = path[i];
    const last = i === path.length - 1;
    const sel = typeof seg === 'string' ? /^([\w-]+)=(.*)$/.exec(seg) : null;
    if (sel && Array.isArray(cur)) {
      let idx = (cur as Record<string, unknown>[]).findIndex((el) => String(el[sel[1]]) === sel[2]);
      if (idx < 0) {
        if (!last) throw new Error(`no element ${seg}`);
        idx = cur.length;
      }
      if (last) (cur as unknown[])[idx] = value;
      else cur = (cur as unknown as Record<number, Record<string, unknown>>)[idx] as Record<string, unknown>;
      continue;
    }
    if (last) {
      cur[seg] = value;
      return;
    }
    if (cur[seg] === undefined || cur[seg] === null) cur[seg] = typeof path[i + 1] === 'number' ? [] : {};
    cur = cur[seg] as Record<string | number, unknown>;
  }
}

function pushEvent(event: string, data: unknown, raw = false, id?: string) {
  const eid = id ?? `digital-hr:${++eventSeq}`;
  let payloadData = data;
  if (!raw && typeof data === 'object' && data !== null && !Array.isArray(data)) {
    const obj = data as Record<string, unknown>;
    payloadData = {
      project: obj.project ?? 'digital-hr',
      run: obj.run ?? obj.slug ?? null,
      ...obj,
    };
  }
  const payload = raw ? String(payloadData) : JSON.stringify(payloadData);
  const frame = `id: ${eid}\nevent: ${event}\ndata: ${payload}\n\n`;
  sentEvents.push({ id: eid, t: Date.now() });
  for (const s of streams) s.write(frame);
}

async function control(req: IncomingMessage, res: ServerResponse, path: string) {
  const body = (await readBody(req)) as Record<string, unknown> | null;
  const b = body ?? {};
  switch (path) {
    case 'ping':
      return send(res, 200, { ok: true });
    case 'reset': {
      db = b.fixture === 'fresh-install' ? freshInstall() : twoProjects();
      ext = freshExt();
      factoryState = { paused: false, paused_at: null, running_total: 1, max_agents: 4 };
      for (const p of (b.presets as string[] | undefined) ?? []) applyPreset(db, p);
      rules = [];
      log = [];
      sentEvents = [];
      refuseUntil = 0;
      chatFail = false;
      runChats = {};
      for (const s of streams) s.end();
      streams = new Set();
      return send(res, 200, { ok: true });
    }
    case 'chat-fail':
      chatFail = b.fail !== false;
      return send(res, 200, { ok: true });
    case 'preset':
      applyPreset(db, String(b.name));
      return send(res, 200, { ok: true });
    case 'rule':
      rules.push(b as unknown as Rule);
      return send(res, 200, { ok: true });
    case 'set':
      setPath(db, b.path as (string | number)[], b.value);
      return send(res, 200, { ok: true });
    case 'event':
      pushEvent(String(b.event), b.data, b.raw === true, typeof b.id === 'string' ? b.id : undefined);
      return send(res, 200, { ok: true });
    case 'events':
      for (const e of b.events as { event: string; data: unknown }[]) pushEvent(e.event, e.data);
      return send(res, 200, { ok: true });
    case 'stream':
      if (b.action === 'refuse') refuseUntil = Date.now() + Number(b.ms ?? 0);
      if (b.action === 'drop') {
        for (const s of streams) s.destroy();
        streams = new Set();
      }
      return send(res, 200, { ok: true });
    case 'agents-touch': {
      const c = (ext.projects[String(b.project)] ??= emptyCfg());
      c.rev += 1;
      return send(res, 200, { ok: true });
    }
    case 'requests':
      return send(res, 200, log);
    case 'sent-events':
      return send(res, 200, sentEvents);
    default:
      return send(res, 404, { error: { code: 'E_NOT_FOUND', message: 'no such control', details: {} } });
  }
}

// ---- API ----

interface Ctx {
  params: string[];
  query: URLSearchParams;
  body: unknown;
}

function resolveRun(slug: string, query: URLSearchParams): { key: string; run: RunData } {
  if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(slug)) throw new ApiErr(400, 'E_VALIDATION', 'invalid slug', { field: 'slug' });
  const project = query.get('project');
  if (project) {
    const key = `${project}/${slug}`;
    if (!db.runs[key] && slug === 'payroll-rounding') db.runs[key] = payrollRounding();
    if (!db.runs[key]) throw new ApiErr(404, 'E_NOT_FOUND', 'run not found');
    return { key, run: db.runs[key] };
  }
  let hits = Object.keys(db.runs).filter((k) => k.endsWith(`/${slug}`));
  if (!hits.length && slug === 'payroll-rounding') {
    db.runs['digital-hr/payroll-rounding'] = payrollRounding();
    hits = ['digital-hr/payroll-rounding'];
  }
  if (hits.length > 1) throw new ApiErr(400, 'E_VALIDATION', 'slug exists in more than one project', { projects: hits.map((k) => k.split('/')[0]) });
  if (!hits.length) throw new ApiErr(404, 'E_NOT_FOUND', 'run not found');
  return { key: hits[0], run: db.runs[hits[0]] };
}

function page<T>(items: T[], query: URLSearchParams): { items: T[]; next: string | null } {
  const limit = query.has('limit') ? Number(query.get('limit')) : 50;
  if (!Number.isInteger(limit) || limit < 1 || limit > 200) throw new ApiErr(400, 'E_VALIDATION', 'bad limit', { field: 'limit' });
  const start = query.get('cursor') ? Number(query.get('cursor')) : 0;
  const slice = items.slice(start, start + limit);
  return { items: slice, next: start + limit < items.length ? String(start + limit) : null };
}

function proj(pid: string) {
  const p = db.projects.find((x) => x.id === pid);
  const data = db.projectData[pid];
  if (!p) throw new ApiErr(404, 'E_NOT_FOUND', 'project not found');
  if (p.status === 'unavailable' || !data) throw new ApiErr(422, 'E_PRECONDITION', p.reason ?? 'unavailable', { fix: 'run sentinel dashboard in the workspace' });
  return data;
}

function syncApproval(run: RunData, gate: 'specification' | 'gherkin', state: string) {
  run.detail.approvals[gate].state = state;
  const g = run.workflow.gates.find((x) => x.gate === gate);
  if (g) g.state = state;
}

function body(ctx: Ctx): Record<string, unknown> {
  if (!ctx.body || typeof ctx.body !== 'object') throw new ApiErr(400, 'E_VALIDATION', 'a JSON object is required');
  return ctx.body as Record<string, unknown>;
}

type Handler = (ctx: Ctx) => [number, unknown];
const routes: [string, RegExp, Handler][] = [];
const route = (method: string, pattern: string, h: Handler) => {
  routes.push([method, new RegExp(`^${pattern.replace(/\{(\w+)\}/g, '([^/]+)')}$`), h]);
};
const V = '/api/v1';

route('GET', `${V}/session`, () => [200, { csrf: CSRF, user: { name: 'dev', role: 'admin' } }]);
route('GET', `${V}/installation`, () => [200, E.installation(db.installation)]);
route('GET', `${V}/runtime`, () => [200, E.runtime(db.runtime)]);
route('GET', `${V}/installation/health`, () => [200, E.health(db.health)]);
route('GET', `${V}/projects`, () => [200, { items: E.projects(db.projects), next: null }]);
route('GET', `${V}/projects/{pid}/readiness`, (c) => {
  const d = proj(decodeURIComponent(c.params[0]));
  const wf = c.query.get('workflow');
  return [200, E.readiness(decodeURIComponent(c.params[0]), (wf && d.readiness.byWorkflow?.[wf]) || d.readiness.default)];
});
route('GET', `${V}/projects/{pid}/repositories`, (c) => {
  const r = proj(c.params[0]).repositories;
  return [200, { items: r.items.map(E.repository), next: r.next }];
});
route('GET', `${V}/projects/{pid}/configuration`, (c) => [200, E.configuration(c.params[0], proj(c.params[0]).configuration)]);
route('GET', `${V}/projects/{pid}/configuration/history`, (c) => {
  const h = proj(c.params[0]).history;
  return [200, { items: h.items.map(E.configVersion), next: h.next }];
});
route('GET', `${V}/projects/{pid}/configuration/diff`, (c) => {
  const d = proj(c.params[0]);
  const a = c.query.get('a');
  const b = c.query.get('b');
  if (!a || !b) throw new ApiErr(400, 'E_VALIDATION', 'a and b are required');
  const text = d.diffs[`${a}:${b}`] ?? `--- version ${a}\n+++ version ${b}\n@@ limits @@\n-limits.task_timeout: 900\n+limits.task_timeout: 1200\n limits.max_retries: 3\n`;
  return [200, E.configDiff(a, b, text)];
});
route('GET', `${V}/factory`, () => [200, getFactoryStatus()]);
route('POST', `${V}/factory/pause`, () => {
  factoryState.paused = true;
  factoryState.paused_at = new Date().toISOString();
  pushEvent('factory.paused', {}, false, `factory:${++eventSeq}`);
  return [200, getFactoryStatus()];
});
route('POST', `${V}/factory/resume`, () => {
  factoryState.paused = false;
  factoryState.paused_at = null;
  pushEvent('factory.resumed', {}, false, `factory:${++eventSeq}`);
  return [200, getFactoryStatus()];
});

route('GET', `${V}/projects/{pid}/factory`, (c) => {
  const pid = decodeURIComponent(c.params[0]);
  const snap = db.factory?.[pid] ?? {
    project: pid,
    factory_paused: false,
    who: {},
    activity: [],
    generated_at: '2026-11-21T10:15:02.123456Z',
    stations: ['intake', 'triage', 'spec', 'gate_spec', 'gherkin', 'gate_gherkin', 'build', 'verify', 'report', 'gate_accept', 'knowledge'],
    limits: { driver: 'engine', max_tasks_per_project: 2, max_agents: 4, running_in_project: 0, running_total: 0 },
    runs: [],
    queue: [],
    routing: { problems: [] },
  };
  return [200, snap];
});

route('GET', `${V}/projects/{pid}/tasks`, (c) => {
  const p = page(proj(c.params[0]).runs, c.query);
  return [200, { items: p.items.map(E.runSummary), next: p.next }];
});
route('POST', `${V}/projects/{pid}/tasks`, (c) => {
  const pid = decodeURIComponent(c.params[0]);
  const d = proj(pid);
  const b = body(c);
  const allowed = ['slug', 'request', 'type', 'repos', 'priority', 'tier', 'ticket', 'spec'];
  for (const k of Object.keys(b)) if (!allowed.includes(k)) throw new ApiErr(400, 'E_VALIDATION', `unknown field ${k}`, { field: k });
  for (const k of ['slug', 'request', 'type']) if (!b[k]) throw new ApiErr(400, 'E_VALIDATION', `${k} is required`, { field: k });
  const slug = String(b.slug);
  if (db.runs[`${pid}/${slug}`]) throw new ApiErr(409, 'E_LOCKED', 'slug is in use', { field: 'slug' });
  const template = JSON.parse(JSON.stringify(db.runs[Object.keys(db.runs).find((k) => k.startsWith(`${pid}/`)) ?? 'digital-hr/leave-balance'] ?? db.runs['digital-hr/leave-balance'])) as RunData;
  const now = '2026-11-14T10:00:00Z';
  template.detail = {
    ...template.detail, slug, project: pid, type: String(b.type), tier: typeof b.tier === 'number' ? b.tier : null, initial_tier: null, state: 'CREATED', reason: null,
    execution_status: 'running', acceptance_status: 'pending', request: String(b.request), priority: String(b.priority ?? 'normal'), ticket: typeof b.ticket === 'string' ? b.ticket : null,
    created_at: now, updated_at: now, task_counts: {},
    approvals: { specification: { gate: 'specification', state: 'NOT_REQUESTED', version: null, sha256: null }, gherkin: { gate: 'gherkin', state: 'NOT_REQUESTED', version: null, sha256: null } },
  };
  if (b.spec && typeof b.spec === 'string' && b.spec.trim()) {
    const specSha = createHash('sha256').update(b.spec).digest('hex');
    template.specification = {
      ...template.specification,
      current: {
        ...template.specification.current,
        version: 1,
        sha256: specSha,
        text: b.spec,
        state: 'IN_REVIEW',
        provenance: 'imported from a session',
      },
      versions: [
        {
          version: 1,
          sha256: specSha,
          decision: null,
          reviewer: null,
          channel: null,
          at: null,
          comment: null,
          provenance: 'imported from a session',
        },
      ],
    };
    template.detail.approvals.specification = {
      gate: 'specification',
      state: 'IN_REVIEW',
      version: 1,
      sha256: specSha,
    };
  }
  template.next = { kind: 'orchestrator', label: 'waiting for AI tool', command: `/sentinel resume ${slug}` };
  template.workflow = { nodes: [], edges: [], gates: [] };
  template.tdd = { cycles: [], evidence: [] };
  template.verification = { round: null, rows: [], missing: [], acceptance: { computed: 'pending', reasons: [] }, acceptance_record: null };
  template.trace = { requirements: [], gaps: [], failures: [], acceptance: null };
  template.changes = { repos: [] };
  template.logs = {};
  template.report = null;
  db.runs[`${pid}/${slug}`] = template;
  d.runs.unshift(summary(template.detail));
  return [201, E.run(template.detail, template.next)];
});

const runGet = (suffix: string, pick: (r: RunData, c: Ctx) => unknown) =>
  route('GET', `${V}/tasks/{slug}${suffix}`, (c) => [200, pick(resolveRun(c.params[0], c.query).run, c)]);
const wrun = (r: RunData) => E.run(r.detail, r.next);
route('GET', `${V}/tasks/{slug}`, (c) => [200, wrun(resolveRun(c.params[0], c.query).run)]);
runGet('/next', (r) => E.next(r.next, r.detail));
runGet('/specification', (r) => E.specification(r.specification.current, r.specification.versions, r.detail.state));
route('GET', `${V}/tasks/{slug}/specification/versions/{v}`, (c) => {
  const { run } = resolveRun(c.params[0], c.query);
  const v = c.params[1];
  const answer = String(run.specification.current.version) === v ? run.specification.current : run.specification.oldVersions[v];
  if (!answer) throw new ApiErr(404, 'E_NOT_FOUND', 'version not found');
  return [200, E.specVersion(answer)];
});
runGet('/gherkin', (r) => E.gherkin(r.gherkin, r.detail.state));
runGet('/workflow', (r) => E.workflow(r.workflow, r.detail));
runGet('/tdd', (r) => E.tdd(r.tdd));
runGet('/verification', (r) => E.verification(r));
runGet('/trace', (r) => E.trace(r));
route('GET', `${V}/tasks/{slug}/changes`, (c) => {
  const { run } = resolveRun(c.params[0], c.query);
  return [200, E.changes(run.detail.slug, run.changes)];
});
route('GET', `${V}/tasks/{slug}/changes/diff`, (c) => {
  const { run } = resolveRun(c.params[0], c.query);
  const repo = c.query.get('repo');
  const path = c.query.get('path');
  const mode = c.query.get('mode');
  if (!repo || !path || (mode !== 'inline' && mode !== 'split')) throw new ApiErr(400, 'E_VALIDATION', 'repo, path and mode are required');
  const d = run.diffs[`${repo}:${path}`];
  if (!d) throw new ApiErr(404, 'E_NOT_FOUND', 'file has no diff');
  return [200, E.diff(repo, path, d, mode)];
});
route('GET', `${V}/tasks/{slug}/artifacts/{aid}`, (c) => {
  const a = resolveRun(c.params[0], c.query).run.artifacts[decodeURIComponent(c.params[1])];
  if (!a) throw new ApiErr(404, 'E_NOT_FOUND', 'artifact not found');
  return [200, a];
});
route('GET', `${V}/tasks/{slug}/logs/{tid}`, (c) => {
  const l = resolveRun(c.params[0], c.query).run.logs[decodeURIComponent(c.params[1])];
  if (!l) throw new ApiErr(404, 'E_NOT_FOUND', 'log not found');
  const offsets: number[] = [];
  let total = 0;
  for (const line of l.lines) {
    offsets.push(total);
    total += Buffer.byteLength(line) + 1;
  }
  const off = Number(c.query.get('offset') ?? 0);
  if (!Number.isInteger(off) || off < 0 || (off !== total && !offsets.includes(off))) throw new ApiErr(400, 'E_VALIDATION', 'offset is not a line start', { field: 'offset' });
  const from = off === total ? l.lines.length : offsets.indexOf(off);
  return [200, E.log(decodeURIComponent(c.params[1]), l.lines, total, from, l.running)];
});
route('GET', `${V}/tasks/{slug}/report`, (c) => {
  const { run } = resolveRun(c.params[0], c.query);
  if (!run.report) throw new ApiErr(422, 'E_PRECONDITION', 'the run has no report yet');
  return [200, run.report];
});
route('GET', `${V}/approvals`, (c) => {
  const state = c.query.get('state');
  if (state !== 'IN_REVIEW') throw new ApiErr(400, 'E_VALIDATION', 'state must be IN_REVIEW', { field: 'state' });
  const items = [];
  for (const [key, r] of Object.entries(db.runs)) {
    for (const gate of ['specification', 'gherkin'] as const) {
      const a = r.detail.approvals[gate];
      if (a.state === 'IN_REVIEW') {
        items.push({ artifact_id: `ar-${gate}`, state: 'IN_REVIEW', project: key.split('/')[0], slug: r.detail.slug, gate, version: a.version, sha256: a.sha256, requested_at: gate === 'specification' ? r.specification.current.requested_at : r.gherkin.requested_at });
      }
    }
  }
  return [200, { items, next: null }];
});
route('GET', `${V}/audit`, (c) => {
  const pid = c.query.get('project');
  if (pid && !db.projectData[pid]) throw new ApiErr(404, 'E_NOT_FOUND', 'project not found');
  const rows = Object.entries(db.projectData)
    .filter(([id]) => !pid || id === pid)
    .flatMap(([id, d]) => d.audit.map((a) => E.audit(id, a)));
  const pg = page(rows, c.query);
  return [200, { items: pg.items, next: pg.next }];
});

route('GET', `${V}/notifications`, (c) => {
  const pid = c.query.get('project');
  if (pid && !db.projects.some((p) => p.id === pid)) throw new ApiErr(404, 'E_NOT_FOUND', 'project not found');
  const all = db.notifications.filter((n) => !pid || n.project === pid).sort((a, b) => b.at.localeCompare(a.at) || b.id.localeCompare(a.id));
  const shown = c.query.get('unread') ? all.filter((n) => !n.read_at) : all;
  const pg = page(shown, c.query);
  return [200, { items: pg.items, next: pg.next, unread: all.filter((n) => !n.read_at).length, unavailable: [] }];
});
route('POST', `${V}/notifications/{id}/read`, (c) => {
  const id = c.params[0];
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*:\d+$/.test(id)) throw new ApiErr(400, 'E_VALIDATION', 'bad notification id', { field: 'id' });
  const n = db.notifications.find((x) => x.id === id);
  if (!n) throw new ApiErr(404, 'E_NOT_FOUND', 'no such notification');
  n.read_at ??= '2026-11-14T11:30:00.000000Z';
  return [200, n];
});
route('GET', `${V}/reports/analytics`, (c) => {
  for (const k of c.query.keys()) if (!['project', 'from', 'to'].includes(k)) throw new ApiErr(400, 'E_VALIDATION', `unknown query parameter ${k}`, { field: k });
  const pid = c.query.get('project');
  if (!pid) throw new ApiErr(400, 'E_VALIDATION', 'project is required', { field: 'project' });
  const a = db.analytics[pid];
  if (!a) throw new ApiErr(404, 'E_NOT_FOUND', 'project not found');
  const from = c.query.get('from') || null;
  const to = c.query.get('to') || null;
  for (const [k, v] of [['from', from], ['to', to]] as const) if (v && !/^\d{4}-\d{2}-\d{2}$/.test(v)) throw new ApiErr(400, 'E_VALIDATION', `${k} must be YYYY-MM-DD`, { field: k });
  if (from && to && from > to) throw new ApiErr(400, 'E_VALIDATION', 'from must not be after to', { field: 'from' });
  return [200, { ...a, range: { from, to } }];
});

route('POST', `${V}/tasks/{slug}/approvals`, (c) => {
  const { run } = resolveRun(c.params[0], c.query);
  const b = body(c);
  for (const k of ['gate', 'sha256', 'decision']) if (!(k in b)) throw new ApiErr(400, 'E_VALIDATION', `${k} is required`, { field: k });
  const gate = b.gate as 'specification' | 'gherkin';
  if (gate !== 'specification' && gate !== 'gherkin') throw new ApiErr(400, 'E_VALIDATION', 'bad gate', { field: 'gate' });
  const a = run.detail.approvals[gate];
  if (a.state !== 'IN_REVIEW') throw new ApiErr(409, 'E_TRANSITION', `approval is ${a.state}`);
  if (b.sha256 !== a.sha256) throw new ApiErr(409, 'E_APPROVAL_STALE', 'approval is stale', { current_sha256: a.sha256 });
  if (b.confirmation !== undefined && b.confirmation !== null && b.confirmation !== String(b.sha256).slice(0, 8)) {
    throw new ApiErr(400, 'E_VALIDATION', 'confirmation does not match', { field: 'confirmation' });
  }
  const decision = String(b.decision);
  if (!['approve', 'changes', 'reject'].includes(decision)) throw new ApiErr(400, 'E_VALIDATION', 'bad decision', { field: 'decision' });
  const comment = typeof b.comment === 'string' ? b.comment : null;
  if ((decision === 'changes' || decision === 'reject') && !comment?.trim()) throw new ApiErr(400, 'E_VALIDATION', 'a comment is required', { field: 'comment' });
  const record = { decision, approver: 'dev', channel: 'dashboard', at: '2026-11-14T09:30:00Z', comment };
  run.detail.approvals[gate].record = record;
  const newState = decision === 'approve' ? 'APPROVED' : decision === 'changes' ? 'CHANGES_REQUESTED' : 'REJECTED';
  syncApproval(run, gate, newState);
  const target = gate === 'specification' ? run.specification.current : run.gherkin;
  target.state = newState;
  target.decision = record;
  run.detail.state =
    decision === 'approve' ? (gate === 'specification' ? 'SPECIFICATION_APPROVED' : 'GHERKIN_APPROVED') : decision === 'changes' ? (gate === 'specification' ? 'SPECIFICATION_DRAFT' : 'GHERKIN_DRAFT') : 'CANCELLED';
  return [200, wrun(run)];
});

route('POST', `${V}/tasks/{slug}/acceptance`, (c) => {
  const { run } = resolveRun(c.params[0], c.query);
  const b = body(c);
  for (const k of ['sha256_of_report', 'decision']) if (!(k in b)) throw new ApiErr(400, 'E_VALIDATION', `${k} is required`, { field: k });
  if (run.detail.state !== 'COMPLETED' || run.verification.acceptance_record?.decision === 'reject') throw new ApiErr(409, 'E_TRANSITION', 'the run cannot be accepted now');
  if (!run.report || b.sha256_of_report !== run.report.sha256) throw new ApiErr(409, 'E_APPROVAL_STALE', 'report changed');
  if (b.confirmation !== undefined && b.confirmation !== null && b.confirmation !== String(b.sha256_of_report).slice(0, 8)) {
    throw new ApiErr(400, 'E_VALIDATION', 'confirmation does not match', { field: 'confirmation' });
  }
  if (b.decision === 'accept' && run.verification.acceptance.computed === 'rejected') throw new ApiErr(422, 'E_PRECONDITION', 'the engine rejected this run');
  const comment = typeof b.comment === 'string' ? b.comment : null;
  const record = { decision: String(b.decision), approver: 'dev', channel: 'dashboard', at: '2026-11-14T09:35:00Z', comment };
  run.verification.acceptance_record = record;
  run.detail.acceptance_status = b.decision === 'accept' ? 'accepted' : 'rejected';
  return [200, wrun(run)];
});

route('POST', `${V}/tasks/{slug}/control`, (c) => {
  const { run } = resolveRun(c.params[0], c.query);
  const b = body(c);
  const nodes = run.workflow.nodes;
  switch (b.action) {
    case 'cancel': {
      if (b.task_id) {
        const n = nodes.find((x) => x.id === b.task_id);
        if (!n) throw new ApiErr(404, 'E_NOT_FOUND', 'task not found');
        n.state = 'CANCELLED';
      } else {
        if (['COMPLETED', 'CANCELLED'].includes(run.detail.state)) throw new ApiErr(409, 'E_TRANSITION', `not allowed in state ${run.detail.state}`);
        run.detail.state = 'CANCELLED';
        for (const n of nodes) if (n.state === 'RUNNING' || n.state === 'QUEUED') n.state = 'CANCELLED';
      }
      break;
    }
    case 'resume':
      if (run.detail.state !== 'NEEDS_HUMAN') throw new ApiErr(409, 'E_TRANSITION', `not allowed in state ${run.detail.state}`);
      if (!b.comment) throw new ApiErr(400, 'E_VALIDATION', 'a comment is required', { field: 'comment' });
      run.detail.state = 'EXECUTING';
      run.detail.reason = null;
      break;
    case 'retry': {
      const n = nodes.find((x) => x.id === b.task_id);
      if (!n || n.state !== 'FAILED') throw new ApiErr(409, 'E_TRANSITION', 'only a failed task can be retried');
      nodes.push({ ...n, id: `${n.id}-r${n.attempt + 1}`, state: 'QUEUED', retry_of: n.id, attempt: n.attempt + 1, error_code: null, started_at: null, finished_at: null, seconds: null });
      run.workflow.edges.push({ from: n.id, to: `${n.id}-r${n.attempt + 1}` });
      break;
    }
    default:
      throw new ApiErr(400, 'E_VALIDATION', 'unknown action', { field: 'action' });
  }
  return [200, wrun(run)];
});

route('POST', `${V}/tasks/{slug}/pause`, (c) => {
  const { run } = resolveRun(c.params[0], c.query);
  if (['COMPLETED', 'CANCELLED'].includes(run.detail.state)) {
    throw new ApiErr(409, 'E_TRANSITION', 'the run cannot be paused now');
  }
  for (const f of Object.values(db.factory ?? {})) {
    const r = f.runs.find((x) => x.slug === c.params[0]);
    if (r) {
      r.paused = true;
      if (r.stations[r.station] === 'working') r.stations[r.station] = 'paused';
    }
  }
  pushEvent('run.paused', { slug: c.params[0] });
  return [200, wrun(run)];
});

route('POST', `${V}/tasks/{slug}/unpause`, (c) => {
  const { run } = resolveRun(c.params[0], c.query);
  for (const f of Object.values(db.factory ?? {})) {
    const r = f.runs.find((x) => x.slug === c.params[0]);
    if (r) {
      r.paused = false;
      if (r.stations[r.station] === 'paused') r.stations[r.station] = 'working';
    }
  }
  pushEvent('run.unpaused', { slug: c.params[0] });
  return [200, wrun(run)];
});

route('POST', `${V}/tasks/{slug}/retry-now`, (c) => {
  const { run } = resolveRun(c.params[0], c.query);
  for (const f of Object.values(db.factory ?? {})) {
    const r = f.runs.find((x) => x.slug === c.params[0]);
    if (r && r.limit) {
      r.limit = null;
      if (r.stations[r.station] === 'limit') r.stations[r.station] = 'working';
    }
  }
  return [200, wrun(run)];
});

route('POST', `${V}/tasks/{slug}/note`, (c) => {
  const { run } = resolveRun(c.params[0], c.query);
  const b = body(c);
  if (typeof b.text !== 'string' || !b.text.trim()) {
    throw new ApiErr(400, 'E_VALIDATION', 'text is required', { field: 'text' });
  }
  if (b.text.length > 4000) {
    throw new ApiErr(400, 'E_VALIDATION', 'text exceeds 4000 characters', { field: 'text' });
  }
  for (const f of Object.values(db.factory ?? {})) {
    const r = f.runs.find((x) => x.slug === c.params[0]);
    if (r) {
      r.pending_notes = (r.pending_notes ?? 0) + 1;
    }
  }
  pushEvent('run.note_added', { slug: c.params[0] });
  return [201, { ...wrun(run), note: { text: b.text } }];
});

const handleChatGet = (c: Ctx): [number, unknown] => {
  const { key } = resolveRun(c.params[0], c.query);
  const items = runChats[key] ?? [];
  const runner = ext.orchestrator ?? 'claude';
  return [200, { items, orchestrator: { runner, model: null } }];
};

const handleChatPost = (c: Ctx): [number, unknown] => {
  const { run, key } = resolveRun(c.params[0], c.query);
  const b = body(c) as { text?: string };
  if (typeof b.text !== 'string' || !b.text.trim()) {
    throw new ApiErr(400, 'E_VALIDATION', 'text is required', { field: 'text' });
  }
  if (b.text.length > 4000) {
    throw new ApiErr(400, 'E_VALIDATION', 'text exceeds 4000 characters', { field: 'text' });
  }
  const items = (runChats[key] ??= []);
  if (items.some((it) => it.status === 'pending')) {
    throw new ApiErr(412, 'E_PRECONDITION', 'another orchestrator reply is already pending');
  }
  const userId = 'u-' + Date.now();
  const userItem: { id: string; role: 'user' | 'orchestrator'; text: string; at: string; status: 'done' | 'pending' | 'failed'; error?: string } = {
    id: userId,
    role: 'user',
    text: b.text.trim(),
    at: new Date().toISOString(),
    status: 'done',
  };
  const orchId = 'o-' + (Date.now() + 1);
  const orchItem: { id: string; role: 'user' | 'orchestrator'; text: string; at: string; status: 'done' | 'pending' | 'failed'; error?: string } = {
    id: orchId,
    role: 'orchestrator',
    text: '',
    at: new Date().toISOString(),
    status: 'pending',
  };
  items.push(userItem, orchItem);

  const slug = c.params[0];
  setTimeout(() => {
    if (chatFail) {
      orchItem.status = 'failed';
      orchItem.error = 'orchestrator runner failed';
      pushEvent('chat.message', { slug, id: orchId, role: 'orchestrator', status: 'failed' });
    } else {
      orchItem.status = 'done';
      orchItem.text = `Run ${slug} is currently in state ${run.detail.state}. Actions stay with the human operator.`;
      pushEvent('chat.message', { slug, id: orchId, role: 'orchestrator', status: 'done' });
    }
  }, 100);

  return [202, { user: userItem, orchestrator: orchItem, items: [userItem, orchItem] }];
};

route('GET', `${V}/runs/{slug}/chat`, handleChatGet);
route('POST', `${V}/runs/{slug}/chat`, handleChatPost);

// ---- providers, orchestrator, agents, folders, project creation ----

const installedIds = () => PROVIDERS.filter((p) => ext.installed[p.id]).map((p) => p.id);
const providerList = () => PROVIDERS.map((p) => ({ ...p, installed: !!ext.installed[p.id], path: ext.installed[p.id] ?? null }));
const SLUG = /^[a-z][a-z0-9-]*$/;

route('GET', `${V}/providers`, () => [200, { items: providerList(), orchestrator: ext.orchestrator }]);
route('POST', `${V}/providers/{id}/test`, (c) => {
  const id = c.params[0];
  if (!PROVIDERS.some((p) => p.id === id)) throw new ApiErr(404, 'E_NOT_FOUND', 'unknown provider');
  const ok = !!ext.installed[id];
  return [200, { id, ok, message: ok ? `${id} 1.0.0` : `${id} is not installed` }];
});
route('GET', `${V}/orchestrator`, () => [200, { id: ext.orchestrator, installed_ids: installedIds() }]);
route('PUT', `${V}/orchestrator`, (c) => {
  const b = body(c);
  const id = b.id ?? null;
  if (id !== null && (typeof id !== 'string' || !installedIds().includes(id))) throw new ApiErr(400, 'E_VALIDATION', 'provider is not installed', { field: 'id' });
  ext.orchestrator = id as string | null;
  return [200, { id: ext.orchestrator, installed_ids: installedIds() }];
});

function agentsAnswer(pid: string | null) {
  if (pid) proj(pid);
  const p = pid ? (ext.projects[pid] ??= emptyCfg()) : null;
  const g = ext.global;
  const pick = (role: string) => {
    if (p?.agents[role]) return { role, runner: p.agents[role].runner ?? null, model: p.agents[role].model ?? null, source: 'project' as const };
    if (g.agents[role]) return { role, runner: g.agents[role].runner ?? null, model: g.agents[role].model ?? null, source: 'global' as const };
    return { role, runner: 'claude', model: null, source: 'default' as const };
  };
  const eff = p ?? g;
  return { project: pid, roles: ROLES, items: ROLES.map(pick), providers: eff.providers, single_model: eff.single_model, sha256: p && pid ? cfgSha(pid, p) : cfgSha('global', g) };
}
route('GET', `${V}/agents`, (c) => [200, agentsAnswer(c.query.get('project'))]);
route('PUT', `${V}/agents`, (c) => {
  const b = body(c);
  const scope = b.scope;
  if (scope !== 'project' && scope !== 'global') throw new ApiErr(400, 'E_VALIDATION', 'scope must be project or global', { field: 'scope' });
  const agents = (b.agents ?? {}) as Record<string, { runner?: string; model?: string }>;
  const known = PROVIDERS.map((p) => p.id);
  for (const [role, v] of Object.entries(agents)) {
    if (!ROLES.includes(role)) throw new ApiErr(400, 'E_VALIDATION', `unknown role ${role}`, { field: `agents.${role}` });
    if (v.runner && !known.includes(v.runner)) throw new ApiErr(400, 'E_VALIDATION', `unknown provider ${v.runner}`, { field: `agents.${role}.runner` });
  }
  if (scope === 'global' && b.single_model !== undefined) throw new ApiErr(400, 'E_VALIDATION', 'single_model is a project setting', { field: 'single_model' });
  const pv = (b.providers ?? {}) as { default?: string; fallback?: string[]; disabled?: string[] };
  const cfg = scope === 'global' ? ext.global : (ext.projects[String(b.project)] ??= emptyCfg());
  let pid: string | null = null;
  if (scope === 'project') {
    pid = String(b.project ?? '');
    proj(pid);
    if (typeof b.sha256 === 'string' && b.sha256 !== cfgSha(pid, cfg)) throw new ApiErr(409, 'E_PRECONDITION', 'the configuration file changed since it was read', { fix: 'reload the configuration' });
  }
  cfg.agents = agents;
  cfg.providers = { default: pv.default ?? null, fallback: pv.fallback ?? [], disabled: pv.disabled ?? [] };
  cfg.single_model = b.single_model === true;
  cfg.rev += 1;
  if (pid) {
    const h = db.projectData[pid].history;
    const version = Math.max(0, ...h.items.map((x) => x.version)) + 1;
    h.items.unshift({ version, sha256: cfgSha(pid, cfg), author: 'dev', channel: 'dashboard', at: '2026-11-14T10:30:00Z', comment: null });
  }
  return [200, agentsAnswer(pid)];
});

route('GET', `${V}/profiles`, () => [200, { items: PROFILES }]);

route('GET', `${V}/fs/dirs`, (c) => {
  const path = (c.query.get('path') || '/home/dev').replace(/\/+$/, '') || '/';
  if (path.includes('\0') || !path.startsWith('/')) throw new ApiErr(400, 'E_VALIDATION', 'path must be absolute', { field: 'path' });
  const kids = ext.tree[path];
  if (!kids) throw new ApiErr(404, 'E_NOT_FOUND', 'not a directory');
  const parent = path === '/' ? null : path.slice(0, path.lastIndexOf('/')) || '/';
  const join2 = (n: string) => (path === '/' ? `/${n}` : `${path}/${n}`);
  return [200, { path, parent, items: kids.filter((n) => !n.startsWith('.')).map((n) => ({ name: n, path: join2(n), is_git: ext.git.has(join2(n)) })) }];
});

function addProject(name: string, path: string, repos: { id: string; path: string; role: string; profile: string }[]) {
  let id = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'project';
  while (db.projects.some((p) => p.id === id)) id = `${id}-2`;
  const project = { id, name, path, status: 'available' as const, active_runs: 0 };
  db.projects.push(project);
  const tpl = Object.values(db.projectData)[0];
  const first = tpl ? JSON.parse(JSON.stringify(tpl)) : null;
  const items = repos.map((r) => ({
    id: r.id, path: r.path, remote: null, default_branch: 'main', branch: 'main', role: r.role, profile: r.profile,
    commands: { build: null, test: null, lint: null, typecheck: null, mutate: null }, guidelines: null, validation: [],
  }));
  db.projectData[id] = {
    ...(first ?? { readiness: { default: { workflow: 'default', state: 'ready', items: [], checked_at: '2026-11-14T09:00:00Z' } }, configuration: { sha256: 'e'.repeat(64), values: [] }, diffs: {}, audit: [] }),
    repositories: { items, next: null },
    history: { items: [], next: null },
    runs: [],
    audit: [],
  };
  db.runtime.projects.push(id);
  return project;
}

function repoFrom(b: Record<string, unknown>, used: Set<string>, base: string) {
  const path = String(b.path ?? '');
  if (!path.startsWith('/')) throw new ApiErr(400, 'E_VALIDATION', 'repository path must be absolute', { field: 'path' });
  if (!ext.tree[path.replace(/\/+$/, '') || '/']) throw new ApiErr(400, 'E_VALIDATION', 'repository path is not an existing directory', { field: 'path' });
  const role = String(b.role ?? '');
  if (!SLUG.test(role)) throw new ApiErr(400, 'E_VALIDATION', 'role is required', { field: 'role' });
  let id = typeof b.id === 'string' && b.id ? b.id : (path.split('/').pop() ?? base).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+/, '') || base;
  if (!SLUG.test(id)) throw new ApiErr(400, 'E_VALIDATION', 'repository id must be lower-case letters, digits and hyphens', { field: 'id' });
  if (used.has(id)) {
    if (typeof b.id === 'string' && b.id) throw new ApiErr(409, 'E_PRECONDITION', `repository ${id} already exists`);
    id = `${id}-2`;
  }
  used.add(id);
  const profile = typeof b.profile === 'string' && b.profile ? b.profile : 'generic';
  return { id, path, role, profile };
}

route('POST', `${V}/projects/register`, (c) => {
  const path = String(body(c).path ?? '');
  if (!path.startsWith('/')) throw new ApiErr(400, 'E_VALIDATION', 'path must be absolute', { field: 'path' });
  const existing = db.projects.find((p) => p.path === path);
  if (existing) return [200, E.projects([existing])[0]];
  if (!ext.workspaces.has(path)) throw new ApiErr(404, 'E_NOT_FOUND', 'no sentinel.config.yaml in that folder');
  const name = path.split('/').pop() ?? 'project';
  return [201, E.projects([addProject(name, path, [{ id: 'app', path, role: 'app', profile: 'generic' }])])[0]];
});

route('POST', `${V}/projects`, (c) => {
  const b = body(c);
  const name = String(b.name ?? '').trim();
  const path = String(b.path ?? '').replace(/\/+$/, '');
  if (!name) throw new ApiErr(400, 'E_VALIDATION', 'name is required', { field: 'name' });
  if (!path.startsWith('/')) throw new ApiErr(400, 'E_VALIDATION', 'path must be absolute', { field: 'path' });
  const shared = (b.shared ?? { mode: 'local' }) as { mode?: string; url?: string };
  if (shared.mode !== 'local' && shared.mode !== 'git') throw new ApiErr(400, 'E_VALIDATION', 'shared.mode must be local or git', { field: 'shared.mode' });
  if (shared.mode === 'git' && !shared.url) throw new ApiErr(400, 'E_VALIDATION', 'shared.url is required for git', { field: 'shared.url' });
  const reposIn = Array.isArray(b.repos) ? (b.repos as Record<string, unknown>[]) : [];
  if (reposIn.length < 1) throw new ApiErr(400, 'E_VALIDATION', 'at least one repository is required: the configuration needs a non empty repos list', { field: 'repos' });
  if (ext.workspaces.has(path) || db.projects.some((p) => p.path === path)) throw new ApiErr(409, 'E_PRECONDITION', 'sentinel.config.yaml already exists in that folder', { fix: 'use Register existing folder' });
  const parent = path.slice(0, path.lastIndexOf('/')) || '/';
  if (!ext.tree[path] && !ext.tree[parent]) throw new ApiErr(400, 'E_VALIDATION', 'the parent folder does not exist', { field: 'path' });
  const used = new Set<string>();
  const repos = reposIn.map((r) => repoFrom(r, used, 'repo'));
  if (!ext.tree[path]) {
    ext.tree[path] = [];
    ext.tree[parent].push(path.split('/').pop() ?? '');
  }
  ext.workspaces.add(path);
  const project = addProject(name, path, repos);
  const g = ext.global;
  ext.projects[project.id] = { agents: JSON.parse(JSON.stringify(g.agents)), providers: JSON.parse(JSON.stringify(g.providers)), single_model: g.single_model, rev: 1 };
  return [201, E.projects([project])[0]];
});

route('POST', `${V}/projects/{pid}/repositories`, (c) => {
  const pid = decodeURIComponent(c.params[0]);
  const d = proj(pid);
  const used = new Set(d.repositories.items.map((r) => r.id));
  const r = repoFrom(body(c), used, 'repo');
  d.repositories.items.push({
    id: r.id, path: r.path, remote: null, default_branch: 'main', branch: 'main', role: r.role, profile: r.profile,
    commands: { build: null, test: null, lint: null, typecheck: null, mutate: null }, guidelines: null, validation: [],
  });
  return [201, E.repository(d.repositories.items[d.repositories.items.length - 1])];
});

route('DELETE', `${V}/projects/{pid}`, (c) => {
  const pid = decodeURIComponent(c.params[0]);
  if (!db.projects.some((x) => x.id === pid)) throw new ApiErr(404, 'E_NOT_FOUND', 'project not found');
  const live = Object.entries(db.runs).some(([k, r]) => k.startsWith(`${pid}/`) && !['COMPLETED', 'CANCELLED'].includes(r.detail.state));
  if (live) throw new ApiErr(409, 'E_PRECONDITION', 'a run is not finished', { fix: 'finish or cancel the runs first' });
  db.projects.splice(db.projects.findIndex((x) => x.id === pid), 1);
  delete db.projectData[pid];
  db.runtime.projects = db.runtime.projects.filter((x) => x !== pid);
  return [200, { removed: pid }];
});

route('DELETE', `${V}/projects/{pid}/repositories/{rid}`, (c) => {
  const pid = decodeURIComponent(c.params[0]);
  const d = proj(pid);
  const rid = c.params[1];
  const idx = d.repositories.items.findIndex((r) => r.id === rid);
  if (idx < 0) throw new ApiErr(404, 'E_NOT_FOUND', 'repository not found');
  if (d.repositories.items.length <= 1) throw new ApiErr(409, 'E_PRECONDITION', 'a project needs at least one repository');
  const live = Object.entries(db.runs).some(([k, r]) => k.startsWith(`${pid}/`) && !['COMPLETED', 'CANCELLED'].includes(r.detail.state));
  if (live) throw new ApiErr(409, 'E_PRECONDITION', 'a run is not finished', { fix: 'finish or cancel the runs first' });
  d.repositories.items.splice(idx, 1);
  return [200, { removed: rid }];
});

// ---- W3 Part B routes ----

route('POST', `${V}/detect`, (c) => {
  const b = body(c) as { paths?: string[] };
  const paths = Array.isArray(b?.paths) ? b.paths : [];
  return [200, { items: sampleDetect(paths) }];
});

route('POST', `${V}/shared/test`, (c) => {
  const b = body(c) as { url?: string };
  const url = String(b?.url ?? '').trim();
  if (!url || url.includes('fail') || url.startsWith('bad')) {
    return [200, { ok: false, read: false, write: false, refs: 0, error: 'Could not resolve host: repository not found' }];
  }
  return [200, { ok: true, read: true, write: true, refs: 4 }];
});

route('GET', `${V}/routing/suggest`, () => [200, sampleRoutingSuggest()]);

route('GET', `${V}/projects/{pid}/routing/fix`, (c) => {
  const pid = decodeURIComponent(c.params[0]);
  return [200, routingFix(pid, db.factory?.[pid]?.routing?.problems ?? [])];
});

const projectConfigs: Record<string, ReturnType<typeof sampleConfigForm>> = {};
route('GET', `${V}/projects/{pid}/config/form`, (c) => {
  const pid = decodeURIComponent(c.params[0]);
  projectConfigs[pid] ??= sampleConfigForm(pid);
  return [200, projectConfigs[pid]];
});

route('POST', `${V}/projects/{pid}/config/preview`, (c) => {
  const pid = decodeURIComponent(c.params[0]);
  const b = body(c) as { changes?: { path: string; value: unknown }[] };
  const changes = Array.isArray(b?.changes) ? b.changes : [];
  for (const ch of changes) {
    if (ch.path === 'state.shared_repo') throw new ApiErr(400, 'E_VALIDATION', 'state.shared_repo cannot be modified via config form');
    if (ch.path.endsWith('.path') && ch.path.startsWith('repos')) throw new ApiErr(400, 'E_VALIDATION', 'repository path cannot be modified via config form');
  }
  const diff = changes.map((ch) => `--- sentinel.config.yaml\n+++ sentinel.config.yaml (preview)\n@@ ${ch.path} @@\n+ ${ch.path}: ${JSON.stringify(ch.value)}\n`).join('\n') || '# No changes detected';
  return [200, { project: pid, valid: true, diff, changes }];
});

route('POST', `${V}/projects/{pid}/config/save`, (c) => {
  const pid = decodeURIComponent(c.params[0]);
  const b = body(c) as { changes?: { path: string; value: unknown }[]; comment?: string };
  const changes = Array.isArray(b?.changes) ? b.changes : [];
  const cfg = (projectConfigs[pid] ??= sampleConfigForm(pid));
  for (const ch of changes) {
    for (const sec of cfg.sections) {
      for (const f of sec.fields) {
        if (f.path === ch.path) f.value = ch.value;
      }
    }
  }
  const p = proj(pid);
  if (p?.configuration) {
    for (const ch of changes) {
      const existing = p.configuration.values.find((v: { path: string }) => v.path === ch.path);
      if (existing) {
        existing.value = ch.value;
      } else {
        p.configuration.values.push({
          path: ch.path,
          value: ch.value,
          category: 'Other',
          source: 'project',
        });
      }
      if (ch.path === 'orchestrator' && typeof ch.value === 'object' && ch.value !== null) {
        const orchObj = ch.value as { runner?: string; model?: string | null };
        if (orchObj.runner) {
          const exRunner = p.configuration.values.find((v: { path: string }) => v.path === 'orchestrator.runner');
          if (exRunner) exRunner.value = orchObj.runner;
          else p.configuration.values.push({ path: 'orchestrator.runner', value: orchObj.runner, category: 'Other', source: 'project' });
        }
        const exModel = p.configuration.values.find((v: { path: string }) => v.path === 'orchestrator.model');
        if (exModel) exModel.value = orchObj.model ?? null;
        else p.configuration.values.push({ path: 'orchestrator.model', value: orchObj.model ?? null, category: 'Other', source: 'project' });
      }
    }
  }
  const snap = db.factory?.[pid];
  if (snap) {
    const isOrch = changes.some((ch) => ch.path === 'routing_mode' && ch.value === 'orchestrator');
    if (isOrch) {
      const orchCh = changes.find((ch) => ch.path === 'orchestrator')?.value as { runner?: string; model?: string | null } | undefined;
      const runner = orchCh?.runner ?? 'claude';
      const model = orchCh?.model ?? null;
      for (const st of Object.keys(snap.who)) {
        snap.who[st].runner = runner;
        snap.who[st].model = model;
      }
      snap.routing = { problems: [] };
    }
    if (changes.some((ch) => ch.path === 'single_model' && ch.value === false)) {
      snap.routing = { problems: [] };
    }
  }
  const newSha = createHash('sha256').update(JSON.stringify(cfg)).digest('hex');
  cfg.sha256 = newSha;
  const diff = changes.map((ch) => `+ ${ch.path}: ${JSON.stringify(ch.value)}`).join('\n');
  return [200, { ok: true, project: pid, sha256: newSha, diff }];
});

route('GET', `${V}/projects/{pid}/knowledge/status`, () => {
  return [200, sampleKnowledgeStatus()];
});

route('GET', `${V}/projects/{pid}/knowledge/related`, (c) => {
  const q = (c.query.get('q') || '').trim();
  const limit = Number(c.query.get('limit') || 5);
  return [200, sampleKnowledgeRelated(q, limit)];
});

route('GET', `${V}/projects/{pid}/knowledge/records`, (c) => {
  const filt = c.query.get('filter') || 'all';
  const q = (c.query.get('q') || '').trim().toLowerCase();
  let list = [...SAMPLE_KNOWLEDGE_RECORDS];
  if (filt !== 'all') {
    list = list.filter((r) => r.provenance === filt);
  }
  if (q) {
    list = list.filter((r) =>
      `${r.key} ${r.title ?? ''} ${r.summary ?? ''} ${r.repo ?? ''} ${(r.files ?? []).join(' ')}`.toLowerCase().includes(q)
    );
  }
  const limit = Math.min(50, Math.max(1, Number(c.query.get('limit') || 20)));
  const cursor = Number(c.query.get('cursor') || 0);
  const items = list.slice(cursor, cursor + limit);
  const next = cursor + limit < list.length ? String(cursor + limit) : null;
  return [200, { items, next, total: list.length }];
});

route('GET', `${V}/projects/{pid}/knowledge/records/{key}`, (c) => {
  const key = decodeURIComponent(c.params[1]);
  const rec = SAMPLE_KNOWLEDGE_RECORDS.find((r) => r.key === key);
  if (!rec) throw new ApiErr(404, 'E_NOT_FOUND', `knowledge record ${key} not found`);
  return [200, { key: rec.key, meta: { provenance: rec.provenance, repo: rec.repo, title: rec.title, summary: rec.summary, reached: rec.reached, date: rec.date }, body: rec.body, path: rec.path }];
});

route('GET', `${V}/projects/{pid}/knowledge/ci-template`, (c) => {
  const repo = c.query.get('repo') || 'backend';
  return [200, sampleKnowledgeCiTemplate(repo)];
});

route('POST', `${V}/projects/{pid}/knowledge/ingest`, () => [202, { ok: true, job: 'job-ingest-1', state: 'queued' }]);

route('POST', `${V}/projects/{pid}/knowledge/snapshot`, () => [202, { ok: true, job: 'job-snapshot-1', state: 'queued' }]);

route('POST', `${V}/projects/{pid}/knowledge/backfill/estimate`, (c) => {
  const b = body(c) as { since?: string; repo?: string };
  return [200, { token: 'tok_backfill_estimate_123', estimate: { backend: { develop: 80, main: 40 }, frontend: { develop: 20 } }, total: 140, since: b?.since ?? '3 months', repo: b?.repo ?? null }];
});

route('POST', `${V}/projects/{pid}/knowledge/backfill`, (c) => {
  const b = body(c) as { token?: string };
  if (!b?.token) throw new ApiErr(400, 'E_VALIDATION', 'token is required');
  return [200, { ok: true, job: 'kj-backfill1', state: 'queued', estimated: 140 }];
});

// ---- request handling ----

function matchRule(method: string, path: string, search: string): Rule | undefined {
  for (const r of rules) {
    if (r.method && r.method !== method) continue;
    const full = path + search;
    const ok = r.path.startsWith('re:') ? new RegExp(r.path.slice(3)).test(path) || new RegExp(r.path.slice(3)).test(full) : r.path === path;
    if (!ok) continue;
    if (r.times !== undefined) {
      if (r.times <= 0) continue;
      r.times -= 1;
    }
    return r;
  }
  return undefined;
}

function serveStatic(res: ServerResponse, path: string) {
  const rel = normalize(decodeURIComponent(path)).replace(/^(\.\.[/\\])+/, '');
  let file = join(DIST, rel === '/' || rel === '' ? 'index.html' : rel);
  if (!file.startsWith(DIST) || !existsSync(file) || statSync(file).isDirectory()) {
    if (rel === '/' || rel === '') file = join(DIST, 'index.html');
    else {
      res.writeHead(404, { 'Content-Type': 'text/plain', ...SECURITY });
      return void res.end('not found');
    }
  }
  const types: Record<string, string> = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml' };
  res.writeHead(200, { 'Content-Type': types[extname(file)] ?? 'application/octet-stream', ...SECURITY });
  res.end(readFileSync(file));
}

function parseCookie(h: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of (h ?? '').split(';')) {
    const i = part.indexOf('=');
    if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://localhost');
  const path = url.pathname;
  const method = req.method ?? 'GET';
  if (path.startsWith('/__control/')) return void (await control(req, res, path.slice('/__control/'.length)));

  const raw = method === 'POST' || method === 'PUT' || method === 'DELETE' ? await readBody(req) : null;
  const headers: Record<string, string> = {};
  for (const [k, v] of Object.entries(req.headers)) headers[k] = Array.isArray(v) ? v.join(', ') : (v ?? '');
  log.push({ n: log.length, t: Date.now(), method, path, search: url.search, headers, body: raw });

  const rule = matchRule(method, path, url.search);
  if (rule) {
    if (rule.drop) return void req.socket.destroy();
    if (rule.hang) {
      req.on('close', () => undefined);
      return;
    }
    if (rule.delayMs) await new Promise((r) => setTimeout(r, rule.delayMs));
    if (!rule.passthrough) {
      if (rule.rawBody !== undefined) {
        res.writeHead(rule.status ?? 200, { 'Content-Type': rule.contentType ?? 'text/plain', ...SECURITY });
        return void res.end(rule.rawBody);
      }
      return send(res, rule.status ?? 200, rule.body ?? {});
    }
  }

  if (path === '/auth') {
    if (url.searchParams.get('t') !== TOKEN) return sendError(res, new ApiErr(401, 'E_AUTH', 'bad token'));
    res.writeHead(302, { Location: '/', 'Set-Cookie': `sentinel_session=${SESSION}; HttpOnly; SameSite=Strict; Path=/`, 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', ...SECURITY });
    return void res.end();
  }

  if (!path.startsWith('/api/')) return serveStatic(res, path);

  // the checks of the real server: only the own Host and, when present, the own Origin
  if (headers.host !== `127.0.0.1:${PORT}` && headers.host !== `localhost:${PORT}`) return sendError(res, new ApiErr(403, 'E_HOST', 'unexpected Host header'));
  if (headers.origin && headers.origin !== `http://${headers.host}`) return sendError(res, new ApiErr(403, 'E_ORIGIN', 'unexpected Origin header'));

  if (parseCookie(req.headers.cookie).sentinel_session !== SESSION) return sendError(res, new ApiErr(401, 'E_AUTH', 'authentication required'));

  if (path === '/api/v1/events') {
    if (Date.now() < refuseUntil) return sendError(res, new ApiErr(503, 'E_INTERNAL', 'stream refused'));
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', Connection: 'keep-alive', ...SECURITY });
    res.write(': connected\n\n');
    streams.add(res);
    req.on('close', () => streams.delete(res));
    return;
  }

  try {
    if (method === 'POST' || method === 'PUT' || method === 'DELETE') {
      if (headers['x-sentinel-csrf'] !== CSRF) throw new ApiErr(403, 'E_CSRF', 'bad csrf value');
      if (!/^application\/json/.test(headers['content-type'] ?? '')) throw new ApiErr(415, 'E_MEDIA_TYPE', 'JSON required');
    }
    for (const [m, re, h] of routes) {
      if (m !== method) continue;
      const match = re.exec(path);
      if (!match) continue;
      const [status, out] = h({ params: match.slice(1).map((s) => decodeURIComponent(s)), query: url.searchParams, body: raw });
      return send(res, status, out);
    }
    throw new ApiErr(404, 'E_NOT_FOUND', 'no such route');
  } catch (e) {
    if (e instanceof ApiErr) return sendError(res, e);
    return sendError(res, new ApiErr(500, 'E_INTERNAL', 'internal error'));
  }
});

heartbeat = setInterval(() => {
  for (const s of streams) s.write(': heartbeat\n\n');
}, 5000);
void heartbeat;

server.listen(PORT, '127.0.0.1', () => {
  console.log(`fake API on http://127.0.0.1:${PORT}`);
});
