import { test, expect, open, heading, RUN } from './helpers.ts';

const summary = (i: number, state = 'EXECUTING') => ({
  slug: `run-${String(i).padStart(3, '0')}`, type: 'feature', tier: 2, state, execution_status: 'RUNNING', acceptance_status: 'PENDING', workflow_version: '2',
  updated_at: `2026-11-14T09:${String(59 - (i % 60)).padStart(2, '0')}:00Z`,
});

test.describe('projects', () => {
  test('AC-PRJ-02a REQ-PRJ-01 the project list', async ({ page }) => {
    await open(page, '/projects');
    const table = page.getByRole('table');
    for (const col of ['Name', 'Path', 'Status', 'Active runs']) await expect(table.getByRole('columnheader', { name: col })).toBeVisible();
    const hr = table.getByRole('row', { name: /digital-hr/ });
    await expect(hr).toContainText('/ws/digital-hr');
    await expect(hr).toContainText('available');
    await expect(hr).toContainText('2');
    await expect(table.getByRole('row', { name: /payroll/ })).toBeVisible();
    await expect(table.getByRole('link', { name: 'digital-hr' })).toHaveAttribute('href', '#/projects/digital-hr');
  });

  test('AC-PRJ-02b an unavailable project shows its reason', async ({ page, api }) => {
    await api.set(['projects', 'id=payroll', 'status'], 'unavailable');
    await api.set(['projects', 'id=payroll', 'reason'], 'workspace missing');
    await open(page, '/projects');
    await expect(page.getByText('Unavailable: workspace missing')).toBeVisible();
    await page.getByRole('link', { name: 'payroll' }).click();
    await expect(page.getByText('Unavailable: workspace missing')).toBeVisible();
    await expect(page.getByRole('heading', { name: /Readiness|Repositories|Runs/ })).toHaveCount(0);
    await expect(page.getByRole('navigation', { name: 'Project' })).toHaveCount(0);
    expect((await api.requests()).filter((r) => /projects\/payroll\/(tasks|repositories|readiness)/.test(r.path))).toEqual([]);
  });

  test('AC-PRJ-02c no project registered', async ({ page, api }) => {
    await api.set(['projects'], []);
    await open(page, '/projects');
    await expect(page.getByText('No project registered')).toBeVisible();
    await expect(page.getByText('Run sentinel dashboard inside a workspace to register it')).toBeVisible();
  });

  test('AC-PRJ-04a the project page offers no archive, delete or edit; repositories offer add and remove only', async ({ page, api }) => {
    await open(page, '/projects/digital-hr');
    await expect(page.getByRole('button', { name: /register|archive|remove|edit|delete|unregister|new project|create project/i })).toHaveCount(0);
    await page.getByRole('navigation', { name: 'Project' }).getByRole('link', { name: 'Repositories' }).click();
    await expect(heading(page, 'Repositories')).toBeVisible();
    const buttons = page.getByRole('main').getByRole('button');
    await expect(buttons.filter({ hasNotText: /^(Add repository|Remove)$/ })).toHaveCount(0);
    await expect(page.getByRole('main')).toContainText('sentinel.config.yaml');
    expect((await api.requests()).filter((r) => r.method !== 'GET')).toEqual([]);
  });

  test('AC-PRJ-02d the project page', async ({ page, api }) => {
    await api.set(['projectData', 'digital-hr', 'runs'], Array.from({ length: 8 }, (_, i) => summary(i)));
    await open(page, '/projects/digital-hr');
    const tabs = page.getByRole('navigation', { name: 'Project' });
    for (const t of ['Overview', 'Repositories', 'Configuration', 'Runs', 'Audit']) await expect(tabs.getByRole('link', { name: t, exact: true })).toBeVisible();
    await expect(page.getByTestId('readiness-panel')).toBeVisible();
    await expect(page.getByTestId('latest-runs').getByRole('row')).toHaveCount(5 + 1);
  });
});

test.describe('repositories', () => {
  test('AC-REP-03b the repository table', async ({ page }) => {
    await open(page, '/projects/digital-hr/repositories');
    await expect(page.getByText('Cross-repo order')).toBeVisible();
    const rows = page.getByTestId('repo-row');
    await expect(rows).toHaveCount(2);
    const be = rows.nth(0);
    await expect(be).toContainText('backend');
    for (const t of ['/ws/digital-hr/backend', 'git@example.com:hr/backend.git', 'main', 'feature/leave', 'spring-gradle', './gradlew test', './gradlew build', 'CLAUDE.md']) await expect(be).toContainText(t);
    await expect(rows.nth(1)).toContainText('frontend');
  });

  test('AC-REP-04b repository problems are shown with their fix', async ({ page, api }) => {
    await api.set(['projectData', 'digital-hr', 'repositories', 'items', 'id=frontend', 'validation', 'item=branch'], { item: 'branch', status: 'failed', fix: 'git fetch origin main' });
    await open(page, '/projects/digital-hr/repositories');
    await expect(page.getByTestId('repo-row').nth(1)).toContainText('Branch: Failed');
    await expect(page.getByTestId('repo-row').nth(1)).toContainText('git fetch origin main');
    const be = page.getByTestId('repo-row').nth(0);
    for (const item of ['Path', 'Git', 'Branch', 'Profile']) await expect(be).toContainText(`${item}: Passed`);
    await expect(be).not.toContainText('Failed');
  });
});

