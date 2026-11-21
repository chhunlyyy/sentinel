# Knowledge base (target 1.3.0)

Status: design approved by the owner on 2026-11-21. Branch `knowledge-base`.

## Goal

Every change that lands on a tracked branch of a project repo becomes team knowledge in the shared repo,
whether or not it was made through Sentinel. Knowledge updates run automatically in the background and
never block a run. v2 agents receive the relevant knowledge in their task prompts.

## Decisions (owner, 2026-11-21)

1. Publishing: the background job auto-pushes **only paths under `knowledge/`** of the shared repo, after
   `scrub --check` passes. Specs, invariants and the regression suite keep their human gate. Candidate
   invariants go to `proposals/`, never `invariants.md`.
2. Backfill: snapshot summaries of the current code plus change records for the last 3 months
   (`knowledge.backfill_months`, default 3) on every tracked branch.
3. Triggers: catch-up ingest before every Sentinel run (inside `sync pull`) plus an optional CI workflow
   template for project repos that runs on push to any tracked branch.
4. Branches are configurable per repo: some teams merge to `develop`, not `main`.

## Config

Per repo (in `repos[]`, schema `sentinel/core/schema/config.schema.json`):

```yaml
repos:
  - id: backend
    path: ./api
    knowledge:
      branches: [develop, main]   # optional; default = the repo's default branch (origin/HEAD, else current HEAD branch)
```

The first branch is the **summary branch**: snapshot summaries are built from it.

Top level:

```yaml
knowledge:
  enabled: true            # default true
  auto_push: true          # default true; push knowledge/ only
  backfill_months: 3       # default 3
  max_changes_per_ingest: 200   # safety cap per invocation; the cursor makes it resumable
  summarize: true          # default true; false = deterministic records only, no agent calls
  budget_usd: null         # optional cap for backfill summarization; stop and report when reached
```

Summarization uses routing role `knowledge` (add it to the routing schema); when not routed it falls back to
the runner routed for `coder`, else the default runner. Deterministic parts never need an agent.

## Layout in the shared repo

```
knowledge/
  README.md                                   # generated: what this folder is, provenance meanings
  cursor.json                                 # {"<repo>@<branch>": {"sha": "...", "updated_at": "..."}}
  index.json                                  # key -> record path, reached branches, provenance, files (for lookup by path)
  repos/<repo>/summary.md                     # level 0, one page per repo
  repos/<repo>/modules/<module-path>.md       # level 1, per top-level module directory
  changes/<repo>/<yyyy-mm>/<key>.md           # one file per change, append-only
  patterns/                                   # example files (curated later; created empty with README)
```

### Change record key

- `pr-<number>` when the change maps to a pull/merge request (merge commit subject "Merge pull request #N",
  "Merged PR N", Gitea "Merge pull request 'x' (#N)", squash subject ending "(#N)").
- otherwise `p-<first 12 chars of git patch-id --stable>` of the change's combined diff.
- A Sentinel v2 run's record uses key `run-<slug>` and lists the PR or patch keys it covers in `covers:`;
  ingest that later meets the same patch-id or PR updates the run record's `reached:` instead of creating a new one.

The same change merged to `develop` and later to `main` keeps **one** record: the key is the same, and
`reached:` gets a second entry.

### Change record format (Markdown with YAML front matter)

```markdown
---
key: pr-142
repo: backend
provenance: inferred          # verified (Sentinel run accepted by a human) | inferred (from git)
status: active                # active | dropped (commits no longer on any tracked branch)
reached:
  - {branch: develop, sha: 1a2b3c..., at: 2026-11-02T10:11:12Z}
  - {branch: main, sha: 9f8e7d..., at: 2026-11-20T08:00:00Z}
authors: [alias-1]            # git author names; scrubbed (no emails)
title: Add leave balance export
files: [src/main/java/.../LeaveController.java, ...]
modules: [src/main/java/hr/leave]
run: null                     # slug for verified records
spec: null                    # shared path of the spec for verified records
---

## What changed
<deterministic: PR title/body or commit messages, diffstat>

## Summary
<agent-written: behavior changed, why, risks; omitted when summarize=false or the agent failed>

## Candidate rules
<agent-written, optional; also copied to proposals/knowledge-<key>.md>
```

