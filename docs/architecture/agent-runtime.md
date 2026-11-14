# Agent Runtime (1.1.0, draft for G1)

Requirements: `SPEC.md` section 8. Schemas: `docs/contracts/configuration-schemas.md` (`task-v1`, `agent-result-v1`).

## 1. Task contract

The engine writes `.sentinel/runs/<slug>/tasks/<task-id>/task.json` (`task-v1`):

```json
{
  "schema": "task-v1",
  "id": "t-0007",
  "run_id": "leave-balance",
  "role": "tdd_green",
  "objective": "Make scenarios of features/leave_balance.feature::Rule balance shown pass",
  "provider": {"name": "codex", "model": null},
  "input": {
    "specification": {"path": "specs/leave-balance/spec.md", "sha256": "..."},
    "gherkin": {"paths": ["specs/leave-balance/features/leave_balance.feature"], "sha256": "..."},
    "cycle_id": "c-0002",
    "previous_results": ["t-0006"],
    "brief": "brief.md"
  },
  "repos": ["backend"],
  "permissions": {
    "read": ["backend/**"],
    "write": ["backend/src/main/**"],
    "readonly_approved": ["backend/src/test/java/leave/LeaveBalanceTest.java"]
  },
  "constraints": {"must_follow_tdd": true, "max_retries": 3, "timeout_seconds": 5400},
  "expected_output": {"schema": "agent-result-v1", "path": "result.json"}
}
```

The rendered stage prompt (existing `render_stage.py`) is generated from this file plus the stage template.

## 2. Result contract

The agent writes `result.json` (`agent-result-v1`): status (`completed`, `blocked`, `failed`), summary, changed files it claims, commands it ran with its own claimed results, findings, questions, out-of-lane notes, new dependencies.

The engine validates it with jsonschema, then **ignores the claims for decisions**: changed files come from the git diff, test results from the engine's own run. Claims are kept only for the report and for spotting disagreements (a claim that differs from the engine's evidence is flagged).

A missing or invalid `result.json` makes the task `FAILED` with `E_RESULT_SCHEMA`; the agent's free-text report is kept as a log.

## 3. Adapter interface

```python
class Adapter(Protocol):
    name: str
    def capabilities(self) -> Capabilities: ...   # resume, cancel, model_select, json_output, streaming, native
    def submit(self, task: Task) -> Handle: ...
    def status(self, handle: Handle) -> TaskStatus: ...
    def result(self, handle: Handle) -> RawResult: ...
    def cancel(self, handle: Handle) -> bool: ...
    def resume(self, handle: Handle, message: str) -> Handle: ...
```

### CliAdapter

- Built from the existing runner table (`DEFAULT_RUNNERS` plus `runners` in config): command, prompt flag, model flag, resume flag, add-dir flag, output format.
- `submit` starts the process in the target repo's directory, streams the live log (existing heartbeat), returns a handle with the pid.
- `cancel` sends SIGTERM, then SIGKILL after 10 s.
- `resume` is supported only when the runner defines `resume_flag` and returned a session id.
- Environment passed to the child: inherited minus `SENTINEL_DASHBOARD_TOKEN` and any variable listed in `policies.redact_env`.

### NativeAdapter

- For stages that run as a subagent inside the user's AI tool (`single_model: true`, or routing says `this session`).
- `submit` writes `task.json` and the rendered prompt and sets the task to `WAITING_FOR_INPUT` with `waiting_on: orchestrator`.
- The orchestrator skill launches the subagent with that prompt, then calls `sentinel task complete <id>`.
- `cancel` marks the task cancelled; the skill is told to stop the subagent. `resume` unsupported.
- Same contract, same evidence checks, so workflows never name a provider.

## 4. Scheduler

- A task becomes `QUEUED` when its dependencies are complete.
- Before `RUNNING`, the scheduler compares its `permissions.write` globs with every running task's globs (per repo, glob intersection test on the repo's file list plus pattern overlap). Overlap: stays queued.
- Concurrency limit: `policies.max_parallel_tasks` (default 1; parallelism is opt-in).
- No task can create tasks. Delegation is the engine's job.

## 5. Lifecycle, timeouts and retries

```text
CREATED -> QUEUED -> RUNNING -> COMPLETED
                         |-> WAITING_FOR_INPUT (native, or agent asked a question)
                         |-> BLOCKED (agent reported blocked)
                         |-> FAILED (exit non-zero, timeout, invalid result, scope violation)
                         |-> CANCELLED (human or engine)
```

- Timeout: `constraints.timeout_seconds`, default from `policies.task_timeout_seconds` (5400).
- Retry: a failed task is retried as a new task (new id, `retry_of` link) up to `max_retries`, with the failure reason in its brief. Scope violations are not retried automatically; they go to `NEEDS_HUMAN`.
- Provider unavailable (command not found, auth error pattern): fallback provider from `providers.fallback`, else FAILED.

## 6. Write-scope enforcement

Extends `boundary.py`:

- Snapshot before: per repo HEAD, diff digest, and the list of changed paths with content hashes.
- Snapshot after: same.
- Paths whose hash changed are matched against `write` globs, then against `readonly_approved`. Any miss is a violation. HEAD moving is a violation. Config, agent and skill files changing is a violation.
- Violations fail the task and are listed. Nothing is reverted without the human's consent.

## 7. Provider capability matrix (initial)

| Provider | Kind | Model select | Resume | Cancel | JSON output |
|---|---|---|---|---|---|
| claude | cli | yes | no (not wired) | yes (signal) | no |
| codex | cli | yes | no | yes (signal) | no |
| gemini | cli | yes | no | yes (signal) | no |
| agy | cli | yes | yes | yes (signal) | yes |
| native | native | tool's choice | no | cooperative | via result.json |

The adapter test suite runs against a fake CLI script that simulates success, failure, timeout, invalid result, out-of-scope writes and a commit.