test.describe('configuration center, read only', () => {
  test('AC-CFG-06b effective values grouped by category with their source', async ({ page }) => {
    await open(page, '/projects/digital-hr/configuration');
    for (const g of ['Project', 'Repositories', 'Providers', 'Agents', 'Workflow and policies', 'TDD', 'Verification', 'Limits']) await expect(page.getByRole('heading', { name: g, exact: true })).toBeVisible();
    const row = page.getByTestId('config-value-limits.max_retries');
    await expect(row).toContainText('limits.max_retries');
    await expect(row).toContainText('Default');
    await expect(page.getByTestId('config-value-project.name')).toContainText('Project');
    await expect(page.getByTestId('config-value-providers.default')).toContainText('Global');
    await expect(page.getByTestId('config-value-repos.backend.commands.test')).toContainText('Repo backend');
  });

  test('AC-CFG-02a an overridden value shows what it overrides', async ({ page }) => {
    await open(page, '/projects/digital-hr/configuration');
    const row = page.getByTestId('config-value-limits.task_timeout');
    await expect(row).toContainText('1200');
    await expect(row).toContainText('Project');
    await row.getByRole('button', { name: 'Show override of limits.task_timeout' }).click();
    await expect(row).toContainText('Overrides Global: 900');
  });

  test('AC-CFG-01a the configuration cannot be edited from the dashboard in 1.1.0', async ({ page, api }) => {
    await open(page, '/projects/digital-hr/configuration');
    await expect(heading(page, 'Configuration')).toBeVisible();
    const main = page.getByRole('main');
    await expect(main.locator('input:not([type=checkbox]), textarea, select')).toHaveCount(0);
    for (const b of ['Save', 'Restore', 'Import', 'Export']) await expect(main.getByRole('button', { name: b })).toHaveCount(0);
    await expect(main).toContainText('Edit sentinel.config.yaml; the change appears here after Reload');
    await main.getByRole('button', { name: 'Reload' }).click();
    expect((await api.requests()).filter((r) => r.method !== 'GET')).toEqual([]);
  });

  test('AC-CFG-05d history and diff between versions', async ({ page, api }) => {
    await open(page, '/projects/digital-hr/configuration');
    await page.getByRole('link', { name: 'History' }).click();
    await expect(page.getByTestId('version-row')).toHaveCount(3);
    const v1 = page.getByTestId('version-1');
    await expect(v1).toContainText('1a2b3c4d');
    await expect(v1).toContainText('dev');
    await expect(v1).toContainText('tty');
    await expect(v1).toContainText('2026-11-10 08:00:00 UTC');
    await expect(v1).toContainText('first snapshot');
    await page.getByRole('checkbox', { name: 'Select version 1' }).check();
    await page.getByRole('checkbox', { name: 'Select version 3' }).check();
    await page.getByRole('button', { name: 'Compare' }).click();
    await expect(page.getByTestId('diff-line-add').first()).toContainText('+');
    await expect(page.getByTestId('diff-line-add').first()).toContainText('limits.task_timeout: 1200');
    await expect(page.getByTestId('diff-line-del').first()).toContainText('-');
    const req = (await api.gets(/configuration\/diff/))[0];
    expect(req.path).toBe('/api/v1/projects/digital-hr/configuration/diff');
    expect(new URLSearchParams(req.search).get('a')).toBe('1');
    expect(new URLSearchParams(req.search).get('b')).toBe('3');
  });

  test('AC-CFG-05e a project with no saved versions', async ({ page, api }) => {
    await api.set(['projectData', 'digital-hr', 'history', 'items'], []);
    await open(page, '/projects/digital-hr/configuration/history');
    await expect(page.getByText('No saved versions yet')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Compare' })).toBeDisabled();
  });

  test('AC-CFG-08e a run shows the configuration it uses', async ({ page, api }) => {
    await api.set([...RUN('leave-balance'), 'detail', 'config_snapshot'], { version: 2, sha256: '2b2b2b2b' + '00'.repeat(28) });
    await open(page, '/projects/digital-hr/runs/leave-balance');
    const header = page.getByTestId('run-header');
    await expect(header).toContainText('Config snapshot 2');
    await expect(header).toContainText('2b2b2b2b');
    await expect(page.getByText('The project configuration changed after this run started. This run keeps using snapshot 2.')).toBeVisible();
    await expect(page.getByRole('link', { name: /diff of versions 2 and 3/i })).toHaveAttribute('href', /#\/projects\/digital-hr\/configuration\/history\?a=2&b=3/);
  });
});

test.describe('audit', () => {
  test('AC-SEC-07b the audit tab', async ({ page, api }) => {
    const items = Array.from({ length: 120 }, (_, i) => ({
      id: 1000 - i, actor: 'dev', channel: i % 2 ? 'tty' : 'dashboard', action: i % 2 ? 'approve' : 'cancel', target: `leave-balance#${i}`,
      before_sha256: 'aaaaaaaa' + '00'.repeat(28), after_sha256: 'bbbbbbbb' + '00'.repeat(28), reason: `reason ${i}`, at: `2026-11-14T09:${String(59 - (i % 60)).padStart(2, '0')}:00Z`,
    }));
    await api.set(['projectData', 'digital-hr', 'audit'], items);
    await open(page, '/projects/digital-hr/audit');
    const rows = page.getByTestId('audit-row');
    await expect(rows).toHaveCount(50);
    const first = rows.first();
    for (const t of ['dev', 'dashboard', 'cancel', 'leave-balance#0', 'aaaaaaaa', 'bbbbbbbb', 'reason 0', '2026-11-14 09:59:00 UTC']) await expect(first).toContainText(t);
    await page.getByRole('button', { name: 'Load more' }).click();
    await expect(rows).toHaveCount(100);
    await page.getByRole('button', { name: 'Load more' }).click();
    await expect(rows).toHaveCount(120);
    await expect(page.getByRole('button', { name: 'Load more' })).toHaveCount(0);
  });
});
