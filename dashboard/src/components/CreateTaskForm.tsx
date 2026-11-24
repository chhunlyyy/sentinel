import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';
import type { Readiness } from '../api/types.ts';

export const TASK_TYPES = ['feature', 'bug', 'refactor', 'docs', 'chore'];
const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export interface CreateTaskBody {
  slug: string;
  request: string;
  type: string;
  repos?: string[];
  priority: string;
  tier?: number;
  ticket?: string;
  spec?: string;
}

export interface RepoItem {
  id: string;
  name?: string;
  stack?: string;
  role?: string;
}

export interface CreateTaskFormProps {
  repos: string[] | RepoItem[];
  pid?: string;
  onSubmit: (body: CreateTaskBody) => void | Promise<void>;
  onTypeChange?: (type: string) => void;
  onRequestChange?: (request: string) => void;
  /** server refusals by field name */
  fieldErrors?: Record<string, string>;
  pending?: boolean;
  /** extra reason to keep the button disabled, e.g. readiness */
  blocked?: boolean;
  submitLabel?: string;
  children?: ReactNode;
  simplified?: boolean;
  readiness?: Readiness | null;
}

function deriveSlug(text: string): string {
  const s = text
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  return s || `task-${Date.now().toString(36)}`;
}

export function CreateTaskForm({
  repos,
  pid,
  onSubmit,
  onTypeChange,
  onRequestChange,
  fieldErrors = {},
  pending = false,
  blocked = false,
  submitLabel = 'Create task',
  children,
  simplified = false,
  readiness = null,
}: CreateTaskFormProps) {
  const uid = useId();
  const repoIds = repos.map((r) => (typeof r === 'string' ? r : r.id));

  // Determine initial chosen repos (in simplified mode, pre-tick only clean repos)
  const isRepoClean = (rId: string) => {
    if (!readiness?.items) return true;
    return !readiness.items.some((i) => i.repo === rId && (i.status === 'failed' || i.status === 'warning'));
  };

  const [slug, setSlug] = useState('');
  const [request, setRequest] = useState('');
  const [type, setType] = useState(simplified ? 'feature' : '');
  const [priority, setPriority] = useState('normal');
  const [tier, setTier] = useState('');
  const [ticket, setTicket] = useState('');
  const [hasSpec, setHasSpec] = useState(false);
  const [spec, setSpec] = useState('');
  const [chosen, setChosen] = useState<string[]>(() => {
    if (simplified && readiness?.items) {
      return repoIds.filter(isRepoClean);
    }
    return repoIds;
  });
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [draftSaved, setDraftSaved] = useState(false);
  const busy = useRef(false);

  const draftKey = pid ? `sentinel_task_draft_${pid}` : null;

  useEffect(() => {
    if (!draftKey) return;
    try {
      const raw = window.localStorage.getItem(draftKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object') {
          if (parsed.slug) setSlug(parsed.slug);
          if (parsed.request) {
            setRequest(parsed.request);
            onRequestChange?.(parsed.request);
          }
          if (parsed.type) {
            setType(parsed.type);
            onTypeChange?.(parsed.type);
          }
          if (parsed.priority) setPriority(parsed.priority);
          if (parsed.tier !== undefined && parsed.tier !== null) setTier(String(parsed.tier));
          if (parsed.ticket) setTicket(parsed.ticket);
          if (parsed.spec) {
            setSpec(parsed.spec);
            setHasSpec(true);
          }
          if (Array.isArray(parsed.repos) && parsed.repos.length) setChosen(parsed.repos);
        }
      }
    } catch {
      // storage errors must not crash
    }
  }, [draftKey]);

  useEffect(() => {
    if (simplified && readiness?.items) {
      setChosen(repoIds.filter(isRepoClean));
    } else {
      setChosen(repoIds);
    }
  }, [repoIds.join('|'), readiness]);

  // Check if any selected repo is blocked
  const blockedRepoItem = readiness?.items?.find(
    (i) => (i.status === 'failed' || i.status === 'warning') && i.repo && chosen.includes(i.repo),
  );
  const isReadinessBlocked = Boolean(blockedRepoItem);

  const touch = (k: string) => setTouched((t) => ({ ...t, [k]: true }));
  const errors: Record<string, string> = {};
  if (!simplified) {
    if (!slug) errors.slug = 'Required';
    else if (!SLUG.test(slug)) errors.slug = 'Use lower-case letters, digits and single hyphens';
    if (!type) errors.type = 'Required';
  }
  if (!request.trim()) errors.request = 'Required';
  if (repoIds.length && chosen.length === 0) errors.repos = 'Pick at least one repository';
  const invalid = Object.keys(errors).length > 0;

  const shown = (k: string): string | undefined => {
    if (touched[k] && errors[k]) return errors[k];
    return fieldErrors[k];
  };

  const handleTypeSelect = (selectedType: string) => {
    setType(selectedType);
    touch('type');
    onTypeChange?.(selectedType);
  };

  const handleUntickRepo = (repoName: string) => {
    setChosen((prev) => prev.filter((r) => r !== repoName));
  };

  const saveDraft = () => {
    if (!draftKey) return;
    const finalSlug = slug.trim() || deriveSlug(request);
    const draftData: CreateTaskBody = {
      slug: finalSlug,
      request,
      type: type || 'feature',
      priority,
      ...(tier ? { tier: Number(tier) } : {}),
      ...(ticket.trim() ? { ticket: ticket.trim() } : {}),
      ...(chosen.length ? { repos: chosen } : {}),
      ...(hasSpec && spec.trim() ? { spec: spec.trim() } : {}),
    };
    try {
      window.localStorage.setItem(draftKey, JSON.stringify(draftData));
      setDraftSaved(true);
      setTimeout(() => setDraftSaved(false), 3000);
    } catch {
      // storage errors must not crash
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (invalid || blocked || isReadinessBlocked || pending || busy.current) return;
    busy.current = true;
    const finalSlug = slug.trim() || deriveSlug(request);
    const finalType = type || 'feature';
    const body: CreateTaskBody = { slug: finalSlug, request, type: finalType, priority };
    if (chosen.length !== repoIds.length) body.repos = chosen;
    if (tier) body.tier = Number(tier);
    if (ticket.trim()) body.ticket = ticket.trim();
    if (hasSpec && spec.trim()) body.spec = spec.trim();
    try {
      await onSubmit(body);
      if (draftKey) {
        try {
          window.localStorage.removeItem(draftKey);
        } catch {
          // ignore
        }
      }
    } finally {
      busy.current = false;
    }
  };

  const err = (k: string) => {
    const m = shown(k);
    return m ? (
      <p className="field-error" id={`${uid}-${k}-err`}>
        {m}
      </p>
    ) : null;
  };
  const aria = (k: string) => ({
    'aria-invalid': shown(k) ? (true as const) : undefined,
    'aria-describedby': shown(k) ? `${uid}-${k}-err` : undefined,
  });

  // SIMPLIFIED NEW TASK FORM (matches NewTask.dc.html)
  if (simplified) {
    const isStartDisabled = !request.trim() || chosen.length === 0 || blocked || isReadinessBlocked || pending;
    const startHint = isReadinessBlocked
      ? 'Fix the repo problem above first.'
      : blocked
      ? 'Fix configuration problems first.'
      : !request.trim()
      ? 'Enter what the factory should build above.'
      : chosen.length === 0
      ? 'Pick at least one repository.'
      : 'About 5 minutes until the spec is ready for you.';

    return (
      <form onSubmit={(e) => void submit(e)} noValidate style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: 24, display: 'flex', flexDirection: 'column', gap: 22, color: 'var(--text)' }}>
          {/* Main prompt input */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label htmlFor="what" style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>
              What should the factory build or fix?
            </label>
            <textarea
              id="what"
              aria-label="Request"
              rows={5}
              placeholder="Describe the change in plain words..."
              value={request}
              onChange={(e) => {
                const val = e.target.value;
                setRequest(val);
                touch('request');
                onRequestChange?.(val);
              }}
              style={{
                fontSize: 15,
                lineHeight: 1.5,
                padding: 12,
                border: '1px solid var(--border)',
                background: 'var(--surface)',
                borderRadius: 10,
                resize: 'vertical',
                color: 'var(--text)',
                fontFamily: 'inherit',
              }}
              {...aria('request')}
            />
            {err('request')}
          </div>

          {/* Already have a spec? */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>
              Already have a spec? <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>(optional)</span>
            </span>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, border: '1px dashed var(--border)', borderRadius: 10, padding: 14 }}>
              <label style={{ cursor: 'pointer', fontSize: 14, padding: '10px 14px', border: '1px solid var(--border)', background: 'var(--surface)', borderRadius: 8, color: 'var(--text)', display: 'inline-block' }}>
                Choose file…
                <input
                  type="file"
                  accept=".md,.txt,text/plain,text/markdown"
                  style={{ display: 'none' }}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    const reader = new FileReader();
                    reader.onload = (ev) => {
                      const text = ev.target?.result;
                      if (typeof text === 'string') {
                        setSpec(text);
                        setHasSpec(true);
                      }
                    };
                    reader.readAsText(file);
                  }}
                />
              </label>
              <span style={{ fontSize: 14, color: 'var(--text-muted)' }}>
                {hasSpec && spec ? 'Specification loaded from file.' : 'or drop a Markdown file here. Missing sections are drafted for you.'}
              </span>
            </div>
          </div>

          {/* Repos as tick chips */}
          <fieldset
            aria-label="Repositories"
            style={{ border: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 10 }}
            {...aria('repos')}
          >
            <legend style={{ fontSize: 15, fontWeight: 600, marginBottom: 4, padding: 0, color: 'var(--text)' }}>
              Which repos does it touch?
            </legend>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: -4 }}>
              Suggested from your text. Tick more if needed.
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
              {repoIds.map((rId) => {
                const isSelected = chosen.includes(rId);
                const repoObj = typeof repos[0] === 'object' ? (repos as RepoItem[]).find((r) => r.id === rId) : null;
                const kind = repoObj?.stack || repoObj?.role || 'git';
                return (
                  <label
                    key={rId}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 8,
                      padding: '10px 14px',
                      borderRadius: 10,
                      cursor: 'pointer',
                      border: isSelected ? '1px solid var(--accent)' : '1px solid var(--border)',
                      background: isSelected ? 'var(--accent-soft)' : 'var(--surface)',
                      color: 'var(--text)',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={(e) => {
                        touch('repos');
                        setChosen((c) => (e.target.checked ? [...c, rId] : c.filter((x) => x !== rId)));
                      }}
                      style={{ width: 18, height: 18, accentColor: 'var(--accent)' }}
                    />
                    <span style={{ fontSize: 14, fontWeight: isSelected ? 600 : 400 }}>{rId}</span>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{kind}</span>
                  </label>
                );
              })}
            </div>
            {err('repos')}
          </fieldset>

          {/* ONE-LINE READINESS STATUS */}
          {isReadinessBlocked && blockedRepoItem ? (
            <div
              role="status"
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                alignItems: 'center',
                gap: 12,
                background: '#FDF5E6',
                border: '1px solid #E8C98F',
                borderRadius: 10,
                padding: '12px 14px',
                fontSize: 14,
                color: '#5C2E03',
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#9A4D06" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="9"></circle>
                <path d="M12 8v5"></path>
                <path d="M12 16h.01"></path>
              </svg>
              <span style={{ flex: '1 1 300px' }}>
                {blockedRepoItem.repo} {blockedRepoItem.message || "is not a git folder, so the factory can't track its changes."}
              </span>
              <button
                type="button"
                onClick={() => handleUntickRepo(blockedRepoItem.repo!)}
                style={{
                  fontSize: 14,
                  padding: '8px 12px',
                  border: '1px solid #D6B57A',
                  background: '#FFFFFF',
                  borderRadius: 8,
                  color: '#5C2E03',
                  cursor: 'pointer',
                }}
              >
                Untick {blockedRepoItem.repo}
              </button>
            </div>
          ) : (
            <div role="status" style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14, color: 'var(--ok)' }}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M20 6L9 17l-5-5"></path>
              </svg>
              Ready. AI team and repos checked.
            </div>
          )}

          {/* More options details dropdown */}
          <details
            open={Boolean(shown('slug') || shown('type') || shown('tier')) || undefined}
            style={{ fontSize: 14, color: 'var(--text)' }}
          >
            <summary style={{ cursor: 'pointer', color: 'var(--text)' }}>More options</summary>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, marginTop: 12 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 6, color: 'var(--text)' }}>
                Slug
                <input
                  aria-label="Slug"
                  value={slug}
                  placeholder="Leave empty to derive from text"
                  onChange={(e) => {
                    setSlug(e.target.value);
                    touch('slug');
                  }}
                  style={{
                    fontSize: 14,
                    padding: '8px 10px',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    background: 'var(--surface)',
                    color: 'var(--text)',
                  }}
                  {...aria('slug')}
                />
                {err('slug')}
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 6, color: 'var(--text)' }}>
                Kind
                <select
                  aria-label="Type"
                  value={type}
                  onChange={(e) => handleTypeSelect(e.target.value)}
                  style={{
                    fontSize: 14,
                    padding: '8px 10px',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    background: 'var(--surface)',
                    color: 'var(--text)',
                  }}
                  {...aria('type')}
                >
                  <option value="feature">Let Sentinel decide</option>
                  <option value="feature">Feature</option>
                  <option value="bug">Bug fix</option>
                  <option value="docs">Docs only</option>
                </select>
                {err('type')}
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 6, color: 'var(--text)' }}>
                How careful
                <select
                  aria-label="Tier"
                  value={tier}
                  onChange={(e) => setTier(e.target.value)}
                  style={{
                    fontSize: 14,
                    padding: '8px 10px',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    background: 'var(--surface)',
                    color: 'var(--text)',
                  }}
                >
                  <option value="">Let Sentinel decide</option>
                  <option value="1">Quick (tier 1)</option>
                  <option value="2">Standard (tier 2)</option>
                  <option value="3">Thorough (tier 3)</option>
                  <option value="4">Critical (tier 4)</option>
                </select>
              </label>
            </div>
          </details>
        </div>

        {children}

        {/* Start button row */}
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16 }}>
          <button
            type="submit"
            disabled={isStartDisabled}
            style={{
              fontSize: 16,
              fontWeight: 600,
              padding: '14px 24px',
              borderRadius: 10,
              border: 'none',
              cursor: isStartDisabled ? 'not-allowed' : 'pointer',
              background: isStartDisabled ? '#E4E3DE' : '#0F766E',
              color: isStartDisabled ? 'var(--text-muted)' : '#FFFFFF',
            }}
          >
            {pending ? 'Sending' : submitLabel || 'Start task'}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={saveDraft}
            style={{
              fontSize: 14,
              padding: '12px 16px',
              borderRadius: 10,
              border: '1px solid var(--border)',
              background: 'var(--surface)',
              color: 'var(--text)',
              cursor: 'pointer',
            }}
          >
            Save as draft
          </button>
          {draftSaved && <span style={{ fontSize: 14, color: 'var(--ok)' }}>Draft saved</span>}
          <span style={{ fontSize: 14, color: 'var(--text-muted)' }}>{startHint}</span>
        </div>
      </form>
    );
  }

  // STANDARD FORM (for unit test compatibility)
  return (
    <form onSubmit={(e) => void submit(e)} noValidate style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <p className="banner">
        Creating a task does not approve anything. The specification and the Gherkin scenarios need your approval before any code is written.
      </p>

      {/* Kind quick selectors */}
      <fieldset style={{ margin: 0, padding: 0, border: 0 }}>
        <legend className="field-label" style={{ fontWeight: 600, marginBottom: '0.4rem' }}>Kind</legend>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
          {[
            { id: 'feature', label: 'Feature' },
            { id: 'bug', label: 'Bug fix' },
            { id: 'docs', label: 'Docs only' },
          ].map((k) => (
            <button
              key={k.id}
              type="button"
              className={type === k.id ? '' : 'secondary'}
              aria-pressed={type === k.id}
              onClick={() => handleTypeSelect(k.id)}
              style={{ minHeight: '2.4rem', padding: '0 1rem' }}
            >
              {k.label}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="field">
        <label htmlFor={`${uid}-slug`}>Slug</label>
        <input
          id={`${uid}-slug`}
          type="text"
          value={slug}
          autoComplete="off"
          placeholder="e.g. leave-balance-export"
          onChange={(e) => {
            setSlug(e.target.value);
            touch('slug');
          }}
          {...aria('slug')}
        />
        {err('slug')}
      </div>

      <div className="field">
        <label htmlFor={`${uid}-request`}>Request</label>
        <textarea
          id={`${uid}-request`}
          rows={6}
          placeholder="Describe what should be built in plain words…"
          value={request}
          onChange={(e) => {
            const val = e.target.value;
            setRequest(val);
            touch('request');
            onRequestChange?.(val);
          }}
          {...aria('request')}
        />
        {err('request')}
      </div>

      <div className="field">
        <label htmlFor={`${uid}-type`}>Type</label>
        <select
          id={`${uid}-type`}
          value={type}
          onChange={(e) => handleTypeSelect(e.target.value)}
          {...aria('type')}
        >
          <option value="">Select a type</option>
          {TASK_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        {err('type')}
      </div>

      <div className="field">
        <label className="check" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <input
            id={`${uid}-has-spec`}
            type="checkbox"
            checked={hasSpec}
            onChange={(e) => setHasSpec(e.target.checked)}
          />
          <span>I already have a spec</span>
        </label>
      </div>

      {hasSpec ? (
        <div className="field">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '0.25rem' }}>
            <label htmlFor={`${uid}-spec`}>Specification</label>
            <label className="secondary" style={{ cursor: 'pointer', fontSize: '0.85rem' }}>
              Upload file
              <input
                type="file"
                accept=".md,.txt,text/plain,text/markdown"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  const reader = new FileReader();
                  reader.onload = (ev) => {
                    const text = ev.target?.result;
                    if (typeof text === 'string') {
                      setSpec(text);
                    }
                  };
                  reader.readAsText(file);
                }}
              />
            </label>
          </div>
          <textarea
            id={`${uid}-spec`}
            rows={8}
            placeholder="Paste your pre-drafted specification here…"
            value={spec}
            onChange={(e) => setSpec(e.target.value)}
          />
        </div>
      ) : null}

      {/* Collapsible options */}
      <details open className="panel" style={{ padding: '0.75rem 1rem' }}>
        <summary style={{ cursor: 'pointer', fontWeight: 600, marginBottom: '0.75rem' }}>
          Options (Sentinel chooses if you leave these)
        </summary>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
          {repoIds.length ? (
            <fieldset aria-describedby={shown('repos') ? `${uid}-repos-err` : undefined} style={{ margin: 0, padding: 0, border: 0 }}>
              <legend className="field-label" style={{ fontWeight: 600, marginBottom: '0.35rem' }}>Repositories</legend>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                {repoIds.map((r) => (
                  <label key={r} className="check" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <input
                      type="checkbox"
                      checked={chosen.includes(r)}
                      onChange={(e) => {
                        touch('repos');
                        setChosen((c) =>
                          e.target.checked
                            ? repoIds.filter((x) => c.includes(x) || x === r)
                            : c.filter((x) => x !== r),
                        );
                      }}
                    />
                    <span>{r}</span>
                  </label>
                ))}
              </div>
              {err('repos')}
            </fieldset>
          ) : null}

          <div className="field">
            <label htmlFor={`${uid}-tier`}>Tier</label>
            <select id={`${uid}-tier`} value={tier} onChange={(e) => setTier(e.target.value)}>
              <option value="">Decided at triage</option>
              {[1, 2, 3, 4].map((t) => (
                <option key={t} value={String(t)}>
                  {t}
                </option>
              ))}
            </select>
            <p className="hint">A tier can only raise the triage result.</p>
          </div>

          <div className="field">
            <label htmlFor={`${uid}-priority`}>Priority</label>
            <select id={`${uid}-priority`} value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="low">low</option>
              <option value="normal">normal</option>
              <option value="high">high</option>
            </select>
          </div>

          <div className="field">
            <label htmlFor={`${uid}-ticket`}>Ticket</label>
            <input
              id={`${uid}-ticket`}
              type="text"
              placeholder="e.g. HR-12 or https://…"
              value={ticket}
              autoComplete="off"
              onChange={(e) => setTicket(e.target.value)}
            />
          </div>
        </div>
      </details>

      {children}

      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="submit" disabled={invalid || blocked || pending}>
          {pending ? 'Sending…' : submitLabel}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={saveDraft}
          style={{ cursor: 'pointer' }}
        >
          Save as draft
        </button>
        {draftSaved ? (
          <span style={{ fontSize: '0.85rem', color: '#4FD1C1' }}>Draft saved</span>
        ) : null}
      </div>
    </form>
  );
}
