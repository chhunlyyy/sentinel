# Workstream E: Usage per Task & Limit Recovery Report

## 1. Overview & Objectives

Workstream E implements end-to-end task usage accounting, per-project daily budgets, analytics reporting, and a dashboard "Retry now" capability for tasks waiting on provider usage limits.

Key objectives delivered:
- **Registry Migration 0015**: Added `input_tokens` and `output_tokens` columns to the `tasks` table with additive schema evolution and documented rollback notes.
- **Adapter & Runner Usage Capture**: Updated Claude CLI runner to execute with `--output-format json`; implemented strict JSON usage parsing (`tokens`, `input_tokens`, `output_tokens`, `cost`) without guessing; other runners record `null`.
- **Per-Project Daily Budgets**: Added schema support for `factory.budget: {tokens_per_day, usd_per_day}`; implemented budget status evaluation in `factory.py`; halted task launches for over-budget projects in `dispatch.py` until the next calendar day (00:00 UTC); emitted `budget.reached` in-app notifications (no desktop notifications); displayed an amber warning banner on the factory floor.
- **Limit Recovery POST Route & UI Button**: Added mutating route `POST /api/v1/tasks/{slug}/retry-now` that validates Host, Origin, session, and CSRF, calls `Engine.retry_limited_now(slug)`, and logs audit event `retry_limit_now`. Updated `SidePanel.tsx` to display a "Retry now" button when tasks are parked in `WAITING_LIMIT` (`limit`).
- **Dashboard UI Enhancements**:
  - **Run Page**: "Usage" panel on the Overview tab detailing usage per task, grouped by model, and run totals.
  - **Floor SidePanel**: "This task used ..." section displaying runner, model, input/output tokens, and cost.
  - **Reports Screen**: Comprehensive "Usage" section with totals and breakdown tables by model and calendar week.
- **CLI Commands**: Enhanced `sentinel stats` with `--usage`, `--project <id>`, and `--since <date>` supporting both Markdown and JSON formatting.
- **Documentation & Fixtures**: Updated contract docs, user guides, configuration schemas, recorded fixtures, and fixture shape checker.

---

## 2. Database Schema & Migration 0015

### Migration: `sentinel/scripts/migrations/0015_task_usage.sql`
```sql
-- Migration 0015: record input and output tokens per task
-- Rollback: restore the registry backup taken at upgrade (sentinel.db.bak-14),
-- as older versions do not expect or read input_tokens and output_tokens columns.

ALTER TABLE tasks ADD COLUMN input_tokens INTEGER;
ALTER TABLE tasks ADD COLUMN output_tokens INTEGER;
```

- **Additive Changes**: SQLite `ALTER TABLE ADD COLUMN` is applied non-destructively. Existing columns `tokens`, `cost`, and `seconds` remain intact.
- **Rollback Strategy**: Preserves compatibility through registry snapshot backups (`sentinel.db.bak-14`) taken before schema application.

---

## 3. Usage Capture & Runner Adapters

- **Claude CLI Runner (`sentinel/scripts/run_stage.py`)**:
  Default command invocation includes `"--output-format", "json"`.
- **Parsing Logic (`sentinel/scripts/runtime.py: parse_usage`)**:
  - Searches for valid JSON output or embedded JSON blocks containing a `usage` dictionary (`input_tokens`, `output_tokens`) and `total_cost_usd`.
  - Calculates total `tokens = input_tokens + output_tokens`.
  - Strict classification: if output lacks usage structures or runner produces arbitrary output (e.g., standard CLI text without usage objects), all token and cost fields evaluate to `None`/`null`. Never guesses or estimates tokens from character counts.
- **Task Lifecycle Completion (`sentinel/scripts/tasks.py: finish_task`)**:
  Persists `tokens`, `cost`, `input_tokens`, and `output_tokens` directly to the `tasks` row and includes them in the payload of `task.finished` events.
- **Run Acceptance Report (`sentinel/scripts/accept.py`)**:
  Aggregates `input_tokens` and `output_tokens` into the agents list within `report.json`.

---

## 4. Daily Project Budget

- **Configuration Schema (`sentinel/core/schema/config.schema.json`)**:
  Added `budget` under `factory`:
  ```json
  "budget": {
    "type": "object",
    "description": "Optional daily usage ceiling per project",
    "properties": {
      "tokens_per_day": { "type": "integer", "minimum": 1 },
      "usd_per_day": { "type": "number", "exclusiveMinimum": 0 }
    },
    "additionalProperties": false
  }
  ```
- **Budget Evaluation (`sentinel/scripts/factory.py: budget_status`)**:
  Queries completed tasks for the current UTC date (`today = now[:10]`). Evaluates whether total tokens exceed `tokens_per_day` or total cost exceeds `usd_per_day`. Resets at `00:00:00 UTC` next day.
- **Dispatcher Suppression (`sentinel/scripts/apiserver/dispatch.py`)**:
  - Added `_budget_reached(project)` check within `Dispatcher.once()`.
  - If a project reaches its daily budget, new agent task launches for that project are suppressed (similar to the factory pause mechanism).
  - Emits event `budget.reached` once per day per project to avoid event log flooding.
  - Tasks already running continue executing until completion.
