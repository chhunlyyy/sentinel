import type {
  DetectItem,
  KnowledgeCiTemplateResult,
  KnowledgeRecord,
  KnowledgeRelatedResult,
  KnowledgeRelatedInvariant,
  KnowledgeStatus,
  KnowledgeUsed,
  RoutingSuggestResult,
  ConfigFormResult,
} from '../src/api/types.ts';

export const SAMPLE_KNOWLEDGE_RECORDS: KnowledgeRecord[] = [
  {
    key: 'run-employee-search',
    repo: 'backend',
    provenance: 'verified',
    title: 'Employee search by ID',
    summary: 'Adds /employees/search with exact ID match; HR and managers only.',
    reached: 'backend · develop Nov 19 → main Nov 20',
    files: ['src/main/EmployeeController.java', 'src/main/EmployeeService.java'],
    date: '2026-11-20T14:32:00Z',
    path: 'changes/run-employee-search.md',
    body: `# Employee search by ID\n\nVerified from run-employee-search.\n\n## Changes\n- Adds endpoint GET /employees/search?id={id}\n- Authorization check: HR and manager roles only\n- Fast indexed lookup on primary employee ID\n\n## Decisions\n- No fuzzy match on employee ID to prevent accidental data disclosure\n- Audit log entry created for every cross-department search`,
  },
  {
    key: 'pr-231',
    repo: 'backend',
    provenance: 'inferred',
    title: 'Bump Spring Boot to 3.4',
    summary: 'Dependency update; no behavior change found in the diff.',
    reached: 'backend · develop Nov 18',
    files: ['build.gradle', 'gradle/libs.versions.toml'],
    date: '2026-11-18T10:15:00Z',
    path: 'changes/pr-231.md',
    body: `# Bump Spring Boot to 3.4\n\nInferred from git merge commit pr-231.\n\n## Summary\nUpgraded org.springframework.boot plugin and dependencies from 3.3.4 to 3.4.0.\nAll automated regression tests passed cleanly.`,
  },
  {
    key: 'pr-228',
    repo: 'frontend',
    provenance: 'inferred',
    title: 'Leave screen paging',
    summary: 'Server-side paging for the leave list, 50 per page.',
    reached: 'frontend · develop Nov 15',
    files: ['src/components/LeaveList.tsx', 'src/api/leave.ts'],
    date: '2026-11-15T09:00:00Z',
    path: 'changes/pr-228.md',
    body: `# Leave screen paging\n\nInferred from git merge commit pr-228.\n\n## Summary\nIntroduced cursor-based pagination for employee leave records.\nPage size fixed at 50 records per page.`,
  },
  {
    key: 'p-9c1e0a77b2d4',
    repo: 'backend',
    provenance: 'inferred',
    title: 'Hotfix: payslip PDF font',
    summary: 'Direct commit on main; embeds the Khmer font in payslip PDFs.',
    reached: 'backend · main Nov 12',
    files: ['src/main/PdfService.java', 'src/resources/fonts/khmer.ttf'],
    date: '2026-11-12T16:45:00Z',
    path: 'changes/p-9c1e0a77b2d4.md',
    body: `# Hotfix: payslip PDF font\n\nDirect commit on main.\n\n## Summary\nBundled unicode Khmer font to resolve rendering issues in generated payslip PDFs for regional employees.`,
  },
  {
    key: 'pr-212',
    repo: 'backend',
    provenance: 'inferred',
    title: 'Leave balance API',
    summary: 'GET /leave/balance per employee; used by the dashboard widget.',
    reached: 'backend · develop Oct 30 → main Nov 3',
    files: ['src/main/LeaveController.java', 'src/main/LeaveService.java'],
    date: '2026-11-03T11:20:00Z',
    path: 'changes/pr-212.md',
    body: `# Leave balance API\n\nInferred from PR #212.\n\n## Summary\nProvides GET /leave/balance endpoint returning annual leave, sick leave, and compensatory days remaining.`,
  },
];

