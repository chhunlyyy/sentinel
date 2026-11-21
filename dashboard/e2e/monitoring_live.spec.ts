import { test, expect, open, control, RUN, stateOf, type Api, settle } from './helpers.ts';

const RUN_URL = '/projects/digital-hr/runs/leave-balance';
const WF = [...RUN('leave-balance'), 'workflow'];
const CONTROL = /\/tasks\/leave-balance\/control$/;

const node = (id: string, role: string, state: string, extra: Record<string, unknown> = {}) => ({
  id, role, repo: 'backend', state, adapter: 'cli', provider: 'codex', model: 'gpt-5', attempt: 1, retry_of: null, error_code: null,
  started_at: '2026-11-14T09:01:10Z', finished_at: null, seconds: 42, tokens: 1200, cost: 0.12, reasons: {}, ...extra,
});

test.describe('the run graph', () => {
  test('AC-MON-01f nodes, edges and gates of the run', async ({ page, api }) => {
    await api.set([...WF, 'nodes'], [
      node('t-spec1', 'specifier', 'COMPLETED', { finished_at: '2026-11-14T09:02:00Z' }),
      node('t-green1', 'tdd_green', 'FAILED', { error_code: 'E_EXIT', finished_at: '2026-11-14T09:03:00Z' }),
      node('t-green2', 'tdd_green', 'QUEUED', { retry_of: 't-green1', attempt: 2, started_at: null, seconds: null }),
      node('t-qa1', 'qa', 'WAITING_FOR_INPUT', { adapter: 'native', label: 'waiting for orchestrator' }),
    ]);
    await api.set([...WF, 'edges'], [{ from: 't-spec1', to: 't-green1' }, { from: 't-green1', to: 't-green2' }, { from: 't-spec1', to: 't-qa1' }]);
    await open(page, `${RUN_URL}/workflow`);
    const green = page.getByTestId('node-t-green1');
    for (const t of ['tdd_green', 'backend', 'FAILED', 'cli', 'codex', 'gpt-5', 'attempt 1', '09:01:10', '42s', 'E_EXIT']) await expect(green).toContainText(t);
    await expect(page.getByTestId('node-t-green2')).toContainText('Retry of t-green1');
    await expect(page.getByTestId('node-t-qa1')).toContainText('waiting for orchestrator');
    await expect(page.locator('[data-edge]')).toHaveCount(3);
    await expect(page.locator('[data-edge="t-spec1->t-green1"]')).toHaveCount(1);
    await expect(page.getByTestId('gate-specification')).toContainText('APPROVED');
    await expect(page.getByTestId('gate-gherkin')).toContainText('APPROVED');
  });

  test('AC-MON-01g the graph has a list view with the same content', async ({ page }) => {
    await open(page, `${RUN_URL}/workflow`);
    await page.getByRole('button', { name: 'List' }).click();
    const rows = page.getByTestId('workflow-row');
    // the 4 tasks of the run plus the 7 tasks named by its TDD cycles, as on the real server
    await expect(rows).toHaveCount(11);
    await expect(rows.filter({ hasText: /^t-spec1/ })).toHaveCount(1);
    const green = rows.filter({ hasText: 't-green1' });
    await expect(green).toContainText('Depends on t-red2');
    for (const t of ['tdd_green', 'backend', 'RUNNING', 'cli', 'codex', 'gpt-5', 'attempt 1']) await expect(green).toContainText(t);
  });

  test('AC-MON-01h a run with no tasks yet', async ({ page, api }) => {
    await api.set([...WF, 'nodes'], []);
    await api.set([...WF, 'edges'], []);
    await open(page, `${RUN_URL}/workflow`);
    await expect(page.getByText('No tasks yet')).toBeVisible();
    await expect(page.getByTestId('next-banner')).toContainText('waiting for AI tool');
    expect((await api.gets(/tasks\/leave-balance\/next/)).length).toBeGreaterThan(0);
  });

  test('AC-MON-01i a run with 500 tasks', async ({ page, api }) => {
    const roles = ['tdd_red', 'tdd_green', 'doc', 'qa', 'review'];
    const states = ['COMPLETED', 'RUNNING', 'QUEUED', 'FAILED'];
    const nodes = Array.from({ length: 500 }, (_, i) => node(`t-${i}`, roles[i % 5], states[i % 4]));
    const edges = Array.from({ length: 499 }, (_, i) => ({ from: `t-${i}`, to: `t-${i + 1}` })).filter((_, i) => i % 7 !== 0);
    await api.set([...WF, 'nodes'], nodes);
    await api.set([...WF, 'edges'], edges);
    const t0 = Date.now();
    await open(page, `${RUN_URL}/workflow`);
    await expect(page.getByTestId(/^node-t-/)).toHaveCount(500, { timeout: 2000 });
    expect(Date.now() - t0).toBeLessThan(2500);
    await page.getByLabel('Filter by state').selectOption('FAILED');
    await expect(page.getByTestId(/^node-t-/)).toHaveCount(125);
    await page.getByLabel('Filter by role').selectOption('doc');
    const n = await page.getByTestId(/^node-t-/).count();
    expect(n).toBeGreaterThan(0);
    expect(n).toBeLessThan(125);
  });
});

