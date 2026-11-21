import { test, expect, open, heading, nav } from './helpers.ts';

test.describe('Factory floor screen', () => {
  test('Factory floor is first in main navigation and default landing when projects exist', async ({ page }) => {
    await open(page, '/');
    const mainNav = nav(page);
    const links = mainNav.getByRole('link');
    // First link in navigation is Factory floor
    await expect(links.first()).toHaveText('Factory floor');
    // Landing on / shows Factory floor
    await expect(heading(page, 'Factory floor')).toBeVisible();
    await expect(page.getByText(/\+ 2 queued/)).toBeVisible();
  });

  test('selects task and neuron, checks side panel, and tests pause call', async ({ page, api }) => {
    await open(page, '/floor');
    await expect(heading(page, 'Factory floor')).toBeVisible();

    // Verify task switcher chips
    const taskGroup = page.getByRole('group', { name: 'Tasks on the floor' });
    const taskChip = taskGroup.getByRole('button', { name: /Leave balance export/ });
    await expect(taskChip).toBeVisible();
    await expect(taskChip).toHaveAttribute('aria-pressed', 'true');

    // Factory network canvas is visible
    const network = page.getByRole('region', { name: 'Factory network' });
    await expect(network).toBeVisible();

    // Side panel shows details for the selected station
    const sidePanel = page.getByRole('complementary', { name: 'Selected station' });
    await expect(sidePanel).toBeVisible();
    await expect(sidePanel.getByText('Who', { exact: true })).toBeVisible();
    await expect(sidePanel.getByText('This task', { exact: true })).toBeVisible();
    await expect(sidePanel.getByText('Next', { exact: true })).toBeVisible();
    await expect(sidePanel.getByRole('link', { name: /Open the full run/ })).toBeVisible();

    // Select a different station neuron: Triage
    const triageNeuron = page.getByRole('button', { name: /^Triage:/ });
    await expect(triageNeuron).toBeVisible();
    await triageNeuron.click();
    await expect(triageNeuron).toHaveAttribute('aria-pressed', 'true');
    await expect(sidePanel.getByRole('heading', { level: 2, name: 'Triage' })).toBeVisible();

    // Build fans out into one lane per behavior: B1 done, B2 working, B3 queued
    await expect(page.getByRole('button', { name: 'Export as CSV: Done' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'HR only: Queued' })).toBeVisible();
    const buildNeuron = page.getByRole('button', { name: 'Filter by dept: Working' });
    await buildNeuron.click({ force: true });
    await expect(buildNeuron).toHaveAttribute('aria-pressed', 'true');

    // Verify side panel shows agent role, runner, model for Build
    await expect(sidePanel.getByText(/tdd_green.*claude.*sonnet/)).toBeVisible();
    await expect(sidePanel.getByText('Verify')).toBeVisible();

    // Test pause action
    const pauseBtn = sidePanel.getByRole('button', { name: 'Pause' });
    await expect(pauseBtn).toBeVisible();
    await pauseBtn.click();

    // Verify the button toggles to Resume (waits for the action to settle)
    const resumeBtn = sidePanel.getByRole('button', { name: 'Resume' });
    await expect(resumeBtn).toBeVisible();

    // Verify the pause call was made to the API
    const pausePosts = await api.posts(/\/tasks\/leave-balance\/pause/);
    expect(pausePosts.length).toBeGreaterThanOrEqual(1);

    // Verify the side panel state updates to Paused
    await expect(sidePanel.getByText('Paused').first()).toBeVisible();
  });

  test('stations show who does the work, and the activity panel lists what happened', async ({ page }) => {
    await open(page, '/floor');
    const network = page.getByRole('region', { name: 'Factory network' });
    await expect(network.getByText('agy · gemini-3.8-flash').first()).toBeVisible();
    await expect(network.getByText('claude · sonnet-4.6').first()).toBeVisible();
    await expect(network.getByText('engine').first()).toBeVisible();
    await expect(network.getByText('you').first()).toBeVisible();
    // the task chips say where each task is
    const taskGroup = page.getByRole('group', { name: 'Tasks on the floor' });
    await expect(taskGroup.getByRole('button', { name: /Build · behavior 2 of 3/ })).toBeVisible();
    await expect(taskGroup.getByRole('button', { name: /Fix payroll rounding.*Waiting for you/ })).toBeVisible();
    await expect(taskGroup.getByRole('button', { name: /Audit log filter.*Triage/ })).toBeVisible();

    const activity = page.getByRole('region', { name: 'Factory activity' });
    await expect(activity.getByRole('heading', { name: 'Activity across the factory' })).toBeVisible();
    const rows = activity.getByRole('listitem');
    await expect(rows).toHaveCount(6);
    await expect(rows.first()).toContainText('10:45:14');
    await expect(rows.first()).toContainText('LB');
    await expect(rows.last()).toContainText('spec review');
  });

  test('a waiting gate offers the review, and the canvas stays dark in the light theme', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await open(page, '/floor');
    const taskGroup = page.getByRole('group', { name: 'Tasks on the floor' });
    await taskGroup.getByRole('button', { name: /Fix payroll rounding/ }).click();
    const sidePanel = page.getByRole('complementary', { name: 'Selected station' });
    await expect(sidePanel.getByRole('heading', { level: 2, name: 'You approve spec' })).toBeVisible();
    await expect(sidePanel.getByRole('link', { name: 'Review specification' })).toBeVisible();
    await expect(sidePanel.getByText('Needs you')).toBeVisible();
    const bg = await page.getByRole('region', { name: 'Factory network' }).evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(bg).toBe('rgb(14, 20, 25)');
    // the final gate links to the report
    await page.getByRole('button', { name: /^You accept:/ }).click({ force: true });
    await expect(sidePanel.getByRole('link', { name: 'Open the report' })).toBeVisible();
  });

  test('station labels sit on a background chip and no station is clipped at 1024px', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 800 });
    await open(page, '/floor');
    const network = page.getByRole('region', { name: 'Factory network' });
    await expect(network).toBeVisible();
    const bg = await network.locator('.floor-label').first().evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(bg).not.toBe('rgba(0, 0, 0, 0)');
    // every label stays inside the canvas margins, so no station is clipped when the canvas scrolls
    const inside = await network.evaluate((el) => {
      const inner = el.querySelector('div')!.getBoundingClientRect();
      return [...el.querySelectorAll('.floor-label')].every((l) => {
        const r = l.getBoundingClientRect();
        return r.left >= inner.left - 32 && r.right <= inner.right + 32;
      });
    });
    expect(inside).toBe(true);
    await page.setViewportSize({ width: 1280, height: 800 });
    const scrolls = await network.evaluate((el) => el.scrollWidth > el.clientWidth + 1);
    expect(scrolls).toBe(false);
  });

  test('project switcher opens the floor of another project', async ({ page }) => {
    await open(page, '/floor');
    const pick = page.getByRole('combobox', { name: 'Project' });
    await expect(pick).toHaveValue('digital-hr');
    await expect(pick.locator('option')).toHaveText(['digital-hr · 2 running', 'payroll · 0 running']);
    await pick.selectOption('payroll');
    await expect(page).toHaveURL(/#\/projects\/payroll\/floor/);
    await expect(page.getByRole('heading', { level: 2, name: 'payroll' })).toBeVisible();
    await expect(page.getByText('No active runs.')).toBeVisible();
    await expect(page.getByRole('button', { name: /Leave balance export/ })).toHaveCount(0);
  });

  test('Overview remains reachable via /overview', async ({ page }) => {
    await open(page, '/overview');
    await expect(heading(page, 'Overview')).toBeVisible();
    await expect(page.getByTestId('installation-summary')).toBeVisible();
  });
});
