import { useEffect, useState } from 'react';
import { calls } from '../api/calls.ts';
import type { ApiError } from '../api/errors.ts';
import type { ConfigValue, ConfigVersion, Page, Repository, RunSummary } from '../api/types.ts';
import { REPO_ROLES } from '../api/orchestration.ts';
import { ErrorView } from '../components/ErrorView.tsx';
import { FolderPicker } from '../components/FolderPicker.tsx';
import { ActionResult, ConfirmDialog, Loaded, Tabs, useAction } from '../components/common.tsx';
import { AgentsPanel } from './Agents.tsx';
import { ReadinessPanel, readinessAllowsTasks } from '../components/ReadinessPanel.tsx';
import { RunTable } from '../components/RunTable.tsx';
import { UnifiedText } from '../components/DiffView.tsx';
import { formatTime, prefix } from '../format.ts';
import { Link, enc, navigate, type Route } from '../router.tsx';
import { useApp, useResource } from '../state/app.tsx';

function RegisterForm({ onDone }: { onDone: () => void }) {
  const app = useApp();
  const reg = useAction();
  const [path, setPath] = useState('');
  return (
    <div className="card" data-testid="register-form">
      <h2>Register existing folder</h2>
      <p className="hint">Use this for a workspace that already has a sentinel.config.yaml.</p>
      <FolderPicker label="Workspace folder" value={path} onChange={setPath} testId="register-folder" />
      <div className="row">
        <button
          type="button"
          disabled={!path.startsWith('/') || reg.pending}
          onClick={() =>
            void reg.run(
              async () => {
                const p = await calls.registerProject(app.client, path);
                navigate(`/projects/${enc(p.id)}`);
                return p;
              },
              (p) => `Registered ${p.name}`,
            )
          }
        >
          Register folder
        </button>
        <button type="button" className="secondary" onClick={onDone}>
          Cancel
        </button>
      </div>
      <ActionResult message={reg.message} />
    </div>
  );
}

