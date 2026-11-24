import { test, expect, open, nav, RUN, H2, H3, G1, SPEC_URL, GHERKIN_URL, settle } from './helpers.ts';

const APPROVALS = /\/tasks\/leave-balance\/approvals$/;

test.beforeEach(async ({ api }) => {
  await api.preset('approvals');
});

test.describe('My Approvals', () => {
  test('AC-SEC-03x approvals waiting across projects', async ({ page, api }) => {
    await open(page, '/approvals');
    const rows = page.getByTestId('approval-row');
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText('digital-hr');
    await expect(rows.nth(0)).toContainText('leave-balance');
    await expect(rows.nth(0)).toContainText('specification');
    await expect(rows.nth(0)).toContainText('3f9a0c12');
    await expect(rows.nth(0)).toContainText('2026-11-14 09:10:00 UTC');
    await expect(rows.nth(1)).toContainText('payroll');
    await expect(rows.nth(1)).toContainText('tax-form');
    await expect(rows.nth(1)).toContainText('gherkin');
    expect((await api.gets(/\/api\/v1\/approvals\?state=IN_REVIEW/)).length).toBeGreaterThan(0);
    // Navigation simplified to 4 items; Approvals is reached directly by URL
    await expect(nav(page).getByRole('link', { name: /^Approvals/ })).toHaveCount(0);
  });

  test('AC-SEC-03y nothing to approve', async ({ page, api }) => {
    await api.preset('no-approvals');
    await open(page, '/approvals');
    await expect(page.getByText('Nothing waits for your approval')).toBeVisible();
  });
});

test.describe('reviewing the specification', () => {
  test('AC-SPA-04d the specification review page', async ({ page }) => {
    await open(page, SPEC_URL);
    await expect(page.getByTestId('review-version')).toHaveText('Version 2');
    await expect(page.getByTestId('sha-full')).toHaveText(H2);
    expect(await page.getByTestId('sha-full').evaluate((e) => getComputedStyle(e).fontFamily)).toMatch(/mono/i);
    await expect(page.getByRole('button', { name: 'Copy sha256' })).toBeVisible();
    await expect(page.getByTestId('validation')).toContainText('1 finding');
    await expect(page.getByTestId('validation')).toContainText('AC-LEAVE-02 has no example');
    const text = page.getByTestId('spec-text');
    await expect(text).toContainText('# Specification: Leave balance');
    await expect(text).toContainText('REQ-LEAVE-01');
    await expect(text).toContainText('AC-LEAVE-01a');
    await page.getByRole('tab', { name: 'Changes since version 1' }).click();
    await expect(page.getByTestId('diff-line-add').first()).toBeVisible();
    await page.getByRole('tab', { name: 'Versions' }).click();
    const v1 = page.getByTestId('version-row-1');
    await expect(v1).toContainText('1c1c1c1c');
    await expect(v1).toContainText('changes');
    await expect(v1).toContainText('dev');
    await expect(v1).toContainText('tty');
    await expect(v1).toContainText('2026-11-14 08:30:00 UTC');
  });

  test('AC-SPA-04e an earlier version is shown read only', async ({ page, api }) => {
    await open(page, SPEC_URL);
    await page.getByRole('tab', { name: 'Versions' }).click();
    await page.getByRole('link', { name: 'Version 1' }).click();
    await expect(page.getByText('Version 1 is not in review')).toBeVisible();
    await expect(page.getByTestId('decision-panel')).toHaveCount(0);
    expect((await api.gets(/specification\/versions\/1/)).length).toBeGreaterThan(0);
  });

  test('AC-SPA-04f knowledge used tab shows records and summaries read by agents', async ({ page }) => {
    await open(page, SPEC_URL);
    await page.getByRole('tab', { name: 'Knowledge used' }).click();
    const knowledgePanel = page.getByTestId('knowledge-used');
    await expect(knowledgePanel).toBeVisible();
    await expect(knowledgePanel.getByRole('heading', { name: 'Change records' })).toBeVisible();
    await expect(knowledgePanel.getByText('pr-212')).toBeVisible();
    await expect(knowledgePanel.getByRole('heading', { name: 'Invariants' })).toBeVisible();
    await expect(knowledgePanel.getByText('HR data only for role HR')).toBeVisible();
  });
});

