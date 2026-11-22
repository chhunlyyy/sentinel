import { useState } from 'react';
import { calls } from '../api/calls.ts';
import type { ApiError } from '../api/errors.ts';
import type { NextStep, Run, Workflow } from '../api/types.ts';
import { ActionResult, ConfirmDialog, CopyButton, Loaded, Tabs, useAction, useControlsEnabled } from '../components/common.tsx';
import { ErrorView } from '../components/ErrorView.tsx';
import { formatTime, prefix } from '../format.ts';
import { takeFlash } from '../flash.ts';
import { Link, enc, type Route } from '../router.tsx';
import { useApp, useResource } from '../state/app.tsx';
import { ReviewPage } from './Approvals.tsx';
import { AcceptanceTab } from './run/Acceptance.tsx';
import { ChangesTab } from './run/Changes.tsx';
import { LogPage } from './run/Log.tsx';
import { EvidencePage, TddTab } from './run/Tdd.tsx';
import { TraceTab } from './run/Trace.tsx';
import { VerificationTab } from './run/Verification.tsx';
import { WorkflowTab, useStateAnnouncer } from './run/Workflow.tsx';

const TERMINAL = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);

const TABS: [string, string][] = [
  ['', 'Overview'],
  ['workflow', 'Workflow'],
  ['tdd', 'TDD'],
  ['verification', 'Verification'],
  ['changes', 'Changes'],
  ['trace', 'Trace'],
  ['acceptance', 'Acceptance'],
  ['specification', 'Specification'],
  ['gherkin', 'Gherkin'],
];

export function RunScreen({ pid, slug, rest }: { pid: string; slug: string; rest: string[]; route: Route }) {
  const run = useResource(`run-${pid}-${slug}`, (c) => calls.run(c, slug, pid), { project: pid, run: slug });
  const history = useResource(`run-config-history-${pid}`, (c) => calls.configHistory(c, pid), { project: pid }, !!run.data?.config_snapshot);

  if (run.error && !run.data) {
    if (run.error.status === 404 || run.error.code === 'E_NOT_FOUND') {
      return (
        <section>
          <h1>Run not found</h1>
          <p>
            <Link to="/">Overview</Link>
          </p>
        </section>
      );
    }
    return <ErrorView error={run.error} />;
  }
  if (!run.data) return <p className="hint" role="status">Loading</p>;
  const r = run.data;
  const base = `/projects/${enc(pid)}/runs/${enc(slug)}`;
  const tab = rest[0] ?? '';
  const latestConfig = history.data?.items.reduce((m, v) => Math.max(m, v.version), 0) ?? 0;

  return (
    <section>
      <div data-testid="run-header">
        <h1>{r.slug}</h1>
        <p>
          Project <strong>{r.project}</strong> · type {r.type} · tier {r.tier ?? 'not set'} · state <strong data-testid="run-state">{r.state}</strong>
          {r.workflow_version === '0.1' ? <span className="badge">Legacy (0.1)</span> : null}
        </p>
        {r.config_snapshot ? (
          <p>
            Config snapshot {r.config_snapshot.version} <code>{prefix(r.config_snapshot.sha256)}</code>
          </p>
        ) : null}
      </div>
      {r.config_snapshot && latestConfig > r.config_snapshot.version ? (
        <p className="banner warn">
          The project configuration changed after this run started. This run keeps using snapshot {r.config_snapshot.version}.{' '}
          <Link to={`/projects/${enc(pid)}/configuration/history?a=${r.config_snapshot.version}&b=${latestConfig}`}>
            Show the diff of versions {r.config_snapshot.version} and {latestConfig}
          </Link>
        </p>
      ) : null}
      {r.workflow_version === '0.1' ? (
        <div className="panel">
          <p>Legacy (0.1) run. State: {r.state}.</p>
          <p>
            To continue it, run <code>sentinel resume {r.slug}</code> in a terminal.
          </p>
        </div>
      ) : (
        <>
          <Tabs label="Run" items={TABS.map(([t, label]) => ({ to: `${base}${t ? `/${t}` : ''}`, label, current: tab === t }))} />
          {tab === '' ? <OverviewTab run={r} pid={pid} base={base} onChanged={() => void run.reload()} /> : null}
          {tab === 'workflow' ? <WorkflowTab pid={pid} slug={slug} base={base} /> : null}
          {tab === 'tdd' ? <TddTab pid={pid} slug={slug} base={base} /> : null}
          {tab === 'verification' ? <VerificationTab pid={pid} slug={slug} base={base} /> : null}
          {tab === 'changes' ? <ChangesTab pid={pid} slug={slug} base={base} /> : null}
          {tab === 'trace' ? <TraceTab pid={pid} slug={slug} base={base} /> : null}
          {tab === 'acceptance' ? <AcceptanceTab run={r} pid={pid} onChanged={() => void run.reload()} /> : null}
          {tab === 'specification' ? <ReviewPage key={`spec-${rest[2] ?? 'current'}`} gate="specification" pid={pid} slug={slug} version={rest[1] === 'versions' ? rest[2] : undefined} onRunChanged={() => void run.reload()} /> : null}
          {tab === 'gherkin' ? <ReviewPage gate="gherkin" pid={pid} slug={slug} onRunChanged={() => void run.reload()} /> : null}
          {tab === 'log' ? <LogPage pid={pid} slug={slug} tid={rest[1] ?? ''} base={base} /> : null}
          {tab === 'evidence' ? <EvidencePage pid={pid} slug={slug} eid={rest[1] ?? ''} base={base} /> : null}
          {!TABS.some(([t]) => t === tab) && tab !== 'log' && tab !== 'evidence' ? <p>Page not found</p> : null}
        </>
      )}
    </section>
  );
}

