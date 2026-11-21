# Configuration reference

Everything lives in `sentinel.config.yaml` at the workspace root. The JSON Schema is `core/schema/config.schema.json`; `sentinel doctor` validates against it when `jsonschema` is installed. See `templates/sentinel.config.yaml` for a complete example.

## version, shape

```yaml
version: 1
shape: fullstack
```

`shape` is one of `single`, `fullstack`, `fullstack-mobile`, `custom`. It records the choice made at `init`; the `repos` list is what the pipeline reads.

## repos

```yaml
repos:
  - id: backend
    path: ./api
    role: backend
    profile: spring-gradle
    commands:
      test: ./gradlew test --parallel
    write_scope: []
```

- `id`: lowercase name used in file ids, agent names, and `--repo`.
- `path`: folder of the repo, relative to the workspace. Must be a git repository.
- `role`: free-form (`app`, `backend`, `frontend`, `mobile`, anything). Generated agents are named `<role>-coder`, `<role>-cleaner`, `<role>-hardener`, `<role>-repro`. The roles `frontend` and `mobile` are treated as client repos by the `no_permanent_frontend_tests` rule.
- `profile`: `flutter`, `spring-gradle`, `nextjs`, `node`, `python`, or `generic`. A profile supplies default commands, the change-map column rules, and the QA driver. A repo can override any command under `commands` (`build`, `lint`, `typecheck`, `test`, `mutate`). An empty command is skipped.
- `guidelines`: optional path (relative to the workspace) to a markdown file with extra rules for this repo, for example API conventions. Its text is appended to every stage prompt for that repo under "Project guidelines". A missing file prints a warning.
- `knowledge`: optional knowledge base settings for this repository.
  - `branches`: list of tracked branch names (for example `[develop, main]`). When omitted, defaults to the repository's default branch (`origin/HEAD`, else the current local HEAD branch). The first entry is the summary branch: snapshot summaries are built from its tip.
- `write_scope`: reserved; currently the boundary check treats the whole repo as the stage's scope.

## qa

```yaml
qa:
  driver: playwright
  ports: [8081, 3001]
  start_commands:
    backend: "./gradlew bootRun --args='...'"
    frontend: "npm run build && npx next start -p 3001"
  fixtures: sanitized
  db_clone: none
```

