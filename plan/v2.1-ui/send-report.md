# Sentinel 2.1 Workstream H Implementation Report: Send an idea from any AI session to Sentinel

**Branch:** `v2.1-send`  
**Workstream:** H ("Send an idea from any AI session to Sentinel", per `plan/v2.1-ui/plan.md`)  
**Status:** Completed

---

## 1. Overview of Delivered Features

This workstream implements the end-to-end pathway allowing any AI agent or user session to formulate a request and pre-drafted specification and send it into Sentinel as a new version 2 task run.

### Key Capabilities & Security Controls
1. **CLI Flags on `sentinel run new`**:
   - `--request-file <path>`: reads the full request from a file (or from stdin when `<path>` is `-`). Mutually exclusive with `--request`. Applies `scrub.MAX_BYTES` (64 KiB) limit and secret scrubbing.
   - `--spec-file <path>`: reads a pre-drafted specification (or stdin via `-`). Applies `scrub.MAX_BYTES` and secret scrubbing. Validates specification structure (required sections based on tier and type).
   - Stored as specification draft v1 with `provenance: "imported from a session"`.
2. **Engine Execution Flow**:
   - Triage runs normally (factors determine run tier).
   - Specifier agent task is skipped for v1 (the engine auto-advances the imported spec from `DRAFT` to `IN_REVIEW` and transitions the run to `SPECIFICATION_REVIEW`).
   - Human approval gate is strictly enforced: an imported spec never counts as approved; approval requires a human session/TTY with the typed 8-character hash prefix.
   - Request changes (`R6`) sends the task to the specifier agent to generate v2 as usual.
   - Agent run creation remains permitted (agents may create runs with `run new`; only approval/acceptance is human-only).
3. **Dashboard & API Server**:
   - `POST /api/v1/projects/{pid}/tasks` accepts optional `spec` string field.
   - Size limit and project secret scrubber applied.
   - Create task form in the dashboard provides an optional "I already have a spec" checkbox with a textarea and file upload support.
   - LocalStorage draft persistence saves and restores the imported spec per project.
   - Review page displays provenance (`(imported from a session)`) next to the version badge and in version history rows.
4. **Agent Skill `/sentinel-send`**:
   - Installed at `skills/sentinel-send/SKILL.md` following existing Sentinel skill conventions.
   - Guides any AI tool to summarize the current conversation into a request and optional spec, check project status, write temporary files, and run `sentinel run new ... --driver engine --request-file ... [--spec-file ...]`.
   - Never auto-approves.
5. **Documentation**:
   - Updated `docs/cli-guide.md`, `docs/gui-guide.md`, `docs/workflow.md`, `docs/contracts/state-transitions.md`, and `docs/contracts/api-contracts.md`.

---

## 2. Files Modified & Created

### Database & Migrations
- `sentinel/scripts/migrations/0016_artifact_provenance.sql`: Created migration adding `provenance TEXT` column to `artifacts` table.

### CLI & Engine (Python)
- `sentinel/scripts/sentinel.py`:
  - Added `--request-file` and `--spec-file` arguments to `run new`.
  - Added `_read_cli_file(...)` with size checks, UTF-8 validation, and secret scrubbing.
  - Mutual exclusion between `--request` and `--request-file`, and single-stdin enforcement.
  - Forwarded `spec` to `engine.create_run`.
  - Added provenance display to `sentinel review <slug> spec|gherkin`.
- `sentinel/scripts/engine.py`:
  - Updated `_store_version` to record `provenance` in `artifacts` and support initial `approval_state` (`DRAFT`).
  - Added `_prepare_imported_spec(...)` to validate and normalize YAML front matter and required sections.
  - Added `_has_imported_spec_v1(...)` and `_advance_imported_spec(...)`.
  - Updated `create_run(...)` to accept `spec` and persist imported spec as draft v1.
  - Updated `_move(...)` to advance imported spec v1 past the specifier stage to `SPECIFICATION_REVIEW`.
  - Updated `review(...)` to include `provenance` in review info and fall back gracefully if tier is uncomputed.
- `sentinel/scripts/artifacts.py`:
  - Made `required_sections(...)` resilient to `run_tier=None`.
- `sentinel/scripts/apiserver/ops.py`:
  - Added `spec` to allowed fields in `parse_create`.
  - Added byte limit checks and secret scrubbing for `spec`.
  - Passed `spec` to `eng.create_run`.
- `sentinel/scripts/apiserver/routes.py`:
  - Passed project scrubber to `ops.create_run`.
- `sentinel/scripts/apiserver/views.py`:
  - Included `provenance` in `_gate_extra` versions list, `specification(...)`, and `specification_version(...)`.

### Dashboard & API Client (TypeScript / React)
- `dashboard/src/api/wire.ts`:
  - Added `provenance?: string | null;` to `WVersion`, `WReview`, and `WSpecVersion`.
