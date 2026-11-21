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
  test('AC-DSH-06j route table has only /api/v1 entries; changes go through POST, PUT or DELETE on known resources', () => {
    for (const r of Object.values(ROUTES)) {
      expect(['GET', 'POST', 'PUT', 'DELETE']).toContain(r.method);
      expect(r.pattern.startsWith('/api/v1/')).toBe(true);
      if (r.method !== 'GET') expect(r.pattern).toMatch(/\/(approvals|acceptance|control|tasks|read|test|orchestrator|agents|projects|\{pid\}|register|repositories|repositories\/\{rid\}|pause|unpause|note|detect|preview|save|ingest|snapshot|estimate|backfill)$/);
    }
  });
  test('AC-DSH-06j screens call the API only through the route table', () => {
    const src = join(process.cwd(), 'src');
    const offenders = walk(src)
      .filter((f) => /\.(ts|tsx)$/.test(f) && !f.endsWith('routes.ts'))
      .filter((f) => /['"`]\/api\/v1/.test(readFileSync(f, 'utf8')) && !f.endsWith('client.ts') && !f.endsWith('stream.ts'));
    expect(offenders).toEqual([]);
  });
  test('deleteProject is DELETE on the project resource and builds the path', async () => {
    const { buildPath } = await import('../../src/api/routes.ts');
    expect(ROUTES.deleteProject.method).toBe('DELETE');
    expect(buildPath('deleteProject', { pid: 'a b' })).toBe('/api/v1/projects/a%20b');
  });
});
