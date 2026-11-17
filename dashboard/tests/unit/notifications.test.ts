import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, test } from 'vitest';
import { CONFIG_EVENTS, NOTIFICATION_EVENTS, appRoute, claimDesktop, loadDesktopConfig, newSeen, raiseCandidates, type DesktopState } from '../../src/notifications.ts';
import { createHub } from '../../src/state/app.tsx';
import type { StreamEnvelope } from '../../src/api/types.ts';
import type { Resource } from '../../src/state/resource.ts';
import type { WNotification } from '../../src/api/wire.ts';

const n = (id: string, over: Partial<WNotification> = {}): WNotification => ({
  id, project: 'digital-hr', run: 'leave-balance', level: 'action', text: 'Specification ready for review', link: '/tasks/leave-balance/specification',
  at: '2026-11-14T10:00:00Z', read_at: null, ...over,
});

describe('AC-NOT-01q a notification link becomes a dashboard route of its project', () => {
  test.each([
    ['/tasks/leave-balance', '/projects/digital-hr/runs/leave-balance'],
    ['/tasks/leave-balance/specification', '/projects/digital-hr/runs/leave-balance/specification'],
    ['/tasks/leave-balance/verification', '/projects/digital-hr/runs/leave-balance/verification'],
  ])('AC-NOT-01q %s', (link, route) => expect(appRoute(n('digital-hr:1', { link }))).toBe(route));
  test('AC-NOT-03a a link that is not a task route goes to the overview and never to an API path', () => {
    expect(appRoute(n('digital-hr:1', { link: '/api/v1/tasks/x/approvals' }))).toBe('/');
    expect(appRoute(n('digital-hr:1', { link: 'https://example.com' }))).toBe('/');
  });
});

const primed = (...ids: string[]) => ({ ids: new Set(ids), primed: true });

describe('AC-NOT-02b only a new, unread notification is raised, and only with consent', () => {
  const on: DesktopState = { enabled: true, permission: 'granted', allowed: (pid) => pid === 'digital-hr' };
  test('AC-NOT-02b the first load raises nothing and remembers what it saw', () => {
    const seen = newSeen();
    expect(raiseCandidates(seen, [n('digital-hr:1'), n('digital-hr:2')], on)).toEqual([]);
    expect([...seen.ids].sort()).toEqual(['digital-hr:1', 'digital-hr:2']);
  });
  test('AC-NOT-02a an empty first answer still counts as the first, so the next new notification is raised', () => {
    const seen = newSeen();
    expect(raiseCandidates(seen, [], on)).toEqual([]);
    expect(raiseCandidates(seen, [n('digital-hr:1')], on).map((x) => x.id)).toEqual(['digital-hr:1']);
  });
  test('AC-NOT-02a a later load raises each new unread notification once', () => {
    const seen = primed('digital-hr:1');
    const first = raiseCandidates(seen, [n('digital-hr:2'), n('digital-hr:1')], on);
    expect(first.map((x) => x.id)).toEqual(['digital-hr:2']);
    expect(raiseCandidates(seen, [n('digital-hr:2'), n('digital-hr:1')], on)).toEqual([]);
  });
  test.each([
    ['the user never pressed enable', { ...on, enabled: false }],
    ['the permission is denied', { ...on, permission: 'denied' as const }],
    ['the permission was never asked', { ...on, permission: 'default' as const }],
    ['the project config switches it off', { ...on, allowed: () => false }],
  ])('AC-NOT-02b nothing is raised when %s', (_name, state) => {
    const seen = primed('digital-hr:1');
    expect(raiseCandidates(seen, [n('digital-hr:2')], state)).toEqual([]);
    expect(seen.ids.has('digital-hr:2')).toBe(true);
  });
  test('AC-NOT-02b a read notification is not raised', () => {
    const seen = primed('digital-hr:1');
    expect(raiseCandidates(seen, [n('digital-hr:2', { read_at: '2026-11-14T10:01:00Z' })], on)).toEqual([]);
  });
});

describe('AC-NOT-02d tabs share one claim per notification', () => {
  test('AC-NOT-02d the first claim wins, the second does not', () => {
    const store = new Map<string, string>();
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
    expect(claimDesktop(storage, 'digital-hr:5')).toBe(true);
    expect(claimDesktop(storage, 'digital-hr:5')).toBe(false);
    expect(claimDesktop(storage, 'digital-hr:6')).toBe(true);
  });
  test('AC-NOT-02d without storage the tab raises it itself', () => {
    expect(claimDesktop(null, 'digital-hr:5')).toBe(true);
  });
});

describe('review: appRoute allows only the known sub pages', () => {
  test.each(['/tasks/x/bogus', '/tasks/x/specification/extra', '/tasks/x/', '/tasks//specification', '/tasks/x/Specification', '/tasks/../x'])(
    '%s falls back to the overview',
    (link) => expect(appRoute(n('digital-hr:1', { link }))).toBe('/'),
  );
  test.each(['specification', 'gherkin', 'workflow', 'verification', 'tdd', 'trace', 'changes'])('%s is a route', (page) =>
    expect(appRoute(n('digital-hr:1', { link: `/tasks/x/${page}` }))).toBe(`/projects/digital-hr/runs/x/${page}`));
});

describe('review: desktop config', () => {
  test('a project whose configuration cannot be read is off', async () => {
    const read = async (id: string) => {
      if (id === 'broken') throw new Error('500');
      return id === 'quiet' ? [{ path: 'notifications.desktop', value: false }] : [{ path: 'notifications.desktop', value: true }];
    };
    expect(await loadDesktopConfig(['digital-hr', 'quiet', 'broken', 'default'], (id) => (id === 'default' ? Promise.resolve([]) : read(id)))).toEqual({
      'digital-hr': true, quiet: false, broken: false, default: true,
    });
  });
});

describe('review: refetch only on the event types the rules read', () => {
  const ev = (type: string): StreamEnvelope => ({ id: 1, type, at: '2026-11-14T10:00:00Z', project: 'digital-hr', run: 'leave-balance', task: null, actor: { kind: 'engine', name: null, channel: 'cli' }, payload: {} });
  const hit = (types: readonly string[] | undefined, type: string, extra: Partial<Parameters<ReturnType<typeof createHub>['register']>[1]> = {}) => {
    const hub = createHub();
    let n = 0;
    hub.register({ invalidate: () => { n += 1; } } as unknown as Resource<unknown>, { types, ...extra });
    hub.dispatch(ev(type));
    return n;
  };
  test('the notification list refetches for rule events and ignores the others', () => {
    for (const t of NOTIFICATION_EVENTS) expect(hit(NOTIFICATION_EVENTS, t)).toBe(1);
    for (const t of ['task.progress', 'task.started', 'cycle.planned', 'config.saved']) expect(hit(NOTIFICATION_EVENTS, t)).toBe(0);
  });
  test('a view without types refetches for every event', () => expect(hit(undefined, 'task.progress')).toBe(1));
  test('the desktop config refetches after a configuration event only', () => {
    expect(hit(CONFIG_EVENTS, 'config.saved')).toBe(1);
    expect(hit(CONFIG_EVENTS, 'task.progress')).toBe(0);
  });
  test('the list matches the candidates of the engine function', () => {
    const py = readFileSync(resolve(__dirname, '../../../sentinel/scripts/notifications.py'), 'utf8');
    const block = /CANDIDATES = \(([^)]*)\)/.exec(py)?.[1] ?? '';
    expect([...block.matchAll(/"([a-z._]+)"/g)].map((m) => m[1]).sort()).toEqual([...NOTIFICATION_EVENTS].sort());
  });
});
