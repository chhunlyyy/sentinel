import type { ReactNode } from 'react';
import { useState } from 'react';
import { calls } from '../../api/calls.ts';
import type { ApiError } from '../../api/errors.ts';
import type { Run } from '../../api/types.ts';
import { ActionResult, useAction, useControlsEnabled } from '../../components/common.tsx';
import { DecisionPanel, type Decision } from '../../components/DecisionPanel.tsx';
import { ErrorView } from '../../components/ErrorView.tsx';
import { useApp, useResource } from '../../state/app.tsx';
import { DecisionRecordView } from '../Approvals.tsx';

export function AcceptanceTab({ run, pid, onChanged }: { run: Run; pid: string; onChanged: () => void }) {
  const app = useApp();
  const enabled = useControlsEnabled();
  const verification = useResource(`acc-verification-${pid}-${run.slug}`, (c) => calls.verification(c, run.slug, pid), { project: pid, run: run.slug });
  const report = useResource(`acc-report-${pid}-${run.slug}`, (c) => calls.report(c, run.slug, pid), { project: pid, run: run.slug });
  const action = useAction();
  const [done, setDone] = useState<{ record: Run['acceptance_record'] & object; text: string } | null>(null);
  const record = done?.record ?? run.acceptance_record ?? null;

  const decide = async (d: { decision: Decision; confirmation: string; comment: string | null }) => {
    const sha = report.data?.sha256;
    if (!sha) return;
    await action.run(
      () => calls.accept(app.client, run.slug, pid, { sha256_of_report: sha, confirmation: d.confirmation, decision: d.decision === 'accept' ? 'accept' : 'reject', comment: d.comment }),
      (r) => {
        setDone({ record: r.acceptance, text: d.decision === 'accept' ? 'Acceptance confirmed' : 'Rejected' });
        return '';
      },
      {
        onError: (e: ApiError) => (e.code === 'E_APPROVAL_STALE' ? 'The report changed. Nothing was confirmed. Reload the report.' : undefined),
        onSettled: () => {
          onChanged();
          void report.reload();
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
  } else if (!report.data) {
    body = report.error ? <ErrorView error={report.error} /> : <p className="hint" role="status">Loading</p>;
  } else {
    const rejectedByEngine = computed?.computed === 'rejected';
    body = (
      <>
        {record ? <DecisionRecordView record={record} text={done?.text ?? 'Acceptance confirmed'} /> : null}
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
    </>
  );
}

