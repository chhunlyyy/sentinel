# Proposed Unified Architecture (for Gate G0)

Status: **approved at G0 on 2026-11-14 with changes recorded in `DECISIONS.md`** (dashboard in this release, local-only; two sequential approvals for every tier; version 1.1.0). Where this file and `DECISIONS.md` differ, `DECISIONS.md` wins.

## 1. Core idea

Keep what makes Sentinel work today: plain-file stages, any AI tool as the worker, skills as the driver, git as the shared store. Move **authority** from the orchestrator LLM into the `sentinel` engine:

- The LLM orchestrator **proposes** transitions by calling `sentinel`.
- The engine **decides**: it checks preconditions, approvals (by hash) and evidence, then either moves the state or refuses with a reason.
- Evidence that matters (test results, build, scope checks) is produced by commands **the engine runs itself**, never copied from an agent's report.
- Humans approve through a channel the engine treats as human-only.

```text
             Human
               |  sentinel review / approve (TTY)        later: dashboard (authenticated)
               v
+------------------------------------------------------------------------------+
|  sentinel engine (Python, stdlib + pyyaml + jsonschema)                      |
|                                                                              |
|  state machines ---- policy (tiers, gates, scopes, human-required actions)   |
|        |                                                                     |
|  approvals (version + sha256)     verification runner (reuses release_check) |
|        |                                  |                                  |
|  registry: .sentinel/sentinel.db (SQLite) + .sentinel/runs/<slug>/artifacts  |
|        |                                                                     |
|  task dispatcher ---> provider adapters                                      |
|                         - cli: claude, codex, gemini, agy (from run_stage)   |
|                         - native: in-tool subagent via the same contract     |
+------------------------------------------------------------------------------+
               ^                                   |
               | sentinel task/ run / tdd ...      v
     Orchestrator skill (LLM)              Worker agents (stages)
     proposes, never authorizes            write within scope, return result-v1
```

The future dashboard is a client of a local API that wraps the same engine functions. It adds no orchestration logic.

## 2. State model (canonical, resolves B8)

**Run states:** `CREATED, TRIAGED, PLANNED, SPECIFICATION_REVIEW, SPECIFICATION_APPROVED, GHERKIN_REVIEW, GHERKIN_APPROVED, EXECUTING, VERIFYING, REVIEWING, NEEDS_HUMAN, COMPLETED, FAILED, CANCELLED, BLOCKED`

- `execution_status`: running, completed, failed, cancelled.
- `acceptance_status`: pending, accepted, rejected. Computed by the engine from the acceptance rules (C 8). `sentinel run finish --outcome` keeps working and maps onto these.

**Task states:** `CREATED, QUEUED, RUNNING, WAITING_FOR_INPUT, BLOCKED, FAILED, CANCELLED, COMPLETED`.

**Approval states:** `DRAFT, IN_REVIEW, CHANGES_REQUESTED, REJECTED, APPROVED, INVALIDATED`.

**TDD cycle states:** `PLANNED, RED_RUNNING, RED_VERIFIED, GREEN_RUNNING, GREEN_VERIFIED, REFACTOR_RUNNING, REFACTOR_VERIFIED, CYCLE_ACCEPTED` (plus `REJECTED` per phase with a reason).

Each transition is one row in a table in code: from, to, actor (`engine`, `orchestrator`, `human`), preconditions, required evidence. Unknown transitions are refused.

## 3. Pipeline per tier (resolves B5)

```text
Tier 1  triage > spec-lite (approve) > gherkin (approve) > TDD cycle(s) > verify
Tier 2  triage > [repro] > spec-lite (approve) > gherkin (approve) > TDD cycles > verify > release check
Tier 3  triage > interview > spec (approve) > gherkin (approve) > TDD cycles > review > QA
        > promotion > verify + release check > docs
Tier 4  as tier 3 + hardener (mutation) after cycles, full QA, security gate (human), rollout, retrospective
Docs-only (any tier)  spec (approve) > docs stage > verify (links, build if docs are built)
```

Stage mapping from today:

| Today | Target |
|---|---|
| `specifier` | `specifier` (sections scale with tier), writes `specs/<slug>.md` only |
| (Gherkin inside spec) | `test_designer` writes `specs/<slug>/*.feature` with `@REQ-` and `@AC-` tags |
| `repro` | Stays for bugs; its failing test becomes the first Red of cycle 1 |
| `coder` | `tdd_red` (tests only) then `tdd_green` (production only) |
| `cleaner` | `tdd_refactor` (production only, tests re-run by engine) |
| `hardener`, `reviewer`, `qa`, `promotion`, `release_check`, `docs`, `rollout`, `retrospective` | unchanged role; results recorded as tasks with evidence |

