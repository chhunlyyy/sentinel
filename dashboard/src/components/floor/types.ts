// View-model types for the factory floor screen.
// Built from WFactory (wire.ts) by floorSnapshot() in Floor.tsx.

export type StationState = 'done' | 'working' | 'waiting' | 'paused' | 'queued' | 'next' | 'todo';
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
  stationLabel: string;
  stations: Record<string, StationState>;
  nextStation: string | null;
  agents: Record<string, AgentView[]>;
  lanes: LaneView[];
  attention: { kind: 'needs_human' | 'blocked'; reason: string } | null;
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

export interface FloorSnapshot {
  project: string;
  generatedAt: string;
  stations: string[];
  limits: FactoryLimits;
  runs: RunView[];
  queue: QueueItem[];
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
}
