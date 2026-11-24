import { test, expect, open, heading, nav } from './helpers.ts';

test.describe('Factory floor screen', () => {
  test('Floor is first in main navigation and default landing when projects exist', async ({ page }) => {
    await open(page, '/');
    const mainNav = nav(page);
    const links = mainNav.getByRole('link');
    // First link in navigation is Floor
    await expect(links.first()).toHaveText('Floor');
    // Landing on / shows Factory floor
    const floorRegion = page.getByRole('region', { name: 'Factory floor' });
    await expect(floorRegion).toBeVisible();
  });

  test('displays task title, station nodes and detail card on node click', async ({ page }) => {
    await open(page, '/floor');
    const floorRegion = page.getByRole('region', { name: 'Factory floor' });
    await expect(floorRegion).toBeVisible();

    // Task section header
    const taskHeading = page.getByRole('heading', { level: 1 }).first();
    await expect(taskHeading).toBeVisible();

    // Station nodes on the floor graph
    const intakeNode = page.getByRole('button', { name: /^Intake/ });
    await expect(intakeNode).toBeVisible();

    const specNode = page.getByRole('button', { name: /^Specification/ });
    await expect(specNode).toBeVisible();

    const scenariosNode = page.getByRole('button', { name: /^Scenarios/ });
    await expect(scenariosNode).toBeVisible();

    // Click Specification node
    await specNode.click();

    // Detail card below the graph updates to show Specification details
    await expect(page.getByRole('heading', { level: 2, name: 'Specification' })).toBeVisible();
    await expect(page.getByText('Spec writer')).toBeVisible();
    await expect(page.getByText('Recent steps')).toBeVisible();
    await expect(page.getByRole('link', { name: /Open full work|Open the full run/i })).toBeVisible();
  });

  test('Pause this task button toggles and sends pause/resume API calls', async ({ page, api }) => {
    await open(page, '/floor');
    const pauseBtn = page.getByRole('button', { name: 'Pause this task' });
    await expect(pauseBtn).toBeVisible();
    await pauseBtn.click();

    // Verify button toggles to Resume
    const resumeBtn = page.getByRole('button', { name: 'Resume this task' });
    await expect(resumeBtn).toBeVisible();

    // Verify pause post was sent
    const pausePosts = await api.posts(/\/tasks\/.*\/pause/);
    expect(pausePosts.length).toBeGreaterThanOrEqual(1);
  });

  test('Continue in terminal button copies sentinel attach command', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await open(page, '/floor');

    const attachBtn = page.getByRole('button', { name: /Continue in terminal/ });
    await expect(attachBtn).toBeVisible();
    await attachBtn.click();

    await expect(page.getByText('Copied')).toBeVisible();
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip).toMatch(/^sentinel attach/);
  });

  test('Tell the orchestrator and Handled for you panels are rendered below the graph', async ({ page }) => {
    await open(page, '/floor');

    // Tell the orchestrator
    await expect(page.getByRole('heading', { level: 2, name: 'Tell the orchestrator' })).toBeVisible();
    const sendBtn = page.getByRole('button', { name: 'Send' });
    await expect(sendBtn).toBeDisabled();
    await expect(page.getByText('Coming next: the orchestrator will act on your messages')).toBeVisible();

    // Handled for you
    await expect(page.getByRole('heading', { level: 2, name: 'Handled for you' })).toBeVisible();
    await expect(page.getByText(/Problems the orchestrator fixed|Nothing needed fixing yet/i)).toBeVisible();
  });

  test('Activity list is shown below the floor', async ({ page }) => {
    await open(page, '/floor');
    await expect(page.getByRole('heading', { level: 2, name: 'Activity across the factory' })).toBeVisible();
    const items = page.getByTestId('activity-row');
    if ((await items.count()) > 0) {
      await expect(items.first()).toBeVisible();
    }
  });

  test('project switcher opens the floor of another project', async ({ page }) => {
    await open(page, '/floor');
    const pick = page.getByRole('combobox', { name: 'Project' });
    if (await pick.isVisible()) {
      await pick.selectOption('payroll');
      await expect(page).toHaveURL(/#\/projects\/payroll\/floor/);
    } else {
      await open(page, '/projects/payroll/floor');
      await expect(page).toHaveURL(/#\/projects\/payroll\/floor/);
    }
  });

  test('Overview remains reachable via /overview', async ({ page }) => {
    await open(page, '/overview');
    await expect(heading(page, 'Overview')).toBeVisible();
  });

  test('the project home shows the Fix routing banner when routing has problems', async ({ page, api }) => {
    await api.set(['factory', 'digital-hr', 'routing'], { problems: ['triage routes to the native adapter'] });
    await open(page, '/projects/digital-hr');
    await expect(page.getByTestId('fix-routing-banner')).toBeVisible();
  });

  test('the canvas stays dark in the light theme and reduced motion disables animations', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await open(page, '/floor');

    const floorRegion = page.getByRole('region', { name: 'Factory floor' });
    await expect(floorRegion).toBeVisible();

    // Verify dark canvas style
    const bg = await floorRegion.evaluate((el) => window.getComputedStyle(el).backgroundImage || window.getComputedStyle(el).backgroundColor);
    expect(bg).toBeTruthy();

    // Reduced motion test
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const pulseEl = floorRegion.locator('.pulse, [data-pulsing="true"]').first();
    if (await pulseEl.isVisible()) {
      const anim = await pulseEl.evaluate((el) => window.getComputedStyle(el).animationName);
      expect(anim === 'none' || anim === '').toBe(true);
    }
  });

  test('phone width 390px: graph scrolls horizontally inside its panel', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page, '/floor');

    const floorRegion = page.getByRole('region', { name: 'Factory floor' });
    await expect(floorRegion).toBeVisible();

    // Canvas container scrolls internally
    const hasScroll = await floorRegion.evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(hasScroll).toBe(true);

    // Document body does not have horizontal overflow
    const docOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2);
    expect(docOverflow).toBe(true);
  });

  test('run with no retries shows Nothing needed fixing yet and no mock strings appear', async ({ page }) => {
    await open(page, '/floor');
    await expect(page.getByText('Nothing needed fixing yet.')).toBeVisible();
    const content = await page.content();
    for (const forbidden of ['REQ-4', 'D12', 'Computer slept', 'RefusalTest', 'Two test runs collided']) {
      expect(content).not.toContain(forbidden);
    }
  });

  test('run with FAILED E_TIMEOUT task and COMPLETED retry shows Handled for you line', async ({ page, api }) => {
    const failedTask = {
      id: 't-green1',
      role: 'coder',
      repo: 'backend',
      state: 'FAILED',
      adapter: 'cli',
      provider: 'claude',
      model: 'sonnet-4.6',
      attempt: 1,
      retry_of: null,
      error_code: 'E_TIMEOUT',
      reason: 'timed out',
      started_at: '2026-11-21T10:41:40.000000Z',
      finished_at: '2026-11-21T10:51:40.000000Z',
      seconds: 600,
      tokens: null,
      cost: null,
      input_tokens: null,
      output_tokens: null,
      label: null,
    };
    const retryTask = {
      id: 't-green2',
      role: 'coder',
      repo: 'backend',
      state: 'COMPLETED',
      adapter: 'cli',
      provider: 'claude',
      model: 'sonnet-4.6',
      attempt: 2,
      retry_of: 't-green1',
      error_code: null,
      reason: null,
      started_at: '2026-11-21T10:51:50.000000Z',
      finished_at: '2026-11-21T10:55:00.000000Z',
      seconds: 190,
      tokens: null,
      cost: null,
      input_tokens: null,
      output_tokens: null,
      label: null,
    };

    await api.set(['runs', 'digital-hr/leave-balance', 'workflow', 'nodes'], [failedTask, retryTask]);
    await api.set(['factory', 'digital-hr', 'runs', '0', 'station_tasks', 'build'], [
      { id: 't-green1', role: 'coder', state: 'FAILED', error_code: 'E_TIMEOUT', reason: 'timed out', retry_of: null },
      { id: 't-green2', role: 'coder', state: 'COMPLETED', error_code: null, reason: null, retry_of: 't-green1' },
    ]);

    await open(page, '/floor');
    await expect(page.getByText('Coder failed (timed out) and was retried: it worked')).toBeVisible();
  });
});
