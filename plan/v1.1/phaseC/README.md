# Phase C: Agent runtime (Gherkin for review)

Scope (from `SPEC.md`, `IMPLEMENTATION_STATUS.md` rows PC-01 and PC-02): AGT-02 to AGT-07, PRV-05, VIS-03, ORC-02 (orchestrator may only call `task complete`), ORC-05 (retry caps), ORC-07 (recovery from persisted state), ORC-08 (legacy runs), TSK-03 and decision Q2 (CLI-routed tasks run without a session, native tasks queue for the AI tool), SEC-02 (child environment), CFG-08 (adapter from the run's config snapshot), VER-02 (claims are not evidence). Task table of `docs/contracts/state-transitions.md` section 2, run transitions R3 (engine), R4 and R8 wiring, R19, R21, R22, R23. CLI commands `sentinel next`, `sentinel task run`, `sentinel task complete` of `docs/contracts/api-contracts.md` section 3.

- PC-01: task and result contracts, adapter interface and capabilities (`task_contracts.feature`, `adapter_interface.feature`).
- PC-02: CLI adapter from `run_stage.py`, native adapter, scheduler, retries, cancel, the three commands (`cli_adapter.feature`, `native_adapter.feature`, `scheduler.feature`, `retries_cancel.feature`, `next_and_cli.feature`).

Not in Phase C: path-level write scopes inside a repo and test or production globs (PD-01; Phase C keeps the repo-level boundary of `boundary.py`, but the scheduler already compares write globs), the test_designer and TDD stage templates and cycles (PD-02), verification and acceptance (Phase E), the orchestrator skill rewrite around `sentinel next` (PE-02), HTTP control endpoints and dashboard (Phase F and later). Phase B is still in progress: scenarios that need approved runs (`... with both approvals valid`) build them through engine fixtures; `AC-ARC-03e` to `AC-ARC-03g` need the Phase B validators and approval command and run last.

## Files

| Feature | Scenarios | Outline rows | Main requirements |
|---|---|---|---|
| `features/task_contracts.feature` | 13 | 29 | AGT-02, AGT-06, VER-02 |
| `features/adapter_interface.feature` | 10 | 20 | AGT-03, AGT-04, PRV-05, VIS-03, CFG-08 |
| `features/cli_adapter.feature` | 16 | 10 | AGT-04, AGT-05, AGT-06, SEC-02, R21, R22 |
| `features/native_adapter.feature` | 11 | 14 | AGT-04, AGT-06, ORC-02, TSK-03 |
| `features/scheduler.feature` | 15 | 22 | AGT-07, SM-03 |
| `features/retries_cancel.feature` | 15 | 15 | AGT-05, ORC-05, ORC-07, R19, R23 |
| `features/next_and_cli.feature` | 14 | 23 | ORC-02, ARC-03, VIS-05, ORC-08, R3, R4, TST-01 |
| Total | 94 | 133 | |

## Coverage table

| Category | Status |
|---|---|
| Happy path | covered (CLI and native task run, task complete, next per state, R3/R4/R8 wiring, dependency order, capabilities, adapter selection, cancel) |
| Invalid input | covered (task-v1 violations, broken result.json, task complete in the wrong state or on a CLI task, bad ids and arguments, dependency cycles, invalid parallel limit, resume unsupported, model without model_flag) |
| Missing required fields | covered (task-v1 required fields, result.json missing `summary` and missing file) |
| Boundary | covered (limit precedence, retry cap 0/1/2, parallel limit unset/1/2, finish just before timeout, SIGTERM then SIGKILL after 10 s, unknown extra result fields) |
| Empty / null | covered (0-byte, whitespace, `{}` and `null` results; empty write scope; run in EXECUTING with no tasks) |
| Authentication | not applicable: Phase C has no network surface; providers keep their own credentials (PRV-04). Dashboard token auth is Phase F |
| Authorization | covered (orchestrator cannot move or cancel tasks, `task complete` has no state flag, task process cannot run or complete tasks, results cannot move the run, task.json tampering, scope violations, no task starts in review or parked states, tasks cannot create tasks) |
| Data integrity | covered (changed files from git, claims never evidence, cancel not overwritten by the finishing process, task.json hash, adapter from config snapshot, R17 cancels running tasks, next never starts a task) |
| Duplicate submissions | covered (second `task complete`, same task run twice at once) |
| Concurrency | covered (write-scope overlap table, overlapping native task, two processes starting overlapping tasks, two `task complete` calls) |
| Error handling | covered (non-zero exit, timeout, invalid result, agent-reported failure and block, retries with brief, retry cap to NEEDS_HUMAN, which failures retry) |
| External service failure | covered (runner missing to BLOCKED (R21) and back (R22), fallback provider, disabled fallback) |
| Database failure | covered (event write failure while finishing a task, Sentinel process killed, reused pid) |
| Regression | covered (`stage run` exit codes 0/1/3 for 0.1 runs and adhoc slugs, new commands refuse 0.1 runs, workflow names no provider, 95 selftest checks and Phase A and B tests green) |
| Performance / security | security covered (child environment strips `SENTINEL_DASHBOARD_TOKEN` and `policies.redact_env`, plus authorization above); performance not applicable (one local process per task, file lists of one repo) |

## How the tests will run

- Unit scenarios: stdlib `unittest` in `tests/`, one test per scenario (one subtest per Examples row), test names carry the AC id (for example `test_AC_AGT_02f_broken_result_fails_the_task`).
- Integration scenarios: new checks in `sentinel/scripts/selftest.py` (or `tests/` with a temporary workspace), named after the AC id. Runners are fake shell scripts configured under `runners`, as in the existing "runner and write boundary" selftest block. Each fake shape (claude-like, codex-like, stdin, agy json) is one script with different runner fields.
- Fixtures: "a version 2 run ... with both approvals valid" and tasks in a given state are written through engine fixture functions, not through the CLI. Task labels in quotes ("A", "docs task") map to the generated `t-<12 hex>` ids. A config step describes the run's config snapshot (CFG-08), so it applies even when the run appears in the Background.
- Timing: the heartbeat interval and timeouts are set to seconds for tests (an engine setting, not a config key). Kill checks look at the process group with `os.kill(pid, 0)`. No test waits longer than 15 seconds.
- Concurrency scenarios use two processes against the same `.sentinel/sentinel.db`, as in Phase A `AC-C-36a`.
- Exit codes used: 0 ok, 1 task FAILED or CANCELLED, 2 usage, 3 scope violation (kept from `run_stage.py`), 5 refused, 6 human action required (run NEEDS_HUMAN or BLOCKED, or `next` returns a human step). When several apply, 3 wins over 6, and 6 wins over 1.
- Gate for Phase C completion: all Phase C tests pass, all Phase A and Phase B tests and the 95 baseline selftest checks pass, evidence recorded in `IMPLEMENTATION_STATUS.md`.

## Set hash

Command, run from `plan/v1.1/phaseC`:

```sh
find features -name '*.feature' | LC_ALL=C sort | while read f; do printf '%s\0' "$f"; cat "$f"; printf '\0'; done | sha256sum
```

Hash: `dbccd512de4c60e8d149ab172ad62ddda002dcb3561a027f57fc07a5de9369fa`

## Open points for the reviewer

Each point is a choice made where the documents conflict or say nothing. Approving this set approves these choices.

1. **New task error codes.** `state-transitions.md` section 5 has no code for a non-zero exit, a timeout, an agent-reported failure or a missing provider; `event-contracts.md` already names `E_PROVIDER`. Choice: add `E_EXIT`, `E_TIMEOUT`, `E_AGENT` and `E_PROVIDER` to the list and to `errors.py`. They appear on the task row and in `task.finished`; a lost process is `E_EXIT` with reason "process lost".
2. **Missing runner blocks the run, it does not fail the task.** `agent-runtime.md` section 5 says "fallback provider, else FAILED". The brief and R21 say BLOCKED. Choice: check the runner before QUEUED to RUNNING; try `providers.fallback` in order (skip disabled or missing); if none is usable, the task stays QUEUED, no retry is used, and the run goes BLOCKED (R21). `next` re-checks and applies R22. A provider that starts but fails (auth error) is a normal failure (`E_EXIT`) and counts toward retries; `policies.provider_retries` is not used in Phase C.
3. **`task complete` on a CLI task** returns `E_PRECONDITION` (the task is not native). On a task that is not waiting (QUEUED, CREATED, final) it returns `E_TRANSITION`. It has no option to choose the state.
4. **Agent processes are detected by `SENTINEL_TASK_ID`.** The CLI adapter sets it in the child environment; `task run` and `task complete` refuse with `E_ACTOR` when it is set and audit the attempt (`task_refused`). An agent can unset it; this is the same residual risk R1 as for approvals, and the boundary check still applies. Native subagents run in the AI tool's process tree, so they cannot be told apart from the orchestrator.
5. **Retry defaults.** `constraints.max_retries` comes from the task, then `agents.<role>.max_retries`, then `limits.<role>_retries` (Phase B's `specifier_retries`, `test_designer_retries`), then 2. Cap N means N retries after the first attempt (N+1 runs). Retried: `E_EXIT`, `E_TIMEOUT`, `E_RESULT_SCHEMA`, `E_AGENT`. Not retried, run to NEEDS_HUMAN: `E_SCOPE`, `E_INTEGRITY`, agent status `blocked`. CANCELLED is never retried.
6. **Agent status `blocked`** puts the task in BLOCKED and the run in NEEDS_HUMAN (R19) with the agent's questions, not BLOCKED (R21 is for missing external dependencies). Answering and resuming a blocked task is not in Phase C beyond the adapter `resume` check.
7. **Exit code and result status together** (`AC-AGT-02i`): exit non-zero always fails (`E_EXIT`), status `failed` with exit 0 fails (`E_AGENT`), status `blocked` blocks, only exit 0 plus status `completed` plus no scope problem completes.
8. **Cancel.** There is no `sentinel task cancel` in the CLI contract; tests cancel through the engine function the HTTP `control` endpoint will call (Phase F), and through `run finish --outcome stopped` (R23). The adapter starts each runner in its own process group and signals the group: SIGTERM, then SIGKILL after 10 s. The `task run` process that owns the runner sees CANCELLED in the registry and never overwrites it. Dependents of a cancelled task are cancelled by the engine. If you want a CLI command, it would be `sentinel task cancel <id>` for the human; it is not in this set.
9. **R17 and R18 during execution** (left open by Phase B point 20): the engine cancels RUNNING, WAITING_FOR_INPUT and QUEUED tasks with reason "approval invalidated" and kills their processes.
10. **Process recovery.** The task row stores pid and process start time. `next` (and any engine call that loads the run) fails a RUNNING CLI task whose process is gone or whose pid now belongs to a different process, with reason "process lost", and applies the retry rules. The adapter writes `exit.json` (exit code, times) to the task folder before it updates the registry, so a failed registry write can be finished later from the files (`AC-ORC-07c`).
11. **Task folder.** `.sentinel/runs/<slug>/tasks/<task-id>/` holds `task.json`, `prompt.md`, `brief.md`, `before.json` (boundary snapshot, needed because the native task finishes in another process), `output.log`, `stderr.log`, `exit.json` and `result.json`. Logs move here from `.sentinel/cache/runs/<slug>/` for version 2 tasks; `stage run` keeps the cache folder.
12. **Task-file integrity.** The registry stores the sha256 of `task.json`. A change during the task fails it with `E_INTEGRITY` and sends the run to NEEDS_HUMAN; the scope check always uses the stored copy.
13. **Native tasks and the timeout.** The engine cannot stop a native subagent. Choice: the timeout is checked when the engine next loads the run (`next`, `task complete`); a late task fails with `E_TIMEOUT` and `next` tells the orchestrator to stop the subagent.
14. **Scheduling rules.** A WAITING_FOR_INPUT task counts as running for both the overlap test and the parallel limit. Overlap test per repo: the two glob patterns overlap if one could match a path the other matches (prefix and wildcard test) or both match a file in the repo's file list. An empty write scope overlaps nothing. A refused start (overlap, limit, open dependencies, run not in an execution state) leaves the task where it was and exits 5. Tasks run only while the run is PLANNED (specifier), SPECIFICATION_APPROVED (test_designer) or EXECUTING, VERIFYING, REVIEWING.
15. **Repo-level boundary in Phase C.** Within an allowed repo, a write outside the task's globs is not caught until PD-01. Two tasks running at once in the same repo (non-overlapping globs, `max_parallel_tasks` above 1) both count that repo as concurrent, as `--concurrent` does today, so one cannot catch the other's writes there until PD-01. A human editing a repo during a native task is blamed on the task.
16. **What `sentinel next` returns.** JSON `kind` is one of `task`, `orchestrator` (triage or write `decisions.md`), `human`, `wait`, `done`. Exit 6 for `human`, otherwise 0. `next` never starts a task but does engine bookkeeping: queue tasks whose dependencies completed, R3 by the engine for a run that needs no `decisions.md`, R22 re-check, lost-process and native-timeout checks. A run in EXECUTING with no task planned returns a human step until Phase D plans cycles.
17. **Task creation in Phase C.** The engine creates the specifier task on R3 and the test_designer task on R5 (spec approved). Execution tasks come from Phase D planning; Phase C tests insert task graphs through an engine fixture. Roles without a stage template yet (`test_designer`, `tdd_*`) can be created and handed to the native adapter, but rendering them with the CLI adapter fails with `E_PRECONDITION` until PD-02 adds the templates. `role` must be in the `task-v1` enum (`coder` is refused; mapping 0.1 stages onto roles is PD-02 work).
18. **Adapter selection** uses the run's config snapshot: `single_model` not false gives native for every role (PRV-05); otherwise `agents.<role>` wins over `routing` (repo-specific key first, as `find_route` does today); no entry gives native ("this session").
19. **`stage run` on a version 2 run** is refused with `E_TRANSITION` pointing to `sentinel task run`, so the engine cannot be bypassed. Slugs with no run, adhoc runs and 0.1 runs work as before.
20. **Migration.** Phase C needs a registry migration (task dependencies table; task columns `attempt`, `waiting_on`, `pid`, `pid_started_at`, `session_id`, `task_sha256`, `reason`). Phase B may add its own migration; numbers are taken in merge order.
21. **Dashboard dispatch (Q2).** `AC-TSK-03a` tests the engine function the server will call. A task routed to a CLI provider runs; a native task stays QUEUED and `next` labels it "waiting for orchestrator". The server itself is Phase F.