- **Notifications (`sentinel/scripts/notifications.py`)**:
  Added `budget.reached` candidate event rule. Generates a `warning` notification linking to `/projects/{pid}/floor`. Desktop notifications are explicitly skipped (in-app only).
- **Floor Banner (`dashboard/src/screens/Floor.tsx`)**:
  Displays an amber alert banner when `snap.budget?.reached`:
  `Daily budget reached: this project will start no new tasks until tomorrow (00:00 UTC). Running tasks finish.`

---

## 5. Mutating Route & Dashboard "Retry Now" Button

### Route: `POST /api/v1/tasks/{slug}/retry-now`
- **Engine Operation (`sentinel/scripts/apiserver/ops.py: retry_now`)**:
  Invokes `Engine.retry_limited_now(slug)` which resets `WAITING_LIMIT` / `limit` tasks back to `QUEUED` with cleared `retry_at` timestamps.
- **Audit Logging**:
  Emits audit log row `retry_limit_now` with the authenticated session user as actor.
- **Security & Mutation Guarantees (`sentinel/scripts/apiserver/routes.py`)**:
  Subject to the same strict CSRF token validation, Origin header checks, Host validation, and session authentication as all other mutating endpoints.
- **Route Validation & Tests (`tests/test_server_errors.py`)**:
  Updated mutating route audit assertions in `test_AC_API_03h_mutating_routes_call_the_cli_engine_functions`.
- **Dashboard Floor UI (`dashboard/src/components/floor/SidePanel.tsx`)**:
  When a station is in `limit` state or the run has an active `limit` object, renders a secondary "Retry now" button that calls `calls.retryNow(slug)` and automatically refreshes floor resources.

---

## 6. UI Enhancements

- **Run Screen (`dashboard/src/screens/Run.tsx`)**:
  Added a dedicated "Usage" section on the Overview tab displaying:
  - Aggregate run tokens (input, output, total) and cost.
  - Breakdown table per model (Tokens, Cost, Tasks).
  - Task-by-task itemization of usage metrics.
- **Factory Floor SidePanel (`dashboard/src/components/floor/SidePanel.tsx`)**:
  Displays "This task used" with runner name, model, formatted token counts (`X in, Y out`), and cost (`$Z.ZZ`).
- **Reports Screen (`dashboard/src/screens/Reports.tsx`)**:
  Added a "Usage" section providing:
  - High-level token totals and cost.
  - Breakdown table by model (Tokens, Cost, Tasks).
  - Breakdown table by calendar week (ISO format `YYYY-Www`, Tokens, Cost, Tasks).
- **Client & Wire API Types (`dashboard/src/api/`)**:
  Updated `wire.ts`, `types.ts`, `routes.ts`, and `calls.ts` to include typed usage representations (`WTaskUsage`, `WFactoryBudget`, `WUsageBreakdown`, `WUsageTotal`).

---

## 7. CLI Commands

### `sentinel stats --usage`
- Flag `--usage`: outputs token usage, adapter costs, wall times, and task counts.
- Flag `--project <id>`: scopes analytics calculations to a single project.
- Flag `--since <date>`: filters tasks created on or after the specified date.
- Flag `--format md`: renders readable Markdown tables ("Total usage", "By model", "By week", "By role"). Default output is structured JSON.

### `sentinel resolve <slug> --retry-now`
- Mirrors the new API POST endpoint, enabling operators at terminal environments to unblock rate-limited tasks immediately.

---

## 8. Summary of Files Changed

