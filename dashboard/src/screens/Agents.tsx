import { useEffect, useState } from 'react';
import { calls } from '../api/calls.ts';
import type { ApiError } from '../api/errors.ts';
import type { AgentsAnswer, Provider, SaveAgentsBody } from '../api/orchestration.ts';
import { ErrorView } from '../components/ErrorView.tsx';
import { ActionResult, Loaded, useAction } from '../components/common.tsx';
import { prefix } from '../format.ts';
import { Link } from '../router.tsx';
import { useApp, useResource } from '../state/app.tsx';

type Scope = 'project' | 'global';
interface Row {
  runner: string;
  model: string;
  custom?: boolean;
}

const CUSTOM = '__custom__';

/** Model control of one role: a select of the provider's models, "Custom..." for any other id. */
export function ModelControl({ roleName, provider, row, onChange }: { roleName: string; provider: Provider | undefined; row: Row; onChange: (model: string, custom: boolean) => void }) {
  const models = provider?.models ?? [];
  if (provider && !provider.capabilities.model_select) {
    return (
      <>
        <select aria-label={`Model for ${roleName}`} disabled value="">
          <option value="">Provider default</option>
        </select>
        <p className="hint">{provider.label} has no model option.</p>
      </>
    );
  }
  if (models.length === 0) {
    return <input type="text" aria-label={`Model for ${roleName}`} value={row.model} placeholder="provider default" autoComplete="off" onChange={(e) => onChange(e.target.value, false)} />;
  }
  const known = row.model === '' || models.some((m) => m.id === row.model);
  const custom = !!row.custom || !known;
  return (
    <>
      <select
        aria-label={`Model for ${roleName}`}
        value={custom ? CUSTOM : row.model}
        onChange={(e) => (e.target.value === CUSTOM ? onChange(known ? '' : row.model, true) : onChange(e.target.value, false))}
      >
        <option value="">Provider default</option>
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
        <option value={CUSTOM}>Custom...</option>
      </select>
      {custom ? (
        <div className="field">
          <label htmlFor={`custom-model-${roleName}`}>Custom model id</label>
          <input id={`custom-model-${roleName}`} type="text" aria-label={`Custom model id for ${roleName}`} value={row.model} autoComplete="off" onChange={(e) => onChange(e.target.value, true)} />
        </div>
      ) : null}
    </>
  );
}

const SOURCE_LABEL = { default: 'Built-in default', global: 'Global default', project: 'Project' } as const;

function rowsFrom(a: AgentsAnswer, scope: Scope): Record<string, Row> {
  const out: Record<string, Row> = {};
  for (const role of a.roles) {
    const it = a.items.find((i) => i.role === role);
    // only values that live at the level being edited are prefilled; the rest are inherited
    const own = it && it.source === scope;
    out[role] = { runner: own ? (it.runner ?? '') : '', model: own ? (it.model ?? '') : '' };
  }
  return out;
}

