import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import { createClient, createSessionState, type Client, type SessionState } from '../api/client.ts';
import type { ApiError } from '../api/errors.ts';
import { createEventClient } from '../events/client.ts';
import { startStream, type ConnectionStatus } from '../events/stream.ts';
import type { StreamEnvelope } from '../api/types.ts';
import { createResource, type Resource, type ResourceState } from './resource.ts';

/** Which events and resync messages make a view refetch. */
export interface Scope {
  project?: string;
  run?: string;
  /** only events of these types refetch the view (resync messages and reconnects always do); every type when absent */
  types?: readonly string[];
  /** false: a resync message does not refetch the view (reconnects still do) */
  resync?: boolean;
}

interface Registration {
  resource: Resource<unknown>;
  scope: Scope;
}

export interface Hub {
  register(resource: Resource<unknown>, scope: Scope): () => void;
  dispatch(ev: StreamEnvelope): void;
  resync(projects: string[]): void;
  refetchAll(): void;
}

export function createHub(): Hub {
  const regs = new Set<Registration>();
  return {
    register(resource, scope) {
      const r = { resource, scope };
      regs.add(r);
      return () => regs.delete(r);
    },
    dispatch(ev) {
      for (const { resource, scope } of regs) {
        if (scope.types && !scope.types.includes(ev.type)) continue;
        if (scope.run) {
          if (ev.project === scope.project && ev.run === scope.run) resource.invalidate();
        } else if (scope.project) {
          if (ev.project === scope.project) resource.invalidate();
        } else resource.invalidate();
      }
    },
    resync(projects) {
      for (const { resource, scope } of regs) if (scope.resync !== false && (!scope.project || projects.includes(scope.project))) resource.invalidate();
    },
    refetchAll() {
      for (const { resource } of regs) resource.invalidate();
    },
  };
}

export interface App {
  client: Client;
  session: SessionState;
  hub: Hub;
  status: ConnectionStatus;
  sessionEnded: boolean;
  announce: (text: string) => void;
  announcement: string;
}

const AppContext = createContext<App | null>(null);

export function useApp(): App {
  const app = useContext(AppContext);
  if (!app) throw new Error('AppProvider missing');
  return app;
}

export function AppProvider({ children, stream = true }: { children: ReactNode; stream?: boolean }) {
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const [ended, setEnded] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const hub = useMemo(() => createHub(), []);
  const session = useMemo(() => createSessionState(() => setEnded(true)), []);
  const client = useMemo(() => createClient({ session }), [session]);

  useEffect(() => {
    if (!stream) return undefined;
    const events = createEventClient({
      onEvent: (ev) => hub.dispatch(ev),
      onResync: (projects) => hub.resync(projects),
    });
    return startStream({ client: events, session, onStatus: setStatus, onReconnect: () => hub.refetchAll() });
  }, [stream, hub, session]);

  const announce = useCallback((text: string) => {
    // a changed text is announced; repeat the same text by toggling a trailing zero-width character
    setAnnouncement((prev) => (prev === text ? text + String.fromCharCode(0x200b) : text));
  }, []);

  const value = useMemo<App>(() => ({ client, session, hub, status, sessionEnded: ended, announce, announcement }), [client, session, hub, status, ended, announce, announcement]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

const EMPTY: ResourceState<never> = { data: null, error: null, loading: true, version: 0 };

export interface UseResult<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  version: number;
  reload: () => Promise<void>;
}

/** Load a REST answer and keep it current: events and resync messages for the scope refetch it. */
export function useResource<T>(key: string, fetcher: (client: Client, signal: AbortSignal) => Promise<T>, scope: Scope, enabled = true): UseResult<T> {
  const app = useApp();
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const scopeKey = `${scope.project ?? ''}/${scope.run ?? ''}/${(scope.types ?? []).join(',')}/${scope.resync === false ? 'n' : ''}`;
  const [resource, setResource] = useState<Resource<T> | null>(null);

  useEffect(() => {
    if (!enabled) {
      setResource(null);
      return undefined;
    }
    const r = createResource<T>((signal) => fetcherRef.current(app.client, signal));
    setResource(r);
    const unregister = app.hub.register(r as Resource<unknown>, scope);
    void r.load();
    return () => {
      unregister();
      r.dispose();
    };
  }, [key, enabled, app.client, app.hub, scopeKey]);

  const subscribe = useCallback((cb: () => void) => (resource ? resource.subscribe(cb) : () => undefined), [resource]);
  const getSnapshot = useCallback(() => (resource ? resource.get() : (EMPTY as ResourceState<T>)), [resource]);
  const snap = useSyncExternalStore(subscribe, getSnapshot);
  const reload = useCallback(async () => {
    await resource?.load();
  }, [resource]);
  return { data: snap.data, error: snap.error, loading: snap.loading, version: snap.version, reload };
}
