import { test, expect, open, nav, heading, type Api } from './helpers.ts';

test.describe('installation and runtime', () => {
  test('AC-INS-02a the installation screen', async ({ page }) => {
    await open(page, '/');
    await nav(page).getByRole('link', { name: 'Settings' }).click();
    await page.getByRole('link', { name: 'Sentinel installation' }).click();
    await expect(heading(page, 'Sentinel installation')).toBeVisible();
    const main = page.getByRole('main');
    await expect(main).toContainText('1.1.0');
    await expect(main).toContainText('/home/dev/.local/share/uv/tools/sentinel');
    await expect(main).toContainText('3.12.3');
    await expect(main).toContainText('uv tool');
    await expect(main).toContainText('4242');
    await expect(main).toContainText('2026-11-14 08:00:00 UTC');
    await expect(main).toContainText('digital-hr');
    await expect(main).toContainText('payroll');
  });

  test('AC-INS-04a REQ-VIS-06 the browser never starts or stops processes', async ({ page }) => {
    await open(page, '/settings/installation');
    await page.getByRole('link', { name: 'Runtime connection' }).click();
    const main = page.getByRole('main');
    await expect(main).toContainText('Connected to the running server');
    await expect(main).toContainText('4242');
    await expect(main.getByRole('button', { name: /start|stop|restart/i })).toHaveCount(0);
    await expect(main.locator('input[type=file], input[type=text]')).toHaveCount(0);
    await expect(main).toContainText('sentinel dashboard');
  });
});

const check = (id: string, status: string, fix: string | null, required = true) => ({ id, label: id, required, status, message: `${id} ${status}`, fix });

