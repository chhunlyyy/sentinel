// SidePanel: detail panel for the selected station + run controls.
import { useId, useState } from 'react';
import { useApp } from '../../state/app.tsx';
import { useAction, ActionResult, ConfirmDialog, useControlsEnabled } from '../common.tsx';
import { calls } from '../../api/calls.ts';
import { Link, enc } from '../../router.tsx';
import type { RunView, StationDef, StationState } from './types.ts';
import { stateLook } from './look.ts';
import { stationById } from './layout.ts';

interface SidePanelProps {
  station: StationDef | null;
  state: StationState;
  run: RunView | null;
  pid: string;
  onChanged: () => void;
}

type DialogKind = 'cancel';

export function SidePanel({ station, state, run, pid, onChanged }: SidePanelProps) {
  const app = useApp();
  const enabled = useControlsEnabled();
  const action = useAction();
  const noteId = useId();
  const [note, setNote] = useState('');
  const [dialog, setDialog] = useState<DialogKind | null>(null);

  if (!station || !run) {
    return (
      <aside
        aria-label="Selected station"
        className="floor-panel"
      >
        <div className="floor-panel-section">
          <p style={{ margin: 0, color: 'var(--floor-text-muted)', fontSize: 13 }}>
            Click any station to see what happens there.
          </p>
        </div>
      </aside>
    );
  }

  const L = stateLook(state);
  const baseStationId = station.id.startsWith('build') ? 'build' : station.id;
  const idx = [
    'intake', 'triage', 'spec', 'gate_spec', 'gherkin', 'gate_gherkin',
    'build', 'verify', 'report', 'gate_accept', 'knowledge',
  ].indexOf(baseStationId);

  const kindLabel = station.kind === 'gate' ? 'human gate' : station.kind;
  const agents = run.agents[baseStationId] ?? [];
  const whoText = agents.length > 0
    ? agents.map((a) => [a.role, a.runner, a.model].filter(Boolean).join(' · ')).join('; ')
    : station.kind === 'gate' ? 'you' : station.kind === 'engine' ? 'engine' : '—';

  const isWaiting = state === 'waiting';
  const isAccept = station.id === 'gate_accept';
  const runBase = `/projects/${enc(pid)}/runs/${enc(run.slug)}`;

  // Determine lane details if this is a build lane
  const laneIdx = station.id.startsWith('build-') ? parseInt(station.id.slice('build-'.length), 10) : -1;
  const currentLane = laneIdx >= 0 && run.lanes[laneIdx] ? run.lanes[laneIdx] : null;

  let thisTaskText = '—';
  if (state === 'todo' || state === 'next') {
    thisTaskText = 'Not reached yet';
  } else if (currentLane) {
    const laneState = currentLane.state.toLowerCase().replace(/_/g, ' ');
    thisTaskText = `${currentLane.name} · ${laneState}`;
  } else if (run.lanes.length > 0 && baseStationId === 'build') {
    thisTaskText = run.lanes.map((l) => `${l.name}: ${l.state.toLowerCase().replace(/_/g, ' ')}`).join('; ');
  } else if (agents.length > 0) {
    thisTaskText = `${agents[0].role} · running`;
  } else if (state === 'done') {
    thisTaskText = 'Done';
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

  return (
    <aside
      aria-label="Selected station"
      className="floor-panel"
    >
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
          <dd className="floor-panel-dd" style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12 }}>{whoText}</dd>

          <dt className="floor-panel-dt">This task</dt>
          <dd className="floor-panel-dd">{thisTaskText}</dd>

          <dt className="floor-panel-dt">Knowledge</dt>
          <dd className="floor-panel-dd">{station.knowledgeText}</dd>

          <dt className="floor-panel-dt">Next</dt>
          <dd className="floor-panel-dd">{nextText}</dd>
        </dl>

        {/* action links */}
        {isWaiting && !isAccept && (
          <Link
            to={`${runBase}/specification`}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              minHeight: 44, borderRadius: 10,
              background: 'var(--floor-waiting-ring)', color: 'var(--floor-waiting-fill)',
              fontWeight: 600, textDecoration: 'none',
            }}
          >
            Review specification
          </Link>
        )}
        {isAccept && (
          <Link
            to={`${runBase}/acceptance`}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              minHeight: 44, borderRadius: 10,
              border: '1px solid var(--border-strong)', color: 'var(--text)',
              fontWeight: 600, textDecoration: 'none',
            }}
          >
            Preview the report page
          </Link>
        )}
        <Link to={runBase} style={{ fontSize: 13, marginTop: 2 }}>
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
              border: 0, background: 'var(--floor-working-ring)', color: 'var(--floor-working-fill)',
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
    </aside>
  );
}
