import { useEffect, useId, useRef, useState } from 'react';
import { ConfirmDialog } from './common.tsx';

export type Decision = 'approve' | 'changes' | 'reject' | 'accept';

export interface DecisionChoice {
  id: Decision;
  radio: string;
  button: string;
  commentRequired: boolean;
}

export interface DecisionPanelProps {
  kind: 'approval' | 'acceptance';
  sha256: string;
  version?: number;
  /** the run the decision is about, named in the second confirmation */
  subject?: string;
  /** which choices are offered; default depends on kind */
  allow?: Decision[];
  disabled?: boolean;
  pending?: boolean;
  onDecide: (d: { decision: Decision; confirmation: string; comment: string | null }) => void | Promise<void>;
}

function choicesFor(kind: 'approval' | 'acceptance', version: number | undefined): DecisionChoice[] {
  if (kind === 'approval') {
    return [
      { id: 'approve', radio: 'Approve', button: `Approve version ${version}`, commentRequired: false },
      { id: 'changes', radio: 'Request changes', button: 'Request changes', commentRequired: true },
      { id: 'reject', radio: 'Reject', button: `Reject version ${version}`, commentRequired: true },
    ];
  }
  return [
    { id: 'accept', radio: 'Accept', button: 'Confirm acceptance', commentRequired: false },
    { id: 'reject', radio: 'Reject', button: 'Reject', commentRequired: true },
  ];
}

/**
 * The reviewer types the first 8 characters of the sha256 shown on the page. The field is never
 * filled in for them (paste is allowed) and the full hash is compared by the server.
 */
export function DecisionPanel(props: DecisionPanelProps) {
  const uid = useId();
  const all = choicesFor(props.kind, props.version);
  const choices = props.allow ? all.filter((c) => props.allow!.includes(c.id)) : all;
  const [choice, setChoice] = useState<Decision | null>(props.kind === 'acceptance' ? (choices[0]?.id ?? null) : null);
  const [typed, setTyped] = useState('');
  const [comment, setComment] = useState('');
  const [confirmReject, setConfirmReject] = useState(false);
  const busy = useRef(false);
  const want = props.sha256.slice(0, 8);

  useEffect(() => {
    if (props.kind === 'acceptance' && choice === null && choices.length) setChoice(choices[0].id);
  }, [props.kind, choice, choices]);

  const current = choices.find((c) => c.id === choice) ?? null;
  const matches = typed === want;
  const hint = typed.length < 8 ? 'Type the first 8 characters' : matches ? 'Matches' : 'Does not match';
  const commentOk = !current?.commentRequired || comment.trim() !== '';
  const ready = !!current && matches && commentOk && !props.disabled && !props.pending;

  const send = async () => {
    if (!current || busy.current) return;
    busy.current = true;
    try {
      await props.onDecide({ decision: current.id, confirmation: typed, comment: comment.trim() === '' ? null : comment });
    } finally {
      busy.current = false;
    }
  };

  const press = () => {
    if (!ready || !current) return;
    if (current.id === 'reject') setConfirmReject(true);
    else void send();
  };

  const rejectText =
    props.kind === 'approval' ? `Rejecting cancels run ${props.subject ?? ''}. This cannot be undone.` : `Rejecting the acceptance of run ${props.subject ?? ''}. This cannot be undone.`;

  return (
    <div className="panel" data-testid="decision-panel">
      <fieldset disabled={props.disabled}>
        <legend className="field-label">Decision</legend>
        {choices.map((c) => (
          <label key={c.id}>
            <input
              type="radio"
              name={`${uid}-decision`}
              checked={choice === c.id}
              onChange={() => setChoice(c.id)}
            />{' '}
            {c.radio}{' '}
          </label>
        ))}
      </fieldset>
      {current ? (
        <>
          <div className="field">
            <label htmlFor={`${uid}-confirm`}>Type the first 8 characters of the sha256 to confirm</label>
            <input
              id={`${uid}-confirm`}
              type="text"
              value={typed}
              autoComplete="off"
              spellCheck={false}
              disabled={props.disabled}
              aria-describedby={`${uid}-hint`}
              onChange={(e) => setTyped(e.target.value)}
              className="mono"
            />
            <p className="hint" id={`${uid}-hint`}>
              {hint}
            </p>
          </div>
          <div className="field">
            <label htmlFor={`${uid}-comment`}>Comment</label>
            <textarea id={`${uid}-comment`} value={comment} disabled={props.disabled} onChange={(e) => setComment(e.target.value)} />
            <p className="hint">{current.commentRequired ? 'Required' : 'Optional'}</p>
          </div>
          <button type="button" disabled={!ready} onClick={press}>
            {props.pending ? 'Sending' : current.button}
          </button>
        </>
      ) : null}
      {confirmReject ? (
        <ConfirmDialog
          text={rejectText}
          cancelLabel="Cancel"
          confirmLabel="Reject run"
          danger
          pending={props.pending}
          onCancel={() => setConfirmReject(false)}
          onConfirm={() => {
            void send().finally(() => setConfirmReject(false));
          }}
        />
      ) : null}
    </div>
  );
}
