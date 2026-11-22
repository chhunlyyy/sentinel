import { test as base, expect, type APIRequestContext, type Locator, type Page } from '@playwright/test';

export { expect };

export const CSRF = 'c0ffee'.repeat(10) + 'c0ff';
export const SESSION = 'test-session';
export { H2, H3, G1, REPORT } from '../fixtures/constants.ts';

export interface LoggedRequest {
  n: number;
  t: number;
  method: string;
  path: string;
  search: string;
  headers: Record<string, string>;
  body: unknown;
}

export interface Rule {
  method?: string;
  /** exact path, or "re:<regex>" tested against path + search */
  path: string;
  status?: number;
  body?: unknown;
  rawBody?: string;
  contentType?: string;
  delayMs?: number;
  drop?: boolean;
  hang?: boolean;
  times?: number;
  /** apply the delay, then answer normally */
  passthrough?: boolean;
}

export class Api {
  private readonly req: APIRequestContext;
  readonly base: string;
  constructor(req: APIRequestContext, base: string) {
    this.req = req;
    this.base = base;
  }

  private async post(path: string, data: unknown = {}) {
    const res = await this.req.post(`${this.base}/__control/${path}`, { data });
    if (!res.ok()) throw new Error(`control ${path} failed: ${res.status()} ${await res.text()}`);
    return res.json();
  }
  reset(fixture = 'two-projects', presets: string[] = []) {
    return this.post('reset', { fixture, presets });
  }
  preset(name: string) {
    return this.post('preset', { name });
  }
  rule(rule: Rule) {
    return this.post('rule', rule);
  }
  /** set a value in the fake database; a path segment "id=x" selects an array element by id */
  set(path: (string | number)[], value: unknown) {
    return this.post('set', { path, value });
  }
  event(event: string, data: unknown, opts: { raw?: boolean; id?: string } = {}) {
    return this.post('event', { event, data, ...opts });
  }
  events(events: { event: string; data: unknown }[]) {
    return this.post('events', { events });
  }
  stream(action: 'drop' | 'refuse', ms = 0) {
    return this.post('stream', { action, ms });
  }
  chatFail(fail = true) {
    return this.post('chat-fail', { fail });
  }
  async requests(): Promise<LoggedRequest[]> {
    const res = await this.req.get(`${this.base}/__control/requests`);
    return res.json();
  }
  async mark(): Promise<number> {
    const all = await this.requests();
    return all.length;
  }
  async since(mark: number): Promise<LoggedRequest[]> {
    return (await this.requests()).slice(mark);
  }
  async posts(re: RegExp): Promise<LoggedRequest[]> {
    return (await this.requests()).filter((r) => r.method === 'POST' && re.test(r.path));
  }
  async gets(re: RegExp, from = 0): Promise<LoggedRequest[]> {
    return (await this.requests()).slice(from).filter((r) => r.method === 'GET' && (re.test(r.path) || re.test(r.path + r.search)));
  }
  /** Resolves when the fake has seen no new request for `quietMs`; this waits for work to finish, it does not guess a duration. */
  async idle(quietMs = 500, maxMs = 10_000): Promise<void> {
    let last = -1;
    let since = Date.now();
    const end = Date.now() + maxMs;
    for (;;) {
      const n = await this.mark();
      if (n !== last) {
        last = n;
        since = Date.now();
      } else if (Date.now() - since >= quietMs) return;
      if (Date.now() > end) throw new Error('requests did not settle');
      await new Promise((r) => setTimeout(r, 50));
    }
  }
  async serverEvents(): Promise<{ id: string; t: number }[]> {
    const res = await this.req.get(`${this.base}/__control/sent-events`);
    return res.json();
  }
}

export const RUN = (slug: string, pid = 'digital-hr') => ['runs', `${pid}/${slug}`];

export const test = base.extend<{ api: Api }>({
  api: async ({ request, baseURL, context }, use) => {
    const api = new Api(request, baseURL!);
    await api.reset();
    await context.addCookies([{ name: 'sentinel_session', value: SESSION, url: baseURL!, httpOnly: true, sameSite: 'Strict' }]);
    await use(api);
  },
  // the session cookie and a fresh fixture set are needed even by tests that never touch `api`
  page: async ({ page, api }, use) => {
    void api;
    await use(page);
  },
});