test.describe('reviewing the Gherkin set', () => {
  test.beforeEach(async ({ api }) => {
    await api.preset('gherkin-review');
  });
  test('AC-GHA-04f the Gherkin review page', async ({ page }) => {
    await open(page, GHERKIN_URL);
    await expect(page.getByTestId('review-version')).toHaveText('Version 1');
    await expect(page.getByTestId('sha-full')).toHaveText(G1);
    const feat = page.getByTestId('feature-leave_balance.feature');
    await expect(feat).toBeVisible();
    const sc = page.getByTestId('scenario-AC-LEAVE-01a');
    for (const t of ['AC-LEAVE-01a', 'e2e', 'P1', 'cov-happy-path']) await expect(sc).toContainText(t);
    const cov = page.getByTestId('coverage-table');
    await expect(cov.getByRole('row')).toHaveCount(15 + 1);
    await expect(cov.getByRole('row', { name: /happy-path/ })).toContainText('covered by 3 scenarios');
    await expect(cov.getByRole('row', { name: /db-failure/ })).toContainText('not applicable');
    await expect(cov.getByRole('row', { name: /db-failure/ })).toContainText('no database');
    const missing = cov.getByRole('row', { name: /concurrency/ });
    await expect(missing).toContainText('Missing');
    await expect(missing.getByTestId('status-icon')).toHaveAttribute('aria-hidden', 'true');
  });

  test('AC-GHA-04g a large Gherkin set stays usable', async ({ page, api }) => {
    const features = Array.from({ length: 12 }, (_, f) => ({
      path: `f${f}.feature`, name: `Feature ${f}`,
      scenarios: Array.from({ length: 34 }, (_, s) => ({ name: `Scenario ${f}-${s}`, ac: `AC-BIG-${f}-${s}`, type: 'unit', priority: 'P2', tags: ['@AC-BIG', '@unit'], cov: ['cov-happy-path'] })),
    }));
    await api.set([...RUN('leave-balance'), 'gherkin', 'features'], features);
    const t0 = Date.now();
    await open(page, GHERKIN_URL);
    await expect(page.getByTestId('scenario-AC-BIG-11-33')).toBeAttached({ timeout: 2000 });
    expect(Date.now() - t0).toBeLessThan(2500);
    // the decision panel sits above the scrollable scenario list: reachable without scrolling through it
    await expect(page.getByRole('button', { name: 'Approve version 1', exact: true })).toBeInViewport();
    await page.getByLabel('Filter scenarios').fill('AC-BIG-3-7');
    await expect(page.getByTestId(/^scenario-/)).toHaveCount(1);
    await page.getByLabel('Filter scenarios').fill('');
  });

  test('AC-GHA-05k approving the Gherkin set', async ({ page, api }) => {
    await open(page, GHERKIN_URL);
    await page.getByRole('button', { name: 'Approve version 1' }).click();
    await expect(page.getByTestId('decision-record')).toBeVisible();
    const posts = await api.posts(APPROVALS);
    expect(posts[0].body).toMatchObject({ gate: 'gherkin', sha256: G1, decision: 'approve' });
    expect((posts[0].body as Record<string, unknown>).confirmation).toBeUndefined();
    await expect(page.getByTestId('decision-record')).toContainText('Approved');
  });
});

