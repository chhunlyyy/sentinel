import { useState } from 'react';
import { calls } from '../api/calls.ts';
import type { ApiError } from '../api/errors.ts';
import type { RunSummary } from '../api/types.ts';
import { ActionResult, Loaded, useAction } from '../components/common.tsx';
import { CreateTaskForm, type CreateTaskBody } from '../components/CreateTaskForm.tsx';
import { ReadinessPanel, readinessAllowsTasks } from '../components/ReadinessPanel.tsx';
import { RunTable } from '../components/RunTable.tsx';
import { setFlash } from '../flash.ts';
import { Link, enc, navigate, type Route } from '../router.tsx';
import { useApp, useResource } from '../state/app.tsx';

function useAllRuns() {
  return useResource<RunSummary[]>('all-runs', async (c) => {
    const projects = await calls.projects(c);
    const out: RunSummary[] = [];
    for (const p of projects.items.filter((x) => x.status === 'available')) {
      const page = await calls.runs(c, p.id);
      out.push(...page.items.map((r) => ({ ...r, project: p.id })));
    }
    return out.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  }, {});
}

export function TasksScreen() {
  const res = useAllRuns();
  return (
    <section>
      <h1>Tasks</h1>
      <p>
        <Link to="/tasks/new">New task</Link>
      </p>
      <Loaded res={res}>{(rows) => (rows.length ? <RunTable rows={rows} project /> : <p>No runs yet</p>)}</Loaded>
    </section>
  );
}

const TERMINAL = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);

export function RunsScreen() {
  const res = useAllRuns();
  return (
    <section>
      <h1>Runs</h1>
      <p className="hint">Runs that are not finished.</p>
      <Loaded res={res}>
        {(rows) => {
          const active = rows.filter((r) => !TERMINAL.has(r.state));
          return active.length ? <RunTable rows={active} project /> : <p>No active runs</p>;
        }}
      </Loaded>
    </section>
  );
}

export function QualityScreen() {
  const res = useAllRuns();
  return (
    <section>
      <h1>Quality</h1>
      <Loaded res={res}>
        {(rows) => {
          const v2 = rows.filter((r) => r.workflow_version === '2');
          return v2.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Project</th>
                    <th scope="col">Run</th>
                    <th scope="col">State</th>
                    <th scope="col">Views</th>
                  </tr>
                </thead>
                <tbody>
                  {v2.map((r) => {
                    const base = `/projects/${enc(r.project ?? '')}/runs/${enc(r.slug)}`;
                    return (
                      <tr key={`${r.project}/${r.slug}`}>
                        <td>{r.project}</td>
                        <td>{r.slug}</td>
                        <td>{r.state}</td>
                        <td>
                          <Link to={`${base}/tdd`}>TDD</Link> <Link to={`${base}/verification`}>Verification</Link> <Link to={`${base}/changes`}>Changes</Link>{' '}
                          <Link to={`${base}/trace`}>Trace</Link>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p>No runs yet</p>
          );
        }}
      </Loaded>
    </section>
  );
}

export function CreateTaskScreen({ route }: { route: Route }) {
  const app = useApp();
  const projects = useResource('projects', (c) => calls.projects(c), {});
  const available = projects.data?.items.filter((p) => p.status === 'available') ?? [];
  const [chosen, setChosen] = useState<string | null>(route.query.get('project'));
  const pid = chosen ?? available[0]?.id ?? '';
  const [type, setType] = useState('');
  const repos = useResource(`create-repos-${pid}`, (c) => calls.repositories(c, pid), { project: pid }, !!pid);
  const readiness = useResource(`create-readiness-${pid}-${type}`, (c) => calls.readiness(c, pid, type || undefined), { project: pid }, !!pid);
  const action = useAction();
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const submit = async (body: CreateTaskBody) => {
    setFieldErrors({});
    const run = await action.run(
      () => calls.createRun(app.client, pid, body),
      (r) => `${r.slug} created: ${r.state}`,
      {
        onError: (e: ApiError) => {
          const field = e.details.field;
          if (typeof field === 'string') {
            setFieldErrors({ [field]: e.message });
            return `${e.text}`;
          }
          return undefined;
        },
      },
    );
    if (run) {
      setFlash(`${run.slug} created: ${run.state}`);
      const target = route.query.get('target') || route.query.get('return');
      if (target === 'floor') {
        navigate(`/projects/${enc(pid)}/floor?task=${enc(run.slug)}`);
      } else {
        navigate(`/projects/${enc(pid)}/runs/${enc(run.slug)}`);
      }
    }
  };

  const ready = readiness.data ? readinessAllowsTasks(readiness.data.state) : true;
  return (
    <section>
      <h1>Create task</h1>
      <Loaded res={projects}>
        {() => (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1.5rem', alignItems: 'flex-start' }}>
            <div style={{ flex: '999 1 540px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <div className="field">
                <label htmlFor="project-select">Project</label>
                <select
                  id="project-select"
                  value={pid}
                  onChange={(e) => {
                    setChosen(e.target.value);
                    setType('');
                  }}
                >
                  {available.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.id}
                    </option>
                  ))}
                </select>
              </div>
              <CreateTaskForm
                key={pid}
                repos={repos.data?.items.map((r) => r.id) ?? []}
                onSubmit={submit}
                onTypeChange={setType}
                fieldErrors={fieldErrors}
                pending={action.pending}
                blocked={!ready}
              >
                {readiness.data && !ready ? <ReadinessPanel readiness={readiness.data} /> : null}
              </CreateTaskForm>
              {action.message?.kind === 'error' && Object.keys(fieldErrors).length === 0 ? <ActionResult message={action.message} /> : null}
            </div>

            <aside aria-label="What happens next" style={{ flex: '1 1 280px', maxWidth: 360, display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <h2 style={{ margin: 0, fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)' }}>
                  After you send it
                </h2>
                <ol style={{ margin: '0.25rem 0', paddingLeft: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.35rem', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                  <li>Triage sizes it (about a minute)</li>
                  <li>An agent writes the spec</li>
                  <li><strong>You approve the spec</strong></li>
                  <li>Scenarios, then <strong>you approve them</strong></li>
                  <li>Build, verify, report</li>
                  <li><strong>You accept</strong></li>
                </ol>
                <p className="hint" style={{ margin: 0, fontSize: '0.8rem' }}>
                  You get a notification at every gate. Close the tab any time: the factory keeps going.
                </p>
              </section>

              <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <h2 style={{ margin: 0, fontSize: '0.9rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Knowledge found
                </h2>
                <p className="hint" style={{ margin: 0, fontSize: '0.85rem' }}>
                  Related past changes the agents will read:
                </p>
                <ul style={{ margin: '0.25rem 0', paddingLeft: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.8rem' }}>
                  <li>Recent verified change records in {pid}</li>
                  <li>Active invariants & team rules</li>
                </ul>
                <Link to={`/projects/${enc(pid)}/knowledge`} style={{ fontSize: '0.85rem' }}>
                  Open knowledge base
                </Link>
              </section>
            </aside>
          </div>
        )}
      </Loaded>
    </section>
  );
}
