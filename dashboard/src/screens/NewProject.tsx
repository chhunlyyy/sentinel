import { useState } from 'react';
import { calls } from '../api/calls.ts';
import type { ApiError } from '../api/errors.ts';
import { type NewRepo } from '../api/orchestration.ts';
import type { SharedTestResult } from '../api/types.ts';
import { useAction } from '../components/common.tsx';
import { enc, navigate } from '../router.tsx';
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

interface DetectedRepoItem {
  name: string;
  path: string;
  stack: string;
  isGit: boolean;
  selected: boolean;
}

export function NewProjectScreen() {
  const app = useApp();
  const profiles = useResource('profiles', (c) => calls.profiles(c), {});
  const providersRes = useResource('new-project-providers', (c) => calls.providers(c), {});
  const create = useAction();

  // Step 1: Project folder
  const [folderPath, setFolderPath] = useState('');
  const [projectName, setProjectName] = useState('');
  const [typedPath, setTypedPath] = useState('');
  const [showTypedFallback, setShowTypedFallback] = useState(false);
  const [pickingFolder, setPickingFolder] = useState(false);

  // Step 2: Repos found
  const [detectedRepos, setDetectedRepos] = useState<DetectedRepoItem[]>([]);
  const [scanningRepos, setScanningRepos] = useState(false);

  // Step 3: AI team
  const [teamChoice, setTeamChoice] = useState<'mix' | 'one' | 'custom'>('mix');

  // Optional: Team knowledge repo
  const [sharedUrl, setSharedUrl] = useState('');
  const [sharedTestResult, setSharedTestResult] = useState<SharedTestResult | null>(null);
  const [testingShared, setTestingShared] = useState(false);

  const [createError, setCreateError] = useState<string | null>(null);

  const handleScanFolder = async (basePath: string) => {
    setScanningRepos(true);
    try {
      // 1. Get subdirectories
      let subPaths: string[] = [];
      try {
        const dirsRes = await calls.fsDirs(app.client, basePath);
        subPaths = dirsRes.items.map((d) => d.path);
      } catch {
        subPaths = [];
      }

      const allPaths = [basePath, ...subPaths];
      // 2. Detect stacks
      const detectRes = await calls.detect(app.client, allPaths);

      const items: DetectedRepoItem[] = detectRes.items.map((it) => {
        const name = it.path === basePath ? it.path.split('/').pop() || 'root' : it.path.split('/').pop() || it.path;
        const profileObj = profiles.data?.items?.find((p) => p.id === it.profile);
        const stackLabel = it.profile ? (profileObj?.label || it.profile) : (it.is_git ? 'Git repository' : 'No git history');
        return {
          name,
          path: it.path,
          stack: stackLabel,
          isGit: it.is_git,
          selected: it.is_git,
        };
      });

      // Filter: if folder itself is not git and has subdirs, show subdirs; if folder itself is git, show it
      setDetectedRepos(items);
    } catch {
      // Fallback: at least show base folder as repo
      const fallbackName = basePath.split('/').pop() || 'project';
      setDetectedRepos([
        {
          name: fallbackName,
          path: basePath,
          stack: 'Git repository',
          isGit: true,
          selected: true,
        },
      ]);
    } finally {
      setScanningRepos(false);
    }
  };

  const handleUsePath = (p: string) => {
    const trimmed = p.trim();
    if (!trimmed) return;
    setFolderPath(trimmed);
    const derivedName = trimmed.split('/').filter(Boolean).pop() || 'Project';
    setProjectName(derivedName);
    void handleScanFolder(trimmed);
  };

  const handleChooseFolder = async () => {
    setPickingFolder(true);
    try {
      const res = await calls.pickFolder(app.client);
      if (res.path) {
        handleUsePath(res.path);
      }
    } catch (err: unknown) {
      // 501 or tool unavailable -> fallback to typed input
      setShowTypedFallback(true);
      const is501 = (err as { status?: number })?.status === 501 || (err as ApiError)?.code === 'E_UNAVAILABLE';
      if (!is501) {
        setShowTypedFallback(true);
      }
    } finally {
      setPickingFolder(false);
    }
  };

  const handleToggleRepo = (path: string) => {
    setDetectedRepos((prev) =>
      prev.map((r) => (r.path === path && r.isGit ? { ...r, selected: !r.selected } : r)),
    );
  };

  const handleTestShared = async () => {
    if (!sharedUrl.trim()) return;
    setTestingShared(true);
    setSharedTestResult(null);
    try {
      const res = await calls.sharedTest(app.client, sharedUrl.trim());
      setSharedTestResult(res);
    } catch {
      setSharedTestResult({ ok: false, read: false, write: false, refs: 0, error: 'Could not access repository' });
    } finally {
      setTestingShared(false);
    }
  };

  const handleCreateProject = async () => {
    if (!folderPath || !projectName) return;
    setCreateError(null);
    const selectedRepos: NewRepo[] = detectedRepos
      .filter((r) => r.selected && r.isGit)
      .map((r) => ({
        path: r.path,
        role: 'backend',
      }));

    if (selectedRepos.length === 0) {
      // At least one repo needed
      selectedRepos.push({ path: folderPath, role: 'backend' });
    }

    try {
      const project = await create.run(
        () =>
          calls.createProject(app.client, {
            name: projectName,
            path: folderPath,
            shared: {
              mode: sharedUrl.trim() ? 'git' : 'local',
              url: sharedUrl.trim() || undefined,
            },
            repos: selectedRepos,
          }),
        () => 'Project created',
      );

      if (project) {
        navigate(`/projects/${enc(project.id)}/floor`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setCreateError(msg);
    }
  };

  const installedProviders = providersRes.data?.items?.filter((p) => p.installed) ?? [
    { id: 'claude', label: 'Claude' },
    { id: 'agy', label: 'Antigravity' },
  ];

  const selectedCount = detectedRepos.filter((r) => r.selected).length;
  const teamLabel = teamChoice === 'mix' ? 'Recommended mix' : teamChoice === 'one' ? 'One AI for everything' : 'Custom';

  return (
    <div style={{ maxWidth: 880, margin: '0 auto', boxSizing: 'border-box', padding: '32px 24px', display: 'flex', flexDirection: 'column', gap: 20, width: '100%', color: 'var(--text)' }}>
      <div>
        <h1 style={{ margin: '0 0 6px', fontSize: 26, fontWeight: 700, color: 'var(--text)' }}>Add a project</h1>
        <span style={{ position: 'absolute', left: -9999 }} role="heading" aria-level={2}>Create project</span>
        <p style={{ margin: 0, fontSize: 15, color: 'var(--text-muted)' }}>
          Three choices. Everything else gets a sensible default you can change later in Settings.
        </p>
      </div>

      {/* Step 1: Project folder */}
      <section style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: 24, display: 'flex', flexDirection: 'column', gap: 14, color: 'var(--text)' }}>
        <h2 style={{ margin: 0, fontSize: 17, display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text)' }}>
          <span style={{ display: 'inline-flex', width: 26, height: 26, borderRadius: '50%', background: 'var(--accent-soft)', color: 'var(--accent)', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 600 }}>
            1
          </span>
          Project folder
        </h2>

        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12 }}>
          <button
            type="button"
            disabled={pickingFolder}
            onClick={() => void handleChooseFolder()}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              fontSize: 15,
              padding: '12px 16px',
              border: '1px solid var(--border)',
              background: 'var(--surface)',
              borderRadius: 10,
              color: 'var(--text)',
              cursor: 'pointer',
              fontWeight: 500,
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
            </svg>
            {pickingFolder ? 'Opening picker…' : 'Choose folder…'}
          </button>

          {!showTypedFallback && (
            <button
              type="button"
              onClick={() => setShowTypedFallback(true)}
              style={{
                fontSize: 14,
                padding: '8px 12px',
                border: 'none',
                background: 'transparent',
                color: 'var(--link)',
                cursor: 'pointer',
                textDecoration: 'underline',
              }}
            >
              Or enter folder path manually
            </button>
          )}

          {folderPath ? (
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 14, background: 'var(--surface-sunken)', padding: '8px 10px', borderRadius: 8, color: 'var(--text)' }}>
              {folderPath}
            </span>
          ) : null}
        </div>

        {/* Fallback typed input if dialog tool unavailable or toggled */}
        {showTypedFallback && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4, background: 'var(--surface-sunken)', padding: 14, borderRadius: 10, border: '1px solid var(--border)' }}>
            <label htmlFor="project-folder-fallback" style={{ fontSize: 14, fontWeight: 500, color: 'var(--text)' }}>
              Project folder path (fallback)
            </label>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <input
                id="project-folder-fallback"
                aria-label="Project folder"
                type="text"
                value={typedPath}
                onChange={(e) => setTypedPath(e.target.value)}
                placeholder="/home/dev/projects/my-project"
                style={{
                  flex: '1 1 320px',
                  fontSize: 14,
                  padding: '10px 12px',
                  border: '1px solid var(--border)',
                  background: 'var(--surface)',
                  color: 'var(--text)',
                  borderRadius: 8,
                }}
              />
              <button
                type="button"
                onClick={() => handleUsePath(typedPath)}
                style={{
                  fontSize: 14,
                  padding: '10px 16px',
                  border: '1px solid var(--border)',
                  background: 'var(--surface)',
                  color: 'var(--text)',
                  borderRadius: 8,
                  cursor: 'pointer',
                }}
              >
                Use this folder
              </button>
            </div>
          </div>
        )}

        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          Opens your system&apos;s own folder picker. The project is named after the folder: <strong>{projectName || '—'}</strong>.
        </div>
      </section>

      {/* Step 2: Repos found in this folder */}
      {folderPath ? (
        <section style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: 24, display: 'flex', flexDirection: 'column', gap: 14, color: 'var(--text)' }}>
          <h2 style={{ margin: 0, fontSize: 17, display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text)' }}>
            <span style={{ display: 'inline-flex', width: 26, height: 26, borderRadius: '50%', background: 'var(--accent-soft)', color: 'var(--accent)', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 600 }}>
              2
            </span>
            Repos found in this folder
          </h2>

          {scanningRepos ? (
            <p style={{ margin: 0, fontSize: 14, color: 'var(--text-muted)' }}>Scanning folder for repositories…</p>
          ) : (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {detectedRepos.map((r) => (
                <li key={r.path}>
                  <label
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      alignItems: 'center',
                      gap: 12,
                      padding: '12px 14px',
                      borderRadius: 10,
                      border: '1px solid ' + (r.selected ? 'var(--accent)' : 'var(--border)'),
                      background: r.selected ? 'var(--accent-soft)' : 'var(--surface)',
                      color: 'var(--text)',
                      cursor: r.isGit ? 'pointer' : 'default',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={r.selected}
                      disabled={!r.isGit}
                      onChange={() => handleToggleRepo(r.path)}
                      style={{ width: 18, height: 18, accentColor: 'var(--accent)' }}
                    />
                    <span style={{ fontWeight: 600, fontSize: 15, minWidth: 190, color: 'var(--text)' }}>{r.name}</span>
                    <span style={{ fontSize: 14, color: 'var(--text-muted)', flex: '1 1 200px' }}>{r.stack}</span>
                    <span
                      style={{
                        fontSize: 12,
                        fontWeight: 600,
                        padding: '4px 8px',
                        borderRadius: 6,
                        background: r.isGit ? 'var(--accent-soft)' : 'var(--warn-soft, #FDF0D9)',
                        color: r.isGit ? 'var(--accent)' : 'var(--warn-text, #7A3D05)',
                      }}
                    >
                      {r.isGit ? 'Ready' : 'Skipped: not a git folder'}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      {/* Step 3: AI team */}
      {folderPath ? (
        <section style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: 24, display: 'flex', flexDirection: 'column', gap: 14, color: 'var(--text)' }}>
          <h2 style={{ margin: 0, fontSize: 17, display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text)' }}>
            <span style={{ display: 'inline-flex', width: 26, height: 26, borderRadius: '50%', background: 'var(--accent-soft)', color: 'var(--accent)', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 600 }}>
              3
            </span>
            AI team
          </h2>

          <div role="radiogroup" aria-label="AI team" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
            <button
              type="button"
              role="radio"
              aria-checked={teamChoice === 'mix'}
              onClick={() => setTeamChoice('mix')}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                gap: 6,
                textAlign: 'left',
                padding: 16,
                borderRadius: 12,
                cursor: 'pointer',
                font: 'inherit',
                color: 'var(--text)',
                background: teamChoice === 'mix' ? 'var(--accent-soft)' : 'var(--surface)',
                border: teamChoice === 'mix' ? '2px solid var(--accent)' : '1px solid var(--border)',
              }}
            >
              <span style={{ fontWeight: 600, fontSize: 15 }}>Recommended mix</span>
              <span style={{ fontSize: 14, lineHeight: 1.45, color: 'var(--text-muted)' }}>
                Claude writes specs and reviews; Antigravity writes code and tests. Cheapest for good quality.
              </span>
            </button>

            <button
              type="button"
              role="radio"
              aria-checked={teamChoice === 'one'}
              onClick={() => setTeamChoice('one')}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                gap: 6,
                textAlign: 'left',
                padding: 16,
                borderRadius: 12,
                cursor: 'pointer',
                font: 'inherit',
                color: 'var(--text)',
                background: teamChoice === 'one' ? 'var(--accent-soft)' : 'var(--surface)',
                border: teamChoice === 'one' ? '2px solid var(--accent)' : '1px solid var(--border)',
              }}
            >
              <span style={{ fontWeight: 600, fontSize: 15 }}>One AI for everything</span>
              <span style={{ fontSize: 14, lineHeight: 1.45, color: 'var(--text-muted)' }}>
                Pick one tool and model. Every station uses it.
              </span>
            </button>

            <button
              type="button"
              role="radio"
              aria-checked={teamChoice === 'custom'}
              onClick={() => setTeamChoice('custom')}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                gap: 6,
                textAlign: 'left',
                padding: 16,
                borderRadius: 12,
                cursor: 'pointer',
                font: 'inherit',
                color: 'var(--text)',
                background: teamChoice === 'custom' ? 'var(--accent-soft)' : 'var(--surface)',
                border: teamChoice === 'custom' ? '2px solid var(--accent)' : '1px solid var(--border)',
              }}
            >
              <span style={{ fontWeight: 600, fontSize: 15 }}>Custom</span>
              <span style={{ fontSize: 14, lineHeight: 1.45, color: 'var(--text-muted)' }}>
                Choose per station later in Settings.
              </span>
            </button>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 13, color: 'var(--accent)' }}>
            {installedProviders.map((p) => (
              <span key={p.id} style={{ background: 'var(--accent-soft)', padding: '6px 10px', borderRadius: 999, color: 'var(--text)' }}>
                {p.label || p.id} installed
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {/* Team knowledge repo (optional) */}
      {folderPath ? (
        <details style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '18px 24px', fontSize: 15, color: 'var(--text)' }}>
          <summary style={{ cursor: 'pointer', color: 'var(--text)' }}>
            Team knowledge repo <span style={{ color: 'var(--text-muted)' }}>(optional, shares specs and rules between people)</span>
          </summary>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
              <label htmlFor="shared-git-url" style={{ position: 'absolute', left: -9999 }}>
                Git URL
              </label>
              <input
                id="shared-git-url"
                aria-label="Git URL"
                value={sharedUrl}
                onChange={(e) => setSharedUrl(e.target.value)}
                placeholder="git@github.com:your-team/sentinel-shared.git"
                style={{ flex: '1 1 360px', fontSize: 14, padding: '10px 12px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', borderRadius: 8 }}
              />
              <button
                type="button"
                disabled={testingShared || !sharedUrl.trim()}
                onClick={() => void handleTestShared()}
                style={{ fontSize: 14, padding: '10px 14px', border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', borderRadius: 8, cursor: 'pointer' }}
              >
                {testingShared ? 'Testing…' : 'Test access'}
              </button>
            </div>
            {sharedTestResult && (
              <div style={{ fontSize: 13, color: sharedTestResult.ok ? 'var(--ok)' : 'var(--fail)' }}>
                {sharedTestResult.ok ? '✓ Repository accessible.' : `✗ ${sharedTestResult.error || 'Access failed.'}`}
              </div>
            )}
          </div>
        </details>
      ) : null}

      {createError && (
        <div style={{ color: 'var(--fail)', background: 'var(--surface-sunken)', border: '1px solid var(--fail)', padding: 12, borderRadius: 8, fontSize: 14 }}>
          {createError}
        </div>
      )}

      {/* Create project button row */}
      {folderPath ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16 }}>
          <button
            type="button"
            disabled={create.pending || selectedCount === 0}
            onClick={() => void handleCreateProject()}
            style={{
              display: 'inline-block',
              fontSize: 16,
              fontWeight: 600,
              padding: '14px 24px',
              borderRadius: 10,
              border: 'none',
              background: '#0F766E',
              color: '#FFFFFF',
              cursor: 'pointer',
            }}
          >
            {create.pending ? 'Creating…' : 'Create project'}
          </button>
          <span style={{ fontSize: 14, color: 'var(--text-muted)' }}>
            {selectedCount} repo{selectedCount === 1 ? '' : 's'} · {teamLabel} · settings saved to sentinel.config.yaml
          </span>
        </div>
      ) : null}
    </div>
  );
}
