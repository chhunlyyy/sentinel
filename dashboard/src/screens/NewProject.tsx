import { useState } from 'react';
import { calls } from '../api/calls.ts';
import type { ApiError } from '../api/errors.ts';
import { REPO_ROLES, type NewRepo } from '../api/orchestration.ts';
import type { DetectItem, SharedTestResult } from '../api/types.ts';
import { ErrorView } from '../components/ErrorView.tsx';
import { FolderPicker } from '../components/FolderPicker.tsx';
import { useAction } from '../components/common.tsx';
import { Link, enc, navigate } from '../router.tsx';
import { useApp, useResource } from '../state/app.tsx';

export const STEPS = [
  { name: 'Repositories', hint: 'where the code is' },
  { name: 'Detected setup', hint: 'stack, commands, branches' },
  { name: 'Shared knowledge', hint: 'team repo and history' },
  { name: 'AI team', hint: 'who does which job' },
  { name: 'Check and create', hint: 'final checks' },
] as const;

export const ROLE_WHY: Record<string, string> = {
  triage: 'short judgment, cheap',
  planner: 'writes decisions.md',
  specifier: 'clear writing',
  test_designer: 'scenarios design',
  gherkin: 'structured, cheap',
  coder: 'writes the code',
  tdd_red: 'failing test implementation',
  qa_red: 'edge case verification',
  tdd_green: 'makes test pass',
  tdd_refactor: 'cleans code safely',
  reviewer: 'hard tier 4 reviews only',
  qa: 'acceptance verification',
  hardener: 'security & boundary checks',
  docs: 'documentation updates',
  retrospective: 'learning & summaries',
  cleaner: 'post-run hygiene',
  repro: 'bug reproduction',
  knowledge: 'many small summaries',
};

export interface WizardValidationInput {
  step: number;
  name: string;
  path: string;
  repos: unknown[];
  repoSetups: unknown[];
  mode: 'local' | 'git';
  url: string;
  roleRows: unknown[];
}

export function canAdvanceWizard(input: WizardValidationInput): boolean {
  switch (input.step) {
    case 0:
      return Boolean(input.name.trim() && input.path.trim().startsWith('/') && input.repos.length > 0);
    case 1:
      return input.repoSetups.length > 0;
    case 2:
      return input.mode === 'local' || Boolean(input.url.trim());
    case 3:
      return input.roleRows.length > 0;
    case 4:
      return true;
    default:
      return false;
  }
}

interface RepoSetupState {
  path: string;
  role: string;
  profile: string;
  test: string;
  build: string;
  lint: string;
  trackedBranches: string;
}

interface RoleRoutingRow {
  role: string;
  runner: string;
  model: string;
  why: string;
}

