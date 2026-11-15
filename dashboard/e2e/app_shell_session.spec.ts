import { readFileSync } from 'node:fs';
import { test, expect, open, nav, heading, createTask, control, decide, SPEC_URL, stateOf, CSRF, SESSION, settle } from './helpers.ts';

test.describe('app shell: navigation', () => {
  test('AC-DSH-01a the main navigation', async ({ page }) => {
    await open(page, '/');
    const n = nav(page);
    for (const name of ['Overview', 'Projects', 'Tasks', 'My Approvals', 'Runs', 'Quality', 'Reports', 'Settings']) {
      await expect(n.getByRole('link', { name: new RegExp(`^${name}`) })).toBeVisible();
    }
    // Phase H: Reports is a menu entry; the notification bell is a button, not a menu entry
    for (const name of ['Notifications', 'Agents', 'Providers', 'Users and Permissions']) {
      await expect(n.getByRole('link', { name })).toHaveCount(0);
    }
    await expect(n.getByRole('link', { name: 'Overview', exact: true })).toHaveAttribute('aria-current', 'page');
  });

  const routes: [string, string][] = [
    ['/#/projects', 'Projects'],
    ['/#/projects/digital-hr', 'digital-hr'],
    ['/#/projects/digital-hr/configuration', 'Configuration'],
    ['/#/tasks', 'Tasks'],
    ['/#/tasks/new', 'Create task'],
    ['/#/approvals', 'My Approvals'],
    ['/#/projects/digital-hr/runs/leave-balance', 'leave-balance'],
    ['/#/projects/digital-hr/runs/leave-balance/trace', 'Trace'],
    ['/#/settings/installation', 'Sentinel installation'],
  ];
  for (const [route, title] of routes) {
    test(`AC-DSH-01b every screen has its own address ${route}`, async ({ page }) => {
      await page.goto(route);
      await expect(heading(page, title)).toBeVisible();
      await page.reload();
      await expect(heading(page, title)).toBeVisible();
    });
  }

  const unknown: [string, string][] = [
    ['/#/no-such-screen', 'Page not found'],
    ['/#/projects/no-such-project', 'Project not found'],
    ['/#/projects/digital-hr/runs/no-such-run', 'Run not found'],
  ];
  for (const [route, message] of unknown) {
    test(`AC-DSH-01c unknown screens and objects ${route}`, async ({ page, api }) => {
      await page.goto(route);
      await expect(page.getByText(message)).toBeVisible();
      await expect(page.getByRole('main').getByRole('link', { name: 'Overview' })).toBeVisible();
      const reqs = await api.requests();
      expect(reqs.filter((r) => r.method !== 'GET')).toEqual([]);
    });
  }

  test('AC-DSH-01d a slug used in two projects opens the run of the project in the address', async ({ page, api }) => {
    await api.preset('dup-slug');
    await open(page, '/projects/payroll/runs/leave-balance');
    await expect(page.getByTestId('run-header')).toContainText('payroll');
    const runReqs = (await api.requests()).filter((r) => /^\/api\/v1\/tasks\/leave-balance/.test(r.path));
    expect(runReqs.length).toBeGreaterThan(0);
    for (const r of runReqs) expect(new URLSearchParams(r.search).get('project')).toBe('payroll');
  });
});

