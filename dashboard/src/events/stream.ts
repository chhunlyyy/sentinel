import type { SessionState } from '../api/client.ts';
import { parseApiError } from '../api/errors.ts';
import { buildPath } from '../api/routes.ts';
import type { EventClient, RawMessage } from './client.ts';

export type ConnectionStatus = 'connecting' | 'connected' | 'lost';

export interface StreamOptions {
  client: EventClient;
  session: SessionState;
  onStatus: (s: ConnectionStatus) => void;
  /** called after a lost connection came back */
  onReconnect: () => void;
  fetchImpl?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
}

/** Server-sent events over fetch, so Last-Event-ID and the 401 answer are under our control. */
export function startStream(opts: StreamOptions): () => void {
  const fetchImpl = opts.fetchImpl ?? ((...a: Parameters<typeof fetch>) => fetch(...a));
  const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  let stopped = false;
  let lastId = '';
  let lost = false;
  let controller: AbortController | null = null;

  async function connectOnce(): Promise<void> {
    controller = new AbortController();
    const headers: Record<string, string> = { Accept: 'text/event-stream' };
    if (lastId) headers['Last-Event-ID'] = lastId;
    const res = await fetchImpl(buildPath('events'), { headers, signal: controller.signal, credentials: 'same-origin', cache: 'no-store' });
    if (res.status === 401) {
      const err = parseApiError(res.status, res.headers.get('content-type'), await res.text().catch(() => ''));
      if (err.code === 'E_AUTH') {
        opts.session.end();
        stopped = true;
      }
      throw new Error('unauthorized');
    }
    if (!res.ok || !(res.headers.get('content-type') ?? '').includes('text/event-stream') || !res.body) throw new Error(`stream refused (${res.status})`);
    opts.onStatus('connected');
    if (lost) {
      lost = false;
      opts.onReconnect();
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let event = '';
    let id = '';
    let data: string[] = [];
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buffer.search(/\r\n|\n|\r/)) >= 0) {
        const line = buffer.slice(0, nl);
        buffer = buffer.slice(nl + (buffer.startsWith('\r\n', nl) ? 2 : 1));
        if (line === '') {
          if (data.length) {
            if (id) lastId = id;
            const msg: RawMessage = { event: event || 'message', data: data.join('\n'), id };
            opts.client.handleMessage(msg);
          }
          event = '';
          id = '';
          data = [];
        } else if (line.startsWith(':')) {
          // heartbeat comment
        } else {
          const colon = line.indexOf(':');
          const field = colon < 0 ? line : line.slice(0, colon);
          const val = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '');
          if (field === 'event') event = val;
          else if (field === 'data') data.push(val);
          else if (field === 'id') id = val;
        }
      }
    }
  }

  async function loop() {
    let attempt = 0;
    while (!stopped) {
      try {
        await connectOnce();
        attempt = 0;
      } catch {
        // fall through to reconnect
      }
      if (stopped) break;
      lost = true;
      opts.onStatus('lost');
      await sleep(Math.min(500 * 2 ** attempt, 2000));
      attempt += 1;
    }
  }
  void loop();
  return () => {
    stopped = true;
    controller?.abort();
  };
}
