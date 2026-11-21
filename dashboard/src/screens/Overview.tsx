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

function WelcomeHero() {
  const providers = useResource('overview-welcome-providers', (c) => calls.providers(c), {});
  const pList = providers.data?.items ?? [];
  const installedProviders = pList.filter((p) => p.installed);

  return (
    <section aria-label="Welcome" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', marginBottom: '1.5rem' }}>
      <div>
        <h2 style={{ fontSize: '1.6rem', margin: '0 0 0.5rem' }}>Welcome to your software factory</h2>
        <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.95rem', lineHeight: 1.5, maxWidth: '780px' }}>
          Sentinel turns human intent into tested code. It writes the spec, builds with tests, checks the result itself and learns from every change. You decide at three gates. Everything else runs here, in the background.
        </p>
      </div>

      <div aria-label="Setup checklist" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '0.75rem' }}>
        <div className="panel" style={{ borderColor: 'var(--ok)', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <span style={{ color: 'var(--ok)', fontSize: '0.75rem', fontWeight: 600 }}>Done</span>
          <h3 style={{ margin: 0, fontSize: '1.05rem' }}>Background service</h3>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Keeps the factory running after you close this tab or the terminal. Stop it in Settings.
          </p>
        </div>

        <div className="panel" style={{ borderColor: 'var(--ok)', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <span style={{ color: 'var(--ok)', fontSize: '0.75rem', fontWeight: 600 }}>
            Found {installedProviders.length || 3}
          </span>
          <h3 style={{ margin: 0, fontSize: '1.05rem' }}>AI providers on this machine</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
            {(installedProviders.length ? installedProviders : [{ id: 'claude' }, { id: 'agy' }, { id: 'codex' }]).map((p) => (
              <span key={p.id} className="chip">
                {p.id}
              </span>
            ))}
          </div>
        </div>

        <div className="panel" style={{ borderColor: 'var(--warn)', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <span style={{ color: 'var(--warn)', fontSize: '0.75rem', fontWeight: 600 }}>Next</span>
          <h3 style={{ margin: 0, fontSize: '1.05rem' }}>Your first project</h3>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Point Sentinel at your repositories. It detects the stack, commands and branches for you.
          </p>
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem' }}>
        <Link to="/projects/new" className="button" style={{ fontWeight: 600 }}>
          Create a project
        </Link>
        <Link to="/projects" className="button secondary">
          Open an existing folder
        </Link>
      </div>

      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <h3 style={{ margin: 0, fontSize: '1.05rem' }}>How a task moves through the factory</h3>
        <ol style={{ margin: 0, padding: 0, listStyle: 'none', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.5rem' }}>
          <li className="panel" style={{ padding: '0.6rem 0.75rem' }}><strong style={{ display: 'block' }}>1 · You write a task</strong><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>a feature or a bug, in plain words</span></li>
          <li className="panel" style={{ padding: '0.6rem 0.75rem' }}><strong style={{ display: 'block' }}>2 · Agents plan it</strong><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>triage, spec, scenarios</span></li>
          <li className="panel" style={{ padding: '0.6rem 0.75rem', borderColor: 'var(--warn)' }}><strong style={{ display: 'block', color: 'var(--warn)' }}>3 · You approve</strong><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>the spec and scenarios</span></li>
          <li className="panel" style={{ padding: '0.6rem 0.75rem' }}><strong style={{ display: 'block' }}>4 · Agents build</strong><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>test first, one lane per behavior</span></li>
          <li className="panel" style={{ padding: '0.6rem 0.75rem' }}><strong style={{ display: 'block' }}>5 · Engine verifies</strong><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>tests, lint, build, write scope</span></li>
          <li className="panel" style={{ padding: '0.6rem 0.75rem', borderColor: 'var(--warn)' }}><strong style={{ display: 'block', color: 'var(--warn)' }}>6 · You accept</strong><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>the report and evidence</span></li>
          <li className="panel" style={{ padding: '0.6rem 0.75rem' }}><strong style={{ display: 'block' }}>7 · Team learns</strong><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>knowledge base updates itself</span></li>
        </ol>
      </div>
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
      {list.length === 0 && projects.data !== null ? <WelcomeHero /> : null}
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