test.describe('health checks', () => {
  const rows: [string, string, string, string][] = [
    ['git', 'passed', 'Passed', 'none'],
    ['jsonschema', 'failed', 'Failed', 'uv tool install --reinstall sentinel'],
    ['provider', 'warning', 'Warning', 'install the codex CLI or set runners'],
    ['provider', 'not_configured', 'Not configured', 'add a runner in sentinel.config.yaml'],
    ['registry_writable', 'failed', 'Failed', 'check the permissions of .sentinel/'],
  ];
  for (const [id, status, label, fix] of rows) {
    test(`AC-INS-03a each check shows its status and its fix: ${id} ${status}`, async ({ page, api }) => {
      await api.set(['health', 'checks', `id=${id}`], check(id, status, fix === 'none' ? null : fix, id !== 'provider'));
      await open(page, '/settings/health');
      const row = page.getByTestId(`check-${id}`);
      await expect(row).toContainText(label);
      if (status === 'passed') await expect(row.getByText('Fix:')).toHaveCount(0);
      else await expect(row).toContainText(fix);
      // status as text and an icon with a text alternative
      await expect(row.getByTestId('status-icon')).toHaveAttribute('aria-hidden', 'true');
      await expect(row.getByTestId('status-text')).toHaveText(label);
    });
  }

  test('AC-INS-03b a failed required check means not ready, whatever else passed', async ({ page, api }) => {
    await api.set(['health', 'checks', 'id=registry_writable'], check('registry_writable', 'failed', 'check the permissions of .sentinel/'));
    await open(page, '/');
    const summary = page.getByTestId('installation-summary');
    await expect(summary).toContainText('Not ready: 1 required check failed');
    await expect(summary).not.toHaveText(/^\s*Ready/);
  });

  const failures: [string, (api: Api) => Promise<void>][] = [
    ['500 with error code E_INTERNAL', (api) => api.rule({ method: 'GET', path: '/api/v1/installation/health', status: 500, body: { error: { code: 'E_INTERNAL', message: 'x', details: {} } } })],
    ['nothing within 30 seconds', (api) => api.rule({ method: 'GET', path: '/api/v1/installation/health', hang: true })],
    ['404 with error code E_NOT_FOUND', (api) => api.rule({ method: 'GET', path: '/api/v1/installation/health', status: 404, body: { error: { code: 'E_NOT_FOUND', message: 'x', details: {} } } })],
  ];
  for (const [name, setup] of failures) {
    test(`AC-INS-03c health checks that cannot be read are not shown as passed: ${name}`, async ({ page, api }) => {
      await setup(api);
      if (name.startsWith('nothing')) await page.clock.install();
      await open(page, '/settings/health');
      if (name.startsWith('nothing')) {
        await expect.poll(async () => (await api.gets(/installation\/health/)).length).toBeGreaterThan(0);
        for (let i = 0; i < 4; i++) await page.clock.runFor(31_000);
      }
      await expect(page.getByText('Connection unavailable')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Check again' })).toBeVisible();
      await expect(page.getByText('Passed')).toHaveCount(0);
    });
  }

  test('AC-INS-03d checking again replaces old results', async ({ page, api }) => {
    await api.set(['health', 'checks', 'id=git'], check('git', 'failed', 'install git'));
    await api.set(['health', 'checked_at'], '2026-11-14T10:00:00Z');
    await open(page, '/settings/health');
    await expect(page.getByTestId('check-git')).toContainText('Failed');
    await api.set(['health', 'checks', 'id=git'], check('git', 'passed', null));
    await api.set(['health', 'checked_at'], '2026-11-14T10:05:00Z');
    await api.rule({ method: 'GET', path: '/api/v1/installation/health', delayMs: 1200, passthrough: true });
    await page.getByRole('button', { name: 'Check again' }).click();
    await expect(page.getByTestId('check-git')).toContainText('Checking');
    await expect(page.getByTestId('check-git')).not.toContainText('Failed');
    await expect(page.getByTestId('check-git')).toContainText('Passed');
    await expect(page.getByTestId('health-checked-at')).toContainText('2026-11-14 10:05:00 UTC');
  });
});

const item = (id: string, status: string, extra: Record<string, unknown> = {}) => ({ id, status, message: `${id} ${status}`, fix: null, ...extra });

test.describe('project readiness', () => {
  const rows: { state: string; items: unknown[]; label: string; enabled: boolean; detail: (p: import('@playwright/test').Page) => Promise<void> }[] = [
    { state: 'ready', items: [item('git', 'passed')], label: 'Ready', enabled: true, detail: async (p) => expect(p.getByTestId('readiness-problems')).toHaveCount(0) },
    {
      state: 'ready_with_warnings', items: [item('knowledge', 'warning', { fix: 'add docs/knowledge.md' })], label: 'Ready with warnings', enabled: true,
      detail: async (p) => { await expect(p.getByTestId('readiness-problems')).toContainText('knowledge'); await expect(p.getByTestId('readiness-problems')).toContainText('add docs/knowledge.md'); },
    },
    {
      state: 'needs_configuration', items: [item('test_command', 'not_configured', { repo: 'backend', fix: 'set repos.backend.commands.test' })], label: 'Needs configuration', enabled: false,
      detail: async (p) => { const l = p.getByTestId('readiness-problems'); await expect(l).toContainText('test_command'); await expect(l).toContainText('backend'); await expect(l).toContainText('set repos.backend.commands.test'); },
    },
    {
      state: 'invalid_configuration', items: [item('schema', 'failed', { path: 'repos[1].role', message: 'role must be one of backend, frontend' })], label: 'Invalid configuration', enabled: false,
      detail: async (p) => { const l = p.getByTestId('readiness-problems'); await expect(l).toContainText('repos[1].role'); await expect(l).toContainText('role must be one of backend, frontend'); },
    },
    {
      state: 'connection_unavailable', items: [item('path', 'unreachable', { repo: 'frontend', message: 'folder missing' })], label: 'Connection unavailable', enabled: false,
      detail: async (p) => { const l = p.getByTestId('readiness-problems'); await expect(l).toContainText('frontend'); await expect(l).toContainText('Not reachable'); },
    },
  ];
  for (const r of rows) {
    test(`AC-DSH-03a the five readiness states: ${r.state}`, async ({ page, api }) => {
      await api.set(['projectData', 'digital-hr', 'readiness', 'default'], { state: r.state, workflow: null, checked_at: '2026-11-14T09:00:00Z', items: r.items });
      await open(page, '/projects/digital-hr');
      await expect(page.getByTestId('readiness-panel')).toContainText(r.label);
      const btn = page.getByRole('button', { name: 'Create task' });
      if (r.enabled) await expect(btn).toBeEnabled();
      else await expect(btn).toBeDisabled();
      await r.detail(page);
    });
  }

  test('AC-DSH-03c readiness depends on the selected workflow', async ({ page, api }) => {
    await api.set(['projectData', 'digital-hr', 'readiness', 'byWorkflow'], {
      docs: { state: 'ready', workflow: 'docs', checked_at: '2026-11-14T09:00:00Z', items: [item('git', 'passed')] },
      feature: { state: 'needs_configuration', workflow: 'feature', checked_at: '2026-11-14T09:00:00Z', items: [item('test_command', 'not_configured', { repo: 'backend', fix: 'set repos.backend.commands.test' })] },
    });
    await open(page, '/tasks/new');
    await page.getByLabel('Project').selectOption('digital-hr');
    await page.getByLabel('Slug').fill('docs-task');
    await page.getByLabel('Request').fill('Write docs');
    await page.getByLabel('Type').selectOption('docs');
    await expect(page.getByRole('button', { name: 'Create task' })).toBeEnabled();
    expect((await api.gets(/readiness\?.*workflow=docs/)).length).toBeGreaterThan(0);
    await page.getByLabel('Type').selectOption('feature');
    await expect(page.getByRole('button', { name: 'Create task' })).toBeDisabled();
    await expect(page.getByTestId('readiness-problems')).toContainText('test_command');
    expect((await api.gets(/readiness\?.*workflow=feature/)).length).toBeGreaterThan(0);
  });
});

test.describe('first-run guide', () => {
  const steps = ['Installation', 'Health', 'Create project', 'Add repositories', 'Configure', 'Readiness', 'First task'];
  const step = (p: import('@playwright/test').Page, name: string) => p.getByTestId(`step-${name.toLowerCase().replace(/ /g, '-')}`);

  test('AC-DSH-02a no project registered yet', async ({ page, api }) => {
    await api.reset('fresh-install');
    await open(page, '/');
    const guide = page.getByTestId('first-run-guide');
    for (const s of steps) await expect(step(page, s)).toBeVisible();
    await expect(guide).toContainText('Installation');
    await expect(step(page, 'Installation')).toContainText('Done');
    await expect(step(page, 'Health')).toContainText('Done');
    for (const s of ['Create project', 'Add repositories', 'Configure']) {
      await expect(step(page, s)).toContainText('sentinel init');
      await expect(step(page, s)).toContainText('sentinel dashboard');
      await expect(step(page, s)).toContainText('sentinel.config.yaml');
    }
    for (const s of ['Create project', 'Add repositories', 'Configure', 'Readiness', 'First task']) await expect(step(page, s)).not.toContainText('Done');
  });

  test('AC-DSH-02b the guide follows what the API reports', async ({ page, api }) => {
    await api.reset('fresh-install');
    await open(page, '/');
    await expect(step(page, 'Create project')).not.toContainText('Done');
    await api.preset('fresh-with-project');
    await api.event('resync', { project: 'digital-hr', reason: 'project available' });
    await expect(step(page, 'Create project')).toContainText('Done');
    await expect(step(page, 'Add repositories')).toContainText('Done');
    await expect(step(page, 'Configure')).toContainText('Current');
    await expect(step(page, 'Configure')).toContainText('test_command');
    await expect(page.getByRole('link', { name: 'Create task' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Create task' })).toHaveCount(0);
    await api.set(['projectData', 'digital-hr', 'readiness', 'default'], { state: 'ready', workflow: null, checked_at: '2026-11-14T09:00:00Z', items: [item('git', 'passed')] });
    await api.event('resync', { project: 'digital-hr', reason: 'database restored' });
    await expect(step(page, 'First task')).toContainText('Current');
    await expect(page.getByRole('link', { name: 'Create task' })).toBeVisible();
  });
});
