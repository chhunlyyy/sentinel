// The answers the fake API gives for the routes of the recorded set (dashboard/fixtures/recorded/<name>.json),
// built from the same fixtures and encoders the fake server uses.
import * as E from './encode.ts';
import { applyPreset } from './presets.ts';
import { analyticsSmall, fourNotifications } from './reports.ts';
import { twoProjects } from './two-projects.ts';

export function fakeAnswers(): Record<string, unknown> {
  const db = twoProjects();
  const lb = db.runs['digital-hr/leave-balance'];
  const legacy = db.runs['digital-hr/old-fix'];
  const dh = db.projectData['digital-hr'];
  const review = twoProjects();
  applyPreset(review, 'approvals');
  const rev = review.runs['digital-hr/leave-balance'];
  const gh = twoProjects();
  applyPreset(gh, 'gherkin-review');
  const ghr = gh.runs['digital-hr/leave-balance'];
  const decided = review.runs['digital-hr/leave-balance'];
  decided.detail.approvals.specification.record = { decision: 'approve', approver: 'dev', channel: 'dashboard', at: '2026-11-14T09:30:00Z', comment: null };
  const fileDiff = lb.diffs['backend:src/main/Leave.java'];
  const task = lb.workflow.nodes[0].id;
  const approvals = ['specification', 'gherkin'].flatMap((gate) => [{ gate, project: 'digital-hr', slug: 'leave-balance', state: 'IN_REVIEW', version: 1, sha256: lb.detail.approvals.specification.sha256 ?? '', artifact_id: 'ar-1', requested_at: '2026-11-14T09:10:00Z' }]);
  return {
    session: { csrf: 'c', user: { name: 'dev', role: 'admin' } },
    installation: E.installation(db.installation),
    runtime: E.runtime(db.runtime),
    health: E.health(db.health),
    projects: { items: E.projects(db.projects), next: null },
    runs: { items: dh.runs.map(E.runSummary), next: null },
    run: E.run(lb.detail, lb.next),
    run_review: E.run(rev.detail, rev.next),
    run_legacy: E.run(legacy.detail, legacy.next),
    next: E.next(lb.next, lb.detail),
    specification: E.specification(rev.specification.current, rev.specification.versions, rev.detail.state),
    specification_version: E.specVersion(lb.specification.current),
    gherkin: E.gherkin(ghr.gherkin, ghr.detail.state),
    workflow: E.workflow(lb.workflow, lb.detail),
    tdd: E.tdd(lb.tdd),
    verification: E.verification(lb),
    trace: E.trace(lb),
    approvals: { items: approvals, next: null },
    audit: { items: dh.audit.map((a) => E.audit('digital-hr', a)), next: null },
    readiness: E.readiness('digital-hr', dh.readiness.default),
    repositories: { items: dh.repositories.items.map(E.repository), next: null },
    configuration: E.configuration('digital-hr', dh.configuration),
    config_history: { items: dh.history.items.map(E.configVersion), next: null },
    config_diff: E.configDiff('1', 'current', ''),
    changes: E.changes('leave-balance', lb.changes),
    changes_diff: E.diff('backend', 'src/main/Leave.java', fileDiff),
    log: E.log(task, lb.logs['t-green1'].lines, 40, 0, false),
    decision: E.run(decided.detail, decided.next),
    report: db.runs['digital-hr/leave-form'].report,
    notifications: { items: fourNotifications(), next: null, unread: 4, unavailable: [] },
    analytics: analyticsSmall(),
    notification_read: { ...fourNotifications()[0], read_at: '2026-11-14T11:30:00.000000Z' },
    factory: db.factory?.['digital-hr'],
  };
}
