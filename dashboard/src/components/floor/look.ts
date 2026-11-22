// Look-up table for station state → visual properties used by neuron buttons and edges.
import type { StationState } from './types.ts';

export interface StateLook {
  label: string;
  ring: string;
  fill: string;
  ink: string;
  glow: string;
  labelColor: string;
  badgeBg: string;
  badgeFg: string;
  edgeCls: string;
  animCls: string;
  live: boolean;
}

const LOOK: Record<StationState, StateLook> = {
  done: {
    label: 'Done',
    ring: 'var(--floor-done-ring)',
    fill: 'var(--floor-done-fill)',
    ink: 'var(--floor-done-ink)',
    glow: 'none',
    labelColor: 'var(--floor-text-muted)',
    badgeBg: 'var(--floor-done-fill)',
    badgeFg: 'var(--floor-done-ink)',
    edgeCls: 'floor-e-done',
    animCls: '',
    live: false,
  },
  working: {
    label: 'Working',
    ring: 'var(--floor-working-ring)',
    fill: 'var(--floor-working-fill)',
    ink: 'var(--floor-working-ink)',
    glow: '0 0 0 6px rgba(79, 209, 193, 0.14), 0 0 34px rgba(79, 209, 193, 0.65)',
    labelColor: 'var(--floor-text)',
    badgeBg: 'var(--floor-working-badge-bg)',
    badgeFg: 'var(--floor-working-badge-fg)',
    edgeCls: 'floor-e-active',
    animCls: 'floor-breathe',
    live: true,
  },
  waiting: {
    label: 'Needs you',
    ring: 'var(--floor-waiting-ring)',
    fill: 'var(--floor-waiting-fill)',
    ink: 'var(--floor-waiting-ink)',
    glow: '0 0 0 6px rgba(245, 181, 71, 0.14), 0 0 34px rgba(245, 181, 71, 0.6)',
    labelColor: 'var(--floor-waiting-label)',
    badgeBg: 'var(--floor-waiting-badge-bg)',
    badgeFg: 'var(--floor-waiting-badge-fg)',
    edgeCls: 'floor-e-wait',
    animCls: 'floor-breathe',
    live: true,
  },
  paused: {
    label: 'Paused',
    ring: 'var(--floor-paused-ring)',
    fill: 'var(--floor-paused-fill)',
    ink: 'var(--floor-paused-ink)',
    glow: 'none',
    labelColor: 'var(--floor-text-muted)',
    badgeBg: 'var(--floor-paused-fill)',
    badgeFg: 'var(--floor-paused-ink)',
    edgeCls: 'floor-e-pause',
    animCls: '',
    live: false,
  },
  limit: {
    label: 'Waiting for usage limit',
    ring: 'var(--floor-paused-ring)',
    fill: 'var(--floor-paused-fill)',
    ink: 'var(--floor-paused-ink)',
    glow: 'none',
    labelColor: 'var(--floor-text-muted)',
    badgeBg: 'var(--floor-paused-fill)',
    badgeFg: 'var(--floor-paused-ink)',
    edgeCls: 'floor-e-pause',
    animCls: '',
    live: false,
  },
  queued: {
    label: 'Queued',
    ring: 'var(--floor-todo-ring)',
    fill: 'var(--floor-todo-fill)',
    ink: 'var(--floor-todo-ink)',
    glow: 'none',
    labelColor: 'var(--floor-text-muted)',
    badgeBg: 'var(--floor-todo-fill)',
    badgeFg: 'var(--floor-todo-ink)',
    edgeCls: 'floor-e-todo',
    animCls: '',
    live: false,
  },
  next: {
    label: 'Next',
    ring: 'var(--floor-todo-ring)',
    fill: 'var(--floor-todo-fill)',
    ink: 'var(--floor-todo-ink)',
    glow: 'none',
    labelColor: 'var(--floor-text-muted)',
    badgeBg: 'var(--floor-todo-fill)',
    badgeFg: 'var(--floor-todo-ink)',
    edgeCls: 'floor-e-todo',
    animCls: '',
    live: false,
  },
  todo: {
    label: 'Later',
    ring: 'var(--floor-todo-ring)',
    fill: 'var(--floor-todo-fill)',
    ink: 'var(--floor-todo-ink)',
    glow: 'none',
    labelColor: 'var(--floor-text-muted)',
    badgeBg: 'var(--floor-todo-fill)',
    badgeFg: 'var(--floor-todo-ink)',
    edgeCls: 'floor-e-todo',
    animCls: '',
    live: false,
  },
};

export function stateLook(state: StationState): StateLook {
  return LOOK[state] ?? LOOK.todo;
}

/** Returns the edge CSS class for the working → knowledge knowledge-feed link */
export function feedEdgeCls(state: StationState): string {
  return state === 'working' ? 'floor-e-feed-on' : 'floor-e-feed';
}
