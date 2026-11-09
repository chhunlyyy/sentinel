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

- Skills run with your agent's full permissions. Installing Sentinel's skills lets the agent run `sentinel` commands, git commands in the shared repo, and your project's build and test commands. They are plain markdown in `skills/`; read them before installing, and pin a release tag (`npx skills@latest add chhunlyyy/sentinel@v0.1.0b6 --skill '*' -a <agent>`) so an update cannot change them without you noticing.

- Agents can run shell commands in your repos. Stages that do not need to write source (reviewer, rollout, retrospective) are told not to, and the runner checks afterwards that no repo changed.
- The runner's boundary check detects, after the fact, writes outside the stage's repo, commits, branch changes, and edits to the Sentinel config. It does not prevent them and does not undo them. It does not watch the workspace root or files outside the repos.
- Some tools can skip their own permission prompts (`unsafe_skip_permissions`). It is off by default. Turn it on per runner only for unattended runs inside a disposable environment (a container or a throwaway checkout), never on a machine that holds production credentials.
- Sentinel never commits or pushes by itself. `sync push` needs `--yes` or `--auto`, merges into the shared repo's main branch and never force-pushes. With `state.auto_sync_push: true` (the default) `/sentinel` publishes a passing run's specs and regression tests there without asking, with no pull request and no human review. Only the scrub check gates it, and it is a safety net, not a guarantee. Merge conflicts are resolved by the agent. Set `auto_sync_push` to `false` to approve every push yourself, and restrict who can write to the shared repo. Stages are told not to commit when `agents_never_run_git` is on; the boundary check reports it when they do anyway.

## Dependencies

The release check prints a notice when a dependency manifest changes. A human must approve each new dependency: check the package, its maintainers, and its license. The reviewer stage is also told to look at new dependencies.

## Locks

Run locks are git refs on the shared remote (`refs/sentinel/locks/<slug>`). A crashed run leaves its lock behind. Delete it with `git push origin :refs/sentinel/locks/<slug>` from `.sentinel/shared`. Anyone with push access to the shared repo can take or delete locks.

## Before you publish your own copy of Sentinel

- Run a secret scan over the whole repository and its history (`gitleaks detect`) and fix anything it finds.
- Search for your organization's names, internal hostnames, and absolute paths.
- Do not copy project-specific specs, invariants, QA logs, or fixtures into the package. They belong in your team's shared repo.
- Choose and add a license. Sentinel does not ship one by default.
