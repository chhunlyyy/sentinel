import { readFileSync } from 'node:fs';
import AxeBuilder from '@axe-core/playwright';
import type { Page } from '@playwright/test';
import { test, expect, open, RUN, SPEC_URL, GHERKIN_URL, tabTo, focusOutlineVisible, activeName, type Api, settle } from './helpers.ts';

const RUN_URL = '/projects/digital-hr/runs/leave-balance';

type Screen = { name: string; theme: 'light' | 'dark'; route: string; wait: string | RegExp; setup?: (api: Api) => Promise<void> };
const screens: Screen[] = [
  { name: 'Overview', theme: 'light', route: '/overview', wait: 'Overview' },
  { name: 'Overview', theme: 'dark', route: '/overview', wait: 'Overview' },
  { name: 'Projects', theme: 'light', route: '/projects', wait: 'Projects' },
  { name: 'Configuration of digital-hr', theme: 'light', route: '/projects/digital-hr/configuration', wait: 'Configuration' },
  { name: 'Health checks', theme: 'light', route: '/settings/health', wait: 'Health checks' },
  { name: 'Create task', theme: 'light', route: '/tasks/new', wait: 'Create task' },
  { name: 'Create task', theme: 'dark', route: '/tasks/new', wait: 'Create task' },
  { name: 'My Approvals', theme: 'light', route: '/approvals', wait: 'My Approvals', setup: (a) => a.preset('approvals') },
  { name: 'Specification review', theme: 'light', route: SPEC_URL, wait: 'Specification review', setup: (a) => a.preset('approvals') },
  { name: 'Specification review', theme: 'dark', route: SPEC_URL, wait: 'Specification review', setup: (a) => a.preset('approvals') },
  { name: 'Gherkin review', theme: 'light', route: GHERKIN_URL, wait: 'Gherkin review', setup: (a) => a.preset('gherkin-review') },
  { name: 'Run workflow graph', theme: 'light', route: `${RUN_URL}/workflow`, wait: 'Workflow' },
  { name: 'Run workflow graph', theme: 'dark', route: `${RUN_URL}/workflow`, wait: 'Workflow' },
  { name: 'Task log', theme: 'dark', route: `${RUN_URL}/log/t-green1`, wait: 'Log of t-green1' },
  { name: 'Verification', theme: 'light', route: `${RUN_URL}/verification`, wait: 'Verification', setup: (a) => a.preset('reviewing') },
  { name: 'Changes with a split diff', theme: 'light', route: `${RUN_URL}/changes?repo=backend&path=src%2Fmain%2FLeave.java&mode=split`, wait: 'Changes' },
  { name: 'Changes with a split diff', theme: 'dark', route: `${RUN_URL}/changes?repo=backend&path=src%2Fmain%2FLeave.java&mode=split`, wait: 'Changes' },
  { name: 'Trace', theme: 'light', route: `${RUN_URL}/trace`, wait: 'Trace' },
  { name: 'Factory floor', theme: 'light', route: '/floor', wait: 'Factory floor' },
  { name: 'Factory floor', theme: 'dark', route: '/floor', wait: 'Factory floor' },
  { name: 'Factory floor with a waiting gate', theme: 'light', route: '/floor', wait: 'Factory floor', setup: (a) => a.preset('approvals') },
  { name: 'Tasks', theme: 'light', route: '/tasks', wait: 'Tasks' },
  { name: 'Runs', theme: 'light', route: '/runs', wait: 'Runs' },
  { name: 'Quality', theme: 'light', route: '/quality', wait: 'Quality' },
  { name: 'Reports', theme: 'light', route: '/reports', wait: 'Reports' },
  { name: 'Reports', theme: 'dark', route: '/reports', wait: 'Reports' },
  { name: 'Knowledge', theme: 'light', route: '/projects/digital-hr/knowledge', wait: 'Team knowledge' },
  { name: 'Settings, installation', theme: 'light', route: '/settings/installation', wait: /Installation|Settings/ },
  { name: 'Settings, providers', theme: 'light', route: '/settings/providers', wait: /Providers|Settings|Orchestrator/ },
  { name: 'Run overview', theme: 'light', route: RUN_URL, wait: /leave-balance|Leave balance/i },
  {
    name: 'Session ended', theme: 'light', route: '/', wait: 'Session ended',
    setup: (a) => a.rule({ method: 'GET', path: 're:^/api/v1/(?!session)', status: 401, body: { error: { code: 'E_AUTH', message: 'authentication required', details: {} } } }),
  },
];

