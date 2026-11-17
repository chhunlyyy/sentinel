import { describe, expect, test, vi } from 'vitest';
import { createClient } from '../../src/api/client.ts';

describe('AC-DSH-04d the API client never repeats a mutating call by itself', () => {
  test('AC-DSH-04d one POST is sent once, a GET is repeated at most twice after >= 1 s', async () => {
    const fetchImpl = vi.fn((...args: [string, RequestInit?]) => Promise.reject(new TypeError(`network error ${args.length}`)));
    const delays: number[] = [];
    const client = createClient({
      fetchImpl: fetchImpl as unknown as typeof fetch,
      sleep: async (ms: number) => {
        delays.push(ms);
      },
    });
    await expect(client.post('/projects/digital-hr/tasks', { slug: 'a' })).rejects.toBeDefined();
    const postCalls = fetchImpl.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST');
    // the CSRF read is a GET and may be repeated; the POST itself must be sent at most once
    expect(postCalls.length).toBeLessThanOrEqual(1);
    fetchImpl.mockClear();
    delays.length = 0;
    await expect(client.get('/projects')).rejects.toBeDefined();
    expect(fetchImpl.mock.calls.length).toBeLessThanOrEqual(3);
    expect(delays.length).toBeGreaterThan(0);
    for (const d of delays) expect(d).toBeGreaterThanOrEqual(1000);
  });

  test('AC-DSH-04d fetch was called exactly once for the POST when the CSRF value is known', async () => {
    const calls: { url: string; method: string }[] = [];
    const fetchImpl = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? 'GET' });
      if (url.endsWith('/session')) {
        return Promise.resolve(new Response(JSON.stringify({ csrf: 'c'.repeat(64) }), { status: 200, headers: { 'content-type': 'application/json' } }));
      }
      return Promise.reject(new TypeError('network error'));
    });
    const client = createClient({ fetchImpl: fetchImpl as unknown as typeof fetch, sleep: async () => {} });
    await expect(client.post('/tasks/x/control', { action: 'cancel' })).rejects.toBeDefined();
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
    expect(calls.filter((c) => c.url.endsWith('/session'))).toHaveLength(1);
  });
});
