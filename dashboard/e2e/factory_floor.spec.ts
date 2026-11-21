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
    await expect(page.getByText(/Factory running/)).toBeVisible();
  });

  test('selects task and neuron, checks side panel, and tests pause call', async ({ page, api }) => {
    await open(page, '/floor');
    await expect(heading(page, 'Factory floor')).toBeVisible();

    // Verify task switcher chips
    const taskGroup = page.getByRole('group', { name: 'Tasks on the floor' });
    const taskChip = taskGroup.getByRole('button', { name: /Show the remaining leave days/ });
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

    // Select the Build station neuron
    const buildNeuron = page.getByRole('button', { name: /^Remaining days show:|^Build:/ });
    await expect(buildNeuron).toBeVisible();
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

  test('Overview remains reachable via /overview', async ({ page }) => {
    await open(page, '/overview');
    await expect(heading(page, 'Overview')).toBeVisible();
    await expect(page.getByTestId('installation-summary')).toBeVisible();
  });
});
