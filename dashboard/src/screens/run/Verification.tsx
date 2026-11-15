import { calls } from '../../api/calls.ts';
import { Loaded } from '../../components/common.tsx';
import { formatTime } from '../../format.ts';
import { Link, enc } from '../../router.tsx';
import { useResource } from '../../state/app.tsx';

const NOT_RUN = new Set(['not_configured', 'disabled', 'not_run']);

export function VerificationTab({ pid, slug, base }: { pid: string; slug: string; base: string }) {
  const res = useResource(`verification-${pid}-${slug}`, (c) => calls.verification(c, slug, pid), { project: pid, run: slug });
  return (
    <>
      <h2>Verification</h2>
      <Loaded res={res}>
        {(v) => {
          const ran = v.rows.filter((r) => !NOT_RUN.has(r.status));
          const notRun = v.rows.filter((r) => NOT_RUN.has(r.status));
          const repos = Array.from(new Set(ran.map((r) => r.repo ?? 'run')));
          return (
            <>
              {v.round ? (
                <p>
                  Round {v.round.number} at {formatTime(v.round.at)}
                </p>
              ) : (
                <p>No verification round yet</p>
              )}
              {repos.map((repo) => (
                <section key={repo}>
                  <h3>{repo}</h3>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          {['Check', 'Status', 'Result', 'Time', 'Output'].map((h) => (
                            <th scope="col" key={h}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {ran.filter((r) => (r.repo ?? 'run') === repo).map((r) => (
                          <tr key={r.id} data-testid={`evidence-row-${r.id}`}>
                            <td>{r.repo ?? ''} {r.kind}</td>
                            <td>{r.status}</td>
                            <td>Exit code {r.exit_code ?? 'not reported'}, {r.passed ?? 0} passed, {r.failed ?? 0} failed</td>
                            <td>{formatTime(r.started_at)}</td>
                            <td><Link to={`${base}/evidence/${enc(r.id)}`}>Output</Link></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ))}
              <section data-testid="not-run">
                <h3>Not run</h3>
                {notRun.length ? (
                  <ul className="plain">
                    {notRun.map((r) => (
                      <li key={r.id}>
                        {r.repo ?? ''} {r.kind}: {r.status}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>Nothing was left out of this round.</p>
                )}
              </section>
              <section data-testid="missing-evidence">
                <h3>Missing evidence</h3>
                {v.missing.length ? (
                  <ul className="plain">
                    {v.missing.map((m, i) => (
                      <li key={i}>
                        {m.repo ?? ''} {m.kind}: {m.reason}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>No evidence is missing.</p>
                )}
              </section>
              <section data-testid="acceptance-computed" className="panel">
                <h3>Acceptance</h3>
                <p>Computed: {v.acceptance.computed}</p>
                {v.acceptance.reasons.length ? (
                  <ul>
                    {v.acceptance.reasons.map((r, i) => (
                      <li key={i}>
                        <Link to={`${base}/${r.view === 'verification' ? 'verification' : r.view}`}>{r.text}</Link>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </section>
            </>
          );
        }}
      </Loaded>
    </>
  );
}

