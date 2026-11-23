import { useEffect, useId, useRef, useState } from 'react';
import { ConfirmDialog } from './common.tsx';

export type Decision = 'approve' | 'changes' | 'reject' | 'accept';

export interface DecisionPanelProps {
  kind: 'approval' | 'acceptance';
  gate?: 'specification' | 'gherkin';
  sha256: string;
  version?: number;
  /** the run the decision is about, named in the second confirmation */
  subject?: string;
  /** which choices are offered; default depends on kind */
  allow?: Decision[];
  disabled?: boolean;
  pending?: boolean;
  onDecide: (d: { decision: Decision; comment: string | null; confirmation?: string }) => void | Promise<void>;
}

export function DecisionPanel(props: DecisionPanelProps) {
  const uid = useId();
  const [mode, setMode] = useState<'idle' | 'changes'>('idle');
  const [changesText, setChangesText] = useState('');
  const [rejectReason, setRejectReason] = useState('');
  const [confirmReject, setConfirmReject] = useState(false);
  const busy = useRef(false);

  const changesTextareaRef = useRef<HTMLTextAreaElement>(null);
  const requestChangesBtnRef = useRef<HTMLButtonElement>(null);
  const rejectBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (mode === 'changes') {
      changesTextareaRef.current?.focus();
    }
  }, [mode]);

  const send = async (decision: Decision, comment: string | null) => {
    if (busy.current) return;
    busy.current = true;
    try {
      await props.onDecide({ decision, comment });
    } finally {
      busy.current = false;
    }
  };

  const cancelChanges = () => {
    setMode('idle');
    setChangesText('');
    setTimeout(() => {
      requestChangesBtnRef.current?.focus();
    }, 0);
  };

  const agentRole = props.gate === 'gherkin' ? 'scenario writer' : 'specifier';
  const rejectText =
    props.kind === 'approval'
      ? `Rejecting cancels run ${props.subject ?? ''}. This cannot be undone.`
      : `Rejecting the acceptance of run ${props.subject ?? ''}. This cannot be undone.`;

  const canApprove = !props.allow || props.allow.includes('approve');
  const canChanges = !props.allow || props.allow.includes('changes');
  const canReject = !props.allow || props.allow.includes('reject');
  const canAccept = !props.allow || props.allow.includes('accept');

  return (
    <div className="panel" data-testid="decision-panel">
      {mode === 'changes' ? (
        <div className="field">
          <label htmlFor={`${uid}-changes`}>What needs to change</label>
          <textarea
            id={`${uid}-changes`}
            ref={changesTextareaRef}
            value={changesText}
            disabled={props.disabled || props.pending}
            placeholder="Add a scenario for inactive parent departments"
            onChange={(e) => setChangesText(e.target.value)}
          />
          <p className="hint">
            The {agentRole} gets this text and writes a new version.
          </p>
          <div className="row" style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
            <button
              type="button"
              className="btn-primary btn-send-changes"
              disabled={changesText.trim() === '' || props.disabled || props.pending}
              onClick={() => void send('changes', changesText.trim())}
            >
              {props.pending ? 'Sending' : 'Send back to the agent'}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={props.disabled || props.pending}
              onClick={cancelChanges}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="decision-actions" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
          {props.kind === 'approval' ? (
            <>
              {canApprove && (
                <button
                  type="button"
                  className="btn-primary btn-approve"
                  disabled={props.disabled || props.pending}
                  onClick={() => void send('approve', null)}
                >
                  {props.pending ? 'Sending' : props.version ? `Approve version ${props.version}` : 'Approve'}
                </button>
              )}
              {canChanges && (
                <button
                  type="button"
                  ref={requestChangesBtnRef}
                  className="secondary btn-changes"
                  disabled={props.disabled || props.pending}
                  onClick={() => setMode('changes')}
                >
                  Request changes
                </button>
              )}
              {canReject && (
                <button
                  type="button"
                  ref={rejectBtnRef}
                  className="secondary tertiary btn-reject"
                  style={{ fontSize: '13px' }}
                  disabled={props.disabled || props.pending}
                  onClick={() => setConfirmReject(true)}
                >
                  Reject run…
                </button>
              )}
            </>
          ) : (
            <>
              {canAccept && (
                <button
                  type="button"
                  className="btn-primary btn-accept"
                  disabled={props.disabled || props.pending}
                  onClick={() => void send('accept', null)}
                >
                  {props.pending ? 'Sending' : 'Accept'}
                </button>
              )}
              {canReject && (
                <button
                  type="button"
                  ref={rejectBtnRef}
                  className="secondary tertiary btn-reject"
                  style={{ fontSize: '13px' }}
                  disabled={props.disabled || props.pending}
                  onClick={() => setConfirmReject(true)}
                >
                  Reject…
                </button>
              )}
            </>
          )}
        </div>
      )}

      {confirmReject ? (
        <ConfirmDialog
          text={rejectText}
          cancelLabel="Cancel"
          confirmLabel="Reject run"
          danger
          initialFocus="comment"
          confirmDisabled={rejectReason.trim() === ''}
          pending={props.pending}
          onCancel={() => {
            setConfirmReject(false);
            setRejectReason('');
          }}
          onConfirm={() => {
            void send('reject', rejectReason.trim()).finally(() => {
              setConfirmReject(false);
              setRejectReason('');
            });
          }}
        >
          <div className="field">
            <label htmlFor={`${uid}-reject-reason`}>Reason</label>
            <textarea
              id={`${uid}-reject-reason`}
              value={rejectReason}
              disabled={props.disabled || props.pending}
              placeholder="Reason for rejection"
              onChange={(e) => setRejectReason(e.target.value)}
            />
            <p className="hint">Required</p>
          </div>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}
