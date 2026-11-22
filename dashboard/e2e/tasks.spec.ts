import { test, expect, open, heading, RUN } from './helpers.ts';

const summary = (i: number, state: string) => ({
  slug: `run-${String(i).padStart(3, '0')}`, type: 'feature', tier: 2, state, execution_status: 'RUNNING', acceptance_status: 'PENDING', workflow_version: '2',
  updated_at: '2026-11-14T09:00:00Z',
});

test.describe('task list', () => {
  test('AC-TSK-01i runs of every project', async ({ page }) => {
    await open(page, '/tasks');
    const table = page.getByRole('table');
    for (const c of ['Project', 'Slug', 'Type', 'Tier', 'State', 'Execution', 'Acceptance', 'Updated']) await expect(table.getByRole('columnheader', { name: c })).toBeVisible();
    await expect(table.getByRole('row', { name: /digital-hr.*leave-balance/ })).toContainText('EXECUTING');
    await expect(table.getByRole('row', { name: /payroll.*tax-form/ })).toBeVisible();
    await expect(table.getByRole('row', { name: /old-fix/ })).toContainText('Legacy (0.1)');
    await table.getByRole('link', { name: 'old-fix' }).click();
    const main = page.getByRole('main');
    await expect(main).toContainText('Legacy (0.1)');
    await expect(main).toContainText('sentinel resume old-fix');
    await expect(main.getByRole('button')).toHaveCount(0);
  });

  test('AC-TSK-01j paging and filters', async ({ page, api }) => {
    const states = ['EXECUTING', 'COMPLETED', 'CANCELLED', 'CREATED'];
    await api.set(['projectData', 'digital-hr', 'runs'], Array.from({ length: 120 }, (_, i) => summary(i, states[i % 4])));
    await open(page, '/projects/digital-hr/runs');
    const rows = page.getByTestId('run-row');
    await expect(rows).toHaveCount(50);
    await page.getByRole('button', { name: 'Load more' }).click();
    await expect(rows).toHaveCount(100);
    await page.getByRole('button', { name: 'Load more' }).click();
    await expect(rows).toHaveCount(120);
    await expect(page.getByRole('button', { name: 'Load more' })).toHaveCount(0);
    const slugs = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('data-slug')));
    expect(new Set(slugs).size).toBe(120);
    await page.getByLabel('State').selectOption('EXECUTING');
    const filtered = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('data-state')));
    expect(filtered.length).toBe(30);
    expect(new Set(filtered)).toEqual(new Set(['EXECUTING']));
  });

  test('AC-TSK-01k a project with no runs', async ({ page, api }) => {
    await api.set(['projectData', 'payroll', 'runs'], []);
    await open(page, '/projects/payroll/runs');
    await expect(page.getByText('No runs yet')).toBeVisible();
    await expect(page.getByRole('main').getByRole('link', { name: 'Create task' })).toBeVisible();
  });
});

