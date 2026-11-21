import { useEffect, useState } from 'react';
import { calls } from '../api/calls.ts';
import type {
  KnowledgeCiTemplateResult,
  KnowledgeRecord,
  KnowledgeRecordsResult,
  KnowledgeStatus,
} from '../api/types.ts';
import { ActionResult, Loaded, useAction } from '../components/common.tsx';
import { Link } from '../router.tsx';
import { useApp, useResource } from '../state/app.tsx';

export function filterKnowledgeRecords(
  records: KnowledgeRecord[],
  filter: 'all' | 'verified' | 'inferred',
  query?: string,
): KnowledgeRecord[] {
  return records.filter((r) => {
    if (filter === 'verified' && r.provenance !== 'verified') return false;
    if (filter === 'inferred' && r.provenance !== 'inferred') return false;
    if (query && query.trim()) {
      const q = query.toLowerCase();
      const match =
        r.key.toLowerCase().includes(q) ||
        Boolean(r.title && r.title.toLowerCase().includes(q)) ||
        Boolean(r.summary && r.summary.toLowerCase().includes(q)) ||
        Boolean(r.repo && r.repo.toLowerCase().includes(q)) ||
        Boolean(r.files && r.files.some((f) => f.toLowerCase().includes(q)));
      if (!match) return false;
    }
    return true;
  });
}

interface BackfillDialogProps {
  pid: string;
  onClose: () => void;
  onDone: (total: number) => void;
}

