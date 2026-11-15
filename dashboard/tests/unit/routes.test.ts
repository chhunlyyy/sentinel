import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, test } from 'vitest';
import { ROUTES } from '../../src/api/routes.ts';

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

describe('AC-DSH-06j every route the app calls is listed in the shared route table', () => {
  test('AC-DSH-06j route table has only /api/v1 GET and POST entries and no mutating route for projects, repos or configuration', () => {
    for (const r of Object.values(ROUTES)) {
      expect(['GET', 'POST']).toContain(r.method);
      expect(r.pattern.startsWith('/api/v1/')).toBe(true);
      if (r.method === 'POST') expect(r.pattern).toMatch(/\/(approvals|acceptance|control|tasks|read)$/);
    }
  });
  test('AC-DSH-06j screens call the API only through the route table', () => {
    const src = join(process.cwd(), 'src');
    const offenders = walk(src)
      .filter((f) => /\.(ts|tsx)$/.test(f) && !f.endsWith('routes.ts'))
      .filter((f) => /['"`]\/api\/v1/.test(readFileSync(f, 'utf8')) && !f.endsWith('client.ts') && !f.endsWith('stream.ts'));
    expect(offenders).toEqual([]);
  });
});
