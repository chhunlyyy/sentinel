import { calls } from '../../api/calls.ts';
import { Loaded } from '../../components/common.tsx';
import { Link, enc } from '../../router.tsx';
import { useResource } from '../../state/app.tsx';

export function TraceTab({ pid, slug, base }: { pid: string; slug: string; base: string }) {
  const res = useResource(`trace-${pid}-${slug}`, (c) => calls.trace(c, slug, pid), { project: pid, run: slug });
  return (
    <>
      <h2>Trace</h2>
      <Loaded res={res}>
        {(t) => {
          const empty = t.requirements.length === 0 && t.gaps.length === 0 && t.failures.length === 0;
          if (empty) return <p>No trace links yet</p>;
          return (
            <>
              {t.requirements.map((r) => (
                <section key={r.id} data-testid={`trace-req-${r.id}`} className="panel">
                  <h3>{r.id}</h3>
                  <ul>
                    {r.acs.map((a) => (
                      <li key={a.id}>
                        <strong>{a.id}</strong>
                        <ul>
                          {a.scenarios.map((s) => (
                            <li key={s.id}>
                              <Link to={`${base}/gherkin`}>{s.name}</Link>
                              {s.cycle ? (
                                <ul>
                                  <li>
                                    Cycle <Link to={`${base}/tdd`}>{s.cycle.id}</Link>
                                    <ul>
                                      {s.cycle.files.map((f) => (
                                        <li key={`${f.repo}:${f.path}`}>
                                          File <Link to={`${base}/changes?repo=${enc(f.repo)}&path=${enc(f.path)}&mode=inline`}>{f.path}</Link>
                                        </li>
                                      ))}
                                      {s.cycle.evidence.map((e) => (
                                        <li key={e.id}>
                                          Evidence <Link to={`${base}/evidence/${enc(e.id)}`}>{e.id}</Link> {e.kind}: {e.passed ? 'passed' : 'failed'}
                                        </li>
                                      ))}
                                    </ul>
                                  </li>
                                </ul>
                              ) : (
                                <span> (no cycle yet)</span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
              <p data-testid="trace-acceptance">Acceptance: {t.acceptance ? t.acceptance.state : 'not reached'}</p>
              {t.gaps.length ? (
                <section data-testid="trace-gaps">
                  <h3>Gaps (missing links)</h3>
                  <ul>
                    {t.gaps.map((g) => (
                      <li key={g}>{g}</li>
                    ))}
                  </ul>
                </section>
              ) : null}
              {t.failures.length ? (
                <section data-testid="trace-failures">
                  <h3>Failures (failing checks)</h3>
                  <ul>
                    {t.failures.map((f) => (
                      <li key={f.text}>{f.evidence_id ? <Link to={`${base}/evidence/${enc(f.evidence_id)}`}>{f.text}</Link> : f.text}</li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </>
          );
        }}
      </Loaded>
    </>
  );
}

