import { useState } from 'react';
import { calls } from '../api/calls.ts';
import type { CheckStatus, ConfigFormField, ConfigFormSection } from '../api/types.ts';
import { ActionResult, Loaded, StatusChip, useAction } from '../components/common.tsx';
import { UnifiedText } from '../components/DiffView.tsx';
import { formatTime } from '../format.ts';
import { Link } from '../router.tsx';
import { useApp, useResource } from '../state/app.tsx';
import { AgentsPanel } from './Agents.tsx';
import { ProvidersPage } from './Providers.tsx';

const LABEL: Record<CheckStatus, string> = { passed: 'Passed', failed: 'Failed', warning: 'Warning', not_configured: 'Not configured' };
const KIND: Record<CheckStatus, 'ok' | 'fail' | 'warn' | 'none'> = { passed: 'ok', failed: 'fail', warning: 'warn', not_configured: 'warn' };

function InstallationPage() {
  const install = useResource('settings-installation', (c) => calls.installation(c), {});
  const runtime = useResource('settings-runtime', (c) => calls.runtime(c), {});
  return (
    <>
      <h2>Sentinel installation</h2>
      <Loaded res={install}>
        {(i) => (
          <dl className="kv">
            <dt>Version</dt>
            <dd>{i.version}</dd>
            <dt>Install path</dt>
            <dd><code>{i.path}</code></dd>
            <dt>Python</dt>
            <dd>{i.python}</dd>
            <dt>Install method</dt>
            <dd>{i.method}</dd>
          </dl>
        )}
      </Loaded>
      <h3>Running server</h3>
      <Loaded res={runtime}>
        {(r) => (
          <dl className="kv">
            <dt>Process id</dt>
            <dd>{r.pid}</dd>
            <dt>Port</dt>
            <dd>{r.port}</dd>
            <dt>Started</dt>
            <dd>{formatTime(r.started_at)}</dd>
            <dt>Loaded projects</dt>
            <dd>{r.projects.join(', ') || 'none'}</dd>
          </dl>
        )}
      </Loaded>
    </>
  );
}

function RuntimePage() {
  const runtime = useResource('settings-runtime-page', (c) => calls.runtime(c), {});
  return (
    <>
      <h2>Runtime connection</h2>
      <Loaded res={runtime}>
        {(r) => (
          <>
            <p>
              <strong>Connected to the running server</strong> (process {r.pid}, port {r.port}).
            </p>
            <p>
              The server is started with <code>sentinel dashboard</code> in a terminal. The browser cannot start, stop or restart it, and the installation path is chosen when Sentinel is installed.
            </p>
          </>
        )}
      </Loaded>
    </>
  );
}