test.describe('automated accessibility checks', () => {
  for (const s of screens) {
    test(`AC-DSH-01e REQ-DSH-07 no serious or critical axe violation: ${s.name} (${s.theme})`, async ({ page, api }) => {
      await s.setup?.(api);
      await page.emulateMedia({ colorScheme: s.theme });
      await open(page, s.route);
      await expect(page.getByRole('heading', { name: s.wait, exact: false }).first()).toBeVisible();
      await settle(page);
      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
      const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
      expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([]);
    });
  }
});

const AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

async function noSeriousViolation(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([]);
}

test.describe('header, menus and dialogs (accessibility)', () => {
  test('AC-DSH-01e the top header has one banner, one named main navigation, one main region and a named status', async ({ page }) => {
    await open(page, '/floor');
    await expect(page.getByRole('heading', { name: 'Factory floor', exact: true })).toBeVisible();
    await expect(page.getByRole('banner')).toHaveCount(1);
    await expect(page.getByRole('main')).toHaveCount(1);
    await expect(page.getByRole('navigation', { name: 'Main' })).toHaveCount(1);
    await expect(page.getByRole('link', { name: 'Sentinel home' })).toBeVisible();
    await expect(page.getByRole('status').filter({ hasText: /Connected/ })).toHaveCount(1);
    // every button and link in the header has an accessible name
    const unnamed = await page.getByRole('banner').locator('button, a').evaluateAll((els) =>
      els.filter((e) => !((e.getAttribute('aria-label') ?? '').trim() || (e.textContent ?? '').trim())).map((e) => e.outerHTML.slice(0, 80)));
    expect(unnamed).toEqual([]);
    await noSeriousViolation(page);
  });

  test('AC-DSH-01e the More menu is a named toggle that reports its state, opens its links and closes with Escape', async ({ page }) => {
    await open(page, '/floor');
    const more = page.getByRole('button', { name: 'More' });
    await expect(more).toHaveAttribute('aria-expanded', 'false');
    await more.click();
    await expect(more).toHaveAttribute('aria-expanded', 'true');
    const nav = page.getByRole('navigation', { name: 'Main' });
    for (const name of ['Overview', 'Tasks', 'Quality']) await expect(nav.getByRole('link', { name, exact: true })).toBeVisible();
    await noSeriousViolation(page);
    await page.keyboard.press('Escape');
    await expect(more).toHaveAttribute('aria-expanded', 'false');
    await expect(nav.getByRole('link', { name: 'Quality', exact: true })).toHaveCount(0);
  });

  test('AC-DSH-01e the notification list opened from the bell has no serious violation', async ({ page }) => {
    await open(page, '/floor');
    await expect(page.getByRole('heading', { name: 'Factory floor', exact: true })).toBeVisible();
    await page.getByRole('button', { name: /Notifications/ }).click();
    await expect(page.getByTestId('notification-panel')).toBeVisible();
    await noSeriousViolation(page);
  });

  test('AC-DSH-01e the factory floor regions are named and its cancel dialog is a labelled modal with no serious violation', async ({ page }) => {
    await open(page, '/floor');
    await expect(page.getByRole('region', { name: 'Factory network' })).toBeVisible();
    await expect(page.getByRole('group', { name: 'Tasks on the floor' })).toBeVisible();
    const side = page.getByRole('complementary', { name: 'Selected station' });
    await expect(side).toBeVisible();
    // every station on the canvas is a named toggle button
    const stations = page.getByRole('region', { name: 'Factory network' }).getByRole('button');
    expect(await stations.count()).toBeGreaterThan(3);
    for (const b of await stations.all()) expect((await b.getAttribute('aria-pressed')) !== null || ((await b.getAttribute('aria-label')) ?? (await b.textContent()) ?? '').trim().length > 0).toBeTruthy();
    await side.getByRole('button', { name: 'Cancel', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toHaveAccessibleName(/\S/);
    await noSeriousViolation(page);
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
  });

  test('AC-DSH-01e the factory pause button is named and states what it does', async ({ page }) => {
    await open(page, '/floor');
    await expect(page.getByRole('button', { name: /^(Pause|Resume) factory$/ })).toBeVisible();
    await expect(page.getByRole('banner').getByText(/Factory (running|paused)/).first()).toBeVisible();
  });
});

test.describe('keyboard use', () => {
  test('AC-DSH-01g approving a specification with the keyboard only', async ({ page, api }) => {
    await api.preset('approvals');
    const outlines: boolean[] = [];
    await open(page, '/overview');
    await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible();
    await tabTo(page, /^Approvals/, 40, outlines);
    await page.keyboard.press('Enter');
    // a route change moves focus to the main area and sets the page title (finding: focus and title on navigation)
    await expect(page.getByRole('main')).toBeFocused();
    await expect(page).toHaveTitle('My Approvals - Sentinel');
    await tabTo(page, /leave-balance.*specification/i, 40, outlines);
    await page.keyboard.press('Enter');
    await expect(page.getByRole('main')).toBeFocused();
    await expect(page.getByTestId('review-version')).toBeVisible();
    await tabTo(page, 'Approve version 2', 80, outlines);
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('action-result')).toBeFocused();
    expect(await page.getByTestId('action-result').getAttribute('role')).toBe('status');
    expect(await api.posts(/approvals$/)).toHaveLength(1);
    expect(outlines.every(Boolean)).toBe(true);
  });

  test('AC-DSH-01h cancelling a run and creating a task with the keyboard only', async ({ page, api }) => {
    await open(page, '/tasks/new');
    await expect(page.getByLabel('Slug')).toBeVisible();
    await tabTo(page, 'Project');
    await page.keyboard.type('digital-hr');
    await tabTo(page, 'Slug');
    await page.keyboard.type('kbd-task');
    await tabTo(page, 'Request');
    await page.keyboard.type('Created with the keyboard');
    await tabTo(page, 'Type');
    await page.keyboard.type('feature');
    await tabTo(page, 'Create task');
    await page.keyboard.press('Enter');
    await expect(page.getByRole('heading', { name: 'kbd-task', exact: true })).toBeVisible();
    await open(page, RUN_URL);
    await expect(page.getByRole('button', { name: 'Cancel run', exact: true })).toBeEnabled();
    await tabTo(page, 'Cancel run');
    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press('Tab');
      expect(await page.evaluate(() => !!document.activeElement?.closest('dialog,[role=dialog]'))).toBe(true);
    }
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    expect(await activeName(page)).toBe('Cancel run');
    expect(await api.posts(/control$/)).toHaveLength(0);
    await page.keyboard.press('Enter');
    await tabTo(page, 'Cancel run');
    expect(await page.evaluate(() => !!document.activeElement?.closest('dialog,[role=dialog]'))).toBe(true);
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('action-result')).toBeVisible();
    expect(await api.posts(/tasks$/)).toHaveLength(1);
    expect(await api.posts(/control$/)).toHaveLength(1);
  });

  for (const route of ['/', '/tasks', SPEC_URL]) {
    test(`AC-DSH-01i the page skips to its content and has no keyboard trap: ${route}`, async ({ page, api }) => {
      await api.preset('approvals');
      await open(page, route);
      await expect(page.getByRole('main')).toBeVisible();
      await settle(page);
      await page.keyboard.press('Tab');
      expect(await activeName(page)).toBe('Skip to content');
      expect(await focusOutlineVisible(page)).toBe(true);
      await page.keyboard.press('Enter');
      expect(await page.evaluate(() => document.activeElement?.tagName.toLowerCase() === 'main' || !!document.activeElement?.closest('main'))).toBe(true);
      // tab through the whole page: focus must leave the document (or wrap) within a bounded number of presses
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      let left = false;
      for (let i = 0; i < 250 && !left; i++) {
        await page.keyboard.press('Tab');
        left = await page.evaluate(() => document.activeElement === document.body || document.activeElement === null);
        if (!left && (await activeName(page)) === 'Skip to content' && i > 2) left = true;
      }
      expect(left).toBe(true);
    });
  }
});

