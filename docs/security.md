# Security notes

Sentinel runs AI agents with write access to your repos, starts your services, and can copy databases. Read this before using it on real systems.

## QA and real data

- The QA stage runs your system against throwaway data. With `qa.fixtures: clone` and `qa.db_clone`, that data is a copy of a real database. A copy of production-like data has the same sensitivity as the original: personal data, password hashes, and tokens end up in QA logs, screenshots, traces, and uploaded files.
- Prefer `qa.fixtures: sanitized`: seed data built for testing, with no real people in it.
- If you must clone, clone from a staging database that already holds masked data, never from production.
- The MySQL plugin only touches schemas ending in `_qa` or `_fresh` (configurable) and never a configured source. Review `boot_args` before the first run to be sure the QA service points at the copies and not at the real schemas.
- QA stops and asks for confirmation before cloning real data (human gate, tiers 3 and 4). Do not remove that step.
- Run `sentinel clean --db` to drop the throwaway schemas when you are done.

## What is shared and what is not

| Content | Where | Shared? |
|---|---|---|
| Specs, invariants, regression tests | shared repo | yes, merged straight into its main branch |
| Run records (briefs, decisions, results, change map) | `.sentinel/runs/` | no (git-ignored) |
| Logs, QA output, uploads, node_modules | `.sentinel/cache/` | no (git-ignored) |
| Generated prompts | `.sentinel/generated/` | no (git-ignored) |

Specs and invariants describe how your internal systems work. Keep the shared repo private and limit access to the team.

The change map (`change-map.html`) embeds source code diffs. Keep it on your machine; do not publish it as a web page or attach it to public tickets.

## The scrubber is a safety net, not a guarantee

`sentinel scrub` and `scrub --check` remove or detect:

- JWTs, bearer tokens, private keys, AWS access keys
- credentials inside URLs
- values assigned to names like `password`, `secret`, `api_key`, `token` (6 characters or more)
- values of secret-looking keys (names containing pass, secret, token, key, credential, private, auth, salt, or dsn) in the workspace's `.env` files, except example files (`.env.example` and similar) and values that are plain lowercase words
- email addresses (except `example.com`, `example.org`, `example.net`, `localhost`, GitHub noreply)
- your workspace path and home directories

It does not find secrets that have no recognizable shape, names, phone numbers, national ids, or free text in any language that identifies a person. It also skips files over 20 MB and binary files (screenshots, traces, database dumps). Treat those as sensitive by default. Install `gitleaks` to add a second detector to the release check.

`sentinel sync push` refuses to push when the scrub check fails, but a clean check does not prove the files are safe to share.

## Agent permissions

- Skills run with your agent's full permissions. Installing Sentinel's skills lets the agent run `sentinel` commands, git commands in the shared repo, and your project's build and test commands. They are plain markdown in `skills/`; read them before installing, and pin a release tag (`npx skills@latest add chhunlyyy/sentinel@v2.1.1 --skill '*' -a <agent>`) so an update cannot change them without you noticing.

- Agents can run shell commands in your repos. Stages that do not need to write source (reviewer, rollout, retrospective) are told not to, and the runner checks afterwards that no repo changed.
- The runner's boundary check detects, after the fact, writes outside the stage's repo, commits, branch changes, and edits to the Sentinel config. It does not prevent them and does not undo them. It does not watch the workspace root or files outside the repos.
- Some tools can skip their own permission prompts (`unsafe_skip_permissions`). It is off by default. Turn it on per runner only for unattended runs inside a disposable environment (a container or a throwaway checkout), never on a machine that holds production credentials.
- Sentinel never commits or pushes by itself. Version 2 runs never push by themselves, whatever the config says: publishing is a separate, explicit `sentinel sync push`, and the agent that drives a run is told never to commit or push. For 0.1 runs, `sync push` needs `--yes` or `--auto`, merges into the shared repo's main branch and never force-pushes. `--auto` works only when `state.auto_sync_push: true` is set in the config; a config that does not set it means off (it meant on in 0.1), so nothing is published without you asking. With it on, a passing 0.1 run's specs and regression tests are published without asking, with no pull request and no human review; only the scrub check gates it, and it is a safety net, not a guarantee. Merge conflicts are resolved by the agent. Restrict who can write to the shared repo. Stages are told not to commit when `agents_never_run_git` is on; the boundary check reports it when they do anyway.

## Trust boundaries

