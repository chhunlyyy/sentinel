import { describe, expect, test } from 'vitest';
import { duration, isNull, percent, costLabel } from '../../src/analytics.ts';

describe('AC-ANL-01p reports format values without inventing any', () => {
  test.each([[7200, '2 h'], [14400, '4 h'], [90, '1 min 30 s'], [45, '45 s'], [0, '0 s'], [3660, '1 h 1 min']])('AC-ANL-01p duration %s', (s, text) => expect(duration(s)).toBe(text));
  test.each([[0.5, '50%'], [0.25, '25%'], [1, '100%'], [2 / 3, '66.7%']])('AC-ANL-01p percent %s', (v, text) => expect(percent(v)).toBe(text));
  test('AC-ANL-01p a null metric is recognised by value null and a reason', () => {
    expect(isNull({ value: null, reason: 'no decided runs' })).toBe(true);
    expect(isNull({ value: 0, accepted: 0, decided: 1 })).toBe(false);
    expect(isNull({ count: 3, median: 7200 })).toBe(false);
  });
  test('AC-ANL-02g partial cost is labelled with the number of tasks that did not report it', () => {
    expect(costLabel({ value: 3, partial: true, reported_tasks: 6, unreported_tasks: 4 })).toBe('partial: 4 tasks did not report cost');
    expect(costLabel({ value: 3, partial: true, reported_tasks: 9, unreported_tasks: 1 })).toBe('partial: 1 task did not report cost');
    expect(costLabel({ value: 3, partial: false, reported_tasks: 6, unreported_tasks: 0 })).toBe('');
  });
});