### Ingest algorithm (per repo, per tracked branch)

1. `git fetch` the repo's remote for tracked branches (skip quietly when offline; use local refs).
2. Resolve `origin/<branch>` (else local `<branch>`). Missing branch: warn, skip.
3. Cursor SHA missing -> start at the first commit on the branch newer than now - backfill_months.
   Cursor SHA no longer an ancestor of the branch tip (rebase/force-push) -> start from
   `git merge-base cursor tip`, and mark records whose `reached` SHAs for that branch are no longer
   reachable from any tracked branch as `status: dropped` (never delete).
4. Walk first-parent commits cursor..tip oldest first. Each first-parent commit is one change
   (a merge commit = the PR; a direct commit = itself). Compute the key, files, diffstat, messages.
5. Upsert the record; append to `reached` if the branch is new for that key.
6. Advance the cursor after each change (resumable). Stop at `max_changes_per_ingest`.
7. Run scrub on every written file before commit.

## Background harvest after a v2 run

- `AcceptOps.complete_run` (sentinel/scripts/accept.py) enqueues a `kb_harvest` job (new registry table
  `kb_jobs`: id, kind, run_slug, state queued|running|done|failed, attempts, error, created_at, updated_at)
  after the run is COMPLETED, then starts a detached worker (`sentinel kb worker`, Popen with
  start_new_session=True, stdio to a log in the state dir). It never raises into complete_run.
- The worker: takes a lock (git ref `refs/sentinel/locks/knowledge` in the shared repo, like run locks),
  pulls the shared repo, writes the verified record for the run (spec, Gherkin paths, trace summary, final
  SHAs, files), runs ingest for the run's repos, refreshes module summaries whose source tree hash changed,
  runs scrub check, commits **only `knowledge/` and `proposals/knowledge-*`** paths, integrates and pushes
  when `knowledge.auto_push` is true. Retries up to 3 times with backoff. Failure: job failed + notification.
- Dashboard: knowledge job status (last success, last failure, queued) on the overview health area.

## Snapshot summaries

- `sentinel kb snapshot [--repo id]` builds `repos/<repo>/summary.md` and `modules/*.md` from the summary
  branch tip (via `git archive`/`ls-tree`, never the working tree, so uncommitted work is excluded).
- Each module file stores `source_tree: <git tree hash of that directory>`; regenerate only when it changed.
- Deterministic header (file count, languages by extension, entry points, test dirs) + agent summary.

## Prompt injection (v2)

`Runtime._render_prompt` adds a `## Project knowledge` section, capped at ~6k chars:
repo summary, module summaries whose directory overlaps the task write scope (use scheduler overlap helpers),
`shared/invariants.md`, and the 5 newest change records touching those modules. Read-only, absolute paths.

## CLI

```
sentinel kb ingest [--repo id] [--branch b] [--no-summarize]
sentinel kb backfill [--since YYYY-MM-DD] [--yes]      # prints estimate (changes, est. agent calls) first
sentinel kb snapshot [--repo id] [--force]
sentinel kb status [--json]                            # cursors, counts, last job, stale modules
sentinel kb worker                                     # internal: process queued jobs
```

`sentinel sync pull` runs `kb ingest` (no push, summaries queued for the worker) after a successful pull
when `knowledge.enabled`.

## Phases

- A. Config + schema, `sentinel/scripts/knowledge.py` core: layout, cursor, keys, records, ingest walk,
  rebase/dropped handling, scrub, CLI `kb ingest|backfill|status` (deterministic, `--no-summarize` path). Tests.
- B. Summarizer through adapters (role `knowledge`), snapshot summaries with tree-hash staleness. Tests.
- C. `kb_jobs` table, worker, complete_run hook, knowledge lock, path-restricted auto-push. Dashboard status. Tests.
- D. `sync pull` catch-up, CI template under `sentinel/templates/ci/knowledge-ingest.yml`, prompt injection. Tests.
- E. Docs (`docs/knowledge.md`, config.md, workflow.md), CHANGELOG, version bump to 1.3.0.
