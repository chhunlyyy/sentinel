import { test, expect, open, RUN, REPORT, heading } from './helpers.ts';

const RUN_URL = '/projects/digital-hr/runs/leave-balance';
const FORM_URL = '/projects/digital-hr/runs/leave-form';
const ACCEPT = /\/tasks\/leave-form\/acceptance$/;
const LABEL = 'Type the first 8 characters of the sha256 to confirm';

test.beforeEach(async ({ api }) => {
  await api.preset('reviewing');
});

test.describe('TDD cycles', () => {
  test('AC-TDD-06g the cycles of a run', async ({ page }) => {
    await open(page, `${RUN_URL}/tdd`);
    const cycles = page.getByTestId(/^cycle-/);
    await expect(cycles).toHaveCount(3);
    const c = page.getByTestId('cycle-remaining');
    await expect(c).toContainText('Shows the remaining leave balance');
    await expect(c).toContainText('backend');
    await expect(c).toContainText('CYCLE_ACCEPTED');
    for (const phase of ['Red', 'Green', 'Refactor']) await expect(c.getByTestId(`phase-${phase.toLowerCase()}`)).toBeVisible();
    const red = c.getByTestId('phase-red');
    await expect(red).toContainText('t-rem-red');
    await expect(red).toContainText('attempt 1');
    await expect(red.getByRole('link', { name: 'e-rem-red' })).toHaveAttribute('href', /#\/projects\/digital-hr\/runs\/leave-balance\/evidence\/e-rem-red/);
    await expect(page.getByTestId('cycle-carry')).toContainText('REJECTED');
    await expect(page.getByTestId('cycle-accrual')).toContainText('GREEN_RUNNING');
  });

  test('AC-TDD-06h the evidence of a phase', async ({ page, api }) => {
    await open(page, `${RUN_URL}/tdd`);
    await page.getByTestId('cycle-remaining').getByRole('link', { name: 'e-rem-red' }).click();
    const main = page.getByRole('main');
    for (const t of ['./gradlew test', 'Exit code 1', '1 passed', '3 failed', 'expected_failure', '2026-11-14 09:05:00 UTC', '2026-11-14 09:05:40 UTC', 'codex', 'gpt-5']) await expect(main).toContainText(t);
    await expect(page.getByTestId('evidence-output')).toContainText('FAILED LeaveTest.remaining');
    expect((await api.gets(/artifacts\/a-out1$/)).length).toBeGreaterThan(0);
  });

  test('AC-TDD-06i evidence output that changed on disk', async ({ page, api }) => {
    await api.rule({ method: 'GET', path: '/api/v1/tasks/leave-balance/artifacts/a-out1', status: 409, body: { error: { code: 'E_INTEGRITY', message: 'artifact changed on disk', details: { sha256: 'ee'.repeat(32) } } } });
    await open(page, `${RUN_URL}/evidence/e-rem-red`);
    await expect(page.getByText('The file changed after it was stored. Its content is not shown.')).toBeVisible();
    await expect(page.getByRole('main')).toContainText('ee'.repeat(32));
    await expect(page.getByTestId('evidence-output')).toHaveCount(0);
  });

  test('AC-TDD-06j a run before execution has no cycles', async ({ page, api }) => {
    await api.set([...RUN('leave-balance'), 'tdd'], { cycles: [], evidence: [] });
    await open(page, `${RUN_URL}/tdd`);
    await expect(page.getByText('No TDD cycles yet. Cycles are planned after the Gherkin approval.')).toBeVisible();
  });
});

test.describe('verification evidence', () => {
  test('AC-VER-02f the evidence rows of the latest round', async ({ page }) => {
    await open(page, `${RUN_URL}/verification`);
    const main = page.getByRole('main');
    await expect(main).toContainText('Round 2');
    await expect(main).toContainText('2026-11-14 09:20:00 UTC');
    const row = page.getByTestId('evidence-row-e-ver-test');
    for (const t of ['backend', 'test', 'passed', 'Exit code 0', '42 passed', '0 failed', '2026-11-14 09:20:10 UTC']) await expect(row).toContainText(t);
    await expect(row.getByRole('link', { name: 'Output' })).toBeVisible();
    const notRun = page.getByTestId('not-run');
    await expect(notRun).toContainText('lint');
    await expect(notRun).toContainText('build');
    // the server reports a check that did not run as a row without an exit code
    await expect(notRun).toContainText('not_run');
    await expect(page.getByTestId('missing-evidence')).not.toContainText('lint');
    await expect(page.getByTestId('missing-evidence')).toContainText('frontend');
  });

  test('AC-VER-02g agent claims are not shown as evidence', async ({ page }) => {
    await open(page, `${RUN_URL}/verification`);
    await expect(page.getByTestId('missing-evidence')).toContainText('no evidence row');
    await expect(page.getByRole('main')).not.toContainText('all tests pass');
  });

  test('AC-VER-03g the computed acceptance and its reasons', async ({ page, api }) => {
    await api.set([...RUN('leave-balance'), 'verification', 'acceptance'], {
      computed: 'rejected',
      reasons: [{ text: 'required tests fail', view: 'verification' }, { text: 'required reviews open', view: 'tdd' }],
    });
    await open(page, `${RUN_URL}/verification`);
    const panel = page.getByTestId('acceptance-computed');
    await expect(panel).toContainText('Computed: rejected');
    const items = panel.getByRole('listitem');
    await expect(items).toHaveCount(2);
    await expect(items.nth(0)).toContainText('required tests fail');
    await expect(items.nth(1)).toContainText('required reviews open');
    // the server sends reasons as text without a view; every reason links to the verification view
    await expect(items.nth(1).getByRole('link')).toHaveAttribute('href', /\/verification$/);
  });
});

test.describe('final acceptance', () => {
  test('AC-VER-04n confirming acceptance', async ({ page, api }) => {
    await open(page, `${FORM_URL}/acceptance`);
    await expect(page.getByTestId('report-summary')).toBeVisible();
    await page.getByLabel(LABEL).fill('77ab01cd');
    await page.getByRole('button', { name: 'Confirm acceptance' }).click();
    await expect(page.getByTestId('decision-record')).toBeVisible();
    const posts = await api.posts(ACCEPT);
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toEqual({ sha256_of_report: REPORT, confirmation: '77ab01cd', decision: 'accept', comment: null });
    const rec = page.getByTestId('decision-record');
    await expect(rec).toContainText('Acceptance confirmed');
    await expect(rec).toContainText('dashboard');
  });

  const states: { name: string; setup: (api: import('./helpers.ts').Api) => Promise<void>; confirm: boolean; reject: boolean; text: string }[] = [
    {
      name: 'computed acceptance rejected',
      setup: async (api) => api.set([...RUN('leave-form'), 'verification', 'acceptance'], { computed: 'rejected', reasons: [{ text: 'required tests fail', view: 'verification' }] }),
      confirm: false, reject: true, text: 'The engine rejected this run',
    },
    { name: 'REVIEWING', setup: async (api) => api.set([...RUN('leave-form'), 'detail', 'state'], 'REVIEWING'), confirm: false, reject: false, text: 'Acceptance is possible when the run is COMPLETED' },
    {
      name: 'already confirmed',
      setup: async (api) => api.set([...RUN('leave-form'), 'detail', 'acceptance_status'], 'accepted'),
      confirm: false, reject: true, text: 'Acceptance confirmed',
    },
  ];
  for (const s of states) {
    test(`AC-VER-04o acceptance cannot be confirmed when the engine does not allow it: ${s.name}`, async ({ page, api }) => {
      await s.setup(api);
      await open(page, `${FORM_URL}/acceptance`);
      await expect(page.getByTestId('acceptance-panel')).toContainText(s.text);
      await expect(page.getByRole('button', { name: 'Confirm acceptance' })).toHaveCount(0);
      await expect(page.getByRole('radio', { name: 'Accept', exact: true })).toHaveCount(0);
      await expect(page.getByRole('radio', { name: 'Reject', exact: true })).toHaveCount(s.reject ? 1 : 0);
      if (s.reject) await expect(page.getByRole('radio', { name: 'Reject', exact: true })).toBeEnabled();
    });
  }

  test('AC-VER-04p rejecting a run needs a comment and a second confirmation', async ({ page, api }) => {
    await open(page, `${FORM_URL}/acceptance`);
    await page.getByRole('radio', { name: 'Reject', exact: true }).check();
    await page.getByLabel(LABEL).fill('77ab01cd');
    await expect(page.getByRole('button', { name: 'Reject', exact: true })).toBeDisabled();
    await page.getByLabel('Comment').fill('wrong totals');
    await page.getByRole('button', { name: 'Reject', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    expect(await api.posts(ACCEPT)).toHaveLength(0);
    await dialog.getByRole('button', { name: 'Reject run' }).click();
    await expect(page.getByTestId('decision-record')).toBeVisible();
    expect((await api.posts(ACCEPT))[0].body).toMatchObject({ decision: 'reject', comment: 'wrong totals' });
  });

  test('AC-VER-04q the report changed after the page loaded', async ({ page, api }) => {
    await api.rule({ method: 'POST', path: '/api/v1/tasks/leave-form/acceptance', status: 409, body: { error: { code: 'E_APPROVAL_STALE', message: 'stale', details: {} } } });
    await open(page, `${FORM_URL}/acceptance`);
    await page.getByLabel(LABEL).fill('77ab01cd');
    await page.getByRole('button', { name: 'Confirm acceptance' }).click();
    await expect(page.getByText('The report changed. Nothing was confirmed. Reload the report.')).toBeVisible();
    await api.idle(400);
    expect(await api.posts(ACCEPT)).toHaveLength(1);
  });
});

test.describe('changes and diffs', () => {
  test('AC-GIT-01e the change map of a run', async ({ page }) => {
    await open(page, `${RUN_URL}/changes`);
    const repo = page.getByTestId('changes-repo-backend');
    for (const t of ['feature/leave', 'abc1234', 'def5678', '2 files', '+14', '-3']) await expect(repo).toContainText(t);
    const file = page.getByTestId('file-src/main/Leave.java');
    for (const t of ['modified', '+10', '-3']) await expect(file).toContainText(t);
    await expect(file.getByRole('link', { name: 'remaining', exact: true }).first()).toBeVisible();
    await expect(file.getByRole('link', { name: 't-rem-green' })).toBeVisible();
  });

  for (const mode of ['inline', 'split']) {
    test(`AC-GIT-01f inline and side-by-side diffs: ${mode}`, async ({ page, api }) => {
      await open(page, `${RUN_URL}/changes`);
      await page.getByTestId('file-src/main/Leave.java').getByRole('link', { name: 'Diff' }).click();
      if (mode === 'split') await page.getByRole('button', { name: 'Split' }).click();
      await expect(page.getByTestId('diff-view')).toHaveAttribute('data-mode', mode);
      const req = (await api.gets(/changes\/diff/)).pop()!;
      expect(req.path).toBe('/api/v1/tasks/leave-balance/changes/diff');
      const q = new URLSearchParams(req.search);
      expect(q.get('repo')).toBe('backend');
      expect(q.get('path')).toBe('src/main/Leave.java');
      expect(q.get('mode')).toBe(mode);
      expect(req.search).toContain('path=src%2Fmain%2FLeave.java');
      const view = page.getByTestId('diff-view');
      if (mode === 'inline') {
        const row = view.getByTestId('diff-row').first();
        await expect(row.getByTestId('old-no')).toBeVisible();
        await expect(row.getByTestId('new-no')).toBeVisible();
        await expect(view.locator('[data-side]')).toHaveCount(0);
      } else {
        await expect(view.locator('[data-side="left"]').first()).toBeVisible();
        await expect(view.locator('[data-side="right"]').first()).toBeVisible();
      }
      const add = view.getByTestId('diff-line-add').first();
      await expect(add).toContainText('+');
      await expect(add.getByText('Added line')).toHaveCount(1);
      const del = view.getByTestId('diff-line-del').first();
      await expect(del).toContainText('-');
      await expect(del.getByText('Removed line')).toHaveCount(1);
    });
  }

  const flags: [string, string][] = [['binary', 'Binary file. No diff shown.'], ['truncated', 'The diff is longer than 1 MB. Only the start is shown.']];
  for (const [flag, message] of flags) {
    test(`AC-GIT-01g binary and truncated diffs: ${flag}`, async ({ page, api }) => {
      await api.set([...RUN('leave-balance'), 'diffs', 'backend:src/main/Leave.java', flag], true);
      await open(page, `${RUN_URL}/changes?repo=backend&path=${encodeURIComponent('src/main/Leave.java')}&mode=inline`);
      await expect(page.getByText(message)).toBeVisible();
    });
  }

  test('AC-GIT-03a the change map is part of the run view', async ({ page }) => {
    await open(page, RUN_URL);
    const sum = page.getByTestId('changes-summary');
    await expect(sum).toContainText('backend');
    await expect(sum).toContainText('2 files');
    await expect(sum).toContainText('+14');
    await expect(sum).toContainText('-3');
    await expect(sum.getByRole('link', { name: 'Changes' })).toHaveAttribute('href', `#${RUN_URL}/changes`);
  });
});

test.describe('trace', () => {
  test('AC-TRC-01e the full chain', async ({ page }) => {
    await open(page, `${RUN_URL}/trace`);
    const req = page.getByTestId('trace-req-REQ-LEAVE-01');
    await expect(req).toContainText('AC-LEAVE-01a');
    await expect(req).toContainText('Show the remaining balance');
    await expect(req.getByRole('link', { name: /Show the remaining balance/ })).toHaveAttribute('href', `#${RUN_URL}/gherkin`);
    await expect(req.getByRole('link', { name: 'remaining', exact: true })).toHaveAttribute('href', `#${RUN_URL}/tdd`);
    await expect(req.getByRole('link', { name: 'src/main/Leave.java' })).toHaveAttribute('href', /changes\?repo=backend&path=src%2Fmain%2FLeave\.java/);
    await expect(req.getByRole('link', { name: 'e-rem-red' })).toHaveAttribute('href', `#${RUN_URL}/evidence/e-rem-red`);
    await expect(page.getByTestId('trace-acceptance')).toContainText('pending');
  });

  test('AC-TRC-02d gaps are shown apart from failures', async ({ page, api }) => {
    await api.set([...RUN('leave-balance'), 'trace', 'gaps'], ['AC-3 has no scenario']);
    await api.set([...RUN('leave-balance'), 'tdd', 'evidence', 'id=e-rem-green', 'exit_code'], 1);
    await api.set([...RUN('leave-balance'), 'tdd', 'evidence', 'id=e-rem-green', 'classification'], 'unexpected_failure');
    await open(page, `${RUN_URL}/trace`);
    const gaps = page.getByTestId('trace-gaps');
    const fails = page.getByTestId('trace-failures');
    await expect(gaps).toContainText('Gaps (missing links)');
    await expect(gaps).toContainText('AC-3 has no scenario');
    await expect(fails).toContainText('Failures (failing checks)');
    await expect(fails).toContainText('evidence "test" of cycle "remaining" failed');
    await expect(gaps).not.toContainText('failed');
    await expect(fails).not.toContainText('AC-3 has no scenario');
  });

  test('AC-TRC-02e a run with no trace links yet', async ({ page, api }) => {
    await api.set([...RUN('leave-balance'), 'trace'], { requirements: [], gaps: [], failures: [], acceptance: null });
    await api.set([...RUN('leave-balance'), 'tdd'], { cycles: [], evidence: [] });
    await open(page, `${RUN_URL}/trace`);
    await expect(heading(page, 'Trace')).toBeVisible();
    await expect(page.getByText('No trace links yet')).toBeVisible();
    await expect(page.getByText(/^Gaps/)).toHaveCount(0);
    await expect(page.getByText(/^Failures/)).toHaveCount(0);
  });
});