- **The config is code.** Build, test, lint, QA start and extra check commands in `sentinel.config.yaml` run in a shell. Read the config of any repository before you run Sentinel in it, as you would a Makefile or `package.json` scripts.
- **The shared repo is code.** QA executes the regression tests from it, and runs merge into its main branch without review. Anyone with write access can run code on every teammate's machine. Keep it private, limit write access, and protect its main branch from force-pushes and deletion.
- **Slugs are validated.** Run names are restricted to lowercase letters, digits, dots, dashes and underscores, so they cannot escape the runs folder or inject into git refs.

## Residual risks

Sentinel 1.1.0 is a local tool for one user. These risks are known, are not removed, and each has a check in the security suite (`tests/security/`) that asserts the outcome described here, so a silent change in either direction fails the build.

- **Accessibility has no manual screen-reader pass.** The dashboard is checked with automated axe-core runs over every screen, the header and More menu, the factory floor and its dialogs, plus keyboard and label tests. A manual screen-reader pass has not been done, and automated checks find only part of the problems.

- **R1: an agent that runs as the same OS user as you can approve.** It can drive a pseudo-terminal and run `sentinel approve`, or read `server.json` in your Sentinel config folder, exchange the token and use the dashboard routes. The deny rules in the agent configs that `sentinel sync-adapters` writes are advisory: other spellings of a command pass a pattern. They cover `--dir X` and `--dir=X` in front of a human-only command; an abbreviation such as `--di X` cannot be covered by a pattern, and the terminal check of each command is the real guard. The controls are the terminal check, the typed hash prefix, and the recorded channel and identity of every approval and acceptance in the audit, which show afterwards how a decision was made. Strong separation needs another OS user or a sandbox, which 1.1.0 does not provide. Run agents under a separate OS user, or inside a container, when you need that boundary.
- **QA scripts run with your environment (TDD-09).** With `rules.no_permanent_frontend_tests` on, the engine runs the QA scripts an agent wrote through `qa.scenario_run`, as your OS user. The environment is the one of a test run: `SENTINEL_DASHBOARD_TOKEN` and the variables in `policies.redact_env` are removed and `SENTINEL_TASK_ID` is not set, and the output is capped at 5 MB and scrubbed before it is stored. Everything else in your environment is visible to the script, so this is the same residual as running agent-written tests (R1, R3): a script can read what you can read. The report is written by the script itself, so the Red and Green evidence is honest only in the sense that the agent did not state the result; a script that writes the report it wants is not stopped. Sentinel hashes the scripts and the runner files named in `qa.scenario_run` (those inside the workspace) when Red is accepted and checks them again at Green, Refactor, acceptance and in the report. The scenario text in the `qa_red` prompt comes from the approved Gherkin and is a prompt-injection surface for the agent (residual): a scenario that says "ignore your scope" is still only text, and the write scope, the scope check afterwards and the engine's own run are the controls.
- **R3: a provider CLI can run any command during a task.** Sentinel cannot stop a provider CLI from running a command while a task runs. It detects file and git effects afterwards (a write outside the write scope, a commit) and fails the task, and it does not undo them.
- **The scrubber is a safety net, not a guarantee.** It removes what has a recognizable shape. Backups and the registry hold unscrubbed request text, specifications and agent output, so treat `.sentinel/sentinel.db`, its backups and `user.db` as sensitive as the repositories themselves; only exports, logs and reports the API serves are scrubbed.
- **The audit hash chain detects edits by other tools, not a same-user attacker.** A process running as you can drop the triggers and rewrite every row, and then it rewrites the whole chain and `sentinel audit verify` passes. Keep an exported copy somewhere the agent user cannot write when you need proof against that.

### Threats and the checks that guard them

| Threat | Status |
|---|---|
| wrong Host (DNS rebinding) | blocked, checked on every request |
| wrong Origin | blocked |
| missing session cookie | blocked |
| missing or wrong CSRF value | blocked |
| token left in the URL after /auth | blocked: `/auth` redirects and a cookie replaces the token |
| path traversal in artifact, log and static routes | blocked |
| path traversal in notification and backup arguments | blocked |
| oversized body | blocked |
| non-TTY approval and acceptance | blocked |
| stale-hash approval | blocked |
| agent environment holds the token or secrets | blocked: the task environment is stripped |
| secrets in logs, evidence, reports and bundles | scrubbed (a safety net) |
| secrets in prompts and task files | blocked |
| untrusted content rendered as HTML (XSS) | blocked: content is rendered as text and links in it are not followed |
| approval forgery by a same-user agent (R1) | residual, see above |
| commands run by a provider during a task (R3) | residual, see above |

The dashboard has no clone-URL or directory-picker route in 1.1.0, so those two threats do not apply.

### Dashboard token and residual risk R1

