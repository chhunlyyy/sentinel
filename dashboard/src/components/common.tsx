import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import type { ApiError } from '../api/errors.ts';
import type { UseResult } from '../state/app.tsx';
import { useApp } from '../state/app.tsx';
import { ErrorView } from './ErrorView.tsx';
import { Link } from '../router.tsx';

export function Loaded<T>({ res, children, unavailable }: { res: UseResult<T>; children: (data: T) => ReactNode; unavailable?: boolean }) {
  if (res.error && !res.data) {
    if (unavailable) {
      return (
        <div className="banner danger" data-testid="unavailable">
          <p>Connection unavailable</p>
          <p className="hint">{res.error.text}</p>
          <button type="button" className="secondary" onClick={() => void res.reload()}>
            Check again
          </button>
        </div>
      );
    }
    return <ErrorView error={res.error} />;
  }
  if (!res.data) return <p className="loading" role="status"><span className="spinner" aria-hidden="true" />Loading</p>;
  return <>{children(res.data)}</>;
}

const ICONS: Record<string, string> = { ok: '✓', warn: '!', fail: '✗', none: '–', wait: '…' };

export function StatusChip({ kind, label }: { kind: 'ok' | 'warn' | 'fail' | 'none' | 'wait'; label: string }) {
  const cls = kind === 'ok' ? 'ok-text' : kind === 'warn' ? 'warn-text' : kind === 'fail' ? 'danger-text' : '';
  return (
    <span className={`status-chip ${cls}`}>
      <span aria-hidden="true" data-testid="status-icon">
        {ICONS[kind]}
      </span>
      <span data-testid="status-text">{label}</span>
    </span>
  );
}

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="secondary"
      aria-label={label ?? `Copy ${text}`}
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(
          () => setCopied(true),
          () => setCopied(false),
        );
      }}
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

export function Tabs({ label, items }: { label: string; items: { to: string; label: string; current: boolean }[] }) {
  return (
    <nav aria-label={label}>
      <ul className="tabs">
        {items.map((i) => (
          <li key={i.to}>
            <Link to={i.to} current={i.current}>
              {i.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function actionErrorText(e: ApiError): string {
  if (e.network) return 'Not confirmed: the server did not answer. Check the run state.';
  if (e.code === 'E_CSRF') return 'The action was not sent. Check the run state and try again.';
  if (e.code === 'E_INTERNAL' || (e.status >= 500 && !e.code)) return 'Not confirmed: server error. See the terminal running sentinel dashboard.';
  return e.text;
}

export interface ActionState {
  pending: boolean;
  message: { kind: 'ok' | 'error'; text: string } | null;
  error: ApiError | null;
  /** runs fn once; a second call while the first is in flight is ignored */
  run: <T>(fn: () => Promise<T>, ok: (r: T) => string, opts?: { onError?: (e: ApiError) => string | undefined; onSettled?: () => void }) => Promise<T | undefined>;
  clear: () => void;
}

export function useAction(): ActionState {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<ActionState['message']>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const busy = useRef(false);
  const run: ActionState['run'] = useCallback(async (fn, ok, opts) => {
    if (busy.current) return undefined;
    busy.current = true;
    setPending(true);
    setMessage(null);
    setError(null);
    try {
      const result = await fn();
      setMessage({ kind: 'ok', text: ok(result) });
      return result;
    } catch (e) {
      const err = e as ApiError;
      setError(err);
      setMessage({ kind: 'error', text: opts?.onError?.(err) ?? actionErrorText(err) });
      return undefined;
    } finally {
      busy.current = false;
      setPending(false);
      opts?.onSettled?.();
    }
  }, []);
  const clear = useCallback(() => {
    setMessage(null);
    setError(null);
  }, []);
  return { pending, message, error, run, clear };
}

/** The result of an action. A status region that takes focus so keyboard users land on the outcome. */
export function ActionResult({ message }: { message: ActionState['message'] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (message) ref.current?.focus();
  }, [message]);
  if (!message) return null;
  return (
    <div ref={ref} role="status" tabIndex={-1} data-testid="action-result" className={`banner ${message.kind === 'ok' ? 'ok' : 'danger'}`}>
      {message.text}
    </div>
  );
}

export interface ConfirmDialogProps {
  text: string;
  confirmLabel: string;
  cancelLabel: string;
  initialFocus?: 'cancel' | 'comment';
  danger?: boolean;
  pending?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}

/** Modal dialog with a focus trap. Escape closes it without confirming; focus returns to the opener. */
export function ConfirmDialog(p: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const id = useId();
  const openerRef = useRef<Element | null>(null);

  useEffect(() => {
    openerRef.current = document.activeElement;
    const el = ref.current;
    if (el && !el.open) {
      if (typeof el.showModal === 'function') el.showModal();
      else el.setAttribute('open', '');
    }
    if (p.initialFocus === 'comment') el?.querySelector<HTMLElement>('textarea, input')?.focus();
    else cancelRef.current?.focus();
    return () => {
      const opener = openerRef.current as HTMLElement | null;
      if (opener && document.contains(opener)) opener.focus();
    };
    // run once on open
  }, []);

  const onKeyDown = (e: KeyboardEvent<HTMLDialogElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      p.onCancel();
      return;
    }
    if (e.key !== 'Tab') return;
    const focusable = Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not([disabled]), textarea, input, select, [href]') ?? []);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <dialog ref={ref} aria-labelledby={id} onKeyDown={onKeyDown} onCancel={(e) => { e.preventDefault(); p.onCancel(); }}>
      <p id={id}>{p.text}</p>
      {p.children}
      <div className="row">
        <button ref={cancelRef} type="button" className="secondary" onClick={p.onCancel}>
          {p.cancelLabel}
        </button>
        <button type="button" className={p.danger ? 'danger' : undefined} disabled={p.confirmDisabled || p.pending} onClick={p.onConfirm}>
          {p.pending ? 'Sending' : p.confirmLabel}
        </button>
      </div>
    </dialog>
  );
}

/** Controls are disabled while the live connection is down, so nothing is decided on a stale view. */
export function useControlsEnabled(): boolean {
  return useApp().status === 'connected';
}
