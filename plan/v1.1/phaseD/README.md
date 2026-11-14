# Phase D: TDD engine (Gherkin for review)

Scope (from `SPEC.md`, `IMPLEMENTATION_STATUS.md` rows PD-01 and PD-02): TDD-01 to TDD-08, AGT-01 (the four new roles and their templates), AGT-06 and SEC scope rows (path-level write scopes), CFG-10 (profile globs and test tooling), CFG-11 (additive `tdd` keys), SM-05 (cycle states in use), TRC-01 and TRC-02 (scenario to cycle to evidence links), VER-02 (claims are not evidence), SEC-06 (scrubbed evidence output), AGT-07 (cycle concurrency). TDD cycle table of `docs/contracts/state-transitions.md` section 4, run transition R13, and the effect of R17 and R18 on running TDD tasks and open cycles (left open by Phase B point 20; Phase C cancels the tasks, Phase D decides what happens to the cycles). Mandatory tests of `SPEC_CORE.md` section 14 covered here: "Gherkin has not been approved", "Red produces expected assertion failure", "Red fails due to environment", "Green modifies approved tests", "Green passes", "Refactor breaks tests", "More behaviors remain", "All cycles pass", "Agent exceeds write scope", "Agent claims tests passed without evidence", "Two tasks modify overlapping files".

- PD-01: path-level scopes, test and production globs in profiles and repos (`write_scopes.feature`).
- PD-02: roles, stage templates and the permission matrix (`tdd_stages.feature`), cycle planning and baseline (`cycle_planning.feature`), Red binding and failure classifier (`red_phase.feature`), Green and Refactor (`green_refactor.feature`), evidence and trace links (`cycle_evidence_trace.feature`), cycle flow, caps, R13, concurrency, invalidation, recovery and regression (`cycle_flow.feature`).

Not in Phase D: running verification after R13 (VERIFYING onward, R14 to R16, Phase E), reviewer and QA tasks, acceptance computation and reports (Phase E), TDD-09 (`no_permanent_frontend_tests` uses QA scenarios as Red evidence, needs QA from Phase E), the TDD-08 exception path (see point 15), restoring a working tree to the Green snapshot (point 12), dashboard views of cycles (Phase F and later). Phase C is still in progress: these scenarios use its task runner, adapters, scheduler, retries and exit codes, and run after the Phase C tests pass.

## Files

| Feature | Scenarios | Outline rows | Main requirements |
|---|---|---|---|
| `features/write_scopes.feature` | 14 | 46 | CFG-10, CFG-08, AGT-06, TDD-08, ORC-08 |
| `features/tdd_stages.feature` | 11 | 18 | AGT-01, AGT-04, TDD-08, ORC-08 |
| `features/cycle_planning.feature` | 11 | 17 | TDD-01, TDD-03 (baseline), TDD-07, ORC-04, R12 |
| `features/red_phase.feature` | 13 | 18 | TDD-02, TDD-03, VER-02 |
| `features/green_refactor.feature` | 12 | 7 | TDD-04, TDD-05, VER-02 |
| `features/cycle_evidence_trace.feature` | 10 | 9 | TDD-06, TRC-01, TRC-02, SEC-06 |
| `features/cycle_flow.feature` | 19 | 21 | SM-05, ORC-01 (R13), ORC-05, ORC-07, AGT-07, R17, R18, CFG-11, TST-01 |
| Total | 90 | 136 | |

New AC ids (none used by Phases A to C): `AC-CFG-10a`-`e`, `AC-CFG-08b`, `AC-CFG-11a`, `AC-AGT-06f`-`l`, `AC-AGT-01a`-`e`, `AC-AGT-04f`-`g`, `AC-AGT-07p`-`s`, `AC-TDD-01a`-`g`, `AC-TDD-02a`-`d`, `AC-TDD-03a`-`m`, `AC-TDD-04a`-`f`, `AC-TDD-05a`-`f`, `AC-TDD-06a`-`f`, `AC-TDD-07a`, `AC-TDD-08a`-`c`, `AC-TRC-01a`-`c`, `AC-TRC-02a`, `AC-SM-05d`-`g`, `AC-ORC-01f`-`i`, `AC-ORC-05e`-`h`, `AC-ORC-07d`, `AC-ORC-08i`-`j`, `AC-TST-01c`.