export function nav(page: Page) {
  return page.getByRole('navigation', { name: 'Main' });
}

export async function open(page: Page, hash: string) {
  await page.goto(`/#${hash}`);
}

export function heading(page: Page, name: string) {
  return page.getByRole('heading', { name, exact: true });
}

/** action helpers shared by several specs */
export async function createTask(page: Page, v: { slug: string; request?: string; type?: string; repos?: string[]; priority?: string; ticket?: string }) {
  await open(page, '/tasks/new');
  await page.getByLabel('Project').selectOption('digital-hr');
  await page.getByLabel('Slug').fill(v.slug);
  await page.getByLabel('Request').fill(v.request ?? 'Report leave per team');
  await page.getByLabel('Type').selectOption(v.type ?? 'feature');
  if (v.repos) {
    for (const r of ['backend', 'frontend']) {
      const box = page.getByRole('checkbox', { name: r, exact: true });
      if (v.repos.includes(r)) await box.check();
      else await box.uncheck();
    }
  }
  if (v.priority) await page.getByLabel('Priority').selectOption(v.priority);
  if (v.ticket) await page.getByLabel('Ticket').fill(v.ticket);
}

export async function control(page: Page, button: string, opts: { comment?: string } = {}) {
  await page.getByRole('button', { name: button, exact: true }).click();
  const dialog = page.getByRole('dialog');
  if (opts.comment !== undefined) await dialog.getByLabel('Comment').fill(opts.comment);
  const confirm = dialog.getByRole('button', { name: button.replace(/ t-[a-z0-9]+$/, ''), exact: true });
  await confirm.click();
}

export async function decide(page: Page, choice: string, prefix: string, button: string, comment?: string) {
  await page.getByRole('radio', { name: choice, exact: true }).check();
  await page.getByLabel('Type the first 8 characters of the sha256 to confirm').fill(prefix);
  if (comment !== undefined) await page.getByLabel('Comment').fill(comment);
  await page.getByRole('button', { name: button, exact: true }).click();
}

export const SPEC_URL = '/projects/digital-hr/runs/leave-balance/specification';
export const GHERKIN_URL = '/projects/digital-hr/runs/leave-balance/gherkin';

export async function focusOutlineVisible(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return true;
    const cs = getComputedStyle(el);
    const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
    const shadow = cs.boxShadow !== 'none';
    return outline || shadow;
  });
}

export async function activeName(page: Page): Promise<string> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return '';
    const aria = el.getAttribute('aria-label');
    if (aria) return aria;
    const labelled = el.getAttribute('aria-labelledby');
    if (labelled) return labelled.split(' ').map((i) => document.getElementById(i)?.textContent ?? '').join(' ');
    const labels = (el as HTMLInputElement).labels;
    if (labels && labels.length) return Array.from(labels).map((l) => l.textContent).join(' ');
    return (el.textContent ?? '').trim() || (el.getAttribute('value') ?? '');
  });
}

/** Tab until the focused element's name matches; returns every outline check made on the way */
export async function tabTo(page: Page, name: string | RegExp, limit = 80, outlines: boolean[] = []) {
  for (let i = 0; i < limit; i++) {
    await page.keyboard.press('Tab');
    outlines.push(await focusOutlineVisible(page));
    const n = await activeName(page);
    if (typeof name === 'string' ? n.trim() === name : name.test(n)) return;
  }
  throw new Error(`could not tab to ${String(name)}`);
}

export async function dialogOpen(page: Page): Promise<boolean> {
  return (await page.getByRole('dialog').count()) > 0;
}

export function stateOf(page: Page): Locator {
  return page.getByTestId('run-state');
}

/** Wait until the page has loaded and its first reads are done. (networkidle never happens: the event stream stays open.) */
export async function settle(page: Page) {
  await expect(page.getByTestId('connection-status')).toHaveText(/Connected|Session ended|Connection lost/).catch(() => undefined);
  await expect(page.getByRole('main').getByText('Loading', { exact: true })).toHaveCount(0);
}
