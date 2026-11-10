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
| `test_infra` | Fails if test runners, configs, reports, or test-only dependencies remain in client repos. Active only when `rules.no_permanent_frontend_tests` is true. |
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
- `single_model` (default `true`): never pass a model to any stage. Every stage uses the current model of whichever tool runs it (the `model` values in `routing` and in the generated Claude agents are ignored; `routing` still picks the runner). Set `single_model: false` to use the per-stage `model` values. `--model` on `sentinel stage run` always wins.
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
- `unsafe_skip_permissions: true` appends `unsafe_args` and prints a warning. Leave it false unless you accept that the tool will act without asking.
- Only `claude` and `agy` have been run for real in this project. Check the flags of `codex` and `gemini` against their own documentation.

## rules

All default to `false`. A rule only adds its text to the stage prompts and the release check when it is on.

| Rule | Effect |
|---|---|
| `no_code_comments` | Agents write no comments; the release check and reviewer flag them. |
| `no_em_dashes` | Agents never write the em dash character. |
| `no_coauthor_trailer` | No Co-Authored-By or AI attribution lines. |
| `agents_never_run_git` | Agents never commit, push, stash, reset, or switch branches. |
| `no_permanent_frontend_tests` | Client repos keep no permanent test suite; the release check fails if test infrastructure is left behind. |

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
  auto_sync_push: true
  shared_ref: main
```

- `dir`: local state folder. Contains `runs/`, `cache/`, `shared/` (a clone of the shared repo), and `generated/`.
- `retention`: `sentinel clean` keeps the newest `runs` run folders and deletes cache files older than `logs_days`.
- `auto_sync_push` (default `true`): when a run passes, `/sentinel` pushes its specs, regression tests and proposed invariants straight into the shared repo's main branch without asking and without a pull request. The scrub check still gates it, and the agent resolves merge conflicts. Set `false` to be asked first.
- `shared_mode` (`git` default, or `local`): `local` means no shared repo. Rules, specs and regression tests live only in `.sentinel/shared/` on this machine (a plain folder, no git), run locks are files, and `sync push` only runs the scrub check. Set up with `sentinel init --local-only`; move to a team repo later with `sentinel shared set <url>`.
- `shared_repo` (**required** unless `shared_mode: local`): clone URL of the team's private shared repo. `sentinel init` asks for it and `sentinel shared set <url>` changes it. `sentinel doctor` fails and `sentinel run new` refuses while it is missing or not cloned.
- `shared_ref`: the branch, tag, or commit to use. Pin a tag or commit for reproducible runs.

## tracker

```yaml
tracker: { kind: github, url: https://github.com/myteam/myrepo }
```

`kind` is `none`, `gitea`, `github`, `gitlab`, or `jira`. Currently only used to tell the docs stage which tracker to link issues from.
