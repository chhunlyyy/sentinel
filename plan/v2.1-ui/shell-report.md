# Workstream B ("Look" and "Shell") Completion Report

**Date:** 2026-11-21  
**Branch:** `v2.1-shell`  
**Status:** Complete  

---

## 1. Summary of Changes

### A. Top Header Replacement (`dashboard/src/App.tsx`)
- Replaced the legacy left sidebar navigation on every screen with the new persistent top navigation header matching the mockups in `plan/v2.1-ui/mockup/`.
- **Branding:** Added Sentinel logo icon and "Sentinel" wordmark linking to root (`#/`).
- **Primary Navigation Items:**
  - `Factory floor` (`#/floor`)
  - `New task` (`#/tasks/new`)
  - `Approvals` (`#/approvals`) with dynamic badge showing pending approval count
  - `Projects` (`#/projects`)
  - `Runs` (`#/runs`)
  - `Knowledge` (`#/knowledge` / default project knowledge)
  - `Reports` (`#/reports`)
  - `Settings` (`#/settings/installation`)
  - All direct links set `aria-current="page"` when their respective route is active.
- **"More" Disclosure Popover Menu:**
  - Accessible disclosure button with `aria-expanded` and popover panel containing:
    - `Overview` (`#/overview`)
    - `Tasks` (`#/tasks`)
    - `Quality` (`#/quality`)
- **Header Actions (Right Side):**
  - **Factory Status Pill:** Displays `Factory running · X of Y agents busy` or `Factory paused · nothing new starts`.
  - **Pause / Resume Factory Button:** Pauses or resumes the entire factory. Pausing triggers a mandatory confirmation dialog (`window.confirm("Pause the factory? Running tasks will complete, but no new tasks will start.")`) before executing.
  - **Notifications Bell:** Includes badge for unread count, opens notifications panel.
  - **Orchestrator Badge:** Shows active provider status and links to `#/settings/providers`.
  - **Connection Status:** Live indicator (`Connected` / `Reconnecting...`).

### B. Global Factory API Calls & State
- **Wire Types (`dashboard/src/api/wire.ts`):**
  - Defined `WFactoryStatus`: `{ paused: boolean; paused_at: string | null; running_total: number; max_agents: number }`.
- **API Routes (`dashboard/src/api/routes.ts`):**
  - `factoryStatus`: `GET /api/v1/factory`
  - `pauseFactory`: `POST /api/v1/factory/pause`
  - `resumeFactory`: `POST /api/v1/factory/resume`
- **Client Calls (`dashboard/src/api/calls.ts`):**
  - Implemented `factoryStatus`, `pauseFactory`, and `resumeFactory` supporting existing client CSRF handling.
- **Event Streaming (`dashboard/src/events/client.ts`):**
  - Added support for `factory.` event prefix (`factory.paused`, `factory.resumed`) to trigger automatic UI refetching.
- **Mock Server Implementation (`dashboard/fake-api/server.ts`):**
  - Added in-memory `factoryState` initialized with 3 of 4 agents busy.
  - Implemented `GET /api/v1/factory`, `POST /api/v1/factory/pause`, and `POST /api/v1/factory/resume`.
  - Emitted `factory.paused` and `factory.resumed` stream events on state mutation.
  - Included factory state reset support during test suite resets.

### C. Look & Restyling (`dashboard/src/styles.css`, `Overview.tsx`, `Projects.tsx`)
- **Dark Palette Default Theme:**
  - Restyled `:root` with mockup's dark palette: `#0F1419` base, `#121820` topbar, `#141A21` surfaces, `#26303A` borders, `#4FD1C1` accent teal, `#7FE3D7` ok green, `#F5B547` amber warn, `#9DB4FF` knowledge blue.
  - Light mode maintained and accessible via explicit `[data-theme="light"]` and `@media (prefers-color-scheme: light)`.
- **Typography & Assets:**
  - Local system font stacks only (`Inter`, `'Space Grotesk'`, `'JetBrains Mono'`). Zero remote or network font requests.
- **Shared Component Restyling:**
  - Primary, secondary, and subtle buttons; cards; forms and inputs; data tables; tabs; status badges.
- **Welcome Screen (`dashboard/src/screens/Overview.tsx`):**
  - Restyled after `Main.dc.html` (headline typography, setup checklist cards, factory workflow cards).
- **Project Home (`dashboard/src/screens/Projects.tsx`):**
  - Restyled after `Project.dc.html` (header, At-a-glance status cards, repository cards, task run summary table).

### D. Responsive Phone Width (390px)
- Top navigation collapses into a dedicated mobile menu button (`.mobile-menu-btn`) with `aria-label="Navigation menu"` and `aria-expanded` toggle.
- Full viewport wrapping ensuring zero horizontal scroll at 390px width (`scrollWidth <= window.innerWidth`).

---

## 2. Test Suite Updates & Verification

1. **Unit Tests (Vitest):**
   - `dashboard/tests/unit/routes.test.ts`: Added `/resume` endpoint to route pattern matching.
   - `dashboard/tests/unit/contrast.test.ts`: Updated color contrast validation to test `:root` (dark default), `[data-theme="dark"]`, `[data-theme="light"]`, and media light. All pass >= 4.5:1.
   - **Result:** 19/19 test files passed, 136/136 tests passed.

2. **TypeScript & Build:**
   - `npm run typecheck` (`tsc --noEmit`): 0 errors.
   - `npm run build` (`vite build`): Built production assets in `../sentinel/dashboard_dist` with zero errors.

3. **Playwright E2E Tests:**
   - `dashboard/e2e/app_shell_session.spec.ts`: Updated navigation assertions to target the top header; added coverage for `More` disclosure menu, factory pause/resume with confirmation dialog, and 390px responsive viewport.
   - `dashboard/e2e/approval_center.spec.ts`: Updated link name selector from `My Approvals` to `Approvals`.
   - `dashboard/e2e/accessibility_xss.spec.ts`: Passed all automated Axe accessibility checks (both light and dark schemes) with 0 serious/critical violations.
   - `dashboard/e2e/monitoring_live.spec.ts`: Scoped run-level control pause check to `main` area to avoid conflict with the top header's global factory pause button.
   - `dashboard/e2e/projects_config_views.spec.ts`, `notifications_reports.spec.ts`, `tasks.spec.ts`, `installation_readiness.spec.ts`, `quality_trace.spec.ts`, `installed_wheel.spec.ts`, `build_packaging.spec.ts`, `factory_floor.spec.ts`: All passed.

---

## 3. Strict Boundary Compliance

- No modifications were made to:
  - `dashboard/src/screens/Floor.tsx`
  - `dashboard/src/components/floor/**`
  - `dashboard/fixtures/two-projects.ts`
  - `sentinel/**`
  - `tests/**`
- No git commits were made; working directory is staged for reviewer validation.

---

## 4. Unfinished Items

- None. All requirements outlined in the plan for Workstream B ("Look" and "Shell") are complete and verified.
