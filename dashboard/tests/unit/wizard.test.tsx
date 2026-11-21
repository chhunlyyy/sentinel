import { describe, expect, test } from 'vitest';
import { STEPS, ROLE_WHY, canAdvanceWizard, type WizardValidationInput } from '../../src/screens/NewProject.tsx';

describe('Project wizard 5-step lifecycle and validation state', () => {
  test('wizard defines the required 5 steps in correct sequence', () => {
    expect(STEPS).toHaveLength(5);
    expect(STEPS.map((s) => s.name)).toEqual([
      'Repositories',
      'Detected setup',
      'Shared knowledge',
      'AI team',
      'Check and create',
    ]);
  });

  test('roles define human-readable rationale for CLI runners', () => {
    const roles = Object.keys(ROLE_WHY);
    expect(roles).toContain('specifier');
    expect(roles).toContain('coder');
    expect(roles).toContain('reviewer');
    expect(roles).toContain('qa');
    expect(roles).toContain('knowledge');

    expect(ROLE_WHY.specifier).toBeTruthy();
    expect(ROLE_WHY.coder).toBeTruthy();
    expect(ROLE_WHY.knowledge).toBe('many small summaries');
  });

  test('step 0 validation requires project name, absolute path, and at least 1 repository', () => {
    const base: WizardValidationInput = {
      step: 0,
      name: '',
      path: '',
      repos: [],
      repoSetups: [],
      mode: 'local',
      url: '',
      roleRows: [],
    };

    // Missing everything
    expect(canAdvanceWizard(base)).toBe(false);

    // Name only
    expect(canAdvanceWizard({ ...base, name: 'Billing' })).toBe(false);

    // Name + relative path
    expect(canAdvanceWizard({ ...base, name: 'Billing', path: 'projects/billing' })).toBe(false);

    // Name + absolute path, but 0 repos
    expect(canAdvanceWizard({ ...base, name: 'Billing', path: '/home/dev/projects/billing' })).toBe(false);

    // Name + absolute path + 1 repo
    expect(
      canAdvanceWizard({
        ...base,
        name: 'Billing',
        path: '/home/dev/projects/billing',
        repos: [{ path: '/home/dev/projects/hr-backend', role: 'backend' }],
      }),
    ).toBe(true);
  });

  test('step 1 validation requires detected repository setups', () => {
    const base: WizardValidationInput = {
      step: 1,
      name: 'Billing',
      path: '/home/dev/projects/billing',
      repos: [{ path: '/home/dev/projects/hr-backend', role: 'backend' }],
      repoSetups: [],
      mode: 'local',
      url: '',
      roleRows: [],
    };

    expect(canAdvanceWizard(base)).toBe(false);
    expect(
      canAdvanceWizard({
        ...base,
        repoSetups: [{ path: '/home/dev/projects/hr-backend', role: 'backend', profile: 'gradle', test: './gradlew test', build: './gradlew build', lint: '', trackedBranches: 'develop, main' }],
      }),
    ).toBe(true);
  });

  test('step 2 validation handles local vs git shared knowledge access', () => {
    const base: WizardValidationInput = {
      step: 2,
      name: 'Billing',
      path: '/home/dev/projects/billing',
      repos: [{ path: '/home/dev/projects/hr-backend', role: 'backend' }],
      repoSetups: [{ path: '/home/dev/projects/hr-backend' }],
      mode: 'local',
      url: '',
      roleRows: [],
    };

    // Local mode requires no URL
    expect(canAdvanceWizard(base)).toBe(true);

    // Git mode requires non-empty URL
    expect(canAdvanceWizard({ ...base, mode: 'git', url: '' })).toBe(false);
    expect(canAdvanceWizard({ ...base, mode: 'git', url: '   ' })).toBe(false);
    expect(canAdvanceWizard({ ...base, mode: 'git', url: 'git@example.com:team/knowledge.git' })).toBe(true);
  });

  test('step 3 validation requires configured AI team roles', () => {
    const base: WizardValidationInput = {
      step: 3,
      name: 'Billing',
      path: '/home/dev/projects/billing',
      repos: [{ path: '/home/dev/projects/hr-backend', role: 'backend' }],
      repoSetups: [{ path: '/home/dev/projects/hr-backend' }],
      mode: 'local',
      url: '',
      roleRows: [],
    };

    expect(canAdvanceWizard(base)).toBe(false);
    expect(
      canAdvanceWizard({
        ...base,
        roleRows: [{ role: 'coder', runner: 'claude', model: 'claude-sonnet-5-5', why: 'code' }],
      }),
    ).toBe(true);
  });

  test('step 4 check and create is actionable', () => {
    const base: WizardValidationInput = {
      step: 4,
      name: 'Billing',
      path: '/home/dev/projects/billing',
      repos: [{ path: '/home/dev/projects/hr-backend', role: 'backend' }],
      repoSetups: [{ path: '/home/dev/projects/hr-backend' }],
      mode: 'local',
      url: '',
      roleRows: [{ role: 'coder', runner: 'claude', model: 'claude-sonnet-5-5', why: 'code' }],
    };

    expect(canAdvanceWizard(base)).toBe(true);
  });
});