test.describe('one-click approvals and decisions', () => {
  test('AC-SPA-05e approving the specification', async ({ page, api }) => {
    await open(page, SPEC_URL);
    await page.getByRole('button', { name: 'Approve version 2' }).click();
    await expect(page.getByTestId('decision-record')).toBeVisible();
    const posts = await api.posts(APPROVALS);
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toEqual({ gate: 'specification', sha256: H2, decision: 'approve', comment: null });
    expect((posts[0].body as Record<string, unknown>).confirmation).toBeUndefined();
    const rec = page.getByTestId('decision-record');
    await expect(rec).toContainText('Approved');
    await expect(rec).toContainText('dev');
    await expect(rec).toContainText('dashboard');
    await expect(rec).toContainText('2026-11-14 09:30:00 UTC');
    await expect(page.getByTestId('decision-panel')).toHaveCount(0);
  });

  test('AC-SPA-06i one-click approve sends no confirmation and the right sha', async ({ page, api }) => {
    await open(page, SPEC_URL);
    const mark = await api.mark();
    await page.getByRole('button', { name: 'Approve version 2' }).click();
    await expect(page.getByTestId('decision-record')).toBeVisible();
    const during = await api.since(mark);
    const post = during.find((r) => r.method === 'POST');
    expect(post).toBeDefined();
    expect(post!.body).toMatchObject({ gate: 'specification', sha256: H2, decision: 'approve' });
    expect((post!.body as Record<string, unknown>).confirmation).toBeUndefined();
  });

  test('AC-SPA-05f requesting changes requires text and sends decision changes with comment', async ({ page, api }) => {
    await open(page, SPEC_URL);
    await page.getByRole('button', { name: 'Request changes' }).click();
    const textarea = page.getByLabel('What needs to change');
    await expect(textarea).toBeFocused();
    await expect(textarea).toHaveAttribute('placeholder', 'Add a scenario for inactive parent departments');
    await expect(page.getByText('The specifier gets this text and writes a new version.')).toBeVisible();
    const sendBtn = page.getByRole('button', { name: 'Send back to the agent' });
    await expect(sendBtn).toBeDisabled();
    await textarea.fill('   ');
    await expect(sendBtn).toBeDisabled();
    await textarea.fill('Add the carry-over rule');
    await expect(sendBtn).toBeEnabled();
    await sendBtn.click();
    await expect(page.getByTestId('decision-record')).toBeVisible();
    const posts = await api.posts(APPROVALS);
    expect(posts[0].body).toEqual({ gate: 'specification', sha256: H2, decision: 'changes', comment: 'Add the carry-over rule' });
    expect((posts[0].body as Record<string, unknown>).confirmation).toBeUndefined();
    await expect(page.getByTestId('decision-record')).toContainText('Changes requested');
    await expect(page.getByTestId('run-state')).toContainText('SPECIFICATION_DRAFT');
  });

  test('cancelling request changes returns focus to Request changes button', async ({ page }) => {
    await open(page, SPEC_URL);
    const reqBtn = page.getByRole('button', { name: 'Request changes' });
    await reqBtn.click();
    await expect(page.getByLabel('What needs to change')).toBeFocused();
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(reqBtn).toBeFocused();
  });

  test('AC-SPA-05h reject needs reason and confirm', async ({ page, api }) => {
    await open(page, SPEC_URL);
    const rejectBtn = page.getByRole('button', { name: 'Reject run…' });
    await rejectBtn.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('Rejecting cancels run leave-balance. This cannot be undone.');
    const confirmBtn = dialog.getByRole('button', { name: 'Reject run' });
    await expect(confirmBtn).toBeDisabled();
    await dialog.getByLabel('Reason').fill('Not needed');
    await expect(confirmBtn).toBeEnabled();
    expect(await api.posts(APPROVALS)).toHaveLength(0);
    await confirmBtn.click();
    await expect(page.getByTestId('decision-record')).toBeVisible();
    const posts = await api.posts(APPROVALS);
    expect(posts[0].body).toMatchObject({ gate: 'specification', sha256: H2, decision: 'reject', comment: 'Not needed' });
    expect((posts[0].body as Record<string, unknown>).confirmation).toBeUndefined();
  });
});

