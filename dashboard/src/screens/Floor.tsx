// Factory Floor screen (W4)
// Route: /floor  and  /projects/{pid}/floor
import { useState, useMemo, useEffect } from 'react';
import { calls } from '../api/calls.ts';
import { useResource } from '../state/app.tsx';
import { floorSnapshot, laneState, initials } from '../components/floor/adapt.ts';
import { STATIONS, buildLanePositions, MAX_LANES, stationById } from '../components/floor/layout.ts';
import { NeuronButton } from '../components/floor/NeuronButton.tsx';
import { EdgeLayer } from '../components/floor/EdgeLayer.tsx';
import { SidePanel } from '../components/floor/SidePanel.tsx';
import { Loaded } from '../components/common.tsx';
import { RoutingBanner } from '../components/RoutingFix.tsx';
import type { ActivityView, FloorSnapshot, RunView, StationState, StationDef } from '../components/floor/types.ts';
import { Link, enc, navigate, useRoute } from '../router.tsx';

// Factory-level event types that trigger a snapshot refetch
const FACTORY_EVENT_TYPES = [
  'run.started', 'run.paused', 'run.unpaused', 'run.note_added',
  'run.state_changed', 'task.state_changed', 'task.started', 'task.finished',
  'run.cancelled', 'run.completed', 'run.created',
  'approval.requested', 'approval.decided', 'task.failed',
  'knowledge.failed', 'knowledge.updated', 'factory.paused', 'factory.resumed', 'task.limit_reached', 'task.queued',
] as const;

/** Choose a stable default task to show when the floor loads */
function defaultTaskSlug(snap: FloorSnapshot): string | null {
  const working = snap.runs.find((r) => !r.paused && r.stations[r.station] === 'working');
  const waiting = snap.runs.find((r) => r.stations[r.station] === 'waiting');
  return (working ?? waiting ?? snap.runs[0])?.slug ?? null;
}

/** The station node to select for a run: its current station, or the busiest lane when build fans out. */
export function nodeOfRun(run: RunView): string {
  if (run.station !== 'build' || run.lanes.length < 2) return run.station;
  const states = run.lanes.map((l) => laneState(l, run.paused, run.stations.build === 'limit'));
  let i = states.findIndex((x) => x === 'working' || x === 'waiting' || x === 'paused' || x === 'limit');
  if (i < 0) i = states.findIndex((x) => x !== 'done');
  return `build-${Math.max(i, 0)}`;
}

/** Compute the per-station state for a given run (taking paused into account) */
export function stationsOf(run: RunView): Record<string, StationState> {
  if (!run.paused) return run.stations;
  const result: Record<string, StationState> = {};
  for (const [k, v] of Object.entries(run.stations)) {
    result[k] = v === 'working' ? 'paused' : v;
  }
  return result;
}

interface TaskChipProps {
  run: RunView;
  selected: boolean;
  onClick: () => void;
}

function TaskChip({ run, selected, onClick }: TaskChipProps) {
  const sc: Record<string, string> = { working: 'var(--floor-working-label)', waiting: 'var(--floor-waiting-label)' };
  const stColor = run.paused ? 'var(--floor-text-muted)' : sc[run.stations[run.station] ?? ''] ?? 'var(--floor-text-muted)';
  const whereText = run.whereLabel;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className="floor-task-chip"
      style={{
        borderColor: selected ? run.color : 'var(--floor-border)',
        background: selected ? '#16222A' : 'var(--floor-surface)',
      }}
    >
      <span
        aria-hidden="true"
        style={{
          width: 26, height: 26, borderRadius: '50%',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: "'JetBrains Mono', ui-monospace, monospace", fontSize: 11, fontWeight: 500,
          background: run.color, color: '#0B0F13',
        }}
      >
        {run.short}
      </span>
      <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
        <span style={{ fontWeight: 600 }}>{run.title}</span>
        <span style={{ fontSize: 12, color: stColor }}>{whereText}</span>
      </span>
    </button>
  );
}

interface FloorNetworkProps {
  snap: FloorSnapshot;
  selectedSlug: string | null;
  selectedNodeId: string | null;
  onSelectRun: (slug: string, nodeId: string) => void;
  onSelectNode: (nodeId: string) => void;
}

/** Second label line under a station: runner and model for agents, `engine`, or `you` for gates. */
function subLabel(station: StationDef, snap: FloorSnapshot): string {
  if (station.kind === 'gate') return 'you';
  if (station.kind === 'engine') return 'engine';
  const w = snap.who[station.id === 'build' || station.id.startsWith('build-') ? 'build' : station.id];
  if (!w) return 'agent';
  return [w.runner, w.model].filter(Boolean).join(' · ');
}

