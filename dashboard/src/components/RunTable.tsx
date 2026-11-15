import type { RunSummary } from '../api/types.ts';
import { formatTime } from '../format.ts';
import { Link, enc } from '../router.tsx';

export function RunTable({ rows, project }: { rows: RunSummary[]; project?: boolean }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {project ? <th scope="col">Project</th> : null}
            <th scope="col">Slug</th>
            <th scope="col">Type</th>
            <th scope="col">Tier</th>
            <th scope="col">State</th>
            <th scope="col">Execution</th>
            <th scope="col">Acceptance</th>
            <th scope="col">Updated</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.project ?? ''}/${r.slug}`} data-testid="run-row" data-slug={r.slug} data-state={r.state}>
              {project ? <td>{r.project}</td> : null}
              <td>
                <Link to={`/projects/${enc(r.project ?? '')}/runs/${enc(r.slug)}`}>{r.slug}</Link>
                {r.workflow_version === '0.1' ? <span className="badge">Legacy (0.1)</span> : null}
              </td>
              <td>{r.type}</td>
              <td>{r.tier ?? ''}</td>
              <td>{r.state}</td>
              <td>{r.execution_status}</td>
              <td>{r.acceptance_status}</td>
              <td>{formatTime(r.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