test.describe('creating a task', () => {
  test('AC-TSK-01l creating a task queues it for the AI tool', async ({ page, api, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await open(page, '/tasks/new');
    await page.getByLabel('Project').selectOption('digital-hr');
    await page.getByLabel('Slug').fill('leave-report');
    await page.getByLabel('Request').fill('Report leave per team');
    await page.getByLabel('Type').selectOption('feature');
    await page.getByRole('checkbox', { name: 'frontend', exact: true }).uncheck();
    await page.getByLabel('Priority').selectOption('high');
    await page.getByLabel('Ticket').fill('HR-12');
    await page.getByRole('button', { name: 'Create task' }).click();
    await expect(heading(page, 'leave-report')).toBeVisible();
    const posts = await api.posts(/projects\/digital-hr\/tasks$/);
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toEqual({ slug: 'leave-report', request: 'Report leave per team', type: 'feature', repos: ['backend'], priority: 'high', ticket: 'HR-12' });
    await expect(page.getByTestId('run-state')).toContainText('CREATED');
    await expect(page.getByText('Queued for the AI tool. In your AI tool session run /sentinel resume leave-report')).toBeVisible();
    await page.getByRole('button', { name: 'Copy /sentinel resume leave-report' }).first().click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('/sentinel resume leave-report');
  });

  test('AC-TSK-02b the form says that creating a task approves nothing', async ({ page }) => {
    await open(page, '/tasks/new');
    await expect(page.getByText('Creating a task does not approve anything. The specification and the Gherkin scenarios need your approval before any code is written.')).toBeVisible();
    await expect(page.getByLabel(/approv|skip|start|gate/i)).toHaveCount(0);
  });

  test('AC-TSK-01m tier and repository choices: every repository checked', async ({ page, api }) => {
    await open(page, '/tasks/new');
    await page.getByLabel('Project').selectOption('digital-hr');
    await page.getByLabel('Slug').fill('all-repos');
    await page.getByLabel('Request').fill('x');
    await page.getByLabel('Type').selectOption('feature');
    await page.getByRole('button', { name: 'Create task' }).click();
    await expect(heading(page, 'all-repos')).toBeVisible();
    const body = (await api.posts(/tasks$/))[0].body as Record<string, unknown>;
    expect('repos' in body).toBe(false);
    expect('tier' in body).toBe(false);
  });

  test('AC-TSK-01m tier and repository choices: no repository checked', async ({ page }) => {
    await open(page, '/tasks/new');
    await page.getByLabel('Project').selectOption('digital-hr');
    await page.getByLabel('Slug').fill('no-repos');
    await page.getByLabel('Request').fill('x');
    await page.getByLabel('Type').selectOption('feature');
    await page.getByRole('checkbox', { name: 'backend', exact: true }).uncheck();
    await page.getByRole('checkbox', { name: 'frontend', exact: true }).uncheck();
    await expect(page.getByRole('button', { name: 'Create task' })).toBeDisabled();
    await expect(page.getByText('Pick at least one repository')).toBeVisible();
  });

  test('AC-TSK-01m tier and repository choices: the tier list', async ({ page }) => {
    await open(page, '/tasks/new');
    await expect(page.getByLabel('Tier')).toBeVisible();
    const options = await page.getByLabel('Tier').locator('option').allTextContents();
    expect(options).toEqual(['Decided at triage', '1', '2', '3', '4']);
    await expect(page.getByText('A tier can only raise the triage result')).toBeVisible();
  });

  test('AC-TSK-01m tier and repository choices: tier 3', async ({ page, api }) => {
    await open(page, '/tasks/new');
    await page.getByLabel('Project').selectOption('digital-hr');
    await page.getByLabel('Slug').fill('tier-three');
    await page.getByLabel('Request').fill('x');
    await page.getByLabel('Type').selectOption('feature');
    await page.getByLabel('Tier').selectOption('3');
    await page.getByRole('button', { name: 'Create task' }).click();
    await expect(heading(page, 'tier-three')).toBeVisible();
    expect(((await api.posts(/tasks$/))[0].body as Record<string, unknown>).tier).toBe(3);
  });

  const refusals: [number, string, string][] = [
    [400, 'E_VALIDATION', 'type'], [400, 'E_VALIDATION', 'repos'], [422, 'E_PRECONDITION', 'slug'], [409, 'E_LOCKED', 'slug'], [422, 'E_PRECONDITION', 'repos'],
  ];
  for (const [status, code, field] of refusals) {
    test(`AC-TSK-01o server refusals are shown at the field: ${status} ${code} ${field}`, async ({ page, api }) => {
      await api.rule({ method: 'POST', path: '/api/v1/projects/digital-hr/tasks', status, body: { error: { code, message: `server says no to ${field}`, details: { field } } } });
      await open(page, '/tasks/new');
      await page.getByLabel('Project').selectOption('digital-hr');
      await page.getByLabel('Slug').fill('refused-one');
      await page.getByLabel('Request').fill('keep me');
      await page.getByLabel('Type').selectOption('feature');
      await page.getByRole('button', { name: 'Create task' }).click();
      const label = { type: 'Type', repos: 'Repositories', slug: 'Slug' }[field]!;
      const control = field === 'repos' ? page.getByRole('group', { name: label }) : page.getByLabel(label, { exact: true });
      await expect(page.getByText(`server says no to ${field}`)).toBeVisible();
      await expect(control).toHaveAttribute(field === 'repos' ? 'aria-describedby' : 'aria-invalid', /.+/);
      await expect(page.getByLabel('Slug')).toHaveValue('refused-one');
      await expect(page.getByLabel('Request')).toHaveValue('keep me');
      await expect(page.getByRole('heading', { name: 'refused-one' })).toHaveCount(0);
      await expect(heading(page, 'Create task')).toBeVisible();
    });
  }

  test('AC-TSK-01p the request text keeps its form', async ({ page, api }) => {
    const text = 'line one\n\nline three\nline four';
    await open(page, '/tasks/new');
    await page.getByLabel('Project').selectOption('digital-hr');
    await page.getByLabel('Slug').fill('multi-line');
    await page.getByLabel('Request').fill(text);
    await page.getByLabel('Type').selectOption('feature');
    await page.getByRole('button', { name: 'Create task' }).click();
    await expect(heading(page, 'multi-line')).toBeVisible();
    expect(((await api.posts(/tasks$/))[0].body as Record<string, unknown>).request).toBe(text);
    const shown = page.getByTestId('run-request');
    await expect(shown).toHaveText(text);
    expect(await shown.evaluate((e) => getComputedStyle(e).whiteSpace)).toMatch(/pre/);
  });

  test('AC-TSK-01q knowledge found side panel, slots note, and save as draft', async ({ page }) => {
    await open(page, '/tasks/new');
    await page.getByLabel('Project').selectOption('digital-hr');

    // Slots note from factory snapshot
    await expect(page.getByText(/Slots: \d+ of \d+ busy in digital-hr/)).toBeVisible();

    // Knowledge found panel
    await expect(page.getByRole('heading', { name: 'Knowledge found' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Open knowledge' })).toHaveAttribute('href', '#/projects/digital-hr/knowledge');

    // Debounced query on request change
    await page.getByLabel('Request').fill('leave balance calculation');
    await expect(page.getByText(/Leave balance API/)).toBeVisible();

    // Save as draft
    await page.getByLabel('Slug').fill('my-draft-slug');
    await page.getByRole('button', { name: 'Save as draft' }).click();
    await expect(page.getByText('Draft saved')).toBeVisible();

    // Reload page to verify draft survives reload
    await page.reload();
    await page.getByLabel('Project').selectOption('digital-hr');
    await expect(page.getByLabel('Slug')).toHaveValue('my-draft-slug');
    await expect(page.getByLabel('Request')).toHaveValue('leave balance calculation');
  });
});

test.describe('waiting for the AI tool', () => {
  const rows: [string, string][] = [['orchestrator', 'waiting for AI tool'], ['task', 'waiting for orchestrator']];
  for (const [kind, label] of rows) {
    test(`AC-TSK-03j steps that wait for the AI tool are shown: ${kind}`, async ({ page, api }) => {
      await api.set([...RUN('leave-balance'), 'next'], { kind, label, command: '/sentinel resume leave-balance' });
      await open(page, '/projects/digital-hr/runs/leave-balance');
      const banner = page.getByTestId('next-banner');
      await expect(banner).toContainText(label);
      await expect(banner).toContainText('/sentinel resume leave-balance');
      await expect(banner.getByRole('button', { name: 'Copy /sentinel resume leave-balance' })).toBeVisible();
    });
  }

  test('AC-TSK-03k a human step of the run links to where it is decided', async ({ page, api }) => {
    await api.set([...RUN('leave-balance'), 'next'], { kind: 'human', label: 'Your approval is needed: specification version 2', gate: 'specification', version: 2, command: null });
    await open(page, '/projects/digital-hr/runs/leave-balance');
    const banner = page.getByTestId('next-banner');
    await expect(banner).toContainText('Your approval is needed: specification version 2');
    await expect(banner.getByRole('link', { name: /review/i })).toHaveAttribute('href', '#/projects/digital-hr/runs/leave-balance/specification');
  });
});