test.describe('labels and announcements', () => {
  const unnamed = async (page: Page) =>
    page.evaluate(() => {
      const out: string[] = [];
      for (const el of Array.from(document.querySelectorAll('input, select, textarea, button'))) {
        const e = el as HTMLInputElement;
        if (e.type === 'hidden' || !(e.offsetWidth || e.offsetHeight || e.getClientRects().length)) continue;
        const name =
          e.getAttribute('aria-label') ||
          (e.getAttribute('aria-labelledby') ? e.getAttribute('aria-labelledby')!.split(' ').map((i) => document.getElementById(i)?.textContent ?? '').join('') : '') ||
          (e.labels && e.labels.length ? Array.from(e.labels).map((l) => l.textContent).join('') : '') ||
          (e.tagName === 'BUTTON' ? e.textContent : '') ||
          e.getAttribute('title') || '';
        if (!name || !name.trim()) out.push(e.outerHTML.slice(0, 80));
      }
      return out;
    });

  test('AC-DSH-01j every form control has a label', async ({ page, api }) => {
    await api.preset('approvals');
    await open(page, '/tasks/new');
    await page.getByLabel('Project').selectOption('digital-hr');
    await expect(page.getByLabel('Slug')).toBeVisible();
    expect(await unnamed(page)).toEqual([]);
    await page.getByLabel('Slug').fill('Bad Slug');
    const slug = page.getByLabel('Slug');
    await expect(slug).toHaveAttribute('aria-invalid', 'true');
    const describedBy = await slug.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(await page.locator(`#${describedBy}`).textContent()).toContain('Use lower-case letters');
    await open(page, SPEC_URL);
    expect(await unnamed(page)).toEqual([]);
    await page.getByRole('button', { name: 'Request changes' }).click();
    expect(await unnamed(page)).toEqual([]);
    await page.getByRole('button', { name: 'Cancel' }).click();
    await page.getByRole('button', { name: 'Reject run…' }).click();
    expect(await unnamed(page)).toEqual([]);
    await page.getByRole('button', { name: 'Cancel' }).click();
    await open(page, RUN_URL);
    await page.getByRole('button', { name: 'Cancel run', exact: true }).click();
    expect(await unnamed(page)).toEqual([]);
    await page.keyboard.press('Escape');
    for (const r of ['/tasks', '/projects/digital-hr/runs', `${RUN_URL}/workflow`, GHERKIN_URL]) {
      await open(page, r);
      await settle(page);
      expect(await unnamed(page), r).toEqual([]);
    }
  });

  test('AC-DSH-01k live changes are announced politely', async ({ page, api }) => {
    await open(page, RUN_URL);
    await expect(page.getByTestId('connection-status')).toHaveText('Connected');
    await expect(page.getByTestId('connection-status')).toHaveAttribute('role', 'status');
    await api.set([...RUN('leave-balance'), 'workflow', 'nodes', 'id=t-green1', 'state'], 'FAILED');
    await api.event('task.state_changed', { id: 5, type: 'task.state_changed', at: '2026-11-14T09:40:00Z', project: 'digital-hr', run: 'leave-balance', task: 't-green1', actor: { kind: 'engine', name: 'engine', channel: 'engine' }, payload: {} });
    const live = page.locator('[aria-live="polite"]').filter({ hasText: 'tdd_green' });
    await expect(live).toContainText('FAILED');
  });
});

