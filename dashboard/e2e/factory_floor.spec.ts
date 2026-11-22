import { test, expect, open, heading, nav, decide } from './helpers.ts';

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
    // Waiting gate opens Review tab in place
    await expect(sidePanel.getByRole('button', { name: /Review/ })).toHaveAttribute('aria-pressed', 'true');
    await expect(sidePanel.getByRole('button', { name: /Expand/i })).toBeVisible();
    await sidePanel.getByRole('button', { name: 'Station' }).click();
    await expect(sidePanel.getByRole('heading', { level: 2, name: 'You approve spec' })).toBeVisible();
    await expect(sidePanel.getByText('Needs you')).toBeVisible();
    const bg = await page.getByRole('region', { name: 'Factory network' }).evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(bg).toBe('rgb(14, 20, 25)');
    // the final gate links to the report
    await page.getByRole('button', { name: /^You accept:/ }).click({ force: true });
    await expect(sidePanel.getByRole('link', { name: 'Open the report' })).toBeVisible();
  });

  test('a run that needs you shows why and links to the run, not to a review with no decision', async ({ page, api }) => {
    await api.set(['factory', 'digital-hr', 'runs', 1, 'state'], 'NEEDS_HUMAN');
    await api.set(['factory', 'digital-hr', 'runs', 1, 'attention'], { kind: 'needs_human', reason: 'imported specification invalid for tier 3' });
    await open(page, '/floor');
    await page.getByRole('group', { name: 'Tasks on the floor' }).getByRole('button', { name: /Fix payroll rounding/ }).click();
    const sidePanel = page.getByRole('complementary', { name: 'Selected station' });
    await expect(sidePanel.getByTestId('floor-attention')).toHaveText('Needs you: imported specification invalid for tier 3');
    await expect(sidePanel.getByRole('button', { name: 'Resume' })).toBeVisible();
    await expect(sidePanel.getByRole('link', { name: /Open the full run/i })).toHaveAttribute('href', /runs\/payroll-rounding$/);
    await expect(sidePanel.getByRole('link', { name: 'Review specification' })).toHaveCount(0);
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

  test('a task waiting for a usage limit shows the paused look with the retry time', async ({ page, api }) => {
    await api.set(['factory', 'digital-hr', 'runs', 2, 'stations', 'triage'], 'limit');
    await api.set(['factory', 'digital-hr', 'runs', 2, 'agents'], {});
    await api.set(['factory', 'digital-hr', 'runs', 2, 'limit'], {
      station: 'triage', task: 't-0123456789ad', role: 'triage', runner: 'agy', retry_at: '2026-11-21T14:05:00.000000Z', reason: 'quota exceeded',
    });
    await open(page, '/projects/digital-hr/floor?task=audit-log-filter');
    const chip = page.getByRole('group', { name: 'Tasks on the floor' }).getByRole('button', { name: /Audit log filter/ });
    await expect(chip).toContainText(/Waiting for usage limit · retries \d\d:\d\d/);
    await expect(page.getByRole('button', { name: 'Triage: Waiting for usage limit' })).toBeVisible();
    await page.getByRole('button', { name: /^Triage:/ }).click();
    await expect(page.getByRole('complementary', { name: 'Selected station' })).toContainText('Waiting for usage limit');
  });

  test('Fix routing: banner, suggestion, preview, save', async ({ page, api }) => {
    await api.set(['factory', 'digital-hr', 'routing'], { problems: ['triage routes to the native adapter', 'qa routes to the native adapter'] });
    await open(page, '/projects/digital-hr/floor');
    const banner = page.getByTestId('fix-routing-banner');
    await expect(banner).toBeVisible();
    await banner.getByRole('button', { name: 'Fix routing' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByLabel('Runner for triage')).toHaveValue('claude');
    await dialog.getByLabel('Model for qa').fill('claude-haiku-5-5');
    await dialog.getByRole('button', { name: 'Preview the YAML change' }).click();
    await expect(dialog.getByTestId('unified-diff')).toContainText('agents.qa.model');
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(banner).toBeHidden();
    const posts = await api.posts(/\/config\/save$/);
    const body = posts[0].body as { changes: { path: string; value: unknown }[]; comment: string };
    expect(body.comment).toBe('Fix routing');
    expect(body.changes).toContainEqual({ path: 'single_model', value: false });
    expect(body.changes).toContainEqual({ path: 'agents.qa.model', value: 'claude-haiku-5-5' });
  });

  test('the project home shows the Fix routing banner too', async ({ page, api }) => {
    await api.set(['factory', 'digital-hr', 'routing'], { problems: ['triage routes to the native adapter'] });
    await open(page, '/projects/digital-hr');
    await expect(page.getByTestId('fix-routing-banner')).toBeVisible();
  });

  test('review in the panel: approve spec from the floor and URL stays on /floor', async ({ page, api }) => {
    await open(page, '/floor');
    await page.getByRole('group', { name: 'Tasks on the floor' }).getByRole('button', { name: /Fix payroll rounding/ }).click();
    const sidePanel = page.getByRole('complementary', { name: 'Selected station' });
    await expect(sidePanel.getByRole('button', { name: /Review/ })).toHaveAttribute('aria-pressed', 'true');
    await decide(page, 'Approve', '3f9a0c12', 'Approve version 2');
    await expect(sidePanel.getByTestId('action-result')).toContainText('approved');
    const posts = await api.posts(/\/approvals/);
    expect(posts.length).toBeGreaterThan(0);
    expect(page.url()).toContain('#/floor');
  });

  test('full-screen review dialog opens, closes on Escape or button, and returns focus to Expand button', async ({ page }) => {
    await open(page, '/floor');
    await page.getByRole('group', { name: 'Tasks on the floor' }).getByRole('button', { name: /Fix payroll rounding/ }).click();
    const sidePanel = page.getByRole('complementary', { name: 'Selected station' });
    const expandBtn = sidePanel.getByRole('button', { name: /Expand/i });
    await expect(expandBtn).toBeVisible();
    await expandBtn.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    expect(page.url()).toContain('#/floor');
    await expect(dialog.getByRole('navigation', { name: 'Sections' })).toBeVisible();
    await dialog.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(expandBtn).toBeFocused();
    await expandBtn.click();
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Exit full screen' }).click();
    await expect(dialog).toBeHidden();
    await expect(expandBtn).toBeFocused();
  });

  test('inline Resume button opens comment dialog and sends control action resume', async ({ page, api }) => {
    await api.set(['factory', 'digital-hr', 'runs', 1, 'state'], 'NEEDS_HUMAN');
    await api.set(['factory', 'digital-hr', 'runs', 1, 'attention'], { kind: 'needs_human', reason: 'imported specification invalid' });
    await open(page, '/floor');
    await page.getByRole('group', { name: 'Tasks on the floor' }).getByRole('button', { name: /Fix payroll rounding/ }).click();
    const sidePanel = page.getByRole('complementary', { name: 'Selected station' });
    const resumeBtn = sidePanel.getByRole('button', { name: 'Resume' });
    await expect(resumeBtn).toBeVisible();
    await resumeBtn.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('textbox').fill('Fixed manually');
    await dialog.getByRole('button', { name: 'Resume', exact: true }).click();
    await expect(dialog).toBeHidden();
    const posts = await api.posts(/\/control/);
    expect(posts.length).toBeGreaterThan(0);
    const body = posts[0].body as { action: string; comment?: string };
    expect(body.action).toBe('resume');
    expect(body.comment).toBe('Fixed manually');
  });

function parseRgb(color: string): [number, number, number] {
  const m = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (!m) return [0, 0, 0];
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

function relativeLuminance(r: number, g: number, b: number): number {
  const srgb = [r, g, b].map((val) => {
    const c = val / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * srgb[0] + 0.7152 * srgb[1] + 0.0722 * srgb[2];
}

function contrastRatio(fg: string, bg: string): number {
  const [r1, g1, b1] = parseRgb(fg);
  const [r2, g2, b2] = parseRgb(bg);
  const l1 = relativeLuminance(r1, g1, b1);
  const l2 = relativeLuminance(r2, g2, b2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

  test('spec body text has contrast ratio >= 4.5 in side panel and full screen', async ({ page }) => {
    await open(page, '/floor');
    await page.getByRole('group', { name: 'Tasks on the floor' }).getByRole('button', { name: /Fix payroll rounding/ }).click();
    const sidePanel = page.getByRole('complementary', { name: 'Selected station' });
    const specPre = sidePanel.getByTestId('spec-text');
    await expect(specPre).toBeVisible();

    const panelColors = await specPre.evaluate((el) => {
      const style = window.getComputedStyle(el);
      let bg = style.backgroundColor;
      let cur: HTMLElement | null = el.parentElement;
      while ((!bg || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') && cur) {
        bg = window.getComputedStyle(cur).backgroundColor;
        cur = cur.parentElement;
      }
      return { color: style.color, bg };
    });
    expect(contrastRatio(panelColors.color, panelColors.bg)).toBeGreaterThanOrEqual(4.5);

    // Expand to full screen
    const expandBtn = sidePanel.getByRole('button', { name: /Expand/i });
    await expandBtn.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const fullSpecPre = dialog.locator('.floor-fullscreen-center pre').first();
    await expect(fullSpecPre).toBeVisible();

    const fullColors = await fullSpecPre.evaluate((el) => {
      const style = window.getComputedStyle(el);
      let bg = style.backgroundColor;
      let cur: HTMLElement | null = el.parentElement;
      while ((!bg || bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent') && cur) {
        bg = window.getComputedStyle(cur).backgroundColor;
        cur = cur.parentElement;
      }
      return { color: style.color, bg };
    });
    expect(contrastRatio(fullColors.color, fullColors.bg)).toBeGreaterThanOrEqual(4.5);
  });

  test('routing switch opens ConfirmDialog and saves routing_mode and orchestrator via configSave', async ({ page, api }) => {
    await open(page, '/projects/digital-hr/floor');
    const routingGroup = page.getByRole('group', { name: 'Model routing' });
    await expect(routingGroup).toBeVisible();
    const perRoleBtn = routingGroup.getByRole('button', { name: 'Per-role routing' });
    const orchBtn = routingGroup.getByRole('button', { name: 'Orchestrator model only' });
    await expect(perRoleBtn).toHaveAttribute('aria-pressed', 'true');
    await orchBtn.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('Switch to orchestrator model only?');
    await expect(dialog.getByLabel('Orchestrator runner')).toBeVisible();
    await expect(dialog.getByLabel('Orchestrator model')).toBeVisible();
    await dialog.getByLabel('Orchestrator model').fill('claude-sonnet-4-6');
    await dialog.getByRole('button', { name: 'Switch to orchestrator' }).click();
    await expect(dialog).toBeHidden();
    const posts = await api.posts(/\/config\/save$/);
    expect(posts.length).toBeGreaterThan(0);
    const saveCall = posts.find((p) => (p.body as { changes?: { path: string }[] }).changes?.some((c) => c.path === 'routing_mode'));
    expect(saveCall).toBeDefined();
    const body = saveCall!.body as { changes: { path: string; value: unknown }[] };
    expect(body.changes).toContainEqual({ path: 'routing_mode', value: 'orchestrator' });
    expect(body.changes).toContainEqual({
      path: 'orchestrator',
      value: { runner: 'claude', model: 'claude-sonnet-4-6' },
    });
  });

  test('clicking a station shows its work log box with Live work or What happened', async ({ page }) => {
    await open(page, '/floor');
    await page.getByRole('button', { name: /^Triage:/ }).click();
    const sidePanel = page.getByRole('complementary', { name: 'Selected station' });
    await expect(sidePanel.getByRole('button', { name: 'Station' })).toHaveAttribute('aria-pressed', 'true');
    await expect(sidePanel.getByRole('heading', { name: /Live work|What happened/i })).toBeVisible();
    const logBox = sidePanel.getByTestId('station-log');
    await expect(logBox).toBeVisible();
    await expect(logBox.locator('li').first()).toBeVisible();
  });
});
