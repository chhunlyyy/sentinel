import { ApiError, networkError, parseApiError } from './errors.ts';
import { buildPath } from './routes.ts';
import type { SessionAnswer } from './types.ts';

export interface ClientOptions {
  fetchImpl?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
  timeoutMs?: number;
  /** shared session state; the event stream ends the session through the same object */
  session?: SessionState;
}

export interface SessionState {
  isEnded(): boolean;
  end(): void;
}

export function createSessionState(onChange?: () => void): SessionState {
  let ended = false;
  return {
    isEnded: () => ended,
    end() {
      if (!ended) {
        ended = true;
        onChange?.();
      }
    },
  };
}

export interface Client {
  get<T>(path: string, opts?: { signal?: AbortSignal }): Promise<T>;
  post<T>(path: string, body: unknown): Promise<T>;
  put<T>(path: string, body: unknown): Promise<T>;
  del<T>(path: string): Promise<T>;
  sessionEnded(): boolean;
  /** forget the CSRF value so the next POST reads it again */
  renewCsrf(): Promise<void>;
}

const REPEAT_GET_DELAY_MS = 1000;
const MAX_GET_REPEATS = 2;

/**
 * The only place that talks to fetch. A mutating call is sent at most once, never repeated by
 * the client. A GET may be repeated twice after a network failure, never faster than 1 s apart.
 */
export function createClient(options: ClientOptions = {}): Client {
  const fetchImpl = options.fetchImpl ?? ((...a: Parameters<typeof fetch>) => fetch(...a));
  const sleep = options.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const timeoutMs = options.timeoutMs ?? 30_000;
  const session = options.session ?? createSessionState();
  let csrf: string | null = null;
  const endSession = () => session.end();

  async function once(path: string, init: RequestInit): Promise<Response> {
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(), timeoutMs);
    // the caller's signal (view left, newer request) and the time limit both end the request
    const signal = init.signal ? AbortSignal.any([init.signal, timeout.signal]) : timeout.signal;
    try {
      return await fetchImpl(path, { ...init, signal, credentials: 'same-origin', cache: 'no-store' });
    } catch {
      throw networkError();
    } finally {
      clearTimeout(timer);
    }
  }

  async function read<T>(res: Response): Promise<T> {
    if (!res.ok) {
      const err = parseApiError(res.status, res.headers.get('content-type'), await res.text().catch(() => ''));
      if (res.status === 401 && err.code === 'E_AUTH') endSession();
      throw err;
    }
    try {
      return (await res.json()) as T;
    } catch {
      throw parseApiError(res.status, 'text/plain', '');
    }
  }

  async function get<T>(path: string, opts: { signal?: AbortSignal } = {}): Promise<T> {
    if (session.isEnded()) throw new ApiError({ status: 401, code: 'E_AUTH', message: 'session ended', text: 'Session ended' });
    let attempt = 0;
    for (;;) {
      try {
        const res = await once(path, { method: 'GET', headers: { Accept: 'application/json' }, signal: opts.signal });
        return await read<T>(res);
      } catch (e) {
        if (!(e instanceof ApiError) || !e.network || attempt >= MAX_GET_REPEATS) throw e;
        attempt += 1;
        await sleep(REPEAT_GET_DELAY_MS);
        if (session.isEnded()) throw e;
      }
    }
  }

  async function ensureCsrf(): Promise<string> {
    if (csrf) return csrf;
    const answer = await get<SessionAnswer>(buildPath('session'));
    csrf = answer.csrf;
    return csrf;
  }

  async function send<T>(method: 'POST' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
    if (session.isEnded()) throw new ApiError({ status: 401, code: 'E_AUTH', message: 'session ended', text: 'Session ended' });
    const token = await ensureCsrf();
    const res = await once(path, {
      method,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-Sentinel-CSRF': token },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 403) {
      const err = parseApiError(res.status, res.headers.get('content-type'), await res.clone().text().catch(() => ''));
      if (err.code === 'E_CSRF') {
        csrf = null;
        await ensureCsrf().catch(() => undefined);
      }
    }
    return read<T>(res);
  }

  const post = <T,>(path: string, body: unknown) => send<T>('POST', path, body);
  const put = <T,>(path: string, body: unknown) => send<T>('PUT', path, body);
  const del = <T,>(path: string) => send<T>('DELETE', path);

  return { get, post, put, del, sessionEnded: () => session.isEnded(), async renewCsrf() { csrf = null; await ensureCsrf(); } };
}