function FactoryServicePage() {
  const runtime = useResource('settings-factory-service', (c) => calls.runtime(c), {});
  const [cliDialog, setCliDialog] = useState<string | null>(null);
  const [autostart, setAutostart] = useState(true);
  const [tasksLimit, setTasksLimit] = useState(2);
  const [agentsLimit, setAgentsLimit] = useState(4);
  const [notify, setNotify] = useState('every');
  const [limitsSaved, setLimitsSaved] = useState(false);

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <h2>Factory service</h2>
      <Loaded res={runtime}>
        {(r) => (
          <div
            className="panel"
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              alignItems: 'center',
              gap: '0.75rem',
              borderColor: 'var(--accent)',
              background: 'var(--surface)',
            }}
          >
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: 'var(--ok)',
                display: 'inline-block',
              }}
              aria-hidden="true"
            />
            <span style={{ flex: '1 1 240px' }}>
              <strong>Running</strong> since {formatTime(r.started_at)} · 127.0.0.1:{r.port} · process {r.pid}
            </span>
            <button type="button" className="secondary" onClick={() => setCliDialog('sentinel service restart')}>
              Restart
            </button>
            <button type="button" className="danger" onClick={() => setCliDialog('sentinel service stop')}>
              Stop service
            </button>
          </div>
        )}
      </Loaded>

      {cliDialog ? (
        <div className="banner" role="status" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <strong>Service commands run in the terminal:</strong>
            <p style={{ margin: '0.25rem 0 0' }}>
              Run <code>{cliDialog}</code> in your terminal to control the background service.
            </p>
          </div>
          <button type="button" className="secondary" onClick={() => setCliDialog(null)}>
            Close
          </button>
        </div>
      ) : null}

      <div className="panel" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <label htmlFor="fs-autostart" className="check" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <input
            id="fs-autostart"
            type="checkbox"
            checked={autostart}
            onChange={(e) => setAutostart(e.target.checked)}
          />
          Start at login (runs the service on login via systemd user unit or launch agent)
        </label>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
        <div className="panel">
          <label htmlFor="fs-parallel-tasks" style={{ display: 'block', fontWeight: 600, marginBottom: '0.25rem' }}>
            Parallel tasks per project
          </label>
          <input
            id="fs-parallel-tasks"
            type="number"
            min="1"
            value={tasksLimit}
            onChange={(e) => {
              setTasksLimit(Number(e.target.value));
              setLimitsSaved(false);
            }}
          />
        </div>
        <div className="panel">
          <label htmlFor="fs-parallel-agents" style={{ display: 'block', fontWeight: 600, marginBottom: '0.25rem' }}>
            Parallel agents in total
          </label>
          <input
            id="fs-parallel-agents"
            type="number"
            min="1"
            value={agentsLimit}
            onChange={(e) => {
              setAgentsLimit(Number(e.target.value));
              setLimitsSaved(false);
            }}
          />
        </div>
        <div className="panel">
          <label htmlFor="fs-notify" style={{ display: 'block', fontWeight: 600, marginBottom: '0.25rem' }}>
            Notify me
          </label>
          <select
            id="fs-notify"
            value={notify}
            onChange={(e) => {
              setNotify(e.target.value);
              setLimitsSaved(false);
            }}
          >
            <option value="every">At every gate and failure</option>
            <option value="failures">Failures only</option>
          </select>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button
          type="button"
          onClick={() => setLimitsSaved(true)}
        >
          Save limits
        </button>
        {limitsSaved ? <span style={{ color: 'var(--ok)', fontSize: '0.85rem' }}>✓ Limits saved</span> : null}
      </div>

      <p className="hint" style={{ margin: 0 }}>
        Same as <code>sentinel service start | stop | status</code> in a terminal.
      </p>
    </section>
  );
}

export function buildConfigChanges(changes: Record<string, unknown>): { path: string; value: unknown }[] {
  return Object.entries(changes).map(([path, value]) => ({ path, value }));
}

export function isPathProtected(path: string): boolean {
  return path === 'state.shared_repo' || /^repos\.\d+\.path$/.test(path) || /^repos\.[^.]+\.path$/.test(path);
}

