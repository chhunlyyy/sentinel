import type { WNotification } from './api/wire.ts';

/** The dashboard screen a notification opens. The server sends /tasks/<slug>[/<page>]; the screens live under the project. */
export function appRoute(n: Pick<WNotification, 'project' | 'link'>): string {
  const m = /^\/tasks\/([a-z0-9][a-z0-9._-]*)(\/(?:specification|gherkin|workflow|verification|tdd|trace|changes))?$/.exec(n.link);
  if (!m) return '/';
  return `/projects/${encodeURIComponent(n.project)}/runs/${m[1]}${m[2] ?? ''}`;
}

export const LEVEL_LABEL: Record<string, string> = { action: 'Action', warning: 'Warning', info: 'Info' };

export interface DesktopState {
  /** the user pressed "Enable desktop notifications" in this browser */
  enabled: boolean;
  permission: 'default' | 'granted' | 'denied';
  /** notifications.desktop of the project config */
  allowed: (project: string) => boolean;
}

export interface Seen {
  ids: Set<string>;
  /** false until the first answer has been taken in */
  primed: boolean;
}

export const newSeen = (): Seen => ({ ids: new Set(), primed: false });

/**
 * The notifications to raise on the desktop. `seen` holds every id already shown by this page: the first answer fills
 * it and raises nothing, so opening the dashboard never replays old notifications.
 */
export function raiseCandidates(seen: Seen, items: WNotification[], state: DesktopState): WNotification[] {
  const fresh = items.filter((n) => !seen.ids.has(n.id));
  const first = !seen.primed;
  for (const n of items) seen.ids.add(n.id);
  seen.primed = true;
  if (first || !state.enabled || state.permission !== 'granted') return [];
  return fresh.filter((n) => !n.read_at && state.allowed(n.project));
}

const CLAIMED = 'sentinel.desktop.shown';
const CLAIM_KEEP = 200;

interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** True for the one tab that may raise this notification (tabs share localStorage). Without storage the tab raises it. */
export function claimDesktop(storage: Store | null, id: string): boolean {
  if (!storage) return true;
  try {
    const list = JSON.parse(storage.getItem(CLAIMED) ?? '[]') as string[];
    if (list.includes(id)) return false;
    storage.setItem(CLAIMED, JSON.stringify([...list, id].slice(-CLAIM_KEEP)));
    return true;
  } catch {
    return true;
  }
}

/** The event types the notification rules read (docs/contracts/event-contracts.md section 4): only these refetch the list. */
export const NOTIFICATION_EVENTS: readonly string[] = [
  'approval.requested', 'approval.decided', 'run.created', 'run.state_changed', 'task.finished', 'evidence.recorded', 'run.status_changed',
  'knowledge.failed',
];

/** The events after which the notifications.desktop switch of a project may have changed. */
export const CONFIG_EVENTS: readonly string[] = ['config.saved', 'project.created', 'project.updated'];

/**
 * The per-project notifications.desktop switch. A project whose configuration cannot be read is treated as "off":
 * a desktop notification is never raised on a guess.
 */
export async function loadDesktopConfig(
  ids: readonly string[],
  read: (id: string) => Promise<ReadonlyArray<{ path: string; value: unknown }>>,
): Promise<Record<string, boolean>> {
  const out: Record<string, boolean> = {};
  for (const id of ids) {
    try {
      out[id] = (await read(id)).find((v) => v.path === 'notifications.desktop')?.value !== false;
    } catch {
      out[id] = false;
    }
  }
  return out;
}