export function sampleKnowledgeRelated(q = '', limit = 5): KnowledgeRelatedResult {
  const words = q.split(/\s+/).filter(Boolean).map((w) => w.toLowerCase());
  let records = [...SAMPLE_KNOWLEDGE_RECORDS];
  if (q) {
    const matched = records.filter((r) => {
      const text = `${r.key} ${r.title ?? ''} ${r.summary ?? ''} ${r.repo ?? ''}`.toLowerCase();
      return text.includes(q.toLowerCase()) || words.some((w) => text.includes(w));
    });
    records = matched.length > 0 ? matched : [SAMPLE_KNOWLEDGE_RECORDS[4], SAMPLE_KNOWLEDGE_RECORDS[0]];
  }
  const sampleInvariants: KnowledgeRelatedInvariant[] = [
    { id: 'INV-HR-1', rule: 'HR data only for role HR', text: 'HR data only for role HR', path: 'invariants.md' },
    { id: 'INV-PAYROLL-1', rule: 'Round once on the final net amount', text: 'Round once on the final net amount', path: 'invariants.md' },
  ];
  let invariants = sampleInvariants;
  if (q) {
    const matched = sampleInvariants.filter((inv) => {
      const text = `${inv.id ?? ''} ${inv.rule ?? ''} ${inv.text ?? ''}`.toLowerCase();
      return text.includes(q.toLowerCase()) || words.some((w) => text.includes(w));
    });
    if (matched.length > 0) invariants = matched;
  }
  return {
    invariants: invariants.slice(0, limit),
    records: records.slice(0, limit).map((r) => ({
      date: r.date,
      key: r.key,
      path: r.path,
      repo: r.repo,
      summary: r.summary,
      title: r.title,
    })),
  };
}

export function sampleKnowledgeUsed(): KnowledgeUsed {
  return {
    invariants: [
      {
        id: 'INV-HR-1',
        path: 'invariants.md',
        rule: 'HR data only for role HR',
        text: 'HR data only for role HR',
      },
    ],
    records: [
      {
        date: '2026-11-03T11:20:00Z',
        key: 'pr-212',
        path: 'changes/pr-212.md',
        repo: 'backend',
        summary: 'GET /leave/balance per employee; used by the dashboard widget.',
        title: 'Leave balance API',
      },
      {
        date: '2026-11-20T14:32:00Z',
        key: 'run-employee-search',
        path: 'changes/run-employee-search.md',
        repo: 'backend',
        summary: 'Adds /employees/search with exact ID match; HR and managers only.',
        title: 'Employee search by ID',
      },
    ],
    summaries: [
      {
        module: 'src/main',
        path: 'knowledge/repos/backend/modules/src-main.md',
        repo: 'backend',
        text: 'Module src/main handles employee leave calculations and queries.',
      },
    ],
  };
}

export function sampleKnowledgeStatus(): KnowledgeStatus {
  return {
    enabled: true,
    records: { total: 42, active: 40, dropped: 2 },
    cursors: { 'develop': 'c0ffee1234', 'main': 'deadbeef5678' },
    by_repo: { backend: 25, frontend: 17 },
    jobs: { running: 0, queued: 0, failed: 0, last_job: 'harvest run-employee-search' },
    module_summaries: 12,
    tracked_branches: 4,
  };
}

export function sampleKnowledgeCiTemplate(repoId: string): KnowledgeCiTemplateResult {
  return {
    repo: repoId,
    profile: repoId.includes('front') ? 'node' : 'spring-gradle',
    branches: ['develop', 'main'],
    filename: 'sentinel-knowledge-ingest.yml',
    template: `name: Sentinel Knowledge Ingest
on:
  push:
    branches:
      - develop
      - main

jobs:
  ingest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Run Sentinel Knowledge Ingest
        env:
          REPO_ID: ${repoId}
          REPO_PROFILE: ${repoId.includes('front') ? 'node' : 'spring-gradle'}
          TRACKED_BRANCHES: '["develop", "main"]'
          SENTINEL_SHARED_URL: \${{ secrets.SENTINEL_SHARED_URL }}
        run: |
          pip install sentinel-ai
          sentinel knowledge ingest
`,
  };
}

export function sampleRoutingSuggest(): RoutingSuggestResult {
  const allRoles = [
    'triage', 'planner', 'specifier', 'test_designer', 'gherkin', 'coder',
    'tdd_red', 'qa_red', 'tdd_green', 'tdd_refactor', 'reviewer', 'qa',
    'hardener', 'docs', 'retrospective', 'cleaner', 'repro', 'knowledge',
  ];
  const strong = new Set(['specifier', 'coder', 'reviewer', 'tdd_red', 'qa_red', 'tdd_green', 'tdd_refactor', 'hardener', 'cleaner', 'repro']);
  const roles: Record<string, { runner: string; model: string | null }> = {};
  const items: { role: string; runner: string; model: string | null }[] = [];

  for (const r of allRoles) {
    if (strong.has(r)) {
      roles[r] = { runner: 'claude', model: 'claude-sonnet-5-5' };
      items.push({ role: r, runner: 'claude', model: 'claude-sonnet-5-5' });
    } else {
      roles[r] = { runner: 'agy', model: 'gemini-3.8-flash' };
      items.push({ role: r, runner: 'agy', model: 'gemini-3.8-flash' });
    }
  }

  return { roles, items };
}

