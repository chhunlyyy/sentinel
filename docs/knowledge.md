# Knowledge base

Sentinel maintains a project knowledge base in the team's shared repository. It records what changed across tracked branches, why changes were made, and how codebase modules are structured.

Knowledge is gathered continuously. Changes made through Sentinel version 2 runs produce verified records. Changes made directly in git or through external pull requests produce inferred records. Ingest and summarization run automatically in the background and never block a run. During subsequent version 2 runs, task prompts receive the relevant module summaries, invariants, and recent change records.

## Layout in the shared repo

The knowledge base lives under the `knowledge/` directory in the shared repository (`.sentinel/shared/knowledge/` in a local clone):

```
knowledge/
  README.md                              # generated overview and provenance definitions
  cursor.json                            # branch sync cursors: {"<repo>@<branch>": {"sha": "...", "updated_at": "..."}}
  index.json                             # fast lookup index mapping keys to paths, branches, provenance, and files
  repos/<repo>/summary.md                # level 0 summary: one page per repository
  repos/<repo>/modules/<module-path>.md  # level 1 summary: per top-level module directory
  changes/<repo>/<yyyy-mm>/<key>.md      # change records, partitioned by year and month
  patterns/                              # curated reusable architecture and code patterns
```

`knowledge/README.md` and the `patterns/` directory are initialized automatically when the layout is created.

## Change records

Each landed change on a tracked branch becomes an append-only Markdown record with YAML front matter under `knowledge/changes/<repo>/<yyyy-mm>/<key>.md`.

### Record keys

Sentinel generates canonical keys based on the source of the change:

- `pr-<number>`: Used when a commit maps to a pull or merge request. Sentinel detects pull request numbers from standard merge messages (GitHub `Merge pull request #N`, Azure DevOps `Merged PR N`, Gitea `Merge pull request '...' (#N)`), or squash commit subjects ending with `(#N)`.
- `p-<patch-id>`: Used for direct commits or merge commits without a pull request number. The key uses `p-` followed by the first 12 characters of `git patch-id --stable` computed from the commit diff.
- `run-<slug>`: Used for accepted Sentinel version 2 runs. The record references the run slug and lists covered commits in `covers:`. If an ingest walk later encounters the underlying commit or PR, it updates the existing `run-<slug>` record rather than creating a duplicate.

### Provenance

The `provenance` field in the record front matter records how the record was produced:

- `verified`: Built from a completed Sentinel version 2 run that was reviewed and accepted by a human. Verified records include links to the approved specification (`spec`), Gherkin feature files (`features`), verification trace summary, and final commit SHAs.
- `inferred`: Reconstructed automatically by ingesting git history. Contains commit messages, diff statistics, touched files, and an agent-generated summary when summarization is enabled.

### Status and branch promotion

The record front matter tracks where changes have landed:

```yaml
---
key: pr-142
repo: backend
provenance: inferred
status: active
reached:
  - {branch: develop, sha: 1a2b3c4d5e6f, at: "2026-11-02T10:11:12Z"}
  - {branch: main, sha: 9f8e7d6c5b4a, at: "2026-11-20T08:00:00Z"}
authors: [alice]
title: Add leave balance export
files: [src/main/java/hr/leave/LeaveController.java]
modules: [src/main/java/hr/leave]
run: null
spec: null
---

## What changed
Add leave balance export endpoint and CSV generator (#142)

## Summary
Introduced LeaveController export route with streaming CSV generation.

## Candidate rules
- CSV exports must stream rows to prevent memory exhaustion on large datasets.
```

- **Branch promotion**: When a change lands on `develop` and is later merged into `main`, Sentinel keeps **one** record. During ingest of `main`, the existing record is matched by patch ID or PR number, and the new branch commit is appended to the `reached` list.
- **Status `active` vs `dropped`**: If a branch is rebased or force-pushed so that previously recorded commits are no longer reachable from any tracked branch, Sentinel marks those records as `status: dropped`. Records are never deleted. If a dropped change subsequently reappears on another tracked branch, its status reverts to `active`.

