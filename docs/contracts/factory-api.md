# Factory API (Sentinel 2.0)

The factory view of one project: every run that is not finished, where it stands on the path of stations, what works there, and what waits because of the limits. The dashboard factory floor draws from it. Everything is derived from the registry and the engine's own views (`factory.snapshot`); nothing is stored for display.

## Route

`GET /api/v1/projects/{pid}/factory`

Same session, Host and Origin checks as every read route. No query parameters (an unknown one is `E_VALIDATION`). Strings pass through the scrubber like other run documents. The view changes when run, task, cycle, verification or knowledge rows change: re-read it when the events stream (`/api/v1/events?project={pid}`) sends an event for the project. Pause and note events: `run.paused`, `run.unpaused`, `run.note_added`.

## Answer

```json
{
  "project": "digital-hr",
  "generated_at": "2026-11-21T10:15:02.123456Z",
  "stations": ["intake", "triage", "spec", "gate_spec", "gherkin", "gate_gherkin", "build", "verify", "report", "gate_accept", "knowledge"],
  "limits": {"driver": "engine", "max_tasks_per_project": 2, "max_agents": 4, "running_in_project": 2, "running_total": 3},
  "runs": [
    {
      "slug": "leave-balance",
      "title": "Show the remaining leave days on the home page",
      "type": "feature",
      "driver": "engine",
      "paused": false,
      "state": "EXECUTING",
      "tier": 3,
      "station": "build",
      "stations": {"intake": "done", "triage": "done", "spec": "done", "gate_spec": "done", "gherkin": "done", "gate_gherkin": "done",
                   "build": "working", "verify": "next", "report": "todo", "gate_accept": "todo", "knowledge": "todo"},
      "next_station": "verify",
      "agents": {
        "build": [{"task": "t-0123456789ab", "role": "tdd_green", "runner": "claude", "model": "sonnet",
                   "adapter": "cli", "started_at": "2026-11-21T10:12:40.000000Z"}]
      },
      "lanes": [
        {"cycle": "c-0123456789ab", "name": "Remaining days show", "repo": "backend", "state": "GREEN_RUNNING",
         "red": "done", "green": "working", "refactor": "todo"}
      ],
      "attention": null,
      "pending_notes": 0,
      "created_at": "2026-11-21T09:58:00.000000Z",
      "updated_at": "2026-11-21T10:12:40.000000Z"
    }
  ],
  "queue": [
    {"slug": "payroll-export", "title": "Export payroll as CSV", "position": 1,
     "reason": "the project limit of 2 running tasks is reached"}
  ],
  "factory_paused": false,
  "who": {
    "triage": {"role": "triage", "runner": "agy", "model": "gemini-3.8-flash"},
    "spec": {"role": "specifier", "runner": "claude", "model": "sonnet"},
    "build": {"role": "tdd_green", "runner": "claude", "model": null}
  },
  "activity": [
    {"at": "2026-11-21T10:12:40.000000Z", "run": "leave-balance", "station": "build", "text": "Build agent started"}
  ]
}
```

### Fields

- `stations`: the fixed order of the path. Intake, triage (the triage agent and, for tier 3 and 4, the planner that writes the decisions), spec (specifier), `gate_spec` (human approves the specification), gherkin (test designer), `gate_gherkin` (human approves the scenarios), build, verify, report (reviewer and QA tasks and the report), `gate_accept` (human accepts the result), knowledge (the background harvest).
- `limits`: the `factory` config of the project with defaults, plus how many tasks are RUNNING in the project and over all projects of the service.
- `runs`: every run of the project that is not FAILED or CANCELLED, oldest first. A COMPLETED run stays while its human acceptance is pending (station `gate_accept`) or its knowledge job is queued or running (station `knowledge`).
  - `title`: first line of the request (at most 80 characters), else the slug. `driver`: `engine`, `ai-tool` or `cli`. `paused`: the run-level flag. `state`: the run state of the state machine. `tier`: null before triage.
  - `station`: the current station. A NEEDS_HUMAN or BLOCKED run shows the station of the state it came from.
  - `stations`: one state per station, one of:
    - `done`: before the current station;
    - `working`: an agent task is RUNNING there (or a verification round runs, or the knowledge job runs);
    - `waiting`: a person must act: a human gate, a NEEDS_HUMAN or BLOCKED run (see `attention`), or an acceptance;
    - `paused`: the run is paused at its current station;
    - `queued`: the engine has work for the station but nothing runs yet (a task waits for a slot, or the next one is not planned yet);
    - `next`: the station after the current one;
    - `todo`: every later station.
    A run of type `docs` skips the Gherkin stations in practice; they show `done` once the run is past them.
  - `next_station`: the station after the current one, null at the end.
  - `agents`: for the current station when it is `working` or `paused`, the agents running there. Each has `task`, `role`, `runner` (the provider id), `model` (may be null), `adapter` and `started_at`. Several entries appear when tasks run side by side (build). Verification and the knowledge harvest are engine work and list no agent.
  - `lanes`: one per TDD cycle (one per behavior of the approved Gherkin): `cycle`, `name` (the behavior), `repo`, `state` (the cycle state) and the phases `red`, `green`, `refactor`, each `done`, `working`, `paused`, `queued` or `todo`. A REJECTED cycle shows all phases `todo`. Empty until the run starts building.
  - `attention`: null, or `{"kind": "needs_human" | "blocked", "reason": "..."}`. A human gate has no `attention`; its station is `waiting`.
  - `pending_notes`: notes from the owner that no agent task has received yet.
