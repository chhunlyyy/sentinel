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
| PC-01 | Runtime | Task and result contracts; adapter interface | In Progress | PA-02 | |
| PC-02 | Runtime | CLI adapter (from run_stage), native adapter, scheduler, retries, cancel | Pending | PC-01 | |
| PD-01 | TDD | Path-level scopes; test and production globs in profiles | Pending | PC-02 | |
| PD-02 | TDD | test_designer, tdd_red, tdd_green, tdd_refactor stages; failure classifier; cycle evidence | Pending | PD-01, PB-02 | |
| PE-01 | Verification | Verification runner, acceptance, reports, export and import | Pending | PD-02 | |
| PE-02 | Skills | Rewrite orchestrator skill around `sentinel next`; regenerate adapters | Pending | PE-01 | |
| PF-01 | Local API | Server, auth, allow-listed operations, SSE | Pending | PE-01 | |
| PG-01 | Dashboard | Installation, projects, repos, configuration center, readiness | Pending | PF-01 | |
| PG-02 | Dashboard | Tasks, approval center, monitoring, TDD, verification, diffs, trace | Pending | PG-01 | |
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
