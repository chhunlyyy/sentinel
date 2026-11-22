import { describe, expect, test } from 'vitest';
import * as adapt from '../../src/api/adapt.ts';
import type * as W from '../../src/api/wire.ts';

describe('review provenance', () => {
  test('adapts provenance from wire specification answer', () => {
    const wireSpec: W.WSpecification = {
      version: 1,
      sha256: 'abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234',
      approval_state: 'IN_REVIEW',
      run_state: 'SPECIFICATION_REVIEW',
      text: '## Problem statement\nDetails',
      validation: { errors: [], warnings: [] },
      diff: null,
      previous_version: null,
      versions: [],
      decision: null,
      requested_at: '2026-11-22T08:00:00Z',
      provenance: 'imported from a session',
    };
    const adapted = adapt.specification(wireSpec);
    expect(adapted.provenance).toBe('imported from a session');
  });

  test('handles null/missing provenance gracefully', () => {
    const wireSpec: W.WSpecification = {
      version: 2,
      sha256: '1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd',
      approval_state: 'IN_REVIEW',
      run_state: 'SPECIFICATION_REVIEW',
      text: '## Problem statement\nDetails',
      validation: { errors: [], warnings: [] },
      diff: null,
      previous_version: 1,
      versions: [],
      decision: null,
      requested_at: '2026-11-22T08:00:00Z',
    };
    const adapted = adapt.specification(wireSpec);
    expect(adapted.provenance).toBeUndefined();
  });
});
