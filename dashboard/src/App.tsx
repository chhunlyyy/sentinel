import { Component, useEffect, useRef, type ReactNode } from 'react';
import { calls } from './api/calls.ts';
import { AppProvider, useApp, useResource } from './state/app.tsx';
import { Link, enc, segments, useRoute, type Route } from './router.tsx';
import { Overview } from './screens/Overview.tsx';
import { ProjectsScreen, ProjectScreen } from './screens/Projects.tsx';
import { NewProjectScreen } from './screens/NewProject.tsx';
import { KnowledgeScreen } from './screens/Knowledge.tsx';
import { TasksScreen, RunsScreen, QualityScreen, CreateTaskScreen } from './screens/Tasks.tsx';
import { ApprovalsScreen } from './screens/Approvals.tsx';
import { RunScreen } from './screens/Run.tsx';
import { SettingsScreen } from './screens/Settings.tsx';
import { ReportsScreen } from './screens/Reports.tsx';
import { FloorScreen } from './screens/Floor.tsx';
import { NotificationBell } from './components/Notifications.tsx';
import { onOrchestratorChanged } from './state/orchestrator.ts';

function NotFound({ message }: { message: string }) {
  return (
    <section>
      <h1>{message}</h1>
      <p>
        <Link to="/">Overview</Link>
      </p>
    </section>
  );
}

function SessionEnded() {
  return (
    <main id="main" tabIndex={-1}>
      <h1>Session ended</h1>
      <p>Run sentinel dashboard in a terminal to open a new session</p>
      <p className="hint">This page sends nothing more until it is reloaded.</p>
    </main>
  );
}

function DefaultLanding() {
  const projects = useResource('landing-projects', (c) => calls.projects(c), {});
  if (projects.loading && !projects.data) {
    return <FloorScreen />;
  }
  const hasProjects = (projects.data?.items.filter((p) => p.status === 'available').length ?? 0) > 0;
  return hasProjects ? <FloorScreen /> : <Overview />;
}

function DefaultKnowledge() {
  const projects = useResource('knowledge-nav-projects', (c) => calls.projects(c), {});
  const firstPid = projects.data?.items.find((p) => p.status === 'available')?.id;
  if (firstPid) return <KnowledgeScreen pid={firstPid} />;
  return (
    <section>
      <h1>Knowledge</h1>
      <p>No projects available. <Link to="/projects/new">Create a project</Link> first.</p>
    </section>
  );
}

function screenFor(route: Route): ReactNode {
  const s = segments(route.path);
  if (s.length === 0) return <DefaultLanding />;
  switch (s[0]) {
    case 'overview':
      return <Overview />;
    case 'floor':
      return <FloorScreen />;
    case 'knowledge':
      return <DefaultKnowledge />;
    case 'projects':
      if (s.length === 1) return <ProjectsScreen />;
      if (s[1] === 'new' && s.length === 2) return <NewProjectScreen />;
      if (s[2] === 'floor') return <FloorScreen pid={s[1]} />;
      if (s[2] === 'knowledge') return <KnowledgeScreen pid={s[1]} />;
      if (s[2] === 'runs' && s[3]) return <RunScreen pid={s[1]} slug={s[3]} rest={s.slice(4)} route={route} />;
      return <ProjectScreen pid={s[1]} tab={s[2] ?? ''} rest={s.slice(3)} route={route} />;
    case 'tasks':
      if (s[1] === 'new') return <CreateTaskScreen route={route} />;
      return s.length === 1 ? <TasksScreen /> : <NotFound message="Page not found" />;
    case 'approvals':
      return <ApprovalsScreen />;
    case 'runs':
      return <RunsScreen />;
    case 'quality':
      return <QualityScreen />;
    case 'reports':
      return <ReportsScreen />;
    case 'settings':
      return <SettingsScreen page={s[1] ?? 'installation'} />;
    default:
      return <NotFound message="Page not found" />;
  }
}

/** A screen that throws must not blank the page: the shell and the menu stay, the screen shows a plain message. */
export class ScreenBoundary extends Component<{ children: ReactNode; resetKey: string }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.failed) this.setState({ failed: false });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <section data-testid="screen-error">
        <h1>This page could not be shown</h1>
        <p className="banner danger" role="alert">The answer of the server did not have the expected form. Nothing was changed.</p>
        <p>
          <Link to="/">Overview</Link>
        </p>
      </section>
    );
  }
}

const TITLES: Record<string, string> = {
  floor: 'Factory floor', overview: 'Overview', projects: 'Projects', knowledge: 'Knowledge', tasks: 'Tasks', approvals: 'My Approvals', runs: 'Runs', quality: 'Quality', reports: 'Reports', settings: 'Settings',
};

export function titleFor(path: string): string {
  const s = segments(path);
  if (s.length === 0) return 'Factory floor';
  if (s[0] === 'projects' && s[1] === 'new') return 'Create project';
  if (s[0] === 'projects' && s[2] === 'floor') return `${s[1]} floor`;
  if (s[0] === 'projects' && s[2] === 'knowledge') return `${s[1]} knowledge`;
  if (s[0] === 'projects' && s[2] === 'runs' && s[3]) return `${s[3]}${s[4] ? ` ${s[4]}` : ''}`;
  if (s[0] === 'projects' && s[1]) return `${s[1]}${s[2] ? ` ${s[2]}` : ''}`;
  if (s[0] === 'tasks' && s[1] === 'new') return 'New task';
  return TITLES[s[0]] ?? 'Page not found';
}

