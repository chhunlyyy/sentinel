import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdtempSync, readdirSync, readFileSync, statSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test, expect } from '@playwright/test';

const root = new URL('..', import.meta.url).pathname;
const dist = join(root, '..', 'sentinel', 'dashboard_dist');

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

interface Manifest {
  source_sha256: string;
  files: Record<string, string>;
}

test.describe('build into dist (pure frontend part of the wheel build)', () => {
  test('AC-OPS-01a the release build puts the assets into the output folder', async () => {
    expect(existsSync(join(dist, 'index.html'))).toBe(true);
    const files = walk(dist);
    const rel = files.map((f) => f.slice(dist.length + 1));
    expect(rel.some((f) => /^assets\/.+-[A-Za-z0-9_-]{6,}\.js$/.test(f))).toBe(true);
    expect(rel.some((f) => /^assets\/.+-[A-Za-z0-9_-]{6,}\.css$/.test(f))).toBe(true);
    expect(rel).toContain('manifest.json');
    const manifest = JSON.parse(readFileSync(join(dist, 'manifest.json'), 'utf8')) as Manifest;
    expect(manifest.source_sha256).toMatch(/^[0-9a-f]{64}$/);
    for (const f of rel.filter((f) => f !== 'manifest.json')) {
      expect(manifest.files[f], f).toBe(createHash('sha256').update(readFileSync(join(dist, f))).digest('hex'));
    }
    expect(Object.keys(manifest.files).sort()).toEqual(rel.filter((f) => f !== 'manifest.json').sort());
    let total = 0;
    for (const f of files) {
      const size = statSync(f).size;
      expect(size, f).toBeLessThan(2 * 1024 * 1024);
      total += size;
      expect(f.endsWith('.map')).toBe(false);
    }
    expect(total).toBeLessThan(5 * 1024 * 1024);
  });

  test('AC-OPS-01d the build is reproducible from the lockfile', async () => {
    test.setTimeout(180_000);
    const manifests: string[] = [];
    for (let i = 0; i < 2; i++) {
      const dir = mkdtempSync(join(tmpdir(), `dash-build-${i}-`));
      for (const entry of ['src', 'index.html', 'package.json', 'package-lock.json', 'tsconfig.json', 'vite.config.ts', 'vitest.config.ts', 'eslint.config.js']) cpSync(join(root, entry), join(dir, entry), { recursive: true });
      symlinkSync(join(root, 'node_modules'), join(dir, 'node_modules'));
      const r = spawnSync('npx', ['vite', 'build'], { cwd: dir, encoding: 'utf8', env: { ...process.env, DASHBOARD_OUT_DIR: 'dist' } });
      expect(r.status, r.stderr + r.stdout).toBe(0);
      manifests.push(readFileSync(join(dir, 'dist', 'manifest.json'), 'utf8'));
    }
    expect(manifests[0]).toBe(manifests[1]);
  });

  test('AC-DSH-06f the built bundle names no remote resource', async () => {
    const offenders: string[] = [];
    for (const f of walk(dist)) {
      const text = readFileSync(f, 'utf8');
      for (const m of text.matchAll(/(?:https?:)?\/\/[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s"'`)<>]*/g)) {
        if (/^(?:https?:)?\/\/www\.w3\.org\/(?:1999\/xhtml|1998\/Math\/MathML|2000\/svg|1999\/xlink|XML\/1998\/namespace|2000\/xmlns\/)/.test(m[0])) continue;
        offenders.push(`${f.slice(dist.length + 1)}: ${m[0]}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

test.describe('network off', () => {
  test('AC-DSH-06g the dashboard tests run with the network off', async () => {
    test.setTimeout(300_000);
    test.skip(process.env.SENTINEL_NO_NET_CHILD === '1', 'already inside the network namespace');
    const probe = spawnSync('unshare', ['-rn', 'true']);
    test.skip(probe.status !== 0, `unshare -rn is not permitted in this environment (${String(probe.stderr).trim()}); needs user namespaces or root`);
    // The wheel environment needs pip and the network, so build it here, outside the namespace, and hand it in.
    let wheelEnv = process.env.SENTINEL_WHEEL_ENV;
    if (!wheelEnv || !existsSync(join(wheelEnv, 'ready.json'))) {
      wheelEnv = wheelEnv ?? mkdtempSync(join(tmpdir(), 'sentinel-wheel-env-ns-'));
      const b = spawnSync('python3', [join(root, '..', 'tools', 'release_gate.py'), 'wheel-env', wheelEnv], { encoding: 'utf8' });
      expect(b.status, b.stdout.slice(-1500) + b.stderr.slice(-1500)).toBe(0);
    }
    const r = spawnSync('unshare', ['-rn', 'sh', '-c', 'ip link set lo up 2>/dev/null; npm test && SENTINEL_NO_NET_CHILD=1 npx playwright test --grep-invert AC-DSH-06g'],
      { cwd: root, encoding: 'utf8', env: { ...process.env, SENTINEL_WHEEL_ENV: wheelEnv } });
    expect(r.status, r.stdout.slice(-2000) + r.stderr.slice(-2000)).toBe(0);
  });
});