`sentinel dashboard` starts the Sentinel background service on 127.0.0.1 and prints a one-time URL that holds a start token. The same
token is written to `server.json` in your Sentinel config folder (mode 0600, folder mode 0700). A coding agent that
runs as your own user can read that file, take the token and open its own dashboard session, so it could call the
dashboard approval routes. This is residual risk R1. Sentinel does not remove it. The deny rules that
`sentinel sync-adapters` writes (for `server.json`, the config folder and the `approve`, `accept` and `dashboard`
commands) are advisory: other spellings of a command can pass a pattern. The `dashboard` command itself runs only on
a terminal (TTY). Run agents under a separate OS user if you need a hard boundary. The browser is opened on a private redirect file
(mode 0600) so the token never appears in the browser's command line.

Sentinel 2.0 maintains this security model across its background service and new routes:
- **Loopback and session token**: The background service binds to 127.0.0.1 only. Every read and write route requires the session cookie or token, validates Host and Origin headers on every request to prevent DNS rebinding and cross-site requests, and enforces CSRF checks on all mutating methods (`POST`, `PUT`, `DELETE`).
- **Approvals still need the typed hash**: Approving a specification or Gherkin set in the dashboard (`POST /api/v1/projects/{pid}/runs/{slug}/approvals`) or in `sentinel approve` requires matching the first 8 characters of the document's SHA-256 hash. Creating a task or reading a notification never approves anything.
- **Shared repo URL validation**: The setup probe route `POST /api/v1/shared/test` tests remote read and write access. It strictly accepts only git URLs (`https://`, `ssh://`, `git://`, `file://`, `git@host:...`) or valid local paths, explicitly rejects strings starting with `-`, and passes `--` before arguments to git subprocess calls. This prevents command option injection such as `--upload-pack=<command>` or `--config` from executing arbitrary code during the probe.
- **Config form protections**: The configuration save route `POST /api/v1/projects/{pid}/config/save` validates changes against `config.schema.json`, writes audit entries, and explicitly refuses modifications to `state.shared_repo` or repository `path` fields, preventing repo redirection or shared repo hijacking through the form.
- **New 2.0 routes**: Setup (`/detect`, `/shared/test`, `/routing/suggest`), config (`/config/form`, `/config/preview`, `/config/save`), knowledge (`/knowledge/status`, `/records`, `/records/{key}`, `/ingest`, `/snapshot`, `/backfill/estimate`, `/backfill`, `/ci-template`), factory snapshot (`/projects/{pid}/factory`), and task controls (`/tasks/{slug}/pause`, `/unpause`, `/note`) all follow these boundaries. Output from runs and knowledge records is scrubbed.

The Docker image changes only where the server listens. Inside the container `sentinel dashboard --bind 0.0.0.0` is accepted only when the image sets `SENTINEL_CONTAINER=1` and the process runs in a container (`/.dockerenv` or `/run/.containerenv`); on a host it is refused with exit code 2, and the environment variable alone changes nothing. A server bound to `0.0.0.0` closes every connection from a peer that is not loopback or the container's default gateway with 403 before it reads the request (`--allow-peer IP` adds an address, for rootless Docker or Docker Desktop). Host and Origin accept only `localhost:PORT` and `127.0.0.1:PORT` (`--public-host`; outside a container its port must be the server's own port). Publish the port as `127.0.0.1:8765:8765` only; the image has no `EXPOSE`, so `-P` publishes nothing. The token, session cookie and CSRF rules are unchanged, and R1 applies to a process that can read the container's config volume. See [the dashboard guide](dashboard.md#docker).

R1 has two known cases, and the security suite (`tests/security/`) asserts both so that a silent change in either
direction fails the build:

- **Pseudo-terminal.** An agent running as your user can open a pseudo-terminal (Python `pty`), start
  `sentinel approve` in it, read the printed hash and type the prefix. The approval then succeeds with channel `tty` and
  your OS user as the approver. The terminal check stops a pipe, not a program that creates a terminal.
- **Token file.** An agent running as your user can read `server.json`, exchange the token at `/auth` and call the
  approval routes. The approval is recorded with channel `dashboard`.

Both are visible afterwards in the audit (channel and identity), not prevented. Only a separate OS user or a sandbox
closes them.

### Residual risk R3: provider commands during a task

Sentinel cannot stop a provider CLI from running a command while a task runs. It detects file and git effects
afterwards: a write outside the task's write scope or a `git commit` fails the task with `E_SCOPE` and parks the run
for a human. It does not undo them. Review the diff of a failed task before you continue.

## Audit log and backups