function Nav({ path }: { path: string }) {
  const approvals = useResource('approvals-count', (c) => calls.approvals(c), {});
  const count = approvals.data?.items.length ?? 0;
  const projects = useResource('nav-projects', (c) => calls.projects(c), {});
  const unavailable = projects.data?.items.filter((p) => p.status === 'unavailable') ?? [];
  const hasProjects = (projects.data?.items.filter((p) => p.status === 'available').length ?? 0) > 0;
  const firstPid = projects.data?.items.find((p) => p.status === 'available')?.id ?? '';
  const items: { to: string; label: string; icon: string; match: (p: string) => boolean }[] = [
    { to: '/floor', label: 'Factory floor', icon: 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5', match: (p) => p === '/floor' || p.endsWith('/floor') || (p === '/' && hasProjects) },
    { to: '/overview', label: 'Overview', icon: 'M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10', match: (p) => p === '/overview' || (p === '/' && !hasProjects) },
    { to: '/projects', label: 'Projects', icon: 'M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2z', match: (p) => p.startsWith('/projects') && !p.endsWith('/floor') && !p.includes('/knowledge') },
    { to: firstPid ? `/projects/${enc(firstPid)}/knowledge` : '/knowledge', label: 'Knowledge', icon: 'M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253', match: (p) => p.includes('/knowledge') },
    { to: '/tasks', label: 'Tasks', icon: 'M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2', match: (p) => p.startsWith('/tasks') },
    { to: '/approvals', label: 'My Approvals', icon: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5', match: (p) => p.startsWith('/approvals') },
    { to: '/runs', label: 'Runs', icon: 'M6 4l14 8-14 8z', match: (p) => p === '/runs' },
    { to: '/quality', label: 'Quality', icon: 'M4 20V10M10 20V4M16 20v-7M22 20H2', match: (p) => p === '/quality' },
    { to: '/reports', label: 'Reports', icon: 'M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h7', match: (p) => p === '/reports' },
    { to: '/settings', label: 'Settings', icon: 'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M16 4v4M10 10v4M18 16v4', match: (p) => p.startsWith('/settings') },
  ];
  return (
    <nav aria-label="Main">
      <ul>
        {items.map((i) => (
          <li key={i.to}>
            <Link to={i.to === '/settings' ? '/settings/installation' : i.to} current={i.match(path)}>
              <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d={i.icon} />
              </svg>
              <span className="nav-label">{i.label}</span>
              {i.to === '/approvals' && count > 0 ? <span className="badge">{count}</span> : null}
            </Link>
          </li>
        ))}
      </ul>
      {unavailable.length ? (
        <p className="hint" data-testid="unavailable-projects">
          {unavailable.map((p) => `Unavailable: ${p.name} (${p.reason ?? 'unknown'})`).join('; ')}
        </p>
      ) : null}
    </nav>
  );
}

function OrchestratorBadge() {
  const orch = useResource('header-orchestrator', (c) => calls.orchestrator(c), {});
  const providers = useResource('header-providers', (c) => calls.providers(c), {});
  useEffect(() => onOrchestratorChanged(() => { void orch.reload(); void providers.reload(); }), [orch.reload, providers.reload]);
  // an older server without the route shows nothing instead of an error in the header
  if (!orch.data) return null;
  const id = orch.data.id;
  const label = id ? (providers.data?.items.find((p) => p.id === id)?.label ?? id) : null;
  return (
    <Link to="/settings/providers" className={`orch-badge${id ? ' on' : ''}`} data-testid="orchestrator-badge" title="Change the orchestrator in Settings">
      <span className="orch-dot" aria-hidden="true" />
      <span className="orch-k">Orchestrator</span>
      <strong>{label ?? 'none'}</strong>
    </Link>
  );
}

function Shell() {
  const app = useApp();
  const route = useRoute();
  const mainRef = useRef<HTMLElement>(null);
  const first = useRef(true);
  // a route change sets the page title and moves focus to the main area, so assistive technology reads the new page
  useEffect(() => {
    document.title = `${titleFor(route.path)} - Sentinel`;
    if (first.current) first.current = false;
    else mainRef.current?.focus();
  }, [route.path]);
  if (app.sessionEnded) return <SessionEnded />;
  const label = app.status === 'connected' ? 'Connected' : app.status === 'connecting' ? 'Connecting' : 'Connection lost. Reconnecting.';
  return (
    <div className="shell">
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          mainRef.current?.focus();
        }}
      >
        Skip to content
      </a>
      <aside className="sidebar">
        <span className="brand">Sentinel</span>
        <NotificationBell />
        <Nav path={route.path} />
        <div className="statusbar">
          <span role="status" data-testid="connection-status">
            {label}
          </span>
        </div>
      </aside>
      <div className="content">
      <header className="topbar" data-testid="topbar">
        <span className="topbar-fill" />
        <OrchestratorBadge />
      </header>
      <main id="main" tabIndex={-1} ref={mainRef}>
        <ScreenBoundary resetKey={route.path}>{screenFor(route)}</ScreenBoundary>
        <div className="sr-only" aria-live="polite" data-testid="announcer">
          {app.announcement}
        </div>
      </main>
      </div>
    </div>
  );
}

export function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
