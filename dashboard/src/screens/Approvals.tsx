import { useEffect, useState } from 'react';
import { calls } from '../api/calls.ts';
import type { ApiError } from '../api/errors.ts';
import type { DecisionRecord, GherkinAnswer, KnowledgeUsed, SpecificationAnswer, VersionRow } from '../api/types.ts';
import { ActionResult, CopyButton, Loaded, StatusChip, useAction, useControlsEnabled } from '../components/common.tsx';
import { AriaTabs } from '../components/AriaTabs.tsx';
import { DecisionPanel, type Decision } from '../components/DecisionPanel.tsx';
import { UnifiedText } from '../components/DiffView.tsx';
import { formatDate, formatTime, prefix } from '../format.ts';
import { Link, enc } from '../router.tsx';
import { useApp, useResource } from '../state/app.tsx';

export function ApprovalsScreen() {
  const res = useResource('approvals', (c) => calls.approvals(c), {});
  return (
    <section>
      <h1>My Approvals</h1>
      <Loaded res={res}>
        {(page) =>
          page.items.length === 0 ? (
            <p>Nothing waits for your approval</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {['Project', 'Run', 'Gate', 'Version', 'sha256', 'Review requested', 'Open'].map((h) => (
                      <th scope="col" key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((a) => (
                    <tr key={`${a.project}/${a.slug}/${a.gate}`} data-testid="approval-row">
                      <td>{a.project}</td>
                      <td>{a.slug}</td>
                      <td>{a.gate}</td>
                      <td>{a.version}</td>
                      <td><code>{prefix(a.sha256)}</code></td>
                      <td>{formatTime(a.requested_at)}</td>
                      <td>
                        <Link to={`/projects/${enc(a.project)}/runs/${enc(a.slug)}/${a.gate}`}>
                          Review {a.slug} {a.gate}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </Loaded>
    </section>
  );
}

const STATE_LABEL: Record<string, string> = {
  IN_REVIEW: 'In review',
  APPROVED: 'Approved',
  CHANGES_REQUESTED: 'Changes requested',
  REJECTED: 'Rejected',
  INVALIDATED: 'Replaced by a newer version',
  NOT_REQUESTED: 'Not requested',
  EARLIER: 'Earlier version',
};
const DECISION_LABEL: Record<string, string> = { approve: 'Approved', changes: 'Changes requested', reject: 'Rejected', accept: 'Acceptance confirmed' };

export function DecisionRecordView({ record, text }: { record: DecisionRecord; text?: string }) {
  return (
    <div className="banner ok" data-testid="decision-record">
      <strong>{text ?? DECISION_LABEL[record.decision] ?? record.decision}</strong>
      <div>
        by {record.approver || 'not reported'} via {record.channel || 'not reported'}{record.at ? ` at ${formatTime(record.at)}` : ''}
      </div>
      {record.comment ? <div className="pre-wrap">Comment: {record.comment}</div> : null}
    </div>
  );
}

type ReviewData = (SpecificationAnswer | GherkinAnswer) & { requested_at: string | null };

interface ReviewProps {
  gate: 'specification' | 'gherkin';
  pid: string;
  slug: string;
  /** an earlier version, shown read only */
  version?: string;
  onRunChanged: () => void;
}

function ValidationView({ validation }: { validation: ReviewData['validation'] }) {
  return (
    <div data-testid="validation">
      <h3>Validation</h3>
      <p>
        {validation.findings.length === 0 ? 'No findings' : `${validation.findings.length} finding${validation.findings.length === 1 ? '' : 's'}`}
      </p>
      <ul>
        {validation.findings.map((f, i) => (
          <li key={i}>
            {f.severity}: {f.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

function VersionsList({ versions, current, gate, pid, slug }: { versions: VersionRow[]; current: number; gate: string; pid: string; slug: string }) {
  const earlier = versions.filter((v) => v.version < current);
  if (!earlier.length) return <p>No earlier versions</p>;
  return (
    <ul className="plain">
      {earlier.map((v) => (
        <li key={v.version} className="panel" data-testid={`version-row-${v.version}`}>
          <Link to={`/projects/${enc(pid)}/runs/${enc(slug)}/${gate}/versions/${v.version}`}>Version {v.version}</Link> <code>{prefix(v.sha256)}</code>{' '}
          {v.provenance ? <span className="provenance hint">({v.provenance}) </span> : null}
          {v.decision ?? 'no decision'} {v.reviewer ? `by ${v.reviewer}` : ''} {v.channel ? `via ${v.channel}` : ''} {v.at ? `at ${formatTime(v.at)}` : ''}
          {v.comment ? <div className="pre-wrap">Comment: {v.comment}</div> : null}
        </li>
      ))}
    </ul>
  );
}

function GherkinBody({ data }: { data: GherkinAnswer }) {
  const [filter, setFilter] = useState('');
  const q = filter.trim().toLowerCase();
  const features = data.features
    .map((f) => ({
      ...f,
      scenarios: f.scenarios.filter((s) => !q || [s.ac, s.name, s.type, s.priority, ...s.tags, ...s.cov].join(' ').toLowerCase().includes(q)),
    }))
    .filter((f) => f.scenarios.length);
  return (
    <>
      <h3>Coverage</h3>
      <table data-testid="coverage-table">
        <thead>
          <tr>
            <th scope="col">Category</th>
            <th scope="col">Coverage</th>
          </tr>
        </thead>
        <tbody>
          {data.coverage.map((c) => (
            <tr key={c.category}>
              <th scope="row">{c.category}</th>
              <td>
                {c.status === 'covered' ? <StatusChip kind="ok" label={`covered by ${c.scenarios} scenarios`} /> : null}
                {c.status === 'not_applicable' ? <StatusChip kind="none" label={`not applicable: ${c.reason ?? ''}`} /> : null}
                {c.status === 'missing' ? <StatusChip kind="fail" label="Missing" /> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Scenarios</h3>
      <div className="field">
        <label htmlFor="scenario-filter">Filter scenarios</label>
        <input id="scenario-filter" type="search" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      {/* a scrollable region must be reachable by keyboard */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <div className="scroll-list" tabIndex={0} role="region" aria-label="Scenarios">
        {features.map((f) => (
          <section key={f.path} data-testid={`feature-${f.path}`}>
            <h4>
              {f.name} <code>{f.path}</code>
            </h4>
            <ul className="plain">
              {f.scenarios.map((s, i) => (
                <li key={`${s.ac}-${i}`} data-testid={`scenario-${s.ac}`}>
                  <strong>{s.name}</strong> <code>{s.ac}</code> {s.type} {s.priority} {s.cov.join(' ')}
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </>
  );
}

export function KnowledgeUsedView({ knowledge }: { knowledge?: KnowledgeUsed | null }) {
  const records = knowledge?.records ?? [];
  const summaries = knowledge?.summaries ?? [];
  const invariants = knowledge?.invariants ?? [];
  const hasItems = records.length > 0 || summaries.length > 0 || invariants.length > 0;

  if (!hasItems) {
    return (
      <div data-testid="knowledge-used" className="panel" style={{ padding: '1rem' }}>
        <p className="hint" style={{ margin: 0 }}>No knowledge base records or summaries were read for this document.</p>
      </div>
    );
  }

  return (
    <div data-testid="knowledge-used" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {records.length > 0 ? (
        <section>
          <h3 style={{ margin: '0 0 0.5rem', fontSize: '1rem' }}>Change records</h3>
          <ul className="plain" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {records.map((r) => (
              <li key={r.key} className="panel" style={{ padding: '0.75rem 1rem' }} data-testid={`knowledge-record-${r.key}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '0.5rem', marginBottom: '0.25rem' }}>
                  <strong>
                    {r.key} {r.title ? `· ${r.title}` : ''}
                  </strong>
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    {r.repo ? `${r.repo} ` : ''}{r.date ? `(${formatDate(r.date)})` : ''}
                  </span>
                </div>
                {r.summary ? <p style={{ margin: '0.25rem 0 0', fontSize: '0.9rem', color: 'var(--text-muted)' }}>{r.summary}</p> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {invariants.length > 0 ? (
        <section>
          <h3 style={{ margin: '0 0 0.5rem', fontSize: '1rem' }}>Invariants</h3>
          <ul className="plain" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {invariants.map((inv, idx) => (
              <li key={inv.id || idx} className="panel" style={{ padding: '0.75rem 1rem' }} data-testid={`knowledge-invariant-${inv.id || idx}`}>
                <strong>{inv.id ? `${inv.id}: ` : 'Invariant: '}</strong>
                <span>{inv.rule || inv.text}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {summaries.length > 0 ? (
        <section>
          <h3 style={{ margin: '0 0 0.5rem', fontSize: '1rem' }}>Module & repository summaries</h3>
          <ul className="plain" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {summaries.map((s, idx) => (
              <li key={s.path || idx} className="panel" style={{ padding: '0.75rem 1rem' }} data-testid={`knowledge-summary-${idx}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '0.5rem', marginBottom: '0.25rem' }}>
                  <strong>{s.module ? `${s.repo} / ${s.module}` : s.repo}</strong>
                  <code>{s.path}</code>
                </div>
                {s.text ? <pre className="pre-wrap" style={{ margin: '0.25rem 0 0', fontSize: '0.85rem' }}>{s.text}</pre> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function SpecBody({ data, tab, setTab, pid, slug }: { data: SpecificationAnswer; tab: string; setTab: (t: string) => void; pid: string; slug: string }) {
  const tabs = [
    { id: 'spec', label: 'Specification' },
    { id: 'diff', label: `Changes since version ${data.previous_version ?? 'none'}` },
    { id: 'knowledge', label: 'Knowledge used' },
    { id: 'versions', label: 'Versions' },
  ];
  return (
    <AriaTabs label="Specification views" idPrefix="spec" tabs={tabs} current={tab} onChange={setTab}>
      {tab === 'spec' ? (
        <pre data-testid="spec-text" className="pre-wrap">
          {data.text}
        </pre>
      ) : null}
      {tab === 'diff' ? (data.diff_to_previous ? <UnifiedText text={data.diff_to_previous} /> : <p>No earlier version to compare with</p>) : null}
      {tab === 'knowledge' ? <KnowledgeUsedView knowledge={data.knowledge_used} /> : null}
      {tab === 'versions' ? <VersionsList versions={data.versions} current={data.version} gate="specification" pid={pid} slug={slug} /> : null}
    </AriaTabs>
  );
}

export function ReviewPage({ gate, pid, slug, version, onRunChanged }: ReviewProps) {
  const app = useApp();
  const enabled = useControlsEnabled();
  const res = useResource<ReviewData>(
    `review-${gate}-${pid}-${slug}-${version ?? 'current'}`,
    (c) => {
      if (gate === 'gherkin') return calls.gherkin(c, slug, pid) as Promise<ReviewData>;
      return (version ? calls.specificationVersion(c, slug, pid, version) : calls.specification(c, slug, pid)) as Promise<ReviewData>;
    },
    { project: pid, run: slug },
  );
  const action = useAction();
  const [shown, setShown] = useState<ReviewData | null>(null);
  const [record, setRecord] = useState<{ record: DecisionRecord; text: string } | null>(null);
  const [staleError, setStaleError] = useState(false);
  const [minVersion, setMinVersion] = useState<number | null>(null);
  const [tab, setTab] = useState('spec');

  useEffect(() => {
    if (!res.data) return;
    if (!shown) setShown(res.data);
    else if (minVersion !== null && res.version >= minVersion) {
      setShown(res.data);
      setMinVersion(null);
      setStaleError(false);
      setRecord(null);
      action.clear();
    }
  }, [res.data, res.version]);

  const latest = res.data;
  const stale = !!(shown && latest && latest.sha256 !== shown.sha256);

  return (
    <Loaded res={res}>
      {() => {
        if (!shown) return null;
        // same version: follow the latest answer so a decision made elsewhere shows up
        const view = latest && latest.sha256 === shown.sha256 ? latest : shown;
        const readOnly = !!version;
        const inReview = view.state === 'IN_REVIEW' && !readOnly;
        const decided = record?.record ?? (view.state !== 'IN_REVIEW' ? view.decision : null);
        const label = gate === 'specification' ? 'Specification' : 'Gherkin';

        const decide = async (d: { decision: Decision; confirmation: string; comment: string | null }) => {
          const loadedSha = shown.sha256;
          await action.run(
            () => calls.decide(app.client, slug, pid, { gate, sha256: loadedSha, confirmation: d.confirmation, decision: d.decision, comment: d.comment }),
            (r) => {
              setRecord({ record: r.approval, text: DECISION_LABEL[d.decision] });
              return d.decision === 'approve' ? `${label} approved` : d.decision === 'changes' ? 'Changes requested' : 'Run rejected';
            },
            {
              onError: (e: ApiError) => {
                if (e.code === 'E_APPROVAL_STALE') {
                  setStaleError(true);
                  return 'A newer version is in review. Nothing was approved.';
                }
                return undefined;
              },
              onSettled: () => {
                onRunChanged();
                void res.reload();
              },
            },
          );
        };

        const blockedByStale = stale || staleError;
        const staleText = staleError ? 'A newer version is in review. Nothing was approved.' : `Version ${latest?.version} replaced the version you are reading`;

        return (
          <>
            <h2>{label} review</h2>
            <p>
              <strong data-testid="review-version">Version {view.version}</strong> <span data-testid="approval-state">{STATE_LABEL[view.state] ?? view.state}</span>
              {'provenance' in view && view.provenance ? <span className="provenance hint" data-testid="review-provenance" style={{ marginLeft: '0.5rem' }}>({view.provenance})</span> : null}
              {view.requested_at ? <span className="hint"> review requested {formatTime(view.requested_at)}</span> : null}
            </p>
            <div>
              <code className="sha mono" data-testid="sha-full">
                {view.sha256}
              </code>
              <CopyButton text={view.sha256} label="Copy sha256" />
            </div>
            {readOnly ? <p className="banner">Version {view.version} is not in review</p> : null}
            {blockedByStale ? (
              <div className="banner warn" data-testid="stale-banner">
                <p>{staleText}</p>
                <button
                  type="button"
                  onClick={() => {
                    setMinVersion(res.version + 1);
                    void res.reload();
                  }}
                >
                  Load the version in review
                </button>
              </div>
            ) : null}
            {action.message && !(staleError && action.message.kind === 'error') ? <ActionResult message={action.message} /> : null}
            {decided ? <DecisionRecordView record={decided} text={record?.text} /> : null}
            {inReview && !record ? (
              <DecisionPanel
                key={`${shown.sha256}-${blockedByStale}`}
                kind="approval"
                version={view.version}
                sha256={view.sha256}
                subject={slug}
                disabled={blockedByStale || !enabled}
                pending={action.pending}
                onDecide={decide}
              />
            ) : null}
            <ValidationView validation={view.validation} />
            {gate === 'gherkin' ? <GherkinBody data={view as GherkinAnswer} /> : <SpecBody data={view as SpecificationAnswer} tab={tab} setTab={setTab} pid={pid} slug={slug} />}
            {gate === 'gherkin' ? (
              <>
                <h3>Versions</h3>
                <VersionsList versions={view.versions} current={view.version} gate="gherkin" pid={pid} slug={slug} />
              </>
            ) : null}
          </>
        );
      }}
    </Loaded>
  );
}

