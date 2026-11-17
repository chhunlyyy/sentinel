// Regenerates the README images from the dashboard's built-in sample data (two imaginary projects).
//   cd dashboard && npm ci && npm run build && node scripts/showcase.mjs && python3 scripts/frames_to_gif.py
// Output: docs/images/dashboard-*.png and docs/images/.frames/*.png (the input of the animated tour).
import { spawn } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const out = resolve(root, '..', 'docs', 'images');
const frames = join(out, '.frames');
mkdirSync(out, { recursive: true });
rmSync(frames, { recursive: true, force: true });
mkdirSync(frames, { recursive: true });

const port = await new Promise((res, rej) => {
  const s = createServer();
  s.once('error', rej);
  s.listen(0, '127.0.0.1', () => {
    const { port: p } = s.address();
    s.close(() => res(p));
  });
});
const base = `http://127.0.0.1:${port}`;
const server = spawn('node', ['fake-api/server.ts'], { cwd: root, env: { ...process.env, FAKE_API_PORT: String(port) }, stdio: 'inherit' });
const stop = () => server.kill('SIGTERM');
process.on('exit', stop);

async function waitUp() {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${base}/__control/ping`)).ok) return;
    } catch { /* not yet */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error('the fake API did not start (run `npm run build` first)');
}
const post = (path, body) => fetch(`${base}/__control/${path}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body ?? {}) });

await waitUp();
const browser = await chromium.launch(process.env.SENTINEL_CHROMIUM_PATH ? { executablePath: process.env.SENTINEL_CHROMIUM_PATH } : {});

async function session(scheme) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: scheme, deviceScaleFactor: 1 });
  // the fake server accepts this session (the real one hands it out at /auth?t=<token>)
  await ctx.addCookies([{ name: 'sentinel_session', value: 'test-session', url: base, httpOnly: true, sameSite: 'Strict' }]);
  return { ctx, page: await ctx.newPage() };
}

async function show(page, hash, ready) {
  await page.goto(`${base}/#${hash}`);
  await page.waitForLoadState('networkidle').catch(() => undefined);
  if (ready) await ready(page);
  await page.getByRole('main').getByText('Loading', { exact: true }).waitFor({ state: 'detached', timeout: 8000 }).catch(() => undefined);
  await page.waitForTimeout(500);
}

async function tab(page, name) {
  const t = page.getByRole('tab', { name, exact: true }).or(page.getByRole('link', { name, exact: true })).first();
  await t.click();
  await page.waitForTimeout(500);
}

let n = 0;
async function frame(page, label) {
  n += 1;
  await page.screenshot({ path: join(frames, `${String(n).padStart(2, '0')}-${label}.png`) });
}
// only the pictures the README shows are kept (keep this list in step with README.md)
const KEEP = new Set(['specification-review', 'workflow', 'tdd', 'trace', 'verification', 'approvals', 'run-dark', 'reports']);
const png = (page, name) => (KEEP.has(name) ? page.screenshot({ path: join(out, `dashboard-${name}.png`) }) : Promise.resolve());

try {
  // ---- light theme, the approval states
  await post('reset', { fixture: 'two-projects', presets: ['approvals'] });
  let { ctx, page } = await session('light');

  await show(page, '/');
  await png(page, 'overview');
  await frame(page, 'overview');

  await show(page, '/approvals');
  await png(page, 'approvals');
  await frame(page, 'approvals');

  await show(page, '/projects/digital-hr/runs/leave-balance');
  await png(page, 'run');
  await frame(page, 'run');

  await tab(page, 'Specification');
  // choose Approve and type the first 8 characters of the shown sha256, as a reviewer does (nothing is submitted)
  await page.getByRole('radio', { name: 'Approve', exact: true }).check();
  await page.getByLabel('Type the first 8 characters of the sha256 to confirm').fill('3f9a0c12');
  await page.waitForTimeout(300);
  await png(page, 'specification-review');
  await frame(page, 'specification-review');

  await ctx.close();

  // ---- light theme, a finished run
  await post('reset', { fixture: 'two-projects', presets: [] });
  ({ ctx, page } = await session('light'));

  await show(page, '/projects/digital-hr/runs/leave-balance');
  for (const [name, file] of [['Workflow', 'workflow'], ['TDD', 'tdd'], ['Verification', 'verification'], ['Trace', 'trace'], ['Acceptance', 'acceptance']]) {
    try {
      await tab(page, name);
      await png(page, file);
      await frame(page, file);
    } catch (e) {
      console.error(`skipped tab ${name}: ${e.message.split('\n')[0]}`);
    }
  }

  await show(page, '/reports');
  await png(page, 'reports');

  await show(page, '/settings/health');
  await png(page, 'readiness');

  await show(page, '/');
  const bell = page.getByRole('button', { name: /notifications/i }).first();
  if (await bell.count()) {
    await bell.click();
    await page.waitForTimeout(600);
    await png(page, 'notifications');
  }
  await ctx.close();

  // ---- terminal session (real output, made by scripts/terminal_demo.py)
  try {
    const { readFileSync } = await import('node:fs');
    const text = readFileSync(join(out, '.terminal.txt'), 'utf8');
    const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;');
    const html = text.split('\n').map((l) => {
      if (l.startsWith('$ ')) return `<span class="p">$</span> <b>${esc(l.slice(2))}</b>`;
      if (/^E_[A-Z_]+:/.test(l)) return `<span class="e">${esc(l)}</span>`;
      if (l.startsWith('#')) return `<span class="c">${esc(l)}</span>`;
      return esc(l);
    }).join('\n');
    const tp = await browser.newPage({ viewport: { width: 1100, height: 900 } });
    await tp.setContent(`<body style="margin:0;background:#0d1117;padding:28px"><div style="background:#161b22;border:1px solid #30363d;border-radius:10px;overflow:hidden;box-shadow:0 8px 30px #0008">
      <div style="background:#21262d;padding:10px 14px;display:flex;gap:8px"><i style="width:12px;height:12px;border-radius:50%;background:#ff5f57"></i><i style="width:12px;height:12px;border-radius:50%;background:#febc2e"></i><i style="width:12px;height:12px;border-radius:50%;background:#28c840"></i></div>
      <pre style="margin:0;padding:18px 22px;color:#c9d1d9;font:15px/1.55 'DejaVu Sans Mono',Menlo,monospace;white-space:pre-wrap">${html}</pre></div>
      <style>.p{color:#3fb950}b{color:#f0f6fc}.e{color:#ff7b72}.c{color:#8b949e}</style></body>`);
    const box = await tp.locator('body > div').boundingBox();
    await tp.screenshot({ path: join(out, 'terminal-session.png'), clip: { x: 0, y: 0, width: 1100, height: Math.ceil(box.y + box.height + 28) } });
    await tp.close();
  } catch (e) {
    console.error(`no terminal image: ${e.message.split('\n')[0]}`);
  }

  // ---- dark theme
  ({ ctx, page } = await session('dark'));
  await show(page, '/projects/digital-hr/runs/leave-balance');
  await png(page, 'run-dark');
  await tab(page, 'Workflow').catch(() => undefined);
  await png(page, 'workflow-dark');
  await ctx.close();
} finally {
  await browser.close();
  stop();
}
console.log(`images in ${out}`);
