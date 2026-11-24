// Factory Floor screen (W4)
// Route: /floor and /projects/{pid}/floor
import { useState, useMemo, useEffect, useRef } from 'react';
import { calls } from '../api/calls.ts';
import { useApp, useResource } from '../state/app.tsx';
import { floorSnapshot, laneState } from '../components/floor/adapt.ts';
import { laneLabel } from '../components/floor/layout.ts';
import { useAction, useControlsEnabled } from '../components/common.tsx';
import { RoutingBanner } from '../components/RoutingFix.tsx';
import type { FloorSnapshot, RunView, StationState } from '../components/floor/types.ts';
import { Link, enc, useRoute } from '../router.tsx';

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

/** Format time ago from ISO string */
function timeAgo(isoString?: string): string {
  if (!isoString) return 'recently';
  const diffMs = Date.now() - new Date(isoString).getTime();
  if (diffMs < 0 || isNaN(diffMs)) return 'recently';
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return `${hours} h ${remMins} min ago`;
}

/** Human-readable role in plain words */
export function plainRole(role?: string | null): string {
  if (!role) return 'Agent';
  const r = role.toLowerCase();
  if (r === 'tdd_green' || r === 'coder') return 'Coder';
  if (r === 'tdd_red' || r === 'test_writer' || r === 'test writer') return 'Test writer';
  if (r === 'tdd_refactor' || r === 'refactor' || r === 'tidy') return 'Refactor';
  if (r === 'triage' || r === 'intake') return 'Intake';
  if (r === 'specifier' || r === 'spec') return 'Spec writer';
  if (r === 'test_designer' || r === 'gherkin' || r === 'scenarios') return 'Scenario writer';
  if (r === 'verify' || r === 'checks') return 'Checks';
  if (r === 'reviewer' || r === 'review') return 'Reviewer';
  if (r === 'qa') return 'QA';
  if (r === 'knowledge') return 'Knowledge';
  return role.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Human-readable error/failure reason in plain words */
export function plainReason(errorCode?: string | null, reason?: string | null): string {
  if (reason) {
    const lower = reason.toLowerCase();
    if (lower.includes('timed out') || lower.includes('timeout')) return 'timed out';
    if (lower.includes('exit')) return 'process exited';
    if (lower.includes('schema')) return 'invalid result schema';
    return reason;
  }
  if (errorCode === 'E_TIMEOUT') return 'timed out';
  if (errorCode === 'E_EXIT') return 'process exited';
  if (errorCode === 'E_RESULT_SCHEMA') return 'invalid result schema';
  return errorCode ? errorCode.toLowerCase().replace(/^e_/, '') : 'unexpected error';
}

/** Clean activity text: no hashes, rewrite internal globs */
export function cleanActivityText(text: string): string {
  let cleaned = text;
  cleaned = cleaned.replace(/checking write scope\s+[^\s,;)]+/gi, 'checking files');
  cleaned = cleaned.replace(/write scope\s+[^\s,;)]+/gi, 'assigned files');
  cleaned = cleaned.replace(/\s*[·•-]?\s*sha256\s+[0-9a-fA-F.]+/gi, '');
  cleaned = cleaned.replace(/\s*sha256\s+[0-9a-fA-F.]+/gi, '');
  cleaned = cleaned.replace(/\s*[·•-]\s*$/g, '').trim();
  return cleaned;
}

interface LaneNodeProps {
  id: string;
  name: string;
  xPercent: number;
  yPx: number;
  state: 'done' | 'asking' | 'working' | 'waiting';
  label: string;
  mark: string;
  selected: boolean;
  onSelect: () => void;
}

function LaneNode({ name, xPercent, yPx, state, label, mark, selected, onSelect }: LaneNodeProps) {
  const glowStyle = useMemo(() => {
    const base = {
      position: 'absolute' as const,
      left: `calc(${xPercent}% - 19px)`,
      top: `${yPx - 19}px`,
      width: 38,
      height: 38,
      borderRadius: '50%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: 'pointer',
      padding: 0,
      font: 'inherit',
      fontWeight: 700,
      fontSize: 15,
      transition: 'all 0.15s ease',
      outline: selected ? '3px solid #FFFFFF' : 'none',
      outlineOffset: selected ? 3 : 0,
      zIndex: selected ? 2 : 1,
    };
    if (state === 'done') {
      return {
        ...base,
        background: '#0F2F2B',
        border: '2px solid #2BB3A3',
        color: '#5EEAD4',
        boxShadow: '0 0 18px rgba(45,212,191,0.35)',
      };
    }
    if (state === 'asking') {
      return {
        ...base,
        background: '#3A2508',
        border: '2px solid #F59E0B',
        color: '#FCD34D',
        animation: 'askpulse 1.6s ease-in-out infinite',
      };
    }
    if (state === 'working') {
      return {
        ...base,
        background: '#0D2D3E',
        border: '2px solid #38BDF8',
        color: '#7DD3FC',
        boxShadow: '0 0 18px rgba(56,189,248,0.35)',
      };
    }
    return {
      ...base,
      background: '#161C1B',
      border: '2px solid #34403E',
      color: '#7C8A87',
    };
  }, [xPercent, yPx, state, selected]);

  return (
    <button
      type="button"
      aria-label={`${name}: ${label}, ${state}`}
      onClick={onSelect}
      style={glowStyle}
    >
      {mark}
    </button>
  );
}

interface StationButtonProps {
  id: string;
  name: string;
  subLabel: string;
  xPercent: number;
  yPx: number;
  state: 'done' | 'asking' | 'working' | 'waiting';
  selected: boolean;
  onSelect: () => void;
  icon: React.ReactNode;
}

