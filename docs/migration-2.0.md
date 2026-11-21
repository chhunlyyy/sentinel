# Migrating from 1.x to 2.0.0

Sentinel 2.0 moves from an AI-tool-orchestrated loop to a software factory driven by the Sentinel background service. It introduces the live Factory Floor, guided project setup and configuration forms in the dashboard, and includes the team knowledge base.

This page explains what changes for existing projects, how to upgrade, and how to keep 1.x behavior if needed. For migrating from earlier 0.1 releases to 1.1.0, see [Migrating from 0.1 to 1.1.0](migration-1.1.md).

## Upgrade

1. Install the 2.0.0 engine:

   ```bash
   uv tool install --force sentinel-pipeline
   sentinel --version
   ```

   (pipx: `pipx install --force sentinel-pipeline`.) The PyPI wheel includes the dashboard.

2. Update your AI tool skills:

   ```bash
   npx skills@latest update
   ```

3. In your workspace, run:

   ```bash
   sentinel doctor
   ```

   `doctor` checks configuration syntax, required tools, repository paths, and runner CLIs.

## What changes

- **Existing runs keep their driver.** Runs created in 1.x retain their recorded driver (`ai-tool` or `cli`). They continue under their existing state machine and are not modified by the upgrade.
- **Dashboard-created runs default to the engine driver.** Runs started from the dashboard now default to `factory.driver: engine`. The Sentinel service drives each step (triage, planning, TDD cycles, in-process verification, and reporting) without requiring an AI tool to run the `/sentinel` skill loop.
- **Routing preflight for engine-driven runs.** An engine-driven run requires a CLI runner (`claude`, `codex`, `gemini`, `agy`, or a custom runner under `runners`) for every role it may start: `triage`, `planner`, `specifier`, `test_designer`, `tdd_red`, `tdd_green`, `tdd_refactor`, `reviewer`, `qa`, `hardener`, `docs` (and `qa_red` if `rules.no_permanent_frontend_tests` is on). The native adapter requires an interactive AI tool session and is refused. If any role lacks a CLI runner, the run enters `BLOCKED` with a preflight error naming the missing roles.
  - *How to fix a blocked run*: Set `agents.<role>.runner` (or `routing`) in `sentinel.config.yaml`, then run `sentinel resolve <slug> --refresh-config -m "<why>"`. The engine re-snapshots the configuration and resumes the run.
- **How to keep the 1.x behavior.** To have dashboard runs driven by your AI tool via the `/sentinel` skill as in 1.x, set `factory.driver: ai-tool` in `sentinel.config.yaml`:

  ```yaml
  factory:
    driver: ai-tool
  ```

- **CLI `sentinel run new` defaults to `cli` driver.** Running `sentinel run new <slug>` without `--driver` creates a run driven by you or an AI tool (`cli`). To create an engine-driven run from the terminal, pass `--driver engine` and `--request "<text>"`.
- **Background service replaces the foreground server.** `sentinel dashboard` now launches a detached Sentinel background service if it is not already running. Closing the terminal or browser no longer interrupts active factory runs. Stop the service with `sentinel stop` (or `sentinel service stop`). To keep the server attached to your terminal in the foreground as before, pass `--foreground`:

  ```bash
  sentinel dashboard --foreground
  ```

- **Factory floor is the landing screen.** When one or more projects are registered, the dashboard opens directly on the Factory Floor (`/floor`). The Overview screen remains available at `/overview`.
- **Project wizard and settings editor in the GUI.** Projects can be created from the dashboard at `/projects/new` using a 5-step wizard with automatic stack and command detection. Settings in `sentinel.config.yaml` can be edited in the dashboard under Settings > Project settings with schema validation, unified YAML diff preview, and version history.
- **Knowledge base is included.** The team knowledge base captures changes continuously into `.sentinel/shared/knowledge/` in your shared repository. Run `sentinel kb status` to check status, or run `sentinel kb backfill` to index historical commits with estimate confirmation.
- **Docker image unchanged.** The image `ghcr.io/chhunlyyy/sentinel` serves the dashboard. Container mode (`--bind 0.0.0.0`) stays in the foreground as the container main process.

## What is untouched

- **State machine and human gates.** The core version 2 state transitions remain unchanged. Specification approval, Gherkin scenario approval, and final acceptance still require typing the 8-character hash prefix in the terminal or in the dashboard.
- **CLI commands.** Every CLI command (`sentinel run new`, `triage`, `review`, `approve`, `next`, `verify`, `report`, `accept`, `resolve`, `task`) continues to work.
- **Existing project configuration.** `sentinel.config.yaml` files from 1.x remain valid. The `factory` block is optional and adopts defaults (`driver: engine`, `max_tasks_per_project: 2`, `max_agents: 4`) when omitted.

## Rollback

To roll back to 1.2.4:

```bash
uv tool install --force sentinel-pipeline==1.2.4
```

(pipx: `pipx install --force sentinel-pipeline==1.2.4`.) Existing version 2 runs and registry files remain readable: the 2.0 columns have defaults, so 1.2.4 ignores them. Runs that the 2.0 engine was driving are not driven by 1.2.4; continue them with your AI tool (`/sentinel resume <slug>`). Stop any running 2.0 service (`sentinel stop`) before starting the earlier version.
