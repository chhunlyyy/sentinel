import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { createResource } from '../../src/state/resource.ts';
import { createEventClient } from '../../src/events/client.ts';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('AC-DSH-05f state is taken from REST answers, never from event payloads', () => {
  test('AC-DSH-05f the store holds VERIFYING, never COMPLETED', async () => {
    const answers = [{ state: 'EXECUTING' }, { state: 'VERIFYING' }];
    const fetcher = vi.fn(async () => answers.shift()!);
    const store = createResource<{ state: string }>(fetcher, { delayMs: 50, maxWaitMs: 200 });
    const seen: string[] = [];
    store.subscribe(() => {
      const s = store.get().data?.state;
      if (s) seen.push(s);
    });
    await store.load();
    expect(store.get().data?.state).toBe('EXECUTING');
    const events = createEventClient({ onEvent: () => store.invalidate(), onResync: () => store.invalidate() });
    events.handleMessage({ event: 'run.state_changed', data: JSON.stringify({ project: 'digital-hr', run: 'leave-balance', payload: { state: 'COMPLETED' } }) });
    await vi.advanceTimersByTimeAsync(300);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(store.get().data?.state).toBe('VERIFYING');
    expect(seen).not.toContain('COMPLETED');
  });
});

describe('AC-DSH-05j unusable stream messages are ignored', () => {
  const rows: [string, string][] = [
    ['task.state_changed', 'not json'],
    ['task.state_changed', '{"project": null}'],
    ['something.new', '{"project": "digital-hr"}'],
  ];
  test.each(rows)('AC-DSH-05j %s %s', (event, data) => {
    const onEvent = vi.fn();
    const onResync = vi.fn();
    const client = createEventClient({ onEvent, onResync });
    expect(() => client.handleMessage({ event, data })).not.toThrow();
    expect(onEvent).not.toHaveBeenCalled();
    expect(onResync).not.toHaveBeenCalled();
    expect(client.ignoredCount()).toBe(1);
  });
});
