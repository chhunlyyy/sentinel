# Implementation Status: Sentinel 1.1.0

Tracks real progress with evidence only. Plan: `plan/v1.1/IMPLEMENTATION_PLAN.md`. Spec: `SPEC.md`. Phase order reordered at G0 (decision B9): core engine before dashboard, all in 1.1.0 (decision B1).

Baseline: 0.1.0b7, commit `aa1481c`, `python3 sentinel/scripts/selftest.py` gives 95 passed, 0 failed (2026-11-14).

| ID | Phase | Task | Status | Dependencies | Evidence |
|---|---|---|---|---|---|
| P0-01 | Discovery | Inspect architecture | Completed | none | `plan/v1.1/phase0/CURRENT_ARCHITECTURE.md` |
| P0-02 | Discovery | Gap analysis, dependencies, risks | Completed | P0-01 | `plan/v1.1/phase0/GAP_ANALYSIS.md`, `DEPENDENCY_ANALYSIS.md`, `IMPLEMENTATION_RISKS.md` |
| G0 | Gate | Discovery approval | Completed | P0-02 | `plan/v1.1/phase0/DECISIONS.md` (approved 2026-11-14 with changes) |
| P1-01 | Architecture | Unified `SPEC.md` | Completed | G0 | `SPEC.md` |
| P1-02 | Architecture | Architecture and contract documents | Completed | P1-01 | `docs/architecture/*.md`, `docs/contracts/*.md` |
| G1 | Gate | Spec, architecture, data model, API contracts | Completed | P1-01, P1-02 | approved 2026-11-14; Q1 React + Vite, Q2 queue for AI tool, Q4 paths as planned |
| PA-00 | Core | Phase A Gherkin (test plan) | Completed | G1 | approved 2026-11-14 at hash `c6409820adf6b0b146d185c9e164edb514197ffea48476c75acb1e87fec45816`, `plan/v1.1/phaseA/features/*.feature` |
| PA-01 | Core | Schemas, registry, migrations, legacy indexing | Completed | PA-00 | `registry.py`, `migrations/0001_init.sql`, `tests/test_registry.py` |
| PA-02 | Core | Run, task, approval, cycle state machines; acceptance split | Completed | PA-01 | `machines.py`, `engine.py`, `tests/test_machines.py`, `tests/test_engine.py`, `tests/test_cli.py` |
| PA-03 | Core | Publish default off; doctor note | Completed | PA-00 | template + schema default false; doctor note; selftest AC-C-35a/b/c |
| PB-00 | Gates | Phase B Gherkin (test plan) | Completed | PA review | approved 2026-11-14 at hash `aca8bae64794fb4fe5e986a818f9a8279bb779950849aa644e07231381fa9278`, `plan/v1.1/phaseB/features/*.feature` |
| PB-01 | Gates | Spec and Gherkin artifacts, validators, coverage table | Completed | PA-02 | `artifacts.py`, `tests/test_artifacts.py` |
| PB-02 | Gates | Review and approve (TTY), hashing, invalidation | Completed | PB-01 | `engine.py` approvals and detection, `sentinel review/approve/submit`, `migrations/0002_audit_reason.sql`, `tests/test_approvals.py`, `tests/test_review_cli.py`, `tests/test_adapters_sync.py` |
| PC-00 | Runtime | Phase C Gherkin (test plan) | Completed | PB review | approved 2026-11-14 at hash `dbccd512de4c60e8d149ab172ad62ddda002dcb3561a027f57fc07a5de9369fa`, `plan/v1.1/phaseC/features/*.feature` |
| PC-01 | Runtime | Task and result contracts; adapter interface | Completed | PA-02 | `tasks.py`, `adapters.py`, schemas, `migrations/0003_task_runtime.sql`, `tests/test_task_contracts.py`, `tests/test_adapter_interface.py`, `tests/test_tasks_engine.py` |
| PC-02 | Runtime | CLI adapter (from run_stage), native adapter, scheduler, retries, cancel | Completed | PC-01 | `runtime.py`, `scheduler.py`, `run_stage.py` LiveProcess, `sentinel next`/`task run`/`task complete`, `tests/test_cli_adapter.py`, `test_native_adapter.py`, `test_scheduler.py`, `test_retries_cancel.py`, `test_next_cli.py`, `test_review_fixes.py` |
| PD-00 | TDD | Phase D Gherkin (test plan) | Completed | PC review | approved 2026-11-14 at hash `3bb67c8c68cd911c7281b5cd2407d92b4f787274ead20d6f457a729031126441`, `plan/v1.1/phaseD/features/*.feature` |
| PD-01 | TDD | Path-level scopes; test and production globs in profiles | Completed | PC-02 | auto-approved (delegated); `scopes.py`, `boundary.py`, `migrations/0004_write_scopes.sql`, profiles, `tests/test_write_scopes.py` |
| PD-02 | TDD | test_designer, tdd_red, tdd_green, tdd_refactor stages; failure classifier; cycle evidence | Completed | PD-01, PB-02 | auto-approved (delegated); `cycles.py`, `classifier.py`, `binding.py`, `testsel.py`, stage templates, migrations 0005, 0006, 0008, tests `test_tdd_stages`, `test_cycle_planning`, `test_red_phase`, `test_green_refactor`, `test_cycle_evidence_trace`, `test_cycle_flow`, `test_phase_d_review` |
| PE-00 | Verification | Phase E Gherkin (test plan) | Completed | PD review | approved 2026-11-14 at hash `dcbf28683ff5331af8e645ba4afb7c1e4f6437dab626d26a3d1785e03d320958`, `plan/v1.1/phaseE/features/*.feature` |
| PE-01 | Verification | Verification runner, acceptance, reports, export and import | Completed | PD-02 | auto-approved (delegated); `verify.py`, `review.py`, `accept.py`, `bundle.py`, `util.py`, `migrations/0009_verification.sql`, tests `test_verification_*`, `test_review_qa`, `test_acceptance`, `test_reports`, `test_export_import`, `test_review_fixes_e` |
| PE-02 | Skills | Rewrite orchestrator skill around `sentinel next`; regenerate adapters | Completed | PE-01 | auto-approved (delegated); `skills/sentinel/SKILL.md`, `pipeline.md`, resume/status skills, AGENTS block, `tests/test_orchestrator_skill.py` |
| PF-00 | Local API | Phase F Gherkin (test plan) | Completed | PE review | approved 2026-11-14 at hash `5ef93cdedf89f47d667c41d18e964070b18fbb79b5ddb8274a002d019865dfbc`, `plan/v1.1/phaseF/features/*.feature` |
| PF-01 | Local API | Server, auth, allow-listed operations, SSE | Completed (acceptance endpoints wired after PE-01) | PE-01 | auto-approved (delegated); `sentinel/scripts/apiserver/`, `controls.py`, `migrations/0007_phase_f_api.sql`, `tests/test_server_*.py`, `tests/test_security_review_f.py`, `tests/test_merge_df.py` |
| PG-00 | Dashboard | Phase G Gherkin (test plan) | Completed | PF review | approved 2026-11-14 at hash `1d27ec935a4ef85ae51e33eca9f968423640e4d831b10912560ffc5b0299b257`, `plan/v1.1/phaseG/features/*.feature` |
| PG-01 | Dashboard | Installation, projects, repos, configuration center, readiness | Completed | PF-01 | auto-approved (delegated); `dashboard/`, `apiserver/readroutes.py`, `health.py`, `tests/test_server_read_routes.py`, `tests/test_dashboard_fixtures.py` |
| PG-02 | Dashboard | Tasks, approval center, monitoring, TDD, verification, diffs, trace | Completed | PG-01 | auto-approved (delegated); `dashboard/` screens, e2e and unit tests |
| PH-00 | Release | Phase H Gherkin (test plan) | Completed | PG review | approved 2026-11-14 at hash `d61984bef91e27725b81c9d4723e298e7a5e2b94716e246c11b6b8d54e994012`, `plan/v1.1/phaseH/features/*.feature` |
| PH-01 | Release | Notifications, analytics, audit, security tests, docs, version 1.1.0 | Pending | PG-02 | |

