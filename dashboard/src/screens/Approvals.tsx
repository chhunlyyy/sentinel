import { useEffect, useState, useRef, Fragment } from 'react';
import { calls } from '../api/calls.ts';
import type { ApiError } from '../api/errors.ts';
import type { DecisionRecord, GherkinAnswer, GherkinScenario, KnowledgeUsed, SpecificationAnswer, VersionRow } from '../api/types.ts';
import { ActionResult, CopyButton, Loaded, StatusChip, useAction, useControlsEnabled } from '../components/common.tsx';
import { AriaTabs } from '../components/AriaTabs.tsx';
import { DecisionPanel, type Decision } from '../components/DecisionPanel.tsx';
import { UnifiedText } from '../components/DiffView.tsx';
import { formatDate, formatTime, prefix } from '../format.ts';
import { Link, enc, navigate } from '../router.tsx';
import { useApp, useResource } from '../state/app.tsx';

export function ApprovalsScreen() {
  const app = useApp();
  const res = useResource('approvals', (c) => calls.approvals(c), {});
  const action = useAction();
  const [approvingSha, setApprovingSha] = useState<string | null>(null);

  const handleRowApprove = async (a: { project: string; slug: string; gate: string; sha256: string }) => {
    setApprovingSha(a.sha256);
    try {
      await calls.decide(app.client, a.slug, a.project, {
        gate: a.gate as 'specification' | 'gherkin',
        sha256: a.sha256,
        decision: 'approve',
        comment: null,
      });
      void res.reload();
    } finally {
      setApprovingSha(null);
    }
  };

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
                    {['Project', 'Run', 'Gate', 'Version', 'sha256', 'Review requested', 'Open', 'Action'].map((h) => (
                      <th scope="col" key={h}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((a) => (
                    <tr
                      key={`${a.project}/${a.slug}/${a.gate}`}
                      data-testid="approval-row"
                      style={{ cursor: 'pointer' }}
                      onClick={() => navigate(`/projects/${enc(a.project)}/runs/${enc(a.slug)}/${a.gate}`)}
                    >
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
                      <td onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          disabled={action.pending || approvingSha === a.sha256}
                          onClick={() => void handleRowApprove(a)}
                          style={{
                            fontSize: 13,
                            fontWeight: 600,
                            padding: '6px 12px',
                            background: '#0F766E',
                            color: '#FFFFFF',
                            border: 'none',
                            borderRadius: 6,
                            cursor: 'pointer',
                          }}
                        >
                          {approvingSha === a.sha256 ? 'Approving…' : 'Approve'}
                        </button>
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
  compact?: boolean;
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

interface ParsedGherkinStep {
  keyword: string;
  text: string;
}

function parseScenarioSteps(rawText: string | undefined, scenarioName: string): ParsedGherkinStep[] {
  if (!rawText) return [];
  const lines = rawText.split('\n');
  let inTargetScenario = false;
  const steps: ParsedGherkinStep[] = [];

  for (const line of lines) {
    const trimmed = line.trim();
    if (/^(Scenario|Scenario Outline):/i.test(trimmed)) {
      const name = trimmed.replace(/^(Scenario|Scenario Outline):\s*/i, '').trim();
      inTargetScenario = name === scenarioName || trimmed.includes(scenarioName);
      continue;
    }
    if (inTargetScenario) {
      if (/^(Rule:|Feature:|Scenario|Scenario Outline:|@)/i.test(trimmed)) {
        break;
      }
      const stepMatch = trimmed.match(/^(Given|When|Then|And|But)\s+(.+)$/i);
      if (stepMatch) {
        steps.push({
          keyword: stepMatch[1],
          text: stepMatch[2],
        });
      }
    }
  }
  return steps;
}

function ScenarioCard({ scenario, featureText, version }: { scenario: GherkinScenario; featureText?: string; version: number }) {
  const steps = parseScenarioSteps(featureText, scenario.name);
  const isNew = version > 1 && scenario.tags.some((t) => t.includes('new') || t.includes('v' + version));

  return (
    <div
      data-testid={`scenario-${scenario.ac}`}
      style={{
        border: isNew ? '2px solid #E8C98F' : '1px solid #E4E3DE',
        borderRadius: 12,
        padding: '16px 18px',
        background: isNew ? '#FFFCF6' : '#FFFFFF',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {isNew && (
          <span style={{ fontSize: 12, fontWeight: 700, color: '#7A3D05', background: '#FDF0D9', padding: '3px 8px', borderRadius: 6 }}>
            NEW IN VERSION {version}
          </span>
        )}
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>{scenario.name}</h3>
        {scenario.ac && (
          <code style={{ fontSize: 12, color: '#6B6B65', background: '#F1F0EC', padding: '2px 6px', borderRadius: 4, marginLeft: 'auto' }}>
            {scenario.ac}
          </code>
        )}
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        {scenario.type ? (
          <span style={{ fontSize: 12, color: '#5A5A55', background: '#F6F6F3', padding: '2px 8px', borderRadius: 999 }}>
            {scenario.type}
          </span>
        ) : null}
        {scenario.priority ? (
          <span style={{ fontSize: 12, color: '#5A5A55', background: '#F6F6F3', padding: '2px 8px', borderRadius: 999 }}>
            {scenario.priority}
          </span>
        ) : null}
        {(scenario.tags || []).map((t) => (
          <span key={t} style={{ fontSize: 12, color: '#5A5A55', background: '#F6F6F3', padding: '2px 8px', borderRadius: 999 }}>
            {t}
          </span>
        ))}
      </div>

      <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: '64px minmax(0, 1fr)', rowGap: 6, fontSize: 15, lineHeight: 1.5 }}>
        {steps.length > 0 ? (
          steps.map((st, i) => (
            <Fragment key={i}>
              <dt style={{ fontWeight: 600, color: '#6B6B65' }}>{st.keyword}</dt>
              <dd style={{ margin: 0, color: '#1B1B19' }}>{st.text}</dd>
            </Fragment>
          ))
        ) : (
          <>
            <dt style={{ fontWeight: 600, color: '#6B6B65' }}>Given</dt>
            <dd style={{ margin: 0, color: '#1B1B19' }}>valid preconditions and test state</dd>
            <dt style={{ fontWeight: 600, color: '#6B6B65' }}>When</dt>
            <dd style={{ margin: 0, color: '#1B1B19' }}>{scenario.name}</dd>
            <dt style={{ fontWeight: 600, color: '#6B6B65' }}>Then</dt>
            <dd style={{ margin: 0, color: '#1B1B19' }}>
              system satisfies {scenario.ac || 'acceptance requirements'} ({scenario.type} {scenario.priority})
            </dd>
          </>
        )}
      </dl>
    </div>
  );
}

function GherkinBody({ data, version }: { data: GherkinAnswer; version: number }) {
  const [filter, setFilter] = useState('');
  const q = filter.trim().toLowerCase();
  const features = data.features
    .map((f) => ({
      ...f,
      scenarios: f.scenarios.filter((s) => !q || [s.ac, s.name, s.type, s.priority, ...s.tags, ...s.cov].join(' ').toLowerCase().includes(q)),
    }))
    .filter((f) => f.scenarios.length);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Coverage Table */}
      <div style={{ background: '#FFFFFF', border: '1px solid #E4E3DE', borderRadius: 14, padding: 20 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 17 }}>Coverage</h3>
        <table data-testid="coverage-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '1px solid #EEEDE8', color: '#6B6B65' }}>
              <th scope="col" style={{ padding: '8px 10px' }}>Category</th>
              <th scope="col" style={{ padding: '8px 10px' }}>Coverage</th>
            </tr>
          </thead>
          <tbody>
            {data.coverage.map((c) => (
              <tr key={c.category} style={{ borderBottom: '1px solid #F6F6F3' }}>
                <th scope="row" style={{ padding: '8px 10px', fontWeight: 500 }}>{c.category}</th>
                <td style={{ padding: '8px 10px' }}>
                  {c.status === 'covered' ? <StatusChip kind="ok" label={`covered by ${c.scenarios} scenarios`} /> : null}
                  {c.status === 'not_applicable' ? <StatusChip kind="none" label={`not applicable: ${c.reason ?? ''}`} /> : null}
                  {c.status === 'missing' ? <StatusChip kind="fail" label="Missing" /> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Scenarios filter */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <label htmlFor="scenario-filter" style={{ fontSize: 14, fontWeight: 600 }}>
          Filter scenarios
        </label>
        <input
          id="scenario-filter"
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by name, tag, or criterion..."
          style={{
            flex: '1 1 300px',
            fontSize: 14,
            padding: '8px 12px',
            border: '1px solid #C9C8C1',
            borderRadius: 8,
          }}
        />
      </div>

      {/* Feature & Scenarios List */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
      <div className="scroll-list" tabIndex={0} role="region" aria-label="Scenarios" style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
        {features.map((f) => (
          <section
            key={f.path}
            id={f.path.replace(/[^a-zA-Z0-9_-]/g, '-')}
            data-testid={`feature-${f.path}`}
            style={{
              background: '#FFFFFF',
              border: '1px solid #E4E3DE',
              borderRadius: 14,
              padding: 24,
              display: 'flex',
              flexDirection: 'column',
              gap: 16,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
              <h2 style={{ margin: 0, fontSize: 19, fontWeight: 700 }}>{f.name}</h2>
              <code style={{ fontSize: 13, color: '#6B6B65' }}>{f.path}</code>
              <span style={{ fontSize: 13, color: '#6B6B65', marginLeft: 'auto' }}>
                {f.scenarios.length} scenario{f.scenarios.length === 1 ? '' : 's'}
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {f.scenarios.map((s) => (
                <ScenarioCard key={s.ac || s.name} scenario={s} featureText={f.text} version={version} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
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

function renderMarkdownContent(content: string) {
  const paragraphs = content.split(/\n\s*\n/);
  return paragraphs.map((para, i) => {
    const trimmed = para.trim();
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      const items = trimmed.split('\n').filter(Boolean).map((line) => line.replace(/^[-*]\s+/, ''));
      return (
        <ul key={i} style={{ margin: '0 0 12px', paddingLeft: 20 }}>
          {items.map((item, idx) => (
            <li key={idx}>{item}</li>
          ))}
        </ul>
      );
    }
    return (
      <p key={i} style={{ margin: '0 0 12px', lineHeight: 1.6 }}>
        {trimmed}
      </p>
    );
  });
}

function SpecBody({ data, tab, setTab, pid, slug }: { data: SpecificationAnswer; tab: string; setTab: (t: string) => void; pid: string; slug: string }) {
  const tabs = [
    { id: 'spec', label: 'Specification' },
    { id: 'diff', label: `Changes since version ${data.previous_version ?? 'none'}` },
    { id: 'knowledge', label: 'Knowledge used' },
    { id: 'versions', label: 'Versions' },
  ];
  const specDoc = parseSpecDoc(data.text);

  return (
    <AriaTabs label="Specification views" idPrefix="spec" tabs={tabs} current={tab} onChange={setTab}>
      {tab === 'spec' ? (
        <div data-testid="spec-text" className="spec-sections-view" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <span style={{ position: 'absolute', left: -9999 }} role="heading" aria-level={2}>
            Specification review
          </span>
          {specDoc.title && (
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}># {specDoc.title}</h1>
          )}
          {specDoc.sections.map((sec) => (
            <section
              key={sec.id}
              id={sec.id}
              style={{
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 14,
                padding: 24,
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
              }}
            >
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>{sec.title}</h2>
              <div style={{ fontSize: 15, color: 'var(--text)' }}>
                {renderMarkdownContent(sec.content)}
              </div>
            </section>
          ))}
        </div>
      ) : null}
      {tab === 'diff' ? (data.diff_to_previous ? <UnifiedText text={data.diff_to_previous} /> : <p>No earlier version to compare with</p>) : null}
      {tab === 'knowledge' ? <KnowledgeUsedView knowledge={data.knowledge_used} /> : null}
      {tab === 'versions' ? <VersionsList versions={data.versions} current={data.version} gate="specification" pid={pid} slug={slug} /> : null}
    </AriaTabs>
  );
}

export function parseSpecDoc(text: string): { title: string; sections: { id: string; title: string; content: string }[] } {
  if (!text) return { title: '', sections: [] };
  const lines = text.split('\n');
  let title = '';
  const sections: { id: string; title: string; content: string }[] = [];
  let currentTitle: string | null = null;
  let currentLines: string[] = [];
  let count = 0;

  for (const line of lines) {
    const h1Match = line.match(/^#\s+(.+)$/);
    if (h1Match && !title) {
      title = h1Match[1].trim();
      continue;
    }
    const h2Match = line.match(/^##\s+(.+)$/);
    if (h2Match) {
      if (currentTitle !== null || currentLines.join('\n').trim().length > 0) {
        sections.push({
          id: `sec-${count++}`,
          title: currentTitle ?? 'Overview',
          content: currentLines.join('\n').trim(),
        });
        currentLines = [];
      }
      currentTitle = h2Match[1].trim();
    } else {
      currentLines.push(line);
    }
  }
  if (currentTitle !== null || currentLines.join('\n').trim().length > 0) {
    sections.push({
      id: `sec-${count++}`,
      title: currentTitle ?? 'Overview',
      content: currentLines.join('\n').trim(),
    });
  }
  return { title, sections };
}

export function parseSpecSections(text: string): { id: string; title: string; content: string }[] {
  return parseSpecDoc(text).sections;
}

export function ReviewPage({ gate, pid, slug, version, onRunChanged, compact }: ReviewProps) {
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

  useEffect(() => {
    if (!fullScreen) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Escape' || (e.target instanceof Element && e.target.closest('dialog'))) return;
      closeFullScreen();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  });

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
        const view = latest && latest.sha256 === shown.sha256 ? latest : shown;
        const readOnly = !!version;
        const inReview = view.state === 'IN_REVIEW' && !readOnly;
        const decided = record?.record ?? (view.state !== 'IN_REVIEW' ? view.decision : null);
        const label = gate === 'specification' ? 'Specification' : 'Scenarios';
        const agentRole = gate === 'gherkin' ? 'scenario writer' : 'spec writer';

        const decide = async (d: { decision: Decision; comment: string | null; confirmation?: string }) => {
          const loadedSha = shown.sha256;
          const body: Record<string, unknown> = {
            gate,
            sha256: loadedSha,
            decision: d.decision,
            comment: d.comment,
          };
          if (d.confirmation !== undefined) body.confirmation = d.confirmation;
          await action.run(
            () => calls.decide(app.client, slug, pid, body as { gate: 'specification' | 'gherkin' }),
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

        // Calculate navigation rules / sections
        const rulesList = gate === 'gherkin'
          ? (view as GherkinAnswer).features.map((f, i) => ({
              id: f.path.replace(/[^a-zA-Z0-9_-]/g, '-'),
              title: f.name,
              count: f.scenarios.length,
              isNew: i === 0 && view.version > 1,
            }))
          : parseSpecDoc((view as SpecificationAnswer).text).sections.map((sec) => ({
              id: sec.id,
              title: sec.title,
              count: 1,
              isNew: false,
            }));

        const totalItemsCount = gate === 'gherkin'
          ? (view as GherkinAnswer).features.reduce((acc, f) => acc + f.scenarios.length, 0)
          : parseSpecDoc((view as SpecificationAnswer).text).sections.length;

        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Header with back link */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
              <Link
                to={pid ? `/projects/${enc(pid)}/floor` : '/floor'}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 15, textDecoration: 'none', color: 'var(--link)' }}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M15 18l-6-6 6-6"></path>
                </svg>
                Back to the floor
              </Link>
              <div style={{ fontSize: 14, color: 'var(--text-muted)' }}>Task · {slug}</div>
              {compact && (
                <button
                  type="button"
                  ref={expandBtnRef}
                  className="floor-btn-expand"
                  onClick={() => setFullScreen(true)}
                  aria-label="Expand the review to full screen"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    fontSize: 13,
                    padding: '6px 10px',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    background: 'var(--surface)',
                    color: 'var(--text)',
                    cursor: 'pointer',
                  }}
                >
                  Expand
                </button>
              )}
            </div>

            {/* Sticky Action Bar */}
            <div
              style={{
                position: 'sticky',
                top: 0,
                zIndex: 10,
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 14,
                boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
                padding: '14px 20px',
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
                color: 'var(--text)',
              }}
            >
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16 }}>
                <div style={{ flex: '1 1 360px', minWidth: 0 }}>
                  {gate === 'gherkin' && (
                    <span style={{ position: 'absolute', left: -9999 }} role="heading" aria-level={2}>
                      Gherkin review
                    </span>
                  )}
                  <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>
                    {label} · <strong data-testid="review-version">Version {view.version}</strong>
                  </h1>
                  <div style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 2 }}>
                    <span data-testid="approval-state">{STATE_LABEL[view.state] ?? view.state}</span>
                    {'provenance' in view && view.provenance ? <span className="provenance hint" data-testid="review-provenance" style={{ marginLeft: '0.5rem' }}>({view.provenance})</span> : null}
                    {' · '}{totalItemsCount} {gate === 'gherkin' ? 'scenarios' : 'sections'} · written by the {agentRole}
                    {view.requested_at ? <span className="hint"> · requested {formatTime(view.requested_at)}</span> : null}
                  </div>
                  <div style={{ marginTop: 4 }}>
                    <code className="sha mono" data-testid="sha-full" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      {view.sha256}
                    </code>
                    <CopyButton text={view.sha256} label="Copy sha256" />
                  </div>
                </div>

                {decided ? (
                  <DecisionRecordView record={decided} text={record?.text} />
                ) : inReview && !record ? (
                  <DecisionPanel
                    key={`${shown.sha256}-${blockedByStale}`}
                    kind="approval"
                    gate={gate}
                    version={view.version}
                    sha256={view.sha256}
                    subject={slug}
                    disabled={blockedByStale || !enabled}
                    pending={action.pending}
                    onDecide={decide}
                  />
                ) : null}
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
            </div>

            {/* Main review body: Left rules nav & Right article content */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, alignItems: 'flex-start' }}>
              {/* Left Nav: Rules / Sections */}
              <nav aria-label="Rules" style={{ flex: '1 1 240px', maxWidth: 300, display: 'flex', flexDirection: 'column', gap: 4, fontSize: 14 }}>
                <div style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', padding: '0 10px 6px' }}>
                  {gate === 'gherkin' ? 'Rules' : 'Sections'}
                </div>
                {rulesList.map((r) => (
                  <a
                    key={r.id}
                    href={`#${r.id}`}
                    style={{
                      padding: '8px 10px',
                      borderRadius: 8,
                      textDecoration: 'none',
                      color: 'var(--text)',
                      background: r.isNew ? 'var(--warn-bg, #FDF5E6)' : 'transparent',
                    }}
                    onClick={(e) => {
                      e.preventDefault();
                      document.getElementById(r.id)?.scrollIntoView({ behavior: 'smooth' });
                    }}
                  >
                    {r.title} <span style={{ color: r.isNew ? 'var(--on-warn, #9A4D06)' : 'var(--text-muted)' }}>· {r.count}{r.isNew ? ' · new' : ''}</span>
                  </a>
                ))}

                {view.version > 1 && (
                  <div style={{ marginTop: 16, padding: 12, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, fontSize: 13, lineHeight: 1.5, color: 'var(--text)' }}>
                    Your request on version {view.version - 1}: <em>&quot;Address feedback and review comments.&quot;</em>
                    <div style={{ marginTop: 6, color: 'var(--ok)', fontWeight: 600 }}>Done in version {view.version}</div>
                  </div>
                )}
              </nav>

              {/* Right Article: Content */}
              <article style={{ flex: '999 1 640px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 20 }}>
                <ValidationView validation={view.validation} />
                {gate === 'gherkin' ? (
                  <GherkinBody data={view as GherkinAnswer} version={view.version} />
                ) : (
                  <SpecBody data={view as SpecificationAnswer} tab={tab} setTab={setTab} pid={pid} slug={slug} />
                )}
                {gate === 'gherkin' && (
                  <div>
                    <h3>Versions</h3>
                    <VersionsList versions={view.versions} current={view.version} gate="gherkin" pid={pid} slug={slug} />
                  </div>
                )}
              </article>
            </div>

            {/* Full screen modal if toggled */}
            {fullScreen && (
              <div
                role="dialog"
                aria-modal="true"
                aria-label={`${label} review, full screen`}
                tabIndex={-1}
                ref={dialogRef}
                className="floor-fullscreen-dialog"
              >
                <div className="floor-fullscreen-header">
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: '1 1 360px', minWidth: 0 }}>
                    <h2 style={{ margin: 0, fontFamily: "'Space Grotesk', system-ui, sans-serif", fontSize: 20 }}>
                      {label} review · {slug}
                    </h2>
                    <span style={{ fontSize: 12, color: 'var(--floor-text-muted)' }}>
                      <strong style={{ color: 'var(--floor-text)' }}>Version {view.version}</strong>{' '}
                      <span style={{ color: 'var(--floor-waiting-label)' }}>{STATE_LABEL[view.state] ?? view.state}</span>
                      {' · '}
                      <code className="mono" style={{ wordBreak: 'break-all' }}>{view.sha256}</code>
                    </span>
                  </div>
                  <button type="button" className="floor-btn-exit" onClick={closeFullScreen}>
                    Exit full screen
                  </button>
                </div>

                <div className="floor-fullscreen-body" style={{ padding: 24 }}>
                  {gate === 'gherkin' ? (
                    <GherkinBody data={view as GherkinAnswer} version={view.version} />
                  ) : (
                    <SpecBody data={view as SpecificationAnswer} tab={tab} setTab={setTab} pid={pid} slug={slug} />
                  )}
                </div>
              </div>
            )}
          </div>
        );
      }}
    </Loaded>
  );
}
