# Changelog

## 1.2.4

### Changed

- A repository with no test command no longer fails the project's readiness (and so no longer disables Create task). It is a warning now: the engine asks for a test command only when a run changes that repo, and docs runs never need one.

### Fixed

- Saving a global default on Settings > Agents failed with "single_model is a project setting", because the page sent `single_model` in the global scope. It is now sent only for a project, and the checkbox is hidden in the global scope.

## 1.2.3

### Fixed

- Removing a repository and deleting a project in the dashboard were refused with "a run is active" for any project with imported 0.1 runs, because their state `LEGACY` counted as active. Only version 2 runs that are not finished block them now.

## 1.2.2

### Added

- Delete a project in the dashboard ("Delete project" on the project page, `DELETE /api/v1/projects/{id}`). It only removes the project from the dashboard; the folder, `sentinel.config.yaml` and `.sentinel` stay on disk. It is refused while a run is active and recorded in the audit.

### Changed

- The last repository of a project keeps its Remove button disabled, with a hint that a project needs at least one repository; the server messages for refused removals are shown.

## 1.2.1

### Fixed

- The release gate no longer fails on a machine without the `claude` command (`test_orchestrator_get_put` assumed it was installed). This release was built without the delete-project change that was meant to ship with it; 1.2.2 has it.

## 1.2.0

The dashboard gets provider and agent setup, project creation and a new look.

### Added

- `sentinel dashboard [provider]`: name the AI tool that orchestrates dashboard runs (a runner id such as `claude`). Without one, the installed providers are listed and you pick. While the server runs, a dashboard-created run that reaches an orchestrator step starts that tool headless (`/sentinel resume <run>`), at most 3 times per state. `SENTINEL_ORCHESTRATOR` (`none` or a runner id) skips the question.
- Settings > Providers (installed providers, a Test button, the orchestrator choice) and Settings > Agents (provider and model per role, fallback, disabled and default providers, `single_model`; for one project or as a global default that is copied into projects created later). Agent roles come from the stage prompts in `sentinel/core/stages`.
- Model choice per provider, with built-in suggestions for `claude` and `gemini`, the new optional `runners.<id>.models` config key, and a custom id.
- Create a project in the dashboard (folder picker, any number of repositories, local or shared git), register an existing folder, and add or remove repositories. `sentinel init` and the dashboard share one module.
- New API routes: `providers`, `providers/{id}/test`, `agents` (GET and PUT), `fs/dirs`, `projects` (POST), `projects/register`, `projects/{id}/repositories` (POST and DELETE), `profiles`, `orchestrator`.

### Changed

- The dashboard has a new design: tokens, light and dark themes, 44px touch targets, icons in the navigation, a phone layout.
- The API checks the CSRF header on PUT and DELETE as well as POST.
- `docs/dashboard.md` no longer calls projects, repositories and configuration read only.

## 1.1.0

The first release with version 2 runs, the local dashboard and the registry. Existing 0.1 runs and workspaces keep working; read the [migration guide](docs/migration-1.1.md) before upgrading.

### Added

