# Sentinel 2.0: the software factory (GUI first)

Status: direction agreed with the owner on 2026-11-21. Details below are a proposal until approved.

## Goal

Sentinel moves from "a CLI and skills your AI tool drives" to "a factory you run from the dashboard".
A user installs Sentinel, runs `sentinel dashboard`, creates a project in a few clicks, writes a task,
sends it to the factory, and watches it move from station to station until they accept the result.
The shared knowledge base (unreleased 1.3.0 work) ships in the same release.

## Decisions (owner, 2026-11-21)

1. **The engine drives runs.** The Sentinel service runs the factory loop itself and starts each agent
   through the existing adapters. AI is used for the work (triage, spec, code, review), never for bookkeeping.
2. **Background service.** The factory keeps running when the terminal or browser closes. `sentinel dashboard`
   starts or attaches to it; it is stopped from the GUI or `sentinel stop`. Optional autostart at login.
3. **CLI stays fully working beside the GUI**, but new effort goes to the GUI: easy to use and to control.
   Both call the same engine; no logic is duplicated in the UI.
4. **One release: 2.0.0** (knowledge base + GUI factory). 1.3.0 is not published.

## What stays

The v2 state machine, the two human gates (spec, Gherkin) and acceptance, write scopes, verification by the
engine ("an agent's claim is never evidence"), adapters and provider routing, the registry, the audit log,
the knowledge base, and every CLI command.

## Workstreams

### W1. Factory driver (engine-driven runs)
- New `factory` loop in the service: for each project with active runs, call the same step logic as
  `sentinel next` (`RuntimeOps._step_for`) and act on it:
  - `task`: start it with the CLI adapter of its routed provider (already exists).
  - `wait`: poll adapters, collect results (already exists).
  - `orchestrator` steps become engine work:
    - triage: an agent task, role `triage`, that returns the seven factors as JSON (schema-checked); the engine
      then runs the triage transition itself.
    - `decisions.md`: an agent task, role `planner`, writing the file in its write scope.
    - `sentinel verify`: called in-process.
    - stop subagents: adapter cancel.
  - `human`: notify and wait for the GUI or CLI decision.
- Routing check before a run starts: every role must route to a CLI-capable provider (the native adapter
  needs an AI tool session and is not allowed in engine-driven mode). Clear error in the GUI otherwise.
- Concurrency: per-project limit on parallel tasks (config, default 2), global limit (default 4).
- The `/sentinel` skill keeps working: a run is claimed by one driver (engine or skill) so they never race;
  `apiserver/dispatch.py` orchestrator launch becomes the fallback mode `driver: ai-tool`.
- Pause and resume a run (new: today only cancel/resume/retry), and "step in": send a note to the next task.

### W2. Background service
- `sentinel service start|stop|status` (and `sentinel stop`); `sentinel dashboard` starts the service if
  needed and opens the browser. Service = today's API server plus the factory loop, detached, one per user.
- Survives terminal and browser close; restart-safe (the registry already holds all state; running agent
  processes are re-attached or marked for retry on restart).
- Optional autostart: systemd user unit (Linux), LaunchAgent (macOS), Startup task (Windows). Off by default,
  switch in Settings.
- Security model unchanged: loopback only, session token, CSRF. Approval in the GUI keeps the typed-hash check.
  The TTY requirement for starting the dashboard is replaced by a one-time login link printed by
  `sentinel dashboard` and openable from the desktop launcher (to review with the security doc, residual risk R1).

### W3. Easy project setup and config in the GUI
- Create project wizard: pick folder(s) or clone from URL; auto-detect stack per repo (profiles already exist),
  test/build/lint commands, default branch and tracked branches; shared repo (create local, or paste URL and
  test access); providers found on the machine with a suggested routing (cheap model for triage/knowledge,
  strong model for coder/reviewer). One screen per step, everything pre-filled, "Finish" runs `doctor`.
- Settings editor for everything that is YAML-only today: commands, policies, limits, verification, knowledge
  (branches, auto-push, backfill, max_summaries), routing per role. Form fields generated from
  `config.schema.json` with inline validation, a diff preview, and the existing config history.
- Knowledge page: status (cursors, records, last job), backfill with its estimate and a confirm, snapshot,
  browse change records and module summaries, the CI template with copy-ready secrets instructions.
- GUI actions for today's CLI-only steps: `resolve`, `sync push` (with its approval), doctor fixes.

### W4. Factory floor (live view)
- A new main screen showing the factory as stations on a path:
  Intake > Triage > Spec > [You approve] > Gherkin > [You approve] > Build (one lane per behavior:
  Red > Green > Refactor) > Verify > Report > [You accept] > Knowledge.
- Each station shows: state (idle, working, waiting for you, done, failed), the agent working there
  (role, provider, model), elapsed time, and what comes next. Human gates are clearly marked "waiting for you"
  with one-click review.
- Several tasks at once: each task is a token moving along the path; a queue shows tasks not started yet.
- Click a station to open its detail (logs, diff, evidence) in the existing run screens.
- Live updates over the existing server events stream; animations respect reduced-motion; keyboard and screen
  reader accessible like the rest of the dashboard. Original design (the reference image is inspiration only).

### W5. Release 2.0.0
- Migration notes 1.x to 2.0 (config keys, driver modes, service), docs rewritten GUI-first with the CLI as
  reference, README and pictures, version bump, release gate updates.

## Suggested order

1. W1 driver core (triage/planner roles, in-process verify, run claim) with tests: the factory must work
   headless before the GUI shows it.
2. W2 service (start/stop/status, restart safety).
3. W4 factory floor (needs W1 events) and W3 wizard and settings, in parallel.
4. W3 knowledge page and CLI-only actions.
5. W5 docs and release.

## Mockup (approved 2026-11-21)

https://claude.ai/artifact/6T9ZxFpFmnmZaGoHaa5ywY: nine linked screens. 1 Welcome (service, providers,
first project), 2 Create project wizard (repos, detected stack/commands/branches, shared repo + backfill, AI team
routing, checks), 3 Project home, 4 New task, 5 Factory floor as an animated neural network (agent = circle,
engine = rounded square, human gate = diamond; Build fans out to one neuron per behavior and joins at Verify;
Knowledge neuron feeds every agent; click a neuron for who/what/next; per-task pause, step-in note, cancel;
factory pause), 6 Approve specification, 7 Report and accept, 8 Knowledge base, 9 Settings (service, providers,
config form with YAML preview, health).

## Defaults taken for the open questions (owner may change)

- Parallel limits: 2 tasks per project, 4 agents in total (`factory.max_tasks_per_project`, `factory.max_agents`).
- Triage factors are applied automatically; they are shown on the floor and the run, and the existing
  re-triage gate still raises the tier.
- Autostart at login: Linux (systemd user unit) first, off by default.
- Team-shared (non-loopback) dashboard: out of scope for 2.0.

## Build routing

Antigravity (`agy`) first, Claude Sonnet subagents next, Opus only for hard work; the main session writes
briefs, reviews diffs and runs the tests. Each workstream in its own git worktree and branch, merged into
`v2-factory`.
