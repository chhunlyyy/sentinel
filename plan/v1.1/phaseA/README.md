# Phase A: Deterministic core (Gherkin for review)

Scope (from `SPEC.md`): ORC-01, ORC-03 (tier rule only), ORC-08, SM-01 to SM-05, PER-01 to PER-05, C-29 (acceptance split), C-35 (publish default), C-36 (registry concurrency).

Not in Phase A: approval gates and hashing (Phase B), adapters (C), TDD and scopes (D), verification (E), dashboard (F to H). Phase A only builds the machinery those phases use.

## Files

| Feature | Scenarios | Main requirements |
|---|---|---|
| `features/run_state_machine.feature` | 12 (+ outline rows) | ORC-01, ORC-03, SM-01 |
| `features/entity_state_machines.feature` | 9 | SM-03, SM-04, SM-05 |
| `features/acceptance_status.feature` | 6 | SM-02, C-29 |
| `features/registry.feature` | 10 | PER-01 to PER-05, ORC-08, C-36 |
| `features/publish_default.feature` | 3 | C-35, OPS-03 |

## Coverage table

| Category | Status |
|---|---|
| Happy path | covered |
| Invalid input | covered (undefined transitions, unknown state, tier lowering, run update on v2) |
| Missing required fields | covered (decisions.md precondition) |
| Boundary | covered (tier factor thresholds) |
| Empty / null | not applicable to Phase A: no user-entered content yet; artifact validation is Phase B |
| Authentication | not applicable: no network surface in Phase A (Phase F) |
| Authorization | covered (actor checks on run, task, approval, cycle, acceptance) |
| Data integrity | covered (atomic state plus event, append-only events) |
| Duplicate submissions | covered by the concurrency scenario |
| Concurrency | covered (two writers) |
| Error handling | covered (error codes, exit code 5) |
| External service failure | not applicable: no provider calls in Phase A |
| Database failure | covered (failed migration, failed event write) |
| Regression | covered (legacy runs, run finish mapping, 95 selftest checks stay green) |
| Performance / security | not applicable in Phase A |

## How the tests will run

- Unit scenarios: stdlib `unittest` in `tests/`, one test per scenario, test names carry the AC id (for example `test_AC_ORC_01c_jumping_over_gates_is_refused`).
- Integration scenarios: new checks added to `sentinel/scripts/selftest.py`, named after the AC id.
- Gate for Phase A completion: all Phase A tests pass, the 95 existing selftest checks pass, evidence recorded in `IMPLEMENTATION_STATUS.md`.
