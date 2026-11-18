import * as A from './adapt.ts';
import type { Client } from './client.ts';
import { buildPath } from './routes.ts';
import type * as T from './types.ts';
import type * as O from './orchestration.ts';
import type * as W from './wire.ts';

// Typed wrappers over the route table. Run routes always carry ?project= so a slug used in two projects is unambiguous.
// Each call reads the answer of the real server (wire.ts) and returns the view model of the screens (types.ts).

const proj = (project: string) => ({ project });
const page = <W1, V>(p: T.Page<W1>, f: (w: W1) => V): T.Page<V> => ({ items: p.items.map(f), next: p.next });

export const calls = {
  installation: async (c: Client) => A.installation(await c.get<W.WInstallation>(buildPath('installation'))),
  runtime: async (c: Client) => A.runtime(await c.get<W.WRuntime>(buildPath('runtime'))),
  health: async (c: Client) => A.health(await c.get<W.WHealth>(buildPath('health'))),
  projects: (c: Client) => c.get<T.Page<T.Project>>(buildPath('projects')),
  readiness: async (c: Client, pid: string, workflow?: string) => A.readiness(await c.get<W.WReadiness>(buildPath('readiness', { pid }, { workflow }))),
  repositories: async (c: Client, pid: string) => page(await c.get<T.Page<W.WRepository>>(buildPath('repositories', { pid })), A.repository),
  configuration: async (c: Client, pid: string) => A.configuration(await c.get<W.WConfiguration>(buildPath('configuration', { pid }))),
  configHistory: async (c: Client, pid: string) => page(await c.get<T.Page<W.WConfigVersion>>(buildPath('configHistory', { pid })), A.configVersion),
  configDiff: (c: Client, pid: string, a: string, b: string) => c.get<W.WConfigDiff>(buildPath('configDiff', { pid }, { a, b })),
  runs: (c: Client, pid: string, cursor?: string | null) => c.get<T.Page<T.RunSummary>>(buildPath('runs', { pid }, { limit: 50, cursor })),
  createRun: async (c: Client, pid: string, body: unknown) => A.run(await c.post<W.WRun>(buildPath('createRun', { pid }), body)),
  run: async (c: Client, slug: string, project: string) => A.run(await c.get<W.WRun>(buildPath('run', { slug }, proj(project)))),
  next: async (c: Client, slug: string, project: string) => {
    const w = await c.get<W.WNext>(buildPath('next', { slug }, proj(project)));
    return A.next(w, w.state) ?? { kind: 'wait' as const, label: 'Nothing to do' };
  },
  specification: async (c: Client, slug: string, project: string) => A.specification(await c.get<W.WSpecification>(buildPath('specification', { slug }, proj(project)))),
  specificationVersion: async (c: Client, slug: string, project: string, v: number | string) => {
    const [version, current] = await Promise.all([
      c.get<W.WSpecVersion>(buildPath('specificationVersion', { slug, v }, proj(project))),
      c.get<W.WSpecification>(buildPath('specification', { slug }, proj(project))),
    ]);
    return A.specificationVersion(version, current);
  },
  gherkin: async (c: Client, slug: string, project: string) => A.gherkin(await c.get<W.WGherkin>(buildPath('gherkin', { slug }, proj(project)))),
  workflow: async (c: Client, slug: string, project: string) => A.workflow(await c.get<W.WWorkflow>(buildPath('workflow', { slug }, proj(project)))),
  tdd: async (c: Client, slug: string, project: string) => {
    const [t, wf, v] = await Promise.all([
      c.get<W.WTdd>(buildPath('tdd', { slug }, proj(project))),
      c.get<W.WWorkflow>(buildPath('workflow', { slug }, proj(project))),
      c.get<W.WVerification>(buildPath('verification', { slug }, proj(project))),
    ]);
    return A.tdd(t, wf, v);
  },
  verification: async (c: Client, slug: string, project: string) => {
    const [v, t, wf] = await Promise.all([
      c.get<W.WVerification>(buildPath('verification', { slug }, proj(project))),
      c.get<W.WTdd>(buildPath('tdd', { slug }, proj(project))),
      c.get<W.WWorkflow>(buildPath('workflow', { slug }, proj(project))),
    ]);
    return A.verification(v, t, wf);
  },
  trace: async (c: Client, slug: string, project: string) => {
    const [t, tdd, v, ch] = await Promise.all([
      c.get<W.WTrace>(buildPath('trace', { slug }, proj(project))),
      c.get<W.WTdd>(buildPath('tdd', { slug }, proj(project))),
      c.get<W.WVerification>(buildPath('verification', { slug }, proj(project))),
      c.get<W.WChanges>(buildPath('changes', { slug }, proj(project))),
    ]);
    return A.trace(t, tdd, v, ch);
  },
  changes: async (c: Client, slug: string, project: string) => A.changes(await c.get<W.WChanges>(buildPath('changes', { slug }, proj(project)))),
  changeDiff: async (c: Client, slug: string, project: string, repo: string, path: string, mode: 'inline' | 'split') =>
    A.diff(await c.get<W.WDiff>(buildPath('changeDiff', { slug }, { repo, path, mode, project }))),
  artifact: (c: Client, slug: string, project: string, aid: string) => c.get<{ content: string; sha256: string }>(buildPath('artifact', { slug, aid }, proj(project))),
  log: (c: Client, slug: string, project: string, tid: string, offset: number) => c.get<W.WLog>(buildPath('log', { slug, tid }, { offset, project })),
  report: async (c: Client, slug: string, project: string) => A.report(await c.get<W.WReport>(buildPath('report', { slug }, { format: 'json', project }))),
  approvals: (c: Client) => c.get<T.Page<W.WApprovalItem>>(buildPath('approvals', {}, { state: 'IN_REVIEW' })),
  audit: async (c: Client, project: string, cursor?: string | null) => page(await c.get<T.Page<W.WAudit>>(buildPath('audit', {}, { project, limit: 50, cursor })), A.audit),
  notifications: (c: Client) => c.get<W.WNotifications>(buildPath('notifications', {}, { limit: 50 })),
  markNotificationRead: (c: Client, id: string) => c.post<W.WNotification>(buildPath('notificationRead', { id }), {}),
  analytics: (c: Client, project: string, from: string, to: string) => c.get<W.WAnalytics>(buildPath('analytics', {}, { project, from, to })),
  decide: async (c: Client, slug: string, project: string, body: { gate: 'specification' | 'gherkin' } & Record<string, unknown>) =>
    A.decision(await c.post<W.WRun>(buildPath('decide', { slug }, proj(project)), body), body.gate),
  accept: async (c: Client, slug: string, project: string, body: { decision: string; comment?: string | null } & Record<string, unknown>) =>
    A.acceptance(await c.post<W.WRun>(buildPath('accept', { slug }, proj(project)), body)),
  control: async (c: Client, slug: string, project: string, body: unknown) => A.run(await c.post<W.WRun>(buildPath('control', { slug }, proj(project)), body)),
  providers: (c: Client, project?: string) => c.get<O.ProvidersAnswer>(buildPath('providers', {}, { project })),
  providerTest: (c: Client, id: string) => c.post<O.ProbeResult>(buildPath('providerTest', { id }), {}),
  orchestrator: (c: Client) => c.get<O.OrchestratorAnswer>(buildPath('orchestrator')),
  setOrchestrator: (c: Client, id: string | null) => c.put<O.OrchestratorAnswer>(buildPath('setOrchestrator'), { id }),
  agents: (c: Client, project?: string) => c.get<O.AgentsAnswer>(buildPath('agents', {}, { project })),
  saveAgents: (c: Client, body: O.SaveAgentsBody) => c.put<O.AgentsAnswer>(buildPath('saveAgents'), body),
  fsDirs: (c: Client, path?: string) => c.get<O.DirsAnswer>(buildPath('fsDirs', {}, { path })),
  profiles: (c: Client) => c.get<{ items: O.ProfileItem[] }>(buildPath('profiles')),
  createProject: (c: Client, body: O.CreateProjectBody) => c.post<T.Project>(buildPath('createProject'), body),
  registerProject: (c: Client, path: string) => c.post<T.Project>(buildPath('registerProject'), { path }),
  addRepository: (c: Client, pid: string, body: O.NewRepo) => c.post<unknown>(buildPath('addRepository', { pid }), body),
  deleteProject: (c: Client, pid: string) => c.del<unknown>(buildPath('deleteProject', { pid })),
  removeRepository: (c: Client, pid: string, rid: string) => c.del<unknown>(buildPath('removeRepository', { pid, rid })),
};
