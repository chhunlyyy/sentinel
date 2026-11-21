import { describe, expect, test } from 'vitest';
import { filterKnowledgeRecords } from '../../src/screens/Knowledge.tsx';
import { SAMPLE_KNOWLEDGE_RECORDS } from '../../fixtures/knowledge-fixtures.ts';

describe('Knowledge records filtering, search, and pagination', () => {
  test('filter all returns all change records', () => {
    const records = filterKnowledgeRecords(SAMPLE_KNOWLEDGE_RECORDS, 'all');
    expect(records.length).toBe(SAMPLE_KNOWLEDGE_RECORDS.length);
  });

  test('filter verified returns only verified records from runs', () => {
    const verified = filterKnowledgeRecords(SAMPLE_KNOWLEDGE_RECORDS, 'verified');
    expect(verified.length).toBeGreaterThan(0);
    expect(verified.every((r) => r.provenance === 'verified')).toBe(true);
  });

  test('filter inferred returns only git-inferred change records', () => {
    const inferred = filterKnowledgeRecords(SAMPLE_KNOWLEDGE_RECORDS, 'inferred');
    expect(inferred.length).toBeGreaterThan(0);
    expect(inferred.every((r) => r.provenance === 'inferred')).toBe(true);
    expect(verifiedAndInferredCount(SAMPLE_KNOWLEDGE_RECORDS)).toBe(SAMPLE_KNOWLEDGE_RECORDS.length);
  });

  test('search query matches title, summary, key, repo or touched files', () => {
    const titleMatch = filterKnowledgeRecords(SAMPLE_KNOWLEDGE_RECORDS, 'all', 'Employee search');
    expect(titleMatch.some((r) => r.key === 'run-employee-search')).toBe(true);

    const repoMatch = filterKnowledgeRecords(SAMPLE_KNOWLEDGE_RECORDS, 'all', 'frontend');
    expect(repoMatch.every((r) => r.repo === 'frontend')).toBe(true);

    const fileMatch = filterKnowledgeRecords(SAMPLE_KNOWLEDGE_RECORDS, 'all', 'build.gradle');
    expect(fileMatch.some((r) => r.key === 'pr-231')).toBe(true);

    const noMatch = filterKnowledgeRecords(SAMPLE_KNOWLEDGE_RECORDS, 'all', 'xyznonexistentterm123');
    expect(noMatch).toEqual([]);
  });

  test('combining provenance filter and search query narrows records accurately', () => {
    const combined = filterKnowledgeRecords(SAMPLE_KNOWLEDGE_RECORDS, 'verified', 'search');
    expect(combined.every((r) => r.provenance === 'verified')).toBe(true);
    expect(combined.length).toBeGreaterThan(0);

    const emptyCombined = filterKnowledgeRecords(SAMPLE_KNOWLEDGE_RECORDS, 'verified', 'Spring Boot');
    expect(emptyCombined).toEqual([]);
  });
});

function verifiedAndInferredCount(records: typeof SAMPLE_KNOWLEDGE_RECORDS): number {
  const v = filterKnowledgeRecords(records, 'verified').length;
  const i = filterKnowledgeRecords(records, 'inferred').length;
  return v + i;
}
