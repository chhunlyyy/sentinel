# Workflow, step by step

This is what happens, in order, when you ask your agent to run Sentinel on a task. Steps marked with a tier only run at that tier or above (see the table at the end of this section).

## Once per team and project

1. **Install** the `sentinel` command (`uv tool install git+https://github.com/chhunlyyy/sentinel`).
2. **Create the team's shared repo**: an empty private git repository. It holds the project's invariants, specs and regression suite, so every teammate sees the same ones.
3. **`sentinel init`** in your workspace. It asks for the shared repo URL (required), the project shape and each repo's stack, then writes `sentinel.config.yaml`, clones the shared repo into `.sentinel/shared/`, and fills an empty one with starter files (committed locally; you publish them once).
4. **`sentinel doctor`** checks the config, the tools it needs, and that the shared repo is cloned.
5. **`npx skills@latest add chhunlyyy/sentinel -a <agent>`** installs the Sentinel skills (`/sentinel` and the others) into your AI tool.

Stages run inside whatever tool you work in, each in its own clean context. For each stage the orchestrator runs `sentinel stage render --stage <name>`, which prints that stage's full instructions for this project (your rules, the repo's commands, the team's guidelines, the paths to read and write), then runs it by the first of these your tool offers: a subagent (Claude Code's Agent tool, Antigravity's `invoke_subagent` with the built-in `self` subagent, or the tool's own equivalent); a fresh headless session of the same tool through `sentinel stage run`; and only if neither exists, inline in its own conversation, which it must announce, and which it may not do for the reviewer or for QA. It records how each stage ran (`subagent`, `headless` or `inline`), `sentinel stats` counts them, and the orchestrator checks every result itself before moving on.

## Every run

**1. Setup check.** The orchestrator (your agent, following the `sentinel` skill) runs `sentinel doctor`. If the shared repo is missing it stops and asks you for the URL, then runs `sentinel shared set <url>`. Nothing else starts until this passes.

**2. Triage.** The orchestrator reads your request, scans the code it touches, and picks a tier from seven factors: repos touched, files likely changed, schema change, authorization change, security surface, regression risk, and business-logic complexity. One high-risk factor raises the whole run. You can say "light" (one tier lower, never below 1) or "full" (forces tier 4). It prints one line with the tier, the reason and a rough cost, then starts.

**3. Interview (tier 3 and 4).** The orchestrator asks every question that does not depend on another unanswered one in a single round, each with its recommended answer. It looks up facts itself and only asks you for decisions. When you confirm, it writes `decisions.md` in the run folder: the request in one paragraph, then `D1`, `D2`, ... with the reason for each. That file, not the chat, is the record every later stage reads. You can say "skip the interview"; the orchestrator then lists the decisions it is assuming and waits for you to confirm.

**4. Pre-flight (tier 2 and up).** `sentinel sync pull` fetches the latest shared repo. The orchestrator records each repo's current commit and checks the baseline is healthy (build, lint, typecheck). A broken baseline is reported to you and fixed as its own task, never folded into the feature. `sentinel run new <slug> --tier N` creates `.sentinel/runs/<slug>/state.json` and takes a lock on the slug as a git ref in the shared repo, so a teammate cannot start the same slug. The skill tells the orchestrator to work on a branch or worktree per repo; Sentinel does not create one for you.

**5. Repro (tier 2 and up, bug fixes only).** The repro agent shows the bug before anyone fixes it: a failing test, or, in repos that keep no permanent tests, a throwaway script or exact steps with the failing output. It confirms the failure is the reported one, writes `<repo>-repro-result.md`, and changes no production code. The orchestrator re-runs the failure itself.

**6. Specifier (tier 3 and 4).** One increment-sized spec in `specs/<slug>.md`: Gherkin scenarios (happy path plus permissions, invalid input, empty state, failure state, multi-step approval chains, and a scenario per invariant the change touches), a numbered QA procedure a human could follow, an API contract note written as intent, the invariants in scope, and an estimate of size and risk. The orchestrator checks those sections exist before going on. If the request is too big for one increment, it shows you the proposed slicing instead of picking one.

**7. Re-triage gate (tier 3 and 4).** The orchestrator reads the spec's estimate and raises the tier if the task turned out bigger. It never lowers a tier once work has started.

**8. Coder, one per repo.** Each coder works only inside its own repo and reads the shared invariants and guidelines. Order follows the project shape: a single repo just runs; with backend and frontend, the backend runs first. Then comes the **sync checkpoint**: the orchestrator asks the finished coder what it actually built (exact routes, fields, status codes) and hands that, not the spec's intent, to the next coder. With a mobile repo, frontend and mobile then run in parallel against the same contract. Each coder writes `<repo>-coder-result.md`: files changed, commands run and results, new dependencies, rollout needs. When fixing a review or QA finding, a coder first adds a test that reproduces it.

**9. Cleaner (tier 3 and 4).** Refactors the changed code for readability and complexity without changing behavior; the tests must stay green.

**10. Hardener (tier 4).** Runs mutation testing on the changed code (for example PIT or Stryker): small deliberate breaks of the logic that the tests should catch. For every mutant that survives it writes or strengthens a test. In client repos that keep no permanent tests, the tooling it added is removed afterwards.

**11. Reviewer (tier 3 and 4).** Read-only. It checks the diff against the spec and the decisions, the invariants, security (who may call it, access to another user's or department's data, validation of every client field, leaks in responses and logs), correctness (null and boundary inputs, transactions, concurrent requests, state transitions), regression risk, and new dependencies. Findings are `blocker`, `major` or `minor`, each with file and line and a failing scenario. Blockers and majors go back to the owning repo's coder, then the hardener (tier 4), then the reviewer re-checks only those findings. The limit is `limits.review_rounds` (default 2). The output ends with the list of existing features QA should re-test.

