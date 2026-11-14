# Orchestration Architecture (1.1.0, draft for G1)

Requirements: `SPEC.md` sections 9 to 14. Transition table: `docs/contracts/state-transitions.md`.

## 1. Authority model

```text
orchestrator (AI tool)   --propose-->   engine   --accept / refuse + reason-->
human (TTY, dashboard)   --decide--->   engine   (approvals, final acceptance, policy gates)
engine                   --self----->   engine   (evidence-based transitions)
```

Every call goes through `engine.transition(run, target, actor, payload)`:

1. Look up `(current, target)` in the table. Missing: refuse `E_TRANSITION`.
2. Check the actor is allowed. Wrong: refuse `E_ACTOR`.
3. Re-hash approved artifacts the target depends on. Mismatch: mark approval `INVALIDATED`, refuse `E_APPROVAL_STALE`, move the run back to the matching review state.
4. Check preconditions and required evidence rows exist and pass. Missing: refuse `E_PRECONDITION` with the list.
5. Check policy (`policies` in config snapshot). Human required: move to `NEEDS_HUMAN`.
6. Write the new state and an event in one SQLite transaction. Write `state.json` view.

## 2. Workflow generation

`engine.plan(run)` builds the task graph from:

- tier (from triage, only rises)
- task type (feature, bug, docs, refactor, migration, security)
- shape and `cross_repo` order (existing)
- approved Gherkin (one TDD cycle per behavior group: a Feature, or a Rule inside it)

The graph is stored. Re-planning happens only after a tier rise or a new approval, and is recorded as an event.

### Stages per tier

| Tier | Gates | Execution | Verification |
|---|---|---|---|
| 1 | spec-lite, Gherkin | cycles | targeted + full tests, build, lint, typecheck, scope |
| 2 | spec-lite, Gherkin | [repro as cycle 1 Red] cycles | as tier 1 + secret scan, dependency audit |
| 3 | full spec, Gherkin | cycles, reviewer, targeted QA, promotion | as tier 2 + migration safety, docs |
| 4 | full spec, Gherkin, security gate | cycles, hardener, reviewer, full QA, promotion | as tier 3 + mutation, rollout, retrospective |
| docs | spec only | docs stage | link check, docs build if configured |

## 3. TDD cycle

```text
PLANNED
  -> RED_RUNNING      dispatch tdd_red (write: test globs of target repos)
  -> engine: scope check; run targeted tests; classify
       assertion failure on new tests, rest unchanged      -> RED_VERIFIED
       compile / environment / missing dep / preexisting -> REJECTED(red), route back to tdd_red with the classified output (retry cap)
       unknown                                            -> NEEDS_HUMAN
  -> GREEN_RUNNING    dispatch tdd_green (write: production globs; approved test files read-only)
  -> engine: scope check (test file touched = fail); run targeted tests
       pass -> GREEN_VERIFIED ; fail -> back to tdd_green (cap)
  -> REFACTOR_RUNNING dispatch tdd_refactor (write: production globs)
  -> engine: scope check; run targeted + related tests
       pass -> REFACTOR_VERIFIED -> CYCLE_ACCEPTED
       fail -> refactor rejected; working tree restored to the GREEN snapshot only with
               the human's consent (default: route back to tdd_refactor), cap
```

"Rest unchanged" = the set of failing tests outside the new ones equals the baseline set recorded at pre-flight.

### Failure classification (per profile)

Profiles gain `test_report` (how to get structured results) and `failure_patterns`:

| Class | Signal |
|---|---|
| assertion | structured report (JUnit XML, Jest JSON, pytest junit) shows the new tests failing with assertion errors |
| compile | build step exit non-zero before tests ran; patterns like `error: cannot find symbol`, `TS2304` |
| environment | connection refused, port in use, DB unreachable patterns |
| missing_dependency | module or package not found patterns |
| preexisting_failure | a failing test that also failed at baseline |
| unknown | anything else |

Profiles without a structured report fall back to patterns; unknown is never accepted.

## 4. Verification and acceptance

`engine.verify(run)` runs every check required by tier and policy, each as an evidence row (command, exit code, output file hash, counts, time). It reuses `release_check.Checker` and adds the diff-scope check (union of task write scopes vs the actual diff from the baseline SHAs).

`engine.acceptance(run)` returns `accepted` only if all of SPEC VER-03 hold, otherwise `rejected` with reasons. The human final acceptance can confirm `accepted` or turn it into `rejected`; it cannot turn `rejected` into `accepted`.

## 5. Failure routing and caps

| Failure | Routed to | Cap |
|---|---|---|
| Red rejected | tdd_red | `limits.red_retries` (default 2) |
| Green fails | tdd_green | `limits.green_retries` (default 3) |
| Refactor fails | tdd_refactor | `limits.refactor_retries` (default 2) |
| Review blocker | owning cycle, new Red if behavior is missing | `limits.review_rounds` |
| QA code bug | new cycle with a Red reproducing it | `limits.qa_rounds` |
| QA spec gap | specifier, then spec review (approval invalidated) | n/a, human |
| Verification fail | owning repo green or refactor | `limits.release_check_rounds` |
| Provider failure | fallback provider per policy, else task FAILED | `policies.provider_retries` |

At any cap: `NEEDS_HUMAN` with the open items.

## 6. Interaction with the AI-tool skill

The rewritten `skills/sentinel/SKILL.md` loop:

```text
loop:
  next = sentinel next <slug> --json      # engine says what is allowed now
  if next.kind == "human":   tell the requester exactly what to approve and how; stop
  if next.kind == "task":    run it (headless via `sentinel task run`, or native subagent with the task file)
                             then `sentinel task complete <task-id>` -> engine validates + checks evidence
  if next.kind == "done":    report
```

The skill no longer decides order, loops or acceptance.

## 7. Legacy runs

`state.json` without `schema_version: 2` is handled by the 0.1 code paths (`run update`, `resume`). `sentinel run new` creates version 2 runs unless `--legacy` is passed.
