# Configuration and Document Schemas (1.1.0, draft for G1)

All schemas are JSON Schema 2020-12 files under `sentinel/core/schema/`, validated with the existing `jsonschema` dependency.

## 1. `sentinel.config.yaml` additions (all optional)

Existing keys are unchanged. New top-level keys:

```yaml
policies:
  human_required:            # added to the mandatory spec and Gherkin gates; cannot remove them
    - security_gate          # tier 4 or auth/permission change
    - destructive_migration
    - real_data_clone
    - publish
    - pull_request
  max_parallel_tasks: 1
  task_timeout_seconds: 5400
  provider_retries: 1
  redact_env: [DATABASE_URL]

tdd:
  enabled: true              # false only for docs-only projects; ignored for code task types
  red_retries: 2
  green_retries: 3
  refactor_retries: 2

verification:                # per-check on/off and extra commands; defaults by tier
  mutation: tier4
  migration_check: auto
  extra: []                  # reuses the existing extra_checks shape

providers:
  default: claude
  fallback: [codex]
  disabled: []

agents:                      # role -> provider/model; same resolution as `routing`
  tdd_green: {runner: codex, model: gpt-5}
  reviewer:  {runner: claude, model: opus}

notifications:
  desktop: true

limits:                      # existing block, new keys
  red_retries: 2
```

Profiles (`sentinel/profiles/*.json`) gain:

```json
{
  "test_globs": ["src/test/**", "**/*Test.java"],
  "production_globs": ["src/main/**"],
  "test_report": {"kind": "junit-xml", "path": "build/test-results/test/*.xml"},
  "targeted_test": "./gradlew test --tests {tests}",
  "failure_patterns": {"compile": ["error: cannot find symbol"], "environment": ["Connection refused"], "missing_dependency": ["Could not resolve"]}
}
```

Repos may override any of these (`repos[].test_globs`, ...).

Template change: `state.auto_sync_push: false` for new configs (existing configs keep their value).

## 2. Spec document (`specs/<slug>/spec.md`)

Markdown with fixed `##` headings. Validated by section presence and ID rules, not by JSON Schema.

Full (tier 3 and 4): Problem statement, Objectives, Scope, Out of scope, Functional requirements, Non-functional requirements, Acceptance criteria, Business rules, Edge cases, Validation rules, Security considerations, API or interface changes, Database changes, Dependencies, Risks and assumptions, Expected deliverables.

Lite (tier 1 and 2): Problem statement, Scope, Out of scope, Functional requirements, Acceptance criteria, Edge cases, Security considerations, Risks and assumptions.

Docs-only: Problem statement, Scope, Expected deliverables.

ID rules: requirements `REQ-<n>`, criteria `AC-<n>` each followed by `(REQ-<n>[, REQ-<m>])`. IDs unique. Front matter:

```yaml
---
run: leave-balance
version: 3
tier: 3
---
```

## 3. Gherkin (`specs/<slug>/features/*.feature`)

```gherkin
@REQ-2
Feature: Leave balance on the request form

  Rule: The balance shown is the remaining annual leave

    @AC-3 @integration @P1
    Scenario: Employee sees remaining days
      Given an employee with 12 days of annual leave and 4 days taken
      When they open the leave request form
      Then the form shows "8 days remaining"

    @AC-4 @unit @P2
    Scenario Outline: Balance never goes below zero
      Given an employee with <entitled> days entitled and <taken> taken
      When the balance is calculated
      Then the balance is <balance>
      Examples:
        | entitled | taken | balance |
        | 10       | 10    | 0       |
        | 10       | 12    | 0       |
```

Rules: every Scenario has at least one `@AC-n` (inherited `@REQ` allowed from Feature or Rule), one type tag, one priority tag. Coverage tags (optional, used by the coverage table): `@cov-invalid-input`, `@cov-authz`, ... one per C 4.2 category. A category marked not applicable is listed in the spec's Edge cases section with a reason.

## 4. `task-v1` (summary)

Required: `schema`, `id`, `run_id`, `role`, `objective`, `input`, `repos`, `permissions.read`, `permissions.write`, `constraints.timeout_seconds`, `expected_output.schema`. Optional: `provider`, `permissions.readonly_approved`, `constraints.max_retries`, `constraints.must_follow_tdd`. `role` enum: specifier, test_designer, tdd_red, tdd_green, tdd_refactor, repro, hardener, reviewer, qa, promotion, docs, rollout, retrospective. Full example: `docs/architecture/agent-runtime.md`.

## 5. `agent-result-v1`

```json
{
  "schema": "agent-result-v1",
  "task_id": "t-0007",
  "status": "completed | blocked | failed",
  "summary": "one paragraph",
  "claimed_changed_files": ["backend/src/main/java/leave/LeaveBalance.java"],
  "claimed_commands": [{"command": "./gradlew test --tests LeaveBalanceTest", "exit_code": 0}],
  "findings": [{"severity": "blocker|major|minor", "location": "path:line", "text": "..."}],
  "questions": [],
  "out_of_lane": [],
  "new_dependencies": [{"name": "...", "reason": "..."}],
  "rollout": []
}
```

Required: `schema`, `task_id`, `status`, `summary`. Claims are recorded and compared with engine evidence; they never decide anything.

## 6. Evidence record (stored, not written by agents)

`kind`, `command`, `cwd`, `exit_code`, `classification`, `passed`, `failed`, `skipped`, `output_sha256`, `started_at`, `finished_at`, `env` (`{"python": "...", "os": "...", "tool_versions": {...}}`), `repo_sha` (working tree reference: HEAD plus diff digest).

## 7. Run report (`runs/<slug>/report.json`, `report.md`)

Sections: execution summary, approved spec (version, hash), approved Gherkin (version, hash), agent history (tasks with provider, model, timings), TDD cycles, verification, regression, review findings, changed files, acceptance (computed and human), cost and duration (missing values marked). The Markdown file is rendered from the JSON.
