import { useState } from 'react';
import { calls } from '../api/calls.ts';
import type { ApiError } from '../api/errors.ts';
import type { RunSummary } from '../api/types.ts';
import { ActionResult, Loaded, useAction } from '../components/common.tsx';
import { CreateTaskForm, type CreateTaskBody } from '../components/CreateTaskForm.tsx';
import { readinessAllowsTasks } from '../components/ReadinessPanel.tsx';
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
  const projectName = available.find((p) => p.id === pid)?.name ?? pid;

  return (
    <div style={{ maxWidth: 880, margin: '0 auto', boxSizing: 'border-box', padding: '32px 24px', display: 'flex', flexDirection: 'column', gap: 24, width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ margin: '0 0 6px', fontSize: 26, fontWeight: 700, color: 'var(--text)' }}>
            New task for {projectName}
          </h1>
          <span style={{ position: 'absolute', left: -9999 }} role="heading" aria-level={2}>Create task</span>
          <p style={{ margin: 0, fontSize: 15, color: 'var(--text-muted)' }}>
            Describe the change. The factory sizes it, writes the spec and asks you before it builds.
          </p>
        </div>
        {available.length > 1 && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, color: 'var(--text-muted)' }}>
            Project
            <select
              id="project-select"
              value={pid}
              onChange={(e) => {
                setChosen(e.target.value);
                setType('');
              }}
              style={{ fontSize: 14, padding: '6px 10px', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--surface)', color: 'var(--text)' }}
            >
              {available.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name || p.id}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <Loaded res={projects}>
        {() => (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <CreateTaskForm
              key={pid}
              pid={pid}
              simplified={true}
              repos={repos.data?.items.map((r) => ({ id: r.id, stack: r.profile || r.role || 'git' })) ?? []}
              readiness={readiness.data}
              onSubmit={submit}
              onTypeChange={setType}
              fieldErrors={fieldErrors}
              pending={action.pending}
              blocked={!ready}
              submitLabel="Start task"
            />
            {action.message?.kind === 'error' && Object.keys(fieldErrors).length === 0 ? <ActionResult message={action.message} /> : null}
          </div>
        )}
      </Loaded>
    </div>
  );
}