- The audit table is append-only: SQLite triggers refuse `UPDATE` and `DELETE`, and every row carries `row_sha` and
  `chain_sha`, a hash chain written in the same transaction as the row. `sentinel audit verify` checks the chain,
  checks that each trigger still has the exact text Sentinel wrote (a trigger of the same name that does nothing is
  reported), and names the first broken row. Every audit field except the id is text or null; anything else is refused
  when the row is written and when a bundle is imported, because SQLite would store it differently from the text that was
  hashed.
- **Exports.** `sentinel audit verify --file export.jsonl` checks the file against itself: each row's hashes, the link
  between neighbours, and, when the export had no filters, that it holds rows 1 to N with none missing. A row the
  scrubber changed cannot be hashed again, so it is checked for its chain link only; it must show a scrubbed value
  (`[REDACTED...]`, `$WORKSPACE` or `$HOME`), and the answer counts these rows. Add `--db sentinel.db` to compare every row
  of the file with the registry's row of the same id.
- **Imported rows.** The audit rows of an imported run bundle are written when you import it, on the channel `import`,
  by the importing user. Who did it and when (and the original reason) stay as data in the row's `reason`
  (`imported_from` is the bundle's sha256). Exports show them as `"imported": true`, and verify counts them.
- **Limit.** The chain and the triggers detect a changed, deleted or inserted row. They do not stop a process that runs
  as your OS user: it can drop the triggers and rewrite every row and the whole chain, and verify will then pass. This is
  the same boundary as R1. Keep an exported copy (`sentinel audit export --out file`) somewhere the agent user cannot
  write if you need proof against that. A deleted last row leaves a chain that still verifies: it is found only by
  comparing against an earlier export or an earlier head (`verify --file earlier.jsonl --db sentinel.db` finds rows
  that disappeared or changed since that export).
- `sentinel audit export`, `sentinel backup` and `sentinel backup restore` are for humans. They are refused inside a
  task process (`E_ACTOR`) and denied in the configs that `sync-adapters` writes; each refusal is written to the audit
  as `audit_export_refused`, `backup_refused` or `restore_refused`. The task-process check reads the
  `SENTINEL_TASK_ID` variable, so a process that runs as your OS user and clears it is not stopped (R1 again; the
  terminal and the typed hash are the real gate for `restore`).
- `restore` needs a terminal and the typed first 8 characters of the backup's hash, because it replaces the registry.
  `--yes` is accepted for scripts and ignored: it never skips that prompt. The copy is read once into a private temp file
  that is hashed and checked (against the typed hash, its `.sha256` file and its audit chain) before anything changes.
  A copy with no registry id or no `.sha256` file cannot be tied to this workspace: `restore` warns and asks for a
  second confirmation. It refuses while a task runs or a Sentinel server holds the lock. The data goes into the live
  registry with the SQLite backup API, so a connection that is open does not lose later writes. Before that, the
  current registry is copied to `backups/pre-restore-<time>.db`, even when its audit chain is broken (the copy and the
  `restore` audit row then say `chain_ok: false`), so a damaged registry can still be replaced. `sentinel backup --force`
  keeps a copy of a registry whose chain is broken the same way.
- The audit export is scrubbed with the same rules as task logs (the `.env` values of the workspace and its repo
  roots, `policies.redact_env`, the dashboard token, and the pattern list); rows changed by the scrubber are marked
  `"scrubbed": true`. A backup is a copy of the registry, so it is as sensitive as the registry (mode 0600 from the
  moment it is created, inside the git-ignored `.sentinel` folder). Old backups are never deleted for you.
- Task logs are scrubbed before they leave the server, line by line (a line is cut at 8192 characters), and again on disk
  when the task ends. A private key that starts before the first line of a live tail is not recognised in that tail.

## Dependencies

The release check prints a notice when a dependency manifest changes. A human must approve each new dependency: check the package, its maintainers, and its license. The reviewer stage is also told to look at new dependencies.

## Locks

Run locks are git refs on the shared remote (`refs/sentinel/locks/<slug>`). A crashed run leaves its lock behind. Delete it with `git push origin :refs/sentinel/locks/<slug>` from `.sentinel/shared`. Anyone with push access to the shared repo can take or delete locks.

## Before you publish your own copy of Sentinel

- Run a secret scan over the whole repository and its history (`gitleaks detect`) and fix anything it finds.
- Search for your organization's names, internal hostnames, and absolute paths.
- Do not copy project-specific specs, invariants, QA logs, or fixtures into the package. They belong in your team's shared repo.
- Choose and add a license. Sentinel does not ship one by default.
