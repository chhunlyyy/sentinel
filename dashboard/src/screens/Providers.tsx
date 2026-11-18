import { useEffect, useState } from 'react';
import { calls } from '../api/calls.ts';
import type { ProbeResult, Provider } from '../api/orchestration.ts';
import { ActionResult, Loaded, StatusChip, useAction } from '../components/common.tsx';
import { notifyOrchestratorChanged } from '../state/orchestrator.ts';
import { useApp, useResource } from '../state/app.tsx';

function ProviderCard({ p, isOrchestrator }: { p: Provider; isOrchestrator: boolean }) {
  const app = useApp();
  const test = useAction();
  const [result, setResult] = useState<ProbeResult | null>(null);
  const caps = [p.capabilities.model_select ? 'model choice' : null, p.capabilities.resume ? 'resume' : null, p.capabilities.json_output ? 'JSON output' : null].filter(Boolean);
  return (
    <li className="card provider-card" data-testid={`provider-${p.id}`}>
      <div className="card-head">
        <h3>{p.label}</h3>
        <span className="chip mono">{p.id}</span>
        {p.installed ? <StatusChip kind="ok" label="Installed" /> : <StatusChip kind="none" label="Not installed" />}
        {isOrchestrator ? <span className="chip accent">Orchestrator</span> : null}
      </div>
      <dl className="kv">
        <dt>Command</dt>
        <dd>
          <code>{p.command}</code>
        </dd>
        <dt>Path</dt>
        <dd>{p.path ? <code>{p.path}</code> : <span className="hint">not found on PATH</span>}</dd>
        <dt>Supports</dt>
        <dd>{caps.length ? caps.join(', ') : 'nothing extra'}</dd>
      </dl>
      <div className="row">
        <button
          type="button"
          className="secondary"
          disabled={!p.installed || test.pending}
          aria-label={`Test ${p.label}`}
          onClick={() =>
            void test.run(
              async () => {
                const r = await calls.providerTest(app.client, p.id);
                setResult(r);
                return r;
              },
              (r) => (r.ok ? `${p.label} answered: ${r.message}` : `${p.label} did not pass: ${r.message}`),
            )
          }
        >
          {test.pending ? 'Testing' : 'Test'}
        </button>
        {result ? <StatusChip kind={result.ok ? 'ok' : 'fail'} label={result.ok ? 'Works' : 'Failed'} /> : null}
      </div>
      <div data-testid={`provider-result-${p.id}`}>
        <ActionResult message={test.message} />
      </div>
    </li>
  );
}

export function ProvidersPage() {
  const app = useApp();
  const res = useResource('settings-providers', (c) => calls.providers(c), {});
  const orch = useResource('settings-orchestrator', (c) => calls.orchestrator(c), {});
  const save = useAction();
  const [choice, setChoice] = useState<string>('');
  const current = orch.data?.id ?? null;
  useEffect(() => {
    if (orch.data) setChoice(orch.data.id ?? '');
  }, [orch.data?.id]);
  const labelOf = (id: string | null) => (id ? (res.data?.items.find((p) => p.id === id)?.label ?? id) : 'None');

  return (
    <>
      <h2>Providers</h2>
      <p className="lede">The AI tools installed on this machine. A provider runs the agent roles of a project.</p>
      <section className="card" aria-labelledby="orch-h">
        <h3 id="orch-h">Orchestrator</h3>
        <p>
          The orchestrator is the AI tool Sentinel starts to drive dashboard runs when a step needs an AI tool. Current:{' '}
          <strong data-testid="orchestrator-current">{labelOf(current)}</strong>
        </p>
        <Loaded res={orch}>
          {(o) => (
            <div className="row">
              <div className="field inline">
                <label htmlFor="orch-select">Orchestrator</label>
                <select id="orch-select" value={choice} onChange={(e) => setChoice(e.target.value)}>
                  <option value="">None (a person resumes runs in the terminal)</option>
                  {o.installed_ids.map((id) => (
                    <option key={id} value={id}>
                      {labelOf(id)} ({id})
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                disabled={save.pending || choice === (o.id ?? '')}
                onClick={() =>
                  void save.run(
                    async () => {
                      const r = await calls.setOrchestrator(app.client, choice || null);
                      await orch.reload();
                      await res.reload();
                      notifyOrchestratorChanged();
                      return r;
                    },
                    (r) => (r.id ? `Orchestrator set to ${labelOf(r.id)}` : 'Orchestrator cleared'),
                  )
                }
              >
                Set orchestrator
              </button>
            </div>
          )}
        </Loaded>
        <ActionResult message={save.message} />
        <p className="hint">The choice lasts until the server stops. Start sentinel dashboard with a provider name to pick it at launch.</p>
      </section>
      <Loaded res={res}>
        {(a) =>
          a.items.length === 0 ? (
            <div className="empty">
              <p>No provider known</p>
            </div>
          ) : (
            <ul className="plain card-grid">
              {a.items.map((p) => (
                <ProviderCard key={p.id} p={p} isOrchestrator={a.orchestrator === p.id} />
              ))}
            </ul>
          )
        }
      </Loaded>
    </>
  );
}
