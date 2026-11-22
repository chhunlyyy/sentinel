# API Contracts (1.1.0, draft for G1)

Two front ends call the same engine functions: the CLI and the local HTTP API. Security rules: `docs/architecture/security-architecture.md`.

## 1. Conventions (HTTP)

- Base `http://127.0.0.1:<port>/api/v1`. JSON in and out. UTF-8.
- Auth: `sentinel_session` cookie; mutating calls also send `X-Sentinel-CSRF`.
- Errors: `{"error": {"code": "E_...", "message": "...", "details": {...}}}` with 400 (validation), 401 (auth), 403 (actor or policy), 404, 409 (stale hash, transition, locked), 422 (precondition), 500.
- Lists: `?limit=&cursor=`; response `{"items": [...], "next": "<cursor>|null"}`.
- Every mutating call returns the new resource state as the engine stored it.

## 2. Endpoints

### Installation and runtime

| Method | Path | Engine function | Notes |
|---|---|---|---|
| GET | `/installation` | `install.info()` | path, version, python, method |
| GET | `/installation/health` | `install.health()` | list of checks with status and fix |
| GET | `/runtime` | `server.info()` | pid, port, started, projects loaded |

### Projects and repositories

| Method | Path | Engine function |
|---|---|---|
| GET | `/projects` | `projects.list()` |
| POST | `/projects` | `projects.create(spec)` (writes config like `sentinel init`) |
| POST | `/projects/register` | `projects.register(path)` |
| GET/PATCH | `/projects/{pid}` | `projects.get / update` |
| POST | `/projects/{pid}/archive` | `projects.archive` |
| DELETE | `/projects/{pid}` | `projects.unregister` (never deletes files) |
| GET | `/projects/{pid}/readiness` | `projects.readiness(workflow?)` |
| GET/POST | `/projects/{pid}/repositories` | `repos.list / add(path or url)` |
| GET/PATCH/DELETE | `/projects/{pid}/repositories/{rid}` | `repos.get / update / remove` |
| POST | `/projects/{pid}/repositories/order` | `repos.reorder(ids)` |
| POST | `/projects/{pid}/repositories/{rid}/inspect` | `repos.inspect` (branches, profile, remote) |
| GET | `/fs/dirs?path=` | `picker.list(path)` (allowed roots only) |

### Configuration

| Method | Path | Engine function |
|---|---|---|
| GET | `/projects/{pid}/configuration` | `config.effective(pid)` with sources |
| POST | `/projects/{pid}/configuration/validate` | `config.validate(doc)` (no save) |
| PUT | `/projects/{pid}/configuration` | `config.save(doc, base_sha)`; 409 if base changed |
| GET | `/projects/{pid}/configuration/history` | `config.history` |
| GET | `/projects/{pid}/configuration/diff?a=&b=` | `config.diff` |
| POST | `/projects/{pid}/configuration/restore/{vid}` | `config.restore` |
| GET/POST | `/projects/{pid}/configuration/export`, `/import` | `config.export / import` |
| GET/PUT | `/configuration/global` | global scope |
| GET | `/providers` | `providers.list()` with capabilities and install status |
| POST | `/providers/{name}/test` | `providers.test(model)` |
| GET | `/agents` | `agents.roles()` with assignments |
| GET | `/workflows`, `/policies`, `/profiles` | read-only catalogs; edits go through configuration PUT |

### Tasks and runs

| Method | Path | Engine function |
|---|---|---|
| GET/POST | `/projects/{pid}/tasks` | `runs.list / create(request, repos, type, priority, ...)` |
| GET | `/tasks/{slug}` | `runs.get` (state, statuses, graph summary) |
| GET | `/tasks/{slug}/next` | `engine.next` (same as `sentinel next --json`) |
| GET | `/tasks/{slug}/specification` | current version, hash, validation, diff to previous |
| GET | `/tasks/{slug}/specification/versions/{v}` | that version |
| GET | `/tasks/{slug}/gherkin` | features, scenarios, tags, coverage table, hash |
| POST | `/tasks/{slug}/approvals` | body `{gate, sha256, confirmation, decision, comment}` -> `approvals.decide` (human only). `sha256` is the full hash, `confirmation` its first 8 characters as typed |
| GET | `/tasks/{slug}/workflow` | full graph: nodes (tasks, gates), edges, states |
| GET | `/tasks/{slug}/tdd` | cycles with phases and evidence ids; each cycle has `red_method` (`test_file` or `qa_scenario`) and `exception` (`{rule, replaced, by, repo}` or null) |
| GET | `/tasks/{slug}/verification` | `cycles` (id, repo, behavior, state, `red_method`, `exception`), evidence list (round, repo, name, verdict), latest finished `round`, `missing` (planned checks without evidence), acceptance computation and `acceptance_record` (decision, approver, channel, at, comment; null while pending) |
| GET | `/tasks/{slug}/trace` | trace links and gaps |
| GET | `/tasks/{slug}/changes` | per repo: base, branch, files, stats |
| GET | `/tasks/{slug}/changes/diff?repo=&path=&mode=inline|split` | scrubbed diff |
| GET | `/tasks/{slug}/artifacts/{aid}` | content, hash verified, scrubbed |
| GET | `/tasks/{slug}/logs/{task_id}?offset=` | live log tail |
| POST | `/tasks/{slug}/control` | body `{action: resume|cancel|retry, task_id?, comment?}` (`pause` and "request intervention" are dropped for 1.1.0; the API answers 400) |
| POST | `/tasks/{slug}/acceptance` | body `{sha256_of_report, confirmation, decision, comment}` (human only). A rejected run or an already confirmed acceptance is `E_TRANSITION` (409), a stale hash `E_APPROVAL_STALE`, a changed report, evidence output or verified tree `E_INTEGRITY` (409); every other refusal keeps its own code. The audit row is `accepted` or `rejected` |
| POST | `/tasks/{slug}/publish` | shared-repo push (human only, scrub-checked) |
| GET | `/tasks/{slug}/report?format=json|md` | run report; `E_INTEGRITY` when report.json no longer matches the report the engine registered |

