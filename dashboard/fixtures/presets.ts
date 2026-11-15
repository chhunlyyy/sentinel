import type * as T from '../src/api/types.ts';
import type { Db, RunData } from './db.ts';
import { G1, GTAX, H2, H3 } from './constants.ts';
import { digitalHrData, repo, summary } from './two-projects.ts';

function setApproval(run: RunData, gate: 'specification' | 'gherkin', state: string, version: number, sha: string) {
  run.detail.approvals[gate] = { gate, state, version, sha256: sha };
  const g = run.workflow.gates.find((x) => x.gate === gate);
  if (g) {
    g.state = state;
    g.version = version;
  }
}

/** Named states of the fake database that several tests start from. */
export function applyPreset(db: Db, name: string): void {
  const lb = db.runs['digital-hr/leave-balance'];
  const tax = db.runs['payroll/tax-form'];
  switch (name) {
    case 'approvals': {
      lb.detail.state = 'SPECIFICATION_REVIEW';
      setApproval(lb, 'specification', 'IN_REVIEW', 2, H2);
      setApproval(lb, 'gherkin', 'NOT_REQUESTED', 0, '');
      lb.specification.current.state = 'IN_REVIEW';
      lb.specification.current.requested_at = '2026-11-14T09:10:00Z';
      lb.next = { kind: 'human', label: 'Your approval is needed: specification version 2', gate: 'specification', version: 2, command: null };
      tax.detail.state = 'GHERKIN_REVIEW';
      setApproval(tax, 'gherkin', 'IN_REVIEW', 1, GTAX);
      tax.gherkin.sha256 = GTAX;
      tax.gherkin.state = 'IN_REVIEW';
      tax.gherkin.requested_at = '2026-11-14T09:15:00Z';
      return;
    }
    case 'gherkin-review': {
      lb.detail.state = 'GHERKIN_REVIEW';
      setApproval(lb, 'specification', 'APPROVED', 2, H2);
      lb.specification.current.state = 'APPROVED';
      setApproval(lb, 'gherkin', 'IN_REVIEW', 1, G1);
      lb.gherkin.state = 'IN_REVIEW';
      lb.gherkin.requested_at = '2026-11-14T09:50:00Z';
      return;
    }
    case 'spec-v3': {
      const v3: T.SpecificationAnswer = {
        ...lb.specification.current, version: 3, sha256: H3, state: 'IN_REVIEW', previous_version: 2, requested_at: '2026-11-14T09:40:00Z',
        text: `${lb.specification.current.text}\nREQ-LEAVE-03 Leave of absence is reported separately.\n`,
      };
      lb.specification.oldVersions['2'] = { ...lb.specification.current, state: 'SUPERSEDED' };
      lb.specification.current = v3;
      lb.specification.versions = [
        ...lb.specification.versions.filter((v) => v.version !== 2),
        { version: 2, sha256: H2, decision: null, reviewer: null, channel: null, at: null, comment: null },
        { version: 3, sha256: H3, decision: null, reviewer: null, channel: null, at: null, comment: null },
      ].sort((a, b) => a.version - b.version);
      lb.detail.state = 'SPECIFICATION_REVIEW';
      setApproval(lb, 'specification', 'IN_REVIEW', 3, H3);
      return;
    }
    case 'no-approvals': {
      for (const r of Object.values(db.runs)) {
        for (const g of ['specification', 'gherkin'] as const) if (r.detail.approvals[g].state === 'IN_REVIEW') r.detail.approvals[g].state = 'APPROVED';
        if (r.specification.current.state === 'IN_REVIEW') r.specification.current.state = 'APPROVED';
        if (r.gherkin.state === 'IN_REVIEW') r.gherkin.state = 'APPROVED';
      }
      return;
    }
    case 'reviewing': {
      lb.detail.state = 'REVIEWING';
      lb.detail.execution_status = 'running';
      return;
    }
    case 'dup-slug': {
      const copy = JSON.parse(JSON.stringify(lb)) as RunData;
      copy.detail.project = 'payroll';
      copy.detail.repos = [{ id: 'payroll-api', baseline_sha: 'abc1234', branch: 'sentinel/leave-payroll', final_sha: null }];
      db.runs['payroll/leave-balance'] = copy;
      db.projectData.payroll.runs.unshift(summary(copy.detail));
      return;
    }
    case 'fresh-with-project': {
      db.projects = [{ id: 'digital-hr', name: 'digital-hr', path: '/ws/digital-hr', status: 'available', reason: null, active_runs: 0 }];
      const data = digitalHrData([]);
      data.readiness.default = {
        state: 'needs_configuration', workflow: null, checked_at: '2026-11-14T09:00:00Z',
        items: [{ id: 'test_command', status: 'not_configured', repo: 'backend', message: 'no test command', fix: 'set repos.backend.commands.test' }],
      };
      data.repositories.items = [repo('backend', {}), repo('frontend', {})];
      db.projectData['digital-hr'] = data;
      db.runtime.projects = ['digital-hr'];
      return;
    }
    default:
      throw new Error(`unknown preset ${name}`);
  }
}
