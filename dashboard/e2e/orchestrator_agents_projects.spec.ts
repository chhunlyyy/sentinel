import AxeBuilder from '@axe-core/playwright';
import { test, expect, open, heading } from './helpers.ts';

const bodyOf = (r: { body: unknown }) => r.body as Record<string, unknown>;
const puts = async (api: { requests: () => Promise<{ method: string; path: string; body: unknown }[]> }, re: RegExp) => (await api.requests()).filter((r) => r.method === 'PUT' && re.test(r.path));

test.describe('providers and orchestrator', () => {
  test('Settings has a Providers page with installed badge, path and Test', async ({ page }) => {
    await open(page, '/settings/providers');
    await expect(heading(page, 'Providers')).toBeVisible();
    const claude = page.getByTestId('provider-claude');
    await expect(claude).toContainText('Claude Code');
    await expect(claude).toContainText('Installed');
    await expect(claude).toContainText('/usr/local/bin/claude');
    const gemini = page.getByTestId('provider-gemini');
    await expect(gemini).toContainText('Not installed');
    await expect(gemini.getByRole('button', { name: 'Test Gemini CLI' })).toBeDisabled();
    await claude.getByRole('button', { name: 'Test Claude Code' }).click();
    await expect(page.getByTestId('provider-result-claude')).toContainText('claude 1.0.0');
  });

  test('the orchestrator is chosen on the page and saved', async ({ page, api }) => {
    await open(page, '/settings/providers');
    const select = page.getByRole('combobox', { name: 'Orchestrator' });
    await expect(select.locator('option')).toHaveText([/None/, /Claude Code \(claude\)/, /Codex CLI \(codex\)/]);
    await select.selectOption('codex');
    await page.getByRole('button', { name: 'Set orchestrator' }).click();
    await expect(page.getByTestId('action-result')).toContainText('Orchestrator set to Codex CLI');
    await expect(page.getByTestId('orchestrator-current')).toHaveText('Codex CLI');
    const sent = await puts(api, /orchestrator$/);
    expect(sent.map(bodyOf)).toEqual([{ id: 'codex' }]);
  });

  test('an id that is not installed is refused by the server and shown', async ({ page, api }) => {
    await open(page, '/settings/providers');
    await api.rule({ method: 'PUT', path: '/api/v1/orchestrator', status: 400, body: { error: { code: 'E_VALIDATION', message: 'provider is not installed', details: { field: 'id' } } } });
    await page.getByRole('combobox', { name: 'Orchestrator' }).selectOption('claude');
    await page.getByRole('button', { name: 'Set orchestrator' }).click();
    await expect(page.getByTestId('action-result')).toContainText('provider is not installed');
  });
});

