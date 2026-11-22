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
  const providerNames = installedProviders.length ? installedProviders.map((p) => p.id) : ['claude', 'agy', 'codex'];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '28px', margin: '20px 0' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--text-muted)' }}>
          uv tool install sentinel-pipeline · sentinel dashboard
        </span>
        <h2 style={{ margin: 0, fontFamily: 'var(--font-heading)', fontSize: '38px', lineHeight: 1.15, fontWeight: 700 }}>
          Welcome to your software factory
        </h2>
        <p style={{ margin: 0, maxWidth: '680px', fontSize: '16px', color: '#C5CDD5', lineHeight: 1.5 }}>
          Sentinel runs your AI agents as one team: it sizes each task, writes the spec, builds with tests, checks the result itself and learns from every change. You decide at three gates. Everything else runs here, in the background.
        </p>
      </div>

      <section aria-label="Setup checklist" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px' }}>
        <div style={{ padding: '18px', borderRadius: '14px', border: '1px solid #2E8C81', background: '#122A28', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span style={{ fontSize: '12px', fontWeight: 600, color: '#7FE3D7' }}>Done</span>
          <h3 style={{ margin: 0, fontSize: '17px', fontFamily: 'var(--font-heading)', color: '#E6EAEE' }}>Background service</h3>
          <p style={{ margin: 0, color: '#C5CDD5', fontSize: '13px' }}>Keeps the factory running after you close this tab or the terminal. Stop it in Settings.</p>
        </div>
        <div style={{ padding: '18px', borderRadius: '14px', border: '1px solid #2E8C81', background: '#122A28', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span style={{ fontSize: '12px', fontWeight: 600, color: '#7FE3D7' }}>Found {providerNames.length}</span>
          <h3 style={{ margin: 0, fontSize: '17px', fontFamily: 'var(--font-heading)', color: '#E6EAEE' }}>AI providers on this machine</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {providerNames.map((name) => (
              <span key={name} style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', padding: '3px 8px', borderRadius: '6px', background: '#1F2730', color: '#E6EAEE' }}>
                {name}
              </span>
            ))}
          </div>
        </div>
        <div style={{ padding: '18px', borderRadius: '14px', border: '1px solid #B8862F', background: '#2A2212', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span style={{ fontSize: '12px', fontWeight: 600, color: '#F5C776' }}>Next</span>
          <h3 style={{ margin: 0, fontSize: '17px', fontFamily: 'var(--font-heading)', color: '#E6EAEE' }}>Your first project</h3>
          <p style={{ margin: 0, color: '#C5CDD5', fontSize: '13px' }}>Point Sentinel at your repositories. It detects the stack, commands and branches for you.</p>
        </div>
      </section>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
        <Link to="/projects/new" style={{ display: 'inline-flex', alignItems: 'center', minHeight: '48px', padding: '0 22px', borderRadius: '12px', background: '#4FD1C1', color: '#062420', fontWeight: 600, textDecoration: 'none', fontSize: '15px' }}>
          Create a project
        </Link>
        <Link to="/projects" style={{ display: 'inline-flex', alignItems: 'center', minHeight: '48px', padding: '0 22px', borderRadius: '12px', border: '1px solid #3A4654', color: '#E6EAEE', fontWeight: 600, textDecoration: 'none', fontSize: '15px', background: '#1C242D' }}>
          Open an existing folder
        </Link>
      </div>

      <section aria-label="How the factory works" style={{ padding: '22px', borderRadius: '16px', border: '1px solid #26303A', background: '#141A21', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <h3 style={{ margin: 0, fontFamily: 'var(--font-heading)', fontSize: '18px', color: '#E6EAEE' }}>How a task moves through the factory</h3>
        <ol style={{ margin: 0, padding: 0, listStyle: 'none', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px' }}>
          <li style={{ padding: '12px', borderRadius: '10px', background: '#171D24' }}>
            <strong style={{ display: 'block', color: '#E6EAEE' }}>1 · You write a task</strong>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>a feature or a bug, in plain words</span>
          </li>
          <li style={{ padding: '12px', borderRadius: '10px', background: '#171D24' }}>
            <strong style={{ display: 'block', color: '#E6EAEE' }}>2 · Agents plan it</strong>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>triage, spec, scenarios</span>
          </li>
          <li style={{ padding: '12px', borderRadius: '10px', background: '#2A2212' }}>
            <strong style={{ display: 'block', color: '#F5C776' }}>3 · You approve</strong>
            <span style={{ fontSize: '12px', color: '#C5CDD5' }}>the spec and the scenarios</span>
          </li>
          <li style={{ padding: '12px', borderRadius: '10px', background: '#171D24' }}>
            <strong style={{ display: 'block', color: '#E6EAEE' }}>4 · Agents build</strong>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>test first, one lane per behavior</span>
          </li>
          <li style={{ padding: '12px', borderRadius: '10px', background: '#171D24' }}>
            <strong style={{ display: 'block', color: '#E6EAEE' }}>5 · Engine verifies</strong>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>tests, lint, build, write scope</span>
          </li>
          <li style={{ padding: '12px', borderRadius: '10px', background: '#2A2212' }}>
            <strong style={{ display: 'block', color: '#F5C776' }}>6 · You accept</strong>
            <span style={{ fontSize: '12px', color: '#C5CDD5' }}>the report and evidence</span>
          </li>
          <li style={{ padding: '12px', borderRadius: '10px', background: '#171D24' }}>
            <strong style={{ display: 'block', color: '#E6EAEE' }}>7 · Team learns</strong>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>knowledge base updates itself</span>
          </li>
        </ol>
      </section>
    </div>
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
    <section style={{ maxWidth: '1080px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <h1 style={{ margin: 0, fontFamily: 'var(--font-heading)', fontSize: '28px' }}>Overview</h1>
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
