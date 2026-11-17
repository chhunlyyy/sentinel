import { describe, expect, test } from 'vitest';
import { check, NOT_COMPARED } from '../../fixtures/check.ts';

describe('AC-DSH-06i the fixtures served by the fake API have the shapes recorded from the real server', () => {
  const { problems, names } = check();
  test('AC-DSH-06i the real server was recorded for every route the UI reads', () => {
    expect(names.length).toBeGreaterThanOrEqual(25);
    for (const n of ['run', 'specification', 'gherkin', 'tdd', 'verification', 'trace', 'changes', 'readiness', 'health', 'configuration']) expect(names).toContain(n);
  });
  test('AC-DSH-06i keys and value types equal the recorded answers', () => {
    expect(problems).toEqual([]);
  });
  test('AC-DSH-06i every recorded answer is compared with the fake', () => {
    expect(Object.keys(NOT_COMPARED)).toEqual([]);
  });
});
