import { Component, useEffect, useRef, useState, type ReactNode } from 'react';
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
        <span>
          {isPaused
            ? 'Factory paused · nothing new starts'
            : `Factory running · ${runningTotal} of ${maxAgents} agents busy`}
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
  const approvals = useResource('approvals-count', (c) => calls.approvals(c), {});
  const count = approvals.data?.items.length ?? 0;
  const projects = useResource('nav-projects', (c) => calls.projects(c), {});
  const unavailable = projects.data?.items.filter((p) => p.status === 'unavailable') ?? [];
  const hasProjects = (projects.data?.items.filter((p) => p.status === 'available').length ?? 0) > 0;
  const firstPid = projects.data?.items.find((p) => p.status === 'available')?.id ?? '';

  const [moreOpen, setMoreOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!moreOpen) return undefined;
    const onClick = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) {
        setMoreOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMoreOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [moreOpen]);

  useEffect(() => {
    setMoreOpen(false);
    setMobileMenuOpen(false);
  }, [path]);

  const isFloor = path === '/floor' || path.endsWith('/floor') || (path === '/' && hasProjects);
  const isNewTask = path === '/tasks/new' || path.startsWith('/tasks/new');
  const isApprovals = path.startsWith('/approvals');
  const isProjects = path.startsWith('/projects') && !path.endsWith('/floor') && !path.includes('/knowledge');
  const isRuns = path === '/runs' || path.startsWith('/runs');
  const isKnowledge = path.includes('/knowledge');
  const isReports = path.startsWith('/reports');
  const isSettings = path.startsWith('/settings');

  const isOverview = path === '/overview' || (path === '/' && !hasProjects);
  const isTasks = path.startsWith('/tasks') && !path.startsWith('/tasks/new');
  const isQuality = path.startsWith('/quality');
  const isMoreActive = isOverview || isTasks || isQuality;

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
            Factory floor
          </Link>
          <Link to="/tasks/new" current={isNewTask}>
            New task
          </Link>
          <Link to="/approvals" current={isApprovals}>
            Approvals
            {count > 0 ? <span className="badge">{count}</span> : null}
          </Link>
          <Link to="/projects" current={isProjects}>
            Projects
          </Link>
          <Link to="/runs" current={isRuns}>
            Runs
          </Link>
          <Link to={firstPid ? `/projects/${enc(firstPid)}/knowledge` : '/knowledge'} current={isKnowledge}>
            Knowledge
          </Link>
          <Link to="/reports" current={isReports}>
            Reports
          </Link>
          <Link to="/settings/installation" current={isSettings}>
            Settings
          </Link>

          <div className="more-menu-container" ref={moreRef}>
            <button
              type="button"
              className={`more-btn${isMoreActive ? ' active' : ''}`}
              aria-expanded={moreOpen}
              aria-haspopup="true"
              onClick={() => setMoreOpen((o) => !o)}
            >
              <span>More</span>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {moreOpen ? (
              <div className="more-dropdown">
                <Link to="/overview" current={isOverview}>
                  Overview
                </Link>
                <Link to="/tasks" current={isTasks}>
                  Tasks
                </Link>
                <Link to="/quality" current={isQuality}>
                  Quality
                </Link>
              </div>
            ) : null}
          </div>
        </nav>

        <span className="header-spacer" />

        <div className="header-right">
          <FactoryControls />
          <NotificationBell />
          <OrchestratorBadge />
          <span role="status" data-testid="connection-status" className="session-status">
            {label}
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
