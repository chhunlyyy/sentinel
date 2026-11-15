import type { BrowserContext, Page } from '@playwright/test';
import { test, expect, open, nav, settle, type Api } from './helpers.ts';

type Permission = 'default' | 'granted' | 'denied';

interface Stub {
  permission: Permission;
  /** what the browser answers when the page asks */
  grant: boolean;
  /** the opt-in flag the dashboard keeps in localStorage, set before the page starts */
  enabled: boolean;
}

declare global {
  interface Window {
    __notes: { title: string; body: string; tag: string; opts: Record<string, unknown>; onclick: (() => void) | null }[];
    __asks: number;
  }
}

/** A stand-in for the browser Notification API that records what the page asks for and constructs. */
async function stubBrowser(target: BrowserContext | Page, stub: Partial<Stub> = {}) {
  const s: Stub = { permission: 'default', grant: true, enabled: false, ...stub };
  await target.addInitScript((init: Stub) => {
    window.__notes = [];
    window.__asks = 0;
    class FakeNotification {
      static permission: string = init.permission;
      static async requestPermission() {
        window.__asks += 1;
        FakeNotification.permission = init.grant ? 'granted' : 'denied';
        return FakeNotification.permission;
      }
      title: string;
      body: string;
      tag: string;
      opts: Record<string, unknown>;
      onclick: (() => void) | null = null;
      constructor(title: string, opts: { body?: string; tag?: string } = {}) {
        this.opts = opts;
        this.title = title;
        this.body = opts.body ?? '';
        this.tag = opts.tag ?? '';
        window.__notes.push(this);
      }
      close() {}
    }
    Object.defineProperty(window, 'Notification', { value: FakeNotification, configurable: true, writable: true });
    try {
      if (init.enabled && !sessionStorage.getItem('__seeded')) localStorage.setItem('sentinel.desktop.enabled', '1');
      sessionStorage.setItem('__seeded', '1');
    } catch {
      /* storage is not available */
    }
  }, s);
}

const bell = (page: Page) => page.getByRole('button', { name: /^Notifications/ });
const notes = (page: Page) => page.evaluate(() => window.__notes.map((n) => ({ title: n.title, body: n.body, tag: n.tag })));

const NEW = {
  id: 'digital-hr:900', project: 'digital-hr', run: 'leave-balance', level: 'action', text: 'Specification ready for review',
  link: '/tasks/leave-balance/specification', at: '2026-11-14T11:00:00.000000Z', read_at: null,
};

async function arrive(api: Api, n: Record<string, unknown> = NEW) {
  await api.set(['notifications', `id=${String(n.id)}`], n);
  await api.event('approval.requested', { id: 900, at: n.at, project: n.project, run: n.run });
}

