import { useState } from 'react';
import { calls } from '../api/calls.ts';
import type { ApiError } from '../api/errors.ts';
import { REPO_ROLES, type NewRepo } from '../api/orchestration.ts';
import { ErrorView } from '../components/ErrorView.tsx';
import { FolderPicker } from '../components/FolderPicker.tsx';
import { useAction } from '../components/common.tsx';
import { Link, enc, navigate } from '../router.tsx';
import { useApp, useResource } from '../state/app.tsx';

const STEPS = ['Project', 'Repositories', 'Sharing', 'Review'] as const;

export function NewProjectScreen() {
  const app = useApp();
  const profiles = useResource('profiles', (c) => calls.profiles(c), {});
  const create = useAction();
  const [step, setStep] = useState(0);
  const [name, setName] = useState('');
  const [path, setPath] = useState('');
  const [repos, setRepos] = useState<NewRepo[]>([]);
  const [draft, setDraft] = useState({ path: '', role: 'backend', profile: '' });
  const [mode, setMode] = useState<'local' | 'git'>('local');
  const [url, setUrl] = useState('');
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [touched, setTouched] = useState(false);

  const nameErr = !name.trim() ? 'Required' : undefined;
  const pathErr = !path.trim() ? 'Required' : !path.startsWith('/') ? 'Use an absolute path that starts with /' : undefined;
  const draftErr = draft.path && !draft.path.startsWith('/') ? 'Use an absolute path that starts with /' : undefined;
  const urlErr = mode === 'git' && !url.trim() ? 'Enter the git URL' : undefined;

  const canNext = [!nameErr && !pathErr, repos.length > 0, !urlErr, true][step];

  const addRepo = () => {
    if (!draft.path.startsWith('/')) return;
    setRepos((r) => [...r, { path: draft.path, role: draft.role, ...(draft.profile ? { profile: draft.profile } : {}) }]);
    setDraft({ path: '', role: draft.role, profile: '' });
  };

  const submit = () =>
    void create.run(
      async () => {
        setFailure(null);
        try {
          const p = await calls.createProject(app.client, { name: name.trim(), path: path.trim(), shared: mode === 'git' ? { mode, url: url.trim() } : { mode }, repos });
          navigate(`/projects/${enc(p.id)}`);
          return p;
        } catch (e) {
          setFailure(e as ApiError);
          throw e;
        }
      },
      (p) => `Created ${p.name}`,
    );

  return (
    <section className="wizard">
      <p className="crumb">
        <Link to="/projects">Projects</Link>
      </p>
      <h1>Create project</h1>
      <ol className="stepper" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s} aria-current={i === step ? 'step' : undefined} data-state={i < step ? 'done' : i === step ? 'current' : 'todo'}>
            <span className="num" aria-hidden="true">{i + 1}</span> {s}
          </li>
        ))}
      </ol>

      <div className="card">
        {step === 0 ? (
          <>
            <h2>Name and folder</h2>
            <div className="field">
              <label htmlFor="np-name">Project name</label>
              <input id="np-name" type="text" value={name} autoComplete="off" onChange={(e) => { setName(e.target.value); setTouched(true); }} aria-invalid={touched && nameErr ? true : undefined} />
              {touched && nameErr ? <p className="field-error">{nameErr}</p> : null}
            </div>
            <FolderPicker
              label="Project folder"
              value={path}
              onChange={(p) => { setPath(p); setTouched(true); }}
              allowNew
              hint="Sentinel keeps its configuration here. The folder is created when it does not exist; its parent must exist."
              error={touched ? pathErr : undefined}
              testId="project-folder"
            />
          </>
        ) : null}

        {step === 1 ? (
          <>
            <h2>Repositories</h2>
            <p className="hint">A project needs at least one repository. Pick folders that already exist; Sentinel does not clone or create them.</p>
            {repos.length === 0 ? <p className="empty-inline">No repository added yet</p> : null}
            <ul className="plain" data-testid="wizard-repos">
              {repos.map((r, i) => (
                <li key={`${r.path}-${i}`} className="row listrow">
                  <code>{r.path}</code>
                  <span className="chip">{r.role}</span>
                  <span className="chip">{r.profile ?? 'auto profile'}</span>
                  <button type="button" className="secondary" aria-label={`Remove ${r.path}`} onClick={() => setRepos((x) => x.filter((_, j) => j !== i))}>
                    Remove
                  </button>
                </li>
              ))}
            </ul>
            <fieldset>
              <legend className="field-label">Add repository</legend>
              <FolderPicker label="Repository folder" value={draft.path} onChange={(p) => setDraft((d) => ({ ...d, path: p }))} error={draftErr} testId="repo-folder" />
              <div className="row">
                <div className="field inline">
                  <label htmlFor="np-role">Role</label>
                  <select id="np-role" value={draft.role} onChange={(e) => setDraft((d) => ({ ...d, role: e.target.value }))}>
                    {REPO_ROLES.map((r) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                </div>
                <div className="field inline">
                  <label htmlFor="np-profile">Profile</label>
                  <select id="np-profile" value={draft.profile} onChange={(e) => setDraft((d) => ({ ...d, profile: e.target.value }))}>
                    <option value="">Auto detect</option>
                    {(profiles.data?.items ?? []).map((p) => (
                      <option key={p.id} value={p.id}>{p.label ?? p.id}</option>
                    ))}
                  </select>
                </div>
              </div>
              <button type="button" className="secondary" disabled={!draft.path.startsWith('/')} onClick={addRepo}>
                Add repository
              </button>
            </fieldset>
          </>
        ) : null}

        {step === 2 ? (
          <>
            <h2>Local or shared</h2>
            <fieldset>
              <legend className="field-label">Where does the project state live</legend>
              <label className="check">
                <input type="radio" name="np-mode" checked={mode === 'local'} onChange={() => setMode('local')} /> Local only
              </label>
              <p className="hint">State stays on this machine.</p>
              <label className="check">
                <input type="radio" name="np-mode" checked={mode === 'git'} onChange={() => setMode('git')} /> Shared through a git repository
              </label>
              {mode === 'git' ? (
                <div className="field">
                  <label htmlFor="np-url">Git URL</label>
                  <input id="np-url" type="text" value={url} autoComplete="off" placeholder="git@host:team/sentinel-state.git" onChange={(e) => setUrl(e.target.value)} aria-invalid={urlErr ? true : undefined} />
                  {urlErr ? <p className="field-error">{urlErr}</p> : null}
                </div>
              ) : null}
            </fieldset>
          </>
        ) : null}

        {step === 3 ? (
          <>
            <h2>Review</h2>
            <dl className="kv" data-testid="wizard-review">
              <dt>Name</dt>
              <dd>{name}</dd>
              <dt>Folder</dt>
              <dd><code>{path}</code></dd>
              <dt>Sharing</dt>
              <dd>{mode === 'git' ? `Shared: ${url}` : 'Local only'}</dd>
              <dt>Repositories</dt>
              <dd>
                <ul className="plain">
                  {repos.map((r, i) => (
                    <li key={i}>
                      <code>{r.path}</code> ({r.role}, {r.profile ?? 'auto profile'})
                    </li>
                  ))}
                </ul>
              </dd>
            </dl>
            {failure ? <ErrorView error={failure} /> : null}
          </>
        ) : null}
      </div>

      <div className="row wizard-nav">
        <button type="button" className="secondary" disabled={step === 0 || create.pending} onClick={() => setStep((s) => s - 1)}>
          Back
        </button>
        {step < STEPS.length - 1 ? (
          <button type="button" disabled={!canNext} onClick={() => { setTouched(true); if (canNext) setStep((s) => s + 1); }}>
            Next
          </button>
        ) : (
          <button type="button" disabled={create.pending} onClick={submit}>
            {create.pending ? 'Creating' : 'Create project'}
          </button>
        )}
        <Link to="/projects">Cancel</Link>
      </div>
    </section>
  );
}
