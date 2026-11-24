import { useEffect, useState, type CSSProperties } from 'react';
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

interface StationRow {
  role: string;
  name: string;
  tool: string;
  model: string;
}

const DEFAULT_STATIONS: StationRow[] = [
  { role: 'specifier', name: 'Spec writer', tool: 'Claude', model: 'claude-opus-5-5' },
  { role: 'test_designer', name: 'Scenario writer', tool: 'Antigravity', model: 'gemini-3.8-flash-high' },
  { role: 'tdd_red', name: 'Test writer', tool: 'Claude', model: 'claude-sonnet-5-5' },
  { role: 'tdd_green', name: 'Coder', tool: 'Claude', model: 'claude-sonnet-5-5' },
  { role: 'reviewer', name: 'Reviewer', tool: 'Claude', model: 'claude-opus-5-5' },
  { role: 'qa', name: 'QA', tool: 'Antigravity', model: 'gemini-3.8-flash-medium' },
];

function UnifiedSettings() {
  const app = useApp();
  const projectsRes = useResource('settings-projects', (c) => calls.projects(c), {});
  const availableProjects = projectsRes.data?.items.filter((p) => p.status === 'available') ?? [];
  const [selectedPid, setSelectedPid] = useState<string>('');
  const pid = selectedPid || availableProjects[0]?.id || '';
  const currentProject = availableProjects.find((p) => p.id === pid) || availableProjects[0];
  const projectName = currentProject?.name || pid || 'MEF-HR';

  const providersRes = useResource('settings-unified-providers', (c) => calls.providers(c), {});
  const formRes = useResource(`settings-unified-form-${pid}`, (c) => calls.configForm(c, pid), { project: pid }, !!pid);

  // Tools testing state
  const [testedTools, setTestedTools] = useState<Record<string, { status: 'testing' | 'works' | 'failed'; message?: string }>>({});

  // Team state: 'mix' | 'one' | 'custom'
  const [team, setTeam] = useState<'mix' | 'one' | 'custom'>('mix');
  const [stations, setStations] = useState<StationRow[]>(DEFAULT_STATIONS);

  // Orchestrator state
  const [selfAnswer, setSelfAnswer] = useState<boolean>(true);
  const [orchModel, setOrchModel] = useState<string>('Claude · claude-opus-5-5');

  // Notify state
  const [notifyDecision, setNotifyDecision] = useState<boolean>(true);
  const [notifyFinished, setNotifyFinished] = useState<boolean>(true);

  // Sync selfAnswer from config if present
  useEffect(() => {
    if (formRes.data?.sections) {
      const field = formRes.data.sections.flatMap((s) => s.fields).find((f) => f.path === 'orchestrator.answer_from_spec');
      if (field && typeof field.value === 'boolean') {
        setSelfAnswer(field.value);
      }
    }
  }, [formRes.data]);

  const handleTestTool = async (toolId: string) => {
    setTestedTools((prev) => ({ ...prev, [toolId]: { status: 'testing' } }));
    try {
      const res = await calls.providerTest(app.client, toolId);
      setTestedTools((prev) => ({
        ...prev,
        [toolId]: {
          status: res.ok ? 'works' : 'failed',
          message: res.message,
        },
      }));
    } catch (err: unknown) {
      setTestedTools((prev) => ({
        ...prev,
        [toolId]: {
          status: 'failed',
          message: err instanceof Error ? err.message : String(err),
        },
      }));
    }
  };

  const handlePickTeam = (picked: 'mix' | 'one' | 'custom') => {
    setTeam(picked);
    if (picked === 'mix') {
      setStations(DEFAULT_STATIONS);
    } else if (picked === 'one') {
      setStations(DEFAULT_STATIONS.map((s) => ({ ...s, tool: 'Claude', model: 'claude-sonnet-5-5' })));
    }
  };

  const handleStationChange = (role: string, field: 'tool' | 'model', val: string) => {
    setStations((prev) =>
      prev.map((s) => {
        if (s.role !== role) return s;
        if (field === 'tool') {
          const defaultModel = val === 'Antigravity' ? 'gemini-3.8-flash-high' : 'claude-sonnet-5-5';
          return { ...s, tool: val, model: defaultModel };
        }
        return { ...s, model: val };
      }),
    );
  };

  const handleToggleSelfAnswer = async () => {
    const nextVal = !selfAnswer;
    setSelfAnswer(nextVal);
    if (pid) {
      try {
        await calls.configSave(app.client, pid, [{ path: 'orchestrator.answer_from_spec', value: nextVal }], 'Toggle orchestrator.answer_from_spec');
      } catch {
        // ignore
      }
    }
  };

  const pillStyle = (on: boolean): CSSProperties => ({
    fontSize: '14px',
    padding: '10px 14px',
    borderRadius: '999px',
    cursor: 'pointer',
    font: 'inherit',
    border: on ? '2px solid #0F766E' : '1px solid #D6D5CF',
    background: on ? '#F1F7F6' : '#FFFFFF',
    color: '#1B1B19',
    fontWeight: on ? 600 : 400,
  });

  // Providers list
  const providerItems = providersRes.data?.items ?? [];
  const tools = providerItems.length > 0
    ? providerItems.map((p) => ({
        id: p.id,
        name: p.label || p.id,
        status: p.installed ? 'Installed · signed in' : 'Not installed',
        installed: p.installed,
      }))
    : [
        { id: 'claude', name: 'Claude', status: 'Installed · signed in', installed: true },
        { id: 'agy', name: 'Antigravity', status: 'Installed · signed in', installed: true },
      ];

  const teamHint =
    team === 'custom'
      ? 'Pick a tool and model per station. A tool that fails falls back to the next one.'
      : 'Switch to Custom to change a single station.';

  return (
    <div style={{ minHeight: '1000px', background: '#F6F6F3', fontFamily: 'Inter, system-ui, sans-serif', color: '#1B1B19', display: 'flex', flexDirection: 'column' }}>
      <div style={{ flex: 1, width: '100%', maxWidth: '880px', margin: '0 auto', boxSizing: 'border-box', padding: '32px 24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: '12px' }}>
          <h1 style={{ margin: 0, fontSize: '26px' }}>Settings</h1>
          <span style={{ fontSize: '15px', color: '#5A5A55' }}>
            for {projectName} · saved as you change them
          </span>
          {availableProjects.length > 1 ? (
            <select
              aria-label="Select project"
              value={pid}
              onChange={(e) => setSelectedPid(e.target.value)}
              style={{ fontSize: '14px', padding: '4px 8px', borderRadius: '6px', border: '1px solid #D6D5CF', marginLeft: 'auto' }}
            >
              {availableProjects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          ) : null}
        </div>

        {/* Section 1: AI tools on this computer */}
        <section style={{ background: '#FFFFFF', border: '1px solid #E4E3DE', borderRadius: '14px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <h2 style={{ margin: 0, fontSize: '17px' }}>AI tools on this computer</h2>
          {tools.map((t) => {
            const testState = testedTools[t.id];
            const testLabel = testState?.status === 'testing' ? 'Testing…' : testState?.status === 'works' ? 'Works' : 'Test';
            return (
              <div
                key={t.id}
                data-testid={`provider-${t.id}`}
                style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '12px', padding: '12px 14px', border: '1px solid #E4E3DE', borderRadius: '10px' }}
              >
                <span style={{ fontWeight: 600, fontSize: '15px', minWidth: '140px' }}>{t.name}</span>
                <span style={{ fontSize: '14px', color: t.installed ? '#0F5E57' : '#8A8984', flex: '1 1 200px' }}>{t.status}</span>
                <button
                  type="button"
                  aria-label={`Test ${t.name}`}
                  disabled={!t.installed || testState?.status === 'testing'}
                  onClick={() => void handleTestTool(t.id)}
                  style={{ fontSize: '14px', padding: '8px 12px', border: '1px solid #D6D5CF', background: '#FFFFFF', borderRadius: '8px', cursor: 'pointer' }}
                >
                  {testLabel}
                </button>
              </div>
            );
          })}
        </section>

        {/* Section 2: AI team */}
        <section style={{ background: '#FFFFFF', border: '1px solid #E4E3DE', borderRadius: '14px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <h2 style={{ margin: 0, fontSize: '17px' }}>AI team</h2>
          <div role="radiogroup" aria-label="AI team" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            <button
              type="button"
              role="radio"
              aria-checked={team === 'mix'}
              onClick={() => handlePickTeam('mix')}
              style={pillStyle(team === 'mix')}
            >
              Recommended mix
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={team === 'one'}
              onClick={() => handlePickTeam('one')}
              style={pillStyle(team === 'one')}
            >
              One AI for everything
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={team === 'custom'}
              onClick={() => handlePickTeam('custom')}
              style={pillStyle(team === 'custom')}
            >
              Custom
            </button>
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px', minWidth: '560px' }}>
              <thead>
                <tr style={{ textAlign: 'left', color: '#6B6B65' }}>
                  <th scope="col" style={{ padding: '8px 10px', fontWeight: 600 }}>Station</th>
                  <th scope="col" style={{ padding: '8px 10px', fontWeight: 600 }}>AI tool</th>
                  <th scope="col" style={{ padding: '8px 10px', fontWeight: 600 }}>Model</th>
                </tr>
              </thead>
              <tbody>
                {stations.map((s) => (
                  <tr key={s.role} style={{ borderTop: '1px solid #EEEDE8' }}>
                    <th scope="row" style={{ padding: '10px', textAlign: 'left', fontWeight: 500 }}>{s.name}</th>
                    <td style={{ padding: '10px' }}>
                      <select
                        aria-label={`${s.name} AI tool`}
                        disabled={team !== 'custom'}
                        value={s.tool}
                        onChange={(e) => handleStationChange(s.role, 'tool', e.target.value)}
                        style={{ fontSize: '14px', padding: '7px 9px', border: '1px solid #D6D5CF', borderRadius: '8px', background: '#FFFFFF' }}
                      >
                        <option value="Claude">Claude</option>
                        <option value="Antigravity">Antigravity</option>
                        <option value="Codex">Codex</option>
                      </select>
                    </td>
                    <td style={{ padding: '10px' }}>
                      <select
                        aria-label={`${s.name} model`}
                        disabled={team !== 'custom'}
                        value={s.model}
                        onChange={(e) => handleStationChange(s.role, 'model', e.target.value)}
                        style={{ fontSize: '14px', padding: '7px 9px', border: '1px solid #D6D5CF', borderRadius: '8px', background: '#FFFFFF' }}
                      >
                        {s.tool === 'Antigravity' ? (
                          <>
                            <option value="gemini-3.8-flash-high">gemini-3.8-flash-high</option>
                            <option value="gemini-3.8-flash-medium">gemini-3.8-flash-medium</option>
                            <option value="gemini-3.8-pro">gemini-3.8-pro</option>
                          </>
                        ) : s.tool === 'Codex' ? (
                          <>
                            <option value="gpt-5">gpt-5</option>
                            <option value="gpt-5-mini">gpt-5-mini</option>
                          </>
                        ) : (
                          <>
                            <option value="claude-opus-5-5">claude-opus-5-5</option>
                            <option value="claude-sonnet-5-5">claude-sonnet-5-5</option>
                            <option value="claude-haiku-4-5">claude-haiku-4-5</option>
                          </>
                        )}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: '13px', color: '#5A5A55' }}>{teamHint}</div>
        </section>

        {/* Section 3: Orchestrator */}
        <section style={{ background: '#FFFFFF', border: '1px solid #E4E3DE', borderRadius: '14px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <h2 style={{ margin: 0, fontSize: '17px' }}>Orchestrator</h2>
          <p style={{ margin: 0, fontSize: '14px', lineHeight: 1.5, color: '#3D3D39' }}>
            Agents ask the orchestrator when they are unsure. It brings real decisions to you as a card on the floor.
          </p>
          <label style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '15px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={selfAnswer}
              onChange={() => void handleToggleSelfAnswer()}
              style={{ width: '18px', height: '18px', accentColor: '#0F766E' }}
            />
            Answer from the approved spec when it settles the question, and show me which section it used
          </label>
          <label style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '10px', fontSize: '15px' }}>
            Orchestrator model
            <select
              aria-label="Orchestrator model"
              value={orchModel}
              onChange={(e) => setOrchModel(e.target.value)}
              style={{ fontSize: '14px', padding: '8px 10px', border: '1px solid #D6D5CF', borderRadius: '8px', background: '#FFFFFF' }}
            >
              <option value="Claude · claude-opus-5-5">Claude · claude-opus-5-5</option>
              <option value="Claude · claude-sonnet-5-5">Claude · claude-sonnet-5-5</option>
              <option value="Antigravity · gemini-3.8-flash-high">Antigravity · gemini-3.8-flash-high</option>
              <option value="Codex · gpt-5">Codex · gpt-5</option>
            </select>
          </label>
        </section>

        {/* Section 4: Notify me */}
        <section style={{ background: '#FFFFFF', border: '1px solid #E4E3DE', borderRadius: '14px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <h2 style={{ margin: 0, fontSize: '17px' }}>Notify me</h2>
          <label style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '15px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={notifyDecision}
              onChange={(e) => setNotifyDecision(e.target.checked)}
              style={{ width: '18px', height: '18px', accentColor: '#0F766E' }}
            />
            When the orchestrator needs a decision
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '15px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={notifyFinished}
              onChange={(e) => setNotifyFinished(e.target.checked)}
              style={{ width: '18px', height: '18px', accentColor: '#0F766E' }}
            />
            When a task is finished
          </label>
        </section>

        {/* Section 5: Advanced folded */}
        <details style={{ background: '#FFFFFF', border: '1px solid #E4E3DE', borderRadius: '14px', padding: '18px 24px', fontSize: '15px' }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Advanced</summary>
          <ul style={{ margin: '12px 0 0', paddingLeft: '20px', lineHeight: 1.9, fontSize: '14px' }}>
            <li>
              <Link to="/settings/config">Edit sentinel.config.yaml</Link> (history kept)
            </li>
            <li>
              <Link to="/settings/service">Retries, time limits and test commands per repo</Link>
            </li>
            <li>
              <Link to="/settings/installation">Installation and service details</Link> (<Link to="/settings/installation">Sentinel installation</Link>)
            </li>
            <li>
              <Link to="/settings/runtime">Runtime connection</Link>
            </li>
            <li>
              <Link to="/settings/health">Health checks</Link>
            </li>
          </ul>
        </details>
      </div>
    </div>
  );
}

export function SettingsScreen({ page }: { page?: string }) {
  if (!page || page === 'index' || page === 'settings') {
    return <UnifiedSettings />;
  }

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
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
        <Link to="/settings" style={{ fontSize: '14px', textDecoration: 'none', color: 'var(--link)', fontWeight: 500 }}>
          ← Back to Settings
        </Link>
      </div>
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
