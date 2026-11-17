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
  onSubmit: (body: CreateTaskBody) => void | Promise<void>;
  onTypeChange?: (type: string) => void;
  /** server refusals by field name */
  fieldErrors?: Record<string, string>;
  pending?: boolean;
  /** extra reason to keep the button disabled, e.g. readiness */
  blocked?: boolean;
  children?: ReactNode;
}

export function CreateTaskForm({ repos, onSubmit, onTypeChange, fieldErrors = {}, pending = false, blocked = false, children }: CreateTaskFormProps) {
  const uid = useId();
  const [slug, setSlug] = useState('');
  const [request, setRequest] = useState('');
  const [type, setType] = useState('');
  const [priority, setPriority] = useState('normal');
  const [tier, setTier] = useState('');
  const [ticket, setTicket] = useState('');
  const [chosen, setChosen] = useState<string[]>(repos);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const busy = useRef(false);

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
  const aria = (k: string) => ({ 'aria-invalid': shown(k) ? (true as const) : undefined, 'aria-describedby': shown(k) ? `${uid}-${k}-err` : undefined });

  return (
    <form onSubmit={(e) => void submit(e)} noValidate>
      <p className="banner">Creating a task does not approve anything. The specification and the Gherkin scenarios need your approval before any code is written.</p>
      <div className="field">
        <label htmlFor={`${uid}-slug`}>Slug</label>
        <input id={`${uid}-slug`} type="text" value={slug} autoComplete="off" onChange={(e) => { setSlug(e.target.value); touch('slug'); }} {...aria('slug')} />
        {err('slug')}
      </div>
      <div className="field">
        <label htmlFor={`${uid}-request`}>Request</label>
        <textarea id={`${uid}-request`} value={request} onChange={(e) => { setRequest(e.target.value); touch('request'); }} {...aria('request')} />
        {err('request')}
      </div>
      <div className="field">
        <label htmlFor={`${uid}-type`}>Type</label>
        <select id={`${uid}-type`} value={type} onChange={(e) => { setType(e.target.value); touch('type'); onTypeChange?.(e.target.value); }} {...aria('type')}>
          <option value="">Select a type</option>
          {TASK_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        {err('type')}
      </div>
      {repos.length ? (
        <fieldset aria-describedby={shown('repos') ? `${uid}-repos-err` : undefined}>
          <legend className="field-label">Repositories</legend>
          {repos.map((r) => (
            <label key={r}>
              <input
                type="checkbox"
                checked={chosen.includes(r)}
                onChange={(e) => {
                  touch('repos');
                  setChosen((c) => (e.target.checked ? repos.filter((x) => c.includes(x) || x === r) : c.filter((x) => x !== r)));
                }}
              />{' '}
              {r}{' '}
            </label>
          ))}
          {err('repos')}
        </fieldset>
      ) : null}
      <div className="field">
        <label htmlFor={`${uid}-priority`}>Priority</label>
        <select id={`${uid}-priority`} value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="low">low</option>
          <option value="normal">normal</option>
          <option value="high">high</option>
        </select>
      </div>
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
        <label htmlFor={`${uid}-ticket`}>Ticket</label>
        <input id={`${uid}-ticket`} type="text" value={ticket} autoComplete="off" onChange={(e) => setTicket(e.target.value)} />
      </div>
      {children}
      <button type="submit" disabled={invalid || blocked || pending}>
        {pending ? 'Sending' : 'Create task'}
      </button>
    </form>
  );
}
