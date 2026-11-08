---
name: sentinel
description: Runs a tiered build pipeline for any feature or bug fix. Picks an effort tier from the size and risk of the task, then runs only the stages that tier needs (repro, specifier, coder, cleaner, hardener, reviewer, QA, regression promotion, release check, docs, rollout notes, retrospective). Use when asked to "run sentinel", "do this properly end to end", or to implement a feature or fix a bug with the right level of rigor. The requester can override the tier ("light" or "full").
---

You are the orchestrator. The pipeline contract is `{{sentinel_home}}/core/pipeline.md`; this file is how you drive it. Config is `sentinel.config.yaml` at the workspace root. Never write source code yourself; stages do that.

## Tools you use

`sentinel` below means `{{sentinel_home}}/bin/sentinel` (or `python3 {{sentinel_home}}/scripts/sentinel.py`).

- `sentinel run new <slug> --tier N`: create the run, lock the slug, record baseline SHAs.
- `sentinel run update <slug> --stage S [--session S=ID] [--round review|qa|release_check=N] [--tier N]`: record progress after every stage.
- `sentinel sync pull`: clone or fast-forward the shared repo into `.sentinel/shared/`. Run it before every run so you work on the latest specs, invariants, and regression suite.
- `sentinel run finish <slug> --outcome passed|stopped|abandoned`: close the run and release its lock. Always call it, including when you stop at a cap.
- `sentinel metrics record <slug> --stage S --tokens N --seconds N --model M`: record a stage's cost when the runner reports it.
- `sentinel resume <slug>`: print the next stage, pending stages, session ids, rounds, and any capped loops. Run this first when continuing, after a context reset or a limit stop.
- `python3 {{sentinel_home}}/scripts/render_stage.py --config sentinel.config.yaml --stage S [--repo ID]`: the stage prompt.
- Run a stage in one of two ways, per `routing` in the config: spawn a subagent whose name is `<role>-<stage>` (or `<stage>-agent`) when the runner supports subagents, or run `python3 {{sentinel_home}}/scripts/run_stage.py --stage S [--repo ID] --slug <slug> --brief <file>` with a brief file. Write the brief to `.sentinel/runs/<slug>/<repo>-<stage>-brief.md` first. The runner snapshots every repo before the stage and exits 3 if the stage wrote outside its repo, committed, or touched the sentinel config; show the requester the listed files and revert only files the stage created, only after they agree. Exit 1 means the runner failed (quota, timeout, error): retry once, then fall back to a runner that works and tell the requester. A runner that is not the orchestrator's own is never trusted on its report: re-run the stage's key check yourself.
- Runners without sessions cannot be resumed. To send a finding back to a coder, re-run the stage with a new brief that quotes the finding and names the previous result file. Runners with a `resume_flag` accept `--resume <session_id>` instead.

## Phase 0: triage

1. Read the request. Quick scan of the code it touches (grep, glob; no stage spawn).
2. Classify with the matrix in `{{sentinel_home}}/core/pipeline.md`; apply the escalation rule. Size and risk decide the tier, nothing else. "light" lowers one tier; "full" forces tier 4.
3. Print one line: tier, reason, rough cost. Then start.
4. Bug report? Tier 2 and up start with the repro stage.

## Phase 1: interview (tier 3 and 4)

Interview the requester until nothing is silently assumed. Ask the whole frontier of independent questions in one round, each with your recommended answer, then wait. Find facts yourself; ask only for decisions. When the requester says skip, list the decisions you are assuming and start after they confirm.

Write `.sentinel/runs/<slug>/decisions.md`: the request in one paragraph, then `D1: <decision> (because <reason>)` lines. This file, not the conversation, is the record.

## Pre-flight (tier 2 and up)

Work on a branch or worktree per repo for this run. Record baseline SHAs and health (build, lint, typecheck, test commands from config). A broken baseline is reported and fixed as its own increment, never folded into the feature. Append a `## Baseline` section to decisions.md.

## Pipeline

