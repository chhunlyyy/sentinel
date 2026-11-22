// AC-DSH-06i: compares the answers of the fake API with the answers recorded from the real server
// (tests/test_dashboard_fixtures.py writes recorded/*.json). Keys and value types must match; values may differ.
// Run by that test and by vitest (tests/unit/fixtures.test.ts).
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fakeAnswers } from './answers.ts';

// run from the dashboard folder (npm test, or tests/test_dashboard_fixtures.py with cwd set there)
// SENTINEL_FIXTURES_DIR points at a fresh recording (tests/test_dashboard_fixtures.py records into a temp folder)
const RECORDED = process.env.SENTINEL_FIXTURES_DIR ?? join(process.cwd(), 'fixtures', 'recorded');

/** Paths whose keys depend on the data (maps), or whose shape depends on a kind field; only their value types are compared. */
const MAPS = [/\.approvals$/, /\.task_counts$/, /\.commands$/, /^factory\.runs\[\]\.(agents|stations|task_usage)$/, /^factory\.who$/, /^analytics\.runs\.by_(state|type)$/, /^analytics\.usage\.by_(model|week|role)$/];
/** The next step has fields that depend on its kind; only the kind is compared. Config values hold any JSON value. */
const KIND_ONLY = [/\.next$/, /^next$/];
const ANY = [/\.value$/, /\.overridden\[\]\.value$/, /^report\.report$/, /^analytics\.(?!range$|runs$)[a-z_]+$/];
/** Recorded answers the fake does not reproduce, with the reason. */
export const NOT_COMPARED: Record<string, string> = {};

const kind = (v: unknown) => (v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v);

export function compare(path: string, rec: unknown, fake: unknown, out: string[]): void {
  if (ANY.some((m) => m.test(path))) return;
  if (KIND_ONLY.some((m) => m.test(path))) {
    const k = (v: unknown) => (v && typeof v === 'object' ? (v as { kind?: unknown }).kind : undefined);
    if (rec && fake && typeof k(rec) !== typeof k(fake)) out.push(`${path}.kind: recorded ${typeof k(rec)}, fake ${typeof k(fake)}`);
    return;
  }
  if (rec === null || fake === null || rec === undefined || fake === undefined) return; // nullable on either side
  if (kind(rec) !== kind(fake)) {
    out.push(`${path}: recorded ${kind(rec)}, fake ${kind(fake)}`);
    return;
  }
  if (Array.isArray(rec)) {
    if (!rec.length) return;
    for (const f of fake as unknown[]) compare(`${path}[]`, rec[0], f, out);
    return;
  }
  if (typeof rec !== 'object') return;
  const r = rec as Record<string, unknown>;
  const f = fake as Record<string, unknown>;
  if (MAPS.some((m) => m.test(path))) {
    const rv = Object.values(r)[0];
    for (const v of Object.values(f)) compare(`${path}.*`, rv, v, out);
    return;
  }
  for (const k of Object.keys(r)) if (!(k in f)) out.push(`${path}.${k}: recorded by the real server, missing in the fake`);
  for (const k of Object.keys(f)) if (!(k in r)) out.push(`${path}.${k}: served by the fake, not in the real answer`);
  for (const k of Object.keys(r)) if (k in f) compare(`${path}.${k}`, r[k], f[k], out);
}

export function check(): { problems: string[]; names: string[] } {
  const fake = fakeAnswers();
  const problems: string[] = [];
  const names = readdirSync(RECORDED).filter((n) => n.endsWith('.json')).map((n) => n.slice(0, -5)).sort();
  for (const name of names) {
    if (name in NOT_COMPARED) continue;
    if (!(name in fake)) {
      problems.push(`${name}: recorded but the fake has no answer for it`);
      continue;
    }
    const rec = JSON.parse(readFileSync(join(RECORDED, `${name}.json`), 'utf8')) as unknown;
    const out: string[] = [];
    compare(name, rec, fake[name], out);
    problems.push(...out);
  }
  for (const name of Object.keys(fake)) if (!names.includes(name)) problems.push(`${name}: the fake answers it but nothing was recorded`);
  return { problems, names };
}

if (process.argv[1] && import.meta.url === new URL(`file://${process.argv[1]}`).href) {
  const { problems, names } = check();
  if (problems.length) {
    console.error(`fixture shapes differ from the recorded answers of the real server (${names.length} recorded):\n${problems.join('\n')}`);
    process.exit(1);
  }
  console.log(`fixture shapes match ${names.length} recorded answers`);
}
