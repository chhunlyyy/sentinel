import { test, expect, open, nav, heading } from './helpers.ts';

test.describe('Phase 1 Simplified UI requirements', () => {
  test('navigation has exactly 4 items: Floor, New task, Projects, Settings', async ({ page }) => {
    await open(page, '/');
    const mainNav = nav(page);
    const links = mainNav.getByRole('link');
    await expect(links).toHaveCount(4);
    await expect(links.nth(0)).toHaveText('Floor');
    await expect(links.nth(1)).toHaveText('New task');
    await expect(links.nth(2)).toHaveText('Projects');
    await expect(links.nth(3)).toHaveText('Settings');

    // More menu removed
    await expect(page.getByRole('button', { name: /More/ })).toHaveCount(0);
  });

  test('Start task shows the blocking reason when blocked', async ({ page }) => {
    await open(page, '/tasks/new');

    // Empty request: blocked
    const startBtn = page.getByRole('button', { name: 'Start task' });
    await expect(startBtn).toBeDisabled();
    await expect(page.getByText('Enter what the factory should build above.')).toBeVisible();

    // Fill request: now enabled (repos pre-ticked)
    await page.getByLabel('Request').fill('Add export leave as CSV');
    await expect(startBtn).toBeEnabled();

    // Untick all repos: blocked with repo reason
    const checkboxes = page.getByRole('checkbox');
    const count = await checkboxes.count();
    for (let i = 0; i < count; i++) {
      if (await checkboxes.nth(i).isChecked()) {
        await checkboxes.nth(i).uncheck();
      }
    }
    await expect(startBtn).toBeDisabled();
    await expect(page.getByText('Pick at least one repository.')).toBeVisible();
  });

  test('pick-folder fallback to a typed path on 501 E_UNAVAILABLE', async ({ page, api }) => {
    // Mock 501 on pick-folder
    await api.rule({
      method: 'POST',
      path: '/api/v1/pick-folder',
      status: 501,
      body: { error: { code: 'E_UNAVAILABLE', message: 'No folder picker installed (zenity, kdialog, osascript)' } },
    });

    await open(page, '/projects/new');
    await expect(page.getByText('Choose folder…')).toBeVisible();

    // Click "Choose folder…"
    await page.getByText('Choose folder…').click();

    // Falls back to a typed path field
    const typedPath = page.getByLabel('Project folder');
    await expect(typedPath).toBeVisible();
    await typedPath.fill('/home/dev/projects/digital-hr');
    await expect(typedPath).toHaveValue('/home/dev/projects/digital-hr');
  });

  test('decision card actions send the right control body', async ({ page, api }) => {
    // Park the run on digital-hr factory so the amber decision card appears with tests-already-pass options
    await api.set(['factory', 'digital-hr', 'runs', '0', 'state'], 'NEEDS_HUMAN');
    await api.set(['factory', 'digital-hr', 'runs', '0', 'attention'], {
      kind: 'needs_human',
      reason: 'All 8 tests for this part already pass. Earlier parts built this behaviour. Accept it as already implemented?',
    });

    await open(page, '/projects/digital-hr/floor');
    await expect(heading(page, 'Factory floor')).toBeVisible();

    // Amber decision card is visible with the action buttons
    const acceptBtn = page.getByRole('button', { name: 'Accept as already implemented' });
    const backBtn = page.getByRole('button', { name: 'Send back to the test writer' });
    const ownWordsBtn = page.getByRole('button', { name: 'Answer in my own words' });

    await expect(acceptBtn).toBeVisible();
    await expect(backBtn).toBeVisible();
    await expect(ownWordsBtn).toBeVisible();

    // Test "Accept as already implemented" sends {"action": "already_implemented"}
    await acceptBtn.click();
    await expect(page.getByText(/^Sent\./)).toBeVisible();
    let posts = await api.posts(/\/tasks\/leave-balance\/control$/);
    expect(posts.length).toBeGreaterThan(0);
    expect((posts[posts.length - 1].body as Record<string, unknown>).action).toBe('already_implemented');

    // Re-park and test "Send back to the test writer" sends {"action": "back_to_red"}
    await api.set(['factory', 'digital-hr', 'runs', '0', 'state'], 'NEEDS_HUMAN');
    await api.set(['factory', 'digital-hr', 'runs', '0', 'attention'], {
      kind: 'needs_human',
      reason: 'All 8 tests for this part already pass. Earlier parts built this behaviour. Accept it as already implemented?',
    });
    await page.reload();
    await backBtn.click();
    await expect(page.getByText(/^Sent\./)).toBeVisible();
    posts = await api.posts(/\/tasks\/leave-balance\/control$/);
    expect((posts[posts.length - 1].body as Record<string, unknown>).action).toBe('back_to_red');

    // Re-park and test "Answer in my own words" custom action
    await api.set(['runs', 'digital-hr/leave-balance', 'detail', 'state'], 'NEEDS_HUMAN');
    await api.set(['factory', 'digital-hr', 'runs', '0', 'state'], 'NEEDS_HUMAN');
    await api.set(['factory', 'digital-hr', 'runs', '0', 'attention'], {
      kind: 'needs_human',
      reason: 'All 8 tests for this part already pass. Earlier parts built this behaviour. Accept it as already implemented?',
    });
    await page.reload();
    await ownWordsBtn.click();
    const customTextarea = page.getByPlaceholder(/Accept it, but also add a test/);
    await customTextarea.fill('Please skip the flaky test and proceed');
    const sendBtn = page.getByRole('button', { name: 'Send to the orchestrator' });
    await sendBtn.click();
    await expect(page.getByText(/^Sent\./)).toBeVisible();
    posts = await api.posts(/\/tasks\/leave-balance\/control$/);
    expect((posts[posts.length - 1].body as Record<string, unknown>).action).toBe('resume');
    expect((posts[posts.length - 1].body as Record<string, unknown>).comment).toBe('Please skip the flaky test and proceed');

    // Test FAILED run shows "Retry"
    await api.set(['runs', 'digital-hr/leave-balance', 'detail', 'state'], 'FAILED');
    await api.set(['factory', 'digital-hr', 'runs', '0', 'state'], 'FAILED');
    await api.set(['factory', 'digital-hr', 'runs', '0', 'attention'], {
      kind: 'failed',
      reason: 'Gradle build failed with exit code 1',
    });
    await page.reload();
    const retryBtn = page.getByRole('button', { name: 'Retry' });
    await expect(retryBtn).toBeVisible();
    await retryBtn.click();
    await expect(page.getByText(/^Sent\./)).toBeVisible();
    posts = await api.posts(/\/tasks\/leave-balance\/control$/);
    expect((posts[posts.length - 1].body as Record<string, unknown>).action).toBe('retry');
  });

  test('Settings screen is one page, no tabs, matching Settings.dc.html', async ({ page }) => {
    await open(page, '/settings');
    await expect(heading(page, 'Settings')).toBeVisible();

    // Section 1: AI tools on this computer
    await expect(page.getByRole('heading', { name: 'AI tools on this computer' })).toBeVisible();
    await expect(page.getByRole('button', { name: /Test Claude/ })).toBeVisible();

    // Section 2: AI team
    await expect(page.getByRole('heading', { name: 'AI team' })).toBeVisible();
    await expect(page.getByRole('radio', { name: 'Recommended mix' })).toBeVisible();
    await expect(page.getByRole('radio', { name: 'One AI for everything' })).toBeVisible();
    await expect(page.getByRole('radio', { name: 'Custom' })).toBeVisible();

    // Stations in the table
    await expect(page.getByText('Spec writer')).toBeVisible();
    await expect(page.getByText('Scenario writer')).toBeVisible();
    await expect(page.getByText('Test writer')).toBeVisible();
    await expect(page.getByText('Coder')).toBeVisible();
    await expect(page.getByText('Reviewer')).toBeVisible();
    await expect(page.getByText('QA')).toBeVisible();

    // Section 3: Orchestrator with answer_from_spec
    await expect(page.getByRole('heading', { name: 'Orchestrator' })).toBeVisible();
    const specAnswerCheck = page.getByLabel('Answer from the approved spec when it settles the question, and show me which section it used');
    await expect(specAnswerCheck).toBeVisible();

    // Section 4: Notify me
    await expect(page.getByRole('heading', { name: 'Notify me' })).toBeVisible();
    await expect(page.getByLabel('When the orchestrator needs a decision')).toBeVisible();
    await expect(page.getByLabel('When a task is finished')).toBeVisible();

    // Section 5: Advanced (folded)
    const advanced = page.getByText('Advanced');
    await expect(advanced).toBeVisible();
  });
});
