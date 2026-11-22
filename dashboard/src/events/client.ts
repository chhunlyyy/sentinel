import type { StreamEnvelope } from '../api/types.ts';

export interface RawMessage {
  event: string;
  data: string;
  id?: string;
}

export interface EventClientHandlers {
  onEvent: (event: StreamEnvelope) => void;
  /** project ids named by a resync message; empty means every project */
  onResync: (projects: string[], reason: string | null) => void;
}

const KNOWN = /^(factory|run|task|approval|artifact|cycle|red|green|refactor|evidence|finding|config|project|repository|publish|notification|chat)\./;

export interface EventClient {
  handleMessage(msg: RawMessage): 'handled' | 'ignored';
  ignoredCount(): number;
}

/** Validates stream messages. Anything it cannot use is counted and dropped, never thrown. */
export function createEventClient(handlers: EventClientHandlers): EventClient {
  let ignored = 0;
  const ignore = () => {
    ignored += 1;
    return 'ignored' as const;
  };
  return {
    ignoredCount: () => ignored,
    handleMessage(msg) {
      try {
        let data: unknown;
        try {
          data = JSON.parse(msg.data);
        } catch {
          return ignore();
        }
        if (!data || typeof data !== 'object' || Array.isArray(data)) return ignore();
        const obj = data as Record<string, unknown>;
        if (msg.event === 'resync') {
          const projects: string[] = [];
          if (typeof obj.project === 'string') projects.push(obj.project);
          if (Array.isArray(obj.projects)) for (const p of obj.projects) if (typeof p === 'string') projects.push(p);
          if (!projects.length) return ignore();
          handlers.onResync(projects, typeof obj.reason === 'string' ? obj.reason : null);
          return 'handled';
        }
        if (!KNOWN.test(msg.event)) return ignore();
        if (msg.event.startsWith('factory.')) {
          handlers.onEvent({
            id: typeof obj.id === 'number' ? obj.id : 0,
            type: msg.event,
            at: typeof obj.at === 'string' ? obj.at : '',
            project: typeof obj.project === 'string' ? obj.project : '',
            run: null,
            task: null,
            actor: { kind: 'engine', name: null, channel: 'engine' },
            payload: obj,
          });
          return 'handled';
        }
        if (typeof obj.project !== 'string' || !obj.project) return ignore();
        const run = typeof obj.run === 'string' ? obj.run : null;
        const task = typeof obj.task === 'string' ? obj.task : null;
        handlers.onEvent({
          id: typeof obj.id === 'number' ? obj.id : 0,
          type: msg.event,
          at: typeof obj.at === 'string' ? obj.at : '',
          project: obj.project,
          run,
          task,
          actor: { kind: 'engine', name: null, channel: 'engine' },
          payload: {},
        });
        return 'handled';
      } catch {
        return ignore();
      }
    },
  };
}
