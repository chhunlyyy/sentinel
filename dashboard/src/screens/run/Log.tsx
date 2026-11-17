import { useEffect, useRef, useState } from 'react';
import { calls } from '../../api/calls.ts';
import type { ApiError } from '../../api/errors.ts';
import { ErrorView } from '../../components/ErrorView.tsx';
import { Link } from '../../router.tsx';
import { useApp } from '../../state/app.tsx';

const LOG_CAP = 5000;

export function LogPage({ pid, slug, tid, base }: { pid: string; slug: string; tid: string; base: string }) {
  const app = useApp();
  const [lines, setLines] = useState<string[]>([]);
  const [hidden, setHidden] = useState(false);
  const [running, setRunning] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [following, setFollowing] = useState(true);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let stop = false;
    let offset = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setLines([]);
    setHidden(false);
    setError(null);
    setRunning(true);
    async function tick() {
      try {
        const a = await calls.log(app.client, slug, pid, tid, offset);
        if (stop) return;
        offset = a.next_offset;
        if (a.lines.length) {
          setLines((prev) => {
            const all = prev.concat(a.lines);
            if (all.length > LOG_CAP) {
              setHidden(true);
              return all.slice(all.length - LOG_CAP);
            }
            return all;
          });
        }
        setRunning(a.running);
        if (a.running) timer = setTimeout(() => void tick(), 1000);
      } catch (e) {
        if (!stop) {
          setError(e as ApiError);
          setRunning(false);
        }
      }
    }
    void tick();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [app.client, slug, pid, tid]);

  useEffect(() => {
    const el = box.current;
    if (el && following) el.scrollTop = el.scrollHeight;
  }, [lines, following]);

  const notFound = error && (error.status === 404 || error.code === 'E_NOT_FOUND');
  return (
    <>
      <h2>Log of {tid}</h2>
      <p>
        <Link to={base}>Back to the run</Link> · <span data-testid="log-status">{error ? 'Stopped' : running ? 'Running, following the log' : 'Finished'}</span>
      </p>
      {notFound ? <p className="banner danger">Log not available</p> : error ? <ErrorView error={error} /> : null}
      {hidden ? <p className="hint">Older lines are hidden. Only the last {LOG_CAP} lines are kept.</p> : null}
      {!following ? (
        <button
          type="button"
          onClick={() => {
            setFollowing(true);
            const el = box.current;
            if (el) el.scrollTop = el.scrollHeight;
          }}
        >
          Follow
        </button>
      ) : null}
      <div
        className="log-box"
        data-testid="log-box"
        ref={box}
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
        role="region"
        aria-label={`Log of ${tid}`}
        onScroll={(e) => {
          const el = e.currentTarget;
          setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
        }}
      >
        <pre>{lines.join('\n')}</pre>
      </div>
    </>
  );
}

