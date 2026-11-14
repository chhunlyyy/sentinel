# State Transitions (1.1.0, draft for G1)

Actors: `E` engine, `O` orchestrator (AI tool through the CLI), `H` human (TTY or dashboard). Any transition not listed is refused with `E_TRANSITION`.

## 1. Run

| # | From | To | Actor | Preconditions | Evidence / effect | On failure |
|---|---|---|---|---|---|---|
| R1 | (none) | CREATED | O, H | slug valid and free; lock acquired | baseline SHAs, config snapshot | refuse |
| R2 | CREATED | TRIAGED | O | factor values submitted | engine computes tier = max(matrix, requested); stored | refuse |
| R3 | TRIAGED | PLANNED | O, E | tier 3+: `decisions.md` exists | task graph stored | refuse |
| R4 | PLANNED | SPECIFICATION_REVIEW | E | specifier task COMPLETED; spec validates | artifact version + hash; approval IN_REVIEW | back to specifier (cap) |
| R5 | SPECIFICATION_REVIEW | SPECIFICATION_APPROVED | H | approval hash == current spec hash | approval APPROVED | `E_APPROVAL_STALE` |
| R6 | SPECIFICATION_REVIEW | PLANNED | H | decision = request changes | comments to specifier brief | n/a |
| R7 | SPECIFICATION_REVIEW | CANCELLED | H | decision = reject | execution_status cancelled, acceptance rejected | n/a |
| R8 | SPECIFICATION_APPROVED | GHERKIN_REVIEW | E | test_designer COMPLETED; Gherkin validates; spec hash unchanged | artifact version + hash | back to test_designer (cap) |
| R9 | GHERKIN_REVIEW | GHERKIN_APPROVED | H | approval hash == current Gherkin hash; spec approval still valid | approval APPROVED | `E_APPROVAL_STALE` |
| R10 | GHERKIN_REVIEW | SPECIFICATION_APPROVED | H | decision = request changes | comments to test_designer | n/a |
| R11 | GHERKIN_REVIEW | CANCELLED | H | decision = reject | as R7 | n/a |
| R12 | GHERKIN_APPROVED | EXECUTING | E | both approvals valid by hash; policy gates before execution satisfied (tier 4 security gate) | cycles planned | NEEDS_HUMAN |
| R13 | EXECUTING | VERIFYING | E | all cycles CYCLE_ACCEPTED; required extra stages (hardener) COMPLETED | n/a | stay |
| R14 | VERIFYING | REVIEWING | E | all required verification evidence passed | evidence rows | route failures (see orchestration doc), stay |
| R15 | REVIEWING | COMPLETED | E | reviews and QA done; no open blocker or major; acceptance computed | execution completed; acceptance accepted or rejected | NEEDS_HUMAN at cap |
| R16 | VERIFYING, REVIEWING | EXECUTING | E | a finding needs a new cycle | new cycle planned | n/a |
| R17 | any active | SPECIFICATION_REVIEW | E | spec hash changed after approval | spec and Gherkin approvals INVALIDATED | n/a |
| R18 | GHERKIN_APPROVED, EXECUTING, VERIFYING, REVIEWING | GHERKIN_REVIEW | E | Gherkin hash changed after approval | Gherkin approval INVALIDATED | n/a |
| R19 | any active | NEEDS_HUMAN | E | cap reached, unknown Red class, scope violation, policy gate | reason recorded | n/a |
| R20 | NEEDS_HUMAN | previous state | H | human decision recorded | audit | n/a |
| R21 | any active | BLOCKED | E | external dependency missing (repo gone, runner missing) | reason | n/a |
| R22 | BLOCKED | previous state | E, H | blocker resolved (re-check passes) | n/a | stay |
| R23 | any active | CANCELLED | H | n/a | running tasks cancelled; lock released | n/a |
| R24 | any active | FAILED | E | unrecoverable error | lock released | n/a |
| R25 | COMPLETED | COMPLETED | H | final human acceptance; can confirm accepted or set rejected, never rejected to accepted | approval `acceptance` | refuse |

Docs-only runs skip R8 to R11: `SPECIFICATION_APPROVED -> EXECUTING` (R12d) with the spec approval as the only gate.

"Any active" = not COMPLETED, FAILED, CANCELLED.

## 2. Task

| From | To | Actor | Condition |
|---|---|---|---|
| CREATED | QUEUED | E | dependencies complete |
| QUEUED | RUNNING | E | no write-scope overlap with running tasks; parallel limit |
| RUNNING | WAITING_FOR_INPUT | E | native adapter, or agent asked a question |
| WAITING_FOR_INPUT | RUNNING | O, H | answer supplied, or orchestrator picked the native task up |
| RUNNING, WAITING_FOR_INPUT | COMPLETED | E | process ended (or `task complete` called); result.json valid; no scope violation |
| RUNNING, WAITING_FOR_INPUT | FAILED | E | non-zero exit, timeout, invalid result, scope violation |
| RUNNING | BLOCKED | E | agent result status blocked |
| any non-final | CANCELLED | H, E | cancel requested |

`O` can only call `task complete`; the engine decides COMPLETED or FAILED.

## 3. Approval

| From | To | Actor |
|---|---|---|
| DRAFT | IN_REVIEW | E (artifact validated) |
| IN_REVIEW | APPROVED / CHANGES_REQUESTED / REJECTED | H only |
| APPROVED | INVALIDATED | E (hash mismatch, or upstream approval invalidated) |
| CHANGES_REQUESTED | DRAFT | E (new version produced) |

## 4. TDD cycle

| From | To | Actor | Condition |
|---|---|---|---|
| PLANNED | RED_RUNNING | E | Gherkin approval valid |
| RED_RUNNING | RED_VERIFIED | E | scope ok; classification = assertion on new tests; rest equals baseline |
| RED_RUNNING | PLANNED (retry) | E | other classification, under cap |
| RED_VERIFIED | GREEN_RUNNING | E | n/a |
| GREEN_RUNNING | GREEN_VERIFIED | E | scope ok; no approved test file changed; targeted tests pass |
| GREEN_VERIFIED | REFACTOR_RUNNING | E | n/a |
| REFACTOR_RUNNING | REFACTOR_VERIFIED | E | scope ok; targeted and related tests pass |
| REFACTOR_VERIFIED | CYCLE_ACCEPTED | E | evidence rows complete |
| any running | REJECTED | E | cap reached; run goes to NEEDS_HUMAN |

## 5. Error codes

`E_TRANSITION`, `E_ACTOR`, `E_PRECONDITION`, `E_APPROVAL_STALE`, `E_APPROVAL_MISSING`, `E_INTEGRITY`, `E_SCOPE`, `E_RESULT_SCHEMA`, `E_LOCKED`, `E_POLICY`, `E_NOT_TTY`, `E_VALIDATION`, `E_NOT_FOUND`.
