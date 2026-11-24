// SidePanel: detail panel for the selected station + run controls.
import { useId, useState, useEffect } from 'react';
import { useApp } from '../../state/app.tsx';
import { useAction, ActionResult, ConfirmDialog, useControlsEnabled } from '../common.tsx';
import { calls } from '../../api/calls.ts';
import type { ApiError } from '../../api/errors.ts';
import { Link, enc } from '../../router.tsx';
import type { RunView, StationDef, StationState, WhoView } from './types.ts';
import { stateLook } from './look.ts';
import { laneLabel, stationById } from './layout.ts';
import { limitText } from './adapt.ts';
import { ReviewPage } from '../../screens/Approvals.tsx';
import { AcceptanceTab } from '../../screens/run/Acceptance.tsx';

interface SidePanelProps {
  station: StationDef | null;
  state: StationState;
  run: RunView | null;
  /** routing per agent station from the snapshot, used when no agent is running there */
  who?: Record<string, WhoView>;
  pid: string;
  singleModel?: boolean;
  onChanged: () => void;
}

type DialogKind = 'cancel' | 'resume';

export function SidePanel({ station, state, run, who, pid, singleModel = false, onChanged }: SidePanelProps) {
  const app = useApp();
  const enabled = useControlsEnabled();
  const action = useAction();
  const noteId = useId();
  const [note, setNote] = useState('');
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const [resumeComment, setResumeComment] = useState('');
  const [tab, setTab] = useState<'station' | 'review'>('station');
  const [logLines, setLogLines] = useState<string[]>([]);

  // Automatically open Review tab when a waiting gate station is selected
  useEffect(() => {
    if (run?.attention) {
      setTab('station');
    } else if (station && ['gate_spec', 'gate_gherkin', 'gate_accept'].includes(station.id) && state === 'waiting') {
      setTab('review');
    } else if (tab === 'review') {
      setTab('station');
    }
  }, [station?.id, state, run?.attention]);

  const baseStationId = station ? (station.id.startsWith('build') ? 'build' : station.id) : '';

  // Feature C: latest task and log polling
  const stationTasks = run?.station_tasks?.[baseStationId] ?? [];
  const latestTask = stationTasks.length > 0 ? stationTasks[stationTasks.length - 1] : null;

  useEffect(() => {
    if (!run || !latestTask || tab !== 'station') {
      setLogLines([]);
      return;
    }
    let cancelled = false;
    let offset = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const fetchLog = async () => {
      try {
        const res = await calls.log(app.client, run.slug, pid, latestTask.id, offset);
        if (cancelled) return;
        if (res.lines && res.lines.length > 0) {
          setLogLines((prev) => (offset === 0 ? res.lines : [...prev, ...res.lines]));
          offset = res.next_offset;
        }
        if (latestTask.state === 'RUNNING' && res.running) {
          timer = setTimeout(fetchLog, 2000);
        }
      } catch {
        // Ignore errors during log fetch
      }
    };

    void fetchLog();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [app.client, run?.slug, pid, latestTask?.id, latestTask?.state, tab]);

  if (!station || !run) {
    return (
      <aside aria-label="Selected station" className="floor-panel">
        <div className="floor-panel-section">
          <p style={{ margin: 0, color: 'var(--floor-text-muted)', fontSize: 13 }}>
            Click any station to see what happens there.
          </p>
        </div>
      </aside>
    );
  }

  const L = stateLook(state);
  const idx = [
    'intake', 'triage', 'spec', 'gate_spec', 'gherkin', 'gate_gherkin',
    'build', 'verify', 'report', 'gate_accept', 'knowledge',
  ].indexOf(baseStationId);

  const kindLabel = station.kind === 'gate' ? 'human gate' : station.kind;
  const agents = run.agents[baseStationId] ?? [];
  const routed = who?.[baseStationId];
  const whoText = agents.length > 0
    ? agents.map((a) => [a.role, a.runner, a.model].filter(Boolean).join(' · ')).join('; ')
    : station.kind === 'gate' ? 'you'
    : station.kind === 'engine' ? (baseStationId === 'knowledge' && routed ? `engine · summaries by ${[routed.runner, routed.model].filter(Boolean).join(' · ')}` : 'engine')
    : routed ? [routed.role, routed.runner, routed.model].filter(Boolean).join(' · ') : '—';

  const isWaiting = state === 'waiting';
  const isAccept = station.id === 'gate_accept';
  const runBase = `/projects/${enc(pid)}/runs/${enc(run.slug)}`;

  // Determine lane details if this is a build lane
  const laneIdx = station.id.startsWith('build-') ? parseInt(station.id.slice('build-'.length), 10) : -1;
  const currentLane = laneIdx >= 0 && run.lanes[laneIdx] ? run.lanes[laneIdx] : null;

  const usage = run.task_usage?.[baseStationId];
  const usageParts = usage
    ? [
        usage.tokens !== null && usage.tokens !== undefined ? `${usage.tokens.toLocaleString()} tokens` : null,
        usage.cost !== null && usage.cost !== undefined ? `$${usage.cost.toFixed(2)}` : null,
        usage.seconds !== null && usage.seconds !== undefined ? `${Math.round(usage.seconds)}s` : null,
      ].filter(Boolean)
    : [];
  const usageText = usageParts.join(' · ');

  let thisTaskText = '—';
  if (state === 'todo' || state === 'next') {
    thisTaskText = 'Not reached yet';
  } else if (state === 'limit' && run.limit) {
    thisTaskText = `${limitText(run.limit.retryAt)} (${run.limit.runner})`;
  } else if (currentLane) {
    const laneState = currentLane.state.toLowerCase().replace(/_/g, ' ');
    thisTaskText = `${laneLabel(currentLane.name)} · ${laneState}`;
  } else if (run.lanes.length > 0 && baseStationId === 'build') {
    thisTaskText = run.lanes.map((l) => `${laneLabel(l.name)}: ${l.state.toLowerCase().replace(/_/g, ' ')}`).join('; ');
  } else if (agents.length > 0) {
    thisTaskText = `${agents[0].role} · running`;
  } else if (state === 'done') {
    thisTaskText = usageText ? `Done · used ${usageText}` : 'Done';
  } else if (state === 'waiting') {
    thisTaskText = `Waiting for you${run.pendingNotes > 0 ? ` · ${run.pendingNotes} note(s) pending` : ''}`;
  }

  const nextStationDef = run.nextStation ? stationById(run.nextStation) : null;
  const nextText = station.id === 'knowledge'
    ? 'Feeds every future task'
    : baseStationId === 'build'
    ? 'Verify'
    : nextStationDef ? nextStationDef.name : run.nextStation ?? 'Done';

  const sendNote = async () => {
    const text = note.trim();
    if (!text) return;
    await action.run(
      () => calls.sendNote(app.client, run.slug, pid, text),
      () => 'Note sent',
      { onSettled: () => { setNote(''); onChanged(); } },
    );
  };

  const togglePause = async () => {
    if (run.paused) {
      await action.run(
        () => calls.unpause(app.client, run.slug, pid),
        () => 'Resumed',
        { onSettled: onChanged },
      );
    } else {
      await action.run(
        () => calls.pause(app.client, run.slug, pid),
        () => 'Paused',
        { onSettled: onChanged },
      );
    }
  };

  const cancelRun = async () => {
    await action.run(
      () => calls.control(app.client, run.slug, pid, { action: 'cancel' }),
      () => 'Cancelled',
      {
        onSettled: () => {
          setDialog(null);
          onChanged();
        },
      },
    );
  };

  const resumeRun = async () => {
    const trimmed = resumeComment.trim();
    if (!trimmed) return;
    await action.run(
      () => calls.control(app.client, run.slug, pid, { action: 'resume', comment: trimmed }),
      () => 'Run resumed',
      {
        onError: (e: ApiError) => (e.code === 'E_TRANSITION' ? 'Refused: the run moved on.' : undefined),
        onSettled: () => {
          setDialog(null);
          setResumeComment('');
          onChanged();
        },
      },
    );
  };

  const retryNow = async () => {
    await action.run(
      () => calls.retryNow(app.client, run.slug, pid),
      () => 'Retry queued',
      { onSettled: onChanged },
    );
  };

  // Determine review gate
  let reviewGate: 'specification' | 'gherkin' | 'acceptance' | null = null;
  if (station.id === 'gate_spec') reviewGate = 'specification';
  else if (station.id === 'gate_gherkin') reviewGate = 'gherkin';
  else if (station.id === 'gate_accept') reviewGate = 'acceptance';
  else if (run.stations.gate_spec === 'waiting') reviewGate = 'specification';
  else if (run.stations.gate_gherkin === 'waiting') reviewGate = 'gherkin';
  else if (run.stations.gate_accept === 'waiting') reviewGate = 'acceptance';

  const hasWaitingGate = ['gate_spec', 'gate_gherkin', 'gate_accept'].some((g) => run.stations[g] === 'waiting');
  const logTitle = latestTask?.state === 'RUNNING' ? 'Live work' : 'What happened';

  return (
    <aside aria-label="Selected station" className="floor-panel">
      {/* Panel Tab Navigation */}
      <div role="group" aria-label="Panel tabs" className="floor-panel-tabs">
        <button
          type="button"
          className="floor-panel-tab"
          aria-pressed={tab === 'station'}
          onClick={() => setTab('station')}
        >
          Station
        </button>
        <button
          type="button"
          className="floor-panel-tab"
          aria-pressed={tab === 'review'}
          onClick={() => setTab('review')}
        >
          Review{hasWaitingGate ? ' •' : ''}
        </button>
      </div>

      {tab === 'review' ? (
        <section className="floor-panel-section">
          {reviewGate === 'specification' || reviewGate === 'gherkin' ? (
            <ReviewPage
              gate={reviewGate}
              pid={pid}
              slug={run.slug}
              onRunChanged={onChanged}
              compact
            />
          ) : reviewGate === 'acceptance' ? (
            <AcceptanceTab
              run={run}
              pid={pid}
              onChanged={onChanged}
              compact
            />
          ) : (
            <p style={{ margin: 0, color: 'var(--floor-text-muted)', fontSize: 13 }}>
              Nothing in this run waits for your review.
            </p>
          )}
        </section>
      ) : (
        <>
          {/* Station info panel */}
          <section
            className="floor-panel-section"
            style={{ borderColor: L.live ? L.ring : 'var(--floor-border)' }}
          >
            {/* kind + state badge */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
              <span style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'var(--floor-text-muted)' }}>
                {kindLabel} · station {idx + 1}
              </span>
              <span
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  fontSize: 11, fontWeight: 600,
                  padding: '3px 9px', borderRadius: 10,
                  background: L.badgeBg, color: L.badgeFg,
                }}
              >
                {L.live && (
                  <span
                    className="floor-pulse"
                    aria-hidden="true"
                    style={{ width: 6, height: 6, borderRadius: '50%', background: L.badgeFg }}
                  />
                )}
                {L.label}
              </span>
            </div>

            {/* station name */}
            <h2 style={{ margin: 0, fontFamily: "'Space Grotesk', system-ui, sans-serif", fontSize: 22, color: 'var(--floor-text)' }}>
              {station.name}
            </h2>
            <p style={{ margin: 0, color: 'var(--floor-text-muted)', fontSize: 13 }}>{station.does}</p>

            {/* key-value grid */}
            <dl className="floor-panel-dl">
              <dt className="floor-panel-dt">Who</dt>
              <dd className="floor-panel-dd" style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12 }}>
                <span>{whoText}</span>{' '}
                {station.kind === 'agent' && (
                  <span className={singleModel ? 'floor-tag-orch' : 'floor-tag-routed'}>
                    {singleModel ? 'orchestrator' : 'routed'}
                  </span>
                )}
              </dd>

              <dt className="floor-panel-dt">This task</dt>
              <dd className="floor-panel-dd">{thisTaskText}</dd>
              {usageText ? (
                <>
                  <dt className="floor-panel-dt">This task used</dt>
                  <dd className="floor-panel-dd" data-testid="task-usage">{usageText}</dd>
                </>
              ) : null}

              {/* Lanes for build */}
              {run.lanes.length > 0 && baseStationId === 'build' && (
                <>
                  <dt className="floor-panel-dt">Lanes</dt>
                  <dd className="floor-panel-dd">
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {run.lanes.map((l) => (
                        <div key={l.cycle} style={{ fontSize: 12 }}>
                          <span title={l.name}>{laneLabel(l.name)}</span>: {l.state.toLowerCase().replace(/_/g, ' ')}
                        </div>
                      ))}
                    </div>
                  </dd>
                </>
              )}

              <dt className="floor-panel-dt">Knowledge</dt>
              <dd className="floor-panel-dd">{station.knowledgeText}</dd>

              <dt className="floor-panel-dt">Next</dt>
              <dd className="floor-panel-dd">{nextText}</dd>
            </dl>

            {/* Feature C: Live work / What happened log tail */}
            <div>
              <h3 style={{ margin: '0 0 6px', fontSize: 12, letterSpacing: '.4px', textTransform: 'uppercase', color: 'var(--floor-text-muted)' }}>
                {logTitle}
              </h3>
              {!latestTask ? (
                <p style={{ margin: 0, fontSize: 13, color: 'var(--floor-text-muted)' }}>Not reached yet</p>
              ) : (
                <ol className="floor-log-box" data-testid="station-log">
                  {logLines.length > 0 ? (
                    logLines.map((line, i) => <li key={i}>{line}</li>)
                  ) : (
                    <li style={{ color: 'var(--floor-text-muted)' }}>No log output yet</li>
                  )}
                </ol>
              )}
            </div>

            {/* action links */}
            {(state === 'limit' || run.limit) && (
              <button
                type="button"
                disabled={!enabled || action.pending}
                onClick={() => void retryNow()}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  minHeight: 44, borderRadius: 10,
                  background: 'var(--floor-waiting-ring)', color: '#1A1206',
                  fontWeight: 600, border: 0, cursor: 'pointer', width: '100%',
                  marginBottom: 8,
                }}
              >
                Retry now
              </button>
            )}

            {/* Feature A point 4: Run needs you with inline Resume button */}
            {run.attention && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <p className="banner warn" data-testid="floor-attention" style={{ margin: 0 }}>
                  {run.attention.kind === 'needs_human' ? 'Needs you' : 'Blocked'}: {run.attention.reason}
                </p>
                <button
                  type="button"
                  className="floor-btn-resume"
                  disabled={!enabled || action.pending}
                  onClick={() => setDialog('resume')}
                >
                  Resume
                </button>
              </div>
            )}

            {/* Gate open review button */}
            {station.kind === 'gate' && isWaiting && (
              <button
                type="button"
                onClick={() => setTab('review')}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  minHeight: 44, borderRadius: 10,
                  background: 'var(--floor-waiting-ring)', color: '#1A1206',
                  fontWeight: 600, border: 0, cursor: 'pointer', width: '100%',
                }}
              >
                Open review here
              </button>
            )}

            {/* Full run link */}
            {isAccept && (
              <p style={{ margin: '4px 0 0' }}>
                <Link to={isWaiting ? `${runBase}/acceptance` : `${runBase}/report`}>
                  Open the report
                </Link>
              </p>
            )}
            <Link to={runBase} style={{ fontSize: 13, marginTop: 4 }}>
              Open the full run: logs, diffs, evidence
            </Link>
          </section>

          {/* Controls panel */}
          <section className="floor-panel-section">
            <h2 style={{ margin: 0, fontSize: 12, letterSpacing: '.4px', textTransform: 'uppercase', color: 'var(--floor-text-muted)' }}>
              Control {run.title}
            </h2>

            <ActionResult message={action.message} />

            {/* step-in note */}
            <label htmlFor={noteId} style={{ fontSize: 13, color: 'var(--floor-text-muted)' }}>
              Step in: a note for the next agent
            </label>
            <textarea
              id={noteId}
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={4000}
              placeholder="e.g. reuse ExportService, do not add a new class"
              style={{
                resize: 'vertical', padding: 10, borderRadius: 10,
                border: '1px solid var(--border-strong)', background: 'var(--surface)',
                color: 'var(--text)', fontFamily: 'inherit', fontSize: 13,
                width: '100%', boxSizing: 'border-box',
              }}
            />
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              <button
                type="button"
                disabled={!enabled || action.pending || !note.trim()}
                onClick={() => void sendNote()}
                style={{
                  flex: '1 1 110px', minHeight: 44, borderRadius: 10,
                  border: 0, background: 'var(--floor-working-ring)', color: '#062420',
                  fontWeight: 600, cursor: 'pointer',
                }}
              >
                Send note
              </button>
              <button
                type="button"
                disabled={!enabled || action.pending}
                onClick={() => void togglePause()}
                style={{
                  flex: '1 1 90px', minHeight: 44, borderRadius: 10,
                  border: '1px solid var(--border-strong)', background: 'var(--surface)',
                  color: 'var(--text)', fontWeight: 600, cursor: 'pointer',
                }}
              >
                {run.paused ? 'Resume' : 'Pause'}
              </button>
              <button
                type="button"
                disabled={!enabled || action.pending}
                onClick={() => setDialog('cancel')}
                style={{
                  flex: '1 1 90px', minHeight: 44, borderRadius: 10,
                  border: '1px solid var(--danger)', background: 'transparent',
                  color: 'var(--danger)', fontWeight: 600, cursor: 'pointer',
                }}
              >
                Cancel
              </button>
            </div>
          </section>
        </>
      )}

      {/* Cancel confirmation */}
      {dialog === 'cancel' && (
        <ConfirmDialog
          text={`Cancel run ${run.slug}? This cannot be undone.`}
          cancelLabel="Keep running"
          confirmLabel="Cancel run"
          danger
          pending={action.pending}
          onCancel={() => setDialog(null)}
          onConfirm={() => void cancelRun()}
        />
      )}

      {/* Resume confirmation dialog */}
      {dialog === 'resume' && (
        <ConfirmDialog
          text={`Resume run ${run.slug}? It continues from the state it had before it needed you.`}
          cancelLabel="Cancel"
          confirmLabel="Resume"
          initialFocus="comment"
          confirmDisabled={resumeComment.trim() === ''}
          pending={action.pending}
          onCancel={() => {
            setDialog(null);
            setResumeComment('');
          }}
          onConfirm={() => void resumeRun()}
        >
          <div className="field">
            <label htmlFor="resume-comment">Comment</label>
            <textarea
              id="resume-comment"
              rows={3}
              value={resumeComment}
              onChange={(e) => setResumeComment(e.target.value)}
              placeholder="Say what was fixed"
              style={{
                resize: 'vertical', padding: 10, borderRadius: 10,
                border: '1px solid var(--border-strong)', background: 'var(--surface)',
                color: 'var(--text)', fontFamily: 'inherit', fontSize: 13,
                width: '100%', boxSizing: 'border-box',
              }}
            />
            {resumeComment.trim() === '' ? (
              <p className="field-error">Say what was fixed</p>
            ) : (
              <p className="hint">Required</p>
            )}
          </div>
        </ConfirmDialog>
      )}
    </aside>
  );
}
