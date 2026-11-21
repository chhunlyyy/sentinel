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
