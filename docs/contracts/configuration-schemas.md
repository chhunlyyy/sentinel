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

factory:                     # Sentinel 2.0+
  driver: engine
  max_tasks_per_project: 2
  max_agents: 4
  budget:
    tokens_per_day: 1000000
    usd_per_day: 20.0

limits:                      # existing block, new keys
  red_retries: 2
```

Profiles (`sentinel/profiles/*.json`) gain (shown for `spring-gradle` and `python`):

```json
{
  "test_globs": ["src/test/**", "**/*Test.java"],
  "production_globs": ["src/main/**"],
  "test_infra_globs": ["build.gradle*", "settings.gradle*", "**/build.gradle*", "gradle.properties"],
  "test_report": {"kind": "junit-xml", "path": "build/test-results/test/*.xml"},
  "targeted_test": "./gradlew test {selectors}",
  "selector": "--tests '*{test}'",
  "selector_join": " ",
  "summary_patterns": ["(?P<passed>\\d+) passed", "(?P<failed>\\d+) failed"],
  "failure_patterns": {"compile": ["error: cannot find symbol"], "environment": ["Connection refused"], "missing_dependency": ["Could not resolve"]}
}
```

```json
{
  "test_report": {"kind": "junit-xml", "path": "{report_dir}/junit.xml"},
  "targeted_test": "pytest -p no:cacheprovider --junitxml={report_dir}/junit.xml {selectors}",
  "selector": "'{node}'"
}
```

Repos may override any of these (`repos[].test_globs`, `repos[].production_globs`, `repos[].selector`, ...), key by key. Globs are repo-relative, `/` separated, case-sensitive; `*` stays in a segment, `**` spans segments; absolute paths and `..` are refused. A path matching both lists is a test file. The `generic` profile ships without globs: a repo using it must set both lists before execution starts (otherwise the run goes to NEEDS_HUMAN with "repo <id> has no test_globs").

- `test_infra_globs` (optional) name test runner configuration and hooks (`conftest.py`, `pytest.ini`, `jest.config.*`, `build.gradle*`, ...). Green and Refactor may not change a path that matches it, or any path that is a test file under `test_globs`, even when `production_globs` also matches it: such a change is `outside_write_scope`.
- `targeted_test` is a template. `{tests}` is the test ids (`Class.method`), shell-quoted. `{selectors}` is one selector per id, joined with `selector_join` (default a space). `{files}` is the distinct test files of the ids. `{report_dir}` is a fresh directory owned by the engine, removed after the run. A selector is the profile's `selector` template over `{test}`, `{file}` (repo-relative), `{class}`, `{method}`, `{node}` (`file::class::method`, class omitted when the file declares none) and `{method_re}` (regex-escaped method). Placeholder values are put in raw, so templates quote them (`'{node}'`); a name with a quote, backslash or control character is refused. Shipped selectors: pytest node ids, Gradle `--tests` once per id, Jest `-t` with `a|b` over method names plus the test files, Flutter `--name` with `a|b`.
- `test_report.path` starting with `{report_dir}` is read from the engine-owned directory (an agent cannot pre-write it). Any other path is repo-relative: it is cleared before the run and only a file newer than the run start counts. A path that is absolute or has a `..` segment is refused, and a file whose real path leaves its base directory is ignored. Gradle writes to a fixed path, so `spring-gradle` keeps `build/test-results/test/*.xml`. Jest needs the `jest-junit` package (the profile sets `JEST_JUNIT_OUTPUT_DIR`, `JEST_JUNIT_CLASSNAME={filename}`); Flutter pipes `flutter test --machine` through `tojunit` (package `junitreport`), which must be installed, and the pipeline exit code is `tojunit`'s, so the report decides.
- `summary_patterns` (optional) is a list of regexes with the named groups `passed`, `failed` or `skipped`. The last match of each in the output is compared with the counts of the report; a mismatch classifies the run `unknown` (NEEDS_HUMAN) instead of trusting the report.
- The classifier reads the assertion pattern against each `<error>` message (the message attribute and element text), not against the whole output.
- Related tests: Red, Green and Refactor run their own tests and the tests of every accepted cycle of the repo; each related test must be present and pass (or fail only as it did at baseline). A skipped test is never a pass.

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

Required: `schema`, `id`, `run_id`, `role`, `objective`, `input`, `repos`, `permissions.read`, `permissions.write`, `constraints.timeout_seconds`, `expected_output.schema`. Optional: `provider`, `permissions.readonly_approved`, `constraints.max_retries`, `constraints.must_follow_tdd`. `role` enum: specifier, test_designer, tdd_red, qa_red, tdd_green, tdd_refactor, repro, hardener, reviewer, qa, promotion, docs, rollout, retrospective. Full example: `docs/architecture/agent-runtime.md`.

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