## Phase A notes

- Architecture decision A-1 (2026-11-14): `sentinel run new` creates a version 2 run unless `--legacy`, `--tier` or `--adhoc` is given; those create a 0.1 run as before. Keeps the 0.1 skill and the 95 selftest checks working until Phase E rewrites the skill. Both kinds are listed in the registry.
- Work split across subagents: Sonnet implements (registry; state machines; engine and CLI integration), Opus reviews the phase.
- Evidence 2026-11-14: Red recorded per agent (registry 14 errors, machines 198 errors, engine 14 errors, review regressions 11 failures + 3 errors). Green: `python3 -m unittest discover -s tests` 81 tests OK; `python3 sentinel/scripts/selftest.py` 115 passed, 0 failed (95 baseline, one check flipped for C-35). Concurrency repro scripts: 0/20 failures for fresh-db open and legacy indexing.
- Opus review found 17 issues (1 blocker, 4 major, 12 minor); all fixed with regression tests. Phase A Gherkin hash unchanged (`c6409820…`).
- Behavior changes to note: configs without `auto_sync_push` now mean off; `resume` and `run update` refuse version 2 runs (exit 5); legacy indexer maps stopped/abandoned to cancelled/rejected; `run finish` on v2 runs is treated as human without TTY proof until Phase B.
- Phase A accepted by human review 2026-11-14.

