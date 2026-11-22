// "Fix routing": a banner for projects whose routing blocks engine runs, and the dialog that fixes it.
// The dialog suggests one runner and model per blocked role (the setup wizard's suggestion), lets the owner edit them,
// previews the YAML change and saves through the same config route as Project settings (with history).
import { useEffect, useState } from 'react';
import { calls } from '../api/calls.ts';
import type { WRoutingFix } from '../api/wire.ts';
import type { Provider } from '../api/orchestration.ts';
import { ActionResult, ConfirmDialog, useAction } from './common.tsx';
import { UnifiedText } from './DiffView.tsx';
import { useApp } from '../state/app.tsx';

interface Row {
  role: string;
  text: string;
  runner: string;
  model: string;
}

function changesOf(rows: Row[]): { path: string; value: unknown }[] {
  const out: { path: string; value: unknown }[] = [{ path: 'single_model', value: false }];
  for (const r of rows) {
    out.push({ path: `agents.${r.role}.runner`, value: r.runner });
    out.push({ path: `agents.${r.role}.model`, value: r.model.trim() || null });
  }
  return out;
}

function FixRoutingDialog({ pid, onClose, onSaved }: { pid: string; onClose: () => void; onSaved: () => void }) {
  const app = useApp();
  const load = useAction();
  const preview = useAction();
  const save = useAction();
  const [fix, setFix] = useState<WRoutingFix | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [diff, setDiff] = useState<string | null>(null);

  useEffect(() => {
    void load
      .run(
        async () => {
          const [f, p] = await Promise.all([calls.routingFix(app.client, pid), calls.providers(app.client, pid)]);
          setFix(f);
          setProviders(p.items);
          setRows(f.problems.map((r) => ({ role: r.role, text: r.text, runner: r.suggested.runner, model: r.suggested.model ?? '' })));
          return f;
        },
        () => 'Suggestion loaded',
      );
    // load once when the dialog opens
  }, []);

  const edit = (i: number, patch: Partial<Row>) => {
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    setDiff(null);
  };
  const runnerIds = Array.from(new Set([...providers.map((p) => p.id), ...rows.map((r) => r.runner)]));

  const doPreview = () =>
    preview.run(
      () => calls.configPreview(app.client, pid, changesOf(rows)),
      (r) => {
        setDiff(r.diff);
        return 'Preview ready';
      },
    );
  const doSave = () =>
    save.run(
      () => calls.configSave(app.client, pid, changesOf(rows), 'Fix routing'),
      () => 'Routing saved',
    ).then((r) => {
      if (r !== undefined) {
        onSaved();
        onClose();
      }
    });

  return (
    <ConfirmDialog
      text="Fix routing: pick the runner and model each role uses"
      confirmLabel="Save"
      cancelLabel="Cancel"
      pending={save.pending}
      confirmDisabled={!fix || rows.length === 0}
      onCancel={onClose}
      onConfirm={() => void doSave()}
    >
      <div data-testid="fix-routing-dialog">
        {load.error ? <p className="banner danger">{load.message?.text}</p> : null}
        <table data-testid="fix-routing-table">
          <thead>
            <tr>
              <th scope="col">Role</th>
              <th scope="col">Runner</th>
              <th scope="col">Model</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const models = providers.find((p) => p.id === r.runner)?.models ?? [];
              return (
                <tr key={r.role}>
                  <th scope="row" title={r.text}>{r.role}</th>
                  <td>
                    <select aria-label={`Runner for ${r.role}`} value={r.runner} onChange={(e) => edit(i, { runner: e.target.value, model: '' })}>
                      {runnerIds.map((id) => (
                        <option key={id} value={id}>{id}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="text"
                      aria-label={`Model for ${r.role}`}
                      list={`fix-models-${r.role}`}
                      value={r.model}
                      placeholder="provider default"
                      autoComplete="off"
                      onChange={(e) => edit(i, { model: e.target.value })}
                    />
                    <datalist id={`fix-models-${r.role}`}>
                      {models.map((m) => (
                        <option key={m.id} value={m.id}>{m.label}</option>
                      ))}
                    </datalist>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="row">
          <button type="button" className="secondary" disabled={preview.pending || rows.length === 0} onClick={() => void doPreview()}>
            Preview the YAML change
          </button>
        </div>
        {diff !== null ? (diff ? <UnifiedText text={diff} /> : <p>No change to sentinel.config.yaml</p>) : null}
        <ActionResult message={preview.error ? preview.message : save.error ? save.message : null} />
      </div>
    </ConfirmDialog>
  );
}

/** Shown while engine runs are blocked by the routing of the project. `problems` comes from the factory snapshot. */
export function RoutingBanner({ pid, problems, onFixed }: { pid: string; problems: string[]; onFixed: () => void }) {
  const [open, setOpen] = useState(false);
  if (problems.length === 0) return null;
  return (
    <section className="banner warn" role="status" data-testid="fix-routing-banner" aria-label="Routing problem">
      <p>
        <strong>Engine runs cannot start.</strong> {problems.length} role{problems.length === 1 ? '' : 's'} {problems.length === 1 ? 'does' : 'do'} not
        route to a CLI runner: {problems.slice(0, 3).join('; ')}
        {problems.length > 3 ? `; and ${problems.length - 3} more` : ''}.
      </p>
      <div className="row">
        <button type="button" onClick={() => setOpen(true)}>Fix routing</button>
      </div>
      {open ? <FixRoutingDialog pid={pid} onClose={() => setOpen(false)} onSaved={onFixed} /> : null}
    </section>
  );
}
