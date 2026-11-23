import type { ReactNode } from 'react';
import { useState, useRef, useEffect } from 'react';
import { calls } from '../../api/calls.ts';
import type { ApiError } from '../../api/errors.ts';
import type { Run } from '../../api/types.ts';
import { ActionResult, useAction, useControlsEnabled } from '../../components/common.tsx';
import { DecisionPanel, type Decision } from '../../components/DecisionPanel.tsx';
import { ErrorView } from '../../components/ErrorView.tsx';
import { useApp, useResource } from '../../state/app.tsx';
import { DecisionRecordView } from '../Approvals.tsx';

export function AcceptanceTab({ run, pid, onChanged, compact }: { run: Run | { slug: string; state: string }; pid: string; onChanged: () => void; compact?: boolean }) {
  const app = useApp();
  const enabled = useControlsEnabled();
  const verification = useResource(`acc-verification-${pid}-${run.slug}`, (c) => calls.verification(c, run.slug, pid), { project: pid, run: run.slug });
  const report = useResource(`acc-report-${pid}-${run.slug}`, (c) => calls.report(c, run.slug, pid), { project: pid, run: run.slug });
  const action = useAction();
  const [done, setDone] = useState(false);
  const [fullScreen, setFullScreen] = useState(false);
  const expandBtnRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (fullScreen && dialogRef.current) {
      dialogRef.current.focus();
    }
  }, [fullScreen]);

  const closeFullScreen = () => {
    setFullScreen(false);
    expandBtnRef.current?.focus();
  };

  // Escape closes full screen; a key inside a native <dialog> (the reject confirmation) belongs to that dialog
  useEffect(() => {
    if (!fullScreen) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Escape' || (e.target instanceof Element && e.target.closest('dialog'))) return;
      closeFullScreen();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  });

  const record = verification.data?.acceptance_record ?? null;

  const decide = async (d: { decision: Decision; confirmation: string; comment: string | null }) => {
    const sha = report.data?.sha256;
    if (!sha) return;
    await action.run(
      () => calls.accept(app.client, run.slug, pid, { sha256_of_report: sha, confirmation: d.confirmation, decision: d.decision === 'accept' ? 'accept' : 'reject', comment: d.comment }),
      () => {
        setDone(true);
        return '';
      },
      {
        onError: (e: ApiError) => (e.code === 'E_APPROVAL_STALE' ? 'The report changed. Nothing was confirmed. Reload the report.' : undefined),
        onSettled: () => {
          onChanged();
          void report.reload();
          void verification.reload();
        },
      },
    );
  };

  const computed = verification.data?.acceptance;
  let body: ReactNode;
  if (record && record.decision === 'reject') {
    body = (
      <>
        <DecisionRecordView record={record} text="Rejected" />
        <p>This cannot change.</p>
      </>
    );
  } else if (run.state !== 'COMPLETED' && !record) {
    body = <p>Acceptance is possible when the run is COMPLETED</p>;
  } else if (!report.data || !verification.data) {
    body = report.error ? <ErrorView error={report.error} /> : <p className="hint" role="status">Loading</p>;
  } else {
    const rejectedByEngine = computed?.computed === 'rejected';
    body = (
      <>
        {record ? <DecisionRecordView record={record} text="Acceptance confirmed" /> : null}
        {rejectedByEngine ? (
          <div className="banner danger">
            <p>The engine rejected this run</p>
            <ul>{computed!.reasons.map((r, i) => <li key={i}>{r.text}</li>)}</ul>
          </div>
        ) : null}
        {!report.data.sha256 ? <p className="banner warn">The server did not send the report hash. Acceptance cannot be confirmed from the dashboard.</p> : null}
        {!done && report.data.sha256 ? (
          <DecisionPanel
            key={report.data.sha256}
            kind="acceptance"
            sha256={report.data.sha256}
            subject={run.slug}
            allow={record ? ['reject'] : rejectedByEngine ? ['reject'] : ['accept', 'reject']}
            disabled={!enabled}
            pending={action.pending}
            onDecide={decide}
          />
        ) : null}
      </>
    );
  }

  return (
    <>
      {compact && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <span style={{ fontSize: 12, color: 'var(--floor-text-muted)' }}>Reading in the side panel</span>
          <button
            type="button"
            ref={expandBtnRef}
            className="floor-btn-expand"
            onClick={() => setFullScreen(true)}
            aria-label="Expand the review to full screen"
          >
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" style={{ verticalAlign: -2 }}>
              <path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" />
            </svg>
            Expand
          </button>
        </div>
      )}
      <h2>Acceptance</h2>
      {action.message?.kind === 'error' ? <ActionResult message={action.message} /> : null}
      <section data-testid="acceptance-panel" className="panel">
        {body}
      </section>
      {report.data ? (
        <section data-testid="report-summary">
          <h3>Report</h3>
          <p>
            sha256 <code className="mono">{report.data.sha256 ?? 'not reported'}</code>
          </p>
          <pre className="pre-wrap">{JSON.stringify(report.data.report, null, 2)}</pre>
        </section>
      ) : null}

      {fullScreen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Acceptance review, full screen"
          tabIndex={-1}
          ref={dialogRef}
          className="floor-fullscreen-dialog"
        >
          <div className="floor-fullscreen-header">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: '1 1 360px', minWidth: 0 }}>
              <h2 style={{ margin: 0, fontFamily: "'Space Grotesk', system-ui, sans-serif", fontSize: 20 }}>
                Acceptance review · {run.slug}
              </h2>
              <span style={{ fontSize: 12, color: 'var(--floor-text-muted)' }}>
                sha256: <code className="mono" style={{ wordBreak: 'break-all' }}>{report.data?.sha256 ?? 'pending'}</code>
              </span>
            </div>
            <span style={{ fontSize: 12, color: 'var(--floor-text-muted)' }}>
              Still on the factory floor. The run keeps its place.
            </span>
            <button type="button" className="floor-btn-exit" onClick={closeFullScreen}>
              <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" style={{ verticalAlign: -2, marginRight: 6 }}>
                <path d="M6 2v4H2M14 6h-4V2M10 14v-4h4M2 10h4v4" />
              </svg>
              Exit full screen
            </button>
          </div>

          <div className="floor-fullscreen-body">
            <nav aria-label="Sections" className="floor-fullscreen-nav">
              <h3 style={{ margin: '0 0 10px', fontSize: 11, letterSpacing: '.4px', textTransform: 'uppercase', color: 'var(--floor-text-muted)' }}>
                Sections
              </h3>
              <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
                <li><a href="#sec-acceptance" style={{ color: 'var(--floor-text-muted)', fontSize: 13, textDecoration: 'none' }}>Acceptance</a></li>
                {report.data ? <li><a href="#sec-report" style={{ color: 'var(--floor-text-muted)', fontSize: 13, textDecoration: 'none' }}>Report details</a></li> : null}
              </ol>
            </nav>

            <article className="floor-fullscreen-center">
              <div style={{ maxWidth: 760, margin: '0 auto', fontSize: 15, lineHeight: 1.7, color: '#D5DBE1' }}>
                <section id="sec-acceptance" style={{ marginBottom: 28 }}>
                  <h2 style={{ margin: '0 0 8px', fontSize: 18, color: 'var(--floor-text)' }}>Verification status</h2>
                  {body}
                </section>
                {report.data ? (
                  <section id="sec-report" style={{ marginBottom: 28 }}>
                    <h2 style={{ margin: '0 0 8px', fontSize: 18, color: 'var(--floor-text)' }}>Report</h2>
                    <pre className="pre-wrap" style={{ fontSize: 13, lineHeight: 1.6, color: '#C9D1D9', background: 'var(--floor-surface)', padding: 12, borderRadius: 10 }}>
                      {JSON.stringify(report.data.report, null, 2)}
                    </pre>
                  </section>
                ) : null}
              </div>
            </article>

            <aside className="floor-fullscreen-aside">
              <div style={{ position: 'sticky', top: 20 }}>
                {body}
              </div>
            </aside>
          </div>
        </div>
      )}
    </>
  );
}