## Phase B notes

- Evidence 2026-11-14: Red recorded (artifacts 112 errors; approvals 74 errors; review CLI 4 failures + 28 errors; review regressions 8 failures). Green: unittest 232 OK; selftest 140 passed, 0 failed. Phase B Gherkin hash unchanged (`aca8bae6…`).
- Opus review: 2 major (integrity failure during detection bricked the run; resume skipped re-detection), 9 minor; all fixed with regression tests.
- Behavior to note: `run finish` on v2 runs needs a TTY; `sync-adapters` adds advisory deny rules for `sentinel approve`/`accept` to `.claude/settings.json`; migration 0002 adds `audit.reason`; invalid edited specs are not stored (approve refused E_VALIDATION), edited Gherkin sets are stored even if invalid (AC-GHA-05i); a Gherkin edit while BLOCKED/NEEDS_HUMAN is detected on resume.
- Phase B accepted by human review 2026-11-14. Phase C Gherkin approved, including open point 2 (missing runner -> BLOCKED, overriding agent-runtime.md "else FAILED").
- Phase F Gherkin approved 2026-11-14. Decision: dashboard `pause` and "request intervention" controls are dropped from 1.1.0 (no paused state); the API keeps refusing them. No Phase G addendum.

## Phase C notes

- Evidence 2026-11-14: Red recorded (PC-01: 39+21 errors, 1 failure + 9 errors; PC-02: 89 failures + 22 errors; review fixes red for items 1-3, 5-9, 14). Green: `python3 -W default -m unittest discover -s tests` 366 OK in 65 s, no ResourceWarnings, no leaked processes; selftest 151 passed, 0 failed. Phase C Gherkin hash unchanged (`dbccd512…`).
- Opus review: 2 blockers (agent could bypass the scope check by deleting or editing before.json / task.sealed.json), 6 major (false process-lost, stage run hang regression, group children surviving cancel, glob false negative, exponential overlap, config schema rejecting documented keys), 8 minor; all fixed. Tampering with task files now yields E_INTEGRITY and NEEDS_HUMAN.
- Behaviour to note: `sentinel submit` removed (use `task run` / `task complete`); `stage run` refused on v2 runs; cancel may block the caller up to 10 s; missing runner -> run BLOCKED.
- Phase C accepted by human review 2026-11-14.
- Phase G Gherkin approved 2026-11-14 with decision G-1: in 1.1.0 the dashboard shows projects, repos and configuration read-only and points to the CLI command or file for changes; mutating routes (project register, repo changes, config save/restore/import, provider tests, publish) move to a later release. Affected SPEC rows (parts of DSH-02, PRJ, REP, CFG, PRV, AGT-08) to be marked LATER in Phase H docs; DSH-07 (accessibility) and SEC-09 (XSS) to be added to SPEC.md.
- Phase H Gherkin approved 2026-11-14 as drafted: G-1 LATER list accepted (1.1.0 ships without dashboard project creation/config editing, VIS-07 deferred); pyproject classifier stays Beta; audit hash chain with `sentinel audit verify`; release gate requires every AC id A-H in a passing test name; metric definitions as in the Phase H README.
- 2026-11-14: the user delegated approval while away. From Phase D onward, phase reviews are approved by the orchestrating session after the Opus review findings are fixed and all tests pass; each auto-approval is marked "auto-approved (delegated)". Commits and pushes to `v1.1-core` carry no co-author lines.

