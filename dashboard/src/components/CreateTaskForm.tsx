import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react';

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
}

export interface CreateTaskFormProps {
  repos: string[];
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
}: CreateTaskFormProps) {
  const uid = useId();
  const [slug, setSlug] = useState('');
  const [request, setRequest] = useState('');
  const [type, setType] = useState('');
  const [priority, setPriority] = useState('normal');
  const [tier, setTier] = useState('');
  const [ticket, setTicket] = useState('');
  const [chosen, setChosen] = useState<string[]>(repos);
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
          if (Array.isArray(parsed.repos) && parsed.repos.length) setChosen(parsed.repos);
        }
      }
    } catch {
      // storage errors must not crash
    }
  }, [draftKey]);

  useEffect(() => setChosen(repos), [repos.join('|')]);

  const touch = (k: string) => setTouched((t) => ({ ...t, [k]: true }));
  const errors: Record<string, string> = {};
  if (!slug) errors.slug = 'Required';
  else if (!SLUG.test(slug)) errors.slug = 'Use lower-case letters, digits and single hyphens';
  if (!request.trim()) errors.request = 'Required';
  if (!type) errors.type = 'Required';
  if (repos.length && chosen.length === 0) errors.repos = 'Pick at least one repository';
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

  const saveDraft = () => {
    if (!draftKey) return;
    const draftData: CreateTaskBody = {
      slug,
      request,
      type,
      priority,
      ...(tier ? { tier: Number(tier) } : {}),
      ...(ticket.trim() ? { ticket: ticket.trim() } : {}),
      ...(chosen.length ? { repos: chosen } : {}),
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
    if (invalid || blocked || pending || busy.current) return;
    busy.current = true;
    const body: CreateTaskBody = { slug, request, type, priority };
    if (chosen.length !== repos.length) body.repos = chosen;
    if (tier) body.tier = Number(tier);
    if (ticket.trim()) body.ticket = ticket.trim();
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

      {/* Collapsible options as in NewTask mockup */}
      <details open className="panel" style={{ padding: '0.75rem 1rem' }}>
        <summary style={{ cursor: 'pointer', fontWeight: 600, marginBottom: '0.75rem' }}>
          Options (Sentinel chooses if you leave these)
        </summary>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
          {repos.length ? (
            <fieldset aria-describedby={shown('repos') ? `${uid}-repos-err` : undefined} style={{ margin: 0, padding: 0, border: 0 }}>
              <legend className="field-label" style={{ fontWeight: 600, marginBottom: '0.35rem' }}>Repositories</legend>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                {repos.map((r) => (
                  <label key={r} className="check" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <input
                      type="checkbox"
                      checked={chosen.includes(r)}
                      onChange={(e) => {
                        touch('repos');
                        setChosen((c) =>
                          e.target.checked
                            ? repos.filter((x) => c.includes(x) || x === r)
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