export function sampleDetect(paths: string[]): DetectItem[] {
  return paths.map((p) => {
    const isNode = p.includes('front') || p.includes('node');
    const isSpring = p.includes('backend') || p.includes('spring') || p.includes('hr');
    const profile = isNode ? 'node' : isSpring ? 'spring-gradle' : 'generic';
    return {
      path: p,
      is_git: true,
      current_branch: 'develop',
      default_branch: 'main',
      local_branches: ['develop', 'main', 'feature/test'],
      profile,
      commands: {
        test: isNode ? 'npm test' : isSpring ? './gradlew test --parallel' : '',
        build: isNode ? 'npm run build' : isSpring ? './gradlew build -x test' : '',
        lint: isNode ? 'npm run lint' : isSpring ? './gradlew spotlessCheck' : '',
        typecheck: isNode ? 'npm run typecheck' : '',
        mutate: '',
      },
      tracked_branches: ['develop', 'main'],
    };
  });
}

export function sampleConfigForm(pid: string): ConfigFormResult {
  return {
    project: pid,
    sha256: 'a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0',
    sections: [
      {
        id: 'factory',
        title: 'Factory',
        fields: [
          { path: 'factory.max_tasks_per_project', type: 'integer', default: 2, value: 2, help: 'Maximum tasks executing concurrently in this project', editable: true },
          { path: 'factory.max_agents', type: 'integer', default: 4, value: 4, help: 'Maximum active agents running across all projects', editable: true },
        ],
      },
      {
        id: 'knowledge',
        title: 'Knowledge',
        fields: [
          { path: 'knowledge.auto_push', type: 'boolean', default: true, value: true, help: 'Publish knowledge records automatically after run completion', editable: true },
          { path: 'knowledge.max_summaries', type: 'integer', default: 300, value: 300, help: 'Summary calls limit per ingest job', editable: true },
          { path: 'knowledge.backfill_months', type: 'integer', default: 3, value: 3, help: 'Default months of git history to scan on backfill', editable: true },
        ],
      },
      {
        id: 'policies',
        title: 'Policies',
        fields: [
          { path: 'policies.agents_never_git', type: 'boolean', default: true, value: true, help: 'Agents are prevented from invoking git directly', editable: true },
          { path: 'policies.no_new_comments', type: 'boolean', default: false, value: false, help: 'Flag new comments as code style violations', editable: true },
          { path: 'policies.security_gate', type: 'boolean', default: true, value: true, help: 'Require explicit security approval on auth changes', editable: true },
        ],
      },
      {
        id: 'limits',
        title: 'Limits',
        fields: [
          { path: 'limits.review_rounds', type: 'integer', default: 2, value: 2, help: 'Maximum automated review rounds before escalating', editable: true },
          { path: 'limits.max_retries', type: 'integer', default: 2, value: 2, help: 'Maximum retries on failed tasks', editable: true },
          { path: 'quality.rigor_default', type: 'string', enum: ['quick', 'standard', 'strict'], default: 'standard', value: 'standard', help: 'Default rigor level for runs', editable: true },
        ],
      },
      {
        id: 'general',
        title: 'General',
        fields: [
          { path: 'single_model', type: 'boolean', default: true, value: true, help: 'Use a single model across all roles', editable: true },
        ],
      },
      {
        id: 'repos',
        title: 'Repositories',
        fields: [
          { path: 'repos.0.path', type: 'string', value: `/home/dev/projects/${pid}/backend`, editable: false, help: 'Repository directory path' },
          { path: 'repos.0.role', type: 'string', value: 'backend', editable: true, help: 'Repository role' },
          { path: 'repos.0.commands.test', type: 'string', default: '', value: './gradlew test --parallel', editable: true, help: 'Test command' },
          { path: 'repos.0.commands.build', type: 'string', default: '', value: './gradlew build -x test', editable: true, help: 'Build command' },
          { path: 'repos.0.commands.lint', type: 'string', default: '', value: './gradlew spotlessCheck', editable: true, help: 'Lint command' },
        ],
      },
    ],
    fields: [],
  };
}