### Other

| Method | Path | Engine function |
|---|---|---|
| GET | `/notifications?project=&unread=&limit=&cursor=` | notifications computed from the events table (event-contracts section 4); answer `{items, next, unread, unavailable}`; each item is `{id, project, run, level, text, link, at, read_at}` |
| POST | `/notifications/{id}/read` | mark one read in `~/.config/sentinel/user.db` (CSRF; no audit row; the first read time stays) |
| GET | `/reports/analytics?project=&from=&to=` | analytics (a missing value is `{value: null, reason}`); the same answer as the `v2` key of `sentinel stats` |
| GET | `/audit?project=` | audit log |

### Added in Phase F

| Method | Path | Notes |
|---|---|---|
| GET | `/session` | `{csrf, user}` for the session cookie; the CSRF value is per session |
| GET | `/approvals?state=` | approvals across projects (default `IN_REVIEW`) |
| POST | `/projects/{pid}/tasks` | body `{slug, request, type, repos?, priority?, tier?, ticket?}`; the run is created for the AI tool (`origin = dashboard`) and authorizes nothing; `?project=<pid>` on `/tasks/{slug}` routes selects the project when a slug exists twice |

### Added in 2.0 (factory)

| Method | Path | Notes |
|---|---|---|
| POST | `/tasks/{slug}/pause` | body `{comment?}`; the dispatcher starts nothing more for the run, running tasks finish. Audit row `pause`, event `run.paused`. A finished or already paused run is `E_TRANSITION` |
| GET | `/factory` | whole-factory pause state `{paused, paused_at, running_total, max_agents}`; see factory-api.md |
| POST | `/factory/pause`, `/factory/resume` | body `{comment?}`; idempotent; the dispatcher starts no new agent task in any project. Audit rows `factory_pause`, `factory_resume`; events `factory.paused`, `factory.resumed` |
| POST | `/tasks/{slug}/unpause` | body `{comment?}`; audit row `unpause`, event `run.unpaused` |
| POST | `/tasks/{slug}/note` | body `{text}` (at most 4000 characters); answer 201 with the run detail and `note`. The next agent task of the run gets the text once. Audit row `note`, event `run.note_added` |
| GET | `/projects/{pid}/factory` | the factory snapshot, see [factory-api.md](factory-api.md) |

### Added in 2.0 (setup, configuration form, and knowledge base - W3 part A)

