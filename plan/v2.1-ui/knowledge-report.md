# Sentinel 2.1 Item 5 Implementation Report: Knowledge in the Flow

**Branch:** `v2.1-knowledge`  
**Workstream:** F (Knowledge in the flow - Item 5)  
**Status:** Completed

---

## 1. Summary of Changes

### Backend & Engine
- **Search & Related Knowledge (`sentinel/scripts/knowledge.py`):**
  - Added `parse_invariants(shared_dir)`: extracts structured rules and IDs from `invariants.md`.
  - Added `search_related_knowledge(shared_dir, q, limit)`: searches across change records (from `index.json`) and active project invariants using token matching, ranked by recency and relevance.
- **Project Knowledge Collection (`sentinel/scripts/kb_context.py`):**
  - Added `collect_project_knowledge(...)`: collects structured records, module summaries, repo summary, and invariants.
  - Added `format_project_knowledge(...)`: formats structured data into markdown for the prompt.
  - Refactored `render_project_knowledge(...)` to delegate to structured collection and formatting.
- **Prompt Rendering & Recording (`sentinel/scripts/runtime.py`):**
  - `Runtime._render_prompt` records structured knowledge into `<task_dir>/knowledge.json` during task setup for specifier, gherkin, coder, and reviewer roles.
- **Engine Artifact & Gate Storage (`sentinel/scripts/engine.py`):**
  - `Engine._store_version` copies `<task_dir>/knowledge.json` into `<artifacts_dir>/<kind>-v<version>.knowledge.json`.
  - Added `Engine.knowledge_for_gate(slug, gate, version)`: retrieves the stored knowledge JSON for specification or gherkin review, with fallback to project knowledge.
- **API Server Views & Routes (`sentinel/scripts/apiserver/views.py`, `readroutes.py`, `routes.py`):**
  - Added `knowledge_used` field to `_gate_extra` on specification and gherkin reviews (`/tasks/{slug}/specification` and `/tasks/{slug}/gherkin`).
  - Added `readroutes.knowledge_related(projects, project, query)` to validate query parameters (`limit` must be a positive integer) and return `{ records, invariants }`.
  - Added `Route("GET", "knowledge_related", "projects/{pid}/knowledge/related", h_knowledge_related)` with `@_project_read` permission and scrubbing.

### Frontend (Dashboard & Fake API)
- **API Client & Types (`dashboard/src/api/`):**
  - Defined wire interfaces and types: `WKnowledgeUsed`, `WKnowledgeRelated`, `WKnowledgeRelatedRecord`, `WKnowledgeRelatedInvariant`.
  - Added route `knowledgeRelated` in `routes.ts`, caller `relatedKnowledge` in `calls.ts`, and adapt mapping in `adapt.ts`.
  - Extended `SpecificationAnswer` and `GherkinAnswer` with `knowledge_used`.
- **New Task Screen (`dashboard/src/screens/Tasks.tsx`, `CreateTaskForm.tsx`):**
  - Added debounced `relatedKnowledge` search as request text changes, updating the "Knowledge found" side panel listing related past changes and invariants, with a direct link to the project knowledge base.
  - Added factory floor slots occupancy note from the factory snapshot: `"Slots: N of M busy in {pid}. ... (position K in the queue)"`.
  - Added "Save as draft" feature: drafts are stored in `localStorage` under `sentinel_task_draft_${pid}`, isolated per project, surviving page reload, and cleared automatically upon successful task submission. All storage operations are safely wrapped in `try/catch`.
- **Approve Screen (`dashboard/src/screens/Approvals.tsx`):**
  - Added "Knowledge used" tab in specification and gherkin review views (`SpecBody`).
  - Implemented `KnowledgeUsedView` displaying change records read (key, title, repo, date, summary), active invariants, and module/repository summaries that agents read.
- **Formatting (`dashboard/src/format.ts`):**
  - Added `formatDate(isoString)` helper.
- **Fake API & Fixtures (`dashboard/fake-api/server.ts`, `dashboard/fixtures/`):**
  - Added fake endpoint `GET /api/v1/projects/{pid}/knowledge/related`.
  - Updated fixture encoders and recorded fixtures with `knowledge_used` shape parity verified by `fixtures.test.ts` and `test_dashboard_fixtures.py`.

### Documentation
- **`docs/contracts/api-contracts.md`**: Documented `GET /projects/{pid}/knowledge/related` endpoint and `knowledge_used` field in review responses.
- **`docs/gui-guide.md`**: Documented the "Knowledge found" side panel, factory slots note, "Save as draft" on New Task, and the "Knowledge used" review tab on Approvals.
- **`docs/knowledge.md`**: Documented how agents record knowledge into `knowledge.json`, version preservation for reviews, and the related knowledge search API.

---

## 2. Test Verification Results

1. **Python Unit & Contract Tests:**
   - `python3 -m pytest -q tests/test_docs.py tests/test_knowledge_related.py tests/test_dashboard_fixtures.py`:
     - **32 passed, 742 subtests passed** in 9.54s
   - `python3 -m pytest -q tests/test_server_read.py tests/test_api_v2_setup.py`:
     - **47 passed, 26 subtests passed** in 25.30s

2. **Dashboard Typecheck, Lint, and Unit Tests:**
   - `npx tsc --noEmit -p .`: **0 errors**
   - `npx eslint src`: **0 errors**
   - `npx vitest run`: **19 test files passed, 143 tests passed** in 2.86s
     - Included unit tests in `createTaskForm.test.tsx` verifying draft saving, restoration, clearing, and error resilience.
     - Included fixture shape checker `fixtures.test.ts`.

3. **Dashboard Build:**
   - `npm run build`: **Built successfully** in 600ms without errors.

4. **Playwright E2E Tests:**
   - `npx playwright test`: **264 passed, 1 skipped** (standard offline test skipped) in 2.1m
     - Verified `AC-TSK-01q` (debounced Knowledge found side panel, slots note, save as draft persistence across reload).
     - Verified `AC-SPA-04f` (Knowledge used tab on specification review showing records and invariants).
     - Verified all 42 automated accessibility checks (WCAG 2.1 AA) pass with 0 violations.

---

## 3. Unfinished Work & Notes
- None. All requirements of Wave 2 Item 5 (backend search route, knowledge recording, approval tab, new task knowledge panel, slots note, draft saving, fake API, fixtures, unit/e2e tests, and documentation) are fully implemented and verified.
- No files were committed in accordance with instructions.