## 4. Approvals (resolves B3)

- Artifact hash: sha256 over the canonical bytes (spec Markdown; all `.feature` files sorted by path).
- `sentinel review <slug> spec|gherkin` shows the artifact, the diff against the last reviewed version, and the validator's coverage table.
- `sentinel approve <slug> spec|gherkin` requires an interactive TTY and typing the first 8 characters of the hash. It records approver (git user.name, OS user), time, version, hash, comment. `--request-changes` and `--reject` work the same way.
- Before any gated transition the engine re-hashes the artifact; a mismatch sets the approval to `INVALIDATED` and the run back to review.
- Generated agent configs (Claude, AGENTS.md) carry a deny rule or instruction for `sentinel approve`. Residual risk R1 is documented.

## 5. Write scopes (resolves B4)

- Each task carries `permissions.read` and `permissions.write` globs, derived from role and repo profile (profiles gain `test_globs`).
- Before and after the task the engine snapshots the repo (extends `boundary.py` from repo-level to path-level).
- Any changed path outside `write` fails the task. Green or Refactor touching a path in the approved test set fails the task. Changes are listed, never reverted without consent (current behavior kept).

## 6. Provider adapters

```python
class Adapter:
    def capabilities(self) -> dict: ...      # resume, cancel, model_select, json_output, streaming
    def submit(self, task) -> str: ...
    def status(self, task_id) -> str: ...
    def result(self, task_id) -> dict: ...   # validated against agent-result-v1
    def cancel(self, task_id) -> bool: ...
    def resume(self, task_id) -> bool: ...   # only when capabilities say so
```

- `CliAdapter`: the existing `run_stage.py` logic (runners table, heartbeat, timeout, JSON parse), now with retries and cancel.
- `NativeAdapter`: for "this session" stages. The engine writes the task file; the orchestrator runs it as a subagent; the subagent writes `result.json`; the engine validates it and runs the evidence checks. Same contract, so the workflow definition never names a provider.
- A2A: deferred.

## 7. Storage (resolves B2)

- `.sentinel/sentinel.db` (stdlib `sqlite3`): runs, tasks, approvals, cycles, evidence index, events (append-only).
- `.sentinel/runs/<slug>/`: briefs, results, command outputs, reports. Each evidence row stores the file's sha256.
- `state.json` is still written as a view for old skills (compatibility).
- `sentinel run export <slug>` / `import`: a scrubbed bundle for cross-machine resume. Opt-in, never auto-pushed.

## 8. Verification and acceptance

- `sentinel verify <slug>` runs, through the engine: targeted tests per cycle, the full test command, build, lint, typecheck, secret scan, dependency audit (all reused from `release_check.py`), and a diff-scope check against the union of task scopes.
- Acceptance is computed: both approvals valid by hash, all cycles accepted, verification evidence present and green, no scope violations, required reviews done, required human approvals done.

## 9. Policy

Config gains an additive `policies` block: human-required actions (security gate, destructive migration, publish, deploy), retry limits, timeouts. Defaults are strict; config can add gates but not remove the two mandatory ones. `auto_sync_push` defaults to `false` for new configs (B6).

## 10. Compatibility

- Runs without `schema_version: 2` continue in legacy mode with today's behavior.
- All existing commands keep their flags. New behavior is behind new commands plus the new run schema.
- The 95 selftest checks stay green; new unit tests live under `tests/` with stdlib `unittest`.

## 11. Reordered roadmap (resolves B1, B9)

| Gate | Phase | Content | Exit test |
|---|---|---|---|
| G0 | 0 | This discovery (now) | owner approves |
| G1 | 1 | Unified `SPEC.md` + contracts (schemas, transition table, CLI contract) | owner approves |
| G2 | A | Schemas, registry, state machines, acceptance split, publish default off | invalid transitions refused; legacy runs resume |
| G3 | B | Spec and Gherkin gates with hashes, TTY approval, invalidation | coding blocked without both approvals; edit after approval invalidates |
| G4 | C | Adapter interface, CLI adapter refactor, native contract, retries, cancel | same workflow runs on two providers |
| G5 | D | Path-level scopes, TDD stages, Red classification, cycle evidence | acceptance table rows 9 to 14 |
| G6 | E | Independent verification, reports, export/import | rows 15 to 23 |
| G7+ | F to H, same release (B1) | Local API and companion, then dashboard (SPEC_DASHBOARD phases 1 to 7), local-only | its own design gate first |

**Proposed first milestone after G1:** Phase A, starting with the run state machine and `acceptance_status`, test-first with `tests/test_state_machine.py`.
