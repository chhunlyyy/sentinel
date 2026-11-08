# Beta testing guide

Version 0.1.0b0. Thank you for testing. This is an internal beta: it works end to end for one team on one stack, and most of it has not been exercised by anyone else yet. Your reports are the point of this phase.

## 1. Set up (10 minutes)

1. Install the engine: `uv tool install git+https://github.com/chhunlyyy/sentinel`, then the skills for your tool: `npx skills@latest add chhunlyyy/sentinel -a <agent>` (see the README install section).
2. Run the self-test. It builds a throwaway workspace in your temp folder and touches nothing else:

   ```bash
   sentinel selftest
   ```

   Expected last line: `<N> passed, 0 failed`. If anything fails, stop and report it (section 5) before testing further.
3. Create an empty private git repo for the team (or use a throwaway local one: `git init --bare ~/sentinel-shared.git`). Sentinel requires it and will not run a task without it.
4. In a **copy or a throwaway branch** of your project: `sentinel init` (it asks for that repo's URL), `sentinel doctor`, then `sentinel sync-adapters --tool <your tool>`.
5. Ask your agent: "Run Sentinel on: <a small task>".

## 2. What to test

Please try at least one of each and tell us how it went:

| Test | What it checks |
|---|---|
| A small bug fix (Tier 2) | repro, coder, release check, resume, finish |
| A small feature with a new endpoint or screen (Tier 3) | specifier, interview, reviewer, QA, promotion, docs; none of these has run for real yet |
| A change that touches auth, data or a migration (Tier 4) | hardener, full QA, rollout notes, retrospective; also untested |
| Your own stack | a profile other than Spring Boot and Next.js; the Flutter, Python and Node profiles have only been tried on samples |
| A tool other than Claude (Codex, Gemini, Cursor) | the adapters were built from memory of those tools and never run against the real CLIs |
| Two people on the same slug | the lock in the shared repo |
| `sentinel resume` after you quit mid-run | state recovery |
| macOS or Windows | only Linux has been tried |

## 3. Safety rules

- Work on a copy or a throwaway branch. Sentinel never commits or pushes on its own, but agents edit files in your repos.
- Do not set `unsafe_skip_permissions: true` on a machine that holds production credentials. It is off by default.
- Do not run QA against a real database. `qa.db_clone` only touches schemas ending in `_qa` or `_fresh`; read your `boot_args` before the first QA run. Prefer sanitized fixtures.
- If a dev server is running on a repo, run the release check with `--skip build` (a build overwrites the dev server's output). Pass `--repo <id>` so unrelated work in progress in other repos is not checked.
- Keep real names, government codes, emails, tokens and passwords out of specs and tests. `sentinel scrub --check` catches common shapes but cannot recognize names.
- The shared repo is private. Do not push specs or logs anywhere else.

## 4. Known gaps

- Stages not yet run for real: specifier, reviewer, hardener, QA, promotion, docs, rollout, retrospective, and the change map on a large change.
- The MySQL QA plugin has been dry-run only; the clone itself has not been run by Sentinel.
- Codex, Gemini, Cursor and `agy` flags are unverified.
- Stage isolation depends on each tool's subagent feature. Claude Code is tested; Antigravity's `invoke_subagent` and the others are not yet confirmed in a Sentinel run. Check `sentinel stats` after a run for inline stages.
- The self-test covers the mechanics (config, prompts, locks, boundary check, scrubber, release check), not the quality of what an agent writes.
- Upgrade both parts: `uv tool upgrade sentinel` and `npx skills@latest update`.
- There is no Windows support and no installer yet.

## 5. How to report a problem

Open an issue (or message the owner) with:

- Sentinel version (`sentinel --version`), your OS, the AI tool and model you used.
- What you asked for, which tier Sentinel chose, and which stage went wrong.
- What you expected and what happened. Paste the exact error text.
- The output of `sentinel doctor`.
- Run records, only after `sentinel scrub`: `.sentinel/runs/<slug>/state.json` and `metrics.json`. Do not attach QA logs, screenshots or anything from `.sentinel/cache/`.

Also welcome: anything that was confusing in the docs, any step you had to guess, and any stage prompt that produced bad output (quote the part).

## 6. What "success" looks like for this beta

- The self-test passes on every tester's machine.
- Each tester completes a Tier 2 run and, ideally, a Tier 3 run on a real task without hand-editing Sentinel files.
- No stage writes outside its repo without the runner catching it.
- Nothing sensitive reaches the shared repo.

## 7. Backing out

- Sentinel only adds `sentinel.config.yaml`, the `.sentinel/` folder, generated agent and skill files, and (for non-Claude tools) a marked block in `AGENTS.md`. Delete those to remove it.
- Remove the skills with `npx skills remove` and the engine with `uv tool uninstall sentinel`. If you used the legacy `sentinel sync-adapters`, back up your agent files first; it overwrites generated ones.
