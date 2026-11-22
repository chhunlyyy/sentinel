// View-model types for the factory floor screen.
// Built from WFactory (wire.ts) by floorSnapshot() in Floor.tsx.
import type * as W from '../../api/wire.ts';

export type StationState = 'done' | 'working' | 'waiting' | 'paused' | 'limit' | 'queued' | 'next' | 'todo';
export type StationKind = 'agent' | 'engine' | 'gate';

export interface LaneView {
  cycle: string;
  name: string;
  repo: string;
  state: string;
  red: StationState;
  green: StationState;
  refactor: StationState;
}

export interface AgentView {
  task: string;
  role: string;
  runner: string;
  model: string | null;
  adapter: string;
  startedAt: string;
}

export interface StationTaskView {
  id: string;
  role: string;
  state: string;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface RunView {
  slug: string;
  title: string;
  /** Short initials (≤2 chars) for the task chip badge */
  short: string;
  /** Brand colour for this task chip */
  color: string;
  paused: boolean;
  station: string;
  state: string;
  stateLabel: string;
  /** where the task is, for the task chip: `Build · behavior 2 of 3`, `Waiting for you`, `Triage` */
  whereLabel: string;
  stationLabel: string;
  stations: Record<string, StationState>;
  nextStation: string | null;
  agents: Record<string, AgentView[]>;
  lanes: LaneView[];
  attention: { kind: 'needs_human' | 'blocked'; reason: string } | null;
  /** the provider usage limit this run waits for, or null */
  limit: { task: string; role: string; runner: string; retryAt: string; reason: string | null } | null;
  task_usage?: Record<string, W.WTaskUsage>;
  station_tasks?: Record<string, StationTaskView[]>;
  pendingNotes: number;
}

export interface QueueItem {
  slug: string;
  title: string;
  position: number;
  reason: string;
}

export interface FactoryLimits {
  driver: string;
  maxTasksPerProject: number;
  maxAgents: number;
  runningInProject: number;
  runningTotal: number;
}

export interface WhoView {
  role: string;
  runner: string;
  model: string | null;
}

export interface ActivityView {
  at: string;
  run: string;
  /** station id (triage, gate_spec, build ...) */
  station: string;
  text: string;
}

export interface FloorSnapshot {
  project: string;
  factoryPaused: boolean;
  who: Record<string, WhoView>;
  activity: ActivityView[];
  generatedAt: string;
  stations: string[];
  limits: FactoryLimits;
  budget?: W.WFactoryBudget;
  runs: RunView[];
  queue: QueueItem[];
  /** roles that block engine runs; the floor offers "Fix routing" while this is not empty */
  routingProblems: string[];
}

/** Fixed station definitions that the layout and edges use */
export interface StationDef {
  id: string;
  name: string;
  glyph: string;
  kind: StationKind;
  /** position in the 1000×560 viewBox */
  x: number;
  y: number;
  /** description of what happens here */
  does: string;
  /** knowledge text for this kind */
  knowledgeText: string;
  /** index of this build lane when build fans out (0, 1, ...) */
  laneIdx?: number;
}
