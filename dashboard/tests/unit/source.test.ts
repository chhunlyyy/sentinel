import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, test } from 'vitest';

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

describe('AC-INS-06e the source has no raw HTML sink', () => {
  const src = join(process.cwd(), 'src');
  const files = walk(src).filter((f) => /\.(ts|tsx|html)$/.test(f));
  test('AC-INS-06e source files exist', () => expect(files.length).toBeGreaterThan(5));
  test.each(['dangerouslySetInnerHTML', 'innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval(', 'new Function'])(
    'AC-INS-06e no file uses %s',
    (needle) => {
      const hits = files.filter((f) => readFileSync(f, 'utf8').includes(needle));
      expect(hits).toEqual([]);
    },
  );
  test('AC-INS-06e ESLint sets react/no-danger and no-implied-eval to error', () => {
    const cfg = readFileSync(join(process.cwd(), 'eslint.config.js'), 'utf8');
    expect(cfg).toMatch(/'react\/no-danger':\s*'error'/);
    expect(cfg).toMatch(/'no-implied-eval':\s*'error'/);
  });
});
