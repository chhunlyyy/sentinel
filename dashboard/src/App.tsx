import { Component, useEffect, useRef, type ReactNode } from 'react';
import { calls } from './api/calls.ts';
import { AppProvider, useApp, useResource } from './state/app.tsx';
import { Link, segments, useRoute, type Route } from './router.tsx';
import { Overview } from './screens/Overview.tsx';
import { ProjectsScreen, ProjectScreen } from './screens/Projects.tsx';
import { TasksScreen, RunsScreen, QualityScreen, CreateTaskScreen } from './screens/Tasks.tsx';
import { ApprovalsScreen } from './screens/Approvals.tsx';
import { RunScreen } from './screens/Run.tsx';
import { SettingsScreen } from './screens/Settings.tsx';

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

function screenFor(route: Route): ReactNode {
  const s = segments(route.path);
  if (s.length === 0) return <Overview />;
  switch (s[0]) {
    case 'projects':
      if (s.length === 1) return <ProjectsScreen />;
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
  projects: 'Projects', tasks: 'Tasks', approvals: 'My Approvals', runs: 'Runs', quality: 'Quality', settings: 'Settings',
};

export function titleFor(path: string): string {
  const s = segments(path);
  if (s.length === 0) return 'Overview';
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
  const items: { to: string; label: string; match: (p: string) => boolean }[] = [
    { to: '/', label: 'Overview', match: (p) => p === '/' },
    { to: '/projects', label: 'Projects', match: (p) => p.startsWith('/projects') },
    { to: '/tasks', label: 'Tasks', match: (p) => p.startsWith('/tasks') },
    { to: '/approvals', label: 'My Approvals', match: (p) => p.startsWith('/approvals') },
    { to: '/runs', label: 'Runs', match: (p) => p === '/runs' },
    { to: '/quality', label: 'Quality', match: (p) => p === '/quality' },
    { to: '/settings', label: 'Settings', match: (p) => p.startsWith('/settings') },
  ];
  return (
    <nav aria-label="Main">
      <ul>
        {items.map((i) => (
          <li key={i.to}>
            <Link to={i.to === '/settings' ? '/settings/installation' : i.to} current={i.match(path)}>
              {i.label}
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
        <Nav path={route.path} />
        <div className="statusbar">
          <span role="status" data-testid="connection-status">
            {label}
          </span>
        </div>
      </aside>
      <main id="main" tabIndex={-1} ref={mainRef}>
        <ScreenBoundary resetKey={route.path}>{screenFor(route)}</ScreenBoundary>
        <div className="sr-only" aria-live="polite" data-testid="announcer">
          {app.announcement}
        </div>
      </main>
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