export function NextBanner({ pid, slug, base, state }: { pid: string; slug: string; base: string; state?: string }) {
  const next = useResource(`next-${pid}-${slug}`, (c) => calls.next(c, slug, pid), { project: pid, run: slug });
  return <Loaded res={next}>{(n: NextStep) => <NextView n={n} base={base} created={state === 'CREATED'} />}</Loaded>;
}

function NextView({ n, base, created }: { n: NextStep; base: string; created: boolean }) {
  return (
    <div className="banner" data-testid="next-banner">
      <strong>{n.label}</strong>
      {created && n.command ? (
        <p>
          Queued for the AI tool. In your AI tool session run <code>{n.command}</code>
        </p>
      ) : null}
      {n.command ? (
        <p>
          <code>{n.command}</code> <CopyButton text={n.command} />
        </p>
      ) : null}
      {n.kind === 'human' && n.gate ? (
        <p>
          <Link to={`${base}/${n.gate}`}>Review the {n.gate}</Link>
        </p>
      ) : null}
    </div>
  );
}

type DialogState = { kind: 'cancel-run' } | { kind: 'resume' } | { kind: 'retry'; id: string } | { kind: 'cancel-task'; id: string } | null;

function OverviewTab({ run, pid, base, onChanged }: { run: Run; pid: string; base: string; onChanged: () => void }) {
  const app = useApp();
  const enabled = useControlsEnabled();
  const workflow = useResource<Workflow>(`overview-workflow-${pid}-${run.slug}`, (c) => calls.workflow(c, run.slug, pid), { project: pid, run: run.slug });
  const changes = useResource(`overview-changes-${pid}-${run.slug}`, (c) => calls.changes(c, run.slug, pid), { project: pid, run: run.slug });
  const action = useAction();
  const [dialog, setDialog] = useState<DialogState>(null);
  const [comment, setComment] = useState('');
  const [flash] = useState(() => takeFlash());
  useStateAnnouncer(workflow.data?.nodes);

  const nodes = workflow.data?.nodes ?? [];
  const active = !TERMINAL.has(run.state);
  const running = nodes.filter((n) => n.state === 'RUNNING').length;
  const retried = new Set(nodes.filter((n) => n.retry_of).map((n) => n.retry_of));
  const failed = active ? nodes.filter((n) => n.state === 'FAILED' && !retried.has(n.id)) : [];
  const queued = active ? nodes.filter((n) => n.state === 'QUEUED') : [];

  const close = () => {
    setDialog(null);
    setComment('');
  };
  const reloadAll = () => {
    onChanged();
    void workflow.reload();
    void changes.reload();
  };

  const send = async () => {
    if (!dialog) return;
    const trimmed = comment.trim();
    const body: Record<string, unknown> =
      dialog.kind === 'cancel-run'
        ? { action: 'cancel' }
        : dialog.kind === 'resume'
          ? { action: 'resume' }
          : dialog.kind === 'retry'
            ? { action: 'retry', task_id: dialog.id }
            : { action: 'cancel', task_id: dialog.id };
    if (trimmed && (dialog.kind === 'cancel-run' || dialog.kind === 'resume' || dialog.kind === 'cancel-task')) body.comment = trimmed;
    const kind = dialog.kind;
    await action.run(
      () => calls.control(app.client, run.slug, pid, body),
      (r) => (kind === 'retry' ? 'Retry queued' : kind === 'cancel-task' ? `Task cancelled. Run state ${r.state}` : `Run state ${r.state}`),
      {
        onError: (e: ApiError) => (e.code === 'E_TRANSITION' ? 'Refused: the run moved on.' : undefined),
        onSettled: () => {
          close();
          reloadAll();
        },
      },
    );
  };

  const dialogText =
    dialog?.kind === 'cancel-run'
      ? `Cancel run ${run.slug}? ${running === 1 ? '1 running task is' : `${running} running tasks are`} stopped. This cannot be undone.`
      : dialog?.kind === 'cancel-task'
        ? `Cancel task ${dialog.id}? This cannot be undone.`
        : dialog?.kind === 'retry'
          ? `Retry task ${dialog.id}? A new attempt is queued.`
          : `Resume run ${run.slug}? It continues from the state it had before it needed you.`;
  const needsComment = dialog?.kind === 'resume';

  return (
    <>
      {flash ? <ActionResult message={{ kind: 'ok', text: flash }} /> : null}
      <ActionResult message={action.message} />
      <NextBanner pid={pid} slug={run.slug} base={base} state={run.state} />
      <h2>Request</h2>
      <p className="pre-wrap" data-testid="run-request">{run.request}</p>
      {run.reason ? <p className="banner warn">Needs you: {run.reason}</p> : null}
      <h2>Controls</h2>
      <div className="row" data-testid="controls">
        {active ? (
          <button type="button" disabled={!enabled} onClick={() => setDialog({ kind: 'cancel-run' })}>
            Cancel run
          </button>
        ) : null}
        {run.state === 'NEEDS_HUMAN' ? (
          <button type="button" disabled={!enabled} onClick={() => setDialog({ kind: 'resume' })}>
            Resume
          </button>
        ) : null}
        {failed.map((n) => (
          <button type="button" key={`r-${n.id}`} disabled={!enabled} onClick={() => setDialog({ kind: 'retry', id: n.id })}>
            Retry {n.id}
          </button>
        ))}
        {queued.map((n) => (
          <button type="button" key={`c-${n.id}`} disabled={!enabled} onClick={() => setDialog({ kind: 'cancel-task', id: n.id })}>
            Cancel task {n.id}
          </button>
        ))}
        {!enabled ? <span className="hint">Controls are disabled while the connection is down.</span> : null}
      </div>
      {dialog ? (
        <ConfirmDialog
          text={dialogText}
          cancelLabel={dialog.kind === 'cancel-run' ? 'Keep running' : dialog.kind === 'cancel-task' ? 'Keep task' : 'Cancel'}
          confirmLabel={dialog.kind === 'cancel-run' ? 'Cancel run' : dialog.kind === 'cancel-task' ? 'Cancel task' : dialog.kind === 'resume' ? 'Resume' : 'Retry'}
          initialFocus={dialog.kind === 'resume' ? 'comment' : 'cancel'}
          danger={dialog.kind === 'cancel-run' || dialog.kind === 'cancel-task'}
          pending={action.pending}
          confirmDisabled={needsComment && comment.trim() === ''}
          onCancel={close}
          onConfirm={() => void send()}
        >
          {dialog.kind !== 'retry' ? (
            <div className="field">
              <label htmlFor="control-comment">Comment</label>
              <textarea id="control-comment" value={comment} onChange={(e) => setComment(e.target.value)} />
              {needsComment && comment.trim() === '' ? <p className="field-error">Say what was fixed</p> : <p className="hint">{needsComment ? 'Required' : 'Optional'}</p>}
            </div>
          ) : null}
        </ConfirmDialog>
      ) : null}
      <h2>Approvals</h2>
      <p>
        Specification: {run.approvals.specification.state}
        {run.approvals.specification.version ? ` version ${run.approvals.specification.version}` : ''} · Gherkin: {run.approvals.gherkin.state}
        {run.approvals.gherkin.version ? ` version ${run.approvals.gherkin.version}` : ''}
      </p>
      <h2>Tasks</h2>
      <p>{Object.entries(run.task_counts).map(([k, v]) => `${v} ${k}`).join(', ') || 'No tasks yet'}</p>
      <h2>Usage</h2>
      <div className="panel" data-testid="run-usage">
        {nodes.some((n) => n.tokens != null || n.cost != null || n.seconds != null) ? (
          <>
            <p>
              <strong>Total:</strong>{' '}
              {[
                nodes.reduce((acc, n) => acc + (n.tokens ?? 0), 0) > 0 ? `${nodes.reduce((acc, n) => acc + (n.tokens ?? 0), 0).toLocaleString()} tokens` : null,
                nodes.reduce((acc, n) => acc + (n.cost ?? 0), 0) > 0 ? `$${nodes.reduce((acc, n) => acc + (n.cost ?? 0), 0).toFixed(2)}` : null,
                nodes.reduce((acc, n) => acc + (n.seconds ?? 0), 0) > 0 ? `${Math.round(nodes.reduce((acc, n) => acc + (n.seconds ?? 0), 0))}s` : null,
              ].filter(Boolean).join(' · ')}
            </p>
            <h3>By model</h3>
            <table>
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  <th scope="col">Tokens</th>
                  <th scope="col">Cost</th>
                  <th scope="col">Tasks</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(
                  nodes.reduce<Record<string, { tokens: number; cost: number; tasks: number }>>((acc, n) => {
                    const m = n.model || 'unspecified';
                    const cur = acc[m] ?? { tokens: 0, cost: 0, tasks: 0 };
                    cur.tokens += n.tokens ?? 0;
                    cur.cost += n.cost ?? 0;
                    cur.tasks += 1;
                    acc[m] = cur;
                    return acc;
                  }, {})
                ).map(([m, d]) => (
                  <tr key={m}>
                    <th scope="row">{m}</th>
                    <td>{d.tokens ? d.tokens.toLocaleString() : '—'}</td>
                    <td>{d.cost ? `$${d.cost.toFixed(2)}` : '—'}</td>
                    <td>{d.tasks}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>Per task</h3>
            <table>
              <thead>
                <tr>
                  <th scope="col">Task</th>
                  <th scope="col">Role</th>
                  <th scope="col">Model</th>
                  <th scope="col">Tokens</th>
                  <th scope="col">Cost</th>
                  <th scope="col">Duration</th>
                </tr>
              </thead>
              <tbody>
                {nodes.filter((n) => n.tokens != null || n.cost != null || n.seconds != null).map((n) => (
                  <tr key={n.id}>
                    <th scope="row">{n.id}</th>
                    <td>{n.role}</td>
                    <td>{n.model || '—'}</td>
                    <td>{n.tokens != null ? n.tokens.toLocaleString() : '—'}</td>
                    <td>{n.cost != null ? `$${n.cost.toFixed(2)}` : '—'}</td>
                    <td>{n.seconds != null ? `${Math.round(n.seconds)}s` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p className="hint">No usage reported for this run.</p>
        )}
      </div>
      <h2>Changes</h2>
      <div data-testid="changes-summary">
        {changes.data ? (
          changes.data.repos.length ? (
            <ul className="plain">
              {changes.data.repos.map((r) => (
                <li key={r.id}>
                  {r.id}: {r.files_count} files, +{r.additions} -{r.deletions}
                </li>
              ))}
            </ul>
          ) : (
            <p>No changes yet</p>
          )
        ) : null}
        <Link to={`${base}/changes`}>Changes</Link>
      </div>
      <p className="hint">Created {formatTime(run.created_at)} · updated {formatTime(run.updated_at)}</p>
    </>
  );
}