**12. QA (tier 3 targeted, tier 4 full).** Before anything is copied, you confirm that QA may clone data. Then it prepares throwaway databases (`sentinel qa-data prepare`), starts each service on the QA ports, and turns every step of the spec's QA procedure into an automated check, logging in as each role the spec names. Tier 3 runs the increment's procedure and the reviewer's regression-risk list. Tier 4 adds authorization probes (calling the API as the denied user, since a hidden button proves nothing), the migrate-from-zero check when the schema changes, and the whole regression suite. A test that fails and then passes on rerun is reported as flaky, not counted as a pass or a blocker. Every failure is triaged: `code-bug` (names the repo) goes to that repo's coder, `spec-gap` goes to the specifier (a product decision comes to you), `test-bug` is QA's own mistake and is fixed quietly. The limit is `limits.qa_rounds` (default 3).

**13. Regression promotion (tier 3 and 4).** Once QA passes, the passing checks become independent files in the shared regression suite, with paths, logins and passwords replaced by config and aliases. The spec is registered with `sentinel spec set`, and the promoted files are run once from the shared folder. Nothing is pushed yet.

**14. Release check (tier 2 and up).** `sentinel release-check` looks at every added line (debug output, TODO and FIXME, secrets, new code comments when that rule is on, leftover test tooling in client repos, plus any `extra_checks` your project defines), then runs each repo's build, lint, typecheck and tests, and scans the shared folder for secrets. Use `--repo <id>` for the repos this run touched and `--skip build` while a dev server is running. Each failure goes to the owning repo's coder; the limit is `limits.release_check_rounds` (default 3).

**15. Change map (tier 2 and up).** The `sentinel-change-map` skill builds an HTML page of every changed file laid out along the request flow, with what each file does and its key diff lines, so you can review before committing.

**16. Docs and PR draft (tier 3 and 4; tier 2 only the changelog line).** Updates docs the change made wrong, adds a CHANGELOG entry where the repo keeps one, and writes the PR title and body to `pr-draft.md`.

**17. Rollout notes (tier 4).** Everything a deploy must change, in order: environment variables and config, feature flags, migrations and whether they can be reversed, which repo deploys first, compatibility between old and new versions, and manual steps. Written to `rollout-notes.md`.

**18. Retrospective (tier 4).** Proposes new project-wide rules when this run exposed a defect that could recur. It writes `proposed-invariants.md` and never edits `invariants.md` directly; the proposals go to the shared repo for the team to review.

**19. Scrub and sync.** `sentinel scrub` removes tokens, emails, credentials and machine paths from the run records, and `sentinel scrub --check` must pass. With `state.auto_sync_push` on (the default) `sentinel sync push <slug> --auto` runs by itself; with it off you approve first and it runs with `--yes`. It pushes a `sentinel/<slug>` branch to the shared repo with the new specs, regression tests and proposed invariants for pull-request review. It never force-pushes and refuses if the scrub check fails.

**20. Finish.** `sentinel run finish <slug>` closes the run and releases the lock. Metrics (tokens and time per stage, rounds used, estimated versus final tier) are in `metrics.json`, and `sentinel stats` adds them up. The orchestrator gives you a final report: what was built, what each stage found and fixed, QA and regression results, the release-check result, open minor findings, and the paths to the change map, PR draft and rollout notes.

## When something goes wrong

- **At a cap or with an open blocker, failing QA step, regression, or failed release check,** the run stops and says plainly that the increment is not production-ready, and why. It still runs the release check so nothing is left half-done.
- **A reviewer blocker in tier 2 or 3** raises the tier automatically.
- **A usage limit or a closed session:** `sentinel resume <slug>` prints the next stage, the session ids, the rounds used and which loops hit their cap.
- **A stage that wrote outside its repo, or committed:** when the stage is run through `sentinel stage run`, the runner snapshots every repo before and after, reports it with exit code 3, and reverts nothing; you see the listed files and decide. Stages run as your agent's own subagents do not get this check, so the orchestrator reviews their diffs itself.
- **No stage's own report is taken on trust.** The orchestrator re-runs the key check itself: the failing repro, the tests, a failing QA step.

## Which tier runs which step

| Step | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---|---|---|---|
| Setup check, triage | yes | yes | yes | yes |
| Interview | | | yes | yes |
| Pre-flight, run state and lock | | yes | yes | yes |
| Repro (bug fixes) | | yes | yes | yes |
| Specifier, re-triage gate | | | yes | yes |
| Coder | yes | yes | yes | yes |
| Cleaner | | | yes | yes |
| Hardener | | | | yes |
| Reviewer | | | yes | yes |
| QA | | | targeted | full |
| Regression promotion | | | yes | yes |
| Release check | | yes | yes | yes |
| Change map | | yes | yes | yes |
| Docs and PR draft | | changelog line | yes | yes |
| Rollout notes, retrospective | | | | yes |
| Scrub, sync, finish, metrics | | yes | yes | yes |

## Where things are stored

| What | Where | Shared? |
|---|---|---|
| Invariants, guidelines, specs, regression suite | `.sentinel/shared/` (a clone of the team's shared repo) | yes, by pull request |
| Decisions, briefs, stage results, change map, PR draft, rollout notes, metrics | `.sentinel/runs/<slug>/` | no |
| QA logs, screenshots, uploads | `.sentinel/cache/` | no |