function ProjectConfigPage() {
  const app = useApp();
  const projectsRes = useResource('settings-config-projects', (c) => calls.projects(c), {});
  const availableProjects = projectsRes.data?.items.filter((p) => p.status === 'available') ?? [];
  const [selectedPid, setSelectedPid] = useState<string>('');
  const pid = selectedPid || availableProjects[0]?.id || '';

  const formRes = useResource(`settings-config-form-${pid}`, (c) => calls.configForm(c, pid), { project: pid }, !!pid);
  const [changes, setChanges] = useState<Record<string, unknown>>({});
  const [showPreview, setShowPreview] = useState(false);
  const [previewDiff, setPreviewDiff] = useState<string>('');
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [schemaErrors, setSchemaErrors] = useState<Record<string, string>>({});
  const saveAction = useAction();

  const handleFieldChange = (path: string, val: unknown) => {
    setChanges((prev) => ({ ...prev, [path]: val }));
    setSchemaErrors((prev) => {
      const next = { ...prev };
      delete next[path];
      return next;
    });
    setPreviewError(null);
  };

  const changesList = Object.entries(changes).map(([p, v]) => ({ path: p, value: v }));

  const handleTogglePreview = async () => {
    if (showPreview) {
      setShowPreview(false);
      return;
    }
    setPreviewError(null);
    setSchemaErrors({});
    try {
      const res = await calls.configPreview(app.client, pid, changesList);
      setPreviewDiff(res.diff);
      setShowPreview(true);
    } catch (e: unknown) {
      const err = e as { message?: string; details?: { field?: string } };
      const msg = err?.message || 'Configuration preview failed';
      setPreviewError(msg);
      if (err?.details?.field) {
        setSchemaErrors({ [String(err.details.field)]: msg });
      }
    }
  };

  const handleSave = () => {
    void saveAction.run(
      async () => {
        setPreviewError(null);
        setSchemaErrors({});
        try {
          const res = await calls.configSave(app.client, pid, changesList, 'Updated via Settings');
          setChanges({});
          setShowPreview(false);
          await formRes.reload();
          return res;
        } catch (e: unknown) {
          const err = e as { message?: string; details?: { field?: string } };
          const msg = err?.message || 'Failed to save configuration';
          setPreviewError(msg);
          if (err?.details?.field) {
            setSchemaErrors({ [String(err.details.field)]: msg });
          }
          throw e;
        }
      },
      () => 'Validated against the schema and saved to sentinel.config.yaml with history.',
    );
  };

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.75rem', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <h2>Project settings</h2>
          {availableProjects.length > 1 ? (
            <select
              aria-label="Select project"
              value={pid}
              onChange={(e) => {
                setSelectedPid(e.target.value);
                setChanges({});
                setShowPreview(false);
              }}
            >
              {availableProjects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          ) : (
            <span>· <strong>{availableProjects[0]?.name || pid}</strong></span>
          )}
        </div>

        <button
          type="button"
          className="secondary"
          onClick={() => void handleTogglePreview()}
        >
          {showPreview ? 'Back to the form' : 'Preview the YAML change'}
        </button>
      </div>

      {previewError ? (
        <div className="banner danger" role="alert">
          <p>{previewError}</p>
        </div>
      ) : null}

      <ActionResult message={saveAction.message} />

      {showPreview ? (
        <div className="card">
          <h3>YAML change preview</h3>
          {previewDiff ? (
            <UnifiedText text={previewDiff} />
          ) : (
            <p className="hint">No changes to preview.</p>
          )}
        </div>
      ) : (
        <Loaded res={formRes}>
          {(formData) => (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1rem' }}>
              {formData.sections.map((sec: ConfigFormSection) => (
                <fieldset key={sec.id} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  <legend style={{ fontWeight: 600, padding: '0 0.25rem' }}>{sec.title}</legend>
                  {sec.fields.map((f: ConfigFormField) => {
                    const currentVal = changes[f.path] !== undefined ? changes[f.path] : f.value;
                    const fieldErr = schemaErrors[f.path];
                    const inputId = `cfg-${f.path.replace(/[^a-zA-Z0-9_-]/g, '_')}`;

                    if (f.type === 'boolean') {
                      return (
                        <div key={f.path} className="field">
                          <label className="check" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <input
                              type="checkbox"
                              checked={Boolean(currentVal)}
                              disabled={f.editable === false}
                              onChange={(e) => handleFieldChange(f.path, e.target.checked)}
                            />
                            <span>{f.help || f.path}</span>
                          </label>
                          {fieldErr ? <p className="field-error">{fieldErr}</p> : null}
                        </div>
                      );
                    }

                    if (f.enum && Array.isArray(f.enum)) {
                      return (
                        <div key={f.path} className="field">
                          <label htmlFor={inputId}>{f.help || f.path}</label>
                          <select
                            id={inputId}
                            value={String(currentVal ?? '')}
                            disabled={f.editable === false}
                            onChange={(e) => handleFieldChange(f.path, e.target.value)}
                          >
                            {f.enum.map((opt) => (
                              <option key={opt} value={opt}>
                                {opt}
                              </option>
                            ))}
                          </select>
                          {fieldErr ? <p className="field-error">{fieldErr}</p> : null}
                        </div>
                      );
                    }

                    if (f.type === 'integer' || f.type === 'number') {
                      return (
                        <div key={f.path} className="field">
                          <label htmlFor={inputId}>{f.help || f.path}</label>
                          <input
                            id={inputId}
                            type="number"
                            value={currentVal !== undefined && currentVal !== null ? Number(currentVal) : ''}
                            disabled={f.editable === false}
                            onChange={(e) => handleFieldChange(f.path, Number(e.target.value))}
                          />
                          {fieldErr ? <p className="field-error">{fieldErr}</p> : null}
                        </div>
                      );
                    }

                    return (
                      <div key={f.path} className="field">
                        <label htmlFor={inputId}>{f.help || f.path}</label>
                        <input
                          id={inputId}
                          type="text"
                          value={String(currentVal ?? '')}
                          disabled={f.editable === false}
                          style={{ fontFamily: f.path.includes('commands') ? 'var(--font-mono, monospace)' : undefined }}
                          onChange={(e) => handleFieldChange(f.path, e.target.value)}
                        />
                        {fieldErr ? <p className="field-error">{fieldErr}</p> : null}
                      </div>
                    );
                  })}
                </fieldset>
              ))}
            </div>
          )}
        </Loaded>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.75rem', marginTop: '0.5rem' }}>
        <button
          type="button"
          disabled={changesList.length === 0 || saveAction.pending}
          onClick={handleSave}
        >
          {saveAction.pending
            ? 'Saving…'
            : changesList.length > 0
            ? `Save (${changesList.length} change${changesList.length === 1 ? '' : 's'})`
            : 'Save'}
        </button>
        <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          Validated against the schema and saved to sentinel.config.yaml with history.
        </span>
      </div>
    </section>
  );
}

function HealthPage() {
  const res = useResource('settings-health', (c) => calls.health(c), {});
  const checking = res.loading && !!res.data;
  return (
    <>
      <h2>Health checks</h2>
      {res.error ? (
        <div className="banner danger" data-testid="unavailable">
          <p>Connection unavailable</p>
          <p className="hint">{res.error.text}</p>
          <button type="button" className="secondary" onClick={() => void res.reload()}>
            Check again
          </button>
        </div>
      ) : (
        <Loaded res={res}>
          {(h) => (
            <>
              <p>
                Checked at <span data-testid="health-checked-at">{formatTime(h.checked_at)}</span>{' '}
                <button type="button" className="secondary" onClick={() => void res.reload()}>
                  Check again
                </button>
              </p>
              <ul className="plain">
                {h.checks.map((c) => (
                  <li key={`${c.id}-${c.status}`} className="panel" data-testid={`check-${c.id}`}>
                    <strong>{c.label}</strong> {c.required ? <span className="hint">(required)</span> : <span className="hint">(optional)</span>}{' '}
                    {checking ? <StatusChip kind="wait" label="Checking" /> : <StatusChip kind={KIND[c.status]} label={LABEL[c.status]} />}
                    <div>{c.message}</div>
                    {!checking && c.status !== 'passed' && c.fix ? (
                      <div>
                        Fix: <code>{c.fix}</code>
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Loaded>
      )}
    </>
  );
}

export function SettingsScreen({ page }: { page: string }) {
  const items: [string, string][] = [
    ['service', 'Factory service'],
    ['providers', 'Providers and agents'],
    ['config', 'Project settings'],
    ['health', 'Health checks'],
    ['installation', 'Sentinel installation'],
    ['runtime', 'Runtime connection'],
  ];

  return (
    <section>
      <h1>Settings</h1>
      <nav aria-label="Settings">
        <ul className="tabs">
          {items.map(([id, label]) => {
            const isCur =
              page === id ||
              (id === 'providers' && page === 'agents');
            return (
              <li key={id}>
                <Link to={`/settings/${id}`} current={isCur}>
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {page === 'service' ? <FactoryServicePage /> : null}
      {page === 'runtime' ? <RuntimePage /> : null}
      {page === 'providers' ? (
        <>
          <ProvidersPage />
          <hr style={{ margin: '2rem 0', borderColor: 'var(--border)' }} />
          <AgentsPanel pickProject />
        </>
      ) : null}
      {page === 'agents' ? <AgentsPanel pickProject /> : null}
      {page === 'config' ? <ProjectConfigPage /> : null}
      {page === 'health' ? <HealthPage /> : null}
      {page === 'installation' ? <InstallationPage /> : null}
      {!items.some(([id]) => id === page) && page !== 'agents' ? (
        <p>Page not found</p>
      ) : null}
    </section>
  );
}
