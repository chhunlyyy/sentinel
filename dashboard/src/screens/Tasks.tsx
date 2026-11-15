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
      navigate(`/projects/${enc(pid)}/runs/${enc(run.slug)}`);
    }
  };

  const ready = readiness.data ? readinessAllowsTasks(readiness.data.state) : true;
  return (
    <section>
      <h1>Create task</h1>
      <Loaded res={projects}>
        {() => (
          <>
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
          </>
        )}
      </Loaded>
    </section>
  );
}
