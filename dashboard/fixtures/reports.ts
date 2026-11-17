// Notifications and analytics of the fake API (plan/v1.1/phaseH): the fixture "analytics-small" is the answer the real
// function gives for the registry of tests/test_analytics.py, and the notifications are rows the rule table produces.
import type * as W from '../src/api/wire.ts';

const note = (id: number, level: string, text: string, link: string, at: string, project = 'digital-hr', run = 'leave-balance'): W.WNotification => ({
  id: `${project}:${id}`, project, run, level, text, link, at, read_at: null,
});

/** Four unread notifications, newest first when sorted by time. */
export function fourNotifications(): W.WNotification[] {
  return [
    note(104, 'action', 'Specification ready for review', '/tasks/leave-balance/specification', '2026-11-14T10:40:00.000000Z'),
    note(103, 'warning', 'Provider <b>codex</b> unavailable', '/tasks/leave-balance/workflow', '2026-11-14T10:30:00.000000Z'),
    note(102, 'info', 'Run started', '/tasks/tax-form', '2026-11-14T10:20:00.000000Z', 'payroll', 'tax-form'),
    note(101, 'warning', 'Verification failed: lint', '/tasks/leave-balance/verification', '2026-11-14T10:10:00.000000Z'),
  ];
}

export function analyticsSmall(): W.WAnalytics {
  return {
    range: { from: '2026-11-01', to: '2026-11-30' },
    runs: { total: 4, by_state: { COMPLETED: 2, EXECUTING: 1, FAILED: 1 }, by_type: { bug: 1, feature: 3 } },
    lead_time_seconds: { count: 3, median: 7200, p90: 14400 },
    acceptance_rate: { value: 0.5, accepted: 1, decided: 2 },
    approval_wait_seconds: { specification: { count: 3, median: 1800, p90: 1800 }, gherkin: { count: 1, median: 1200, p90: 1200 } },
    tasks: { by_role: { specifier: { count: 1, median_seconds: 60 }, tdd_green: { count: 4, median_seconds: 150 } } },
    retries: { total: 1 },
    provider_failure_rate: { claude: { value: 0, failures: 0, tasks: 1 }, codex: { value: 0.25, failures: 1, tasks: 4 }, gemini: { value: null, reason: 'no tasks for this provider' } },
    cost: { total: { value: 11.5, partial: false, reported_tasks: 5, unreported_tasks: 0 }, partial: false, by_task: { t1: 1, t2: 2 }, by_role: { specifier: 0.5, tdd_green: 11 }, by_provider: { claude: 0.5, codex: 11 } },
    tdd: { cycles: { total: 3, accepted: 2, rejected: { red: 0, green: 1, refactor: 0 } } },
    verification: {
      pass_rate: { lint: { value: 1, passed: 3, total: 3 }, test: { value: 2 / 3, passed: 2, total: 3 } },
      first_attempt_pass_rate: { value: 0.5, passed_first: 1, verified: 2 },
    },
    rework: { spec_revisions: 1, gherkin_revisions: 1, changes_requested: 1, findings_routed: 2 },
  };
}

/** Nothing reported: every metric that can be missing is a null with its reason. */
export function analyticsEmpty(): W.WAnalytics {
  const a = analyticsSmall();
  a.lead_time_seconds = { value: null, reason: 'no finished runs' };
  a.acceptance_rate = { value: null, reason: 'no decided runs' };
  a.approval_wait_seconds = { value: null, reason: 'no decided approvals' };
  a.cost = { ...a.cost, total: { value: null, reason: 'not reported' }, by_task: {}, by_role: {}, by_provider: {} };
  return a;
}

export function analyticsPartialCost(): W.WAnalytics {
  const a = analyticsSmall();
  a.cost = { ...a.cost, total: { value: 3.5, partial: true, reported_tasks: 6, unreported_tasks: 4 }, partial: true };
  return a;
}
