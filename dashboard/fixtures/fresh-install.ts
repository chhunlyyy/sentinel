import type { Db } from './db.ts';
import { health } from './two-projects.ts';

export function freshInstall(): Db {
  return {
    installation: { version: '1.1.0', path: '/home/dev/.local/share/uv/tools/sentinel', python: '3.12.3', method: 'uv tool' },
    runtime: { pid: 4242, port: 47831, started_at: '2026-11-14T08:00:00Z', projects: [] },
    health: health(),
    projects: [],
    projectData: {},
    runs: {},
  };
}