## Coverage table

| Category | Status |
|---|---|
| Happy path | covered (full cycle end to end, next behavior begins, planning per behavior group, baseline, Red verified, Green passes, Refactor accepted, evidence and trace chain complete, R13, templates render, both adapters run TDD roles) |
| Invalid input | covered (bad glob lists, unknown or reworded scenario references, unknown repo tag, undefined cycle moves) |
| Missing required fields | covered (code repo without globs, missing `targeted_test`, incomplete evidence rows) |
| Boundary | covered (glob matching table, test-and-production overlap, same-bytes rewrite, cap 0/2/3, cap precedence, related-test set, classification precedence, one passing new test, baseline failure that now passes, parallel limit 1) |
| Empty / null | covered (empty glob list, empty baseline, Red that changes no test, Refactor that changes nothing) |
| Authentication | not applicable: Phase D has no network surface; providers keep their own credentials (PRV-04). Dashboard token auth is Phase F |
| Authorization | covered (writes outside globs, approved test changed by Green or Refactor, Red writing production or a feature file, shared-file authors limited to their file, permission matrix, task cannot ask for more, only the engine moves cycles and requests VERIFYING) |
| Data integrity | covered (content-hash scope check with pre-existing changes, config snapshot globs, approved test edited by hand, evidence output tampered, claims never evidence, R17/R18 cancel tasks and reject open cycles, re-approval keeps unchanged accepted cycles, R18 wins over R13, transactional planning) |
| Duplicate submissions | covered (retried Red replaces its test links; duplicate task runs are Phase C `AC-AGT-07k`) |
| Concurrency | covered (two tasks in one repo judged by own globs, unattributed write blamed on all, cycles in two repos in parallel, overlapping scope waits, cycles in one repo ordered, parallel limit) |
| Error handling | covered (each classifier class and its routing, retry brief, new failure outside new tests, Red passing unexpectedly, Green and Refactor rejections, caps to REJECTED and NEEDS_HUMAN, shared cap for task failures, replanning after R20) |
| External service failure | covered (baseline that cannot run: environment, missing dependency, compile, crash). Runner missing and provider fallback are Phase C |
| Database failure | covered (failed cycle insert during planning, failed evidence write, Sentinel killed between task and verification) |
| Regression | covered (0.1 stage templates byte-identical, repo-level boundary for 0.1 stage runs including `--concurrent`, configs without `tdd` keys valid, profile `commands` and `lanes` unchanged, repro test kept as regression test, 95 selftest checks and Phase A to C tests green) |
| Performance / security | security covered (scrubbed evidence output, plus authorization above); performance not applicable (engine test runs use the project's own commands; Phase D adds no hot path beyond one `git status` and hashing of changed files per task) |

## How the tests will run

- Unit scenarios: stdlib `unittest` in `tests/`, one test per scenario (one subtest per Examples row), test names carry the AC id (for example `test_AC_TDD_03d_classification_and_routing`).
- Integration scenarios: new checks in `sentinel/scripts/selftest.py` (or `tests/` with a temporary workspace), named after the AC id. Agents are fake CLIs configured under `runners`, as in Phase C.
- Test profile `fake-junit`: a test-only profile (under the test fixtures, not shipped) whose `commands.test` and `targeted_test` call a fake test tool. Each scenario scripts the tool's exit code, stdout and the JUnit XML it writes (passing, failing with `<failure>`, erroring with `<error>`, or absent). Test ids are `Class.method` from that XML. `scenario_ref` reads `@Scenario("<feature path> :: <scenario name>")` from changed test files.
- Fixtures: runs, approvals, planned cycles and cycles in a given state are written through engine fixture functions. Quoted cycle labels ("remaining", "carry-over", "request-form") map to generated `c-<12 hex>` ids; task labels as in Phase C. Scenario keys are `<path relative to specs/<slug>/> :: <scenario name>`.
- Golden files for `AC-ORC-08j` are rendered from the commit before Phase D starts and stored under `tests/fixtures/`.
- Timing as in Phase C: no test waits longer than 15 seconds. Concurrency scenarios use two processes against the same `.sentinel/sentinel.db`.
- Exit codes of `sentinel task run` and `task complete` for TDD tasks: 0 phase verified, 1 task failed or phase rejected with a retry queued, 3 scope violation, 5 refused, 6 run went to NEEDS_HUMAN (unknown class, cap, integrity). Order as in Phase C: 3 over 6 over 1.
- Gate for Phase D completion: all Phase D tests pass, all Phase A, B and C tests and the 95 baseline selftest checks pass, evidence recorded in `IMPLEMENTATION_STATUS.md`.

## Set hash

Command, run from `plan/v1.1/phaseD`:

```sh
find features -name '*.feature' | LC_ALL=C sort | while read f; do printf '%s\0' "$f"; cat "$f"; printf '\0'; done | sha256sum
```

Hash: `3bb67c8c68cd911c7281b5cd2407d92b4f787274ead20d6f457a729031126441`

## Open points for the reviewer

Each point is a choice made where the documents conflict or say nothing. Approving this set approves these choices.

1. **Behavior group and repo.** One cycle per Rule, or per Feature without Rules; scenarios before the first Rule form a "(no rule)" group. A behavior group gets its repo from a `@repo-<id>` tag on the Rule (wins) or Feature; a single-repo run needs no tag. A multi-repo run with an untagged group, or an unknown repo id, sends the run to NEEDS_HUMAN at R12 with no cycle stored. `@repo-*` is an allowed plain tag under Phase B point 15. A cross-repo behavior must be split into Rules per repo.
2. **Cycle order.** Cycles of the same repo run in file order: the next cycle's Red depends on the previous cycle being CYCLE_ACCEPTED. Cycles of different repos are independent and can run in parallel within `policies.max_parallel_tasks`. This keeps engine test runs in one repo from seeing another cycle's half-done work.
3. **Baseline.** Taken once per repo, right before that repo's first Red, with the profile's full test command. Stored as an evidence row of kind `baseline` with the failing test set. A baseline classified compile, environment, missing_dependency or unknown sends the run to NEEDS_HUMAN. "Rest unchanged" (TDD-03, state table) is read as "no test outside the new ones fails unless it failed at baseline": a baseline failure that now passes is fine.
4. **Classifier.** Order: compile (build failed before tests, or a compile pattern) > missing_dependency > environment > structured report. With a report: new tests failing with `<failure>` = assertion; failures limited to tests that already failed at baseline, new tests absent = preexisting_failure; `<error>` with no pattern match, or no report and no pattern = unknown. Profiles can add patterns per class (including `assertion` for languages where missing behavior surfaces as an error, for example Python `AttributeError`).
5. **Routing.** compile, missing_dependency, environment and preexisting_failure retry tdd_red with the classified output in the brief (as `orchestration-architecture.md` section 3 says), counted against the Red cap. unknown goes to NEEDS_HUMAN at once, no retry. Red rejections for other reasons (new tests pass, partial pass, no test changed, binding problem, new failure outside new tests) also retry Red.
6. **Red passing unexpectedly** is retried, not sent to a human at once, because the usual cause is a vacuous test. If the behavior already exists, the cap brings in the human. Alternative: NEEDS_HUMAN at once.
7. **Scenario binding.** The profile's `scenario_ref` regex is applied to the changed test files. Every scenario of the cycle needs at least one reference; each reference must be an approved scenario key of this cycle, matched exactly (case included). A Scenario Outline is one scenario; one test per row is not required.
8. **Caps and retries.** One counter per cycle phase covers both task failures (Phase C `E_EXIT`, `E_TIMEOUT`, ...) and engine rejections. Cap from `tdd.<phase>_retries`, then `limits.<phase>_retries`, then 2/3/2 (Red/Green/Refactor). Cap N means N retries after the first attempt. Phase C's `constraints.max_retries` is set from this value for TDD tasks. `E_SCOPE` and `E_INTEGRITY` are never retried (Phase C point 5); the cycle stays in its running state and the run goes NEEDS_HUMAN.
9. **Cycle states on retry.** The table only has `RED_RUNNING -> PLANNED` for a retry. Green and Refactor retries keep the cycle in GREEN_RUNNING or REFACTOR_RUNNING with a new task; no new row is needed.
10. **New cycle table rows.** On R17 or R18, open cycles (not CYCLE_ACCEPTED or REJECTED) become REJECTED with reason "approval invalidated". This needs `REJECTED` from PLANNED, RED_VERIFIED, GREEN_VERIFIED and REFACTOR_VERIFIED too (today only from the running states). After renewed approval, R12 replans: an accepted cycle is kept when every scenario of its group is byte-identical (per-scenario text hash); otherwise a new cycle is planned and the old one stays as history. After R20 on a cap, the engine plans a new cycle for the group with `retry_of` (`AC-ORC-05h`); `REJECTED -> PLANNED` stays undefined.
11. **Approved test files.** A test file becomes approved for a cycle when Red is verified, with its sha256 stored. Green and Refactor tasks list all approved test files of their repo in `readonly_approved`; a change there is `E_SCOPE` with kind `approved_test_changed`, any other test file is `outside_write_scope`. Later Reds may edit earlier approved test files (tests often share a file); earlier tests must still pass under the "rest unchanged" rule. Before dispatching Green or Refactor the engine re-hashes approved test files; a mismatch (human edit) is `E_INTEGRITY`.
12. **Refactor rejection** leaves the working tree as it is and retries Refactor. Restoring the Green snapshot needs human consent; Phase D offers no restore command.
13. **Related tests** = the targeted tests of this cycle plus those of every CYCLE_ACCEPTED cycle in the same repo. The full suite is Phase E verification.
14. **Path-level scope check.** Changed paths come from `git status --porcelain --untracked-files=all` plus per-path content hashes before and after; a path counts as changed only if its hash changed (deletes and both sides of a rename count). Paths ignored by `.gitignore` are not checked (build output). Glob syntax: repo-relative, `/` separators, `*` within a segment, `**` across segments, case-sensitive, dotfiles matched. A path matching both test and production globs is a test file. Shared files: specifier writes only `spec.md`, test_designer only `features/**`; SPEC_CORE 6.6 lets the test designer write test files, but Red owns repo tests here.
15. **Two tasks in one repo.** A changed path that matches another running task's globs is that task's; a path matching no running task is a violation for every task running in that repo at the time. TDD-08 exceptions ("explicit, recorded engine authorization") have no command or contract yet: Phase D refuses every widened scope with `E_POLICY`. Proposal for a later phase: a human-only `sentinel tdd authorize`.
16. **Evidence storage needs a migration.** New table `changed_files` (run, task, cycle, repo, path, sha256 before and after, phase); `evidence` gains `output_sha256`, `repo_sha`, `provider`, `model`, `failing` (JSON list) and `verdict`/`reason`; `cycles` gains `repo_id`, `retry_of`, `reason`. Output files are scrubbed with `scrub.py` before they are written; the stored sha256 is of the scrubbed file. Incomplete evidence at REFACTOR_VERIFIED sends the run to NEEDS_HUMAN.
17. **Trace link kinds.** `scenario -> cycle` at planning, `scenario -> test` and `cycle -> test_file` at RED_VERIFIED (replaced on each Red verify), `cycle -> file` at GREEN_VERIFIED and REFACTOR_VERIFIED, `cycle -> evidence` at CYCLE_ACCEPTED. The trace report (`AC-TRC-02a`) is an engine function; Phase E puts it in the run report.
18. **Profiles.** All shipped code profiles gain `test_globs`, `production_globs`, `targeted_test`, `test_report`, `failure_patterns` and `scenario_ref`; `generic` gets none, so a generic repo must set them in `repos[]` before execution (R12 to NEEDS_HUMAN otherwise). Template names and front matter values `writes: tests | production | gherkin` are new; `render_stage.py` gains placeholders for globs, scenarios and read-only files without changing 0.1 output.
19. **R13** runs as engine bookkeeping in `sentinel next` (and after any cycle reaches CYCLE_ACCEPTED). Required extra stages are the hardener at tier 4 only, for now. Docs-only runs need their docs task COMPLETED and no cycle.
