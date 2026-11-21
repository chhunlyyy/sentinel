import type { Page } from '@playwright/test';
import { test, expect, open, heading } from './helpers.ts';

interface ProjectCreatedBody {
  name: string;
  shared: { mode: string; url?: string };
  repos: { path: string; role: string }[];
}

interface ConfigSaveBody {
  changes: { path: string; value: unknown }[];
}

const bodyOf = <T = Record<string, unknown>>(r: { body: unknown }) => r.body as T;

async function pick(page: Page, label: string, ...dirs: string[]) {
  await page.getByRole('button', { name: `Browse folders for ${label}` }).click();
  for (const d of dirs) await page.getByRole('button', { name: `Open ${d}`, exact: true }).click();
}

test.describe('W3b GUI screens: wizard, shared access, config preview & save, knowledge backfill', () => {
  test('wizard happy path through all 5 steps to the factory floor', async ({ page, api }) => {
    await open(page, '/projects/new');
    await expect(heading(page, 'Create project')).toBeVisible();

    // Step 1: Repositories
    await page.getByLabel('Project name').fill('Billing');
    await pick(page, 'Project folder', 'projects');
    await page.getByLabel('New folder name').fill('billing');
    await page.getByRole('button', { name: 'Create folder here' }).click();
    await expect(page.getByRole('textbox', { name: 'Project folder' })).toHaveValue('/home/dev/projects/billing');

    await pick(page, 'Repository folder', 'projects', 'hr-backend');
    await page.getByRole('button', { name: 'Use this folder' }).click();
    await page.getByLabel('Role').selectOption('backend');
    await page.getByRole('button', { name: 'Add repository' }).click();
    await expect(page.getByTestId('wizard-repos')).toContainText('/home/dev/projects/hr-backend');

    // Advance to Step 2: Detected setup
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByText('We looked at your repos')).toBeVisible();
    await expect(page.getByLabel('Test command')).toBeVisible();

    // Advance to Step 3: Shared knowledge
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByText('Shared team knowledge')).toBeVisible();
    await page.getByRole('radio', { name: /Shared through a git repository/ }).check();
    await page.getByLabel('Git URL').fill('git@example.test:team/state.git');

    // Advance to Step 4: AI team
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByText('Your AI team')).toBeVisible();
    await expect(page.getByRole('table')).toBeVisible();
    await expect(page.getByLabel('Provider for coder')).toBeVisible();

    // Advance to Step 5: Checks and Create
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page.getByText('Ready to open the factory')).toBeVisible();
    await expect(page.getByTestId('wizard-review')).toContainText('Billing');
    await expect(page.getByTestId('wizard-review')).toContainText('Shared: git@example.test:team/state.git');

    // Submit wizard
    await page.getByRole('button', { name: 'Create project' }).click();
    await expect(heading(page, 'Billing')).toBeVisible();
    await expect(page).toHaveURL(/#\/projects\/billing\/floor/);

    const [sent] = (await api.posts(/\/api\/v1\/projects$/)).map((r) => bodyOf<ProjectCreatedBody>(r));
    expect(sent.name).toBe('Billing');
    expect(sent.shared.mode).toBe('git');
    expect(sent.shared.url).toBe('git@example.test:team/state.git');
  });

  test('failing shared access test is shown with error notice', async ({ page }) => {
    await open(page, '/projects/new');
    await page.getByLabel('Project name').fill('Billing');
    await page.getByRole('textbox', { name: 'Project folder' }).fill('/home/dev/projects/billing');
    await page.getByRole('textbox', { name: 'Repository folder' }).fill('/home/dev/projects/hr-backend');
    await page.getByRole('button', { name: 'Add repository' }).click();

    // Advance to Step 2 then Step 3
    await page.getByRole('button', { name: 'Next' }).click();
    await page.getByRole('button', { name: 'Next' }).click();

    await page.getByRole('radio', { name: /Shared through a git repository/ }).check();
    // 'fail' in url triggers mock server error in fake-api
    await page.getByLabel('Git URL').fill('git@example.test:fail/unreachable.git');
    await page.getByRole('button', { name: 'Test access' }).click();

    await expect(page.getByText(/Could not resolve host|Access test failed/)).toBeVisible();
  });

  test('project settings config preview diff then save', async ({ page, api }) => {
    await open(page, '/settings/config');
    await expect(heading(page, 'Project settings')).toBeVisible();

    // Toggle a checkbox in the form
    const autoPushCheck = page.getByRole('checkbox', { name: /Publish knowledge records automatically/ });
    await expect(autoPushCheck).toBeVisible();
    await autoPushCheck.click();

    // Preview the YAML change
    await page.getByRole('button', { name: 'Preview the YAML change' }).click();
    await expect(page.getByText('YAML change preview')).toBeVisible();
    await expect(page.getByText('--- sentinel.config.yaml')).toBeVisible();

    // Return to form and save
    await page.getByRole('button', { name: 'Back to the form' }).click();
    await page.getByRole('button', { name: /Save \(\d+ changes?\)/ }).click();
    await expect(page.getByTestId('action-result')).toContainText('Validated against the schema and saved');

    const [saveCall] = (await api.posts(/\/api\/v1\/projects\/digital-hr\/config\/save$/)).map((r) => bodyOf<ConfigSaveBody>(r));
    expect(saveCall.changes).toBeDefined();
    expect(saveCall.changes.length).toBeGreaterThan(0);
  });

  test('knowledge page shows backfill estimate before confirming', async ({ page }) => {
    await open(page, '/projects/digital-hr/knowledge');
    await expect(page.getByRole('heading', { name: /Team knowledge/ })).toBeVisible();

    // Status tiles are rendered
    await expect(page.getByText('Change records')).toBeVisible();
    await expect(page.getByText('Tracked branches')).toBeVisible();

    // Open Backfill dialog
    await page.getByRole('button', { name: 'Backfill history…' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText('Backfill knowledge from history')).toBeVisible();

    // Verify estimate is shown BEFORE clicking confirm
    await expect(dialog.getByTestId('backfill-estimate-result')).toBeVisible();
    await expect(dialog.getByTestId('backfill-estimate-result')).toContainText('140');

    // Confirm and verify backfill completes
    await dialog.getByRole('button', { name: 'Confirm and start backfill' }).click();
    await expect(page.getByTestId('action-result')).toContainText('Backfilled 140 changes into knowledge');
  });
});
