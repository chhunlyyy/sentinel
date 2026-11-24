// Maps the WFactory wire shape to the view-model (FloorSnapshot + RunView) used by the floor screen.
import type * as W from '../../api/wire.ts';
import type { ActivityView, WhoView, FloorSnapshot, RunView, StationState, AgentView, LaneView, FactoryLimits, QueueItem, StationTaskView } from './types.ts';

/** Colour palette for task chips — cycles if more than 5 tasks */
const TASK_COLORS = ['#4FD1C1', '#F5B547', '#9DB4FF', '#FC8181', '#B794F4', '#68D391'];

/** Derive 1–2 letter initials from a slug */
export function initials(slug: string): string {
  const parts = slug.split('-').filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function stationLabel(run: W.WFactoryRun): string {
  const st = run.station;
  const labels: Record<string, string> = {
    intake: 'Intake', triage: 'Triage', spec: 'Specification',
    gate_spec: 'Spec review', gherkin: 'Scenarios', gate_gherkin: 'Scenario review',
    build: 'Build', verify: 'Verify', report: 'Report',
    gate_accept: 'Acceptance', knowledge: 'Knowledge',
  };
  return labels[st] ?? st;
}

/** "14:05" in the viewer's time zone */
export function retryClock(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** `Waiting for usage limit · retries 14:05` */
export function limitText(retryAt: string): string {
  return `Waiting for usage limit · retries ${retryClock(retryAt)}`;
}

function stateLabel(run: W.WFactoryRun): string {
  if (run.paused) return 'Paused';
  const s = run.station;
  const st = run.stations[s];
  if (st === 'limit' && run.limit) return limitText(run.limit.retry_at);
  if (st === 'waiting') return 'Waiting for you';
  if (st === 'working') return 'Working';
  if (st === 'queued') return 'Queued';
  return run.state;
}

/** State of one build lane: a working or waiting step wins; otherwise done when all steps are, queued when none started. */
export function laneState(l: Pick<LaneView, 'red' | 'green' | 'refactor'>, paused: boolean, limit = false): StationState {
  const steps = [l.red, l.green, l.refactor];
  if (steps.includes('working')) return paused ? 'paused' : limit ? 'limit' : 'working';
  if (steps.includes('waiting')) return 'waiting';
  if (steps.every((x) => x === 'done')) return 'done';
  if (steps.every((x) => x === 'todo' || x === 'queued' || x === 'next')) return 'queued';
  return paused ? 'paused' : limit ? 'limit' : 'working';
}

function whereLabel(run: W.WFactoryRun): string {
  if (run.paused) return 'Paused';
  const st = run.stations[run.station];
  if (st === 'waiting') return 'Waiting for you';
  if (st === 'limit' && run.limit) return limitText(run.limit.retry_at);
  if (run.station === 'build' && run.lanes.length > 1) {
    const states = run.lanes.map((l) => laneState(l, false, run.stations.build === 'limit'));
    let i = states.findIndex((x) => x === 'working' || x === 'waiting' || x === 'limit');
    if (i < 0) i = states.findIndex((x) => x !== 'done');
    return `Build · behavior ${Math.max(i, 0) + 1} of ${run.lanes.length}`;
  }
  return stationLabel(run);
}

function adaptAgents(agents: Record<string, W.WFactoryAgent[]>): Record<string, AgentView[]> {
  const out: Record<string, AgentView[]> = {};
  for (const [station, list] of Object.entries(agents)) {
    out[station] = list.map((a) => ({
      task: a.task,
      role: a.role,
      runner: a.runner,
      model: a.model,
      adapter: a.adapter,
      startedAt: a.started_at,
    }));
  }
  return out;
}

function adaptLanes(lanes: W.WFactoryLane[]): LaneView[] {
  return lanes.map((l) => ({
    cycle: l.cycle,
    name: l.name,
    repo: l.repo,
    state: l.state,
    red: l.red as StationState,
    green: l.green as StationState,
    refactor: l.refactor as StationState,
  }));
}

function adaptStationTasks(tasks?: Record<string, W.WStationTask[]>): Record<string, StationTaskView[]> {
  const out: Record<string, StationTaskView[]> = {};
  if (!tasks) return out;
  for (const [st, list] of Object.entries(tasks)) {
    out[st] = (list ?? []).map((t) => ({
      id: t.id,
      role: t.role,
      state: t.state,
      startedAt: t.started_at,
      finishedAt: t.finished_at,
    }));
  }
  return out;
}

function adaptRun(run: W.WFactoryRun, idx: number): RunView {
  return {
    slug: run.slug,
    title: run.title,
    tier: run.tier,
    createdAt: run.created_at,
    short: initials(run.slug),
    color: TASK_COLORS[idx % TASK_COLORS.length],
    paused: run.paused,
    station: run.station,
    state: run.state,
    stateLabel: stateLabel(run),
    whereLabel: whereLabel(run),
    stationLabel: stationLabel(run),
    stations: run.stations as Record<string, StationState>,
    nextStation: run.next_station,
    agents: adaptAgents(run.agents),
    lanes: adaptLanes(run.lanes),
    attention: run.attention,
    limit: run.limit
      ? { task: run.limit.task, role: run.limit.role, runner: run.limit.runner, retryAt: run.limit.retry_at, reason: run.limit.reason }
      : null,
    task_usage: run.task_usage,
    station_tasks: adaptStationTasks(run.station_tasks),
    pendingNotes: run.pending_notes,
  };
}

export function floorSnapshot(w: W.WFactory): FloorSnapshot {
  const limits: FactoryLimits = {
    driver: w.limits.driver,
    maxTasksPerProject: w.limits.max_tasks_per_project,
    maxAgents: w.limits.max_agents,
    runningInProject: w.limits.running_in_project,
    runningTotal: w.limits.running_total,
  };
  const queue: QueueItem[] = w.queue.map((q) => ({
    slug: q.slug,
    title: q.title,
    position: q.position,
    reason: q.reason,
  }));
  const who: Record<string, WhoView> = {};
  for (const [station, v] of Object.entries(w.who ?? {})) who[station] = { role: v.role, runner: v.runner, model: v.model };
  const activity: ActivityView[] = (w.activity ?? []).map((a) => ({ at: a.at, run: a.run, station: a.station, text: a.text }));
  return {
    project: w.project,
    factoryPaused: w.factory_paused ?? false,
    who,
    activity,
    generatedAt: w.generated_at,
    stations: w.stations,
    limits,
    budget: w.budget,
    runs: w.runs.map(adaptRun),
    queue,
    routingProblems: w.routing?.problems ?? [],
  };
}