function StationButton({ name, subLabel, xPercent, yPx, state, selected, onSelect, icon }: StationButtonProps) {
  const glowStyle = useMemo(() => {
    const base = {
      position: 'absolute' as const,
      left: `calc(${xPercent}% - 30px)`,
      top: `${yPx - 30}px`,
      width: 60,
      height: 60,
      borderRadius: 18,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: 'pointer',
      padding: 0,
      outline: selected ? '3px solid #FFFFFF' : 'none',
      outlineOffset: selected ? 3 : 0,
      zIndex: selected ? 2 : 1,
      transition: 'all 0.15s ease',
    };
    if (state === 'done') {
      return {
        ...base,
        background: '#0F2F2B',
        border: '2px solid #2BB3A3',
        color: '#5EEAD4',
        boxShadow: '0 0 18px rgba(45,212,191,0.35)',
      };
    }
    if (state === 'asking') {
      return {
        ...base,
        background: '#3A2508',
        border: '2px solid #F59E0B',
        color: '#FCD34D',
        animation: 'askpulse 1.6s ease-in-out infinite',
      };
    }
    if (state === 'working') {
      return {
        ...base,
        background: '#0D2D3E',
        border: '2px solid #38BDF8',
        color: '#7DD3FC',
        boxShadow: '0 0 18px rgba(56,189,248,0.35)',
      };
    }
    return {
      ...base,
      background: '#161C1B',
      border: '2px solid #34403E',
      color: '#7C8A87',
    };
  }, [xPercent, yPx, state, selected]);

  return (
    <>
      <button
        type="button"
        aria-label={`${name}: ${state}`}
        onClick={onSelect}
        style={glowStyle}
      >
        {icon}
      </button>
      <div
        style={{
          position: 'absolute',
          left: `calc(${xPercent}% - 60px)`,
          top: yPx + 40,
          width: 120,
          textAlign: 'center',
          pointerEvents: 'none',
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, color: '#E6F2EF' }}>{name}</div>
        <div style={{ fontSize: 12, color: '#9FB3AF' }}>{subLabel}</div>
      </div>
    </>
  );
}

