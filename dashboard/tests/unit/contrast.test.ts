import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, test } from 'vitest';

const css = readFileSync(join(process.cwd(), 'src/styles.css'), 'utf8');

function tokens(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)) out[m[1]] = m[2];
  return out;
}
function blockAfter(src: string, marker: string): string {
  const start = src.indexOf(marker);
  if (start < 0) throw new Error(`missing ${marker}`);
  const open = src.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === '{') depth++;
    if (src[i] === '}' && --depth === 0) return src.slice(open + 1, i);
  }
  throw new Error('unbalanced');
}
const defaultDarkTokens = tokens(blockAfter(css, ':root {'));
const explicitDark = { ...defaultDarkTokens, ...tokens(blockAfter(css, ':root[data-theme="dark"]')) };
const lightTokens = { ...defaultDarkTokens, ...tokens(blockAfter(css, ':root[data-theme="light"]')) };
const mediaLight = { ...defaultDarkTokens, ...tokens(blockAfter(blockAfter(css, '@media (prefers-color-scheme: light)'), ':root:not([data-theme="dark"])')) };

function lum(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
function ratio(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const textPairs: [string, string][] = [
  ['text', 'bg'], ['text', 'surface'], ['text-muted', 'bg'], ['text-muted', 'surface'],
  ['link', 'bg'], ['link', 'surface'], ['on-accent', 'accent'],
  ['ok', 'bg'], ['ok', 'surface'], ['warn', 'bg'], ['warn', 'surface'], ['danger', 'bg'], ['danger', 'surface'],
  ['add-text', 'add-bg'], ['del-text', 'del-bg'], ['text', 'code-bg'],
];
const nonText: [string, string][] = [['focus', 'bg'], ['focus', 'surface'], ['border-strong', 'bg']];

describe('AC-DSH-01f colour tokens meet contrast', () => {
  const themes: [string, Record<string, string>][] = [
    ['dark (default)', defaultDarkTokens],
    ['dark (explicit toggle)', explicitDark],
    ['light (explicit toggle)', lightTokens],
    ['light (media query)', mediaLight],
  ];
  test.each(themes)('AC-DSH-01f %s theme', (_name, t) => {
    for (const [fg, bg] of textPairs) {
      expect(t[fg], `token ${fg}`).toBeDefined();
      expect(t[bg], `token ${bg}`).toBeDefined();
      expect(ratio(t[fg], t[bg]), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
    for (const [fg, bg] of nonText) expect(ratio(t[fg], t[bg]), `${fg} on ${bg}`).toBeGreaterThanOrEqual(3);
  });
});