- Version 2 runs with two approvals: a human approves the specification, then the Gherkin scenarios, in a terminal (the first characters of the hash must be typed) or in the dashboard. Any later change invalidates the approvals.
- TDD cycles and independent verification: one Red, Green and Refactor cycle per behavior, each phase checked by the engine within the task's write scope; verification, acceptance rules, `report.json` and `report.md`, and a human acceptance step. Agent claims are never evidence.
- Provider-neutral tasks: CLI and native adapters, fallbacks, write scopes, parallel limits, retries, timeouts, cancel and resume after an interruption.
- Local dashboard and API: `sentinel dashboard` serves a React dashboard and an HTTP API on 127.0.0.1 with a session token, Host, Origin and CSRF checks and server-sent events; works offline; keyboard and automated accessibility (axe) tested; manual screen-reader check not performed before this release (waived by the owner; accessibility feedback from real use is welcome). The dashboard UI is in the PyPI wheel (`sentinel_pipeline-1.1.0-py3-none-any.whl`) only; a `uv tool install git+https://…` install has the CLI without the dashboard UI (see [installation](docs/installation.md#the-dashboard-ui)).
- Registry `.sentinel/sentinel.db` (SQLite, WAL, migrations with a backup before each upgrade) and `sentinel doctor` health checks shared with the dashboard.
- Notifications, stats, audit export, backup: `sentinel notifications`, `sentinel stats` (lead time, acceptance rate, approval wait, provider failures, cost as reported), `sentinel audit export` and `verify` over a hash-chained append-only audit, and `sentinel backup` with verify and restore.
- A security suite (`tests/security/`) that asserts each threat and the residual risks, and a release gate (`tools/release_gate.py`).
- New config keys, all optional: `policies`, `providers`, `agents`, `tdd`, `verification`, `notifications`, per-repo `test_globs` and `production_globs`.
- One-command install: `uv tool install sentinel-pipeline` (PyPI distribution `sentinel-pipeline`; the command and the import package stay `sentinel`), and a dashboard-only Docker image, `docker run --rm -it --init -p 127.0.0.1:8765:8765 -v "$PWD":/work -v sentinel-config:/home/sentinel/.config/sentinel ghcr.io/chhunlyyy/sentinel`. New `sentinel dashboard` options `--bind 0.0.0.0` (container image only: needs `SENTINEL_CONTAINER=1` and a container marker; the server then answers only loopback and the container gateway, `--allow-peer IP` adds more), `--public-host localhost:PORT` (outside a container its port must be the server port) and `--allow-peer`. `SENTINEL_APPROVER_NAME` sets the approver display name in the container. A tag-triggered release workflow (`.github/workflows/release.yml`) is prepared for PyPI trusted publishing and GHCR.
- TDD-09: with `rules.no_permanent_frontend_tests` on, a behavior group of a client repo (role `frontend` or `mobile`) uses its Gherkin scenarios, run through the QA driver, as the Red evidence. New role `qa_red`, new optional keys `qa.scenario_run` and `qa.scenario_report`, the engine runs the scripts and records the exception (events, evidence rows, `tdd_exceptions` in the report), the `tdd` and `verification` API answers gain `red_method` and `exception`, and `sentinel resolve <slug> --refresh-config` lets a human re-snapshot the config of a parked run. Registry migration 0011.
- Guides: `docs/dashboard.md`, `docs/operations.md`, `docs/migration-1.1.md`.

### Changed

- `sentinel run new` creates a version 2 run unless `--legacy`, `--tier` or `--adhoc` is given.
- `run update`, `resume` and `stage run` are refused for version 2 runs; `run finish` on a version 2 run needs a terminal.
- `state.auto_sync_push` is off when not set (auto_sync_push off when not set; it meant on in 0.1). Configs created by 0.1 `sentinel init` contain `auto_sync_push: true` and stay on after the upgrade (`sentinel doctor` notes it); set it to `false` to stop automatic publishing. Only new 1.1.0 configs default to false. Version 2 runs never auto-push.
- `sentinel sync-adapters` writes deny rules for `approve`, `accept`, `resolve`, the dashboard command and the token file.
- `sentinel stats` keeps its 0.1 keys and adds a `v2` section.
- The skills drive version 2 runs through `sentinel next`.
- `docs/security.md` has a "Residual risks" section.

### Removed

- sentinel submit removed (use `sentinel task run` and `sentinel task complete`).

### Security

- Residual risks R1 and R3 are stated plainly in [docs/security.md](docs/security.md#residual-risks): an agent running as your OS user can drive a pseudo-terminal or read the token file (R1), and Sentinel cannot stop a provider CLI from running a command during a task (R3). Deny rules are advisory; strong separation needs another OS user or a sandbox.
- Approvals need a terminal and the typed hash prefix; the dashboard needs a session cookie, CSRF value and matching Host and Origin; the token never stays in the URL; agent environments are stripped of the token and secrets; logs, reports, exports and notifications are scrubbed (a safety net, not a guarantee); content from runs is rendered as text.
- Known limits: the scrubber is quadratic on very long lines (mitigated by cutting log lines at 8 KiB); the Flutter `tojunit` path is untested offline; the dashboard test that runs inside a network namespace needs user namespaces and is skipped where they are not allowed (pending owner run on a machine that allows them).
- Migration guide: [docs/migration-1.1.md](docs/migration-1.1.md).

## 0.1.0b7

The last 0.1 beta: the tiered pipeline of stages, run through skills and `sentinel` commands, with a shared repo for specs and regression tests.
