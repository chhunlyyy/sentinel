import { createServer } from 'node:net';
import { defineConfig } from '@playwright/test';

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.once('error', reject);
    s.listen(0, '127.0.0.1', () => {
      const { port } = s.address() as { port: number };
      s.close(() => resolve(port));
    });
  });
}

// A free port, chosen once: the workers started by Playwright read the same variable.
process.env.FAKE_API_PORT ??= String(await freePort());
const port = Number(process.env.FAKE_API_PORT);

export default defineConfig({
  testDir: 'e2e',
  testMatch: /.*\.spec\.ts/,
  timeout: 30_000,
  expect: { timeout: 7_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'off',
    // Distributions without a Playwright-supported glibc, or offline machines, can point at a system Chromium.
    launchOptions: process.env.SENTINEL_CHROMIUM_PATH ? { executablePath: process.env.SENTINEL_CHROMIUM_PATH } : {},
  },
  webServer: {
    command: `npm run build && node fake-api/server.ts`,
    url: `http://127.0.0.1:${port}/__control/ping`,
    env: { FAKE_API_PORT: String(port) },
    reuseExistingServer: process.env.REUSE_FAKE_API === '1',
    timeout: 120_000,
  },
});