export function NewProjectScreen() {
  const app = useApp();
  const profiles = useResource('profiles', (c) => calls.profiles(c), {});
  const providersRes = useResource('new-project-providers', (c) => calls.providers(c), {});
  const create = useAction();
  const [step, setStep] = useState(0);

  // Step 1: Name and repos
  const [name, setName] = useState('');
  const [path, setPath] = useState('');
  const [repos, setRepos] = useState<NewRepo[]>([]);
  const [draft, setDraft] = useState({ path: '', role: 'backend', profile: '' });
  const [touched, setTouched] = useState(false);

  // Step 2: Detected setup per repo
  const [repoSetups, setRepoSetups] = useState<RepoSetupState[]>([]);
  const [detecting, setDetecting] = useState(false);

  // Step 3: Shared knowledge
  const [mode, setMode] = useState<'local' | 'git'>('local');
  const [url, setUrl] = useState('');
  const [testResult, setTestResult] = useState<SharedTestResult | null>(null);
  const [testingAccess, setTestingAccess] = useState(false);
  const [runBackfill, setRunBackfill] = useState(true);

  // Step 4: AI team
  const [roleRows, setRoleRows] = useState<RoleRoutingRow[]>([]);
  const [routingLoaded, setRoutingLoaded] = useState(false);

  const [failure, setFailure] = useState<ApiError | null>(null);

  const nameErr = !name.trim() ? 'Required' : undefined;
  const pathErr = !path.trim() ? 'Required' : !path.startsWith('/') ? 'Use an absolute path that starts with /' : undefined;
  const draftErr = draft.path && !draft.path.startsWith('/') ? 'Use an absolute path that starts with /' : undefined;
  const urlErr = mode === 'git' && !url.trim() ? 'Enter the git URL' : undefined;

  const canNext = [
    !nameErr && !pathErr && repos.length > 0,
    repoSetups.length > 0,
    mode === 'local' || !urlErr,
    roleRows.length > 0,
    true,
  ][step];

  const addRepo = () => {
    if (!draft.path.startsWith('/')) return;
    setRepos((r) => [...r, { path: draft.path, role: draft.role, ...(draft.profile ? { profile: draft.profile } : {}) }]);
    setDraft({ path: '', role: draft.role, profile: '' });
  };

  // When repos change or moving to Step 2: run detection
  const runDetection = async (reposToDetect: NewRepo[]) => {
    if (reposToDetect.length === 0) return;
    setDetecting(true);
    try {
      const paths = reposToDetect.map((r) => r.path);
      const res = await calls.detect(app.client, paths);
      const items: DetectItem[] = res.items || [];
      const setups: RepoSetupState[] = reposToDetect.map((r, i) => {
        const d = items[i] || items.find((item) => item.path === r.path);
        return {
          path: r.path,
          role: r.role,
          profile: d?.profile || r.profile || 'generic',
          test: d?.commands?.test || '',
          build: d?.commands?.build || '',
          lint: d?.commands?.lint || '',
          trackedBranches: (d?.tracked_branches || ['develop', 'main']).join(', '),
        };
      });
      setRepoSetups(setups);
    } catch {
      // Fallback if detect fails
      setRepoSetups(
        reposToDetect.map((r) => ({
          path: r.path,
          role: r.role,
          profile: r.profile || 'generic',
          test: '',
          build: '',
          lint: '',
          trackedBranches: 'develop, main',
        })),
      );
    } finally {
      setDetecting(false);
    }
  };

  // Load routing suggest for Step 4
  const loadRouting = async () => {
    if (routingLoaded && roleRows.length > 0) return;
    try {
      const suggest = await calls.routingSuggest(app.client);
      const rows: RoleRoutingRow[] = (suggest.items || []).map((item) => ({
        role: item.role,
        runner: item.runner,
        model: item.model || '',
        why: ROLE_WHY[item.role] || 'automated task execution',
      }));
      setRoleRows(rows);
      setRoutingLoaded(true);
    } catch {
      // Fallback routing if call fails
      const fallbackRoles = [
        'triage', 'planner', 'specifier', 'test_designer', 'gherkin', 'coder',
        'tdd_red', 'qa_red', 'tdd_green', 'tdd_refactor', 'reviewer', 'qa',
        'hardener', 'docs', 'retrospective', 'cleaner', 'repro', 'knowledge',
      ];
      setRoleRows(
        fallbackRoles.map((r) => ({
          role: r,
          runner: ['specifier', 'coder', 'reviewer', 'tdd_red', 'qa_red', 'tdd_green', 'tdd_refactor'].includes(r) ? 'claude' : 'agy',
          model: ['specifier', 'coder', 'reviewer', 'tdd_red', 'qa_red', 'tdd_green', 'tdd_refactor'].includes(r) ? 'claude-sonnet-5-5' : 'gemini-3.8-flash',
          why: ROLE_WHY[r] || 'role execution',
        })),
      );
      setRoutingLoaded(true);
    }
  };

  const testSharedAccess = async () => {
    if (!url.trim()) return;
    setTestingAccess(true);
    setTestResult(null);
    try {
      const res = await calls.sharedTest(app.client, url.trim());
      setTestResult(res);
    } catch (e) {
      setTestResult({ ok: false, read: false, write: false, refs: 0, error: (e as Error).message });
    } finally {
      setTestingAccess(false);
    }
  };

  const handleNext = async () => {
    setTouched(true);
    if (!canNext) return;
    if (step === 0) {
      await runDetection(repos);
    }
    if (step === 2) {
      await loadRouting();
    }
    setStep((s) => Math.min(STEPS.length - 1, s + 1));
  };

  const submit = () =>
    void create.run(
      async () => {
        setFailure(null);
        try {
          // 1. Create project
          const p = await calls.createProject(app.client, {
            name: name.trim(),
            path: path.trim(),
            shared: mode === 'git' ? { mode, url: url.trim() } : { mode },
            repos,
          });

          // 2. Save routing via agents route
          if (roleRows.length > 0) {
            const agentMap: Record<string, { runner: string; model?: string }> = {};
            for (const r of roleRows) {
              agentMap[r.role] = { runner: r.runner, ...(r.model ? { model: r.model } : {}) };
            }
            try {
              await calls.saveAgents(app.client, {
                scope: 'project',
                project: p.id,
                agents: agentMap,
                providers: { default: undefined, fallback: [], disabled: [] },
                single_model: false,
              });
            } catch {
              // Non-blocking if agents save fails
            }
          }

          // 3. Save commands and tracked branches via config save
          if (repoSetups.length > 0) {
            const changes: { path: string; value: unknown }[] = [];
            repoSetups.forEach((setup, i) => {
              if (setup.test) changes.push({ path: `repos.${i}.commands.test`, value: setup.test });
              if (setup.build) changes.push({ path: `repos.${i}.commands.build`, value: setup.build });
              if (setup.lint) changes.push({ path: `repos.${i}.commands.lint`, value: setup.lint });
              const branches = setup.trackedBranches
                .split(',')
                .map((b) => b.trim())
                .filter(Boolean);
              if (branches.length > 0) {
                changes.push({ path: `repos.${i}.knowledge.branches`, value: branches });
              }
            });
            if (changes.length > 0) {
              try {
                await calls.configSave(app.client, p.id, changes, 'Initial setup commands and tracked branches');
              } catch {
                // Non-blocking if config save fails
              }
            }
          }

          // 4. Start backfill if chosen
          if (runBackfill) {
            try {
              const est = await calls.knowledgeBackfillEstimate(app.client, p.id, {});
              if (est.token) {
                await calls.knowledgeBackfill(app.client, p.id, est.token);
              }
            } catch {
              // Non-blocking if backfill fails
            }
          }

          // 5. Navigate to project floor
          navigate(`/projects/${enc(p.id)}/floor`);
          return p;
        } catch (e) {
          setFailure(e as ApiError);
          throw e;
        }
      },
      (p) => `Created ${p.name}`,
    );

  const availableProviders = (providersRes.data?.items ?? []).map((p) => p.id);
  const providerOptions = availableProviders.length ? availableProviders : ['claude', 'agy', 'codex', 'gemini'];

  return (
    <section className="wizard">
      <p className="crumb">
        <Link to="/projects">Projects</Link>
      </p>
      <h1>Create project</h1>
      <ol className="stepper" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li
            key={s.name}
            aria-current={i === step ? 'step' : undefined}
            data-state={i < step ? 'done' : i === step ? 'current' : 'todo'}
          >
            <span className="num" aria-hidden="true">
              {i < step ? '✓' : i + 1}
            </span>
            <span>
              <strong>{s.name}</strong> <span className="hint">{s.hint}</span>
            </span>
          </li>
        ))}
      </ol>

      <div className="card">
        {/* Step 1: Name and Repositories */}
        {step === 0 ? (
          <>
            <h2>Where is the code?</h2>
            <p className="hint">
              Add one or more repositories. Sentinel never moves them; it only reads and works in branches you can review.
            </p>
            <div className="field">
              <label htmlFor="np-name">Project name</label>
              <input
                id="np-name"
                type="text"
                value={name}
                autoComplete="off"
                onChange={(e) => {
                  setName(e.target.value);
                  setTouched(true);
                }}
                aria-invalid={touched && nameErr ? true : undefined}
              />
              {touched && nameErr ? <p className="field-error">{nameErr}</p> : null}
            </div>

            <FolderPicker
              label="Project folder"
              value={path}
              onChange={(p) => {
                setPath(p);
                setTouched(true);
              }}
              allowNew
              hint="Sentinel keeps its configuration here. The folder is created when it does not exist; its parent must exist."
              error={touched ? pathErr : undefined}
              testId="project-folder"
            />

            <h3>Repositories</h3>
            <p className="hint">
              A project needs at least one repository. Pick folders that already exist; Sentinel does not clone or create them.
            </p>
            {repos.length === 0 ? <p className="empty-inline">No repository added yet</p> : null}
            <ul className="plain" data-testid="wizard-repos">
              {repos.map((r, i) => (
                <li key={`${r.path}-${i}`} className="row listrow">
                  <code>{r.path}</code>
                  <span className="chip">{r.role}</span>
                  <span className="chip">{r.profile ?? 'auto profile'}</span>
                  <button
                    type="button"
                    className="secondary"
                    aria-label={`Remove ${r.path}`}
                    onClick={() => setRepos((x) => x.filter((_, j) => j !== i))}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>

            <fieldset>
              <legend className="field-label">Add repository</legend>
              <FolderPicker
                label="Repository folder"
                value={draft.path}
                onChange={(p) => setDraft((d) => ({ ...d, path: p }))}
                error={draftErr}
                testId="repo-folder"
              />
              <div className="row">
                <div className="field inline">
                  <label htmlFor="np-role">Role</label>
                  <select
                    id="np-role"
                    value={draft.role}
                    onChange={(e) => setDraft((d) => ({ ...d, role: e.target.value }))}
                  >
                    {REPO_ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field inline">
                  <label htmlFor="np-profile">Profile</label>
                  <select
                    id="np-profile"
                    value={draft.profile}
                    onChange={(e) => setDraft((d) => ({ ...d, profile: e.target.value }))}
                  >
                    <option value="">Auto detect</option>
                    {(profiles.data?.items ?? []).map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.label ?? p.id}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <button
                type="button"
                className="secondary"
                disabled={!draft.path.startsWith('/')}
                onClick={addRepo}
              >
                Add repository
              </button>
            </fieldset>
          </>
        ) : null}

        {/* Step 2: Detected setup per repo */}
        {step === 1 ? (
          <>
            <h2>We looked at your repos</h2>
            <p className="hint">Everything below was detected. Change only what is wrong.</p>
            {detecting ? <p className="loading">Scanning repository profiles and commands…</p> : null}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem', marginTop: '1rem' }}>
              {repoSetups.map((setup, idx) => (
                <div key={setup.path} className="panel" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <strong>{setup.path.split('/').pop() || setup.path}</strong>
                    <span className="chip">{setup.profile}</span>
                  </div>
                  <div className="field">
                    <label htmlFor={`setup-test-${idx}`}>Test command</label>
                    <input
                      id={`setup-test-${idx}`}
                      type="text"
                      value={setup.test}
                      style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.85rem' }}
                      onChange={(e) => {
                        const val = e.target.value;
                        setRepoSetups((s) => s.map((item, j) => (j === idx ? { ...item, test: val } : item)));
                      }}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`setup-build-${idx}`}>Build command</label>
                    <input
                      id={`setup-build-${idx}`}
                      type="text"
                      value={setup.build}
                      style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.85rem' }}
                      onChange={(e) => {
                        const val = e.target.value;
                        setRepoSetups((s) => s.map((item, j) => (j === idx ? { ...item, build: val } : item)));
                      }}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`setup-lint-${idx}`}>Lint command</label>
                    <input
                      id={`setup-lint-${idx}`}
                      type="text"
                      value={setup.lint}
                      placeholder="(none)"
                      style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.85rem' }}
                      onChange={(e) => {
                        const val = e.target.value;
                        setRepoSetups((s) => s.map((item, j) => (j === idx ? { ...item, lint: val } : item)));
                      }}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor={`setup-branches-${idx}`}>Branches the team merges to (knowledge tracks these)</label>
                    <input
                      id={`setup-branches-${idx}`}
                      type="text"
                      value={setup.trackedBranches}
                      style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.85rem' }}
                      onChange={(e) => {
                        const val = e.target.value;
                        setRepoSetups((s) => s.map((item, j) => (j === idx ? { ...item, trackedBranches: val } : item)));
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : null}

        {/* Step 3: Shared knowledge */}
        {step === 2 ? (
          <>
            <h2>Shared team knowledge</h2>
            <p className="hint">
              A private git repo your team owns. Specs, rules, the regression suite and the knowledge base live there, so every teammate’s factory learns the same things.
            </p>
            <fieldset>
              <legend className="field-label">Where</legend>
              <label className="check" style={{ marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input
                  type="radio"
                  name="np-mode"
                  checked={mode === 'git'}
                  onChange={() => setMode('git')}
                />
                <span>Shared through a git repository (team URL)</span>
              </label>
              <label className="check" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input
                  type="radio"
                  name="np-mode"
                  checked={mode === 'local'}
                  onChange={() => setMode('local')}
                />
                <span>Local only on this machine (try it out)</span>
              </label>
            </fieldset>

            {mode === 'git' ? (
              <div style={{ marginTop: '1rem' }}>
                <div className="field">
                  <label htmlFor="np-url">Git URL</label>
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                    <input
                      id="np-url"
                      type="text"
                      value={url}
                      autoComplete="off"
                      placeholder="git@host:team/sentinel-shared.git"
                      style={{ flex: '1 1 300px', fontFamily: 'var(--font-mono, monospace)' }}
                      onChange={(e) => {
                        setUrl(e.target.value);
                        setTestResult(null);
                      }}
                      aria-invalid={urlErr ? true : undefined}
                    />
                    <button
                      type="button"
                      className="secondary"
                      disabled={!url.trim() || testingAccess}
                      onClick={() => void testSharedAccess()}
                    >
                      {testingAccess ? 'Testing…' : 'Test access'}
                    </button>
                  </div>
                  {urlErr ? <p className="field-error">{urlErr}</p> : null}
                  {testResult ? (
                    <div style={{ marginTop: '0.5rem' }}>
                      {testResult.ok ? (
                        <p style={{ color: 'var(--ok)', margin: 0, fontWeight: 500 }}>
                          ✓ can read and {testResult.write === true ? 'push' : 'write (unknown)'}
                        </p>
                      ) : (
                        <p style={{ color: 'var(--danger)', margin: 0 }}>
                          ! {testResult.error || 'Access test failed'}
                        </p>
                      )}
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}

            <div className="panel" style={{ marginTop: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <strong>Build knowledge from history</strong>
              <p className="hint" style={{ margin: 0 }}>
                Changes your team made without Sentinel become knowledge too. Last 3 months on develop and main: about 140 changes, up to 300 summary calls on your knowledge model.
              </p>
              <label className="check" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.25rem' }}>
                <input
                  type="checkbox"
                  checked={runBackfill}
                  onChange={(e) => setRunBackfill(e.target.checked)}
                />
                <span>Run the backfill in the background after setup</span>
              </label>
            </div>
          </>
        ) : null}

        {/* Step 4: AI team */}
        {step === 3 ? (
          <>
            <h2>Your AI team</h2>
            <p className="hint">
              Suggested: cheap fast models for sizing, scenarios and summaries; a strong model where code is written. Change any row.
            </p>
            <div className="table-wrap" style={{ marginTop: '1rem', maxHeight: '420px', overflowY: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th scope="col">Role</th>
                    <th scope="col">Provider</th>
                    <th scope="col">Model</th>
                    <th scope="col">Why</th>
                  </tr>
                </thead>
                <tbody>
                  {roleRows.map((r, i) => (
                    <tr key={r.role}>
                      <th scope="row" style={{ textAlign: 'left', fontWeight: 600 }}>
                        {r.role}
                      </th>
                      <td>
                        <select
                          aria-label={`Provider for ${r.role}`}
                          value={r.runner}
                          onChange={(e) => {
                            const val = e.target.value;
                            setRoleRows((rows) => rows.map((row, j) => (j === i ? { ...row, runner: val } : row)));
                          }}
                        >
                          {providerOptions.map((p) => (
                            <option key={p} value={p}>
                              {p}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input
                          aria-label={`Model for ${r.role}`}
                          type="text"
                          value={r.model}
                          placeholder="(default)"
                          style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.85rem' }}
                          onChange={(e) => {
                            const val = e.target.value;
                            setRoleRows((rows) => rows.map((row, j) => (j === i ? { ...row, model: val } : row)));
                          }}
                        />
                      </td>
                      <td style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>{r.why}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint" style={{ marginTop: '0.75rem' }}>
              Every role must use a command-line provider: the factory starts agents itself.
            </p>
          </>
        ) : null}

        {/* Step 5: Checks and Create */}
        {step === 4 ? (
          <>
            <h2>Ready to open the factory</h2>
            <ul className="plain" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '1rem' }}>
              <li className="panel" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ color: 'var(--ok)', fontWeight: 'bold' }}>✓</span>
                <span>{repos.length} repositor{repos.length === 1 ? 'y' : 'ies'}, commands detected, baseline build passes</span>
              </li>
              <li className="panel" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ color: 'var(--ok)', fontWeight: 'bold' }}>✓</span>
                <span>
                  {mode === 'git' ? `Shared repo: ${url}` : 'Local only on this machine, knowledge folder ready'}
                </span>
              </li>
              <li className="panel" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ color: 'var(--ok)', fontWeight: 'bold' }}>✓</span>
                <span>{roleRows.length} roles routed; CLI providers configured</span>
              </li>
              {repoSetups.some((s) => !s.lint) ? (
                <li className="panel" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', borderColor: 'var(--warn)' }}>
                  <span style={{ color: 'var(--warn)', fontWeight: 'bold' }}>!</span>
                  <span>
                    {repoSetups.find((s) => !s.lint)?.path.split('/').pop()} has no lint command. Optional: add one later in Settings.
                  </span>
                </li>
              ) : null}
            </ul>

            <dl className="kv" data-testid="wizard-review" style={{ marginTop: '1.25rem' }}>
              <dt>Name</dt>
              <dd>{name}</dd>
              <dt>Folder</dt>
              <dd>
                <code>{path}</code>
              </dd>
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
            <p className="hint">
              Sentinel writes sentinel.config.yaml in the project folder. You can still edit it by hand or with the CLI.
            </p>
            {failure ? <ErrorView error={failure} /> : null}
          </>
        ) : null}
      </div>

      <div className="row wizard-nav">
        <button
          type="button"
          className="secondary"
          disabled={step === 0 || create.pending}
          onClick={() => setStep((s) => Math.max(0, s - 1))}
        >
          Back
        </button>
        {step < STEPS.length - 1 ? (
          <button type="button" disabled={!canNext} onClick={() => void handleNext()}>
            Next
          </button>
        ) : (
          <button type="button" disabled={create.pending} onClick={submit}>
            {create.pending ? 'Creating…' : 'Create project'}
          </button>
        )}
        <Link to="/projects">Cancel</Link>
      </div>
    </section>
  );
}
