# Sentinel 2.1 UI: make the real app match the 2.0 mockup

The owner's verdict: the real dashboard (`/#/floor` and the rest) does not look like the approved mockup. The mockup
screens are in `plan/v2.1-ui/mockup/*.dc.html` (static HTML; ignore `support.js`, `<x-dc>`, `<sc-for>`, `{{...}}`
templating: read them for layout, colors, type, spacing and copy). Scope chosen by the owner: **the whole app like the
mockup**.

## Look (all screens)

- Dark by default, palette from the mockup: page `#0F1419`, header `#121820`, surface `#141A21` / `#171D24`,
  border `#26303A` / `#3A4654`, text `#E6EAEE` / `#C5CDD5` / muted `#9AA6B2`, accent teal `#4FD1C1` (on-accent text
  `#062420`), amber "needs you" `#F5B547` (on-amber text `#1A1206`), knowledge blue `#9DB4FF`, danger `#F2A3A3`.
  Keep the existing light theme reachable (if the app has a theme choice, dark becomes the default; never remove the
  `data-theme` / `prefers-color-scheme` handling). Text contrast at least 4.5:1.
- Type: Inter for body, Space Grotesk for headings and the wordmark, JetBrains Mono for code, hashes and ids.
  **No network fonts** (the dashboard must work offline): use a local font stack
  (`Inter, system-ui, sans-serif`, `'Space Grotesk', Inter, system-ui, sans-serif`,
  `'JetBrains Mono', ui-monospace, monospace`). Do not add a Google Fonts link.
- Radii 10 to 18 px, touch targets at least 44 px, flex/grid with gap, no emoji.

## Shell (workstream B)

Replace the left sidebar with the mockup's top header on every screen:

```
[logo] Sentinel   Factory floor  New task  Approvals(badge)  Projects  Runs  Knowledge  Reports  Settings  [More v]   (spacer)  [● Factory running · 1 of 4 agents busy] [Pause factory] [bell]
```

- `More` is a disclosure menu (button with `aria-expanded`) holding Overview, Tasks and Quality. Every screen that exists
  today stays reachable; routes do not change.
- `aria-current="page"` on the active item; active item background `#1C242D`, bold.
- The factory pill and the Pause factory / Resume factory button use `GET /api/v1/factory` and
  `POST /api/v1/factory/pause|resume` (contract below). Pausing asks for confirmation. The pill says
  `Factory paused · nothing new starts` when paused.
- At phone width the nav wraps (or collapses into one menu button); no horizontal page scroll.
- Notifications bell and session/orchestrator status keep working (they move into the header).
- The Welcome screen (`Main.dc.html`) and every other screen get the mockup's spacing: content column
  `max-width` 1080 to 1360 px centered, padding 24 px.

## Floor (workstream C)

Owner decision: **one floor per project**, with a project switcher on the floor (`/floor` opens the first available
project; `/projects/<id>/floor` is that project's floor).


Match `mockup/Floor.dc.html` exactly where the data allows:

- Always the dark immersive canvas (radial `#121B22` to `#0B0F13`), even in light theme.
- Under each agent station: `runner · model` from the snapshot's `who` map (for example `agy · gemini-3.8-flash`);
  engine stations say `engine`, gates say `you`.
- Build fans out into one lane per behavior (B1, B2, B3 ...) whenever the run has lanes; one lane still shows its name.
- "Activity across the factory" panel under the canvas from the snapshot's `activity` list (time, task initials,
  station, text), newest first, live (refetch on events).
- Waiting station: the side panel's amber `Review specification` button (or the matching review); final gate:
  `Open the report`.
- Gate diamonds and labels must not collide with edges: give gate labels a background chip or offset.
- Sample data (fake API fixtures) shows the mockup's three tasks: one building with 3 lanes (B1 done, B2 working,
  B3 queued), one waiting at the spec gate, one in triage, plus queue entries; and a non-empty activity list.

## API contract (workstream A implements; B and C code against it)

### Whole-factory pause

- `GET /api/v1/factory` -> `200 {"paused": bool, "paused_at": str|null, "running_total": int, "max_agents": int}`
  (`max_agents`: the largest `factory.max_agents` over the available projects, default 4).
- `POST /api/v1/factory/pause`, `POST /api/v1/factory/resume` -> `200` with the same body. Same session, Origin and
  CSRF rules as every other mutating route; optional JSON `{"comment": str}`. Idempotent.
- Stored in the user config dir (`~/.config/sentinel/factory.json`, `{"paused": true, "paused_at": "..."}`).
- While paused the service starts **no new agent task** in any project; tasks already running finish. Runs keep
  their own `paused` flag; resuming the factory does not unpause runs.
- Events: `factory.paused`, `factory.resumed` on the events stream (no project).
- CLI parity: `sentinel service pause`, `sentinel service resume`; `sentinel service status` shows `factory: paused`.
- Audit log entry for each change (like run pause).

### Factory snapshot additions (`GET /api/v1/projects/{pid}/factory`)