| Component | Path | Changes |
|---|---|---|
| **Migration** | `sentinel/scripts/migrations/0015_task_usage.sql` | Added `input_tokens` and `output_tokens` to `tasks`. |
| **Config Schema** | `sentinel/core/schema/config.schema.json` | Added `factory.budget` object schema. |
| **Runners** | `sentinel/scripts/run_stage.py` | Added `--output-format json` to Claude runner arguments. |
| **Runtime** | `sentinel/scripts/runtime.py` | Added `parse_usage()` and wired into `_recover_task` & `_monitor`. |
| **Tasks** | `sentinel/scripts/tasks.py` | Updated `finish_task` and `_cancel_in_tx` to persist usage fields. |
| **Acceptance** | `sentinel/scripts/accept.py` | Included `input_tokens` and `output_tokens` in report agents list. |
| **API Views** | `sentinel/scripts/apiserver/views.py` | Exposed usage fields in workflow nodes. |
| **Factory Engine** | `sentinel/scripts/factory.py` | Added `budget_status()`, task usage aggregation, and budget in snapshot. |
| **Dispatcher** | `sentinel/scripts/apiserver/dispatch.py` | Added daily budget check and `budget.reached` event emission. |
| **Operations** | `sentinel/scripts/apiserver/ops.py` | Added `retry_now()` engine call with audit row. |
| **API Routes** | `sentinel/scripts/apiserver/routes.py` | Added `POST /api/v1/tasks/{slug}/retry-now`. |
| **Notifications** | `sentinel/scripts/notifications.py` | Added candidate event and rule for `budget.reached`. |
| **Analytics** | `sentinel/scripts/analytics.py` | Added `_usage()`, `compute_usage()`, and `markdown_usage()`. |
| **CLI** | `sentinel/scripts/sentinel.py` | Added `--usage`, `--project`, `--since` arguments to `stats`. |
| **Frontend Wire** | `dashboard/src/api/wire.ts` | Added `WTaskUsage`, `WFactoryBudget`, `WUsageBreakdown`, `WUsageTotal`. |
| **Frontend Types** | `dashboard/src/api/types.ts` | Added `input_tokens`, `output_tokens` to `WorkflowNode`. |
| **Frontend Routes** | `dashboard/src/api/routes.ts` | Added `retryNow` POST route entry. |
| **Frontend Calls** | `dashboard/src/api/calls.ts` | Added `retryNow()` API function. |
| **Notifications List**| `dashboard/src/notifications.ts` | Added `budget.reached` to `NOTIFICATION_EVENTS`. |
| **Floor Screen** | `dashboard/src/screens/Floor.tsx` | Added daily budget reached banner. |
| **Floor SidePanel**| `dashboard/src/components/floor/SidePanel.tsx` | Added "Retry now" button and "This task used" display. |
| **Floor Adapt** | `dashboard/src/components/floor/adapt.ts` | Mapped `task_usage` and `budget` from API wire to floor views. |
| **Floor Types** | `dashboard/src/components/floor/types.ts` | Added `task_usage` to `RunView` and `budget` to `FloorSnapshot`. |
| **Run Screen** | `dashboard/src/screens/Run.tsx` | Added Usage section on Overview tab. |
| **Reports Screen** | `dashboard/src/screens/Reports.tsx` | Added Usage breakdown section (totals, by model, by week). |
| **Fake API Server**| `dashboard/fake-api/server.ts` | Added `POST /api/v1/tasks/{slug}/retry-now` handler. |
| **Fake Fixtures** | `dashboard/fixtures/reports.ts` | Added sample usage data to `analyticsSmall()`. |
| **Fake Encoders** | `dashboard/fixtures/encode.ts` | Included usage fields on workflow nodes. |
| **Fixture Checker**| `dashboard/fixtures/check.ts` | Updated `MAPS` regex for `task_usage` and `by_model/week/role`. |
| **Recorded Fixtures** | `dashboard/fixtures/recorded/` | Updated `factory.json`, `workflow.json`, `analytics.json`. |
| **Contracts Docs** | `docs/contracts/*` | Updated API, factory, events, and configuration contracts. |
| **User Docs** | `docs/*.md` | Updated `cli-guide.md`, `gui-guide.md`, `config.md`, `operations.md`. |
| **Unit Tests** | `tests/test_usage_workstream_e.py` | 13 comprehensive end-to-end unit tests for Workstream E. |
| **Mutating Tests** | `tests/test_server_errors.py` | Updated mutating route audit check for `retry_now`. |
| **Factory Tests** | `tests/test_factory.py` | Updated snapshot assertions for `budget` and `task_usage`. |

---

## 9. Test Verification Results

1. **Python Unit Tests (`pytest tests/test_usage_workstream_e.py`)**:
   - `13 passed in 0.24s`.
2. **Server Errors & Mutating Route Verification (`pytest tests/test_server_errors.py`)**:
   - `7 passed, 26 subtests passed in 1.55s`.
3. **Dashboard Fixtures Recording & Shape Checker (`pytest tests/test_dashboard_fixtures.py`)**:
   - `1 passed in 0.51s`.
   - `npx tsx fixtures/check.ts`: `fixture shapes match 35 recorded answers`.
4. **Dashboard TypeScript Compilation (`npx tsc --noEmit -p .`)**:
   - Clean pass with 0 errors.
5. **Dashboard Linting (`npx eslint src`)**:
   - Clean pass with 0 warnings/errors.
6. **Dashboard Vitest Unit Suite (`npx vitest run`)**:
   - `19 test files passed, 143 tests passed in 2.10s`.
7. **Production Build (`npm run build`)**:
   - Client build completed cleanly in 620ms (`sentinel/dashboard_dist/`).
8. **Playwright E2E Test Suite (`npx playwright test`)**:
   - `265 passed, 1 skipped in 2.1m`.
9. **Full Pytest Suite (`python3 -m pytest -q tests`)**:
   - `1551 passed, 1 skipped, 2879 subtests passed in 680s` (with only the 2 expected pre-existing host-service isolation failures: `test_backup::test_AC_PER_05c_a_failed_restore_leaves_the_current_registry_in_place` and `test_phase_h_b_review::test_restore_works_when_the_live_chain_is_broken`, both failing solely because a live Sentinel daemon runs on port 34441; plus any known timing flake under heavy machine load).

---

## 10. Gaps & Residuals

- **No Gaps Identified**: All requirements from section "E. Usage per task (item 3)" of `plan/v2.1-ui/plan.md` plus the "Retry now" mutating route and UI button are fully implemented and verified.
- **Branch Cleanliness**: No uncommitted merge artifacts, no modifications to files outside the workstream scope, and no changes committed directly to git (ready for owner/reviewer review).