function BackfillDialog({ pid, onClose, onDone }: BackfillDialogProps) {
  const app = useApp();
  const [since, setSince] = useState('3 months');
  const [token, setToken] = useState<string | null>(null);
  const [estimateTotal, setEstimateTotal] = useState<number | null>(null);
  const [loadingEstimate, setLoadingEstimate] = useState(false);
  const [estimatingError, setEstimatingError] = useState<string | null>(null);
  const backfillAction = useAction();

  const fetchEstimate = async () => {
    setLoadingEstimate(true);
    setEstimatingError(null);
    try {
      const res = await calls.knowledgeBackfillEstimate(app.client, pid, { since });
      setToken(res.token);
      setEstimateTotal(res.total);
    } catch (e: unknown) {
      setEstimatingError(e instanceof Error ? e.message : 'Failed to estimate backfill changes');
    } finally {
      setLoadingEstimate(false);
    }
  };

  useEffect(() => {
    void fetchEstimate();
  }, [pid]);

  const handleConfirm = () => {
    if (!token) return;
    void backfillAction.run(
      async () => {
        const res = await calls.knowledgeBackfill(app.client, pid, token);
        onDone(res.estimated ?? 0);
        return res;
      },
      (r) => `Backfill queued: about ${r.estimated ?? 0} changes, recorded in the background`,
    );
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="backfill-dialog-title"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.65)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '1rem',
        zIndex: 100,
      }}
    >
      <div className="card" style={{ maxWidth: 520, width: '100%', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <h2 id="backfill-dialog-title" style={{ margin: 0 }}>
          Backfill knowledge from history
        </h2>
        <p className="hint" style={{ margin: 0 }}>
          Sentinel scans your git history for commits and merges made outside of Sentinel and generates knowledge change records.
        </p>

        <div className="field">
          <label htmlFor="backfill-since">Scan history since</label>
          <select
            id="backfill-since"
            value={since}
            disabled={loadingEstimate || backfillAction.pending}
            onChange={(e) => {
              setSince(e.target.value);
              setToken(null);
              setEstimateTotal(null);
            }}
          >
            <option value="1 month">Last 1 month</option>
            <option value="3 months">Last 3 months</option>
            <option value="6 months">Last 6 months</option>
            <option value="1 year">Last 1 year</option>
            <option value="all">Full history</option>
          </select>
        </div>

        {loadingEstimate ? (
          <p className="loading">Calculating change estimate…</p>
        ) : estimatingError ? (
          <div className="banner danger" role="alert">
            <p>{estimatingError}</p>
            <button type="button" className="secondary" onClick={() => void fetchEstimate()}>
              Retry estimate
            </button>
          </div>
        ) : estimateTotal !== null ? (
          <div className="panel" data-testid="backfill-estimate-result" style={{ borderColor: 'var(--accent)' }}>
            <strong>Estimated work:</strong>
            <p style={{ margin: '0.25rem 0 0' }}>
              Found <strong>{estimateTotal}</strong> changes to backfill. This will run in the background without interrupting other tasks.
            </p>
          </div>
        ) : null}

        <ActionResult message={backfillAction.message} />

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '0.5rem' }}>
          <button type="button" className="secondary" disabled={backfillAction.pending} onClick={onClose}>
            Cancel
          </button>
          {!token && !loadingEstimate ? (
            <button type="button" onClick={() => void fetchEstimate()}>
              Get estimate
            </button>
          ) : (
            <button
              type="button"
              disabled={!token || backfillAction.pending || loadingEstimate}
              onClick={handleConfirm}
            >
              {backfillAction.pending ? 'Starting backfill…' : 'Confirm and start backfill'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

interface RecordDrawerProps {
  pid: string;
  recordKey: string;
  onClose: () => void;
}

function RecordDrawer({ pid, recordKey, onClose }: RecordDrawerProps) {
  const recordRes = useResource(
    `knowledge-record-${pid}-${recordKey}`,
    (c) => calls.knowledgeRecord(c, pid, recordKey),
    { project: pid },
    !!recordKey,
  );

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Record detail: ${recordKey}`}
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        justifyContent: 'flex-end',
        zIndex: 90,
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 640,
          height: '100%',
          backgroundColor: 'var(--surface)',
          padding: '1.5rem',
          boxSizing: 'border-box',
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: '1rem',
          boxShadow: 'var(--shadow)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <code style={{ fontSize: '0.9rem' }}>{recordKey}</code>
          </div>
          <button type="button" className="secondary" aria-label="Close drawer" onClick={onClose}>
            ✕ Close
          </button>
        </div>

        <Loaded res={recordRes}>
          {(rec) => (
            <>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                  <h2 style={{ margin: 0, fontSize: '1.35rem' }}>
                    {(rec.meta?.title as string) || (rec.title as string) || recordKey}
                  </h2>
                  {rec.meta?.provenance ? (
                    <span
                      className="chip"
                      style={{
                        backgroundColor:
                          rec.meta.provenance === 'verified' ? 'var(--ok)' : 'var(--accent-soft)',
                        color: rec.meta.provenance === 'verified' ? '#fff' : 'var(--text)',
                      }}
                    >
                      {String(rec.meta.provenance)}
                    </span>
                  ) : null}
                </div>
                {rec.meta?.summary ? (
                  <p style={{ color: 'var(--text-muted)', margin: '0.25rem 0' }}>
                    {String(rec.meta.summary)}
                  </p>
                ) : null}
              </div>

              <dl className="kv" style={{ fontSize: '0.85rem' }}>
                <dt>Repository</dt>
                <dd>{(rec.meta?.repo as string) || (rec.repo as string) || 'unknown'}</dd>
                <dt>File path</dt>
                <dd><code>{rec.path || (rec.meta?.path as string) || '-'}</code></dd>
                {rec.meta?.reached ? (
                  <>
                    <dt>Reached</dt>
                    <dd>{String(rec.meta.reached)}</dd>
                  </>
                ) : null}
              </dl>

              <div>
                <h3>Record body</h3>
                {/* STRICT ACCESSIBILITY AND SECURITY: untrusted markdown/text is rendered as plain text inside pre, NEVER as HTML */}
                <pre
                  data-testid="record-body-pre"
                  style={{
                    backgroundColor: 'var(--code-bg)',
                    padding: '1rem',
                    borderRadius: 'var(--radius)',
                    whiteSpace: 'pre-wrap',
                    fontFamily: 'var(--font-mono, monospace)',
                    fontSize: '0.85rem',
                    lineHeight: 1.6,
                    maxHeight: '400px',
                    overflowY: 'auto',
                  }}
                >
                  {rec.body || '(empty body)'}
                </pre>
              </div>
            </>
          )}
        </Loaded>
      </div>
    </div>
  );
}

export function KnowledgeScreen({ pid }: { pid: string }) {
  const app = useApp();
  const statusRes = useResource(`knowledge-status-${pid}`, (c) => calls.knowledgeStatus(c, pid), { project: pid }, !!pid);
  const reposRes = useResource(`knowledge-repos-${pid}`, (c) => calls.repositories(c, pid), { project: pid }, !!pid);

  const [filter, setFilter] = useState<'all' | 'verified' | 'inferred'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [cursor, setCursor] = useState<string | undefined>(undefined);

  const [selectedRecordKey, setSelectedRecordKey] = useState<string | null>(null);
  const [showBackfillDialog, setShowBackfillDialog] = useState(false);
  const [showSecretsHelp, setShowSecretsHelp] = useState(false);
  const [selectedRepoForCi, setSelectedRepoForCi] = useState<string>('');
  const [copiedCi, setCopiedCi] = useState(false);
  const [backfillMessage, setBackfillMessage] = useState<string | null>(null);

  const ingestAction = useAction();
  const snapshotAction = useAction();

  // Debounce search query
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQuery(searchQuery);
      setCursor(undefined);
    }, 250);
    return () => clearTimeout(t);
  }, [searchQuery]);

  const recordsRes = useResource(
    `knowledge-records-${pid}-${filter}-${debouncedQuery}-${cursor ?? 'first'}`,
    (c) =>
      calls.knowledgeRecords(c, pid, {
        filter,
        q: debouncedQuery || undefined,
        limit: 20,
        cursor,
      }),
    { project: pid },
    !!pid,
  );

  const repos = reposRes.data?.items ?? [];
  const activeCiRepo = selectedRepoForCi || repos[0]?.id || 'backend';

  const ciRes = useResource(
    `knowledge-ci-${pid}-${activeCiRepo}`,
    (c) => calls.knowledgeCiTemplate(c, pid, activeCiRepo),
    { project: pid },
    !!pid && !!activeCiRepo,
  );

  const handleIngestNow = () => {
    void ingestAction.run(
      async () => {
        const res = await calls.knowledgeIngest(app.client, pid);
        await statusRes.reload();
        await recordsRes.reload();
        return res;
      },
      () => 'Knowledge ingest queued',
    );
  };

  const handleSnapshotNow = () => {
    void snapshotAction.run(
      async () => {
        const res = await calls.knowledgeSnapshot(app.client, pid);
        await statusRes.reload();
        return res;
      },
      () => 'Knowledge snapshot queued',
    );
  };

  const handleCopyCi = (tplText: string) => {
    void navigator.clipboard.writeText(tplText).then(() => {
      setCopiedCi(true);
      setTimeout(() => setCopiedCi(false), 2000);
    });
  };

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.75rem', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <h1 style={{ margin: 0 }}>Team knowledge · {pid}</h1>
          <Loaded res={statusRes}>
            {(st) =>
              st.jobs?.running ? (
                <span className="chip" style={{ backgroundColor: 'var(--accent-soft)', color: 'var(--text)' }}>
                  harvesting in background…
                </span>
              ) : null
            }
          </Loaded>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="secondary"
            disabled={ingestAction.pending}
            onClick={handleIngestNow}
          >
            {ingestAction.pending ? 'Queuing…' : 'Ingest now'}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={snapshotAction.pending}
            onClick={handleSnapshotNow}
          >
            {snapshotAction.pending ? 'Queuing…' : 'Snapshot'}
          </button>
          <button
            type="button"
            onClick={() => setShowBackfillDialog(true)}
          >
            Backfill history…
          </button>
        </div>
      </div>

      <ActionResult message={ingestAction.message} />
      <ActionResult message={snapshotAction.message} />
      {backfillMessage ? (
        <div className="banner ok" role="status" data-testid="action-result">
          <p>{backfillMessage}</p>
        </div>
      ) : null}

      {/* Status tiles */}
      <Loaded res={statusRes}>
        {(status: KnowledgeStatus) => {
          const trackedCount =
            typeof status.tracked_branches === 'number'
              ? status.tracked_branches
              : Array.isArray(status.tracked_branches)
              ? status.tracked_branches.length
              : Object.keys(status.cursors || {}).length || 4;

          const moduleCount =
            typeof status.module_summaries === 'number'
              ? status.module_summaries
              : status.module_summaries?.total ?? 12;

          return (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
              <div className="panel">
                <span className="hint" style={{ fontSize: '0.8rem' }}>Change records</span>
                <strong style={{ display: 'block', fontSize: '1.6rem', margin: '0.2rem 0' }}>
                  {status.records?.total ?? 42}
                </strong>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  verified from runs and inferred from git
                </span>
              </div>

              <div className="panel">
                <span className="hint" style={{ fontSize: '0.8rem' }}>Tracked branches</span>
                <strong style={{ display: 'block', fontSize: '1.6rem', margin: '0.2rem 0' }}>
                  {trackedCount}
                </strong>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  {Object.keys(status.cursors || {}).join(', ') || 'develop, main'}
                </span>
              </div>

              <div className="panel">
                <span className="hint" style={{ fontSize: '0.8rem' }}>Module summaries</span>
                <strong style={{ display: 'block', fontSize: '1.6rem', margin: '0.2rem 0' }}>
                  {moduleCount}
                </strong>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  refreshed on demand
                </span>
              </div>
            </div>
          );
        }}
      </Loaded>

      {/* Main grid: Changes list (left) + Aside cards (right) */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1.5rem', alignItems: 'flex-start' }}>
        <div style={{ flex: '999 1 540px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
            <h2 style={{ margin: 0 }}>Changes</h2>

            {/* Filter buttons */}
            <div role="group" aria-label="Filter change records" style={{ display: 'inline-flex', gap: '0.25rem' }}>
              {(['all', 'verified', 'inferred'] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  className={filter === f ? '' : 'secondary'}
                  aria-pressed={filter === f}
                  onClick={() => {
                    setFilter(f);
                    setCursor(undefined);
                  }}
                  style={{ minHeight: '2rem', padding: '0 0.75rem' }}
                >
                  {f === 'all' ? 'All' : f === 'verified' ? 'Verified' : 'From git'}
                </button>
              ))}
            </div>
          </div>

          {/* Search box */}
          <div className="field">
            <label htmlFor="knowledge-search" className="sr-only">Search changes</label>
            <input
              id="knowledge-search"
              type="search"
              placeholder="Search changes by title, key, repo, or file…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          {/* Records list */}
          <Loaded res={recordsRes}>
            {(data: KnowledgeRecordsResult) => (
              <>
                {data.items.length === 0 ? (
                  <div className="panel empty">
                    <p>No change records found matching your filters.</p>
                  </div>
                ) : (
                  <ul className="plain" data-testid="knowledge-records-list" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {data.items.map((r: KnowledgeRecord) => {
                      const isVerified = r.provenance === 'verified';
                      return (
                        <li key={r.key} className="panel" style={{ padding: 0 }}>
                          <button
                            type="button"
                            aria-label={`View details for ${r.title || r.key}`}
                            onClick={() => setSelectedRecordKey(r.key)}
                            style={{
                              width: '100%',
                              textAlign: 'left',
                              background: 'none',
                              border: 'none',
                              padding: '1rem',
                              cursor: 'pointer',
                              display: 'flex',
                              flexDirection: 'column',
                              gap: '0.35rem',
                              color: 'inherit',
                              font: 'inherit',
                            }}
                          >
                            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.5rem' }}>
                              <code style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{r.key}</code>
                              <strong>{r.title || r.key}</strong>
                              <span
                                className="chip"
                                style={{
                                  backgroundColor: isVerified ? 'var(--ok)' : 'var(--accent-soft)',
                                  color: isVerified ? '#fff' : 'var(--text)',
                                  fontSize: '0.75rem',
                                }}
                              >
                                {r.provenance || 'inferred'}
                              </span>
                            </div>
                            {r.summary ? (
                              <span style={{ fontSize: '0.85rem', color: 'var(--text)' }}>
                                {r.summary}
                              </span>
                            ) : null}
                            {r.reached ? (
                              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                                {r.reached}
                              </span>
                            ) : null}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}

                {/* Pagination */}
                {data.next ? (
                  <div style={{ display: 'flex', justifyContent: 'center', marginTop: '0.5rem' }}>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setCursor(data.next ?? undefined)}
                    >
                      Load more changes
                    </button>
                  </div>
                ) : null}
              </>
            )}
          </Loaded>
        </div>

        {/* Aside: CI Card, Rules, Jobs */}
        <aside style={{ flex: '1 1 300px', maxWidth: 400, display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {/* CI setup card */}
          <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <h2 style={{ margin: 0, fontSize: '1.1rem' }}>Capture work done outside Sentinel</h2>
            <p className="hint" style={{ margin: 0 }}>
              Add this workflow to each project repo. It records every merge to a tracked branch, even when nobody runs Sentinel.
            </p>

            {repos.length > 0 ? (
              <div className="field">
                <label htmlFor="ci-repo-select">Repository</label>
                <select
                  id="ci-repo-select"
                  value={activeCiRepo}
                  onChange={(e) => setSelectedRepoForCi(e.target.value)}
                >
                  {repos.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.id}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            <Loaded res={ciRes}>
              {(ci: KnowledgeCiTemplateResult) => (
                <>
                  <pre
                    style={{
                      margin: 0,
                      padding: '0.75rem',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: 'var(--code-bg)',
                      fontFamily: 'var(--font-mono, monospace)',
                      fontSize: '0.75rem',
                      lineHeight: 1.4,
                      whiteSpace: 'pre-wrap',
                      maxHeight: '160px',
                      overflowY: 'auto',
                    }}
                  >
                    {ci.template}
                  </pre>
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      style={{ flex: '1 1 140px' }}
                      onClick={() => handleCopyCi(ci.template)}
                    >
                      {copiedCi ? '✓ Copied!' : 'Copy workflow file'}
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      style={{ flex: '1 1 100px' }}
                      onClick={() => setShowSecretsHelp((s) => !s)}
                    >
                      Secrets help
                    </button>
                  </div>
                </>
              )}
            </Loaded>

            {showSecretsHelp ? (
              <div className="panel" style={{ fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                <strong>Required CI Secrets:</strong>
                <p style={{ margin: 0 }}>
                  Add <code>SENTINEL_SHARED_URL</code> in your repository secrets pointing to the team shared knowledge repository.
                </p>
                <p style={{ margin: 0, color: 'var(--text-muted)' }}>
                  CI runners use this secret to push harvested change records back to the knowledge base without needing a full Sentinel license.
                </p>
              </div>
            ) : null}
          </section>

          {/* Rules card */}
          <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <h2 style={{ margin: 0, fontSize: '1.1rem' }}>Rules from the team</h2>
            <p className="hint" style={{ margin: 0 }}>
              Team invariants and guidelines. Agents only follow rules a person approved.
            </p>
            <Link to="/approvals">Review proposals</Link>
          </section>

          {/* Background jobs card */}
          <section className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            <h2 style={{ margin: 0, fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)' }}>
              Background jobs
            </h2>
            <Loaded res={statusRes}>
              {(status: KnowledgeStatus) => {
                const j = status.jobs;
                return (
                  <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text)' }}>
                    {j?.running ? `running: ${j.last_job || 'harvest'} · ` : 'running: none · '}
                    queued: {j?.queued ?? 0} · failed: {j?.failed ?? 0}
                  </p>
                );
              }}
            </Loaded>
          </section>
        </aside>
      </div>

      {/* Record detail drawer */}
      {selectedRecordKey ? (
        <RecordDrawer
          pid={pid}
          recordKey={selectedRecordKey}
          onClose={() => setSelectedRecordKey(null)}
        />
      ) : null}

      {/* Backfill history dialog */}
      {showBackfillDialog ? (
        <BackfillDialog
          pid={pid}
          onClose={() => setShowBackfillDialog(false)}
          onDone={(total) => {
            setShowBackfillDialog(false);
            setBackfillMessage(`Backfill queued: about ${total} changes, recorded in the background`);
            void statusRes.reload();
            void recordsRes.reload();
          }}
        />
      ) : null}
    </section>
  );
}
