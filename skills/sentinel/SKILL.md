---
name: sentinel
description: Runs a tiered build pipeline for any feature or bug fix. Picks an effort tier from the size and risk of the task, then runs only the stages that tier needs (repro, specifier, coder, cleaner, hardener, reviewer, QA, regression promotion, release check, docs, rollout notes, retrospective). Use when asked to "run sentinel", to use /sentinel, "do this properly end to end", or to implement a feature or fix a bug with the right level of rigor. The requester can override the tier with "light" or "full".
---

You are the orchestrator. The pipeline contract is `pipeline.md`, next to this file; this file is how you drive it. The config is `sentinel.config.yaml` at the workspace root. While you orchestrate you do not write source code; the stages do.

`sentinel` below is the Sentinel command line tool. If the command is not found, tell the requester to install it with `uv tool install git+https://github.com/chhunlyyy/sentinel` (or `pipx install` with the same URL) and stop. `sentinel --help` lists every command.

Each stage is also installed as its own skill (`sentinel-repro`, `sentinel-spec`, `sentinel-code`, `sentinel-clean`, `sentinel-harden`, `sentinel-review`, `sentinel-qa`, `sentinel-promote`, `sentinel-docs`, `sentinel-rollout`, `sentinel-retro`, `sentinel-release-check`) so a requester can run one stage alone. If the requester wants only one stage, point them to that skill instead of starting a pipeline run.

## Commands you use

- `sentinel doctor`: check the setup.
- `sentinel sync pull`: fetch the team's shared repo into `.sentinel/shared/` (latest specs, invariants, regression suite).
- `sentinel run new <slug> --tier N`: create the run, lock the slug for the whole team, record baseline commits.
- `sentinel run update <slug> --stage S [--round review|qa|release_check=N] [--tier N]`: record progress after every stage.
- `sentinel resume <slug>`: print the next stage, pending stages, rounds, and any capped loops.
- `sentinel stage render --stage S [--repo ID]`: print the complete instructions for a stage in this project.
- `sentinel release-check [--repo ID] [--skip build]`: the production-readiness gate.
- `sentinel scrub`, `sentinel scrub --check`: remove and detect secrets and personal data.
- `sentinel sync push <slug> --yes`: publish specs and regression tests to the shared repo for review.
- `sentinel run finish <slug> --outcome passed|stopped|abandoned`: close the run and release its lock. Always call it, including when you stop at a cap.
- `sentinel metrics record <slug> --stage S --tokens N --seconds N`: record a stage's cost when your tool reports it. `sentinel stats` adds the runs up.

## Setup check (every time, before anything else)

Run `sentinel doctor`. If it reports a problem:

- No `sentinel.config.yaml`: use the `sentinel-setup` skill, or run `sentinel init` and answer its questions together with the requester.
- The shared repo is missing or not cloned: stop here. Ask the requester for the clone URL of their team's private shared repo (an empty private git repository their team owns; for a quick local trial, a bare repo on disk works). Then run `sentinel shared set <url>`. If that repo was empty, Sentinel commits starter files locally; tell the requester to publish them once with the command it prints. Do not triage or start a run until `sentinel doctor` no longer reports the shared repo.
- Any other problem: show it to the requester. Continue only if it is something this task does not need.

## Running a stage

`sentinel stage render --stage S [--repo ID]` prints the complete instructions for that stage in this project: its rules, the repo's commands, the team's guidelines, and the paths to read and write. Run every stage this way:

1. Write a short brief to `.sentinel/runs/<slug>/<repo>-<stage>-brief.md`: what to do, the files involved, any findings to fix, and the previous result file.
2. Run the stage in its own fresh context. Do not do it yourself in this conversation: a stage's result is only worth trusting when it came from a clean context, and the reviewer must never review code that its own context wrote. Use the first of these that your tool offers:
   - **A subagent.** Start one with the rendered instructions and the brief as its task. In Claude Code use the Agent tool with a general-purpose agent. In Antigravity call `invoke_subagent` with the built-in `self` subagent (a clean clone of you with the same tools; workspace `inherit`). In other tools use their subagent, delegate or task feature. Independent stages, such as the cleaners of different repos, may run in parallel.
   - **A fresh headless session of the same tool.** Run `sentinel stage run --stage S [--repo ID] --slug <slug> --brief <file> --runner <claude|agy|codex|gemini>`. It also checks every repo afterwards: exit 3 means the stage wrote outside its repo, committed, or touched the Sentinel config (show the listed files to the requester and revert nothing without their agreement); exit 1 means the tool failed (retry once, then try the other option and say so).
   - **Inline, only if neither exists.** Tell the requester at once that this stage runs in the same context. For the reviewer and for QA, stop and ask the requester how to proceed instead of reviewing or testing your own work.
3. Record how the stage ran, so the report is honest: `sentinel run update <slug> --stage S --session S=subagent` (or `headless` or `inline`).
4. Verify the result yourself before recording it as done: re-run the failing repro, the tests, a failing QA step. Never accept a stage's own report on trust.