test.describe('app shell: session and CSRF', () => {
  test('AC-SEC-01y the app reads the CSRF value once and sends it only on mutating calls', async ({ page, api }) => {
    await createTask(page, { slug: 'csrf-check' });
    await page.getByRole('button', { name: 'Create task' }).click();
    await expect(heading(page, 'csrf-check')).toBeVisible();
    await open(page, '/projects/digital-hr/runs/leave-balance');
    await control(page, 'Cancel run');
    await expect(stateOf(page)).toContainText('CANCELLED');
    const reqs = await api.requests();
    expect(reqs.filter((r) => r.path === '/api/v1/session')).toHaveLength(1);
    const posts = reqs.filter((r) => r.method === 'POST');
    expect(posts.length).toBe(2);
    for (const p of posts) {
      expect(p.headers['x-sentinel-csrf']).toBe(CSRF);
      expect(p.headers['content-type']).toMatch(/^application\/json/);
    }
    for (const g of reqs.filter((r) => r.method === 'GET')) expect(g.headers['x-sentinel-csrf']).toBeUndefined();
    const stored = await page.evaluate(async () => {
      const dbs = (await indexedDB.databases?.()) ?? [];
      return JSON.stringify({ l: { ...localStorage }, s: { ...sessionStorage }, c: document.cookie, dbs });
    });
    expect(stored).not.toContain(CSRF);
    expect(stored).not.toContain(SESSION);
    expect(JSON.parse(stored).dbs).toEqual([]);
  });

  const requests: [string, () => Promise<void>][] = [];
  for (const kind of ['GET /api/v1/tasks/leave-balance', 'the event stream reconnect', 'POST /api/v1/tasks/leave-balance/control']) {
    test(`AC-SEC-01z an ended session stops the app: ${kind}`, async ({ page, api }) => {
      void requests;
      const err = { error: { code: 'E_AUTH', message: 'authentication required', details: {} } };
      if (kind.startsWith('GET')) await api.rule({ method: 'GET', path: '/api/v1/tasks/leave-balance', status: 401, body: err });
      if (kind.startsWith('the event')) await api.rule({ method: 'GET', path: '/api/v1/events', status: 401, body: err });
      if (kind.startsWith('POST')) await api.rule({ method: 'POST', path: '/api/v1/tasks/leave-balance/control', status: 401, body: err });
      await open(page, '/projects/digital-hr/runs/leave-balance');
      if (kind.startsWith('POST')) {
        await expect(page.getByRole('button', { name: 'Cancel run', exact: true })).toBeEnabled();
        await control(page, 'Cancel run', { comment: 'secret-form-content' });
      }
      await expect(page.getByText('Session ended')).toBeVisible();
      await expect(page.getByText('Run sentinel dashboard in a terminal to open a new session')).toBeVisible();
      const mark = await api.mark();
      await api.idle(1000);
      expect(await api.since(mark)).toEqual([]);
      const posts = await api.posts(/control$/);
      expect(posts.length).toBeLessThanOrEqual(1);
    });
  }

  test('AC-DSH-04c a refused CSRF value is renewed but the action is not resent', async ({ page, api }) => {
    await api.rule({ method: 'POST', path: '/api/v1/tasks/leave-balance/control', status: 403, body: { error: { code: 'E_CSRF', message: 'bad csrf', details: {} } }, times: 1 });
    await open(page, '/projects/digital-hr/runs/leave-balance');
    await expect(page.getByRole('button', { name: 'Cancel run', exact: true })).toBeEnabled();
    await control(page, 'Cancel run', { comment: 'wrong ticket' });
    await expect(page.getByText('The action was not sent. Check the run state and try again.')).toBeVisible();
    await expect(stateOf(page)).toContainText('EXECUTING');
    const reqs = await api.requests();
    expect(reqs.filter((r) => r.path === '/api/v1/session').length).toBe(2);
    const idx = reqs.findIndex((r) => r.method === 'POST');
    expect(reqs.filter((r) => r.method === 'POST')).toHaveLength(1);
    expect(reqs.slice(idx + 1).some((r) => r.method === 'GET' && r.path === '/api/v1/tasks/leave-balance')).toBe(true);
  });
});

