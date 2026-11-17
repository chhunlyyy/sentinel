import type { ApiError } from '../api/errors.ts';

export interface ResourceState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  /** increments after each answer, so views can tell a refetch from a rerender */
  version: number;
}

export interface Resource<T> {
  get(): ResourceState<T>;
  subscribe(cb: () => void): () => void;
  /** fetch now */
  load(): Promise<void>;
  /** ask for a refetch; bursts are coalesced */
  invalidate(): void;
  dispose(): void;
}

export interface ResourceOptions {
  /** quiet time before a coalesced refetch starts */
  delayMs?: number;
  /** a continuous burst never delays the refetch longer than this */
  maxWaitMs?: number;
}

/**
 * Holds the last REST answer of one view. An event only calls invalidate(); the state it holds
 * is always what the fetcher returned, never a value taken from an event payload.
 */
export function createResource<T>(fetcher: (signal: AbortSignal) => Promise<T>, options: ResourceOptions = {}): Resource<T> {
  const delayMs = options.delayMs ?? 300;
  const maxWaitMs = options.maxWaitMs ?? 800;
  let state: ResourceState<T> = { data: null, error: null, loading: false, version: 0 };
  const listeners = new Set<() => void>();
  let seq = 0;
  let controller: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let maxTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  const set = (next: ResourceState<T>) => {
    state = next;
    for (const l of Array.from(listeners)) l();
  };

  async function load(): Promise<void> {
    if (disposed) return;
    clearTimers();
    controller?.abort();
    controller = new AbortController();
    const mine = ++seq;
    set({ ...state, loading: true });
    try {
      const data = await fetcher(controller.signal);
      if (mine !== seq || disposed) return;
      set({ data, error: null, loading: false, version: state.version + 1 });
    } catch (e) {
      if (mine !== seq || disposed) return;
      set({ ...state, error: e as ApiError, loading: false, version: state.version + 1 });
    }
  }

  function clearTimers() {
    if (timer) clearTimeout(timer);
    if (maxTimer) clearTimeout(maxTimer);
    timer = null;
    maxTimer = null;
  }

  function invalidate() {
    if (disposed) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => void load(), delayMs);
    if (!maxTimer) maxTimer = setTimeout(() => void load(), maxWaitMs);
  }

  return {
    get: () => state,
    subscribe(cb) {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    load,
    invalidate,
    dispose() {
      disposed = true;
      clearTimers();
      controller?.abort();
      listeners.clear();
    },
  };
}