test.describe('stale and changed versions', () => {
  test('AC-SPA-08h a stale hash is shown, never retried with the new hash', async ({ page, api }) => {
    await api.rule({ method: 'POST', path: '/api/v1/tasks/leave-balance/approvals', status: 409, body: { error: { code: 'E_APPROVAL_STALE', message: 'stale', details: { current_sha256: H3 } } } });
    await open(page, SPEC_URL);
    await page.getByRole('button', { name: 'Approve version 2' }).click();
    await expect(page.getByText('A newer version is in review. Nothing was approved.')).toBeVisible();
    await api.preset('spec-v3');
    await page.getByRole('button', { name: 'Load the version in review' }).click();
    await expect(page.getByTestId('review-version')).toHaveText('Version 3');
    await expect(page.getByRole('button', { name: 'Approve version 3' })).toBeVisible();
    const posts = await api.posts(APPROVALS);
    expect(posts).toHaveLength(1);
    expect(JSON.stringify(posts)).not.toContain(H3);
  });

  test('AC-SPA-08i a new version arrives while the reviewer reads', async ({ page, api }) => {
    await open(page, SPEC_URL);
    await expect(page.getByTestId('review-version')).toHaveText('Version 2');
    await api.preset('spec-v3');
    await api.event('approval.state_changed', { id: 99, type: 'approval.state_changed', at: '2026-11-14T09:40:00Z', project: 'digital-hr', run: 'leave-balance', task: null, actor: { kind: 'engine', name: 'engine', channel: 'engine' }, payload: { gate: 'specification', version: 3 } });
    await expect(page.getByText('Version 3 replaced the version you are reading')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Approve version 2' })).toBeDisabled();
    await page.getByRole('button', { name: 'Load the version in review' }).click();
    await expect(page.getByRole('button', { name: 'Approve version 3' })).toBeEnabled();
  });

  test('AC-SPA-06j someone else decided first', async ({ page, api }) => {
    await api.rule({ method: 'POST', path: '/api/v1/tasks/leave-balance/approvals', status: 409, body: { error: { code: 'E_TRANSITION', message: 'approval already decided', details: {} } } });
    await open(page, SPEC_URL);
    await expect(page.getByTestId('review-version')).toBeVisible();
    await api.set([...RUN('leave-balance'), 'specification', 'current', 'state'], 'APPROVED');
    await page.getByRole('button', { name: 'Approve version 2' }).click();
    await expect(page.getByText('Refused: the run moved on.')).toBeVisible();
    await expect(page.getByTestId('approval-state')).toContainText('Approved');
    await expect(page.getByText('Specification approved')).toHaveCount(0);
  });

  test('AC-SPA-06k the server could not store the decision', async ({ page, api }) => {
    await api.rule({ method: 'POST', path: '/api/v1/tasks/leave-balance/approvals', status: 500, body: { error: { code: 'E_INTERNAL', message: 'internal error', details: {} } } });
    await open(page, SPEC_URL);
    await page.getByRole('button', { name: 'Approve version 2' }).click();
    await expect(page.getByText('Not confirmed: server error. See the terminal running sentinel dashboard.')).toBeVisible();
    await expect(page.getByTestId('approval-state')).toContainText('In review');
    await expect(page.getByRole('button', { name: 'Approve version 2' })).toBeEnabled();
  });

  test('AC-SPA-06l two tabs decide the same approval', async ({ page, api, context }) => {
    const second = await context.newPage();
    await open(page, SPEC_URL);
    await open(second, SPEC_URL);
    await expect(second.getByTestId('review-version')).toBeVisible();
    await page.getByRole('button', { name: 'Approve version 2' }).click();
    await expect(page.getByTestId('decision-record')).toContainText('Approved');
    await second.getByRole('button', { name: 'Approve version 2' }).click();
    await expect(second.getByText('Refused: the run moved on.')).toBeVisible();
    await expect(second.getByTestId('approval-state')).toContainText('Approved');
    expect((await api.posts(APPROVALS)).length).toBe(2);
  });
});

test('AC-SPA-05i reading, navigating and reconnecting send no decision', async ({ page, api }) => {
  await api.preset('gherkin-review');
  const hrefs = new Set<string>();
  for (const url of [SPEC_URL, GHERKIN_URL]) {
    await open(page, url);
    await expect(page.getByTestId('review-version')).toBeVisible();
    for (const h of await page.getByRole('main').getByRole('link').evaluateAll((els) => els.map((e) => e.getAttribute('href') ?? ''))) if (h.startsWith('#/')) hrefs.add(h);
  }
  for (const h of hrefs) {
    await page.goto(`/${h}`);
    await settle(page);
  }
  for (const url of [SPEC_URL, GHERKIN_URL]) {
    await open(page, url);
    await page.reload();
  }
  await api.stream('drop');
  await api.idle(1000);
  expect(await api.posts(APPROVALS)).toEqual([]);
});
