# Operations

Everyday commands for running Sentinel 1.1.0: notifications, statistics, the audit log and backups. They read the registry of the workspace (`.sentinel/sentinel.db`) and never change a run. Run them from the workspace, or pass `--dir`.

## Notifications

`sentinel notifications` lists what needs you. A notification is computed from the registry's events, so there is nothing to clear and nothing is stored with the run:

| Event | Notification |
|---|---|
| Specification or Gherkin ready for review | action: review and approve |
| Changes requested | info |
| Run started | info |
| Run needs a human, or is blocked | action or warning, with the reason |
| A task failed, or a provider is unavailable | warning |
| A verification check failed | warning |
| Knowledge harvest failed | warning |
| A provider usage limit was reached (`task.limit_reached`) | warning, with the retry time and `sentinel resolve <slug> --retry-now`; info when `routing.fallback` took over |
| Run completed and waiting for acceptance | action: `sentinel accept` |
| Run accepted, rejected or failed | info or warning |

```bash
sentinel notifications                 # all, newest first
sentinel notifications --unread        # prints nothing when there are none
sentinel notifications --json --project digital-hr --limit 20
sentinel notifications read digital-hr:123    # mark one read (the id is <project>:<event number>)
sentinel notifications read --all
```

Which notifications you have read is kept only in `~/.config/sentinel/user.db` (project, registry id, event id and times; no text). Reading does not write to the registry or the audit. The file is created by the first "mark read", not by a fresh install. Text is scrubbed before it is shown. The dashboard bell shows the same list. Desktop notifications are raised by your browser after you press "Enable desktop notifications" and the browser grants permission; `notifications.desktop: false` in the config hides the option (see [config](config.md#notifications)). Sentinel uses no operating system notification tool, service worker or push service, and sends nothing outside the machine.

An agent cannot mark notifications read: `sentinel notifications read` is refused inside a task process.

## Usage limits

A provider CLI that exits non-zero with a usage, quota or rate-limit message (Claude "usage limit reached ... resets 3pm", Gemini and Antigravity `RESOURCE_EXHAUSTED` or "quota exceeded ... reset after 1h2m", Codex "try again at 3:45 PM", HTTP 429) does not fail the task. The task returns from RUNNING to QUEUED with `retry_at` and the reason; the dispatcher starts it after that time, and the run is not parked. Patterns are kept in one table per runner in `sentinel/scripts/limits.py`. Without a parsable time the wait is `routing.limit_backoff` minutes (default 30). With `routing.fallback` the task moves to the fallback runner at once. A task waiting for a usage limit can also be retried immediately via `sentinel resolve <slug> --retry-now` or the floor side panel "Retry now" button (`POST /api/v1/tasks/{slug}/retry-now`). See [config](config.md#routing-a-model-or-provider-per-stage-optional).

Registry migration 0014 adds the columns `tasks.retry_at`, `limit_reason` and `limit_hits`. Registry migration 0015 adds columns `tasks.input_tokens` and `tasks.output_tokens`. They are additive; to roll back, restore the registry backup taken at upgrade (`sentinel.db.bak-13` / `sentinel.db.bak-14`), since older versions do not read these columns.

## Daily project budget

Projects can configure an optional daily budget in `sentinel.config.yaml`:
```yaml
factory:
  budget:
    tokens_per_day: 1000000
    usd_per_day: 20.0
```
When total tokens or total USD cost reported by tasks finished on that UTC day reach the budget ceiling:
- The factory dispatcher pauses starting new agent tasks for that project until the next day (00:00 UTC).
- Tasks currently executing finish normally.
- An in-app notification `budget.reached` is raised once per day (no desktop notification).
- A warning banner appears on the factory floor.

## Stats and analytics

`sentinel stats` prints the 0.1 statistics (which count 0.1 runs only) plus a `v2` section for version 2 runs:

```bash
sentinel stats
sentinel stats --from 2026-11-01 --to 2026-11-30 --format md
sentinel stats --usage [--project digital-hr] [--since 2026-11-01] [--format md|json]
```

`--from` and `--to` filter on the run's creation date (UTC, inclusive). `--format md` prints a Markdown table. `--usage` outputs usage totals (tokens, input/output tokens, cost, seconds, tasks) and breakdowns by model, week, and role. Stats open the registry read only and never create it. The dashboard's Reports screen and `GET /api/v1/reports/analytics` give the same numbers.

| Metric | Definition |
|---|---|
| Lead time | created to finished, for runs that finished as completed or failed (a cancelled run is left out): median and p90 |
| Acceptance rate | accepted runs over decided (accepted or rejected) runs |
| Approval wait | from the `approval.requested` event to the decision; never negative |
| Retries | retry tasks |
| Provider failure rate | `E_PROVIDER` failures over finished tasks of the provider |
| TDD cycles | cycles accepted, and rejected per phase |
| Verification pass rate | per check, and the share of runs that passed on the first attempt (finished runs only) |
| Rework | specification and Gherkin revisions, changes requested, findings routed back |
| Cost | summed from the cost that tasks reported, labelled partial when some did not; nothing is estimated from tokens |

A value that cannot be computed is shown as not reported, with the reason, never as 0.

## Audit export and verify

Every human action, approval, acceptance and control writes an audit row. The audit is append-only: triggers refuse changes, and each row carries a hash that chains it to the one before.

```bash
sentinel audit export --out audit.jsonl                      # scrubbed JSON lines
sentinel audit export --out audit.csv --format csv --from 2026-11-01 --to 2026-11-30 --actor dev --channel tty --action approve --run leave-balance
sentinel audit export --out audit.jsonl --force              # replace an existing file
sentinel audit verify                                        # the registry of this workspace
sentinel audit verify --file audit.jsonl                     # an export, against itself
sentinel audit verify --file audit.jsonl --db .sentinel/sentinel.db   # and against the registry
```

`verify` names the first broken row. Exports are scrubbed; rows the scrubber changed are marked, and CSV cells that start with a formula character get a leading apostrophe. The chain detects edits made by other tools; it does not stop a process running as your user from rewriting the whole chain (see [security](security.md#residual-risks)). Keep an export somewhere the agent user cannot write if you need that proof. Export is for humans: it is refused inside a task process.

## Backup, verify and restore

```bash
sentinel backup                       # copies the registry into .sentinel/backups/ (git-ignored, mode 0600)
sentinel backup --out /safe/place
sentinel backup --verify .sentinel/backups/sentinel-20261115T100000Z.db
sentinel backup --force               # keep a copy even when the audit chain is broken
sentinel backup restore .sentinel/backups/sentinel-20261115T100000Z.db
```

A backup uses the SQLite backup API, so it is consistent while the server runs, and it is checked (integrity, row counts, audit chain) before it is kept. `--verify` checks a copy later. It holds the workspace registry only: run folders, config files and `user.db` are not in it (copy run folders yourself, or use `sentinel run export`). Old backups are never deleted for you.

`restore` is for a human at a terminal: it replaces the registry, so it asks you to type the first 8 characters of the backup's hash, refuses while a task or a Sentinel server is running, and first saves the current registry as `backups/pre-restore-<time>.db`. A backup is as sensitive as the registry, which holds unscrubbed request text; see [security](security.md#audit-log-and-backups).

## Knowledge base

Commands for inspecting the team [knowledge base](knowledge.md) and background harvesting jobs:

```bash
sentinel kb status
sentinel kb status --json
```

`sentinel kb status` reports tracked branch cursors, record counts (total, active, and dropped), counts by repository, and the state of background harvesting jobs (`queued`, `last_success`, `last_failure`).

### Worker logs and lock

The background harvest worker logs to:

```
.sentinel/kb-worker.log
```

The worker acquires a PID lock file at `.sentinel/kb-worker.lock` to ensure only one worker processes harvest jobs per workspace. Dead worker locks are detected and replaced automatically.

### Retrying failed jobs

The worker automatically retries transient errors up to 3 times with backoff (5s, 30s). When a job fails permanently (for example, if `scrub --check` detects a secret) or retries are exhausted, the job state becomes `failed` and triggers a `knowledge.failed` notification. The registry does not provide a separate retry command; after fixing the problem (e.g. updating scrub patterns or credentials), re-run `sentinel kb ingest` with `--publish` to ingest and publish current changes.

## Service management

Sentinel 2.0 runs as a background service:

```bash
sentinel service start                # start the service detached in the background
sentinel service start --port 8765    # fix the port
sentinel service stop                 # stop the running service (or: sentinel stop)
sentinel service status               # status, PID, port, uptime, projects, log path
sentinel service status --json        # machine-readable JSON status (includes factory_paused)
sentinel service pause -m "reason"    # pause the whole factory: no new agent task starts in any project
sentinel service resume               # resume it (runs keep their own pause)
sentinel service run                  # run the server in the foreground
```

The service logs to `~/.config/sentinel/service.log`.

`sentinel service pause` (the dashboard's **Pause factory** button does the same) writes `~/.config/sentinel/factory.json`. While it is set the service starts no new agent task in any project; tasks already running finish, and `sentinel service status` shows `Factory: paused`. Each change is recorded in the audit log of every project as `factory_pause` or `factory_resume`. Both commands need a terminal and are refused inside a task process.

On startup, the service automatically inspects registered projects for tasks left in `RUNNING` state by a previous server process and recovers them. Tasks that were interrupted are safely marked for retry.

### Autostart

On Linux, Sentinel can start automatically at login via a systemd user unit:

```bash
sentinel service autostart on         # write unit and enable via systemctl
sentinel service autostart off        # disable and remove unit
sentinel service autostart status     # check autostart status
```

The user unit file is installed at `~/.config/systemd/user/sentinel.service`. On non-Linux operating systems, autostart is Linux-only in 2.0.

## Release checklist

For the maintainer who cuts a release. The gate never tags, publishes or pushes; those steps stay with you.

1. Start from a clean checkout of the release commit (`git status` shows nothing). The gate refuses a dirty tree.
2. Build the dashboard: `cd dashboard && npm ci && npm run build`.
3. Build the release wheel: `SENTINEL_RELEASE=1 python3 -m build --wheel` (or `hatchling build -t wheel`). A release build refuses a missing or stale dashboard build and names `npm run build`.
4. Run the gate: `python3 tools/release_gate.py`. It runs the dashboard scripts, the offline wheel install, the selftest, the unit and security suites and the acceptance-criteria check, and writes `release-evidence.json`. `--allow-dirty` runs everything on a dirty tree but can never report "release ready".
5. The gate prints `release ready` only when every manual item in `tests/release/manual.json` has `status: done` with a date and a machine. Until then it prints `release candidate: N manual checks pending owner` and lists them.
6. Do the manual checks on a machine that allows user namespaces and with a screen reader: the loopback-only namespace runs (AC-OPS-01i, AC-DSH-06g) and the screen-reader pass. Record each in `tests/release/manual.json` as `status: done`, with the date and the machine.
7. The wheel to publish is `sentinel_pipeline-2.0.0-py3-none-any.whl` (distribution `sentinel-pipeline`, command `sentinel`), with the sdist. It includes the dashboard UI; a `uv tool install git+https://…` install has the CLI without it (see [installation](installation.md#the-dashboard-ui)).
8. Tag and push: `git tag v2.0.0 && git push origin v2.0.0`. The tag must equal `v` plus the content of `sentinel/VERSION`. The release workflow (below) then reruns the gate, publishes the wheel and sdist to PyPI and pushes the image `ghcr.io/chhunlyyy/sentinel` with the tags `2.0.0` and `latest`. Nothing in this repository tags or publishes by itself.
9. Check the result: `uv tool install sentinel-pipeline` in a clean environment prints `sentinel --version` 2.0.0, and the documented `docker run` command in the README shows the dashboard.

## Release workflow and repository settings

`.github/workflows/release.yml` runs when a tag `v*` is pushed: `gate` (runs `tools/release_gate.py` on the tag and fails unless the evidence says `release_ready`, so pending manual checks fail it with their ids), `build` (dashboard, then wheel and sdist with `SENTINEL_RELEASE=1`, uploaded once), `publish-pypi` and `publish-image`. It is prepared and has not been run. Before the first tag, set up:

1. **PyPI trusted publisher.** On pypi.org create the project `sentinel-pipeline` (or a "pending publisher" for it) and add a trusted publisher with: owner and repository `chhunlyyy/sentinel`, workflow file `release.yml`, environment `pypi`. No API token is stored anywhere; the job uses OpenID Connect (`id-token: write`).
2. **GitHub environment.** Create the environment `pypi` in the repository settings (optionally with required reviewers, so a human approves each publish).
3. **Packages write permission.** The image job pushes with the `GITHUB_TOKEN` and `packages: write`. In Settings, Actions, General, "Workflow permissions" must allow the workflow to request it (read and write permissions, or leave the default read-only token: the workflow declares what each job needs). After the first push, set the package `sentinel` under Packages to **public** (and link it to the repository) so `docker run ghcr.io/chhunlyyy/sentinel` works without a login.
4. **Tags.** Protect tags matching `v*` so only maintainers can create them.
5. The action versions in the workflow are exact release tags. For stricter supply-chain pinning replace each with the commit hash of that tag.
6. Node is pinned to the same exact version (`22.18.0`, the minimum the dashboard's `engines` asks for) in `dashboard/.nvmrc`, the workflow and the `Dockerfile`; change the three together. The gate job installs `pyyaml` and `jsonschema` and the Playwright browser itself, and the workflow allows one release run per ref at a time. The gate job needs a runner that allows user namespaces (the workflow lowers the Ubuntu restriction) and Docker (the image tests run there); `tests/release/manual.json` must have every item with `status: done` before a tag, or the workflow stops at the gate.
