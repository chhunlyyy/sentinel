import type { DiffAnswer, DiffLine } from '../api/types.ts';

/** A unified diff given as text (configuration versions, specification changes). */
export function UnifiedText({ text }: { text: string }) {
  const lines = text.split('\n');
  if (lines[lines.length - 1] === '') lines.pop();
  return (
    <div className="diff" data-testid="unified-diff">
      {lines.map((l, i) => {
        const add = l.startsWith('+') && !l.startsWith('+++');
        const del = l.startsWith('-') && !l.startsWith('---');
        const cls = add ? 'add' : del ? 'del' : l.startsWith('@@') ? 'hunk' : '';
        return (
          <div key={i} className={cls} data-testid={add ? 'diff-line-add' : del ? 'diff-line-del' : 'diff-line'}>
            <span className="pre-wrap">{l || ' '}</span>
            {add ? <span className="sr-only"> Added line</span> : null}
            {del ? <span className="sr-only"> Removed line</span> : null}
          </div>
        );
      })}
    </div>
  );
}

function Sign({ type }: { type: DiffLine['type'] }) {
  if (type === 'add')
    return (
      <>
        <span aria-hidden="true">+</span>
        <span className="sr-only">Added line</span>
      </>
    );
  if (type === 'del')
    return (
      <>
        <span aria-hidden="true">-</span>
        <span className="sr-only">Removed line</span>
      </>
    );
  return <span aria-hidden="true"> </span>;
}

function Inline({ answer }: { answer: DiffAnswer }) {
  return (
    <div className="diff">
      <table data-testid="diff-view" data-mode="inline">
        <caption className="sr-only">Changes in {answer.path}</caption>
        <tbody>
          {answer.hunks.flatMap((h, hi) => [
            <tr key={`h${hi}`} className="hunk" data-testid="diff-hunk">
              <td colSpan={3}>{h.header}</td>
            </tr>,
            ...h.lines.map((l, li) => (
              <tr key={`${hi}-${li}`} className={l.type === 'ctx' ? '' : l.type} data-testid="diff-row" data-line={l.type === 'ctx' ? undefined : l.type}>
                <td className="num" data-testid="old-no">{l.old ?? ''}</td>
                <td className="num" data-testid="new-no">{l.new ?? ''}</td>
                <td data-testid={l.type === 'add' ? 'diff-line-add' : l.type === 'del' ? 'diff-line-del' : undefined}>
                  <Sign type={l.type} /> <span className="pre-wrap">{l.text}</span>
                </td>
              </tr>
            )),
          ])}
        </tbody>
      </table>
    </div>
  );
}

interface Pair {
  left: DiffLine | null;
  right: DiffLine | null;
}

function pairs(lines: DiffLine[]): Pair[] {
  const out: Pair[] = [];
  let i = 0;
  while (i < lines.length) {
    if (lines[i].type === 'ctx') {
      out.push({ left: lines[i], right: lines[i] });
      i += 1;
      continue;
    }
    const dels: DiffLine[] = [];
    const adds: DiffLine[] = [];
    while (i < lines.length && lines[i].type === 'del') dels.push(lines[i++]);
    while (i < lines.length && lines[i].type === 'add') adds.push(lines[i++]);
    for (let k = 0; k < Math.max(dels.length, adds.length); k++) out.push({ left: dels[k] ?? null, right: adds[k] ?? null });
  }
  return out;
}

function Cell({ line, side }: { line: DiffLine | null; side: 'left' | 'right' }) {
  if (!line) return <><td className="num" /><td data-side={side} /></>;
  const no = side === 'left' ? line.old : line.new;
  const testid = line.type === 'add' ? 'diff-line-add' : line.type === 'del' ? 'diff-line-del' : undefined;
  return (
    <>
      <td className="num">{no ?? ''}</td>
      <td className={line.type === 'ctx' ? '' : line.type} data-side={side} data-testid={testid}>
        <Sign type={line.type} /> <span className="pre-wrap">{line.text}</span>
      </td>
    </>
  );
}

function Split({ answer }: { answer: DiffAnswer }) {
  return (
    <div className="diff split">
      <table data-testid="diff-view" data-mode="split">
        <caption className="sr-only">Side by side changes in {answer.path}</caption>
        <tbody>
          {answer.hunks.flatMap((h, hi) => [
            <tr key={`h${hi}`} className="hunk" data-testid="diff-hunk">
              <td colSpan={4}>{h.header}</td>
            </tr>,
            ...(h.rows ?? pairs(h.lines)).map((p, pi) => (
              <tr key={`${hi}-${pi}`} data-testid="diff-row">
                <Cell line={p.left} side="left" />
                <Cell line={p.right} side="right" />
              </tr>
            )),
          ])}
        </tbody>
      </table>
    </div>
  );
}

export function DiffViewer({ answer, mode }: { answer: DiffAnswer; mode: 'inline' | 'split' }) {
  if (answer.binary) return <p className="banner">Binary file. No diff shown.</p>;
  return (
    <>
      {answer.truncated ? <p className="banner warn">The diff is longer than 1 MB. Only the start is shown.</p> : null}
      {mode === 'split' ? <Split answer={answer} /> : <Inline answer={answer} />}
    </>
  );
}