## Phase D notes

- Evidence 2026-11-15: Red recorded for PD-01 (module missing), PD-02b (per feature) and review fixes (55 failures/errors); PD-02a recorded no RED, so the Opus review mutation-tested it (13 of 15 mutants killed, 2 equivalent). Green: unittest 526 OK in 111 s; selftest 164 passed, 0 failed. Phase D Gherkin hash unchanged (`3bb67c8c…`).
- Opus review: 1 blocker (Green could write test files/conftest when globs overlap), 7 major (skipped tests passed, rest-unchanged not enforced with real runners, shipped profile commands unusable, ignore-rule hiding, renamed Rule deadlock, E_SCOPE dead end, Phase F retry not cycle-aware), 7 minor; all fixed except the optional cycles.py split.
- Migration renumbered: Phase D review migration is `0008_cycle_review.sql` (Phase F owns 0007). Phase E takes 0009, Phase H 0010.
- Known limits: flutter `tojunit` path untested offline; selector values must be quoted in profile templates (names with quotes/backslashes refused); cancelling a cycle task does not queue a retry by itself (Phase F ControlOps must call `retry_cycle_task`).
- Phase D auto-approved (delegated) 2026-11-15.

## Phase F notes

- Built in worktree branch `v1.1-phase-f` (322dd51, fixes 23c6721), merged into `v1.1-core` 2026-11-15.
- Evidence: RED 36 failures + 128 errors before server code; review-fix tests red first. Merged tree: unittest 720 OK (3 skipped: dashboard acceptance waits for Phase E `accept`), selftest 180 passed, 0 failed.
- Opus security review: 4 major (unscrubbed cross-project audit, tier floor override, migration gap, token in browser argv), 7 minor/nit; all fixed. Migration runner now records applied versions and fills gaps.
- Merge integration: ControlOps retry/cancel of TDD cycle tasks go through Phase D cycle hooks.
- Residual: scrubber is quadratic on very long strings (mitigated by 8 KiB log-line cut).
- Phase F auto-approved (delegated) 2026-11-15.

## Phase G notes

- 2026-11-15: UI built (React 19, Vite 7, Vitest, Playwright), Opus review found contract drift with the real Phase F server (3 white-screen crashes), missing server read routes and fixtures recorded by hand. Fixes: 8 Phase G GET routes (`apiserver/readroutes.py`, `health.py` shared with `doctor`), fixtures recorded from the real server (AC-DSH-06i), UI adapted to server shapes, error boundary, a11y fixes, build output to `sentinel/dashboard_dist` (git-ignored, built at release, shipped as wheel artifact).
- Evidence: unittest 742 OK (4 skipped), selftest 187 passed; dashboard lint clean, vitest 54 passed, Playwright 198 passed, 1 skipped (AC-DSH-06g needs user namespaces).
- OPEN until Phase E merges: AC-VER-04o (already rejected) removed and AC-VER-04n/03g weakened because the server had no acceptance record; must be restored to the approved scenarios after Phase E. Wheel/release ACs (OPS-01b/c/e/f, DSH-06h, TST-01i/j) are Phase H. Phase G not yet approved.

