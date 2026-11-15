// The route table shared with the fake API server. Every call the app makes goes through it.

export interface Route {
  method: 'GET' | 'POST';
  pattern: string;
}

export const ROUTES = {
  session: { method: 'GET', pattern: '/api/v1/session' },
  installation: { method: 'GET', pattern: '/api/v1/installation' },
  runtime: { method: 'GET', pattern: '/api/v1/runtime' },
  health: { method: 'GET', pattern: '/api/v1/installation/health' },
  projects: { method: 'GET', pattern: '/api/v1/projects' },
  readiness: { method: 'GET', pattern: '/api/v1/projects/{pid}/readiness' },
  repositories: { method: 'GET', pattern: '/api/v1/projects/{pid}/repositories' },
  configuration: { method: 'GET', pattern: '/api/v1/projects/{pid}/configuration' },
  configHistory: { method: 'GET', pattern: '/api/v1/projects/{pid}/configuration/history' },
  configDiff: { method: 'GET', pattern: '/api/v1/projects/{pid}/configuration/diff' },
  runs: { method: 'GET', pattern: '/api/v1/projects/{pid}/tasks' },
  createRun: { method: 'POST', pattern: '/api/v1/projects/{pid}/tasks' },
  run: { method: 'GET', pattern: '/api/v1/tasks/{slug}' },
  next: { method: 'GET', pattern: '/api/v1/tasks/{slug}/next' },
  specification: { method: 'GET', pattern: '/api/v1/tasks/{slug}/specification' },
  specificationVersion: { method: 'GET', pattern: '/api/v1/tasks/{slug}/specification/versions/{v}' },
  gherkin: { method: 'GET', pattern: '/api/v1/tasks/{slug}/gherkin' },
  workflow: { method: 'GET', pattern: '/api/v1/tasks/{slug}/workflow' },
  tdd: { method: 'GET', pattern: '/api/v1/tasks/{slug}/tdd' },
  verification: { method: 'GET', pattern: '/api/v1/tasks/{slug}/verification' },
  trace: { method: 'GET', pattern: '/api/v1/tasks/{slug}/trace' },
  changes: { method: 'GET', pattern: '/api/v1/tasks/{slug}/changes' },
  changeDiff: { method: 'GET', pattern: '/api/v1/tasks/{slug}/changes/diff' },
  artifact: { method: 'GET', pattern: '/api/v1/tasks/{slug}/artifacts/{aid}' },
  log: { method: 'GET', pattern: '/api/v1/tasks/{slug}/logs/{tid}' },
  report: { method: 'GET', pattern: '/api/v1/tasks/{slug}/report' },
  approvals: { method: 'GET', pattern: '/api/v1/approvals' },
  decide: { method: 'POST', pattern: '/api/v1/tasks/{slug}/approvals' },
  accept: { method: 'POST', pattern: '/api/v1/tasks/{slug}/acceptance' },
  control: { method: 'POST', pattern: '/api/v1/tasks/{slug}/control' },
  audit: { method: 'GET', pattern: '/api/v1/audit' },
  events: { method: 'GET', pattern: '/api/v1/events' },
} as const satisfies Record<string, Route>;

export type RouteName = keyof typeof ROUTES;

/** Fill the placeholders with percent-encoded values and append the query in the order given. */
export function buildPath(name: RouteName, params: Record<string, string | number> = {}, query: Record<string, string | number | null | undefined> = {}): string {
  const path = ROUTES[name].pattern.replace(/\{(\w+)\}/g, (_m, key: string) => {
    const v = params[key];
    if (v === undefined) throw new Error(`missing route parameter ${key}`);
    return encodeURIComponent(String(v));
  });
  const parts = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `${path}?${parts.join('&')}` : path;
}
