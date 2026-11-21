import { describe, expect, test } from 'vitest';
import { sampleConfigForm } from '../../fixtures/knowledge-fixtures.ts';
import { buildConfigChanges, isPathProtected } from '../../src/screens/Settings.tsx';

describe('Project configuration form field mapping and payload generation', () => {
  const form = sampleConfigForm('mef-hr');

  test('form sections and fields are categorized and typed', () => {
    expect(form.project).toBe('mef-hr');
    expect(form.sections.length).toBeGreaterThanOrEqual(3);

    const allFields = form.sections.flatMap((s) => s.fields);
    const booleans = allFields.filter((f) => f.type === 'boolean');
    const integers = allFields.filter((f) => f.type === 'integer');
    const strings = allFields.filter((f) => f.type === 'string');
    const enums = allFields.filter((f) => Boolean(f.enum));

    expect(booleans.length).toBeGreaterThan(0);
    expect(integers.length).toBeGreaterThan(0);
    expect(strings.length).toBeGreaterThan(0);
    expect(enums.length).toBeGreaterThan(0);

    const autoPublish = booleans.find((f) => f.path === 'knowledge.auto_push');
    expect(autoPublish).toBeDefined();
    expect(autoPublish?.editable).toBe(true);

    const summaries = integers.find((f) => f.path === 'knowledge.max_summaries');
    expect(summaries).toBeDefined();
    expect(summaries?.value).toBe(300);

    const rigors = enums.find((f) => f.path === 'quality.rigor_default');
    expect(rigors).toBeDefined();
    expect(rigors?.enum).toContain('standard');
    expect(rigors?.enum).toContain('strict');
  });

  test('buildConfigChanges converts modified fields into payload changes', () => {
    const rawChanges = {
      'knowledge.auto_push': false,
      'knowledge.max_summaries': 400,
      'quality.rigor_default': 'strict',
    };

    const payload = buildConfigChanges(rawChanges);
    expect(payload).toEqual([
      { path: 'knowledge.auto_push', value: false },
      { path: 'knowledge.max_summaries', value: 400 },
      { path: 'quality.rigor_default', value: 'strict' },
    ]);
  });

  test('isPathProtected guards against modifying shared_repo and repo root paths', () => {
    expect(isPathProtected('state.shared_repo')).toBe(true);
    expect(isPathProtected('repos.0.path')).toBe(true);
    expect(isPathProtected('repos.backend.path')).toBe(true);

    // Non-protected paths can be updated
    expect(isPathProtected('knowledge.auto_publish')).toBe(false);
    expect(isPathProtected('repos.0.commands.test')).toBe(false);
    expect(isPathProtected('quality.rigor_default')).toBe(false);
  });
});
