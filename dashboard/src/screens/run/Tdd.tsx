import { calls } from '../../api/calls.ts';
import type { Evidence } from '../../api/types.ts';
import { Loaded } from '../../components/common.tsx';
import { ErrorView } from '../../components/ErrorView.tsx';
import { formatTime, prefix } from '../../format.ts';
import { Link, enc } from '../../router.tsx';
import { useResource } from '../../state/app.tsx';

const CYCLE_WORDS = (s: string) => (s.includes('ACCEPTED') ? 'accepted' : s === 'REJECTED' ? 'rejected' : s.includes('RUNNING') ? 'in progress' : s.toLowerCase().replace(/_/g, ' '));

export function TddTab({ pid, slug, base }: { pid: string; slug: string; base: string }) {
  const res = useResource(`tdd-${pid}-${slug}`, (c) => calls.tdd(c, slug, pid), { project: pid, run: slug });
  return (
    <>
      <h2>TDD cycles</h2>
      <Loaded res={res}>
        {(tdd) =>
          tdd.cycles.length === 0 ? (
            <p>No TDD cycles yet. Cycles are planned after the Gherkin approval.</p>
          ) : (
            <>
              {tdd.cycles.map((c) => (
                <article key={c.id} className="panel" data-testid={`cycle-${c.id}`}>
                  <h3>{c.behavior}</h3>
                  <p>
                    Repository {c.repo} · state <strong>{c.state}</strong> ({CYCLE_WORDS(c.state)})
                  </p>
                  <div className="row">
                    {c.phases.map((p) => (
                      <div key={p.phase} data-testid={`phase-${p.phase}`} className="panel">
                        <strong>{p.phase === 'red' ? 'Red' : p.phase === 'green' ? 'Green' : 'Refactor'}</strong>
                        <div>
                          {p.task_id ?? 'no task'} · {p.state} · attempt {p.attempt}
                        </div>
                        <div>
                          {p.evidence_ids.map((e) => (
                            <span key={e}>
                              <Link to={`${base}/evidence/${enc(e)}`}>{e}</Link>{' '}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </article>
              ))}
            </>
          )
        }
      </Loaded>
    </>
  );
}

function EvidenceCard({ ev, slug, pid }: { ev: Evidence; slug: string; pid: string }) {
  const out = useResource(`artifact-${pid}-${slug}-${ev.output_artifact}`, (c) => calls.artifact(c, slug, pid, ev.output_artifact!), { project: pid, run: slug }, !!ev.output_artifact);
  return (
    <>
      <dl className="kv">
        <dt>Kind</dt><dd>{ev.kind}</dd>
        <dt>Command</dt><dd><code>{ev.command ?? 'none'}</code></dd>
        <dt>Result</dt><dd>Exit code {ev.exit_code ?? 'not reported'}, {ev.passed ?? 0} passed, {ev.failed ?? 0} failed</dd>
        <dt>Classification</dt><dd>{ev.classification ?? 'none'}</dd>
        <dt>Started</dt><dd>{formatTime(ev.started_at)}</dd>
        <dt>Finished</dt><dd>{formatTime(ev.finished_at)}</dd>
        <dt>Provider</dt><dd>{ev.provider ?? 'Not reported'}</dd>
        <dt>Model</dt><dd>{ev.model ?? 'Not reported'}</dd>
        <dt>Changed files</dt>
        <dd>
          {ev.files.length === 0 ? <span>Not reported</span> : null}
          <ul className="plain">
            {ev.files.map((f) => (
              <li key={f.path}>
                <code>{f.path}</code> <code>{prefix(f.sha256)}</code>
              </li>
            ))}
          </ul>
        </dd>
      </dl>
      <h3>Captured output</h3>
      {!ev.output_artifact ? <p>No output was captured.</p> : null}
      {out.error ? (
        <div>
          <ErrorView error={out.error} />
          {typeof out.error.details.sha256 === 'string' ? <p>Stored sha256: <code>{out.error.details.sha256}</code></p> : null}
        </div>
      ) : null}
      {out.data ? (
        <pre data-testid="evidence-output" className="pre-wrap">
          {out.data.content}
        </pre>
      ) : null}
    </>
  );
}

export function EvidencePage({ pid, slug, eid, base }: { pid: string; slug: string; eid: string; base: string }) {
  const tdd = useResource(`evidence-tdd-${pid}-${slug}`, (c) => calls.tdd(c, slug, pid), { project: pid, run: slug });
  const ver = useResource(`evidence-ver-${pid}-${slug}`, (c) => calls.verification(c, slug, pid), { project: pid, run: slug });
  const ev = [...(tdd.data?.evidence ?? []), ...(ver.data?.rows ?? [])].find((e) => e.id === eid);
  const loading = !tdd.data && !tdd.error && !ver.data && !ver.error;
  return (
    <>
      <h2>Evidence {eid}</h2>
      <p>
        <Link to={`${base}/tdd`}>Back to TDD cycles</Link>
      </p>
      {loading ? <p className="hint" role="status">Loading</p> : ev ? <EvidenceCard ev={ev} slug={slug} pid={pid} /> : <p>Evidence not found</p>}
    </>
  );
}