export function ProjectsScreen() {
  const res = useResource('projects', (c) => calls.projects(c), {});
  const [registering, setRegistering] = useState(false);
  return (
    <section>
      <div className="page-head">
        <h1>Projects</h1>
        <div className="row">
          <button type="button" className="secondary" onClick={() => setRegistering((r) => !r)} aria-expanded={registering}>
            Register existing folder
          </button>
          <button type="button" onClick={() => navigate('/projects/new')}>
            Create project
          </button>
        </div>
      </div>
      {registering ? <RegisterForm onDone={() => setRegistering(false)} /> : null}
      <Loaded res={res}>
        {(page) =>
          page.items.length === 0 ? (
            <div className="panel empty">
              <p>No project registered</p>
              <p>Run sentinel dashboard inside a workspace to register it</p>
              <p className="hint">Or create a new project here, or register a folder that already has a sentinel.config.yaml.</p>
              <div className="row">
                <button type="button" onClick={() => navigate('/projects/new')}>
                  Create project
                </button>
              </div>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Name</th>
                    <th scope="col">Path</th>
                    <th scope="col">Status</th>
                    <th scope="col">Active runs</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <Link to={`/projects/${enc(p.id)}`}>{p.name}</Link>
                      </td>
                      <td>
                        <code>{p.path}</code>
                      </td>
                      <td>{p.status === 'unavailable' ? `Unavailable: ${p.reason ?? ''}` : p.status}</td>
                      <td>{p.status === 'unavailable' ? '' : p.active_runs}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </Loaded>
    </section>
  );
}

const TABS: [string, string][] = [
  ['', 'Overview'],
  ['repositories', 'Repositories'],
  ['configuration', 'Configuration'],
  ['agents', 'Agents'],
  ['runs', 'Runs'],
  ['audit', 'Audit'],
];

export function ProjectScreen({ pid, tab, rest, route }: { pid: string; tab: string; rest: string[]; route: Route }) {
  const res = useResource('projects', (c) => calls.projects(c), {});
  return (
    <section>
      <Loaded res={res}>
        {(page) => {
          const p = page.items.find((x) => x.id === pid);
          if (!p) {
            return (
              <>
                <h1>Project not found</h1>
                <p>
                  <Link to="/">Overview</Link>
                </p>
              </>
            );
          }
          if (p.status === 'unavailable') {
            return (
              <>
                <h1>{p.name}</h1>
                <div className="banner danger">Unavailable: {p.reason ?? 'unknown reason'}</div>
              </>
            );
          }
          return (
            <>
              <h1>{p.name}</h1>
              <Tabs label="Project" items={TABS.map(([t, label]) => ({ to: `/projects/${enc(pid)}${t ? `/${t}` : ''}`, label, current: tab === t }))} />
              {tab === '' ? <OverviewTab pid={pid} /> : null}
              {tab === 'repositories' ? <RepositoriesTab pid={pid} /> : null}
              {tab === 'configuration' ? <ConfigurationTab pid={pid} sub={rest[0]} route={route} /> : null}
              {tab === 'agents' ? <AgentsPanel pid={pid} /> : null}
              {tab === 'runs' ? <RunsTab pid={pid} /> : null}
              {tab === 'audit' ? <AuditTab pid={pid} /> : null}
              {!TABS.some(([t]) => t === tab) ? <p>Page not found</p> : null}
            </>
          );
        }}
      </Loaded>
    </section>
  );
}

function OverviewTab({ pid }: { pid: string }) {
  const readiness = useResource(`readiness-${pid}`, (c) => calls.readiness(c, pid), { project: pid });
  const runs = useResource(`runs-latest-${pid}`, (c) => calls.runs(c, pid), { project: pid });
  return (
    <>
      <h2>Readiness</h2>
      <Loaded res={readiness}>
        {(r) => (
          <>
            <ReadinessPanel readiness={r} />
            <button type="button" disabled={!readinessAllowsTasks(r.state)} onClick={() => navigate(`/tasks/new?project=${enc(pid)}`)}>
              Create task
            </button>
          </>
        )}
      </Loaded>
      <h2>Latest runs</h2>
      <Loaded res={runs}>
        {(page) => (
          <div data-testid="latest-runs">
            <RunTable rows={page.items.slice(0, 5).map((r) => ({ ...r, project: pid }))} />
          </div>
        )}
      </Loaded>
    </>
  );
}

const repoStatus = (s: string) => (s === 'passed' ? 'Passed' : s === 'failed' ? 'Failed' : s === 'warning' ? 'Warning' : s === 'unreachable' ? 'Not reachable' : s === 'not_configured' ? 'Not configured' : 'Not checked');
const title = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function AddRepoForm({ pid, onAdded }: { pid: string; onAdded: () => void }) {
  const app = useApp();
  const add = useAction();
  const profiles = useResource('profiles', (c) => calls.profiles(c), {});
  const [path, setPath] = useState('');
  const [id, setId] = useState('');
  const [role, setRole] = useState('backend');
  const [profile, setProfile] = useState('');
  return (
    <div className="card" data-testid="add-repo-form">
      <h3>Add repository</h3>
      <FolderPicker label="Repository folder" value={path} onChange={setPath} testId="add-repo-folder" />
      <div className="row">
        <div className="field inline">
          <label htmlFor="ar-id">Id (optional)</label>
          <input id="ar-id" type="text" value={id} autoComplete="off" onChange={(e) => setId(e.target.value)} />
        </div>
        <div className="field inline">
          <label htmlFor="ar-role">Role</label>
          <select id="ar-role" value={role} onChange={(e) => setRole(e.target.value)}>
            {REPO_ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>
        <div className="field inline">
          <label htmlFor="ar-profile">Profile</label>
          <select id="ar-profile" value={profile} onChange={(e) => setProfile(e.target.value)}>
            <option value="">Auto detect</option>
            {(profiles.data?.items ?? []).map((p) => (
              <option key={p.id} value={p.id}>{p.label ?? p.id}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="row">
        <button
          type="button"
          disabled={!path.startsWith('/') || add.pending}
          onClick={() =>
            void add.run(
              () => calls.addRepository(app.client, pid, { path, role, ...(id.trim() ? { id: id.trim() } : {}), ...(profile ? { profile } : {}) }),
              () => 'Repository added',
              { onSettled: () => undefined },
            ).then((r) => { if (r !== undefined) onAdded(); })
          }
        >
          Add to project
        </button>
      </div>
      <ActionResult message={add.message} />
    </div>
  );
}

function RepositoriesTab({ pid }: { pid: string }) {
  const res = useResource(`repos-${pid}`, (c) => calls.repositories(c, pid), { project: pid });
  const app = useApp();
  const act = useAction();
  const [adding, setAdding] = useState(false);
  const [confirm, setConfirm] = useState<string | null>(null);
  const done = () => void res.reload();
  return (
    <>
      <div className="page-head">
        <h2>Repositories</h2>
        <button type="button" onClick={() => setAdding((a) => !a)} aria-expanded={adding}>
          Add repository
        </button>
      </div>
      <p className="hint">
        Add or remove repositories here, or edit <code>sentinel.config.yaml</code> in the workspace and reload. Other settings of a repository are changed in that file.
      </p>
      {adding ? <AddRepoForm pid={pid} onAdded={() => { setAdding(false); done(); }} /> : null}
      <ActionResult message={act.message} />
      {confirm ? (
        <ConfirmDialog
          text={`Remove repository ${confirm} from this project? Its folder is not deleted.`}
          confirmLabel="Remove repository"
          cancelLabel="Keep repository"
          danger
          pending={act.pending}
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            const rid = confirm;
            setConfirm(null);
            void act.run(() => calls.removeRepository(app.client, pid, rid), () => `Removed ${rid}`, { onSettled: done });
          }}
        />
      ) : null}
      <Loaded res={res}>
        {(page) => (
          <>
            <p className="hint">Cross-repo order: the repositories are listed in the order the API returned them.</p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {['Id', 'Path', 'Remote', 'Default branch', 'Current branch', 'Role', 'Profile', 'Commands', 'Guidelines', 'Validation', 'Actions'].map((h) => (
                      <th scope="col" key={h}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((r: Repository) => (
                    <tr key={r.id} data-testid="repo-row">
                      <th scope="row">{r.id}</th>
                      <td><code>{r.path}</code></td>
                      <td>{r.remote ?? 'none'}</td>
                      <td>{r.default_branch}</td>
                      <td>{r.branch}</td>
                      <td>{r.role}</td>
                      <td>{r.profile}</td>
                      <td>
                        <ul className="plain">
                          {Object.entries(r.commands).map(([k, v]) => (
                            <li key={k}>
                              {k}: <code>{v ?? 'not configured'}</code>
                            </li>
                          ))}
                        </ul>
                      </td>
                      <td>{r.guidelines ?? 'none'}</td>
                      <td>
                        <ul className="plain">
                          {r.validation.map((v) => (
                            <li key={v.item}>
                              {title(v.item)}: {repoStatus(v.status)}
                              {v.status !== 'passed' && v.fix ? <> Fix: <code>{v.fix}</code></> : null}
                            </li>
                          ))}
                        </ul>
                      </td>
                      <td>
                        <button type="button" className="secondary" aria-label={`Remove repository ${r.id}`} onClick={() => setConfirm(r.id)}>
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Loaded>
    </>
  );
}

const CATEGORIES = ['Project', 'Repositories', 'Providers', 'Agents', 'Workflow and policies', 'TDD', 'Verification', 'Limits'];
const SOURCE = (v: Pick<ConfigValue, 'source' | 'repo'>) => (v.source === 'repo' ? `Repo ${v.repo ?? ''}` : title(v.source));
const show = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v));

function ConfigRow({ v }: { v: ConfigValue }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="panel" data-testid={`config-value-${v.path}`}>
      <code>{v.path}</code>: <strong>{show(v.value)}</strong> <span className="badge">{SOURCE(v)}</span>
      {v.overrides ? (
        <>
          {' '}
          <button type="button" className="secondary" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? `Hide override of ${v.path}` : `Show override of ${v.path}`}
          </button>
          {open ? <p>Overrides {SOURCE(v.overrides)}: {show(v.overrides.value)}</p> : null}
        </>
      ) : null}
    </div>
  );
}

function ConfigurationTab({ pid, sub, route }: { pid: string; sub?: string; route: Route }) {
  const res = useResource(`config-${pid}`, (c) => calls.configuration(c, pid), { project: pid }, sub !== 'history');
  return (
    <>
      <h2>Configuration</h2>
      <nav aria-label="Configuration views">
        <ul className="tabs">
          <li><Link to={`/projects/${enc(pid)}/configuration`} current={sub !== 'history'}>Effective values</Link></li>
          <li><Link to={`/projects/${enc(pid)}/configuration/history`} current={sub === 'history'}>History</Link></li>
        </ul>
      </nav>
      {sub === 'history' ? (
        <HistoryView pid={pid} route={route} />
      ) : (
        <>
          <p>
            Edit <code>sentinel.config.yaml</code>; the change appears here after Reload
          </p>
          <button type="button" className="secondary" onClick={() => void res.reload()}>
            Reload
          </button>
          <Loaded res={res}>
            {(cfg) => (
              <>
                <p className="hint">
                  Current file <code>{prefix(cfg.sha256)}</code>
                </p>
                {CATEGORIES.map((cat) => {
                  const values = cfg.values.filter((v) => v.category === cat);
                  return values.length ? (
                    <section key={cat}>
                      <h3>{cat}</h3>
                      {values.map((v) => (
                        <ConfigRow key={`${v.path}-${v.repo ?? ''}`} v={v} />
                      ))}
                    </section>
                  ) : null;
                })}
              </>
            )}
          </Loaded>
        </>
      )}
    </>
  );
}

function HistoryView({ pid, route }: { pid: string; route: Route }) {
  const app = useApp();
  const res = useResource(`config-history-${pid}`, (c) => calls.configHistory(c, pid), { project: pid });
  const [selected, setSelected] = useState<number[]>(() => [route.query.get('a'), route.query.get('b')].filter(Boolean).map(Number));
  const [diff, setDiff] = useState<{ text: string } | { error: ApiError } | null>(null);
  const [busy, setBusy] = useState(false);

  const compare = async (a: number, b: number) => {
    setBusy(true);
    try {
      const d = await calls.configDiff(app.client, pid, String(a), String(b));
      setDiff({ text: d.diff });
    } catch (e) {
      setDiff({ error: e as ApiError });
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const a = route.query.get('a');
    const b = route.query.get('b');
    if (a && b) void compare(Number(a), Number(b));
  }, []);

  return (
    <Loaded res={res}>
      {(page: Page<ConfigVersion>) => (
        <>
          <h3>History</h3>
          {page.items.length === 0 ? <p>No saved versions yet</p> : null}
          <ul className="plain">
            {page.items.map((v) => (
              <li key={v.version} className="panel" data-testid={`version-${v.version}`}>
                <div data-testid="version-row">
                  <label>
                    <input
                      type="checkbox"
                      checked={selected.includes(v.version)}
                      onChange={(e) =>
                        setSelected((s) => (e.target.checked ? [...s, v.version].slice(-2) : s.filter((x) => x !== v.version)))
                      }
                      aria-label={`Select version ${v.version}`}
                    />{' '}
                    Version {v.version}
                  </label>{' '}
                  <code>{prefix(v.sha256)}</code> by {v.author} via {v.channel} at {formatTime(v.at)}
                  {v.comment ? <span>: {v.comment}</span> : null}
                </div>
              </li>
            ))}
          </ul>
          <button
            type="button"
            disabled={selected.length !== 2 || busy || page.items.length === 0}
            onClick={() => {
              const [a, b] = [...selected].sort((x, y) => x - y);
              void compare(a, b);
            }}
          >
            Compare
          </button>
          {diff && 'error' in diff ? <ErrorView error={diff.error} /> : null}
          {diff && 'text' in diff ? <UnifiedText text={diff.text} /> : null}
        </>
      )}
    </Loaded>
  );
}

function usePaged<T>(key: string, fetchPage: (cursor: string | null) => Promise<Page<T>>, project: string) {
  const first = useResource<Page<T>>(key, () => fetchPage(null), { project });
  const [extra, setExtra] = useState<T[]>([]);
  const [next, setNext] = useState<string | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setExtra([]);
    setNext(undefined);
  }, [first.version]);
  const cursor = next === undefined ? (first.data?.next ?? null) : next;
  const more = async () => {
    if (!cursor || busy) return;
    setBusy(true);
    try {
      const page = await fetchPage(cursor);
      setExtra((e) => [...e, ...page.items]);
      setNext(page.next);
    } finally {
      setBusy(false);
    }
  };
  return { first, items: [...(first.data?.items ?? []), ...extra], cursor, more, busy };
}

function RunsTab({ pid }: { pid: string }) {
  const app = useApp();
  const paged = usePaged<RunSummary>(`runs-${pid}`, (cur) => calls.runs(app.client, pid, cur), pid);
  const [state, setState] = useState('');
  const states = Array.from(new Set(paged.items.map((r) => r.state))).sort();
  const rows = paged.items.filter((r) => !state || r.state === state).map((r) => ({ ...r, project: pid }));
  return (
    <>
      <h2>Runs</h2>
      <Loaded res={paged.first}>
        {() =>
          paged.items.length === 0 ? (
            <p>
              No runs yet. <Link to={`/tasks/new?project=${enc(pid)}`}>Create task</Link>
            </p>
          ) : (
            <>
              <div className="field">
                <label htmlFor="state-filter">State</label>{' '}
                <select id="state-filter" value={state} onChange={(e) => setState(e.target.value)}>
                  <option value="">All states</option>
                  {states.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
              <RunTable rows={rows} />
              {paged.cursor ? (
                <button type="button" className="secondary" disabled={paged.busy} onClick={() => void paged.more()}>
                  Load more
                </button>
              ) : null}
            </>
          )
        }
      </Loaded>
    </>
  );
}

function AuditTab({ pid }: { pid: string }) {
  const app = useApp();
  const paged = usePaged(`audit-${pid}`, (cur) => calls.audit(app.client, pid, cur), pid);
  return (
    <>
      <h2>Audit</h2>
      <Loaded res={paged.first}>
        {() => (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {['Actor', 'Channel', 'Action', 'Target', 'Before', 'After', 'Reason', 'Time'].map((h) => (
                      <th scope="col" key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paged.items.map((a) => (
                    <tr key={a.id} data-testid="audit-row">
                      <td>{a.actor}</td>
                      <td>{a.channel}</td>
                      <td>{a.action}</td>
                      <td>{a.target}</td>
                      <td><code>{prefix(a.before_sha256)}</code></td>
                      <td><code>{prefix(a.after_sha256)}</code></td>
                      <td>{a.reason}</td>
                      <td>{formatTime(a.at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {paged.cursor ? (
              <button type="button" className="secondary" disabled={paged.busy} onClick={() => void paged.more()}>
                Load more
              </button>
            ) : null}
          </>
        )}
      </Loaded>
    </>
  );
}


