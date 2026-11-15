import { calls } from '../api/calls.ts';
import type { CheckStatus } from '../api/types.ts';
import { Loaded, StatusChip } from '../components/common.tsx';
import { formatTime } from '../format.ts';
import { Link } from '../router.tsx';
import { useResource } from '../state/app.tsx';

const LABEL: Record<CheckStatus, string> = { passed: 'Passed', failed: 'Failed', warning: 'Warning', not_configured: 'Not configured' };
const KIND: Record<CheckStatus, 'ok' | 'fail' | 'warn' | 'none'> = { passed: 'ok', failed: 'fail', warning: 'warn', not_configured: 'warn' };

function InstallationPage() {
  const install = useResource('settings-installation', (c) => calls.installation(c), {});
  const runtime = useResource('settings-runtime', (c) => calls.runtime(c), {});
  return (
    <>
      <h2>Sentinel installation</h2>
      <Loaded res={install}>
        {(i) => (
          <dl className="kv">
            <dt>Version</dt>
            <dd>{i.version}</dd>
            <dt>Install path</dt>
            <dd><code>{i.path}</code></dd>
            <dt>Python</dt>
            <dd>{i.python}</dd>
            <dt>Install method</dt>
            <dd>{i.method}</dd>
          </dl>
        )}
      </Loaded>
      <h3>Running server</h3>
      <Loaded res={runtime}>
        {(r) => (
          <dl className="kv">
            <dt>Process id</dt>
            <dd>{r.pid}</dd>
            <dt>Port</dt>
            <dd>{r.port}</dd>
            <dt>Started</dt>
            <dd>{formatTime(r.started_at)}</dd>
            <dt>Loaded projects</dt>
            <dd>{r.projects.join(', ') || 'none'}</dd>
          </dl>
        )}
      </Loaded>
    </>
  );
}

function RuntimePage() {
  const runtime = useResource('settings-runtime-page', (c) => calls.runtime(c), {});
  return (
    <>
      <h2>Runtime connection</h2>
      <Loaded res={runtime}>
        {(r) => (
          <>
            <p>
              <strong>Connected to the running server</strong> (process {r.pid}, port {r.port}).
            </p>
            <p>
              The server is started with <code>sentinel dashboard</code> in a terminal. The browser cannot start, stop or restart it, and the installation path is chosen when Sentinel is installed.
            </p>
          </>
        )}
      </Loaded>
    </>
  );
}

function HealthPage() {
  const res = useResource('settings-health', (c) => calls.health(c), {});
  const checking = res.loading && !!res.data;
  return (
    <>
      <h2>Health checks</h2>
      {res.error ? (
        <div className="banner danger" data-testid="unavailable">
          <p>Connection unavailable</p>
          <p className="hint">{res.error.text}</p>
          <button type="button" className="secondary" onClick={() => void res.reload()}>
            Check again
          </button>
        </div>
      ) : (
        <Loaded res={res}>
          {(h) => (
            <>
              <p>
                Checked at <span data-testid="health-checked-at">{formatTime(h.checked_at)}</span>{' '}
                <button type="button" className="secondary" onClick={() => void res.reload()}>
                  Check again
                </button>
              </p>
              <ul className="plain">
                {h.checks.map((c) => (
                  <li key={`${c.id}-${c.status}`} className="panel" data-testid={`check-${c.id}`}>
                    <strong>{c.label}</strong> {c.required ? <span className="hint">(required)</span> : <span className="hint">(optional)</span>}{' '}
                    {checking ? <StatusChip kind="wait" label="Checking" /> : <StatusChip kind={KIND[c.status]} label={LABEL[c.status]} />}
                    <div>{c.message}</div>
                    {!checking && c.status !== 'passed' && c.fix ? (
                      <div>
                        Fix: <code>{c.fix}</code>
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Loaded>
      )}
    </>
  );
}

export function SettingsScreen({ page }: { page: string }) {
  const items: [string, string][] = [
    ['installation', 'Sentinel installation'],
    ['runtime', 'Runtime connection'],
    ['health', 'Health checks'],
  ];
  return (
    <section>
      <h1>Settings</h1>
      <nav aria-label="Settings">
        <ul className="tabs">
          {items.map(([id, label]) => (
            <li key={id}>
              <Link to={`/settings/${id}`} current={page === id}>
                {label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {page === 'installation' ? <InstallationPage /> : null}
      {page === 'runtime' ? <RuntimePage /> : null}
      {page === 'health' ? <HealthPage /> : null}
      {!items.some(([id]) => id === page) ? <p>Page not found</p> : null}
    </section>
  );
}
