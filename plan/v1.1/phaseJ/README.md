# Phase J: TDD-09, QA scenarios as Red evidence under `no_permanent_frontend_tests` (Gherkin for review)

Scope (from `SPEC.md` TDD-09, `plan/v1.1/phase0/GAP_ANALYSIS.md` B10, `DECISIONS.md`, Phase E point 20, Phase D line 8): with `rules.no_permanent_frontend_tests` on, a behavior group on a client repo (role `frontend` or `mobile`, the `CLIENT_ROLES` of `render_stage.py`) uses its Gherkin scenarios, run through the QA driver, as the Red evidence. No test file is committed. The engine records the exception. SPEC.md TDD-09 changes from "LATER" to "MUST in 1.1.0" when this set is approved. Also touched: CFG-08 (config snapshot), TDD-03 to TDD-06 (verification, caps, evidence), TRC-01/02, VER-02/03 (claims are not evidence, acceptance reasons), ART-01 (report), SEC-06 (scrubbing), ORC-05 (caps), R12/R13/R17/R18.

Not in Phase J: new dashboard views (existing `tdd` and `verification` answers gain two fields only), a new QA driver, QA at R14 (unchanged), changing the cycle or run state machines, replacing the interim hygiene skip (it stays for test-file cycles; QA-Red cycles never need it).

## Design in brief (against the built code)