test.describe('bell and list', () => {
  test('AC-NOT-01q the bell shows the unread count and the list', async ({ page, api }) => {
    await api.preset('notifications');
    await open(page, '/');
    await settle(page);
    await expect(bell(page)).toContainText('4 unread');
    await bell(page).click();
    const items = page.getByRole('list', { name: 'Notifications' }).getByRole('listitem');
    await expect(items).toHaveCount(4);
    for (const t of ['Action', 'digital-hr', '2026-11-14', 'Specification ready for review']) await expect(items.first()).toContainText(t);
    // plain text: markup in a notification is shown, never rendered
    await expect(items.filter({ hasText: 'Provider <b>codex</b> unavailable' })).toHaveCount(1);
    await expect(page.locator('li b')).toHaveCount(0);
  });

  test('AC-NOT-01q an empty list says so', async ({ page }) => {
    await open(page, '/');
    await settle(page);
    await expect(bell(page)).toContainText('0 unread');
    await bell(page).click();
    await expect(page.getByText('No notifications')).toBeVisible();
  });

  test('AC-NOT-03a opening an approval notification does not approve', async ({ page, api }) => {
    await api.preset('notifications');
    await open(page, '/');
    await settle(page);
    const mark = await api.mark();
    await bell(page).click();
    await page.getByRole('link', { name: /Specification ready for review/ }).click();
    await expect(page).toHaveURL(/#\/projects\/digital-hr\/runs\/leave-balance\/specification$/);
    await expect(page.getByRole('heading', { name: 'Specification review' })).toBeVisible();
    await api.idle();
    const sent = (await api.since(mark)).filter((r) => r.method !== 'GET');
    expect(sent).toHaveLength(1);
    expect(sent[0].path).toMatch(/^\/api\/v1\/notifications\/digital-hr%3A\d+\/read$/);
    expect(sent.every((r) => !/approvals|acceptance/.test(r.path))).toBe(true);
    await expect(bell(page)).toContainText('3 unread');
  });
});

test.describe('desktop notifications', () => {
  test('AC-NOT-02a desktop notifications after the user enables them', async ({ page, api, context }) => {
    await api.preset('notifications');
    await stubBrowser(context, { permission: 'default', grant: true });
    await open(page, '/');
    await settle(page);
    await bell(page).click();
    await page.getByRole('button', { name: 'Enable desktop notifications' }).click();
    await expect.poll(() => page.evaluate(() => window.__asks)).toBe(1);
    await expect(page.getByRole('button', { name: 'Enable desktop notifications' })).toHaveCount(0);
    await arrive(api);
    await expect.poll(() => notes(page)).toEqual([{ title: 'Sentinel', body: 'Specification ready for review', tag: 'digital-hr:900' }]);
    await expect(bell(page)).toContainText('5 unread');
    const mark = await api.mark();
    await page.evaluate(() => window.__notes[0].onclick?.());
    await expect(page).toHaveURL(/#\/projects\/digital-hr\/runs\/leave-balance\/specification$/);
    await api.idle();
    const sent = (await api.since(mark)).filter((r) => r.method !== 'GET');
    expect(sent.every((r) => /\/notifications\/.*\/read$/.test(r.path))).toBe(true);
  });

  const conditions: [string, Partial<Stub>, (api: Api) => Promise<void>][] = [
    ['the browser permission is "denied"', { permission: 'denied', enabled: true }, async () => undefined],
    ['the user never pressed "Enable desktop notifications"', { permission: 'granted', enabled: false }, async () => undefined],
    ['notifications.desktop is false in the project config', { permission: 'granted', enabled: true }, async (api) => {
      for (const pid of ['digital-hr', 'payroll']) await api.set(['projectData', pid, 'configuration', 'values', 'path=notifications.desktop', 'value'], false);
    }],
  ];
  for (const [name, stub, setup] of conditions) {
    test(`AC-NOT-02b no desktop notification without consent: ${name}`, async ({ page, api, context }) => {
      await api.preset('notifications');
      await setup(api);
      await stubBrowser(context, stub);
      await open(page, '/');
      await settle(page);
      await expect(bell(page)).toContainText('4 unread');
      await arrive(api);
      await expect(bell(page)).toContainText('5 unread');
      await bell(page).click();
      await expect(page.getByRole('list', { name: 'Notifications' }).getByRole('listitem')).toHaveCount(5);
      expect(await notes(page)).toEqual([]);
    });
  }

  test('AC-NOT-02b the option is hidden when notifications.desktop is false', async ({ page, api, context }) => {
    for (const pid of ['digital-hr', 'payroll']) await api.set(['projectData', pid, 'configuration', 'values', 'path=notifications.desktop', 'value'], false);
    await stubBrowser(context, { permission: 'default' });
    await open(page, '/');
    await settle(page);
    await bell(page).click();
    await expect(page.getByRole('button', { name: 'Enable desktop notifications' })).toHaveCount(0);
  });

  test('AC-NOT-02c the page never asks for permission on load', async ({ page, api, context }) => {
    await api.preset('notifications');
    await stubBrowser(context, { permission: 'default' });
    for (const route of ['/', '/projects', '/projects/digital-hr', '/tasks', '/tasks/new', '/approvals', '/runs', '/quality', '/reports', '/settings/installation',
      '/projects/digital-hr/runs/leave-balance', '/projects/digital-hr/runs/leave-balance/workflow']) {
      await open(page, route);
      await page.reload();
      await settle(page);
      expect(await page.evaluate(() => window.__asks), route).toBe(0);
    }
    await bell(page).click();
    await page.getByRole('button', { name: 'Enable desktop notifications' }).click();
    await expect.poll(() => page.evaluate(() => window.__asks)).toBe(1);
  });

  test('AC-NOT-02d two tabs raise one desktop notification', async ({ page, api, context }) => {
    await api.preset('notifications');
    await stubBrowser(context, { permission: 'granted', enabled: true });
    const second = await context.newPage();
    await open(page, '/');
    await open(second, '/');
    await settle(page);
    await settle(second);
    await expect(bell(second)).toContainText('4 unread');
    await api.set(['notifications', 'id=digital-hr:901'], { ...NEW, id: 'digital-hr:901', level: 'action', text: 'unknown Red failure', link: '/tasks/leave-balance' });
    await api.event('run.state_changed', { id: 901, at: NEW.at, project: 'digital-hr', run: 'leave-balance' });
    await expect(bell(page)).toContainText('5 unread');
    await expect(bell(second)).toContainText('5 unread');
    await api.idle(1000);
    const all = [...(await notes(page)), ...(await notes(second))];
    expect(all).toEqual([{ title: 'Sentinel', body: 'unknown Red failure', tag: 'digital-hr:901' }]);
  });

  test('AC-VIS-04a the dashboard registers no service worker and uses no Push API', async ({ page, api }) => {
    await api.preset('notifications');
    await open(page, '/');
    await settle(page);
    const found = await page.evaluate(async () => ({
      workers: 'serviceWorker' in navigator ? (await navigator.serviceWorker.getRegistrations()).length : 0,
      scripts: Array.from(document.scripts).map((s) => s.src),
    }));
    expect(found.workers).toBe(0);
    const source = await (await page.request.get(found.scripts.find((s) => s.endsWith('.js')) ?? '/')).text();
    expect(source).not.toMatch(/serviceWorker\.register|PushManager|pushManager/);
  });
});

test.describe('reports', () => {
  test('AC-ANL-01p the Reports screen', async ({ page, api }) => {
    await open(page, '/');
    await nav(page).getByRole('link', { name: 'Reports' }).click();
    await expect(page.getByRole('heading', { name: 'Reports', level: 1 })).toBeVisible();
    await page.getByLabel('Project').selectOption('digital-hr');
    await page.getByLabel('From').fill('2026-11-01');
    await page.getByLabel('To').fill('2026-11-30');
    for (const h of ['Runs', 'Lead time', 'Acceptance rate', 'Approval wait', 'Retries', 'Provider failure rate', 'TDD cycles', 'Verification pass rate', 'Rework', 'Cost']) {
      await expect(page.getByRole('heading', { name: h, level: 2 })).toBeVisible();
    }
    await expect.poll(async () => (await api.gets(/reports\/analytics/)).some((r) => r.search.includes('from=2026-11-01') && r.search.includes('to=2026-11-30'))).toBe(true);
    const runs = page.getByTestId('report-runs');
    await expect(runs).toContainText('4');
    await expect(page.getByTestId('report-lead-time')).toContainText('2 h');
    await expect(page.getByTestId('report-acceptance')).toContainText('50%');
    await expect(page.getByTestId('report-acceptance')).toContainText('1 accepted of 2 decided');
    await expect(page.getByTestId('report-providers')).toContainText('codex');
    await expect(page.getByTestId('report-providers')).toContainText('25%');
    await expect(page.getByTestId('report-cost')).toContainText('11.5');
    // null values are shown as "Not reported" with the reason, never as 0
    const gemini = page.getByTestId('report-providers').getByRole('row', { name: /gemini/ });
    await expect(gemini).toContainText('Not reported');
    await expect(gemini).toContainText('no tasks for this provider');
    await expect(gemini).not.toContainText(/\b0\b/);
  });

  test('AC-ANL-01p nothing reported shows Not reported with the reason', async ({ page, api }) => {
    await api.preset('analytics-empty');
    await open(page, '/reports');
    await page.getByLabel('Project').selectOption('digital-hr');
    for (const [id, reason] of [['report-lead-time', 'no finished runs'], ['report-acceptance', 'no decided runs'], ['report-approval-wait', 'no decided approvals'], ['report-cost', 'not reported']]) {
      const section = page.getByTestId(id);
      await expect(section).toContainText('Not reported');
      await expect(section).toContainText(reason);
    }
  });

  test('AC-ANL-01p a range that ends before it starts is refused by the page and never sent', async ({ page, api }) => {
    await open(page, '/reports');
    await page.getByLabel('Project').selectOption('digital-hr');
    await page.getByLabel('To').fill('2026-11-01');
    await page.getByLabel('From').fill('2026-11-05');
    await expect(page.getByRole('alert')).toContainText('From must not be after To');
    expect((await api.gets(/reports\/analytics/)).filter((r) => r.search.includes('from=2026-11-05')).length).toBe(0);
  });

  test('AC-ANL-02g partial cost is labelled on screen', async ({ page, api }) => {
    await api.preset('analytics-partial-cost');
    await open(page, '/reports');
    await page.getByLabel('Project').selectOption('digital-hr');
    await expect(page.getByTestId('report-cost')).toContainText('partial: 4 tasks did not report cost');
  });
});

test.describe('untrusted content on the new screens', () => {
  const rows: { payload: string; field: string; screen: string; shown: boolean; setup: (api: Api, p: string) => Promise<void>; route: string }[] = [
    { payload: '<img src=x onerror=alert(1)>', field: 'a notification text', screen: 'the notification list', shown: true, route: '/',
      setup: (a, p) => a.set(['notifications', 'id=digital-hr:900'], { ...NEW, text: p }) },
    { payload: "<script>fetch('//evil.example')</script>", field: 'a run slug in a notification', screen: 'the notification list', shown: false, route: '/',
      setup: (a, p) => a.set(['notifications', 'id=digital-hr:900'], { ...NEW, run: p, link: `/tasks/${p}` }) },
    { payload: 'javascript:alert(1)', field: 'a notification link', screen: 'the notification list', shown: false, route: '/',
      setup: (a, p) => a.set(['notifications', 'id=digital-hr:900'], { ...NEW, text: 'Link test', link: p }) },
    { payload: '<svg onload=alert(1)>', field: 'a provider name in analytics', screen: 'Reports', shown: true, route: '/reports',
      setup: async (a, p) => {
        await a.set(['analytics', 'digital-hr', 'provider_failure_rate', p], { value: 0.5, failures: 1, tasks: 2 });
      } },
    { payload: '"><iframe src=//evil.example>', field: 'an audit reason', screen: 'the audit tab', shown: true, route: '/projects/digital-hr/audit',
      setup: (a, p) => a.set(['projectData', 'digital-hr', 'audit'], [{ id: 1, actor: 'dev', channel: 'tty', action: 'approve', target: 'leave-balance', before_sha256: 'a'.repeat(64), after_sha256: 'b'.repeat(64), reason: p, at: '2026-11-14T09:00:00Z' }]) },
  ];
  for (const r of rows) {
    test(`AC-SEC-09a payloads from runs are shown as text: ${r.field} on ${r.screen} (${r.payload})`, async ({ page, api }) => {
      await api.preset('notifications');
      const dialogs: string[] = [];
      const left: string[] = [];
      page.on('dialog', (d) => { dialogs.push(d.message()); void d.dismiss(); });
      page.on('request', (q) => { if (/evil\.example/.test(q.url())) left.push(q.url()); });
      await r.setup(api, r.payload);
      await open(page, r.route);
      if (r.screen === 'Reports') await page.getByLabel('Project').selectOption('digital-hr');
      if (r.screen === 'the notification list') {
        await bell(page).click();
        await expect(page.getByTestId('notification').first()).toBeVisible();
      }
      if (r.shown) await expect(page.locator('main, [data-testid="notification-panel"]').first()).toContainText(r.payload);
      if (r.field === 'a notification link' || r.field === 'a run slug in a notification') {
        await page.getByTestId('notification').filter({ hasText: r.field === 'a notification link' ? 'Link test' : 'Specification ready' }).first().click();
        await expect(page).not.toHaveURL(/javascript|evil/i);
      }
      const created = await page.evaluate(() =>
        document.querySelectorAll('main script, main img[src="x"], main svg[onload], main iframe, [data-testid="notification-panel"] img, [data-testid="notification-panel"] iframe, [data-testid="notification-panel"] svg[onload], a[href^="javascript"]').length,
      );
      expect(created).toBe(0);
      await page.evaluate(() => new Promise((res) => requestAnimationFrame(() => res(null))));
      expect(dialogs).toEqual([]);
      expect(left).toEqual([]);
    });
  }

  test('AC-SEC-09c the desktop notification text is plain', async ({ page, api, context }) => {
    await api.preset('notifications');
    await stubBrowser(context, { permission: 'granted', grant: true, enabled: true });
    await open(page, '/');
    await settle(page);
    await arrive(api, { ...NEW, text: '<b>bold</b>' });
    await expect.poll(() => notes(page)).toEqual([{ title: 'Sentinel', body: '<b>bold</b>', tag: 'digital-hr:900' }]);
    const options = await page.evaluate(() => Object.keys(window.__notes[0].opts).sort());
    expect(options).toEqual(['body', 'tag']);
  });
});
