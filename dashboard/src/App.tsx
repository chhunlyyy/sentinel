import { Component, useEffect, useRef, useState, type ReactNode } from 'react';
import { calls } from './api/calls.ts';
import { AppProvider, useApp, useResource } from './state/app.tsx';
import { Link, segments, useRoute, type Route } from './router.tsx';
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
      return <SettingsScreen page={s[1] ?? ''} />;
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

function FactoryControls() {
  const app = useApp();
  const factory = useResource('header-factory-status', (c) => calls.factoryStatus(c), {
    types: ['factory.paused', 'factory.resumed'],
  });
  const [pending, setPending] = useState(false);
  const isPaused = factory.data?.paused ?? false;
  const runningTotal = factory.data?.running_total ?? 1;
  const maxAgents = factory.data?.max_agents ?? 4;

  const handleToggle = async () => {
    if (pending) return;
    if (!isPaused) {
      if (!window.confirm('Pause the entire factory? Tasks already running will finish, but no new tasks will start.')) {
        return;
      }
      setPending(true);
      try {
        await calls.pauseFactory(app.client);
        await factory.reload();
      } finally {
        setPending(false);
      }
    } else {
      setPending(true);
      try {
        await calls.resumeFactory(app.client);
        await factory.reload();
      } finally {
        setPending(false);
      }
    }
  };

  return (
    <div className="factory-controls">
      <span className="factory-pill" data-testid="factory-status-pill">
        <span
          className={`factory-dot${isPaused ? ' paused' : ' running pulse'}`}
          aria-hidden="true"
        />
        <span title={isPaused ? 'Factory paused · nothing new starts' : `Factory running · ${runningTotal} of ${maxAgents} agents busy`}>
          {isPaused ? 'Factory paused' : 'Factory running'}
          {/* the detail drops on narrower windows so the header stays on one row */}
          <span className="pill-extra">
            {isPaused ? ' · nothing new starts' : ` · ${runningTotal} of ${maxAgents} agents busy`}
          </span>
        </span>
      </span>
      <button
        type="button"
        className="factory-btn secondary"
        disabled={pending}
        onClick={handleToggle}
      >
        {isPaused ? 'Resume factory' : 'Pause factory'}
      </button>
    </div>
  );
}

function TopHeader({ path, label }: { path: string; label: string }) {
  const projects = useResource('nav-projects', (c) => calls.projects(c), {});
  const unavailable = projects.data?.items.filter((p) => p.status === 'unavailable') ?? [];
  const hasProjects = (projects.data?.items.filter((p) => p.status === 'available').length ?? 0) > 0;

  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    setMobileMenuOpen(false);
  }, [path]);

  const isFloor = path === '/floor' || path.endsWith('/floor') || (path === '/' && hasProjects);
  const isNewTask = path === '/tasks/new' || path.startsWith('/tasks/new');
  const isProjects = path.startsWith('/projects') && !path.endsWith('/floor') && !path.includes('/knowledge');
  const isSettings = path.startsWith('/settings');

  return (
    <>
      <header className="topbar-header" data-testid="topbar">
        <Link to="/" className="brand" aria-label="Sentinel home">
          <svg className="brand-logo" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#4FD1C1" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="5" cy="12" r="2.2" />
            <circle cx="12" cy="5" r="2.2" />
            <circle cx="12" cy="19" r="2.2" />
            <circle cx="19" cy="12" r="2.2" />
            <path d="M7 11l3-4M7 13l3 4M14 6l3 4M14 18l3-4" />
          </svg>
          <span className="brand-name">Sentinel</span>
        </Link>

        <button
          type="button"
          className="mobile-menu-btn"
          aria-expanded={mobileMenuOpen}
          aria-label="Navigation menu"
          onClick={() => setMobileMenuOpen((o) => !o)}
        >
          Menu
        </button>

        <nav aria-label="Main" className={mobileMenuOpen ? 'main-nav open' : 'main-nav'}>
          <Link to="/floor" current={isFloor}>
            Floor
          </Link>
          <Link to="/tasks/new" current={isNewTask}>
            New task
          </Link>
          <Link to="/projects" current={isProjects}>
            Projects
          </Link>
          <Link to="/settings" current={isSettings}>
            Settings
          </Link>
        </nav>

        <span className="header-spacer" />

        <div className="header-right">
          <FactoryControls />
          <NotificationBell />
          <span role="status" data-testid="connection-status" className="session-status" title={label}>
            <span className={`session-dot${label === 'Connected' ? ' ok' : ''}`} aria-hidden="true" />
            <span className="sr-only">{label}</span>
          </span>
        </div>
      </header>
      {unavailable.length ? (
        <div className="hint unavailable-banner" data-testid="unavailable-projects">
          {unavailable.map((p) => `Unavailable: ${p.name} (${p.reason ?? 'unknown'})`).join('; ')}
        </div>
      ) : null}
    </>
  );
}

function Shell() {
  const app = useApp();
  const route = useRoute();
  const mainRef = useRef<HTMLElement>(null);
  const first = useRef(true);

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
      <TopHeader path={route.path} label={label} />
      <main id="main" tabIndex={-1} ref={mainRef} className={route.path === '/' || route.path.endsWith('/floor') || route.path === '/floor' ? 'wide' : undefined}>
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