- `driver`: `playwright`, `emulator`, `native`, or `none`. Tells the QA stage how to drive the system.
- `ports`: ports QA uses, chosen so a developer's own servers keep running. The first port is available to boot arguments as `{port}`.
- `start_commands`: how to start each service, keyed by repo id; each runs from that repo's directory. Written into the QA stage prompt. `{scripts}/qa-data` is accepted as an alias for `sentinel qa-data` (write `sentinel qa-data boot-args qa`).
- `fixtures`: `sanitized` (preferred) or `clone` (copies real data; see [security.md](security.md)).
- `db_clone`: `none`, or the MySQL plugin block below.
- `scenario_run` (optional): the command the engine runs for QA scenarios as Red, Green and Refactor evidence (TDD-09). Placeholders `{scripts}` (the cycle's script folder under `.sentinel/cache/qa/tests/current/<slug>/<cycle id>`), `{report}` (the report file) and `{cycle}`. It runs from the repo directory (a relative path in it is looked up in the repo first, then in the workspace), after the engine started the repo's `start_commands` entry and waited for `ports`.
- `scenario_report` (optional): path of the JUnit XML report `scenario_run` writes, relative to `.sentinel/cache/qa/` (no `..`, not absolute). One `testcase` per scenario, `name` is the scenario id (its `@AC-...` tag); a failure message starts with the Gherkin keyword of the failing step (`Then the form shows 5 days: ...`); an `<error>` or another start is a script error.

### MySQL plugin (`qa.db_clone`)

```yaml
db_clone:
  engine: mysql
  connection:
    env_file: ./backend/.env
    url_var: DB_URL
    user_var: DB_USERNAME
    password_var: DB_PASSWORD
  databases:
    - { source: legacy_db, target: legacy_db_qa, refresh: if_missing }
    - { source: app_db, target: app_db_qa, refresh: always }
  fresh: { target: app_db_fresh, replaces: app_db }
  throwaway_suffixes: [_qa, _fresh]
  storage_dirs: [uploads]
  boot_args:
    - "--server.port={port}"
    - "--spring.datasource.url={jdbc:legacy_db}"
    - "--app.uploads.storage-dir={storage:uploads}"
```

- Credentials are read from the env file; host and port come from `url_var` (a JDBC URL) or `host_var` and `port_var`.
- Each entry in `databases` is cloned from `source` into `target`. `refresh: always` re-clones every run; `if_missing` reuses an existing copy (pass `--refresh-all` to force).
- `fresh` is an empty schema for the migrate-from-zero check. `replaces` names the source whose copy it stands in for in `boot-args fresh`.
- Safety: a target must end in one of `throwaway_suffixes` (default `_qa`, `_fresh`), and can never be a configured source. The tool refuses otherwise.
- `boot_args` placeholders: `{port}`, `{jdbc:<source-schema>}` (the cloned or fresh schema URL), `{storage:<name>}`.
- Commands: `sentinel qa-data prepare | fresh | drop-fresh | drop-all | boot-args <qa|fresh>`, plus `--dry-run` to print what would run. `sentinel clean --db` runs `drop-all`.

## release_checks

A list of check names. When omitted, the default is all of: `debug_output`, `todo`, `comments`, `secrets`, `new_dependencies`, `test_infra`, `commands`.

| Check | What it does |
|---|---|
| `debug_output` | Fails on added print, console.log, debugger and similar lines in non-test files. |
| `todo` | Fails on added TODO, FIXME, XXX. |
| `comments` | Fails on added code comments. Active only when `rules.no_code_comments` is true. |
| `secrets` | Fails on secret patterns in the diff (and gitleaks findings if gitleaks is installed), and on secrets or personal data in `.sentinel/shared`. |
| `new_dependencies` | Prints a notice when a dependency manifest changed; a human must approve new dependencies. Does not fail the run. |
| `test_infra` | Fails if test runners, configs, reports, or test-only dependencies remain in client repos. Active only when `rules.no_permanent_frontend_tests` is true. A QA-Red cycle commits no test file, so every test file or runner config in a client repo is flagged. Only a cycle that still has approved test files (a run planned before Phase J) has them skipped. |
| `commands` | Runs each repo's build, lint, typecheck, and test commands. |

Run it: `sentinel release-check`. It only checks repos that have uncommitted changes. Options: `--quick` skips all build, lint, typecheck and test commands; `--repo <id>` (repeatable) limits it to the repos your increment touched; `--skip build,lint` skips named commands (for example `build` while a dev server is running on that repo).

## stage_guidelines

```yaml
stage_guidelines:
  reviewer: .sentinel/shared/guidelines/reviewer.md
  qa: .sentinel/shared/guidelines/qa.md
```

Same idea as repo `guidelines`, keyed by stage name, for stages that are not tied to one repo (specifier, reviewer, qa, and so on).

## extra_checks

Project-specific release checks, defined in config, run in addition to the built-in ones. Each applies to repos with uncommitted changes (limit it with `repo`).

```yaml
extra_checks:
  - name: hard-coded UI text
    type: added_lines
    repo: frontend
    path_regex: '^src/.*\.(ts|tsx)$'
    pattern: '[\u1780-\u17FF]'
    exclude_path_regex: '^src/lib/format\.ts$'
    exclude_line_regex: ['^\s*(//|\*|/\*)']
  - name: migration name must be V<14 digits>__name.sql
    type: changed_paths
    repo: backend
    path_regex: 'db/migration'
    must_match: '/V[0-9]{14}__[a-z0-9_]+\.sql$'
  - name: already-applied migration edited
    type: changed_paths
    repo: backend
    path_regex: 'db/migration'
    status: modified
```

- `added_lines`: fails when an added line (in files matching `path_regex`, not matching `exclude_path_regex`) matches `pattern` and none of the `exclude_line_regex` patterns.
- `changed_paths`: fails for each changed file matching `path_regex` that has the given `status` (`any`, `modified`, or `added`) and, if `must_match` is set, does not match it.

## routing: a model or provider per stage (optional)

By default the AI tool you work in runs every stage itself, as subagents where it has them. Add `routing` to choose the runner (the AI tool) and the model for any stage. A routed stage is not a subagent: Sentinel starts that tool as its own headless process (`sentinel stage run`), in the background where your tool allows it, and checks the write boundary when it finishes. Independent stages, such as the coders of different repos, run side by side.

```yaml
routing:
  coder: { runner: claude, model: opus }
  backend-coder: { runner: claude, model: sonnet }
  qa: { runner: claude, model: sonnet }
  hardener: { runner: agy, model: gemini-3.8-flash-high }
  cleaner: { runner: gemini, model: gemini-2.5-flash }
```

- A key is a stage name (`repro`, `specifier`, `coder`, `cleaner`, `hardener`, `reviewer`, `qa`, `promotion`, `docs`, `rollout`, `retrospective`) or `<repo id>-<stage>`, which wins over the stage key for that repo. Repro uses the `coder` key unless it has its own.
- `runner` is `claude`, `codex`, `gemini`, `agy` or one you define under `runners`. `model` is passed to the tool's model flag, so use the names that tool accepts: `claude --model`, `agy --model` (`agy models` lists them), `gemini -m`, `codex -m`.
- A stage with no entry runs in the current session. The reviewer and QA never run inline, so give them a runner if your tool has no subagents.
- `single_model` (default `true`): one model, one tool. `routing` is ignored completely: every stage runs in the AI tool you opened (Claude Code, Antigravity, Codex, Cursor) with that tool's current model, as a subagent where it has them. Set `single_model: false` to turn `routing` on, so each stage uses its own runner and `model`. `--runner` and `--model` on `sentinel stage run` always work.
- `sentinel routing` prints what every stage will use and whether the CLI is installed. `sentinel doctor` fails when a routed CLI is missing, a model is set on a runner without a `model_flag`, or a model is written with its flag (`--model sonnet` instead of `sonnet`). `sentinel doctor --check-models` also asks each runner whether it accepts the model, and for `agy` suggests the closest id from `agy models`.
- Model names: you do not need full IDs. `claude` accepts the aliases `sonnet`, `opus` and `haiku` (always the latest of that family). `agy` uses the ids printed by `agy models`, such as `gemini-3.8-flash-high`; the display names ("Gemini 3.8 Flash (High)") are not accepted.
- One-off override: `sentinel stage run --stage qa --runner agy --model gemini-3.8-flash-high ...`.

### runners

The built-in runners `claude`, `codex`, `gemini` and `agy` need no configuration. Add a `runners` entry only to change one or to add your own tool; your keys are merged into the built-in entry, so you only list what differs.

```yaml
runners:
  agy:
    args: [--output-format, json, --mode, accept-edits]
  mytool:
    command: mytool
    prompt_flag: -p
    model_flag: --model
```

- A runner is a command line. Sentinel builds: `command` + `args` + (`model_flag` model) + (`resume_flag` id) + the prompt (after `prompt_flag` if set, or on stdin when `input: stdin`).
- `add_dir_flag`: the tool's flag for granting access to an extra directory (for example `--add-dir`). Sentinel passes the state folder, because stages run inside a repo but must read the brief and the invariants and write their result under `.sentinel/`. Without it, tools that sandbox file access to the working directory cannot do their job.
- `output: json_response` reads `status`, `response`, and the session id (`session_field`, default `conversation_id`) from the JSON the tool prints.
- `models`: model ids the dashboard offers for this runner (Settings > Agents). They are listed before the built-in suggestions for `claude` and `gemini`; "Custom" always accepts any id. A runner without `model_flag` offers none.
- `unsafe_skip_permissions: true` appends `unsafe_args` and prints a warning. Leave it false unless you accept that the tool will act without asking.
- Only `claude` and `agy` have been run for real in this project. Check the flags of `codex` and `gemini` against their own documentation.

## notifications

```yaml
notifications:
  desktop: true   # default; false hides "Enable desktop notifications" in the dashboard
```

`sentinel notifications` and the dashboard bell always work. `desktop` only controls whether the dashboard offers browser notifications: they are raised by the browser after you press "Enable desktop notifications" and the browser grants permission. Sentinel uses no operating system notification tool, no service worker and no push service.

## policies

```yaml
policies:
  max_parallel_tasks: 1        # default 1; tasks whose write scopes overlap never run together
  task_timeout_seconds: 5400   # default 5400; a task that runs longer is killed and fails
  test_timeout_seconds: 1800   # default 1800; the engine's own test and QA driver runs are killed after this
  provider_retries: 1          # accepted by the schema; it has no effect in 1.1.0 (task retries use `limits` and `agents.<role>.max_retries`)
  redact_env: [DATABASE_URL]   # extra environment variable names whose values the scrubber removes
  human_required: [real_data_clone]   # added to the two mandatory approvals
```

Version 2 runs only. `human_required` can add gates (`real_data_clone` makes QA on a clone of real data wait for `sentinel resolve --approve-clone`; `security_gate`, `destructive_migration`) and can never remove the specification and Gherkin approvals: an empty list keeps both.

## providers

```yaml
providers:
  default: claude
  fallback: [codex]    # tried in order when a runner is not installed or the provider fails
  disabled: []         # runners that must not be used, even by routing
```

Providers are the runners defined under [runners](#runners). The engine picks the provider of every task from `agents` (or `routing`) and this block; the agent that drives the run never chooses. A disabled or missing provider in `fallback` is skipped. Sentinel stores no API keys: each provider CLI keeps its own credentials.

### Global defaults and the dashboard

`<config dir>/config.yaml` (`~/.config/sentinel/config.yaml`, mode 0600) can hold `agents` and `providers`, the defaults you set in the dashboard under Settings. The engine does not merge this file at run time. Its values are copied into the `sentinel.config.yaml` of every project created afterwards (`POST /api/v1/projects`); existing projects keep what they have until you change them. `sentinel init` does not seed them.

The dashboard reads and writes this through the local API (all under `/api/v1/`, CSRF header on every change):

| Route | Use |
|-------|-----|
| `GET providers`, `POST providers/{id}/test` | Installed runners, and a `--version` probe of one. |
| `GET agents?project=<id>`, `PUT agents` | The effective runner and model of each role (the roles are the stage prompts in `sentinel/core/stages`) (project, then global, then `claude`). `PUT` with `scope: project` validates against the schema, writes `sentinel.config.yaml` atomically and records a configuration version; `sha256` guards against a stale edit (409). `scope: global` writes the file above. |
| `GET orchestrator`, `PUT orchestrator` | The server-wide AI tool that resumes dashboard runs, chosen from the installed runners (or none). |
| `POST projects`, `POST projects/register` | Create a workspace (like `sentinel init` without prompts, at least one repo) or register an existing one. |
| `DELETE projects/{id}` | Remove the project from the dashboard. Nothing is deleted on disk (the folder, `sentinel.config.yaml` and `.sentinel` stay); refused with 409 while a run is active. |
| `POST projects/{id}/repositories`, `DELETE projects/{id}/repositories/{repo}` | Edit `repos`. The last repo cannot be removed, nor any repo while a run is active. |
| `GET profiles`, `GET fs/dirs?path=` | Stack profiles and allowed repo roles; a directory browser (folders only). |

## agents

```yaml
agents:
  tdd_green: { runner: codex, model: gpt-5, max_retries: 3 }
  reviewer: { runner: claude, model: opus }
```

A key is a task role: `specifier`, `test_designer`, `tdd_red`, `qa_red` (reads the `tdd_red` retry cap), `tdd_green`, `tdd_refactor`, `reviewer`, `qa`, `docs`, `knowledge` (summarizes knowledge base records and module snapshots), or a repo role such as `backend-coder`. `runner` and `model` resolve exactly like [routing](#routing-a-model-or-provider-per-stage-optional); `max_retries` overrides the retry limit of that role (the TDD roles `tdd_red`, `tdd_green` and `tdd_refactor` read `tdd` instead). Role `knowledge` falls back to the runner configured for `coder`, then to the default runner; summarization can be turned off with `knowledge.summarize: false` or environment variable `SENTINEL_KB_NO_AGENT=1`. Write scope is not set here: read-only roles (`specifier`, `test_designer`, `reviewer`, `qa`, `retrospective`) always get an empty write scope, a coder role gets its repo, and `repos[].write_scope` narrows a repo further. A task that writes outside its scope fails with `E_SCOPE` and parks the run for a human.

## tdd

```yaml
tdd:
  red_retries: 2       # defaults
  green_retries: 3
  refactor_retries: 2
```

Retry limits of the three phases of a TDD cycle (the same keys exist under `limits`; `tdd` is read first). At the limit the cycle stops and `sentinel resolve` asks a human.

## verification

```yaml
verification:
  mutation: tier4          # tier4 (default), always or never
  migration_check: auto    # auto (default: when a migration file changed), always or never
  disabled: []             # checks to turn off: targeted, build, lint, typecheck, hygiene, secret, deps, mutation, migration, extra, docs_links, docs_build
  extra: []                # extra checks, the same shape as `extra_checks`
```

Verification is run by the engine, never by the agent. A check with no command, or turned off here, is recorded as not run; a configuration that would turn off a mandatory check is invalid.

## test and production globs

Per repo, `test_globs` and `production_globs` (and `test_infra_globs`) tell the TDD engine which files are tests and which are production code; Red may write only test files, Green only production files, and a file that matches both lists counts as a test file. Every shipped profile with a test runner names them; a repo entry overrides the profile key by key:

```yaml
repos:
  - id: backend
    path: ./api
    role: backend
    profile: spring-gradle
    test_globs: [src/test/**, '**/*Test.java']
    production_globs: [src/main/**]
```

A code repo with no usable globs cannot start execution. Globs are relative to the repo and may not contain `..`.

## rules

All default to `false`. A rule only adds its text to the stage prompts and the release check when it is on.

| Rule | Effect |
|---|---|
| `no_code_comments` | Agents write no comments; the release check and reviewer flag them. |
| `no_em_dashes` | Agents never write the em dash character. |
| `no_coauthor_trailer` | No Co-Authored-By or AI attribution lines. |
| `agents_never_run_git` | Agents never commit, push, stash, reset, or switch branches. |
| `no_permanent_frontend_tests` | Client repos (role `frontend` or `mobile`) keep no permanent test suite. In a version 2 run their behavior groups use QA scenarios as the Red evidence (TDD-09): a `qa_red` task writes the scripts, the engine runs them through `qa.scenario_run`, and the exception is recorded in the cycle, the evidence rows, the events and the report. R12 refuses the run (NEEDS_HUMAN, `E_PRECONDITION`) when the QA driver is not usable: configure `qa.driver`, `qa.scenario_run`, `qa.scenario_report` and `qa.start_commands`, then run `sentinel resolve <slug> --refresh-config -m "..."`, or turn the rule off. The release check fails if test infrastructure is left behind. |

## knowledge

Controls the team knowledge base ([knowledge.md](knowledge.md)) in the shared repo.

```yaml
knowledge:
  enabled: true                 # default true; false turns off harvesting and ingest
  auto_push: true               # default true; automatically push knowledge/ and proposals/knowledge-*
  backfill_months: 3            # default 3; history window in months for initial backfill
  max_changes_per_ingest: 200   # default 200; cap on changes processed per ingest run
  summarize: true               # default true; false produces deterministic records without agent calls
  max_summaries: 300            # default 300; agent calls per command or worker job
```

- `enabled`: when `false`, background harvest after runs and catch-up ingest are skipped.
- `auto_push`: when `true`, the background worker commits and pushes `knowledge/` and `proposals/knowledge-*` after `scrub --check` passes. It never pushes unpushed specifications, invariants, or tests.
- `backfill_months`: default history window used by `sentinel kb backfill` and initial branch ingest.
- `max_changes_per_ingest`: safety cap per invocation. The cursor advances commit-by-commit, keeping ingest resumable.
- `summarize`: when `false`, change records and snapshots use deterministic git metadata only (no agent calls).
- `max_summaries`: the most agent calls one command or one worker job makes for summaries (default 300). After that, records and summaries keep only their deterministic part; `0` turns agent calls off.

Summarization routes through role `knowledge` under `agents` (fallback: `coder`, then default runner; see [agents](#agents)).

## factory

Controls who drives a run and how much runs at once (Sentinel 2.0).

```yaml
factory:
  driver: engine                # default engine; engine | ai-tool, for runs created at the dashboard
  max_tasks_per_project: 2      # default 2; agent tasks running at once in this project
  max_agents: 4                 # default 4; agent tasks running at once over every project of the service
```

- `driver`: `engine` means the Sentinel service runs the run itself: triage and the decisions file are agent tasks (roles `triage` and `planner`), verification is called in the service, and the AI tool is used for the work only. `ai-tool` keeps the earlier behavior: an AI tool runs the `/sentinel` skill loop around `sentinel next`. A run created with `sentinel run new` is driven by you (`cli`) unless you pass `--driver engine --request "<text>"`. One driver owns a run: `sentinel next` on an engine-driven run answers `wait` with `driven_by: engine`.
- An engine-driven run starts only when every role it may use routes to a CLI runner: set `agents.<role>.runner` (or `routing`) for `triage`, `planner`, `specifier`, `test_designer`, `tdd_red`, `tdd_green`, `tdd_refactor`, `reviewer`, `qa`, `hardener` and `docs`. The native adapter needs an AI tool session and is refused. Otherwise the run is BLOCKED with the roles named; fix the config and run `sentinel resolve <slug> --refresh-config -m "..."`.
- `max_tasks_per_project` and `max_agents`: the dispatcher starts no further task while either limit is reached; the run waits in the queue the factory view shows. Running tasks are never stopped by a limit.
- `sentinel pause <slug>` and `sentinel unpause <slug>` stop and resume starting tasks for one run; `sentinel note <slug> "<text>"` adds a note that the next agent task of the run receives in its prompt (section "Note from the owner"), once.

## limits

```yaml
limits: { review_rounds: 2, qa_rounds: 3, release_check_rounds: 3 }
```

At a cap the run stops and reports "not production-ready". `sentinel resume` lists capped loops.

## state

```yaml
state:
  dir: .sentinel
  retention: { runs: 20, logs_days: 14 }
  shared_repo: git@host:myteam/myteam-sentinel-shared.git
  auto_sync_push: false
  shared_ref: main
```

- `dir`: local state folder. Contains `runs/`, `cache/`, `shared/` (a clone of the shared repo), and `generated/`.
- `retention`: `sentinel clean` keeps the newest `runs` run folders and deletes cache files older than `logs_days`.
- `auto_sync_push` (default `false` since 1.1.0; a config that does not set it means off): when set to `true`, a passing 0.1 run's specs, regression tests and proposed invariants are pushed straight into the shared repo's main branch without asking and without a pull request. The scrub check still gates it, and the agent resolves merge conflicts. Version 2 runs never push by themselves, whatever this says.
- `shared_mode` (`git` default, or `local`): `local` means no shared repo. Rules, specs and regression tests live only in `.sentinel/shared/` on this machine (a plain folder, no git), run locks are files, and `sync push` only runs the scrub check. Set up with `sentinel init --local-only`; move to a team repo later with `sentinel shared set <url>`.
- `shared_repo` (**required** unless `shared_mode: local`): clone URL of the team's private shared repo. `sentinel init` asks for it and `sentinel shared set <url>` changes it. `sentinel doctor` fails and `sentinel run new` refuses while it is missing or not cloned.
- `shared_ref`: the branch, tag, or commit to use. Pin a tag or commit for reproducible runs.

## tracker

```yaml
tracker: { kind: github, url: https://github.com/myteam/myrepo }
```

`kind` is `none`, `gitea`, `github`, `gitlab`, or `jira`. Currently only used to tell the docs stage which tracker to link issues from.