1. **R12 picks the method per cycle.** `cycles._plan_cycles` stores `cycles.red_method`: `qa_scenario` when the rule is on and the repo role is in `CLIENT_ROLES`, else `test_file` (and `test_file` for every existing row). The method is read from the run's config snapshot, so a later config edit changes nothing (CFG-08). Docs-only runs have no cycles; 0.1 runs never reach this code.
2. **Red task.** `ensure_cycle_tasks` and `_phase_task` create a task of the new role `qa_red` (stage `sentinel/core/stages/qa_red.md`, adapted from `qa.md`) instead of `tdd_red`. Its scope: write only `.sentinel/cache/qa/tests/current/<slug>/<cycle id>/**`, repo read-only, real-data clone gate (`qa_gate`) applies, `SENTINEL_TASK_ID` set. It writes one automated script per scenario of the group, each reporting a result keyed by the scenario's `@AC` key. Test globs stay forbidden: any file the task or any later task writes in a client repo that classifies as `test` is `E_SCOPE` (`scopes.classify`), and a `tdd_red` task for a QA cycle is refused.
3. **Engine runs the scripts, not the agent.** New optional keys `qa.scenario_run` (a command; placeholders `{scripts}`, `{report}`, `{cycle}`) and `qa.scenario_report` (JUnit XML path under the QA cache folder). `_verify_red` for such a cycle starts the repo's `qa.start_commands` entry, waits for `qa.ports`, runs `qa.scenario_run` through `_run_tests`-style execution (scrubbed output, timeout 1800 s, stored artifact), parses the report with `classifier.parse_junit_cases` and binds results to the group's scenario keys like `binding.bind`.
4. **Failure classes for QA-Red** (new, next to `classifier.CLASSES`): `assertion` (right reason: the failing step is a `Then` step; accepted), `unexpected_pass` (a scenario passes before Green; rejected, retry), `setup_failure` (failure at a `Given` or `When` step or a missing selector; retry), `script_error` (retry), `unbound_scenario` (missing, skipped or foreign scenario key; retry), `flaky` (a failing scenario passes on the engine's single rerun; retry), and the human classes `app_not_running`, `driver_error` (binary or browser missing, timeout) and `unknown` (NEEDS_HUMAN, never an agent retry, because an agent cannot fix the environment). The engine reruns an environment class once itself; only two environment results park the run.
5. **Green and Refactor** keep their roles (`tdd_green`, `tdd_refactor`), scope (production globs only) and cap logic. Their engine verification runs the same scripts through the driver and needs every scenario of the group to pass. The scripts are read-only to them and hashed at Red (`cycles.approved_scripts`, like `approved_tests`); a change or deletion is `E_INTEGRITY` (same path as `_approved_changed`).
6. **Exception record.** (a) cycle field `red_method`; (b) evidence rows of the cycle get `method` (`qa_scenario`) and `exception` JSON `{rule, replaced, by, repo}`, plus the script manifest and per-scenario results; (c) events `tdd.exception_planned` (R12) and `tdd.exception_recorded` (once per cycle, naming the accepted red row); (d) `_evidence_gaps` requires method, scripts, exception and the event before `CYCLE_ACCEPTED`; (e) `accept._acceptance` adds the reason `tdd exception evidence missing: <repo> <cycle>`; (f) `report.json` gets `tdd_exceptions` and `report.md` the section "TDD exceptions" (only when at least one exists); (g) the existing `tdd` and `verification` API answers gain `red_method` and `exception` per cycle (no new endpoint).
7. **Trace links.** `scenario -> cycle` (exists), new `scenario -> qa_script` (`to_id` is the script path relative to the workspace) in place of `scenario -> test`, `cycle -> evidence` (exists). A missing `qa_script` link is a trace gap (TRC-02).
8. **No driver, no silent downgrade.** At R12 a QA-Red cycle with no usable driver (driver `none` or absent, no `scenario_run`, `scenario_report` or start command, script missing) gives `E_PRECONDITION`, run NEEDS_HUMAN with the reason, no cycle, no task. The text names the two ways out (configure the driver or turn the rule off).
9. **Concurrency.** Cycles of one repo run one after another as today (`_cycle_blockers`, extended to `qa_red`). Driver runs across repos share the QA ports, so the engine holds a QA driver lock (a file under the QA cache) for each driver run; a second run waits, a stale lock from a killed process does not block.

## Files

| Feature | Scenarios | Outline rows | Main requirements |
|---|---|---|---|
| `features/qa_red_planning.feature` | 13 | 18 | TDD-09, CFG-08, CFG-12 (qa keys), TDD-01 |
| `features/qa_red_phase.feature` | 20 | 26 | TDD-09, TDD-02, TDD-03, VER-02, SEC-06, SEC-11, ORC-09 |
| `features/qa_red_green_exception.feature` | 28 | 19 | TDD-09, TDD-04 to TDD-06, TRC-03, VER-05, ART-04, ORC-09, SM-06 |
| Total | 61 | 63 | |

All three files load with `sentinel/scripts/artifacts.py` `parse_gherkin` with no errors (`errors == []`); every scenario has one `@AC` tag, a type tag and a priority tag.

New AC ids (checked by grep against `plan/v1.1/phase*`, `tests/`, `sentinel/`, `docs/`, `SPEC.md`: no clash): `AC-TDD-09a`-`z`, `AC-TDD-09aa`; `AC-CFG-12a`-`e`; `AC-ORC-09a`-`k`; `AC-SEC-11a`-`e`; `AC-TRC-03a`-`b`; `AC-VER-05a`-`f`; `AC-ART-04a`-`c`; `AC-SM-06a`; `AC-TST-06a`.

## Coverage table

| Category | Status |
|---|---|
| Happy path | covered (QA-Red fails, Green passes, cycle accepted, exception recorded; mixed run; Refactor; export/import; human resume) |
| Invalid input | covered (qa key validation, tdd_red for a QA cycle, scope widening, unbound or foreign scenario keys) |
| Missing required fields | covered (missing driver pieces at R12, missing evidence fields and exception event before acceptance, missing script link as trace gap) |
| Boundary | covered (method by rule and role, retry cap 0/1/2, one scenario passing) |
| Empty / null | covered (no exception section when none; empty `tdd_exceptions`; docs-only run) |
| Authentication | not applicable beyond the existing API token on the two answers (`AC-TDD-09aa`); no new endpoint |
| Authorization | covered (qa_red scope, E_SCOPE for test globs and repo writes, no engine commands from a task, agent claims ignored, command from config only, clone gate) |
| Data integrity | covered (script hash integrity, config snapshot, output hash, exception once per cycle, reproducible report) |
| Duplicate submissions | covered (exception event once across retries, two verify calls) |
| Concurrency | covered (same-repo cycles queue, driver lock across repos, double verify, killed engine) |
| Error handling | covered (failure class table, flaky, environment rerun, caps, NEEDS_HUMAN for driver errors, runner crash) |
| External service failure | covered (driver missing, timeout, app not running, killed process) |
| Database failure | not applicable to Phase J: registry write failure is covered by the Phase D and E fault-injection scenarios, and the new rows use the same transaction helpers |
| Regression | covered (rule off, backend and `app` roles, docs-only, 0.1, hygiene without exception, config without new keys, state machines unchanged, bug-run brief) |
| Performance / security | security covered (scrubbing, screenshots and traces stay in the cache and out of the bundle, narrow scope, SENTINEL_TASK_ID); performance not applicable (one extra driver run per phase, bounded by the 1800 s timeout) |

## How the tests will run

- Unit scenarios: stdlib `unittest` in `tests/`, one test per scenario (one subtest per Examples row), names carry the AC id (`test_AC_TDD_09b_method_follows_rule_and_role`). Integration scenarios: `tests/` with a temporary workspace, fake CLIs under `runners` as in Phases C to E.
- Fake QA driver: `tests/fixtures/qa/fake_qa_driver.py`. It reads a JSON script from `FAKE_QA_PLAN` (per run number and per scenario key: `pass`, `fail_then`, `fail_given`, `fail_when`, `skip`, `missing`; or a whole-run mode `app_down`, `driver_missing`, `timeout`, `garbage`), writes the JUnit XML named by `qa.scenario_report` with the failing step name in the failure message, can print secrets and write PNG and trace files into the QA cache, and records start and end times and its pid in a log for the overlap and lock checks. The fake app is a one-line TCP listener on port 4173 started by `qa.start_commands.frontend`.
- Fake agents write script files named after scenario keys under the QA cache folder (and, for `AC-TDD-09j`, the forbidden paths).
- Fixtures: runs, cycles, evidence rows and approvals through the engine fixture functions of Phases D and E; "RED_VERIFIED by QA-Red" is a fixture that writes scripts, hashes, evidence and the exception event.
- Concurrency scenarios use two processes against one `.sentinel/sentinel.db`. No test waits longer than 15 seconds.
- Exit codes as in Phases D and E (0 done, 1 database error, 5 refused, 6 NEEDS_HUMAN).
- Gate for Phase J completion: all Phase J tests pass, all Phase A to I tests and the baseline selftest checks pass (run by the owner at the next release gate, not by this plan), the existing `TDD_09` tests in `tests/test_verification_checks.py` still pass, `SPEC.md` TDD-09 and `docs/config.md` updated, evidence in `IMPLEMENTATION_STATUS.md`.

## Set hash

Command, run from `plan/v1.1/phaseJ`:

```sh
find features -name '*.feature' | LC_ALL=C sort | while read f; do printf '%s\0' "$f"; cat "$f"; printf '\0'; done | sha256sum
```

Hash: `be59129425b1fa619c3c81aad2191dac960e87b90d432f489389ee8a3423f92e`

## Open points for the reviewer

Each point is a choice made where the documents say nothing. Approving this set approves these choices.

1. **New role `qa_red`, not the existing `qa` role.** The `qa` role belongs to the R14 chain, its tasks have no cycle, and `accept._acceptance` counts open `qa` tasks as "required reviews open". A new role keeps both chains apart and makes the Red task's scope and stage template its own. The cost is one more role in the permission matrix, `agents.*` config and adapters.
2. **The engine runs the QA scripts.** The agent writes scripts, the engine runs them through `qa.scenario_run` (VER-02, same as test runs). This needs two new optional `qa` keys (`scenario_run`, `scenario_report`) and a JUnit-style report; the existing `qa.driver` enum only names a driver and holds no command. Without such a command there is no engine-run evidence, so it is required for QA-Red.
3. **Scripts stay out of the repo.** They live in `.sentinel/cache/qa/`, hashed in the evidence row, not exported (cache is never exported), and read-only to Green and Refactor. The cost: the scripts are not versioned; a replan or a lost cache means Red is repeated.
4. **Right-reason rule.** Red is accepted only when each scenario fails at a `Then` step (the step name comes from the report). Failures at `Given` or `When` are `setup_failure` and retried. A stricter or looser rule changes `AC-TDD-09n`.
5. **Environment classes go to a human, not to an agent**, after one engine rerun. This differs from test-file Red, where `environment` is retried by an agent, because an agent cannot start the app or the driver. Such parks do not use up the retry cap.
6. **Retry cap.** `qa_red` uses the same cap as `tdd_red` (`retry_cap`); no new config key. Reaching it gives REJECTED, run NEEDS_HUMAN, reason `red cap reached`.
7. **Unexpected pass is a rejection, not "already implemented".** A scenario that passes before Green is retried until the cap, then a human decides. Treating it as a no-op cycle would need a new rule and is left out.
8. **R12 refusal is NEEDS_HUMAN with E_PRECONDITION**, like `_tdd_precheck`. After fixing the config the human resumes with a new config snapshot (`AC-CFG-12c`). If snapshot refresh on resume does not exist, a new run is the only way out; the reviewer should confirm which.
9. **Exception visible in three places:** events, evidence rows (`method`, `exception`), and the report. A missing exception record is an acceptance reason of its own (`tdd exception evidence missing`), not folded into "cycles incomplete".
10. **Dashboard:** only two new fields (`red_method`, `exception`) on cycle objects in the existing `tdd` and `verification` answers. No script body or secret in them.
11. **Driver lock** is one workspace-wide file lock around each driver run, because `qa.ports` is shared. This serializes QA-Red across repos; parallel QA-Red would need per-repo ports (not in 1.1.0).
12. **Interim hygiene skip stays** for runs whose cycles use test files while the rule is on (older rows); QA-Red cycles never need it. `docs/config.md` text for `test_infra` and `no_permanent_frontend_tests` is updated at build time.
13. **Scenario count:** 61 scenarios with 63 Outline rows, about one above the target; the three concurrency and R17/R18 scenarios could merge if the reviewer wants fewer.