test.describe('live log tail', () => {
  const LOG = [...RUN('leave-balance'), 'logs', 't-green1'];
  const lines = (n: number, from = 0) => Array.from({ length: n }, (_, i) => `line ${from + i + 1}`);

  test('AC-MON-03d following the log of a running task', async ({ page, api }) => {
    await api.set(LOG, { lines: lines(3), running: true });
    await open(page, `${RUN_URL}/log/t-green1`);
    const box = page.getByTestId('log-box');
    await expect(box).toContainText('line 3');
    await api.set([...LOG, 'lines'], lines(5));
    await expect(box).toContainText('line 5');
    const text = await box.textContent();
    expect((text!.match(/line 3/g) ?? []).length).toBe(1);
    const offsets = (await api.gets(/logs\/t-green1/)).map((r) => new URLSearchParams(r.search).get('offset'));
    expect(offsets[0]).toBe('0');
    expect(offsets.some((o) => o === '21')).toBe(true); // 3 lines of 6 bytes plus newline each
    await api.set([...LOG, 'running'], false);
    await expect(page.getByTestId('log-status')).toContainText('Finished');
    const mark = await api.mark();
    await api.idle(1200);
    expect((await api.since(mark)).filter((r) => /logs/.test(r.path))).toEqual([]);
  });

  test('AC-MON-03e a long log stays usable', async ({ page, api }) => {
    await api.set(LOG, { lines: lines(20000), running: true });
    await open(page, `${RUN_URL}/log/t-green1`);
    const box = page.getByTestId('log-box');
    await expect(box).toContainText('line 20000');
    await expect(page.getByText('Older lines are hidden')).toBeVisible();
    const count = (await box.textContent())!.split('\n').filter(Boolean).length;
    expect(count).toBeLessThanOrEqual(5000);
    await box.evaluate((e) => { e.scrollTop = 0; });
    await expect(page.getByRole('button', { name: 'Follow' })).toBeVisible();
    await page.getByRole('button', { name: 'Follow' }).click();
    await expect(page.getByRole('button', { name: 'Follow' })).toHaveCount(0);
    expect(await box.evaluate((e) => e.scrollHeight - e.scrollTop - e.clientHeight)).toBeLessThan(40);
  });

  test('AC-MON-03f a log that cannot be read', async ({ page, api }) => {
    await api.rule({ method: 'GET', path: '/api/v1/tasks/leave-balance/logs/t-green1', status: 404, body: { error: { code: 'E_NOT_FOUND', message: 'no log', details: {} } } });
    await open(page, `${RUN_URL}/log/t-green1`);
    await expect(page.getByText('Log not available')).toBeVisible();
    const mark = await api.mark();
    await api.idle(1200);
    expect((await api.since(mark)).filter((r) => /logs/.test(r.path))).toEqual([]);
  });
});

async function stateRows(api: Api, rows: Record<string, unknown>) {
  for (const [k, v] of Object.entries(rows)) await api.set([...RUN('leave-balance'), ...k.split('/')], v);
}

// the failed green task of the TDD cycle "carry" is part of the fixture run
const RETRY = 'Retry t-car-green';