## Phase E notes

- 2026-11-15: PE-01 built on worktree branch `v1.1-phase-e` (22067f8). Opus review: 2 blockers (stale evidence accepted; import could inject rows into other runs, e.g. a forged security approval), 7 major (report.json hash not checked against artifact, tier 4 security gate never requested, tier-raise blocker never routed, agent/skill files missing from scope check, command checks ran before scope check, verify/task-run lock one-way, audit action wording), minors. Mutation check: 24 of 25 mutants killed. Fixes in progress.
- PENDING HUMAN CONFIRMATION: approved Gherkin conflict on the acceptance audit action. Phase F AC-VER-04k says `accepted`/`rejected`; Phase E AC-VER-04a says `acceptance`. Orchestrator chose Phase F wording (one row, action `accepted` or `rejected`); Phase E AC-VER-04a wording needs the user's confirmation (a `.feature` change would change the Phase E hash).
- PE-02 (skill rewrite around `sentinel next`): built in main tree, uncommitted; 14 tests red first (22 subtest failures) then green; selftest check "every sentinel command a skill mentions exists" waits for the PE-01 merge; ARC-03n/03o end-to-end tests wait for PE-01.
- 2026-11-15: PE-01 review fixes (d046d60): all 16 findings fixed, 25 of 25 mutants killed. Merged into v1.1-core with PE-02 and Phase G; Phase G acceptance scenarios AC-VER-04n/04o/03g restored to approved wording; dashboard fixtures test no longer rewrites the repo (record with SENTINEL_RECORD_FIXTURES=1). Skill: native step runs `task run` first when no prompt yet.
- Evidence (merged tree): unittest 895 OK (1 skipped), selftest 196 passed, dashboard lint clean, vitest 54, playwright 199 passed (1 skipped: AC-DSH-06g needs user namespaces).
- Phases E and G auto-approved (delegated) 2026-11-15. Still pending the user's confirmation: acceptance audit action wording (Phase F `accepted`/`rejected` used; Phase E AC-VER-04a says `acceptance`).

## Phase H notes

- Part A (notifications + analytics), main tree: Opus review 3 major (clip-before-scrub secret leak, concurrent user.db writes, read-only URI not escaped), minors, 6 surviving mutants; all fixed, all listed mutants killed. Lead time counts COMPLETED and FAILED runs, not CANCELLED (the approved analytics.feature fixture overrides the orchestrator's COMPLETED-only choice). `sentinel notifications read` denied to agents (E_ACTOR in task processes). Scrubber gained a GitHub token pattern.
- Evidence part A: unittest 962 OK (1 skipped), selftest 213 passed, dashboard lint clean, vitest 98, playwright 214 (1 skipped). Process slips: some fixes written before their tests; mutation runs confirm the tests fail on old behaviour.
- Part B (audit chain, export, backup/restore, security suite): worktree branch `v1.1-phase-h-b` (6a62c81, fixes 0df9d82). Opus review 6 major (restore impossible with broken chain, non-text audit values broke the chain, verify --file missed deleted rows, imported rows looked native, restore swap could lose writes, live logs unscrubbed) plus minors; all fixed; 15 of 16 mutants killed (1 equivalent). Merged into v1.1-core with security rows for notifications added.
- Evidence merged tree: unittest 1040 OK (1 skipped, includes tests/security), selftest 221 passed, vitest 98, playwright 214 (1 skipped).
- Parts A and B auto-approved (delegated). Remaining: Phase H part C (docs, SPEC LATER marks, release gate, version 1.1.0).