| Method | Path | Engine / module | Notes |
|---|---|---|---|
| POST | `/detect` | `manage.detect_paths` | body `{paths: [...]}`; returns per path: `is_git`, `current_branch`, `default_branch`, `local_branches`, `profile`, `commands`, `tracked_branches` |
| POST | `/shared/test` | `manage.test_shared` | body `{url}`; tests read access via `shared.verify_remote` and write access via push dry-run (`write`: true, false, or "unknown") |
| GET | `/routing/suggest` | `manage.suggest_routing` | suggested deterministic role -> {runner, model} routing from installed CLI-capable providers (cheap/fast for triage, gherkin, planner, knowledge; strong for specifier, coder, reviewer) |
| GET | `/projects/{pid}/routing/fix` | `factory.routing_fix` | roles that block engine runs with `current` and `suggested` {runner, model} and the `changes` ({path, value}) that apply them; save through `config/preview` and `config/save`. `applies` is false unless the project's factory driver is `engine` |
| GET | `/projects/{pid}/config/form` | `manage.config_form` | returns editable config sections and fields generated from `config.schema.json` with type, enum, default, current value, help |
| POST | `/projects/{pid}/config/preview` | `manage.config_preview` | body `{changes: [{path, value}, ...]}`; schema validated, returns YAML diff (refuses changes to `state.shared_repo` and repo `path`) |
| POST | `/projects/{pid}/config/save` | `manage.config_save` | body `{changes: [{path, value}, ...], comment?}`; saves `sentinel.config.yaml`, writes config version history and audit row `config_changed` (refuses changes to `state.shared_repo` and repo `path`) |
| GET | `/projects/{pid}/knowledge/status` | `readroutes.knowledge_status` | returns knowledge status (cursors, records, by_repo) and kb job summary from `kb_worker` |
| GET | `/projects/{pid}/knowledge/records?filter=&q=&limit=&cursor=` | `readroutes.knowledge_records` | paginated change records from `index.json`, front matter only, scrubbed text; filter `all|verified|inferred` |
| GET | `/projects/{pid}/knowledge/records/{key}` | `readroutes.knowledge_record` | single change record body and metadata by key; 404 if not found |
| POST | `/projects/{pid}/knowledge/ingest` | `manage.knowledge_ingest` | queues an ingest job in `kb_jobs`, spawns worker in background, writes audit row `knowledge_ingest`; answers 202 without blocking |
| POST | `/projects/{pid}/knowledge/snapshot` | `manage.knowledge_snapshot` | queues a snapshot job in `kb_jobs`, spawns worker in background, writes audit row `knowledge_snapshot`; answers 202 without blocking |
| POST | `/projects/{pid}/knowledge/backfill/estimate` | `manage.knowledge_backfill_estimate` | body `{since?, repo?}`; computes backfill change estimate and returns an estimate token |
| POST | `/projects/{pid}/knowledge/backfill` | `manage.knowledge_backfill` | body `{token}`; runs backfill ingest with estimate token, writes audit row `knowledge_backfill` |
| GET | `/projects/{pid}/knowledge/ci-template?repo=<id>` | `readroutes.knowledge_ci_template` | CI template (`sentinel-knowledge-ingest.yml`) filled with `REPO_ID`, `REPO_PROFILE`, and `TRACKED_BRANCHES` from project configuration |

Pause, unpause and note use the same session, CSRF and audit checks as `/tasks/{slug}/control`. Run detail and run list items carry `driver` (`engine`, `ai-tool`, `cli`) and `paused`.

Only Phase F routes exist; every other route above answers `404 E_NOT_FOUND` until Phase G or H builds it. Check order: Host, Origin, session cookie, route, CSRF, body. HTTP-only codes (not engine codes): `E_AUTH` 401, `E_CSRF` 403, `E_HOST` 403, `E_ORIGIN` 403, `E_METHOD` 405, `E_BODY_TOO_LARGE` 413, `E_MEDIA_TYPE` 415, `E_INTERNAL` 500. Engine codes map to one status each (`apiserver/status.py`).

## 3. CLI contract (new and changed commands)

| Command | Actor | Purpose |
|---|---|---|
| `sentinel run new <slug> --type T [--repos a,b] [--legacy]` | O, H | create run (version 2 by default) |
| `sentinel triage <slug> --factors k=v,...` | O | submit factors; engine sets tier |
| `sentinel next <slug> [--json]` | O, H | what is allowed now: task to run, human action, or done |
| `sentinel task run <task-id>` | O | dispatch through the adapter |
| `sentinel task complete <task-id>` | O | native task finished; engine validates. Replaced the Phase B `sentinel submit` hook, which is removed |
| `sentinel review <slug> spec|gherkin` | H | show artifact, diff, validation |
| `sentinel approve <slug> spec|gherkin [--request-changes|--reject] [-m comment]` | H (TTY) | decision |
| `sentinel verify <slug>` | O, H | run verification |
| `sentinel accept <slug> [--reject] [-m]` | H (TTY) | final acceptance |
| `sentinel report <slug> [--json]` | any | write and print reports |
| `sentinel run export|import` | H | bundle |
| `sentinel dashboard [--port N] [--no-open]` | H | start or attach to the server |
| `sentinel notifications [--unread] [--json] [--project P] [read <id>\|--all]` | any | list notifications, or mark them read |
| `sentinel stats [--from D] [--to D] [--format json\|md]` | any | the 0.1 keys plus a `v2` key from the registry (read-only; never creates it) |
| `sentinel backup` | H | copy registry |
| `sentinel audit export` | H | audit log |

Unchanged: `init`, `doctor`, `routing`, `sync-adapters`, `run update` (legacy runs only; refused with `E_TRANSITION` on version 2 runs), `run finish`, `resume`, `sync`, `spec set`, `metrics record`, `shared`, `clean`, `scrub`, `release-check`, `qa-data`, `stage render`, `stage run`, `change-map`, `selftest`.

Exit codes: 0 ok, 1 failure, 2 usage, 3 boundary violation (kept), 4 shared-repo conflict (kept), 5 refused transition, 6 human action required.