test.describe('controls are cancel, resume and retry', () => {
  const buttons = async (page: import('@playwright/test').Page) => (await page.getByTestId('controls').getByRole('button').allTextContents()).map((s) => s.trim()).sort();
  const rows: [string, Record<string, unknown>, string[]][] = [
    ['the run is EXECUTING', {}, ['Cancel run', RETRY]],
    ['the run is NEEDS_HUMAN', { 'detail/state': 'NEEDS_HUMAN', 'detail/reason': 'red retry cap reached' }, ['Cancel run', 'Resume', RETRY]],
    ['task t-doc1 is FAILED', { 'workflow/nodes/id=t-doc1/state': 'FAILED' }, ['Cancel run', 'Retry t-doc1', RETRY]],
    ['task t-red2 is QUEUED', { 'workflow/nodes/id=t-red2/state': 'QUEUED' }, ['Cancel run', 'Cancel task t-red2', RETRY]],
    ['the run is COMPLETED', { 'detail/state': 'COMPLETED', 'workflow/nodes/id=t-green1/state': 'COMPLETED', 'workflow/nodes/id=t-doc1/state': 'COMPLETED' }, []],
    ['the run is CANCELLED', { 'detail/state': 'CANCELLED', 'workflow/nodes/id=t-green1/state': 'CANCELLED', 'workflow/nodes/id=t-doc1/state': 'CANCELLED' }, []],
    ['the run is a 0.1 run', { 'detail/workflow_version': '0.1' }, []],
  ];
  for (const [name, patch, expected] of rows) {
    test(`AC-MON-02j controls offered by run and task state: ${name}`, async ({ page, api }) => {
      await stateRows(api, patch);
      await open(page, RUN_URL);
      await expect(page.getByTestId('run-header')).toBeVisible();
      expect(await buttons(page)).toEqual([...expected].sort());
      await expect(page.getByRole('main').getByRole('button', { name: /pause|request intervention/i })).toHaveCount(0);
    });
  }

  const sends: [string, Record<string, unknown>, string, string | undefined, unknown][] = [
    ['the run is EXECUTING', {}, 'Cancel run', 'wrong ticket', { action: 'cancel', comment: 'wrong ticket' }],
    ['task t-red2 is QUEUED', { 'workflow/nodes/id=t-red2/state': 'QUEUED' }, 'Cancel task t-red2', undefined, { action: 'cancel', task_id: 't-red2' }],
    ['the run is NEEDS_HUMAN', { 'detail/state': 'NEEDS_HUMAN', 'detail/reason': 'red retry cap reached' }, 'Resume', 'test data fixed', { action: 'resume', comment: 'test data fixed' }],
    ['task t-doc1 is FAILED', { 'workflow/nodes/id=t-doc1/state': 'FAILED' }, 'Retry t-doc1', undefined, { action: 'retry', task_id: 't-doc1' }],
  ];
  for (const [name, patch, button, comment, body] of sends) {
    test(`AC-MON-02k each control sends one engine action: ${name}`, async ({ page, api }) => {
      await stateRows(api, patch);
      await open(page, RUN_URL);
      await control(page, button, comment === undefined ? {} : { comment });
      await expect(page.getByTestId('action-result')).toBeVisible();
      const posts = await api.posts(CONTROL);
      expect(posts).toHaveLength(1);
      expect(posts[0].body).toEqual(body);
      await expect(stateOf(page)).not.toHaveText('');
    });
  }

  test('AC-MON-02l resume needs a reason', async ({ page, api }) => {
    await stateRows(api, { 'detail/state': 'NEEDS_HUMAN', 'detail/reason': 'red retry cap reached' });
    await open(page, RUN_URL);
    await page.getByRole('button', { name: 'Resume', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('button', { name: 'Resume', exact: true })).toBeDisabled();
    await expect(dialog.getByText('Say what was fixed')).toBeVisible();
    await dialog.getByLabel('Comment').fill('   ');
    await expect(dialog.getByRole('button', { name: 'Resume', exact: true })).toBeDisabled();
    await dialog.getByLabel('Comment').fill('fixed');
    await expect(dialog.getByRole('button', { name: 'Resume', exact: true })).toBeEnabled();
  });

  test('AC-MON-02m cancelling asks first and names its effect', async ({ page, api }) => {
    await open(page, RUN_URL);
    await page.getByRole('button', { name: 'Cancel run', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('Cancel run leave-balance? 3 running tasks are stopped. This cannot be undone.');
    await expect(dialog.getByRole('button', { name: 'Keep running' })).toBeFocused();
    await dialog.getByRole('button', { name: 'Keep running' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('button', { name: 'Cancel run', exact: true }).click();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(await api.posts(CONTROL)).toEqual([]);
  });

  test('AC-MON-02n a control refused by the engine', async ({ page, api }) => {
    await api.rule({ method: 'POST', path: '/api/v1/tasks/leave-balance/control', status: 409, body: { error: { code: 'E_TRANSITION', message: 'not allowed', details: {} } } });
    await open(page, RUN_URL);
    await control(page, 'Cancel run');
    await expect(page.getByText('Refused: the run moved on.')).toBeVisible();
    await expect(stateOf(page)).toContainText('EXECUTING');
    expect((await api.gets(/^\/api\/v1\/tasks\/leave-balance$/)).length).toBeGreaterThanOrEqual(2);
  });
});

const evt = (type: string, run = 'leave-balance', task: string | null = null, payload: unknown = {}) => ({
  id: 1, type, at: '2026-11-14T09:40:00Z', project: 'digital-hr', run, task, actor: { kind: 'engine', name: 'engine', channel: 'engine' }, payload,
});

test.describe('live updates and reconnect', () => {
  test('AC-DSH-05e events refresh the views they touch', async ({ page, api }) => {
    await open(page, RUN_URL);
    await expect(page.getByTestId('connection-status')).toHaveText('Connected');
    await api.set([...WF, 'nodes', 'id=t-green1', 'state'], 'FAILED');
    const mark = await api.mark();
    await api.event('task.state_changed', evt('task.state_changed', 'leave-balance', 't-green1'));
    await expect.poll(async () => (await api.gets(/^\/api\/v1\/tasks\/leave-balance\/workflow/, mark)).length, { timeout: 1500 }).toBeGreaterThan(0);
    await page.getByRole('link', { name: 'Workflow' }).click();
    await expect(page.getByTestId('node-t-green1')).toContainText('FAILED');
    await api.idle(500); // the refetches of the first event are done
    const mark2 = await api.mark();
    await api.event('task.state_changed', { ...evt('task.state_changed', 'leave-form', 't-x'), run: 'leave-form' });
    await api.idle(500);
    expect((await api.since(mark2)).filter((r) => /tasks\/leave-balance/.test(r.path))).toEqual([]);
  });

  test('AC-DSH-05g the connection drops and comes back', async ({ page, api }) => {
    await open(page, RUN_URL);
    const status = page.getByTestId('connection-status');
    await expect(status).toHaveText('Connected');
    await api.event('task.state_changed', evt('task.state_changed', 'leave-balance', 't-green1'));
    await api.idle(300);
    await api.stream('refuse', 5000);
    await api.stream('drop');
    await expect(status).toHaveText('Connection lost. Reconnecting.', { timeout: 2000 });
    await expect(page.getByRole('button', { name: 'Cancel run', exact: true })).toBeDisabled();
    const mark = await api.mark();
    await expect(status).toHaveText('Connected', { timeout: 12_000 });
    await api.idle(500);
    const after = await api.since(mark);
    expect(after.filter((r) => r.method === 'GET' && r.path === '/api/v1/tasks/leave-balance')).toHaveLength(1);
    const streams = (await api.requests()).filter((r) => r.path === '/api/v1/events');
    expect(streams.some((r) => (r.headers['last-event-id'] ?? '').startsWith('digital-hr:'))).toBe(true);
    await expect(page.getByRole('button', { name: 'Cancel run', exact: true })).toBeEnabled();
  });

  const resyncs: [string, string, string][] = [['digital-hr', 'unknown event id', 'refetch'], ['payroll', 'project unavailable', 'other'], ['digital-hr', 'database restored', 'refetch']];
  for (const [project, reason, outcome] of resyncs) {
    test(`AC-DSH-05h a resync message re-fetches the named projects: ${project} ${reason}`, async ({ page, api }) => {
      await open(page, RUN_URL);
      await expect(page.getByTestId('connection-status')).toHaveText('Connected');
      await settle(page);
      if (outcome === 'other') await api.set(['projects', 'id=payroll', 'status'], 'unavailable');
      const mark = await api.mark();
      await api.event('resync', { project, reason });
      await api.idle(500);
      const after = (await api.since(mark)).filter((r) => r.method === 'GET');
      const mine = after.filter((r) => /digital-hr|tasks\/leave-balance/.test(r.path + r.search));
      if (outcome === 'refetch') {
        expect(mine.length).toBeGreaterThan(0);
        const counts = new Map<string, number>();
        for (const r of mine) counts.set(r.path + r.search, (counts.get(r.path + r.search) ?? 0) + 1);
        for (const [url, n] of counts) expect(n, url).toBe(1);
      } else {
        expect(mine.filter((r) => !/\/projects$/.test(r.path))).toEqual([]);
        expect(after.some((r) => r.path === '/api/v1/projects')).toBe(true);
      }
    });
  }

  test('AC-DSH-05i a burst of events causes few requests', async ({ page, api }) => {
    await open(page, RUN_URL);
    await expect(page.getByTestId('connection-status')).toHaveText('Connected');
    await settle(page);
    const mark = await api.mark();
    const burst = Array.from({ length: 200 }, (_, i) => ({ event: 'task.state_changed', data: evt('task.state_changed', 'leave-balance', 't-green1', { i }) }));
    for (let k = 0; k < 4; k++) {
      await api.events(burst.slice(k * 50, k * 50 + 50));
    }
    await api.idle(500);
    const calls = await api.gets(/^\/api\/v1\/tasks\/leave-balance\/workflow/, mark);
    expect(calls.length).toBeGreaterThan(0);
    expect(calls.length).toBeLessThanOrEqual(3);
    const sent = await api.serverEvents();
    const lastEvent = Math.max(...sent.map((e) => e.t));
    expect(Math.max(...calls.map((c) => c.t))).toBeGreaterThanOrEqual(lastEvent);
  });
});