## Tracked branches

Tracked branches are configured per repository in `sentinel.config.yaml`:

```yaml
repos:
  - id: backend
    path: ./api
    role: backend
    profile: spring-gradle
    knowledge:
      branches: [develop, main]
```

When `branches` is omitted, Sentinel tracks the repository's default branch (`origin/HEAD`, or the current local branch).

The first branch in the `branches` list is the **summary branch**. Snapshot summaries for the repository and its modules are always generated from the tip of this branch.

## Triggers

Knowledge base updates occur via three triggers:

1. **Background harvest after an accepted run**: When a human accepts a version 2 run (`sentinel accept <slug>`), `complete_run` enqueues a harvest job in the registry `kb_jobs` table and launches a detached background worker (`sentinel kb worker`). The worker writes the verified record, ingests tracked branches, updates module summaries, verifies scrub rules, and publishes changes. Completing a run never blocks on knowledge harvesting.
2. **Catch-up on sync pull**: Before starting work, running `sentinel sync pull` fetches the shared repository and executes `sentinel kb ingest` to bring local knowledge up to date with any changes pushed by teammates or CI.
3. **Continuous Integration**: The template `sentinel/templates/ci/knowledge-ingest.yml` can be installed in project repositories to run on push to tracked branches. CI ingests new commits and publishes updated knowledge using repository secrets `SENTINEL_SHARED_REPO_URL` and `SENTINEL_SHARED_TOKEN`.

## Publishing and safety

When `knowledge.auto_push` is enabled (the default), the background worker commits and pushes knowledge updates automatically.

Publishing enforces strict safety controls:

- **Path restrictions**: The worker stages and commits **only** paths under `knowledge/` and proposal files matching `proposals/knowledge-*`.
- **Scrub gate**: Every file to be published must pass `sentinel scrub --check`. If any secret, token, private credential, or forbidden pattern is detected, the publish aborts immediately as a permanent failure, changes are discarded from the working copy, and a notification is raised.
- **Isolation from human gates**: The worker never pushes other unpushed commits in the shared repository. If uncommitted or unpushed files exist outside `knowledge/` (such as specifications, test suites, or invariants), the worker leaves them in place and reports `committed locally (other unpushed changes wait for sentinel sync push)`. Specifications and regression tests retain their required human approval gate.
- **Locking**: The worker acquires a shared git lock ref (`refs/sentinel/locks/knowledge`) before updating files, preventing concurrent worker collisions.

## Backfill and cost estimation

When initializing the knowledge base on an existing project, `sentinel kb backfill` imports past commit history up to `knowledge.backfill_months` (default 3 months).

Before processing commits, backfill prints an estimate of the number of changes and estimated summarizer calls, prompting for confirmation:

```bash
sentinel kb backfill
```

Options:
- `--since YYYY-MM-DD`: Backfill commits starting from a specific date instead of the default months window.
- `--yes`: Proceed with backfill without interactive confirmation.

To protect against unexpected LLM API costs during a large backfill, configure `knowledge.budget_usd`. When the estimated or reported cost reaches the cap, summarization stops and reports the limit reached, leaving remaining records deterministic.

## Module and repository summaries

Sentinel maintains hierarchical summaries to give agents immediate context without reading entire codebases:

- **Level 0 (`repos/<repo>/summary.md`)**: High-level overview of the repository, key directories, technologies, and architecture.
- **Level 1 (`repos/<repo>/modules/<module-path>.md`)**: Detailed breakdown of each top-level module, its responsibilities, dependencies, and key interfaces.

Summaries are generated from the tip of the configured summary branch using `git archive` and `ls-tree`, ensuring uncommitted working tree modifications are never included.

Each module summary file records the git tree hash of its directory in front matter (`source_tree: <hash>`). When running summaries, Sentinel checks tree hashes and regenerates only modules whose source trees have changed.

Run snapshot generation manually:

```bash
sentinel kb snapshot
```

Options for `sentinel kb snapshot`:
- `--repo <id>`: Limit snapshot summary generation to a single repository.
- `--force`: Force regeneration of all summaries regardless of tree-hash matching.

### Summarizer routing

Summaries are produced by AI agents routed through the `knowledge` role. Configure the runner and model under `agents` in `sentinel.config.yaml`:

```yaml
agents:
  knowledge:
    runner: claude
    model: sonnet
```

Routing fallbacks:
1. Role `knowledge` in `agents`.
2. Fallback to the runner configured for `coder`.
3. Fallback to the default system runner.

To disable agent summarization entirely (generating deterministic diffstat records only):
- Set `knowledge.summarize: false` in `sentinel.config.yaml`.
- Set environment variable `SENTINEL_KB_NO_AGENT=1` for the command or process.
- Pass `--no-summarize` to `sentinel kb ingest`.

## How agents receive knowledge

During Sentinel version 2 runs, `Runtime._render_prompt` automatically injects a `## Project knowledge` section into task prompts for coder, specifier, and reviewer roles.

The section is capped at approximately 6,000 characters and contains:
1. The repository summary (`repos/<repo>/summary.md`).
2. Module summaries (`repos/<repo>/modules/...`) whose directories overlap with the task write scope.
3. Relevant project rules and candidate proposals from `proposals/knowledge-*`.
4. Up to 5 newest change records touching the affected modules.

Files are referenced by absolute read-only paths so agents can inspect full details if needed.

## CLI commands

The `sentinel kb` CLI provides management commands:

- `sentinel kb ingest`: Ingests new commits from tracked branches into change records. Options: `--repo <id>`, `--branch <branch>`, `--no-summarize`, and with `--publish` (when publishing to the remote shared repository).
- `sentinel kb backfill`: Scans historical commits over the backfill window, displays cost and change estimates, and populates change records upon confirmation.
- `sentinel kb snapshot`: Generates or refreshes repository and module snapshot summaries. Options: `--repo <id>` and `--force`.
- `sentinel kb status`: Displays knowledge base health, tracked cursors, record counts (active and dropped), and background worker job state. Add `--json` for machine-readable output.
- `sentinel kb worker`: Internal worker command that processes queued harvest jobs in the registry.

## Privacy and security

The knowledge base follows strict privacy and data hygiene boundaries:

- **Author privacy**: Sentinel records author names only. Email addresses are stripped from commit metadata using regex filtering before records are created.
- **Scrubber integration**: Every record and proposal file passes through Sentinel's configured text scrubber before write and before commit. Secrets, credentials, private tokens, and internal server paths are scrubbed.
- **Model provider exposure**: Agent summarization sends code diffs and commit messages to the configured provider for role `knowledge`. If your project handles sensitive code that cannot be sent to an external model, set `knowledge.summarize: false` or `SENTINEL_KB_NO_AGENT=1` to keep all knowledge base records purely deterministic.

## Troubleshooting

### Inspecting status

Check cursors and background jobs:

```bash
sentinel kb status
```

To view raw JSON data:

```bash
sentinel kb status --json
```

### Worker logs

The background harvest worker writes logs to:

```
.sentinel/kb-worker.log
```

The worker uses a PID lock file at `.sentinel/kb-worker.lock` to ensure only one worker runs per workspace. If a worker process terminates unexpectedly, subsequent invocations check process liveness and automatically clear stale locks.

### Failed harvest jobs

When a background job encounters an error:
1. The worker retries transient failures up to 3 times with exponential backoff (5 seconds, then 30 seconds).
2. If retries are exhausted or a permanent failure occurs (such as a failed scrub check), the job is marked `failed` in the database.
3. Sentinel records a `knowledge.failed` event in the run registry and displays a warning notification in the dashboard and CLI.
4. Check `.sentinel/kb-worker.log` for the specific error trace.
5. Once resolved, re-run `sentinel kb ingest` with `--publish`.