test.describe('agent routing', () => {
  test('route a role to a provider and model, with the sha256 sent back', async ({ page, api }) => {
    await open(page, '/settings/agents');
    await expect(page.getByRole('heading', { name: 'Agents', level: 2 })).toBeVisible();
    await expect(page.getByTestId('routing-table')).toBeVisible();
    await expect(page.getByTestId('agent-row-qa')).toContainText('codex (Global default)');
    await page.getByLabel('Provider for reviewer', { exact: true }).selectOption('codex');
    await page.getByLabel('Model for reviewer').fill('gpt-5');
    await page.getByLabel('Fallback Claude Code').check();
    await page.getByLabel('Disable Gemini CLI').check();
    await page.getByLabel('Single model').check();
    await page.getByRole('button', { name: 'Save to project' }).click();
    await expect(page.getByTestId('action-result')).toContainText('Saved to sentinel.config.yaml');
    const [sent] = (await puts(api, /\/agents$/)).map(bodyOf);
    expect(sent.scope).toBe('project');
    expect(sent.project).toBe('digital-hr');
    expect(sent.sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(sent.agents).toEqual({ reviewer: { runner: 'codex', model: 'gpt-5' } });
    expect(sent.providers).toEqual({ fallback: ['claude'], disabled: ['gemini'] });
    expect(sent.single_model).toBe(true);
    await expect(page.getByTestId('agent-row-reviewer')).toContainText('codex / gpt-5 (Project)');
  });

  test('a stale file is refused with a clear message and can be reloaded', async ({ page, baseURL }) => {
    await open(page, '/projects/digital-hr/agents');
    await expect(page.getByTestId('routing-table')).toBeVisible();
    await page.request.post(`${baseURL}/__control/agents-touch`, { data: { project: 'digital-hr' } });
    await page.getByLabel('Provider for qa', { exact: true }).selectOption('claude');
    await page.getByRole('button', { name: 'Save to project' }).click();
    await expect(page.getByTestId('action-result')).toContainText('changed after it was loaded');
    await page.getByRole('button', { name: 'Reload file' }).click();
    await expect(page.getByRole('button', { name: 'Reload file' })).toHaveCount(0);
    await page.getByLabel('Provider for qa', { exact: true }).selectOption('claude');
    await page.getByRole('button', { name: 'Save to project' }).click();
    await expect(page.getByTestId('action-result')).toContainText('Saved to sentinel.config.yaml');
  });

  test('the scope switch saves a global default without a project', async ({ page, api }) => {
    await open(page, '/settings/agents');
    await page.getByRole('radio', { name: 'Global default' }).check();
    await expect(page.getByText('copied into the configuration of projects created afterwards')).toBeVisible();
    await page.getByLabel('Provider for specifier', { exact: true }).selectOption('gemini');
    await page.getByRole('button', { name: 'Save global default' }).click();
    await expect(page.getByTestId('action-result')).toContainText('Saved as global default');
    const [sent] = (await puts(api, /\/agents$/)).map(bodyOf);
    expect(sent.scope).toBe('global');
    expect(sent).not.toHaveProperty('project');
    expect(sent).not.toHaveProperty('sha256');
    expect(sent).not.toHaveProperty('single_model');
    await expect(page.getByLabel('Single model')).toHaveCount(0);
    expect(sent.agents).toEqual({ specifier: { runner: 'gemini' }, qa: { runner: 'codex' } });
  });

  test('a server refusal is shown', async ({ page, api }) => {
    await open(page, '/projects/digital-hr/agents');
    await expect(page.getByTestId('routing-table')).toBeVisible();
    await api.rule({ method: 'PUT', path: '/api/v1/agents', status: 400, body: { error: { code: 'E_VALIDATION', message: 'unknown provider zzz', details: { field: 'agents.qa.runner' } } } });
    await page.getByLabel('Provider for qa', { exact: true }).selectOption('claude');
    await page.getByRole('button', { name: 'Save to project' }).click();
    await expect(page.getByTestId('action-result')).toContainText('unknown provider zzz');
    await expect(page.getByTestId('error-view')).toContainText('E_VALIDATION');
  });
});

test.describe('project creation', () => {
  test('wizard: folder, repositories, AI team, create', async ({ page, api }) => {
    await open(page, '/projects');
    await page.getByRole('button', { name: 'Create project' }).click();
    await expect(heading(page, 'Create project')).toBeVisible();

    // Step 1: Project folder
    await page.getByRole('button', { name: 'Or enter folder path manually' }).click();
    await page.getByLabel('Project folder').fill('/home/dev/projects/billing');
    await page.getByRole('button', { name: 'Use this folder' }).click();

    // Step 2: Repositories
    await expect(page.getByText('Repos found in this folder')).toBeVisible();

    // Step 3: Shared knowledge
    await page.getByText('Team knowledge repo').click();
    await page.getByLabel('Git URL').fill('git@example.test:team/state.git');

    // Create project
    await page.getByRole('button', { name: 'Create project' }).click();
    await expect(page).toHaveURL(/#\/projects\/billing\/floor/);

    const [sent] = (await api.posts(/\/api\/v1\/projects$/)).map(bodyOf);
    expect(sent).toMatchObject({
      name: 'billing',
      path: '/home/dev/projects/billing',
      shared: { mode: 'git', url: 'git@example.test:team/state.git' },
    });
    await open(page, '/projects/billing/repositories');
    await expect(page.getByTestId('repo-row')).toHaveCount(1);
  });

  test('add and remove repositories on the Repositories tab; the last one cannot go', async ({ page, api }) => {
    await open(page, '/projects/new');
    await page.getByRole('button', { name: 'Or enter folder path manually' }).click();
    await page.getByLabel('Project folder').fill('/home/dev/projects/solo');
    await page.getByRole('button', { name: 'Use this folder' }).click();
    await page.getByRole('button', { name: 'Create project' }).click();
    await expect(page).toHaveURL(/#\/projects\/solo\/floor/);
    await open(page, '/projects/solo/repositories');
    await expect(page.getByTestId('repo-row')).toHaveCount(1);

    await page.getByRole('button', { name: 'Add repository' }).click();
    await page.getByRole('textbox', { name: 'Repository folder' }).fill('/home/dev/projects/hr-frontend');
    await page.getByLabel('Role').selectOption('frontend');
    await page.getByRole('button', { name: 'Add to project' }).click();
    await expect(page.getByTestId('repo-row')).toHaveCount(2);
    const added = (await api.posts(/projects\/solo\/repositories$/)).map(bodyOf);
    expect(added).toEqual([{ path: '/home/dev/projects/hr-frontend', role: 'frontend' }]);

    await page.getByRole('button', { name: 'Remove repository hr-frontend' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Remove repository' }).click();
    await expect(page.getByTestId('repo-row')).toHaveCount(1);
    expect((await api.requests()).filter((r) => r.method === 'DELETE').map((r) => r.path)).toEqual(['/api/v1/projects/solo/repositories/hr-frontend']);

    const last = page.getByRole('button', { name: /^Remove repository (hr-backend|solo)/ });
    await expect(last).toBeDisabled();
    await expect(last).toHaveAccessibleDescription('A project needs at least one repository. Add another first, or delete the project.');
    await expect(page.getByTestId('repo-row')).toHaveCount(1);

    await page.getByRole('button', { name: 'Delete project' }).click();
    const dlg = page.getByRole('dialog');
    await expect(dlg).toContainText('NOT deleted');
    await dlg.getByRole('button', { name: 'Keep project' }).click();
    expect((await api.requests()).filter((r) => r.method === 'DELETE' && r.path === '/api/v1/projects/solo')).toEqual([]);
    await page.getByRole('button', { name: 'Delete project' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Delete project' }).click();
    await expect(heading(page, 'Projects')).toBeVisible();
    await expect(page).toHaveURL(/\/projects$/);
    await expect(page.getByTestId('action-result')).toContainText(/Deleted project (Solo|solo)/);
    await expect(page.getByRole('link', { name: /^solo$/i })).toHaveCount(0);
    expect((await api.requests()).filter((r) => r.method === 'DELETE').map((r) => r.path)).toContain('/api/v1/projects/solo');
  });

  test('a server 409 on project delete or repository remove is shown', async ({ page }) => {
    await open(page, '/projects/digital-hr');
    await page.getByRole('button', { name: 'Delete project' }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Delete project' }).click();
    await expect(page.getByTestId('action-result')).toContainText('a run is not finished');
    await expect(heading(page, 'digital-hr')).toBeVisible();

    await open(page, '/projects/digital-hr/repositories');
    await page.getByRole('button', { name: /^Remove repository / }).first().click();
    await page.getByRole('dialog').getByRole('button', { name: 'Remove repository' }).click();
    await expect(page.getByTestId('action-result')).toContainText('a run is not finished');
  });

  test('the empty state offers Create project, and a folder with a config can be registered', async ({ page, api }) => {
    await api.set(['projects'], []);
    await open(page, '/projects');
    await expect(page.getByText('No project registered')).toBeVisible();
    await expect(page.getByRole('main').getByRole('button', { name: 'Create project' })).toHaveCount(2);
    await page.getByRole('button', { name: 'Register existing folder' }).click();
    await page.getByRole('textbox', { name: 'Workspace folder' }).fill('/home/dev/projects/legacy');
    await page.getByRole('button', { name: 'Register folder' }).click();
    await expect(heading(page, 'legacy')).toBeVisible();
    const [sent] = (await api.posts(/projects\/register$/)).map(bodyOf);
    expect(sent).toEqual({ path: '/home/dev/projects/legacy' });
  });

  test('a folder without a config cannot be registered and the error is shown', async ({ page }) => {
    await open(page, '/projects');
    await page.getByRole('button', { name: 'Register existing folder' }).click();
    await page.getByRole('textbox', { name: 'Workspace folder' }).fill('/home/dev/Documents');
    await page.getByRole('button', { name: 'Register folder' }).click();
    await expect(page.getByTestId('register-form').getByTestId('action-result')).toContainText('no sentinel.config.yaml');
  });
});

test.describe('layout and accessibility of the new screens', () => {
  const screens: [string, string, string][] = [
    ['Providers', '/settings/providers', 'Providers'],
    ['Agents', '/settings/agents', 'Agents'],
    ['Project agents', '/projects/digital-hr/agents', 'Agents'],
    ['Create project', '/projects/new', 'Create project'],
    ['Repositories', '/projects/digital-hr/repositories', 'Repositories'],
  ];
  for (const theme of ['light', 'dark'] as const) {
    for (const [name, route, wait] of screens) {
      test(`no serious axe violation: ${name} (${theme})`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: theme });
        await open(page, route);
        await expect(page.getByRole('heading', { name: wait }).first()).toBeVisible();
        await expect(page.getByRole('main').getByText('Loading', { exact: true })).toHaveCount(0);
        const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
        const bad = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
        expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([]);
      });
    }
  }

  test('phone width: no horizontal page scroll', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    for (const [, route, wait] of screens.concat([['Projects', '/projects', 'Projects']])) {
      await open(page, route);
      await expect(page.getByRole('heading', { name: wait }).first()).toBeVisible();
      await expect(page.getByRole('main').getByText('Loading', { exact: true })).toHaveCount(0);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(over, route).toBeLessThanOrEqual(0);
    }
  });
});

test.describe('empty states and long values', () => {
  test('Agents without a project shows an empty state, not an empty editor', async ({ page, api }) => {
    await api.rule({ method: 'GET', path: 're:^/api/v1/projects(\\?.*)?$', status: 200, body: { items: [], next: null } });
    await open(page, '/settings/agents');
    const empty = page.getByTestId('agents-no-project');
    await expect(empty).toBeVisible();
    await expect(empty.getByRole('link', { name: 'Create project' })).toHaveAttribute('href', /\/projects\/new$/);
    await expect(empty).toContainText('Global default');
    await expect(page.getByTestId('routing-table')).toHaveCount(0);
    await expect(page.getByText(/A save is refused/)).toHaveCount(0);
    await page.getByLabel('Global default').check();
    await expect(page.getByTestId('routing-table')).toBeVisible();
    await expect(page.getByText(/^File\s*\./)).toHaveCount(0);
  });

  test('a long provider path stays inside its card', async ({ page, api }) => {
    const long = '/home/x/.nvm/versions/node/v24.19.0/lib/node_modules/@scope/some-very-long-package-name/bin/gemini';
    await api.rule({
      method: 'GET',
      path: 're:^/api/v1/providers(\\?.*)?$',
      status: 200,
      body: { orchestrator: null, items: [{ id: 'gemini', label: 'Gemini CLI', command: 'gemini', installed: true, path: long, capabilities: { model_select: true, resume: false, json_output: true } }] },
    });
    await open(page, '/settings/providers');
    const card = page.getByTestId('provider-gemini');
    await expect(card).toContainText(long);
    const over = await card.evaluate((el) => el.scrollWidth > el.clientWidth + 1);
    expect(over).toBe(false);
  });
});

test.describe('model select tied to the provider', () => {
  test('list, Custom..., reset on provider change and disabled control', async ({ page, api }) => {
    await open(page, '/settings/agents');
    await expect(page.getByTestId('routing-table')).toBeVisible();
    const provider = page.getByLabel('Provider for reviewer', { exact: true });
    const model = page.getByLabel('Model for reviewer', { exact: true });
    await provider.selectOption('claude');
    await expect(model.locator('option')).toHaveText(['Provider default', 'Opus', 'Sonnet', 'Haiku', 'Custom...']);
    await model.selectOption('sonnet');
    await provider.selectOption('gemini');
    await expect(model).toHaveValue('');
    await model.selectOption('__custom__');
    await page.getByLabel('Custom model id for reviewer').fill('gemini-exp-1');
    await provider.selectOption('claude');
    await expect(page.getByLabel('Custom model id for reviewer')).toHaveCount(0);
    await model.selectOption('haiku');
    await provider.selectOption('agy');
    await expect(model).toBeDisabled();
    await expect(page.getByTestId('agent-row-reviewer')).toContainText('has no model option');
    await provider.selectOption('claude');
    await model.selectOption('opus');
    await page.getByRole('button', { name: 'Save to project' }).click();
    await expect(page.getByTestId('action-result')).toContainText('Saved to sentinel.config.yaml');
    const [sent] = (await puts(api, /\/agents$/)).map(bodyOf);
    expect(sent.agents).toEqual({ reviewer: { runner: 'claude', model: 'opus' } });
  });

  test('a saved model outside the list is preselected as Custom', async ({ page }) => {
    await open(page, '/settings/agents');
    const provider = page.getByLabel('Provider for qa', { exact: true });
    await provider.selectOption('claude');
    await page.getByLabel('Model for qa', { exact: true }).selectOption('__custom__');
    await page.getByLabel('Custom model id for qa').fill('claude-x-9');
    await page.getByRole('button', { name: 'Save to project' }).click();
    await expect(page.getByTestId('action-result')).toContainText('Saved to sentinel.config.yaml');
    await page.reload();
    await expect(page.getByLabel('Model for qa', { exact: true })).toHaveValue('__custom__');
    await expect(page.getByLabel('Custom model id for qa')).toHaveValue('claude-x-9');
  });
});
