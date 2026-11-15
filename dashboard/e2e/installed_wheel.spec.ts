import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { test, expect, type Page } from '@playwright/test';

// The installed wheel (built with SENTINEL_RELEASE=1, installed offline into a fresh virtual environment, no node on
// the PATH of the server) serves the dashboard: AC-OPS-01b, AC-DSH-06h. SENTINEL_WHEEL_ENV names a folder made by
// `python3 tools/release_gate.py wheel-env DIR`; without it the test makes one.
const repo = resolve(import.meta.dirname, '..', '..');
let server: ChildProcess | null = null;
let info: { url: string; port: number; project: string } | null = null;

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  test.setTimeout(600_000);
  let envDir = process.env.SENTINEL_WHEEL_ENV;
  if (!envDir || !existsSync(join(envDir, 'ready.json'))) {
    envDir = envDir ?? mkdtempSync(join(tmpdir(), 'sentinel-wheel-env-pw-'));
    const r = spawnSync('python3', [join(repo, 'tools', 'release_gate.py'), 'wheel-env', envDir], { encoding: 'utf8' });
    if (r.status !== 0) throw new Error(`could not build the wheel environment: ${r.stdout}${r.stderr}`);
  }
  server = spawn('python3', [join(repo, 'tools', 'serve_installed.py'), envDir], { stdio: ['pipe', 'pipe', 'inherit'] });
  info = await new Promise((res, rej) => {
    let buf = '';
    server?.stdout?.on('data', (d: Buffer) => {
      buf += d.toString();
      const line = buf.split('\n')[0];
      if (buf.includes('\n')) {
        const parsed = JSON.parse(line) as { url?: string; error?: string };
        if (parsed.url) res(parsed as { url: string; port: number; project: string });
        else rej(new Error(parsed.error));
      }
    });
    server?.once('exit', () => rej(new Error('the server helper exited')));
  });
});

test.afterAll(() => {
  server?.stdin?.end();
  server?.kill('SIGTERM');
});

async function signIn(page: Page) {
  await page.goto(info!.url);
  await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible();
}

test('AC-OPS-01b the installed wheel serves the dashboard and the overview shows data of the real server', async ({ page }) => {
  await signIn(page);
  const html = await (await page.request.get(`http://127.0.0.1:${info!.port}/`)).text();
  expect(html).toContain('<div id="root">');
  await expect(page.getByRole('main')).toContainText('demo-ws');
  const assets = [...(await page.content()).matchAll(/(?:src|href)="\.\/(assets\/[^"]+)"/g)].map((m) => m[1]);
  expect(assets.length).toBeGreaterThanOrEqual(2);
  for (const a of assets) expect((await page.request.get(`http://127.0.0.1:${info!.port}/${a}`)).status()).toBe(200);
  await page.goto(`http://127.0.0.1:${info!.port}/#/projects/${info!.project}/runs/demo-run`);
  await expect(page.getByRole('main')).toContainText('demo-run');
});

test('AC-DSH-06h a session with the network cable out: every screen renders and nothing leaves the machine', async ({ page }) => {
  const outside: string[] = [];
  const failed: string[] = [];
  await page.route('**/*', (route) => {
    const u = new URL(route.request().url());
    if (u.hostname !== '127.0.0.1') {
      outside.push(route.request().url());
      return route.abort();
    }
    return route.continue();
  });
  page.on('requestfailed', (r) => failed.push(`${r.url()} ${r.failure()?.errorText ?? ''}`));
  await signIn(page);
  const p = info!.project;
  const screens = [
    '/', '/projects', `/projects/${p}`, '/tasks', '/tasks/new', '/approvals', '/runs', '/quality', '/reports', '/settings/installation',
    '/settings/health', `/projects/${p}/configuration`, `/projects/${p}/audit`, `/projects/${p}/runs/demo-run`,
  ];
  for (const route of screens) {
    await page.goto(`http://127.0.0.1:${info!.port}/#${route}`);
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 }).first()).not.toBeEmpty();
    await expect(page.locator('main')).not.toContainText('Session ended');
  }
  expect(outside).toEqual([]);
  expect(failed.filter((f) => !/favicon/.test(f))).toEqual([]);
});