test.describe('app shell: no success before the API confirms', () => {
  type Row = { name: string; request: RegExp; shown: string; setup?: (api: import('./helpers.ts').Api) => Promise<void>; act: (page: import('@playwright/test').Page) => Promise<void>; pendingButton?: string; pre?: (page: import('@playwright/test').Page) => Promise<void> };
  const rows: Row[] = [
    {
      name: 'approve specification version 2', request: /\/tasks\/leave-balance\/approvals$/, shown: 'Specification approved',
      setup: (api) => api.preset('approvals'),
      pre: (page) => open(page, SPEC_URL),
      act: (page) => decide(page, 'Approve', '3f9a0c12', 'Approve version 2'),
    },
    {
      name: 'create task "leave-report"', request: /\/projects\/digital-hr\/tasks$/, shown: 'leave-report created: CREATED',
      pre: (page) => createTask(page, { slug: 'leave-report' }),
      act: (page) => page.getByRole('button', { name: 'Create task' }).click(),
    },
    {
      name: 'cancel run', request: /\/tasks\/leave-balance\/control$/, shown: 'Run state CANCELLED',
      pre: (page) => open(page, '/projects/digital-hr/runs/leave-balance'),
      act: (page) => control(page, 'Cancel run'),
    },
    {
      name: 'retry task t-doc1', request: /\/tasks\/leave-balance\/control$/, shown: 'Retry queued',
      setup: (api) => api.set(['runs', 'digital-hr/leave-balance', 'workflow', 'nodes', 'id=t-doc1', 'state'], 'FAILED'),
      pre: (page) => open(page, '/projects/digital-hr/runs/leave-balance'),
      act: (page) => control(page, 'Retry t-doc1'),
    },
    {
      name: 'resume run', request: /\/tasks\/leave-balance\/control$/, shown: 'Run state EXECUTING',
      setup: async (api) => {
        await api.set(['runs', 'digital-hr/leave-balance', 'detail', 'state'], 'NEEDS_HUMAN');
        await api.set(['runs', 'digital-hr/leave-balance', 'detail', 'reason'], 'red retry cap reached');
      },
      pre: (page) => open(page, '/projects/digital-hr/runs/leave-balance'),
      act: (page) => control(page, 'Resume', { comment: 'test data fixed' }),
    },
    {
      name: 'confirm acceptance of "leave-form"', request: /\/tasks\/leave-form\/acceptance$/, shown: 'Acceptance confirmed',
      pre: (page) => open(page, '/projects/digital-hr/runs/leave-form/acceptance'),
      act: (page) => page.getByLabel('Type the first 8 characters of the sha256 to confirm').fill('77ab01cd').then(() => page.getByRole('button', { name: 'Confirm acceptance' }).click()),
    },
  ];
  for (const row of rows) {
    test(`AC-DSH-04a pending, then the stored state: ${row.name}`, async ({ page, api }) => {
      await row.setup?.(api);
      await api.rule({ method: 'POST', path: `re:${row.request.source}`, delayMs: 2000, times: 1, passthrough: true });
      await row.pre!(page);
      await row.act(page);
      const sending = page.getByRole('button', { name: 'Sending' });
      await expect(sending).toBeVisible();
      await expect(sending).toBeDisabled();
      await expect(page.getByText(row.shown)).toHaveCount(0);
      await expect(page.getByText(row.shown)).toBeVisible({ timeout: 6000 });
    });
  }

  const failures: [string, 'drop' | 'hang' | 'status', number?, string?, string?][] = [
    ['a dropped connection', 'drop', undefined, undefined, 'Not confirmed: the server did not answer. Check the run state.'],
    ['no answer within 30 seconds', 'hang', undefined, undefined, 'Not confirmed: the server did not answer. Check the run state.'],
    ['500 and E_INTERNAL', 'status', 500, 'E_INTERNAL', 'Not confirmed: server error. See the terminal running sentinel dashboard.'],
    ['409 and E_TRANSITION', 'status', 409, 'E_TRANSITION', 'Refused: the run moved on.'],
  ];
  for (const [name, kind, status, code, message] of failures) {
    test(`AC-DSH-04b a failed or unanswered action is shown as not confirmed: ${name}`, async ({ page, api }) => {
      const path = '/api/v1/tasks/leave-balance/control';
      if (kind === 'drop') await api.rule({ method: 'POST', path, drop: true });
      if (kind === 'hang') await api.rule({ method: 'POST', path, hang: true });
      if (kind === 'status') await api.rule({ method: 'POST', path, status, body: { error: { code, message: 'x', details: {} } } });
      if (kind === 'hang') await page.clock.install();
      await open(page, '/projects/digital-hr/runs/leave-balance');
      await expect(page.getByRole('button', { name: 'Cancel run', exact: true })).toBeEnabled();
      await control(page, 'Cancel run', { comment: 'wrong ticket' });
      if (kind === 'hang') {
        await expect.poll(async () => (await api.posts(/control$/)).length).toBe(1);
        await page.clock.runFor(31_000);
      }
      await expect(page.getByText(message!)).toBeVisible();
      await expect(stateOf(page)).toContainText('EXECUTING');
      const gets = await api.gets(/^\/api\/v1\/tasks\/leave-balance$/);
      expect(gets.length).toBeGreaterThanOrEqual(2);
    });
  }

  test('AC-DSH-04e double clicks send one request', async ({ page, api }) => {
    await api.rule({ method: 'POST', path: 're:/projects/digital-hr/tasks$', delayMs: 500, passthrough: true });
    await createTask(page, { slug: 'double-click' });
    await page.getByRole('button', { name: 'Create task' }).dblclick();
    await expect(heading(page, 'double-click')).toBeVisible();
    expect(await api.posts(/\/projects\/digital-hr\/tasks$/)).toHaveLength(1);
  });
});

