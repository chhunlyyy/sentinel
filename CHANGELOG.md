# Changelog

## 1.1.0

The first release with version 2 runs, the local dashboard and the registry. Existing 0.1 runs and workspaces keep working; read the [migration guide](docs/migration-1.1.md) before upgrading.

### Added

- Version 2 runs with two approvals: a human approves the specification, then the Gherkin scenarios, in a terminal (the first characters of the hash must be typed) or in the dashboard. Any later change invalidates the approvals.
- TDD cycles and independent verification: one Red, Green and Refactor cycle per behavior, each phase checked by the engine within the task's write scope; verification, acceptance rules, `report.json` and `report.md`, and a human acceptance step. Agent claims are never evidence.
- Provider-neutral tasks: CLI and native adapters, fallbacks, write scopes, parallel limits, retries, timeouts, cancel and resume after an interruption.
- Local dashboard and API: `sentinel dashboard` serves a React dashboard and an HTTP API on 127.0.0.1 with a session token, Host, Origin and CSRF checks and server-sent events; works offline; keyboard and automated accessibility (axe) tested; manual screen-reader check pending. The dashboard UI is in the release wheel `sentinel-1.1.0-py3-none-any.whl` only; a `uv tool install git+https://…` install has the CLI without the dashboard UI (see [installation](docs/installation.md#the-dashboard-ui)).
- Registry `.sentinel/sentinel.db` (SQLite, WAL, migrations with a backup before each upgrade) and `sentinel doctor` health checks shared with the dashboard.
- Notifications, stats, audit export, backup: `sentinel notifications`, `sentinel stats` (lead time, acceptance rate, approval wait, provider failures, cost as reported), `sentinel audit export` and `verify` over a hash-chained append-only audit, and `sentinel backup` with verify and restore.
- A security suite (`tests/security/`) that asserts each threat and the residual risks, and a release gate (`tools/release_gate.py`).
- New config keys, all optional: `policies`, `providers`, `agents`, `tdd`, `verification`, `notifications`, per-repo `test_globs` and `production_globs`.
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