const PAYLOADS = {
  script: '<script>alert(1)</script>',
  img: '<img src=x onerror=alert(1)>',
  svg: '<svg onload=alert(1)>',
  iframe: '<iframe src=//evil.example>',
  pre: "</pre><script>fetch('//evil.example')</script>",
  anchor: '<a href=javascript:alert(1)>click</a>',
  bold: '<b onmouseover=alert(1)>x</b>',
  style: '<style>body{display:none}</style>',
  tpl: "{{constructor.constructor('alert(1)')()}}",
};

test.describe('untrusted content is rendered as text', () => {
  const rows: { place: string; payload: string; route: string; setup: (api: Api, p: string) => Promise<void>; literal?: boolean; extra?: (page: Page) => Promise<void> }[] = [
    { place: 'the specification text of version 2', payload: PAYLOADS.script, route: SPEC_URL, setup: (a, p) => a.set([...RUN('leave-balance'), 'specification', 'current', 'text'], `# Spec\n${p}`) },
    { place: 'a Gherkin scenario name', payload: PAYLOADS.img, route: GHERKIN_URL, setup: (a, p) => a.set([...RUN('leave-balance'), 'gherkin', 'features', 0, 'scenarios', 0, 'name'], p) },
    { place: 'a line of the log of t-green1', payload: PAYLOADS.svg, route: `${RUN_URL}/log/t-green1`, setup: (a, p) => a.set([...RUN('leave-balance'), 'logs', 't-green1', 'lines'], [p]) },
    { place: 'a line of the diff of Leave.java', payload: PAYLOADS.iframe, route: `${RUN_URL}/changes?repo=backend&path=src%2Fmain%2FLeave.java&mode=inline`, setup: (a, p) => a.set([...RUN('leave-balance'), 'diffs', 'backend:src/main/Leave.java', 'hunks', 0, 'lines', 1, 'text'], p) },
    { place: 'the output of evidence a-out1', payload: PAYLOADS.pre, route: `${RUN_URL}/evidence/e-rem-red`, setup: (a, p) => a.set([...RUN('leave-balance'), 'artifacts', 'a-out1', 'content'], p) },
    { place: 'the request text of run leave-balance', payload: PAYLOADS.anchor, route: RUN_URL, setup: (a, p) => a.set([...RUN('leave-balance'), 'detail', 'request'], p) },
    { place: 'an approval comment', payload: PAYLOADS.bold, route: SPEC_URL, setup: (a, p) => a.set([...RUN('leave-balance'), 'specification', 'versions', 0, 'comment'], p),
      extra: async (page) => { await page.getByRole('tab', { name: 'Versions' }).click(); } },
    { place: 'a project name', payload: PAYLOADS.style, route: '/projects', setup: (a, p) => a.set(['projects', 'id=payroll', 'name'], p) },
    { place: 'an error message of an API answer', payload: PAYLOADS.img, route: `${RUN_URL}/workflow`, setup: (a, p) => a.rule({ method: 'GET', path: '/api/v1/tasks/leave-balance/workflow', status: 422, body: { error: { code: 'E_PRECONDITION', message: p, details: {} } } }) },
    { place: 'a finding text in the verification view', payload: PAYLOADS.tpl, route: `${RUN_URL}/verification`, setup: (a, p) => a.set([...RUN('leave-balance'), 'verification', 'acceptance', 'reasons'], [{ text: p, view: 'verification' }]) },
    { place: 'a run reason shown after an event refetch', payload: PAYLOADS.script, route: RUN_URL, literal: false, setup: async () => {} },
  ];
  for (const r of rows) {
    test(`AC-INS-06c markup in run content is shown literally and never runs: ${r.place}`, async ({ page, api }) => {
      await api.preset('approvals');
      await api.preset('reviewing');
      const dialogs: string[] = [];
      const evil: string[] = [];
      page.on('dialog', (d) => { dialogs.push(d.message()); void d.dismiss(); });
      page.on('request', (q) => { if (q.url().includes('evil.example')) evil.push(q.url()); });
      await r.setup(api, r.payload);
      await open(page, r.route);
      await r.extra?.(page);
      if (r.literal === false) {
        await settle(page);
        // the page shows only REST answers: the hostile text arrives through the refetch the event causes, and the event payload is never shown
        await api.set([...RUN('leave-balance'), 'detail', 'state'], 'NEEDS_HUMAN');
        await api.set([...RUN('leave-balance'), 'detail', 'reason'], r.payload);
        await api.event('run.state_changed', { id: 7, type: 'run.state_changed', at: '2026-11-14T09:40:00Z', project: 'digital-hr', run: 'leave-balance', task: null, actor: { kind: 'engine', name: 'engine', channel: 'engine' }, payload: { reason: r.payload } });
        await expect(page.getByRole('main')).toContainText(r.payload);
      } else {
        await expect(page.getByRole('main')).toContainText(r.payload);
      }
      const created = await page.evaluate(() =>
        document.querySelectorAll('main script, main img[src="x"], main svg[onload], main iframe, main b[onmouseover], main style, main a[href^="javascript"]').length,
      );
      expect(created).toBe(0);
      await expect(page.locator('body')).toBeVisible();
      expect(await page.evaluate(() => getComputedStyle(document.body).display)).not.toBe('none');
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(null))));
      expect(dialogs).toEqual([]);
      expect(evil).toEqual([]);
    });
  }

  for (const link of ['javascript:alert(1)', 'data:text/html;base64,PHNjcmlwdD4=', 'https://evil.example/x']) {
    test(`AC-INS-06d links from run content are never script or remote links: ${link}`, async ({ page, api }) => {
      await api.preset('approvals');
      await api.set([...RUN('leave-balance'), 'specification', 'current', 'text'], `# Spec\nSee ${link} for details\n[click](${link})`);
      await open(page, SPEC_URL);
      const text = page.getByTestId('spec-text');
      await expect(text).toContainText(link);
      await expect(text.locator('a')).toHaveCount(0);
      expect(await page.locator(`a[href="${link}"]`).count()).toBe(0);
    });
  }

  test('AC-INS-06f the built page runs under the server CSP', async ({ page }) => {
    const violations: string[] = [];
    await page.addInitScript(() => {
      (window as unknown as { __csp: string[] }).__csp = [];
      document.addEventListener('securitypolicyviolation', (e) => (window as unknown as { __csp: string[] }).__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
    });
    page.on('console', (m) => { if (/content security policy/i.test(m.text())) violations.push(m.text()); });
    const resp = await page.goto('/');
    expect(resp!.headers()['content-security-policy']).toBe("default-src 'self'; frame-ancestors 'none'");
    for (const s of ['/', '/projects', '/projects/digital-hr/configuration', '/tasks/new', '/approvals', SPEC_URL, GHERKIN_URL, `${RUN_URL}/workflow`, `${RUN_URL}/tdd`, `${RUN_URL}/verification`, `${RUN_URL}/changes?repo=backend&path=src%2Fmain%2FLeave.java&mode=split`, `${RUN_URL}/trace`, `${RUN_URL}/log/t-green1`, '/settings/health']) {
      await open(page, s);
      await settle(page);
    }
    expect(violations).toEqual([]);
    expect(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp)).toEqual([]);
    const html = readFileSync(new URL('../../sentinel/dashboard_dist/index.html', import.meta.url), 'utf8');
    expect(html).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/i);
    expect(html).not.toMatch(/<style[\s>]/i);
    expect(html).not.toMatch(/\sstyle\s*=/i);
    expect(html).not.toMatch(/\son[a-z]+\s*=/i);
  });

  test('AC-INS-06g values from the address and run content never reach the API path unencoded', async ({ page, api }) => {
    const evil = '../../../../home/dev/.config/sentinel/server.json';
    // a hostile task id in the address bar
    await open(page, `${RUN_URL}/log/${encodeURIComponent(evil)}`);
    await expect(page.getByText('Log not available')).toBeVisible();
    // a hostile file path in the address bar
    await open(page, `${RUN_URL}/changes?repo=backend&path=${encodeURIComponent(evil)}&mode=inline`);
    await expect(page.getByText('Diff of')).toBeVisible();
    await api.idle(300);
    const sent = (await api.requests()).filter((r) => /\/logs\/|changes\/diff/.test(r.path));
    expect(sent.length).toBeGreaterThanOrEqual(2);
    for (const r of sent) {
      // the value stays one path segment: its slashes are percent-encoded, so it cannot climb out of /logs/
      if (/\/logs\//.test(r.path)) {
        expect(r.path.split('/')).toHaveLength('/api/v1/tasks/leave-balance/logs/x'.split('/').length);
        expect(r.path).toContain('%2F');
      }
      // in a query value every slash is encoded too
      if (/changes\/diff/.test(r.path)) {
        expect(new URLSearchParams(r.search).get('path')).toBe(evil);
        expect(r.search).not.toContain('/');
      }
    }
  });
});