test.describe('own origin only', () => {
  test('AC-DSH-06e every request of a full session goes to the server origin', async ({ page, api, baseURL }) => {
    await api.preset('approvals');
    const urls: string[] = [];
    page.on('request', (r) => urls.push(r.url()));
    const screens = ['/', '/projects', '/projects/digital-hr', '/projects/digital-hr/repositories', '/projects/digital-hr/configuration', '/projects/digital-hr/configuration/history', '/projects/digital-hr/audit', '/tasks', '/approvals', '/settings/installation', '/settings/runtime', '/settings/health', '/projects/digital-hr/runs/leave-balance', '/projects/digital-hr/runs/leave-balance/workflow', '/projects/digital-hr/runs/leave-balance/tdd', '/projects/digital-hr/runs/leave-balance/verification', '/projects/digital-hr/runs/leave-balance/changes', '/projects/digital-hr/runs/leave-balance/trace', '/projects/digital-hr/runs/leave-balance/gherkin', '/projects/digital-hr/runs/leave-balance/log/t-green1'];
    for (const s of screens) {
      await open(page, s);
      await settle(page);
    }
    await open(page, SPEC_URL);
    await decide(page, 'Approve', '3f9a0c12', 'Approve version 2');
    await expect(page.getByText('Specification approved')).toBeVisible();
    await createTask(page, { slug: 'origin-check' });
    await page.getByRole('button', { name: 'Create task' }).click();
    await expect(heading(page, 'origin-check')).toBeVisible();
    await open(page, '/projects/digital-hr/runs/leave-balance');
    await control(page, 'Cancel run');
    await expect(page.getByText('Run state CANCELLED')).toBeVisible();
    const manifest = JSON.parse(readFileSync(new URL('../../sentinel/dashboard_dist/manifest.json', import.meta.url), 'utf8')) as { files: Record<string, unknown> };
    const origin = new URL(baseURL!).origin;
    for (const u of urls) {
      const url = new URL(u);
      expect(url.origin, u).toBe(origin);
      const ok = url.pathname.startsWith('/api/v1/') || url.pathname === '/' || url.pathname === '/index.html' || url.pathname.slice(1) in manifest.files;
      expect(ok, u).toBe(true);
    }
  });

  test('AC-DSH-01a a screen that throws leaves the shell and the menu usable', async ({ page, api }) => {
    // edges is not a list: the workflow screen throws while it renders
    await api.rule({ method: 'GET', path: '/api/v1/tasks/leave-balance/workflow', status: 200, body: { nodes: [{ id: 'a' }], edges: 5, gates: [] } });
    await open(page, '/projects/digital-hr/runs/leave-balance/workflow');
    await expect(page.getByTestId('screen-error')).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Projects', exact: true }).click();
    await expect(page.getByTestId('screen-error')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  });
});