- `"factory_paused": bool`
- `"who": {"<station>": {"role": str, "runner": str, "model": str|null}}` for the agent stations
  (`triage`, `spec`, `gherkin`, `build`, and `knowledge` for summaries) from the project's routing config
  (the same resolution the dispatcher uses). Missing route: omit the station.
- `"activity": [{"at": str, "run": slug, "station": str, "text": str}]`, newest first, at most 20, built from rows the
  registry already has (task started/finished/failed, gate waiting/approved, run created/paused/unpaused/noted,
  knowledge job done/failed). Strings pass through the scrubber.

Update `docs/contracts/factory-api.md`, the fixture recorder answers (`dashboard/fixtures/recorded/factory.json`
and a new one for `GET /factory` if the recorder covers it), `docs/operations.md` / `docs/cli-guide.md` /
`docs/gui-guide.md` for the new commands and controls.

## Ownership (to keep merges clean)

- A: `sentinel/**`, `tests/**` (Python), `docs/contracts/factory-api.md`, `dashboard/fixtures/recorded/**`, docs for the
  CLI commands.
- B: `dashboard/src/App.tsx`, global CSS/theme files, shell components, `dashboard/src/api/calls.ts` and `wire.ts`
  **only for** the new global `/factory` calls, the fake API routes for `/factory` pause/resume, e2e specs for the shell
  and every spec that clicked the old sidebar.
- C: `dashboard/src/screens/Floor.tsx`, `dashboard/src/components/floor/**`, `wire.ts` snapshot fields,
  `dashboard/fixtures/two-projects.ts` factory sample, fake API factory snapshot, `e2e/factory_floor.spec.ts`,
  `dashboard/scripts/showcase.mjs`.
- Never revert or rewrite a file you did not change. Commit on your own branch only.

# Wave 2 (owner: "implement 1 to 6, add them all")

Starts after workstreams A (API) and B (shell) are merged into `v2.1-ui`, so each branch starts from the new shell and API.

## D. Usage limits and routing fix (items 1 and 2)

1. **Usage limits.** When a provider CLI fails because of a usage or rate limit (detect from exit code and output per
   adapter: Claude "usage limit reached ... resets at", Gemini/agy "quota", "RESOURCE_EXHAUSTED", HTTP 429), the task is
   not FAILED: it becomes `WAITING_LIMIT` (or the existing parked state with a reason) with `retry_at` parsed from the
   message (fallback: now + `routing.limit_backoff` default 30 min). The dispatcher retries after `retry_at`.
   Optional `routing.fallback: {claude: agy, ...}` (or per role) runs the task on the fallback runner at once instead.
   Floor shows the station as "Waiting for usage limit · retries 14:05" (paused look, not failed); a notification
   `task.limit_reached`. CLI: `sentinel status` shows it; `sentinel resolve <slug> --retry-now`.
2. **Routing fix.** When a project's routing blocks engine runs (factory.routing_problems), the dashboard shows a
   "Fix routing" banner on the project home and floor; it opens a dialog with a suggested runner and model per role
   (reuse the wizard's suggestion API), Preview the YAML change, Save (same config write path as Project settings, with
   history). CLI: `sentinel doctor --fix-routing` prints the same suggestion and writes it after a yes.

## E. Usage per task (item 3)

- Record per agent task: runner, model, input/output tokens, cost estimate when the adapter reports them (Claude
  `--output-format json` usage; others: null), wall time. Registry migration (new columns or table), rollback note.
- Show: run page "Usage" panel (per task, per model, totals), floor side panel "This task used ...", Reports page
  usage by project/model/week. CLI: `sentinel stats --usage [--project] [--since]`.
- Optional `factory.budget: {tokens_per_day, usd_per_day}` per project; when reached, the project stops starting new
  tasks (like the factory pause, project scope) with a notification `budget.reached`; resets next day; floor banner.

## F. Knowledge in the flow (item 5)

Item 4 (desktop notifications) dropped by the owner.

5. **Knowledge in the flow.** New task screen: "Knowledge found" panel (related change records, invariants) from a
   new `GET /api/v1/projects/{pid}/knowledge/related?q=` (reuse the knowledge search the agents use) and "Slots: N of M
   busy, position K in the queue". Approve screen: "Knowledge used" tab listing the records/summaries the agents read
   for that document (from the run's recorded knowledge reads; record them if not yet stored). Save as draft for new
   tasks.

## G. Housekeeping (item 6)

- Fix the flaky `test_release::Installed::test_AC_OPS_01i` (find the timing/shared-state cause; no retries).
- Accessibility: automated axe-core pass over every screen in e2e (no new violations), plus an accessibility-tree
  review of the new header, floor and dialogs. Docs say plainly that a manual screen-reader pass is still not done.
- Adapters: run the Gemini adapter against the real `gemini` CLI (installed here) on a tiny throwaway repo; fix what
  breaks. Codex and Cursor CLIs are not installed: docs keep saying they are untried.