function FloorNetwork({ snap, selectedSlug, selectedNodeId, onSelectRun, onSelectNode }: FloorNetworkProps) {
  const run = snap.runs.find((r) => r.slug === selectedSlug) ?? snap.runs[0] ?? null;
  const states = run ? stationsOf(run) : {};

  // Determine build lane positions
  const buildLaneCount = run?.lanes.length ?? 0;
  const lanePositions = buildLanePositions(buildLaneCount);
  const buildLaneYs = lanePositions.map((p) => p.y);
  const laneStates: StationState[] = (run?.lanes ?? []).slice(0, MAX_LANES).map((l) => laneState(l, run?.paused ?? false, run?.stations.build === 'limit'));
  const extraLanes = buildLaneCount > MAX_LANES ? buildLaneCount - MAX_LANES : 0;

  // Build task dots: map station id → list of tasks here
  const taskDotsMap: Record<string, Array<{ short: string; color: string; title: string }>> = {};
  for (const r of snap.runs) {
    const nodeId = r.slug === run?.slug ? nodeOfRun(r) : r.station;
    if (!taskDotsMap[nodeId]) taskDotsMap[nodeId] = [];
    taskDotsMap[nodeId].push({ short: r.short, color: r.color, title: r.title });
  }

  // Build expanded station list (non-build stations + build lanes if >1)
  const stationsToRender = STATIONS.flatMap((s) => {
    if (s.id !== 'build') return [{ ...s, laneIdx: -1 }];
    // one lane still shows its name
    if (buildLaneCount <= 1) return [{ ...s, name: run?.lanes[0]?.name ?? s.name, glyph: run?.lanes[0] ? 'B1' : s.glyph, x: 670, y: 250, laneIdx: 0 }];
    return lanePositions.map((pos, i) => ({
      ...s,
      id: `build-${i}`,
      name: run?.lanes[i]?.name ?? `Lane ${i + 1}`,
      glyph: `B${i + 1}`,
      x: pos.x, y: pos.y,
      laneIdx: i,
    }));
  });

  return (
    <section
      aria-label="Factory network"
      style={{
        borderRadius: 18, border: '1px solid var(--floor-canvas-border)',
        background: 'var(--floor-canvas-bg)', overflowX: 'auto',
      }}
    >
      {/* side margins keep the first and last station labels (120px wide) inside the canvas */}
      <div style={{ position: 'relative', minWidth: 840, margin: '0 32px', aspectRatio: '1000 / 560' }}>
        <EdgeLayer states={states} buildLaneYs={buildLaneYs} laneStates={laneStates} />

        {stationsToRender.map((s) => {
          const isLane = s.id.startsWith('build-');
          const stId = isLane ? 'build' : s.id;
          let stState: StationState = states[stId] ?? 'todo';

          // If multiple build lanes, use per-lane state
          if (isLane && run && s.laneIdx >= 0) stState = laneStates[s.laneIdx] ?? stState;

          const dots = taskDotsMap[s.id] ?? [];
          const isSelected = selectedNodeId === s.id;

          return (
            <NeuronButton
              key={s.id}
              station={s}
              state={stState}
              taskDots={dots}
              sub={subLabel(s, snap)}
              selected={isSelected}
              onClick={() => {
                if (run) onSelectRun(run.slug, s.id);
                else onSelectNode(s.id);
              }}
            />
          );
        })}

        {/* Extra build lanes indicator */}
        {extraLanes > 0 && (
          <div
            style={{
              position: 'absolute',
              left: '73%', top: '90%',
              fontSize: 11, color: 'var(--floor-text-muted)',
            }}
          >
            +{extraLanes} more
          </div>
        )}

      </div>
      {/* Legend: below the canvas, in normal flow, so it never covers a station */}
      <div className="floor-legend" aria-hidden="true">
        <span className="floor-legend-item">
          <span style={{ width: 12, height: 12, borderRadius: '50%', border: '2px solid var(--floor-working-edge)', display: 'inline-block' }} />
          agent
        </span>
        <span className="floor-legend-item">
          <span style={{ width: 12, height: 12, borderRadius: 3, border: '2px solid var(--floor-text-muted)', display: 'inline-block' }} />
          engine
        </span>
        <span className="floor-legend-item">
          <span style={{ width: 10, height: 10, transform: 'rotate(45deg)', border: '2px solid var(--floor-waiting-edge)', display: 'inline-block' }} />
          you decide
        </span>
        <span className="floor-legend-item">
          <span style={{ width: 18, borderTop: '2px dashed var(--floor-feed-active)', display: 'inline-block' }} />
          knowledge feeding agents
        </span>
      </div>
    </section>
  );
}