export function FloorScreen({ pid }: { pid?: string }) {
  const app = useApp();
  const route = useRoute();
  const taskSlugFromQuery = route.query.get('task') ?? undefined;

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

  const snap = useMemo(() => (factory.data ? floorSnapshot(factory.data) : null), [factory.data]);

  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string>('lane-0');
  const [copiedAttach, setCopiedAttach] = useState(false);
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Decision card state
  const [decisionSentMsg, setDecisionSentMsg] = useState<string | null>(null);
  const [showOtherTextarea, setShowOtherTextarea] = useState(false);
  const [otherText, setOtherText] = useState('');
  const [decisionPending, setDecisionPending] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  const action = useAction();
  const controlsEnabled = useControlsEnabled();

  // Set default run
  useEffect(() => {
    if (!snap) return;
    if (taskSlugFromQuery && snap.runs.some((r) => r.slug === taskSlugFromQuery)) {
      setSelectedSlug(taskSlugFromQuery);
    } else if (!selectedSlug || !snap.runs.some((r) => r.slug === selectedSlug)) {
      setSelectedSlug(defaultTaskSlug(snap));
    }
  }, [snap, taskSlugFromQuery, selectedSlug]);

  const currentRun = useMemo(() => {
    if (!snap) return null;
    return snap.runs.find((r) => r.slug === selectedSlug) ?? snap.runs[0] ?? null;
  }, [snap, selectedSlug]);

  const wf = useResource(
    `floor-wf-${resolvedPid}-${currentRun?.slug}`,
    (c) => (currentRun ? calls.workflow(c, currentRun.slug, resolvedPid) : Promise.resolve(null)),
    { project: resolvedPid, run: currentRun?.slug },
    !!(resolvedPid && currentRun?.slug),
  );

  const ver = useResource(
    `floor-ver-${resolvedPid}-${currentRun?.slug}`,
    (c) => (currentRun ? calls.verification(c, currentRun.slug, resolvedPid) : Promise.resolve(null)),
    { project: resolvedPid, run: currentRun?.slug },
    !!(resolvedPid && currentRun?.slug),
  );

  const changes = useResource(
    `floor-ch-${resolvedPid}-${currentRun?.slug}`,
    (c) => (currentRun ? calls.changes(c, currentRun.slug, resolvedPid) : Promise.resolve(null)),
    { project: resolvedPid, run: currentRun?.slug },
    !!(resolvedPid && currentRun?.slug),
  );

  const rep = useResource(
    `floor-rep-${resolvedPid}-${currentRun?.slug}`,
    async (c) => {
      if (!currentRun) return null;
      try {
        return await calls.report(c, currentRun.slug, resolvedPid);
      } catch {
        return null;
      }
    },
    { project: resolvedPid, run: currentRun?.slug },
    !!(resolvedPid && currentRun?.slug),
  );

  // Set default node when run changes
  useEffect(() => {
    if (currentRun) {
      setSelectedNodeId(nodeOfRun(currentRun));
    }
  }, [currentRun?.slug]);

  // Cleanup copy timeout
  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    };
  }, []);

  const handleCopyAttach = () => {
    if (!currentRun) return;
    const text = `sentinel attach ${currentRun.slug}`;
    void navigator.clipboard.writeText(text);
    setCopiedAttach(true);
    if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current);
    copyTimeoutRef.current = setTimeout(() => setCopiedAttach(false), 3000);
  };

  const handleTogglePause = async () => {
    if (!currentRun) return;
    if (currentRun.paused) {
      await action.run(
        () => calls.unpause(app.client, currentRun.slug, resolvedPid),
        () => 'Run resumed',
        { onSettled: () => void factory.reload() },
      );
    } else {
      await action.run(
        () => calls.pause(app.client, currentRun.slug, resolvedPid),
        () => 'Run paused',
        { onSettled: () => void factory.reload() },
      );
    }
  };

  // Build lanes
  const lanes = useMemo(() => {
    if (!currentRun || currentRun.lanes.length === 0) {
      return [
        {
          name: 'Main build',
          red: 'done' as const,
          green: 'done' as const,
          refactor: 'done' as const,
          state: 'done' as const,
        },
      ];
    }
    return currentRun.lanes.slice(0, 4).map((l) => ({
      name: laneLabel(l.name),
      red: l.red as 'done' | 'working' | 'waiting' | 'todo',
      green: l.green as 'done' | 'working' | 'waiting' | 'todo',
      refactor: l.refactor as 'done' | 'working' | 'waiting' | 'todo',
      state: l.state,
    }));
  }, [currentRun]);

  const doneLaneCount = useMemo(() => {
    return lanes.filter((l) => l.refactor === 'done' || l.state === 'DONE').length;
  }, [lanes]);

  // Calculate coordinates for lanes
  const laneYPositions = useMemo(() => {
    const count = Math.max(lanes.length, 1);
    if (count === 1) return [200];
    if (count === 2) return [130, 270];
    if (count === 3) return [100, 200, 300];
    return [70, 160, 250, 340];
  }, [lanes.length]);

  // Determine station states
  const intakeState = useMemo<'done' | 'asking' | 'working' | 'waiting'>(() => {
    if (!currentRun) return 'waiting';
    const s = currentRun.stations.triage ?? currentRun.stations.intake;
    if (s === 'done') return 'done';
    if (s === 'working') return 'working';
    if (s === 'waiting') return 'asking';
    return 'waiting';
  }, [currentRun]);

  const specState = useMemo<'done' | 'asking' | 'working' | 'waiting'>(() => {
    if (!currentRun) return 'waiting';
    const s = currentRun.stations.gate_spec ?? currentRun.stations.spec;
    if (s === 'done') return 'done';
    if (s === 'working') return 'working';
    if (s === 'waiting') return 'asking';
    return 'waiting';
  }, [currentRun]);

  const scenState = useMemo<'done' | 'asking' | 'working' | 'waiting'>(() => {
    if (!currentRun) return 'waiting';
    const s = currentRun.stations.gate_gherkin ?? currentRun.stations.gherkin;
    if (s === 'done') return 'done';
    if (s === 'working') return 'working';
    if (s === 'waiting') return 'asking';
    return 'waiting';
  }, [currentRun]);

  const checksState = useMemo<'done' | 'asking' | 'working' | 'waiting'>(() => {
    if (!currentRun) return 'waiting';
    const s = currentRun.stations.verify;
    if (s === 'done') return 'done';
    if (s === 'working') return 'working';
    if (s === 'waiting') return 'asking';
    return 'waiting';
  }, [currentRun]);

  const reviewState = useMemo<'done' | 'asking' | 'working' | 'waiting'>(() => {
    if (!currentRun) return 'waiting';
    const s = currentRun.stations.gate_accept ?? currentRun.stations.report;
    if (s === 'done') return 'done';
    if (s === 'working') return 'working';
    if (s === 'waiting') return 'asking';
    return 'waiting';
  }, [currentRun]);

  const doneState = useMemo<'done' | 'asking' | 'working' | 'waiting'>(() => {
    if (!currentRun) return 'waiting';
    if (currentRun.state === 'COMPLETED') return 'done';
    return 'waiting';
  }, [currentRun]);

  // Decision Card status
  const isParked = currentRun?.attention !== null && currentRun?.attention !== undefined;
  const isNeedsHuman = currentRun?.state === 'NEEDS_HUMAN' || currentRun?.attention?.kind === 'needs_human';
  const parkReason = currentRun?.attention?.reason ?? '';

  // Parse questions from park reason (separated by ;)
  const questionsList = useMemo(() => {
    if (!parkReason) return [];
    return parkReason.split(';').map((q) => q.trim()).filter(Boolean);
  }, [parkReason]);

  // Is tests already pass situation
  const isTestsAlreadyPass = useMemo(() => {
    const text = (parkReason + ' ' + (currentRun?.attention?.reason ?? '')).toLowerCase();
    return text.includes('already pass') || text.includes('tests pass') || text.includes('refusal');
  }, [parkReason, currentRun?.attention?.reason]);

  // Find relevant task ID for red stage / current action
  const parkedTaskId = useMemo(() => {
    if (!currentRun) return undefined;
    const allTasks = Object.values(currentRun.station_tasks ?? {}).flat();
    const targetTask = allTasks.find((t) => t.role === 'tdd_red' || t.state === 'BLOCKED' || t.state === 'FAILED');
    if (targetTask) return targetTask.id;
    const currentAgent = Object.values(currentRun.agents ?? {}).flat()[0];
    return currentAgent?.task ?? 't-red';
  }, [currentRun]);

  // Handle Decision Actions
  const handleControlAction = async (actionKind: string, comment: string, taskId?: string) => {
    if (!currentRun) return;
    const resolvedTaskId = taskId ?? (actionKind === 'resume' ? undefined : parkedTaskId);
    setDecisionPending(true);
    setDecisionError(null);
    try {
      await calls.control(app.client, currentRun.slug, resolvedPid, {
        action: actionKind,
        comment: comment || 'Action submitted from dashboard',
        task_id: resolvedTaskId,
      });
      if (actionKind === 'already_implemented') {
        setDecisionSentMsg('Sent. The orchestrator accepted the part as already implemented; the factory moves on to Checks.');
      } else if (actionKind === 'back_to_red') {
        setDecisionSentMsg('Sent. The orchestrator asked the test writer to rewrite the tests; the part starts again from "Test first".');
      } else if (actionKind === 'retry') {
        setDecisionSentMsg('Sent. The orchestrator queued a retry for the failed task.');
      } else {
        setDecisionSentMsg(`Sent. The orchestrator received your decision: "${comment}".`);
      }
      setShowOtherTextarea(false);
      setOtherText('');
      void factory.reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setDecisionError(msg);
    } finally {
      setDecisionPending(false);
    }
  };

  // Selected station detail
  const selectedDetail = useMemo(() => {
    if (!currentRun || !selectedNodeId) {
      return {
        name: 'Station details',
        who: 'Ready',
        doing: 'No work recorded yet.',
        steps: [] as string[],
        files: [] as string[],
      };
    }

    // Determine station key from selectedNodeId
    let stationKey = selectedNodeId;
    let laneName: string | null = null;
    let isLane = false;
    if (selectedNodeId.startsWith('lane-') || selectedNodeId.startsWith('build-')) {
      isLane = true;
      stationKey = 'build';
      const idx = parseInt(selectedNodeId.replace(/^(lane|build)-/, ''), 10) || 0;
      const lane = lanes[idx] ?? lanes[0];
      laneName = lane?.name ?? 'Build lane';
    }

    const stationNames: Record<string, string> = {
      intake: 'Intake',
      triage: 'Intake',
      spec: 'Specification',
      gate_spec: 'Specification review',
      gherkin: 'Scenarios',
      gate_gherkin: 'Scenario review',
      build: laneName ?? 'Build',
      verify: 'Checks',
      report: 'Review & QA',
      gate_accept: 'Review & QA',
      done: 'Done',
      knowledge: 'Knowledge',
    };
    const name = stationNames[selectedNodeId] ?? stationNames[stationKey] ?? selectedNodeId;

    // Collect all tasks for the run
    const allWfNodes = wf.data?.nodes ?? [];
    const stationTasksFromRun = currentRun.station_tasks?.[stationKey] ?? [];

    let matchedTasks = allWfNodes.filter((n) => {
      if (stationKey === 'build') return ['tdd_red', 'tdd_green', 'tdd_refactor', 'coder'].includes(n.role);
      if (stationKey === 'spec' || stationKey === 'gate_spec') return ['specifier', 'spec'].includes(n.role);
      if (stationKey === 'gherkin' || stationKey === 'gate_gherkin') return ['test_designer', 'gherkin'].includes(n.role);
      if (stationKey === 'intake' || stationKey === 'triage') return ['triage', 'intake'].includes(n.role);
      if (stationKey === 'verify') return ['verify', 'checks'].includes(n.role);
      if (stationKey === 'report' || stationKey === 'gate_accept') return ['reviewer', 'qa', 'report'].includes(n.role);
      if (stationKey === 'knowledge') return ['knowledge'].includes(n.role);
      return n.role === stationKey;
    });

    if (matchedTasks.length === 0 && stationTasksFromRun.length > 0) {
      matchedTasks = stationTasksFromRun.map((t) => ({
        id: t.id,
        role: t.role,
        state: t.state,
        repo: null,
        adapter: '',
        provider: null,
        model: null,
        attempt: 1,
        retry_of: null,
        error_code: (t as { error_code?: string }).error_code ?? null,
        started_at: t.startedAt,
        finished_at: t.finishedAt,
        seconds: null,
        reason: (t as { reason?: string }).reason ?? null,
        changed_files: (t as { changed_files?: string[] }).changed_files ?? null,
      }));
    }

    // Role in plain words
    const primaryTask = matchedTasks[matchedTasks.length - 1];
    const who = primaryTask
      ? plainRole(primaryTask.role)
      : stationKey === 'spec'
      ? 'Spec writer'
      : stationKey === 'gherkin'
      ? 'Scenario writer'
      : stationKey === 'build'
      ? 'Test writer & Coder'
      : stationKey === 'verify'
      ? 'Engine'
      : stationKey === 'report'
      ? 'Reviewer & QA agent'
      : 'Engine';

    // Doing: task's state and reason in plain words
    let doing = '';
    if (primaryTask) {
      const stateLower = primaryTask.state.toLowerCase();
      const reasonPart = (primaryTask as { reason?: string }).reason || primaryTask.error_code ? ` (${plainReason(primaryTask.error_code, (primaryTask as { reason?: string }).reason)})` : '';
      if (isNeedsHuman && (stationKey === currentRun.station || isLane)) {
        doing = `Waiting on your decision${parkReason ? `: ${parkReason}` : ''}.`;
      } else if (primaryTask.state === 'RUNNING') {
        doing = `Task is running${reasonPart}.`;
      } else if (primaryTask.state === 'COMPLETED') {
        doing = `Task finished successfully.`;
      } else if (primaryTask.state === 'FAILED') {
        doing = `Task failed${reasonPart}.`;
      } else if (primaryTask.state === 'BLOCKED') {
        doing = `Task blocked${reasonPart}.`;
      } else {
        doing = `Task ${stateLower}${reasonPart}.`;
      }
    } else if (isNeedsHuman && (stationKey === currentRun.station || isLane)) {
      doing = `Waiting on your decision${parkReason ? `: ${parkReason}` : ''}.`;
    }

    // Recent progress events in plain words
    const stEvents = (snap?.activity ?? []).filter((a) => {
      const runMatch = !a.run || a.run === currentRun.slug;
      const stationMatch = a.station === stationKey || a.station === selectedNodeId || (stationKey === 'build' && a.station === 'build');
      return runMatch && stationMatch;
    });

    const steps = stEvents.slice(0, 5).map((a) => cleanActivityText(a.text)).filter(Boolean);

    if (steps.length === 0 && primaryTask) {
      steps.push(`Task: ${primaryTask.state.toLowerCase()}`);
    }

    // Changed files (from task changed_files, changes resource, or report)
    const taskChangedFiles: string[] = (primaryTask as { changed_files?: string[] })?.changed_files ?? [];
    let files = Array.isArray(taskChangedFiles) ? [...taskChangedFiles] : [];

    if (files.length === 0 && changes.data?.repos) {
      const relevantFiles = changes.data.repos.flatMap((r) =>
        r.files.filter((f) => !primaryTask || f.tasks?.includes(primaryTask.id)).map((f) => f.path)
      );
      if (relevantFiles.length > 0) {
        files = relevantFiles;
      } else if (stationKey === 'build' || stationKey === 'report') {
        files = changes.data.repos.flatMap((r) => r.files.map((f) => f.path));
      }
    }

    if (files.length === 0 && rep.data?.report) {
      const repFiles = (rep.data.report as { changed_files?: unknown })?.changed_files;
      if (Array.isArray(repFiles)) {
        files = repFiles.filter((f): f is string => typeof f === 'string');
      }
    }

    if (!primaryTask && steps.length === 0 && files.length === 0 && !doing) {
      doing = 'No work recorded yet.';
    }

    return {
      name,
      who,
      doing: doing || 'No work recorded yet.',
      steps,
      files,
    };
  }, [selectedNodeId, currentRun, lanes, isNeedsHuman, parkReason, snap, wf.data, changes.data, rep.data]);

  // Handled for you list derived ONLY from real run events/data
  const handledList = useMemo(() => {
    if (!currentRun) return [];
    const items: string[] = [];
    const allTasks: Array<{ id: string; role: string; state: string; error_code?: string | null; reason?: string | null; retry_of?: string | null }> = [];

    if (wf.data?.nodes) {
      for (const n of wf.data.nodes) {
        allTasks.push({
          id: n.id,
          role: n.role,
          state: n.state,
          error_code: n.error_code,
          reason: (n as { reason?: string }).reason,
          retry_of: n.retry_of,
        });
      }
    }
    if (currentRun.station_tasks) {
      for (const tasks of Object.values(currentRun.station_tasks)) {
        for (const t of tasks) {
          if (!allTasks.some((x) => x.id === t.id)) {
            allTasks.push({
              id: t.id,
              role: t.role,
              state: t.state,
              error_code: (t as { error_code?: string }).error_code,
              reason: (t as { reason?: string }).reason,
              retry_of: (t as { retry_of?: string }).retry_of,
            });
          }
        }
      }
    }

    // 1. A task that FAILED with E_TIMEOUT / E_EXIT / E_RESULT_SCHEMA followed by a retry task (retry_of) that COMPLETED
    for (const task of allTasks) {
      const err = task.error_code ?? '';
      const rsn = task.reason ?? '';
      const isExpectedError =
        ['E_TIMEOUT', 'E_EXIT', 'E_RESULT_SCHEMA'].includes(err) ||
        /timeout|timed out/i.test(rsn) ||
        /exit/i.test(rsn) ||
        /schema/i.test(rsn);

      if (task.state === 'FAILED' && isExpectedError) {
        const retry = allTasks.find((t) => t.retry_of === task.id && t.state === 'COMPLETED');
        if (retry) {
          const roleText = plainRole(task.role);
          const reasonText = plainReason(task.error_code, task.reason);
          items.push(`${roleText} failed (${reasonText}) and was retried: it worked`);
        }
      }
    }

    // 2. A verification round that failed then a later one passed
    const evidenceRows = ver.data?.rows ?? [];
    if (evidenceRows.length > 0) {
      const rounds = new Map<number, boolean>();
      for (const e of evidenceRows) {
        const rNum = (e as unknown as { round?: number }).round ?? 1;
        const passed = (e.failed === 0 || e.failed === null) && e.exit_code === 0 && (e as unknown as { verdict?: string }).verdict !== 'failed';
        if (!rounds.has(rNum)) rounds.set(rNum, true);
        if (!passed) rounds.set(rNum, false);
      }
      const sortedRounds = Array.from(rounds.entries()).sort((a, b) => a[0] - b[0]);
      const hasFailedRound = sortedRounds.some(([, ok]) => !ok);
      const latestPassed = sortedRounds.length > 0 && sortedRounds[sortedRounds.length - 1][1];
      if (hasFailedRound && (latestPassed || ver.data?.acceptance?.computed === 'accepted')) {
        items.push('Checks failed once and passed on the next round');
      }
    }

    return items;
  }, [currentRun, wf.data, ver.data]);

  if (!resolvedPid && !projects.loading) {
    return (
      <section style={{ padding: 24 }}>
        <h1>Factory floor</h1>
        <p>No projects found. <Link to="/projects/new">Create a project</Link> to get started.</p>
      </section>
    );
  }

  const markOf = (st: string) => (st === 'done' ? '✓' : st === 'asking' ? '?' : st === 'working' ? '•' : '');
  const stateOf = (st: string): 'done' | 'asking' | 'working' | 'waiting' =>
    st === 'done' || st === 'asking' || st === 'working' ? st : 'waiting';

  return (
    <div style={{ minHeight: '100%', display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Routing banner if needed */}
      {snap?.routingProblems && (
        <RoutingBanner pid={resolvedPid} problems={snap.routingProblems} onFixed={() => void factory.reload()} />
      )}

      {/* Task header section */}
      <section
        aria-label="Task"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: 16,
          justifyContent: 'space-between',
        }}
      >
        <div style={{ flex: '1 1 420px', minWidth: 0 }}>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 4 }}>
            Task · {currentRun?.slug ?? projectName} · started {timeAgo(currentRun?.createdAt)}
          </div>
          <h1 style={{ margin: 0, fontSize: 24, lineHeight: 1.3, fontWeight: 700, color: 'var(--text)' }}>
            {currentRun?.title ?? 'No active task on the floor'}
          </h1>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {currentRun && (
            <>
              <button
                type="button"
                onClick={handleCopyAttach}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: 14,
                  padding: '10px 14px',
                  border: '1px solid var(--border)',
                  background: 'var(--surface)',
                  borderRadius: 8,
                  color: 'var(--text)',
                  cursor: 'pointer',
                  fontWeight: 500,
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M4 17l6-6-6-6"></path>
                  <path d="M12 19h8"></path>
                </svg>
                {copiedAttach ? `Copied: sentinel attach ${currentRun.slug}` : 'Continue in terminal'}
              </button>

              <button
                type="button"
                disabled={!controlsEnabled || action.pending}
                onClick={handleTogglePause}
                style={{
                  fontSize: 14,
                  padding: '10px 14px',
                  border: '1px solid var(--border)',
                  background: 'var(--surface)',
                  borderRadius: 8,
                  color: 'var(--text)',
                  cursor: 'pointer',
                  fontWeight: 500,
                }}
              >
                {currentRun.paused ? 'Resume this task' : 'Pause this task'}
              </button>
            </>
          )}

          {/* Project switch & pause factory */}
          {snap?.factoryPaused && (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                fontSize: 14,
                color: '#9A4D06',
                background: '#FDF0D9',
                padding: '8px 12px',
                borderRadius: 999,
              }}
            >
              Factory paused
            </span>
          )}
        </div>
      </section>

      {/* Factory Floor Dark Neuron Graph Canvas */}
      <section
        aria-label="Factory floor"
        style={{
          background: 'radial-gradient(ellipse at 50% 40%, #12302C 0%, #0B1513 70%)',
          borderRadius: 16,
          padding: '18px 20px 14px',
          overflowX: 'auto',
          color: '#E6F2EF',
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 12, marginBottom: 8 }}>
          <h1 style={{ fontWeight: 600, fontSize: 15, margin: 0 }}>Factory floor</h1>
          <span style={{ fontSize: 13, color: '#9FB3AF' }}>
            Click a node to see its work · {doneLaneCount} of {lanes.length} build parts done
          </span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 14, fontSize: 12, color: '#9FB3AF' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#2DD4BF' }}></span>Done
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#F59E0B' }}></span>Needs a decision
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#4B5A57' }}></span>Waiting
            </span>
          </span>
        </div>

        <div style={{ position: 'relative', height: 400, minWidth: 1040 }}>
          {/* SVG Connection Paths */}
          <svg
            viewBox="0 0 1000 400"
            preserveAspectRatio="none"
            aria-hidden="true"
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', overflow: 'visible' }}
          >
            <g fill="none" strokeLinecap="round">
              {/* Intake -> Spec */}
              <path
                d="M50 200 L150 200"
                stroke={intakeState === 'done' ? '#2BB3A3' : '#34403E'}
                strokeWidth="2.5"
                vectorEffect="non-scaling-stroke"
              />
              {/* Spec -> Scenarios */}
              <path
                d="M150 200 L250 200"
                stroke={specState === 'done' ? '#2BB3A3' : '#34403E'}
                strokeWidth="2.5"
                vectorEffect="non-scaling-stroke"
              />

              {/* Scenarios branching to each lane */}
              {laneYPositions.map((y, idx) => {
                const lane = lanes[idx];
                const isLaneDone = lane?.refactor === 'done';
                const isLaneAsking = lane?.red === 'waiting' || (idx === lanes.length - 1 && isNeedsHuman);
                const strokeColor = isLaneDone ? '#2BB3A3' : isLaneAsking ? '#F59E0B' : '#34403E';
                return (
                  <g key={`lane-paths-${idx}`}>
                    <path
                      d={`M250 200 C 330 200 340 ${y} 420 ${y}`}
                      stroke={strokeColor}
                      strokeWidth="2"
                      strokeDasharray={isLaneAsking ? '6 6' : undefined}
                      vectorEffect="non-scaling-stroke"
                    />
                    <path
                      d={`M420 ${y} L520 ${y}`}
                      stroke={lane?.green === 'done' ? '#2BB3A3' : strokeColor}
                      strokeWidth="2"
                      vectorEffect="non-scaling-stroke"
                    />
                    <path
                      d={`M520 ${y} L620 ${y}`}
                      stroke={isLaneDone ? '#2BB3A3' : '#34403E'}
                      strokeWidth="2"
                      vectorEffect="non-scaling-stroke"
                    />
                    <path
                      d={`M620 ${y} C 690 ${y} 690 200 760 200`}
                      stroke={isLaneDone ? '#2F6F67' : '#34403E'}
                      strokeWidth="2"
                      vectorEffect="non-scaling-stroke"
                    />
                  </g>
                );
              })}

              {/* Checks -> Review */}
              <path
                d="M760 200 L860 200"
                stroke={checksState === 'done' ? '#2BB3A3' : '#34403E'}
                strokeWidth="2"
                vectorEffect="non-scaling-stroke"
              />
              {/* Review -> Done */}
              <path
                d="M860 200 L950 200"
                stroke={reviewState === 'done' ? '#2BB3A3' : '#34403E'}
                strokeWidth="2"
                vectorEffect="non-scaling-stroke"
              />
            </g>
          </svg>

          {/* Intake button */}
          <StationButton
            id="intake"
            name="Intake"
            subLabel={`tier ${currentRun?.tier ?? 3}, 1 repo`}
            xPercent={5}
            yPx={200}
            state={intakeState}
            selected={selectedNodeId === 'intake' || selectedNodeId === 'triage'}
            onSelect={() => setSelectedNodeId('intake')}
            icon={
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M4 13l2.5-7h11L20 13"></path>
                <path d="M4 13v5h16v-5h-5l-1.5 2h-3L9 13z"></path>
              </svg>
            }
          />

          {/* Specification button */}
          <StationButton
            id="spec"
            name="Specification"
            subLabel={specState === 'done' ? 'you approved v1' : 'functional spec'}
            xPercent={15}
            yPx={200}
            state={specState}
            selected={selectedNodeId === 'spec' || selectedNodeId === 'gate_spec'}
            onSelect={() => setSelectedNodeId('spec')}
            icon={
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                <path d="M14 3v6h6"></path>
                <path d="M8 13h8M8 17h6"></path>
              </svg>
            }
          />

          {/* Scenarios button */}
          <StationButton
            id="gherkin"
            name="Scenarios"
            subLabel={scenState === 'done' ? 'you approved v2' : 'Given/When/Then'}
            xPercent={25}
            yPx={200}
            state={scenState}
            selected={selectedNodeId === 'gherkin' || selectedNodeId === 'gate_gherkin'}
            onSelect={() => setSelectedNodeId('gherkin')}
            icon={
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M9 6h11M9 12h11M9 18h11"></path>
                <path d="M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2"></path>
              </svg>
            }
          />

          {/* Parallel build lane nodes */}
          {lanes.map((lane, idx) => {
            const y = laneYPositions[idx];
            const isLastLaneAsking = idx === lanes.length - 1 && isNeedsHuman;
            const rState = isLastLaneAsking ? 'asking' : stateOf(lane.red);
            const gState = isLastLaneAsking ? 'waiting' : stateOf(lane.green);
            const fState = isLastLaneAsking ? 'waiting' : stateOf(lane.refactor);

            return (
              <div key={`lane-group-${idx}`}>
                <div
                  style={{
                    position: 'absolute',
                    left: 'calc(42% - 19px)',
                    top: `${y - 44}px`,
                    fontSize: 12,
                    color: isLastLaneAsking ? '#FCD34D' : '#B8CBC7',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {lane.name}
                </div>
                <LaneNode
                  id={`lane-${idx}-test`}
                  name={lane.name}
                  xPercent={42}
                  yPx={y}
                  state={rState}
                  label="test first"
                  mark={markOf(rState)}
                  selected={selectedNodeId === `lane-${idx}` || selectedNodeId === `build-${idx}`}
                  onSelect={() => setSelectedNodeId(`lane-${idx}`)}
                />
                <LaneNode
                  id={`lane-${idx}-pass`}
                  name={lane.name}
                  xPercent={52}
                  yPx={y}
                  state={gState}
                  label="make it pass"
                  mark={markOf(gState)}
                  selected={selectedNodeId === `lane-${idx}` || selectedNodeId === `build-${idx}`}
                  onSelect={() => setSelectedNodeId(`lane-${idx}`)}
                />
                <LaneNode
                  id={`lane-${idx}-tidy`}
                  name={lane.name}
                  xPercent={62}
                  yPx={y}
                  state={fState}
                  label="tidy"
                  mark={markOf(fState)}
                  selected={selectedNodeId === `lane-${idx}` || selectedNodeId === `build-${idx}`}
                  onSelect={() => setSelectedNodeId(`lane-${idx}`)}
                />
              </div>
            );
          })}

          {/* Build lane column headers */}
          <div style={{ position: 'absolute', left: 'calc(42% - 30px)', top: 374, width: 60, textAlign: 'center', fontSize: 11, color: '#9FB3AF' }}>Test first</div>
          <div style={{ position: 'absolute', left: 'calc(52% - 40px)', top: 374, width: 80, textAlign: 'center', fontSize: 11, color: '#9FB3AF' }}>Make it pass</div>
          <div style={{ position: 'absolute', left: 'calc(62% - 30px)', top: 374, width: 60, textAlign: 'center', fontSize: 11, color: '#9FB3AF' }}>Tidy</div>

          {/* Checks button */}
          <StationButton
            id="verify"
            name="Checks"
            subLabel="full tests, build"
            xPercent={76}
            yPx={200}
            state={checksState}
            selected={selectedNodeId === 'verify'}
            onSelect={() => setSelectedNodeId('verify')}
            icon={
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7l8-4z"></path>
                <path d="M9 12l2 2 4-4"></path>
              </svg>
            }
          />

          {/* Review & QA button */}
          <StationButton
            id="report"
            name="Review & QA"
            subLabel="code review, e2e"
            xPercent={86}
            yPx={200}
            state={reviewState}
            selected={selectedNodeId === 'report' || selectedNodeId === 'gate_accept'}
            onSelect={() => setSelectedNodeId('report')}
            icon={
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"></path>
                <circle cx="12" cy="12" r="3"></circle>
              </svg>
            }
          />

          {/* Done button */}
          <StationButton
            id="done"
            name="Done"
            subLabel="report"
            xPercent={95}
            yPx={200}
            state={doneState}
            selected={selectedNodeId === 'done'}
            onSelect={() => setSelectedNodeId('done')}
            icon={
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M5 21V4"></path>
                <path d="M5 4h11l-2 4 2 4H5"></path>
              </svg>
            }
          />
        </div>
      </section>

      {/* Below the floor: Decision card (Left) & Station details (Right) */}
      <section aria-label="Below the floor" style={{ display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'flex-start' }}>
        {/* Left card: Decision Card */}
        <div
          data-testid="decision-card"
          style={{
            flex: '3 1 560px',
            minWidth: 0,
            background: 'var(--surface)',
            border: isParked || isNeedsHuman ? '1px solid var(--warn)' : '1px solid var(--border)',
            borderRadius: 14,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              background: isParked || isNeedsHuman ? 'var(--warn-bg, #FDF5E6)' : 'var(--surface-alt)',
              padding: '14px 20px',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              borderBottom: '1px solid var(--border)',
            }}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={isParked || isNeedsHuman ? '#9A4D06' : '#0F766E'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="9"></circle>
              <path d="M12 8v5"></path>
              <path d="M12 16h.01"></path>
            </svg>
            <span style={{ fontWeight: 600, color: isParked || isNeedsHuman ? 'var(--on-warn, #7A3D05)' : 'var(--text)' }}>
              {isParked || isNeedsHuman ? 'The orchestrator needs your decision' : 'Orchestrator status'}
            </span>
            <span style={{ marginLeft: 'auto', fontSize: 13, color: isParked || isNeedsHuman ? 'var(--on-warn, #7A3D05)' : 'var(--text-muted)' }}>
              {isParked || isNeedsHuman ? 'Build · Decision required' : 'Watching task'}
            </span>
          </div>

          <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {decisionSentMsg ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 0' }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0F766E" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M20 6L9 17l-5-5"></path>
                </svg>
                <span style={{ fontSize: 16, lineHeight: 1.5, color: 'var(--ok)' }}>{decisionSentMsg}</span>
              </div>
            ) : isParked || isNeedsHuman ? (
              <>
                <p style={{ margin: 0, fontSize: 18, lineHeight: 1.45, fontWeight: 600, color: 'var(--text)' }}>
                  {isTestsAlreadyPass
                    ? 'All tests for this part already pass. Earlier parts built this behaviour. Accept it as already implemented?'
                    : parkReason || 'The agent reached a point that requires human guidance.'}
                </p>

                {questionsList.length > 1 ? (
                  <ul style={{ margin: 0, paddingLeft: 20, fontSize: 15, lineHeight: 1.55, color: 'var(--text)' }}>
                    {questionsList.map((q, idx) => (
                      <li key={idx}>{q}</li>
                    ))}
                  </ul>
                ) : questionsList.length === 1 ? (
                  <p style={{ margin: 0, fontSize: 15, lineHeight: 1.55, color: 'var(--text)' }}>
                    {questionsList[0]}
                  </p>
                ) : null}

                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, background: 'var(--accent-soft)', borderRadius: 10, padding: '12px 14px' }}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ flex: 'none', marginTop: 2, color: 'var(--accent)' }}>
                    <path d="M12 3l1.9 5.8H20l-4.9 3.6 1.9 5.8L12 14.6l-5 3.6 1.9-5.8L4 8.8h6.1z"></path>
                  </svg>
                  <span style={{ fontSize: 14, lineHeight: 1.5, color: 'var(--text)' }}>
                    <strong>Suggested:</strong> accept as already implemented. The report will record this, and the tests stay in your repository.
                  </span>
                </div>

                {decisionError && (
                  <div style={{ color: '#8A2C0D', fontSize: 14, background: '#FDF2F0', padding: 10, borderRadius: 8 }}>
                    {decisionError}
                  </div>
                )}

                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                  {isTestsAlreadyPass ? (
                    <>
                      <button
                        type="button"
                        disabled={decisionPending}
                        onClick={() => void handleControlAction('already_implemented', 'Accept as already implemented')}
                        style={{
                          fontSize: 15,
                          fontWeight: 600,
                          padding: '12px 18px',
                          border: 'none',
                          background: '#0F766E',
                          color: '#FFFFFF',
                          borderRadius: 10,
                          cursor: 'pointer',
                        }}
                      >
                        Accept as already implemented
                      </button>
                      <button
                        type="button"
                        disabled={decisionPending}
                        onClick={() => void handleControlAction('back_to_red', 'Send back to the test writer')}
                        style={{
                          fontSize: 15,
                          padding: '12px 18px',
                          border: '1px solid #D6D5CF',
                          background: '#FFFFFF',
                          color: '#1B1B19',
                          borderRadius: 10,
                          cursor: 'pointer',
                        }}
                      >
                        Send back to the test writer
                      </button>
                    </>
                  ) : currentRun?.state === 'FAILED' ? (
                    <button
                      type="button"
                      disabled={decisionPending}
                      onClick={() => void handleControlAction('retry', 'Retry failed check')}
                      style={{
                        fontSize: 15,
                        fontWeight: 600,
                        padding: '12px 18px',
                        border: 'none',
                        background: '#0F766E',
                        color: '#FFFFFF',
                        borderRadius: 10,
                        cursor: 'pointer',
                      }}
                    >
                      Retry
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={decisionPending}
                      onClick={() => void handleControlAction('resume', otherText || 'Resume and continue')}
                      style={{
                        fontSize: 15,
                        fontWeight: 600,
                        padding: '12px 18px',
                        border: 'none',
                        background: '#0F766E',
                        color: '#FFFFFF',
                        borderRadius: 10,
                        cursor: 'pointer',
                      }}
                    >
                      Answer and continue
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={() => setShowOtherTextarea(!showOtherTextarea)}
                    style={{
                      fontSize: 15,
                      padding: '12px 18px',
                      border: '1px solid transparent',
                      background: 'transparent',
                      color: '#0F5E57',
                      borderRadius: 10,
                      cursor: 'pointer',
                      textDecoration: 'underline',
                    }}
                  >
                    Answer in my own words
                  </button>
                </div>

                {showOtherTextarea && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4 }}>
                    <label htmlFor="orchestrator-answer" style={{ fontSize: 14, fontWeight: 600 }}>
                      Your answer to the orchestrator
                    </label>
                    <textarea
                      id="orchestrator-answer"
                      rows={3}
                      value={otherText}
                      onChange={(e) => setOtherText(e.target.value)}
                      placeholder="e.g. Accept it, but also add a test for a service whose only department is inactive."
                      style={{
                        fontSize: 15,
                        padding: 12,
                        border: '1px solid #C9C8C1',
                        borderRadius: 10,
                        resize: 'vertical',
                        color: '#1B1B19',
                        fontFamily: 'inherit',
                      }}
                    />
                    <div>
                      <button
                        type="button"
                        disabled={decisionPending || !otherText.trim()}
                        onClick={() => void handleControlAction('resume', otherText.trim())}
                        style={{
                          fontSize: 15,
                          fontWeight: 600,
                          padding: '10px 16px',
                          border: 'none',
                          background: '#0F766E',
                          color: '#FFFFFF',
                          borderRadius: 10,
                          cursor: 'pointer',
                        }}
                      >
                        Send to the orchestrator
                      </button>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <p style={{ margin: 0, fontSize: 15, color: 'var(--text-muted)' }}>
                All systems active. No pending decisions needed from you right now.
              </p>
            )}
          </div>


        </div>

        {/* Right card: Station detail card */}
        <div
          data-testid="station-detail-card"
          style={{
            flex: '2 1 380px',
            minWidth: 0,
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 14,
            padding: 20,
            display: 'flex',
            flexDirection: 'column',
            gap: 14,
            color: 'var(--text)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
            <h2 style={{ margin: 0, fontSize: 17, color: 'var(--text)' }}>{selectedDetail.name}</h2>
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{selectedDetail.who}</span>
          </div>

          <p style={{ margin: 0, fontSize: 15, lineHeight: 1.55, color: 'var(--text)' }}>{selectedDetail.doing}</p>

          <div style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Recent steps
          </div>
          {selectedDetail.steps.length > 0 ? (
            <ol style={{ margin: 0, paddingLeft: 20, fontSize: 14, lineHeight: 1.7, color: 'var(--text)' }}>
              {selectedDetail.steps.map((st, i) => (
                <li key={i}>{st}</li>
              ))}
            </ol>
          ) : (
            <p style={{ margin: 0, fontSize: 14, color: 'var(--text-muted)' }}>No work recorded yet.</p>
          )}

          {selectedDetail.files.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {selectedDetail.files.map((f, i) => (
                <span
                  key={i}
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12,
                    background: 'var(--code-bg)',
                    padding: '4px 8px',
                    borderRadius: 6,
                    color: 'var(--text)',
                  }}
                >
                  {f}
                </span>
              ))}
            </div>
          )}

          {currentRun && (
            <Link
              to={`/projects/${enc(resolvedPid)}/runs/${enc(currentRun.slug)}`}
              style={{ fontSize: 14, marginTop: 4, color: 'var(--link)' }}
            >
              Open full work: changes, tests, evidence
            </Link>
          )}
        </div>
      </section>

      {/* Tell the orchestrator & Handled for you panel */}
      <section
        aria-label="Orchestrator"
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 14,
          display: 'flex',
          flexWrap: 'wrap',
          color: 'var(--text)',
        }}
      >
        <div
          style={{
            flex: '3 1 560px',
            minWidth: 0,
            padding: 20,
            display: 'flex',
            flexDirection: 'column',
            gap: 14,
            borderRight: '1px solid var(--border)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0F766E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="3"></circle>
              <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"></path>
            </svg>
            <h2 style={{ margin: 0, fontSize: 17, color: 'var(--text)' }}>Tell the orchestrator</h2>
            <span style={{ marginLeft: 'auto', fontSize: 13, color: 'var(--ok)' }}>Watching this task</span>
          </div>
          <div style={{ fontSize: 14, color: 'var(--text-muted)' }}>
            Change anything about this task in your own words: size, repos, scenarios, which AI does a step, pause a part.
          </div>

          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <label htmlFor="tell-orchestrator" style={{ position: 'absolute', left: -9999 }}>
              Message to the orchestrator
            </label>
            <input
              id="tell-orchestrator"
              disabled
              placeholder="e.g. Use Claude for QA on this task"
              title="The orchestrator watches this task; it acts on your decisions above. Prompting is disabled during an active run."
              style={{
                flex: '1 1 320px',
                fontSize: 15,
                padding: 12,
                border: '1px solid var(--border)',
                borderRadius: 10,
                background: 'var(--surface-alt)',
                color: 'var(--text-muted)',
              }}
            />
            <button
              type="button"
              disabled
              title="Coming next: the orchestrator will act on your messages"
              style={{
                fontSize: 15,
                fontWeight: 600,
                padding: '12px 18px',
                border: 'none',
                background: 'var(--border)',
                color: 'var(--text-muted)',
                borderRadius: 10,
                cursor: 'not-allowed',
              }}
            >
              Send
            </button>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Coming next: the orchestrator will act on your messages.
          </div>
        </div>

        <div style={{ flex: '2 1 340px', minWidth: 0, padding: 20, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <h2 style={{ margin: 0, fontSize: 17, color: 'var(--text)' }}>Handled for you</h2>
          {handledList.length > 0 ? (
            <>
              <div style={{ fontSize: 14, color: 'var(--text-muted)' }}>Problems the orchestrator fixed without stopping the task.</div>
              <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 10, fontSize: 14, lineHeight: 1.45 }}>
                {handledList.map((item, i) => (
                  <li key={i} style={{ display: 'flex', gap: 10 }}>
                    <span style={{ flex: 'none', color: 'var(--ok)', fontWeight: 700 }}>✓</span>
                    <span style={{ color: 'var(--text)' }}>{item}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <div style={{ fontSize: 14, color: 'var(--text-muted)' }}>Nothing needed fixing yet.</div>
          )}
        </div>
      </section>

      {/* Activity section */}
      <section
        aria-label="Activity"
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 14,
          padding: '16px 20px',
          color: 'var(--text)',
        }}
      >
        <h2 style={{ fontSize: 13, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', margin: '0 0 8px 0' }}>
          Activity across the factory
        </h2>
        {snap && snap.activity.length > 0 ? (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6, fontSize: 14, color: 'var(--text)' }}>
            {snap.activity.slice(0, 10).map((act, i) => (
              <li key={i} data-testid="activity-row">
                <span style={{ color: 'var(--text-muted)', display: 'inline-block', width: 64 }}>
                  {/^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(act.at) ? act.at.slice(11, 16) : act.at}
                </span>
                {cleanActivityText(act.text)}
              </li>
            ))}
          </ul>
        ) : (
          <p style={{ margin: 0, fontSize: 14, color: 'var(--text-muted)' }}>No recent activity.</p>
        )}
      </section>
    </div>
  );
}