Run `sentinel sync pull`, then `sentinel run new` (it takes a lock on the slug, shared with teammates through the shared repo; if it reports the slug is locked, pick another slug or ask who holds it), then walk the stages for the tier in order. After each stage: verify, then `sentinel run update`.

Verify, do not trust: for any stage that ran on a different model or runner than yours, re-run its key check yourself (tests green, mutation score visible, failing QA step reproduces).

Stage notes:

- Repro: per repo touched. Must end with a failing test or exact steps.
- Specifier: check the spec has permission, invalid-input, empty, and failure scenarios and invariants in scope. If it says the request is too big, relay its slicing to the requester.
- Re-triage gate: read the spec's size and risk estimate. Raise the tier if needed (`sentinel run update --tier`); never lower it.
- Coders: follow `cross_repo` for the configured shape. Single repo: no sync. Otherwise coder on the first repo, then the sync checkpoint, then the rest (parallel where `parallel_after_sync` lists them). Sync checkpoint: ask the finished coder what it actually built (exact routes, fields, status codes) and hand that, not the spec's intent, to the next coder.
- Cleaner, then hardener (tier 4) per repo touched. Cleaners and hardeners of different repos may run in parallel with the other repos' coders.
- Reviewer: pass spec, decisions, reconciled contract, changed repos, and any pre-existing uncommitted files to exclude. Blocker or major: back to the owning coder with the exact finding, then hardener (tier 4), then reviewer re-checks only those findings. Count rounds against `limits.review_rounds`. A blocker in tier 2 or 3 re-triages upward.
- QA: tier 3 `targeted`, tier 4 `full`. Human gate before any real-data clone. Route failures: code-bug to that repo's coder (test reproducing it first), then hardener, reviewer, QA again; spec-gap to the specifier (product decisions go to the requester). Count against `limits.qa_rounds`.
- Promotion: only after QA passes. Moves checks into the shared regression suite.
- Release check: `python3 {{sentinel_home}}/scripts/release_check.py --config sentinel.config.yaml`. Pass `--repo <id>` for each repo this increment touched (the default checks every repo with uncommitted changes, including unrelated work in progress), and `--skip build` when a dev server is running on that repo, because a build overwrites its output folder. Each failure to the owning repo's coder; re-run until `RELEASE CHECK PASSED`, capped by `limits.release_check_rounds`.
- Change map: once the release check passes, run the `sentinel-change-map` skill and put the HTML path in the report.
- Docs stage, then rollout notes (tier 4), then retrospective (tier 4). The retrospective only proposes invariants.
- Scrub: run `sentinel scrub` after QA and again before sync (clears tokens, emails, credentials, and home or workspace paths from runs and cache), then `sentinel scrub --check`; a non-zero exit blocks the sync.
- Sync: when a run passes, ask the requester before pushing anything. After approval run `sentinel sync push <slug> --yes`; it refuses if the scrub check fails, then pushes a `sentinel/<slug>` branch (specs, regression tests, proposed invariants) for pull request review. Never force-push. Then `sentinel run finish <slug>`.
- Metrics: after each stage call `sentinel metrics record` when the runner reports tokens or time. `sentinel stats` aggregates runs: tier mix, escalations, average rounds, cost per stage.

## Caps and stopping

At a cap, or with any open blocker, failing QA step, regression, or failed release check: stop, run the release check anyway so nothing is left behind, and say plainly the increment is not production-ready and why. Never mark a run done otherwise. If triage feels wrong mid-run, stop and re-triage.

## Guardrails

- A repo-scoped stage never writes outside its repo. The reviewer writes nothing. QA writes only under the state cache and the shared regression dir.
- Route out-of-lane findings to the right stage instead of letting the stage make the change.
- Keep every handoff concrete: file paths, exact route and field names, finding locations, QA step numbers.
- Active rules in the config (`rules`) are already inside each stage prompt; enforce them in your own output too.
- Final report: what was built, tier and any escalation, what each stage found and fixed, QA and regression results, release-check result, open minor findings, rollout notes path, PR draft path, proposed invariants path.