Optional routing: if `sentinel.config.yaml` has a `routing` section, a stage routed to another tool always runs with `sentinel stage run`. Tools without sessions cannot be resumed; send a finding back as a new brief that quotes it and names the previous result file.

## Phase 0: triage

1. Read the request. Quick scan of the code it touches (search only; no stage yet).
2. Classify with the matrix in `pipeline.md` and apply the escalation rule. Size and risk decide the tier, nothing else. "light" lowers one tier; "full" forces tier 4.
3. Print one line: tier, reason, rough cost. Then start.
4. A bug report? Tier 2 and up start with the repro stage.

## Phase 1: interview (tier 3 and 4)

Interview the requester until nothing is silently assumed. Ask every question that does not depend on another unanswered one in a single round, each with your recommended answer, in your tool's question prompt if it has one, otherwise in chat. Find facts yourself; ask only for decisions. When the requester says skip, list the decisions you are assuming and start after they confirm.

Write `.sentinel/runs/<slug>/decisions.md`: the request in one paragraph, then `D1: <decision> (because <reason>)` lines. This file, not the conversation, is the record.

## Pre-flight (tier 2 and up)

Record each repo's current commit and its health (build, lint, typecheck, test commands from the config). A broken baseline is reported and fixed as its own task, never folded into the feature. Work on a branch or worktree per repo if the requester wants isolation. Append a `## Baseline` section to decisions.md.

## Pipeline

Run `sentinel sync pull`, then `sentinel run new` (it locks the slug for the team; if it reports the slug is locked, pick another slug or ask who holds it), then walk the stages for the tier in order. After each stage: verify, then `sentinel run update`.

Stage notes:

- Repro: per repo touched. Must end with a failing test or exact steps.
- Specifier: check the spec has permission, invalid-input, empty, and failure scenarios and invariants in scope. If it says the request is too big, relay its slicing to the requester.
- Re-triage gate: read the spec's size and risk estimate. Raise the tier if needed (`sentinel run update --tier`); never lower it.
- Coders: follow `cross_repo` for the configured shape. Single repo: no sync. Otherwise the first repo, then the sync checkpoint, then the rest (in parallel where `parallel_after_sync` lists them and your tool can). Sync checkpoint: ask the finished coder what it actually built (exact routes, fields, status codes) and hand that, not the spec's intent, to the next coder.
- Cleaner, then hardener (tier 4) per repo touched.
- Reviewer: pass spec, decisions, reconciled contract, changed repos, and any pre-existing uncommitted files to exclude. Blocker or major: back to the owning coder with the exact finding, then hardener (tier 4), then the reviewer re-checks only those findings. Count rounds against `limits.review_rounds`. A blocker in tier 2 or 3 re-triages upward.
- QA: tier 3 `targeted`, tier 4 `full`. Ask the requester before any real-data clone. Route failures: code-bug to that repo's coder (a test reproducing it first), then hardener, reviewer, QA again; spec-gap to the specifier (product decisions go to the requester). Count against `limits.qa_rounds`.
- Promotion: only after QA passes. Moves checks into the shared regression suite.
- Release check: `sentinel release-check`. Pass `--repo <id>` for each repo this increment touched (the default checks every repo with uncommitted changes, including unrelated work in progress), and `--skip build` when a dev server is running on that repo, because a build overwrites its output folder. Each failure goes to the owning repo's coder; re-run until `RELEASE CHECK PASSED`, capped by `limits.release_check_rounds`.
- Change map: once the release check passes, use the `sentinel-change-map` skill and put the HTML path in the report.
- Docs stage, then rollout notes (tier 4), then retrospective (tier 4). The retrospective only proposes invariants.
- Scrub: run `sentinel scrub` after QA and again before sync, then `sentinel scrub --check`; a non-zero exit blocks the sync.
- Sync: when a run passes, ask the requester before pushing anything. After approval run `sentinel sync push <slug> --yes`; it refuses if the scrub check fails, then pushes a `sentinel/<slug>` branch for pull request review. Never force-push. Then `sentinel run finish <slug>`.
- Metrics: after each stage call `sentinel metrics record` when your tool reports tokens or time.

## Caps and stopping

At a cap, or with any open blocker, failing QA step, regression, or failed release check: stop, run the release check anyway so nothing is left behind, and say plainly the increment is not production-ready and why. Never mark a run done otherwise. If triage feels wrong mid-run, stop and re-triage.

## Guardrails

- A repo-scoped stage never writes outside its repo. The reviewer writes nothing. QA writes only under the state cache and the shared regression folder.
- Route out-of-lane findings to the right stage instead of letting a stage make the change.
- Keep every handoff concrete: file paths, exact route and field names, finding locations, QA step numbers.
- The active rules in the config (`rules`) are already inside each rendered stage; enforce them in your own output too.
- Never commit or push yourself unless the requester asked for it.
- Final report: what was built, the tier and any escalation, how each stage ran (subagent, headless or inline; flag every inline stage), what each stage found and fixed, QA and regression results, the release-check result, open minor findings, and the paths to the rollout notes, PR draft and proposed invariants.