function Editor({ data, scope, pid, providers, onSaved, onReload }: { data: AgentsAnswer; scope: Scope; pid: string | null; providers: Provider[]; onSaved: (a: AgentsAnswer) => void; onReload: () => void }) {
  const app = useApp();
  const save = useAction();
  const [rows, setRows] = useState(() => rowsFrom(data, scope));
  const [def, setDef] = useState(data.providers.default ?? '');
  const [fallback, setFallback] = useState<string[]>(data.providers.fallback);
  const [disabled, setDisabled] = useState<string[]>(data.providers.disabled);
  const [single, setSingle] = useState(data.single_model);
  const [stale, setStale] = useState(false);

  useEffect(() => {
    setRows(rowsFrom(data, scope));
    setDef(data.providers.default ?? '');
    setFallback(data.providers.fallback);
    setDisabled(data.providers.disabled);
    setSingle(data.single_model);
    setStale(false);
  }, [data.sha256, scope, data.project]);

  const toggle = (list: string[], set: (l: string[]) => void, id: string) => set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const effective = (role: string) => data.items.find((i) => i.role === role);
  const providerOf = (role: string) => providers.find((p) => p.id === (rows[role]?.runner || effective(role)?.runner || 'claude'));
  const changeRunner = (role: string, runner: string) =>
    setRows((r) => {
      const next = providers.find((p) => p.id === (runner || effective(role)?.runner || 'claude'));
      const cur = r[role]?.model ?? '';
      const valid = !!next && next.capabilities.model_select && (next.models ?? []).some((m) => m.id === cur);
      return { ...r, [role]: { runner, model: valid ? cur : '', custom: false } };
    });

  const submit = () => {
    const agents: SaveAgentsBody['agents'] = {};
    for (const [role, r] of Object.entries(rows)) {
      if (!r.runner && !r.model.trim()) continue;
      agents[role] = { ...(r.runner ? { runner: r.runner } : {}), ...(r.model.trim() ? { model: r.model.trim() } : {}) };
    }
    const body: SaveAgentsBody = {
      scope,
      agents,
      providers: { ...(def ? { default: def } : {}), fallback, disabled },
      single_model: single,
      ...(scope === 'project' && pid ? { project: pid, ...(data.sha256 ? { sha256: data.sha256 } : {}) } : {}),
    };
    void save.run(
      async () => {
        const a = await calls.saveAgents(app.client, body);
        onSaved(a);
        return a;
      },
      () => (scope === 'global' ? 'Saved as global default. New projects start with these values.' : 'Saved to sentinel.config.yaml'),
      {
        onError: (e: ApiError) => {
          if (e.code === 'E_PRECONDITION' && e.status === 409) {
            setStale(true);
            return 'The configuration file changed after it was loaded. Reload it, then apply your edits again.';
          }
          return undefined;
        },
      },
    );
  };

  const runnerOptions = providers.map((p) => (
    <option key={p.id} value={p.id}>
      {p.label}
      {p.installed ? '' : ' (not installed)'}
    </option>
  ));

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {scope === 'global' ? (
        <p className="banner">Global defaults are copied into the configuration of projects created afterwards. They do not change existing projects.</p>
      ) : data.sha256 ? (
        <p className="hint">
          File <code>{prefix(data.sha256)}</code>. A save is refused when the file changed since it was loaded.
        </p>
      ) : null}
      <h3>Routing by role</h3>
      <div className="table-wrap">
        <table data-testid="routing-table">
          <thead>
            <tr>
              <th scope="col">Role</th>
              <th scope="col">Provider</th>
              <th scope="col">Model</th>
              <th scope="col">Effective now</th>
            </tr>
          </thead>
          <tbody>
            {data.roles.map((role) => {
              const eff = effective(role);
              return (
                <tr key={role} data-testid={`agent-row-${role}`}>
                  <th scope="row">{role}</th>
                  <td>
                    <select aria-label={`Provider for ${role}`} value={rows[role]?.runner ?? ''} onChange={(e) => changeRunner(role, e.target.value)}>
                      <option value="">Inherit</option>
                      {runnerOptions}
                    </select>
                  </td>
                  <td>
                    <ModelControl
                      roleName={role}
                      provider={providerOf(role)}
                      row={rows[role] ?? { runner: '', model: '' }}
                      onChange={(model, custom) => setRows((r) => ({ ...r, [role]: { ...r[role], model, custom } }))}
                    />
                  </td>
                  <td>
                    <span className="hint">
                      {eff ? `${eff.runner ?? 'claude'}${eff.model ? ` / ${eff.model}` : ''} (${SOURCE_LABEL[eff.source]})` : 'Built-in default'}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <h3>Provider policy</h3>
      <div className="field">
        <label htmlFor="prov-default">Default provider</label>
        <select id="prov-default" value={def} onChange={(e) => setDef(e.target.value)}>
          <option value="">Built-in default</option>
          {runnerOptions}
        </select>
      </div>
      <div className="split">
        <fieldset>
          <legend className="field-label">Fallback order</legend>
          <p className="hint">Used when the default provider fails.</p>
          {providers.map((p) => (
            <label key={p.id} className="check">
              <input type="checkbox" checked={fallback.includes(p.id)} onChange={() => toggle(fallback, setFallback, p.id)} aria-label={`Fallback ${p.label}`} /> {p.label}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend className="field-label">Disabled</legend>
          <p className="hint">Never used for any role.</p>
          {providers.map((p) => (
            <label key={p.id} className="check">
              <input type="checkbox" checked={disabled.includes(p.id)} onChange={() => toggle(disabled, setDisabled, p.id)} aria-label={`Disable ${p.label}`} /> {p.label}
            </label>
          ))}
        </fieldset>
      </div>
      <label className="check">
        <input type="checkbox" checked={single} onChange={(e) => setSingle(e.target.checked)} /> Single model
      </label>
      <p className="hint">One model does every role of a run. Per role models above are ignored while this is on.</p>

      <div className="row">
        <button type="submit" disabled={save.pending}>
          {save.pending ? 'Saving' : scope === 'global' ? 'Save global default' : 'Save to project'}
        </button>
      </div>
      <ActionResult message={save.message} />
      {stale ? (
        <button type="button" className="secondary" onClick={onReload}>
          Reload file
        </button>
      ) : null}
      {save.error && !stale ? <ErrorView error={save.error} /> : null}
    </form>
  );
}

/** Shared by Settings > Agents (project picker shown) and the project Agents tab (project fixed). */
export function AgentsPanel({ pid, pickProject = false }: { pid?: string; pickProject?: boolean }) {
  const projects = useResource('agents-projects', (c) => calls.projects(c), {});
  const [scope, setScope] = useState<Scope>('project');
  const [picked, setPicked] = useState<string>('');
  const available = (projects.data?.items ?? []).filter((p) => p.status !== 'unavailable');
  const current = pid ?? (picked || available[0]?.id || '');
  // the project's own runners.<id>.models are part of the list
  const providers = useResource(`agents-providers-${current || 'none'}`, (c) => calls.providers(c, current || undefined), {});
  const [override, setOverride] = useState<AgentsAnswer | null>(null);
  // global scope reads and writes the global file, never a project
  const target = scope === 'global' ? '' : current;
  const noProject = pickProject && !!projects.data && available.length === 0 && scope === 'project';
  const res = useResource(`agents-${target || 'global'}`, (c) => calls.agents(c, target || undefined), {}, pickProject ? !!projects.data && !noProject : true);

  useEffect(() => setOverride(null), [target, res.version]);
  const fresh = override ?? res.data;
  // never show the previous scope's data while the new one loads
  const data = fresh && (fresh.project ?? '') === target ? fresh : null;

  return (
    <>
      <h2>Agents</h2>
      <p className="lede">Choose which provider and model runs each agent role.</p>
      <div className="row controls">
        <div className="field inline">
          <span className="field-label" id="scope-label">
            Applies to
          </span>
          <div role="radiogroup" aria-labelledby="scope-label" className="segmented">
            <label>
              <input type="radio" name="agents-scope" checked={scope === 'project'} onChange={() => setScope('project')} /> This project
            </label>
            <label>
              <input type="radio" name="agents-scope" checked={scope === 'global'} onChange={() => setScope('global')} /> Global default
            </label>
          </div>
        </div>
        {pickProject && scope === 'project' && available.length > 0 ? (
          <div className="field inline">
            <label htmlFor="agents-project">Project</label>
            <select id="agents-project" value={current} onChange={(e) => setPicked(e.target.value)}>
              {available.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>
      {noProject ? (
        <div className="card empty" data-testid="agents-no-project">
          <h3>No project to configure</h3>
          <p>Per project routing needs a registered project.</p>
          <p>
            <Link to="/projects/new" className="button-link">Create project</Link>
          </p>
          <p className="hint">The Global default scope still works: pick it above to set the routing new projects start with.</p>
        </div>
      ) : (
      <Loaded res={res}>
        {() =>
          data && providers.data ? (
            <Editor
              data={data}
              scope={scope}
              pid={target || null}
              providers={providers.data.items}
              onSaved={(a) => setOverride(a)}
              onReload={() => void res.reload()}
            />
          ) : (
            <p className="loading" role="status"><span className="spinner" aria-hidden="true" />Loading</p>
          )
        }
      </Loaded>
      )}
    </>
  );
}
