import { calls } from '../../api/calls.ts';
import { Loaded } from '../../components/common.tsx';
import { DiffViewer } from '../../components/DiffView.tsx';
import { Link, enc, navigate } from '../../router.tsx';
import { useResource } from '../../state/app.tsx';

export function ChangesTab({ pid, slug, base }: { pid: string; slug: string; base: string }) {
  const res = useResource(`changes-${pid}-${slug}`, (c) => calls.changes(c, slug, pid), { project: pid, run: slug });
  const q = new URLSearchParams(window.location.hash.split('?')[1] ?? '');
  const repo = q.get('repo');
  const path = q.get('path');
  const mode = q.get('mode') === 'split' ? 'split' : 'inline';
  const diff = useResource(`diff-${pid}-${slug}-${repo}-${path}-${mode}`, (c) => calls.changeDiff(c, slug, pid, repo!, path!, mode), { project: pid, run: slug }, !!repo && !!path);
  const diffLink = (r: string, p: string, m: string) => `${base}/changes?repo=${enc(r)}&path=${enc(p)}&mode=${m}`;
  return (
    <>
      <h2>Changes</h2>
      <Loaded res={res}>
        {(c) =>
          c.repos.length === 0 ? (
            <p>No changes yet</p>
          ) : (
            <>
              {c.repos.map((r) => (
                <section key={r.id} data-testid={`changes-repo-${r.id}`}>
                  <h3>{r.id}</h3>
                  <p>
                    Branch {r.branch} · base <code>{r.base}</code> · head <code>{r.head}</code> · {r.files_count} files · +{r.additions} -{r.deletions}
                  </p>
                  <ul className="plain">
                    {r.files.map((f) => (
                      <li key={f.path} data-testid={`file-${f.path}`}>
                        <code>{f.path}</code> {f.status} +{f.additions} -{f.deletions}{' '}
                        {f.cycles.map((cy) => (
                          <span key={cy}><Link to={`${base}/tdd`}>{cy}</Link>{' '}</span>
                        ))}
                        {f.tasks.map((t) => (
                          <span key={t}><Link to={`${base}/log/${enc(t)}`}>{t}</Link>{' '}</span>
                        ))}
                        <Link to={diffLink(r.id, f.path, 'inline')}>Diff</Link>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </>
          )
        }
      </Loaded>
      {repo && path ? (
        <section>
          <h3>
            Diff of {path} in {repo}
          </h3>
          <div className="row">
            <button type="button" className="secondary" aria-pressed={mode === 'inline'} onClick={() => navigate(diffLink(repo, path, 'inline').replace('#', ''))}>
              Inline
            </button>
            <button type="button" className="secondary" aria-pressed={mode === 'split'} onClick={() => navigate(diffLink(repo, path, 'split').replace('#', ''))}>
              Split
            </button>
          </div>
          <Loaded res={diff}>{(d) => <DiffViewer answer={d} mode={mode} />}</Loaded>
        </section>
      ) : null}
    </>
  );
}