- `queue`: runs that cannot start because a limit is reached: engine- or AI-tool-driven, not paused, not finished, with a queued CLI task and no task running. `position` is the start order, `reason` names the limit. Empty while no limit is reached.

- `factory_paused`: true while the whole factory is paused (see "Whole-factory pause" below).
- `who`: for the agent stations `triage`, `spec`, `gherkin`, `build` and `knowledge` (summaries), the role and the runner and model the project's routing gives them: `{"role", "runner", "model"}` (`model` may be null). It uses the same resolution the dispatcher uses to start tasks (`select_adapter` for the roles `triage`, `specifier`, `test_designer`, `tdd_green`; the `knowledge` route, then `coder`, for summaries). A station without a CLI runner is left out. Engine stations and gates have no entry.
- `activity`: the latest happenings of the listed runs, newest first, at most 20: `{"at", "run", "station", "text"}`. Built from registry rows: task started or finished or failed, a gate waiting or decided, task created, run paused or resumed, note added, knowledge job done or failed.

## Whole-factory pause

`GET /api/v1/factory` answers `200 {"paused": false, "paused_at": null, "running_total": 0, "max_agents": 4}`. `max_agents` is the largest `factory.max_agents` over the available projects (default 4); `running_total` is the number of tasks RUNNING over all projects. No query parameters.

`POST /api/v1/factory/pause` and `POST /api/v1/factory/resume` answer `200` with the same body. Body: optional `{"comment": "..."}`. Same session, Origin and CSRF rules as every mutating route. Both are idempotent: pausing a paused factory changes nothing.

The switch lives in `~/.config/sentinel/factory.json` (`{"paused": true, "paused_at": "..."}`). While it is set the service starts no new agent task, engine step or orchestrator launch in any project; running tasks finish. Runs keep their own `paused` flag: resuming the factory does not unpause runs. Each change is audited as `factory_pause` or `factory_resume` (target `factory`, channel `dashboard` or `cli`) in every available project. The events stream sends `factory.paused` and `factory.resumed` to every stream that is not filtered to one run, with `project` and `run` null and no event id (do not use it for `Last-Event-ID`); it also reports a change made with `sentinel service pause`. CLI: `sentinel service pause`, `sentinel service resume` (a terminal is required); `sentinel service status` shows the state.

## Related routes

| Route | Use |
|---|---|
| `POST /tasks/{slug}/pause`, `/unpause` | body `{comment?}` |
| `GET /factory`, `POST /factory/pause`, `/factory/resume` | whole-factory pause, body `{comment?}` |
| `POST /tasks/{slug}/note` | body `{text}` |
| `POST /tasks/{slug}/control` | cancel, resume, retry (unchanged) |
| `GET /tasks/{slug}` | run detail with `driver` and `paused` |

## Drivers and the state machine

A run has one driver: `engine` (the service runs it; created at the dashboard unless `factory.driver` says `ai-tool`, or with `sentinel run new --driver engine --request "..."`), `ai-tool` (an AI tool runs the `/sentinel` skill) or `cli` (a person; default for `sentinel run new`). `sentinel next` on an engine-driven run answers a `wait` step with `driven_by: engine` for task, orchestrator and wait work, so the skill never races the engine. Gate (`human`) and `done` steps are unchanged.

Engine-driven run order: CREATED (routing preflight, then a `triage` agent task whose result carries the seven factors; the engine applies the triage transition) → TRIAGED (tier 3 and 4: a `planner` agent task writes `specs/<slug>/decisions.md` in the shared folder and the engine copies it to the run folder) → PLANNED and on, as before. VERIFYING runs `sentinel verify` in the service. A run whose roles do not all route to a CLI runner is BLOCKED in CREATED with the roles named in the reason.
