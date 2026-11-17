import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { calls } from '../api/calls.ts';
import type { WNotification } from '../api/wire.ts';
import { clock, formatTime } from '../format.ts';
import { CONFIG_EVENTS, LEVEL_LABEL, NOTIFICATION_EVENTS, appRoute, claimDesktop, loadDesktopConfig, newSeen, raiseCandidates, type DesktopState } from '../notifications.ts';
import { Link, navigate } from '../router.tsx';
import { useApp, useResource } from '../state/app.tsx';

const ENABLED_KEY = 'sentinel.desktop.enabled';
const CONFIG_REFRESH_MS = 60_000;

type Permission = 'default' | 'granted' | 'denied';

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function permissionNow(): Permission | null {
  return typeof Notification === 'undefined' ? null : (Notification.permission as Permission);
}

/** The per-project notifications.desktop switch; the option is offered when any available project leaves it on. */
function useDesktopConfig() {
  const config = useResource<Record<string, boolean>>('desktop-config', async (c) => {
    const projects = await calls.projects(c);
    return loadDesktopConfig(projects.items.filter((x) => x.status === 'available').map((p) => p.id), async (id) => (await calls.configuration(c, id)).values);
  }, { types: CONFIG_EVENTS, resync: false });
  const reload = config.reload;
  useEffect(() => {
    const timer = window.setInterval(() => void reload(), CONFIG_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [reload]);
  return config;
}

/** Browser notifications: only after the user pressed the button and the browser granted permission. */
function useDesktop(items: WNotification[] | null, open: (n: WNotification) => void) {
  const config = useDesktopConfig();
  const [enabled, setEnabled] = useState(() => storage()?.getItem(ENABLED_KEY) === '1');
  const [permission, setPermission] = useState<Permission | null>(permissionNow);
  const seen = useRef(newSeen());
  const configRef = useRef<Record<string, boolean> | null>(null);
  configRef.current = config.data;
  const openRef = useRef(open);
  openRef.current = open;

  const allowed = useCallback((project: string) => configRef.current?.[project] ?? false, []);
  const offered = permission !== null && Object.values(config.data ?? {}).some(Boolean);

  useEffect(() => {
    if (!items) return;
    const state: DesktopState = { enabled, permission: permission ?? 'denied', allowed };
    for (const n of raiseCandidates(seen.current, items, state)) {
      const raise = () => {
        const note = new Notification('Sentinel', { body: n.text, tag: n.id });
        note.onclick = () => {
          window.focus();
          openRef.current(n);
        };
      };
      const locks = (navigator as Navigator & { locks?: LockManager }).locks;
      if (locks) void locks.request(`sentinel-desktop-${n.id}`, () => (claimDesktop(storage(), n.id) ? raise() : undefined));
      else if (claimDesktop(storage(), n.id)) raise();
    }
  }, [items, enabled, permission, allowed]);

  const enable = useCallback(async () => {
    if (typeof Notification === 'undefined') return;
    const answer = (await Notification.requestPermission()) as Permission;
    setPermission(answer);
    if (answer === 'granted') {
      try {
        storage()?.setItem(ENABLED_KEY, '1');
      } catch {
        /* the choice then lasts for this page only */
      }
      setEnabled(true);
    }
  }, []);

  return { canEnable: offered && permission !== 'granted' && permission !== 'denied', enabled: enabled && permission === 'granted', denied: permission === 'denied', enable };
}

export function NotificationBell() {
  const app = useApp();
  const res = useResource('notifications', (c) => calls.notifications(c), { types: NOTIFICATION_EVENTS });
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const items = res.data?.items ?? null;
  const unread = res.data?.unread ?? 0;

  const openOne = useCallback(
    (n: WNotification) => {
      setOpen(false);
      navigate(appRoute(n));
      if (!n.read_at) {
        void calls
          .markNotificationRead(app.client, n.id)
          .then(() => res.reload())
          .catch(() => undefined);
      }
    },
    [app.client, res],
  );
  const desktop = useDesktop(items, openOne);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <div className="bell">
      <button ref={buttonRef} type="button" className="secondary" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((o) => !o)}>
        Notifications
        {unread > 0 ? <span className="badge" aria-hidden="true">{unread}</span> : null}
        <span className="sr-only"> {unread} unread</span>
      </button>
      {open ? (
        <section id={panelId} className="bell-panel" aria-label="Notification list" data-testid="notification-panel">
          {res.error && !res.data ? <p className="banner danger" role="alert">{res.error.text}</p> : null}
          {items && items.length === 0 ? <p>No notifications</p> : null}
          {items?.length ? (
            <ul className="plain" aria-label="Notifications">
              {items.map((n) => (
                <li key={n.id} data-testid="notification" data-unread={n.read_at ? 'false' : 'true'}>
                  <Link
                    to={appRoute(n)}
                    onClick={(e) => {
                      e.preventDefault();
                      openOne(n);
                    }}
                  >
                    {n.text}
                  </Link>
                  <div className="hint">
                    <span>{LEVEL_LABEL[n.level] ?? n.level}</span> · <span>{n.project}</span> · <time dateTime={n.at} title={formatTime(n.at)}>{formatTime(n.at).slice(0, 10)} {clock(n.at)}</time>
                    {n.read_at ? ' · read' : ''}
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
          {res.data?.unavailable.length ? <p className="hint">Unavailable: {res.data.unavailable.map((u) => `${u.project} (${u.reason})`).join('; ')}</p> : null}
          {desktop.canEnable ? (
            <p>
              <button type="button" onClick={() => void desktop.enable()}>
                Enable desktop notifications
              </button>
            </p>
          ) : desktop.enabled ? (
            <p className="hint">Desktop notifications are on in this browser.</p>
          ) : desktop.denied ? (
            <p className="hint">The browser blocks desktop notifications for this page.</p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