- `dashboard/src/api/types.ts`:
  - Added `provenance?: string;` to `VersionRow` and `SpecificationAnswer`.
  - Added `spec?: string;` to `CreateTaskBody`.
- `dashboard/src/api/adapt.ts`:
  - Adapted `provenance` in `versionRow`, `specification`, and `specificationVersion`.
- `dashboard/fixtures/encode.ts`:
  - Added `provenance` to `specification`, `specVersion`, and `versions`.
- `dashboard/fixtures/recorded/`:
  - Recorded fixture shapes updated for `specification.json`, `specification_version.json`, and `gherkin.json` with `provenance: null`.
- `dashboard/fake-api/server.ts`:
  - Added `spec` to allowed fields for `POST /api/v1/projects/{pid}/tasks`.
  - Handled imported spec creation, setting version 1, `IN_REVIEW`, and `provenance: 'imported from a session'`.
- `dashboard/src/components/CreateTaskForm.tsx`:
  - Added "I already have a spec" checkbox toggle.
  - Added Specification textarea and file upload handler (`FileReader` UTF-8).
  - Preserved and restored `spec` in localStorage project draft.
  - Submitted `spec` in `CreateTaskBody`.
- `dashboard/src/screens/Approvals.tsx`:
  - Displayed `view.provenance` next to version badge on review page.
  - Displayed `v.provenance` in `VersionsList`.

### Skills
- `skills/sentinel-send/SKILL.md`:
  - Created skill definition and instructions for summarizing sessions into Sentinel runs.

### Documentation
- `docs/cli-guide.md`: Documented `--request-file`, `--spec-file`, and added `/sentinel-send` to skills table.
- `docs/gui-guide.md`: Documented "I already have a spec" field and review provenance display.
- `docs/workflow.md`: Documented `--request-file` and `--spec-file` in run creation.
- `docs/contracts/state-transitions.md`: Documented imported spec draft v1 and skipping specifier for v1.
- `docs/contracts/api-contracts.md`: Documented `spec` in task creation body and `provenance` in review responses.

### Tests
- `tests/test_send_idea.py`: Comprehensive test suite with 17 tests covering CLI flags, mutual exclusion, size limits, scrubbing, draft v1 creation, triage execution, specifier skipping for v1, human approval requirement, change request causing v2 specifier task, provenance in review and API, and skill file verification.
- `dashboard/tests/unit/createTaskForm.test.tsx`: Form unit tests for "I already have a spec", draft save/restore, and submission.
- `dashboard/tests/unit/reviewProvenance.test.tsx`: Unit tests for provenance adapter mapping.

---

## 3. Test Verification Results

### 1. New Feature Tests (TDD)
- `python3 -m unittest tests/test_send_idea.py`:
  - **17 tests passed** (100% pass) in 1.80s.
- `cd dashboard && npx vitest run tests/unit/createTaskForm.test.tsx tests/unit/reviewProvenance.test.tsx`:
  - **13 tests passed** in 2.15s.

### 2. Full Test Suites
- **Full Python Pytest Suite (`python3 -m pytest -q tests`)**:
  - **1563 passed, 1 skipped, 2 failed** (known environment-only failures due to live Sentinel server running on pid 1006613, port 34441, as noted in task prompt: `VerifyRestore::test_AC_PER_05c_a_failed_restore_leaves_the_current_registry_in_place` and `T::test_restore_works_when_the_live_chain_is_broken`).
- **Documentation Verification (`python3 -m unittest tests/test_docs.py`)**:
  - **24 tests passed** in 7.22s.
- **Fixture Verification (`SENTINEL_RECORD_FIXTURES=1 python3 -m pytest tests/test_dashboard_fixtures.py`)**:
  - **Passed** with 0 shape mismatches.
- **Dashboard Typecheck, Lint & Vitest (`cd dashboard && npx tsc --noEmit -p . && npx eslint src && npx vitest run`)**:
  - TypeScript compilation: **0 errors**.
  - ESLint: **0 errors**.
  - Vitest: **20 test files passed, 150 tests passed** in 2.72s.
- **Dashboard Build (`cd dashboard && npm run build`)**:
  - Built production bundle in 628ms without warnings or errors.
- **Playwright End-to-End Suite (`cd dashboard && npx playwright test`)**:
  - **267 passed, 1 skipped** in 2.1m.

---

## 4. Gaps & Known Constraints

- **None**: All deliverables defined in `plan/v2.1-ui/plan.md` section H have been implemented and verified.
- **Security Boundaries Preserved**:
  - Imported specs are never auto-approved.
  - Spec review gate strictly requires typed hash prefix from a human session on a TTY or the dashboard.
  - Scrubbing and size caps (`scrub.MAX_BYTES`) apply equally to request and spec files.
  - Floor components (`Floor.tsx` and `floor/**`) were untouched.
  - Real Sentinel background service and configuration (`~/.config/sentinel`) were not modified.
