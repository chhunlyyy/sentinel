import type { ReactNode } from 'react';
import { calls } from '../api/calls.ts';
import type { Health, Project } from '../api/types.ts';
import { Link, enc } from '../router.tsx';
import { useResource } from '../state/app.tsx';
import { READINESS_LABEL, readinessAllowsTasks } from '../components/ReadinessPanel.tsx';

function installationSummary(h: Health): string {
  const failed = h.checks.filter((c) => c.required && c.status === 'failed');
  if (failed.length) return `Not ready: ${failed.length} required check${failed.length === 1 ? '' : 's'} failed`;
  const warn = h.checks.filter((c) => c.status !== 'passed');
  return warn.length ? 'Ready with warnings' : 'Ready';
}

type StepState = 'done' | 'current' | 'todo';

function Step({ id, title, state, children }: { id: string; title: string; state: StepState; children?: ReactNode }) {
  return (
    <li data-testid={`step-${id}`} data-state={state}>
      <strong>{title}</strong> <span className="hint">{state === 'done' ? 'Done' : state === 'current' ? 'Current' : 'To do'}</span>
      {children ? <div>{children}</div> : null}
    </li>
  );
}

function FirstRunGuide({ projects }: { projects: Project[] }) {
  const health = useResource('overview-health', (c) => calls.health(c), {});
  const install = useResource('overview-installation', (c) => calls.installation(c), {});
  const first = projects.find((p) => p.status === 'available');
  const pid = first?.id ?? '';
  const readiness = useResource(`guide-readiness-${pid}`, (c) => calls.readiness(c, pid), { project: pid }, !!first);
  const repos = useResource(`guide-repos-${pid}`, (c) => calls.repositories(c, pid), { project: pid }, !!first);
  const runs = useResource(`guide-runs-${pid}`, (c) => calls.runs(c, pid), { project: pid }, !!first);

  const installDone = !!install.data;
  const failed = health.data ? health.data.checks.filter((c) => c.required && c.status === 'failed') : null;
  const healthDone = !!health.data && failed!.length === 0;
  const projectDone = !!first;
  const reposDone = (repos.data?.items.length ?? 0) > 0;
  const ready = !!readiness.data && readinessAllowsTasks(readiness.data.state);
  const configureDone = projectDone && ready;
  const taskDone = (runs.data?.items.length ?? 0) > 0;
  const flags = [installDone, healthDone, projectDone, reposDone, configureDone, configureDone, taskDone];
  const currentIndex = flags.findIndex((f) => !f);
  const st = (i: number): StepState => (flags[i] ? 'done' : i === currentIndex ? 'current' : 'todo');
  const problems = readiness.data?.items.filter((i) => i.status !== 'passed' && i.status !== 'not_checked' && i.status !== 'unknown') ?? [];
  const commands = (
    <>
      Run <code>sentinel init</code> or <code>sentinel dashboard</code> in the workspace, then edit <code>sentinel.config.yaml</code>.
    </>
  );
  return (
    <section data-testid="first-run-guide">
      <h2>Getting started</h2>
      <ol className="steps">
        <Step id="installation" title="Installation" state={st(0)}>
          {install.data ? `Sentinel ${install.data.version} at ${install.data.path}` : 'Not read yet'}
        </Step>
        <Step id="health" title="Health" state={st(1)}>
          {health.data ? installationSummary(health.data) : 'Not read yet'}
        </Step>
        <Step id="create-project" title="Create project" state={st(2)}>
          {projectDone ? `Project ${first!.name}` : commands}
        </Step>
        <Step id="add-repositories" title="Add repositories" state={st(3)}>
          {reposDone ? `${repos.data!.items.length} repositories` : commands}
        </Step>
        <Step id="configure" title="Configure" state={st(4)}>
          {configureDone ? 'Configured' : problems.length ? (
            <ul className="plain">
              {problems.map((p) => (
                <li key={`${p.id}-${p.repo ?? ''}`}>
                  {p.id}
                  {p.repo ? ` (${p.repo})` : ''}: {p.message ?? p.status}
                  {p.fix ? <> Fix: <code>{p.fix}</code></> : null}
                </li>
              ))}
            </ul>
          ) : commands}
        </Step>
        <Step id="readiness" title="Readiness" state={st(5)}>
          {readiness.data ? READINESS_LABEL[readiness.data.state] : 'Not checked'}
        </Step>
        <Step id="first-task" title="First task" state={st(6)}>
          {configureDone && !taskDone ? <Link to="/tasks/new">Create task</Link> : taskDone ? 'Created' : 'Offered when readiness is Ready or Ready with warnings'}
        </Step>
      </ol>
    </section>
  );
}

export function Overview() {
  const projects = useResource('projects', (c) => calls.projects(c), {});
  const health = useResource('overview-summary-health', (c) => calls.health(c), {});
  const approvals = useResource('overview-approvals', (c) => calls.approvals(c), {});
  const list = projects.data?.items ?? [];
  const firstRuns = useResource('overview-runs', async (c) => {
    const page = await calls.projects(c);
    const out = [];
    for (const p of page.items.filter((x) => x.status === 'available')) {
      const r = await calls.runs(c, p.id);
      out.push(...r.items.map((i) => ({ ...i, project: p.id })));
    }
    return out;
  }, {});
  const runs = firstRuns.data ?? [];
  const guideNeeded = projects.data !== null && (list.length === 0 || runs.length === 0);

  return (
    <section>
      <h1>Overview</h1>
      <div className="panel" data-testid="installation-summary">
        {health.data ? installationSummary(health.data) : health.error ? 'Connection unavailable' : 'Loading'}
      </div>
      {guideNeeded ? <FirstRunGuide projects={list} /> : null}
      <h2>Waiting for you</h2>
      <p>
        {approvals.data ? (
          approvals.data.items.length ? <Link to="/approvals">{approvals.data.items.length} approvals waiting</Link> : 'Nothing waits for your approval'
        ) : (
          'Loading'
        )}
      </p>
      {list.length ? (
        <>
          <h2>Projects</h2>
          <ul>
            {list.map((p) => (
              <li key={p.id}>
                <Link to={`/projects/${enc(p.id)}`}>{p.name}</Link> {p.status === 'unavailable' ? `Unavailable: ${p.reason ?? ''}` : `${p.active_runs} active runs`}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