const ACTIVITY_STATION: Record<string, string> = {
  intake: 'intake', triage: 'triage', spec: 'spec', gate_spec: 'spec review', gherkin: 'scenarios',
  gate_gherkin: 'scenario review', build: 'build', verify: 'verify', report: 'report',
  gate_accept: 'acceptance', knowledge: 'knowledge',
};

function clock(at: string): string {
  return /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d/.test(at) ? at.slice(11, 19) : at;
}

function ActivityPanel({ snap }: { snap: FloorSnapshot }) {
  const rows: ActivityView[] = snap.activity.slice(0, 20);
  const look = (slug: string) => snap.runs.find((r) => r.slug === slug);
  return (
    <section aria-label="Factory activity" className="floor-activity">
      <div className="floor-activity-head">
        <h2>Activity across the factory</h2>
        <span style={{ fontSize: 12, color: 'var(--floor-text-muted)' }}>live</span>
      </div>
      {rows.length === 0 ? (
        <p style={{ margin: 0, fontSize: 13, color: 'var(--floor-text-muted)' }}>Nothing has happened yet.</p>
      ) : (
        <ul className="floor-activity-list">
          {rows.map((a, i) => {
            const r = look(a.run);
            return (
              <li key={`${a.at}-${i}`} className="floor-activity-row">
                <time dateTime={a.at}>{clock(a.at)}</time>
                <span className="floor-activity-task" title={r?.title ?? a.run} style={{ background: r?.color ?? '#9AA6B2' }}>
                  {r?.short ?? initials(a.run)}
                </span>
                <span className="floor-activity-st">{ACTIVITY_STATION[a.station] ?? a.station}</span>
                <span className="floor-activity-text">{a.text}</span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

interface FloorContentProps {
  snap: FloorSnapshot;
  pid: string;
  initialTaskSlug?: string;
  reload: () => void;
}

function FloorContent({ snap, pid, initialTaskSlug, reload }: FloorContentProps) {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(() => {
    if (initialTaskSlug && snap.runs.some((r) => r.slug === initialTaskSlug)) {
      return initialTaskSlug;
    }
    return defaultTaskSlug(snap);
  });
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(() => {
    const slug = initialTaskSlug && snap.runs.some((r) => r.slug === initialTaskSlug)
      ? initialTaskSlug
      : defaultTaskSlug(snap);
    const run = snap.runs.find((r) => r.slug === (slug ?? ''));
    return run ? nodeOfRun(run) : null;
  });

  useEffect(() => {
    if (initialTaskSlug && snap.runs.some((r) => r.slug === initialTaskSlug)) {
      setSelectedSlug(initialTaskSlug);
      const run = snap.runs.find((r) => r.slug === initialTaskSlug);
      if (run) setSelectedNodeId(nodeOfRun(run));
    }
  }, [initialTaskSlug, snap.runs]);

  const selectedRun = snap.runs.find((r) => r.slug === selectedSlug) ?? null;
  const selectedStates = selectedRun ? stationsOf(selectedRun) : {};

  // Resolve selected station definition (handle build-N lanes cleanly)
  const selectedStation = useMemo(() => {
    if (!selectedNodeId) return null;
    if (selectedNodeId.startsWith('build-')) {
      const idx = parseInt(selectedNodeId.slice('build-'.length), 10);
      const base = stationById('build');
      if (!base) return null;
      const lane = selectedRun?.lanes[idx];
      return {
        ...base,
        id: selectedNodeId,
        name: lane?.name ?? base.name,
        glyph: `B${idx + 1}`,
      };
    }
    return stationById(selectedNodeId) ?? null;
  }, [selectedNodeId, selectedRun]);

  const selectedLane = selectedRun && selectedNodeId?.startsWith('build-')
    ? selectedRun.lanes[parseInt(selectedNodeId.slice('build-'.length), 10)]
    : undefined;
  const selectedState: StationState = selectedLane && selectedRun
    ? laneState(selectedLane, selectedRun.paused, selectedRun.stations.build === 'limit')
    : selectedStation
    ? (selectedStates[selectedStation.id.startsWith('build') ? 'build' : selectedStation.id] ?? 'todo')
    : 'todo';

  const handleSelectRun = (slug: string, nodeId: string) => {
    setSelectedSlug(slug);
    setSelectedNodeId(nodeId);
  };

  return (
    <>
      <RoutingBanner pid={pid} problems={snap.routingProblems} onFixed={reload} />

      {snap.factoryPaused && (
        <p role="status" className="floor-paused-note">
          The factory is paused: no new agent starts until you resume it. Tasks already running finish.
        </p>
      )}

      {snap.budget?.reached && (
        <p role="status" className="floor-paused-note" data-testid="budget-banner" style={{ background: 'var(--amber-dim, #382806)', borderColor: 'var(--amber, #f59e0b)', color: 'var(--amber-bright, #fef3c7)' }}>
          Daily budget reached{snap.budget.reason ? `: ${snap.budget.reason}` : ''} · no new agent tasks start until tomorrow.
        </p>
      )}

      {/* Task switcher chips */}
      <div
        role="group"
        aria-label="Tasks on the floor"
        style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 14 }}
      >
        {snap.runs.map((r) => (
          <TaskChip
            key={r.slug}
            run={r}
            selected={r.slug === selectedSlug}
            onClick={() => handleSelectRun(r.slug, nodeOfRun(r))}
          />
        ))}
        {snap.queue.length > 0 && (
          <span style={{ fontSize: 12, color: 'var(--floor-text-muted)', marginLeft: 6 }}>
            + {snap.queue.length} queued ·{' '}
            <Link to="/tasks/new">New task</Link>
          </span>
        )}
        {snap.runs.length === 0 && snap.queue.length === 0 && (
          <span style={{ fontSize: 13, color: 'var(--floor-text-muted)' }}>No active runs.</span>
        )}
      </div>

      {/* Main layout: network + side panel */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18, alignItems: 'flex-start' }}>
        <div style={{ flex: '999 1 904px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <FloorNetwork
            snap={snap}
            selectedSlug={selectedSlug}
            selectedNodeId={selectedNodeId}
            onSelectRun={handleSelectRun}
            onSelectNode={setSelectedNodeId}
          />
          <ActivityPanel snap={snap} />
        </div>

        <SidePanel
          station={selectedStation}
          state={selectedState}
          who={snap.who}
          run={selectedRun}
          pid={pid}
          onChanged={reload}
        />
      </div>
    </>
  );
}

interface FloorScreenProps {
  pid?: string;
}

export function FloorScreen({ pid }: FloorScreenProps) {
  const route = useRoute();
  const taskSlug = route.query.get('task') ?? undefined;
  // If no pid, pick the first available project
  const projects = useResource('floor-projects', (c) => calls.projects(c), {});
  const resolvedPid = pid ?? projects.data?.items.find((p) => p.status === 'available')?.id ?? '';
  const projectName = projects.data?.items.find((p) => p.id === resolvedPid)?.name ?? resolvedPid;

  const factory = useResource(
    `factory-${resolvedPid}`,
    (c) => calls.factory(c, resolvedPid),
    {
      project: resolvedPid,
      types: FACTORY_EVENT_TYPES as unknown as readonly string[],
    },
    !!resolvedPid,
  );

  const available = projects.data?.items.filter((p) => p.status === 'available') ?? [];

  if (!resolvedPid && !projects.loading) {
    return (
      <section>
        <h1>Factory floor</h1>
        <p>No projects found. <Link to="/projects/new">Create a project</Link> to get started.</p>
      </section>
    );
  }

  return (
    <section className="floor-root">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
        <h1 style={{ margin: 0 }}>Factory floor</h1>
        {resolvedPid ? (
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '1rem', flexWrap: 'wrap' }}>
            <h2 style={{ margin: 0, fontSize: '1.25rem', color: 'var(--text-muted)' }}>
              {projectName}
            </h2>
            {available.length > 1 && (
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-muted)' }}>
                Project
                <select
                  className="floor-project-select"
                  value={resolvedPid}
                  onChange={(e) => navigate(`/projects/${enc(e.target.value)}/floor`)}
                >
                  {available.map((p) => (
                    <option key={p.id} value={p.id}>{p.name} · {p.active_runs} running</option>
                  ))}
                </select>
              </label>
            )}
            <nav aria-label="Project" style={{ display: 'inline-flex', gap: '0.75rem', fontSize: '0.9rem' }}>
              <Link to={`/projects/${enc(resolvedPid)}/repositories`}>Repositories</Link>
              <Link to={`/projects/${enc(resolvedPid)}/knowledge`}>Knowledge</Link>
              <Link to={`/projects/${enc(resolvedPid)}`}>Project home</Link>
            </nav>
          </div>
        ) : null}
      </div>
      <Loaded res={factory} unavailable>
        {(data) => {
          const snap = floorSnapshot(data);
          return (
            <FloorContent
              key={resolvedPid}
              snap={snap}
              pid={resolvedPid}
              initialTaskSlug={taskSlug}
              reload={() => void factory.reload()}
            />
          );
        }}
      </Loaded>
    </section>
  );
}
