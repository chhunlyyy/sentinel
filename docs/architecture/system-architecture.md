# System Architecture (1.1.0, draft for G1)

Requirements: `SPEC.md` sections 1, 2, 3, 15.

## 1. Processes

Everything runs on the user's machine.

```text
+-------------------+      +------------------+      +----------------------+
| AI tool session   |      | Browser          |      | Terminal             |
| (skills)          |      | dashboard SPA    |      | sentinel CLI         |
+---------+---------+      +---------+--------+      +----------+-----------+
          | sentinel CLI             | HTTPS-less loopback HTTP  | direct calls
          | (subprocess)             | cookie token, SSE         |
          v                          v                           v
+--------------------------------------------------------------------------+
|                         sentinel engine (library)                         |
|  engine/      state machines, transitions, policy, triage, acceptance     |
|  approvals/   versions, hashes, decisions, invalidation                   |
|  dispatch/    task contract, scheduler, adapters (cli, native)            |
|  tdd/         cycles, failure classifier                                  |
|  verify/      verification runner (wraps release_check), scope check      |
|  registry/    SQLite access, migrations, artifacts, events                |
|  projects/    project registry, repo inspection, config load/save/history |
|  server/      HTTP API + SSE + static assets (only when `sentinel dashboard`)|
+--------------------------------------------------------------------------+
          |                       |                          |
   .sentinel/sentinel.db   .sentinel/runs/<slug>/     .sentinel/shared/ (git)
   ~/.config/sentinel/     artifacts, logs            only remote exchange
```

- The engine is a Python library inside the existing `sentinel` package. The CLI (`sentinel/scripts/sentinel.py`) and the HTTP server are thin front ends over the same functions.
- `sentinel dashboard` starts one server per user (pid file in `~/.config/sentinel/`). It manages any number of registered projects.
- Provider CLIs are child processes of whoever dispatches the task (CLI or server).
- The only network traffic Sentinel itself starts is `git` to the shared repo and, when the user adds one, to a project repo remote.

## 2. Package layout (extracted only as code arrives)

```text
sentinel/
  scripts/            existing CLI and scripts (kept; sentinel.py grows thin)
  engine/             new: states.py, transitions.py, policy.py, triage.py, acceptance.py
  approvals/          new
  dispatch/           new: contract.py, scheduler.py, adapters/cli.py, adapters/native.py
  tdd/                new: cycles.py, classify.py
  verify/             new: runner.py (wraps scripts/release_check.py), scope.py
  registry/           new: db.py, migrations/, artifacts.py, events.py
  projects/           new: registry.py, repos.py, config_store.py
  server/             new: app.py (stdlib ThreadingHTTPServer), routes.py, sse.py, auth.py
  dashboard_dist/     built SPA assets (generated at release)
  core/stages/        existing + test_designer.md, tdd_red.md, tdd_green.md, tdd_refactor.md
dashboard/            SPA source (React + TypeScript + Vite, pending Q1)
tests/                unittest suites
```

## 3. Responsibilities

| Layer | Owns | Never does |
|---|---|---|
| Engine | state, policy, approvals, evidence, acceptance | trust agent output without checks |
| CLI | argument parsing, TTY approval prompt, printing | business rules |
| Server | auth, routing, validation of HTTP input, SSE | business rules, arbitrary command execution |
| SPA | presentation, forms, live view | decide anything; claim success before the API answers |
| Skills (AI tool) | propose next steps, run native subagent stages, write briefs | approve, accept, change state outside the CLI |
| Worker agents | do one task within scope, write `result.json` | touch state, approvals, other repos, git history |

## 4. Run flow (feature, tier 3)

```text
human/dashboard or AI tool: task created ............................ CREATED
orchestrator: sentinel triage <slug> --factors ... (engine computes) TRIAGED
orchestrator: interview -> decisions.md; sentinel run plan .......... PLANNED
engine: dispatch specifier; validate spec ........................... SPECIFICATION_REVIEW
human: approve spec (TTY or dashboard) .............................. SPECIFICATION_APPROVED
engine: dispatch test_designer; validate Gherkin .................... GHERKIN_REVIEW
human: approve Gherkin .............................................. GHERKIN_APPROVED
engine: cycles: red -> engine runs tests -> green -> engine runs tests -> refactor -> engine runs tests
                                                                    EXECUTING
engine: verification runner ......................................... VERIFYING
engine: dispatch reviewer, qa; findings routed ..................... REVIEWING
engine: acceptance computed; human final acceptance ................ COMPLETED (+ acceptance_status)
```

## 5. Dashboard

- Single-page app served from the wheel at `http://127.0.0.1:<port>/`.
- Talks only to `/api/v1/*` and `/api/v1/events` (SSE).
- Screens follow `SPEC.md` DSH-01 (navigation of SPEC_DASHBOARD section 19).
- No CDN, fonts or analytics from the network.
- State is never cached as truth in the browser; after reconnect it re-fetches.

## 6. Compatibility

- Existing commands keep their names and flags.
- Legacy runs (`state.json` without `schema_version`) continue in the 0.1 flow.
- `sentinel.config.yaml` stays the project config; new keys are optional.
