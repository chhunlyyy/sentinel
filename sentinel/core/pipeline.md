# Sentinel pipeline

Provider-neutral contract. Any AI tool, or a human, can run it. Stages talk through files in `.sentinel/runs/<slug>/`, never through chat memory.

## Vocabulary

- repo: one entry in `repos` of `sentinel.config.yaml`. Each has a `role` (app, backend, frontend, mobile, any custom name).
- stage: one unit of work with a brief file in and a result file out.
- run: one increment, identified by a slug. State lives in `runs/<slug>/state.json`.
- shared repo: team repo cloned to `.sentinel/shared/`. Holds invariants, specs, and the regression suite.

## Phase 0: triage

Pick the tier from the request using the matrix, then apply the escalation rule: any single factor at a higher tier pulls the whole run up.

| Factor | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---|---|---|---|
| Repos touched | 1 | 1 | 1 or more | 2 or more |
| Files likely changed | 0-1 | 1-3 | 3-8 | 8+ |
| Schema migration | no | no | additive | any |
| Auth or permission change | no | no | existing pattern | new rules |
| Security surface | none | none | low | medium or high |
| Regression risk | none | low | medium | high |
| Business logic | trivial | simple | moderate | complex |

Tier is decided by task size and risk only. Requester override: "light" lowers one tier (never below 1); "full" forces tier 4.

Print one status line: tier, reason, rough cost. Then start. Write `state.json` with tier and baseline SHAs.

## Pipeline by tier

```
Tier 1: Coder
Tier 2: [Repro, bugs only] > Coder > Release Check (+secret scan) > Metrics > Changelog line
Tier 3: Specifier > Re-triage gate > Coder > Cleaner > Reviewer > Targeted QA
        > Regression promotion > Release Check (+security gate, +migration safety if schema)
        > Docs, changelog, PR draft > Metrics
Tier 4: Specifier > Re-triage gate > Coder > Cleaner > Hardener > Reviewer > Full QA
        > Regression promotion > Release Check (+security gate, +migration safety)
        > Docs, changelog, PR draft > Rollout notes > Retrospective > Metrics
```

Shape effects, from `shape` in config:

- single: one repo, no sync checkpoint.
- fullstack: coder runs per repo in `cross_repo.order`; sync checkpoint after the first repo.
- fullstack-mobile: backend first, one sync checkpoint, then frontend and mobile in parallel against the same reconciled contract.
- custom: `cross_repo` in config decides.

## Stage contracts

| Stage | Question | Input | Output |
|---|---|---|---|
| Repro | Can the bug be shown? | bug report | failing test or exact repro steps, kept as a regression |
| Specifier | What must be true, including permissions and unhappy paths? | decisions file | `specs/<slug>.md` (Gherkin, QA procedure, API contract note) |
| Re-triage gate | Is the tier still right? | spec | same tier or higher; never lower after code starts |
| Coder | Is it built? | spec, invariants, reconciled contract | code in the repo's `write_scope` only |
| Cleaner | Readable and simple, same behavior? | changed files | refactor, tests still green |
| Hardener | Do tests pin down behavior? | changed code | mutation run, new tests for survivors |
| Reviewer | Right and secure, matching spec and invariants? | diff, spec | findings with file:line, routed to the owning repo |
| QA | Works for a real user, nothing old broke? | spec QA procedure | pass or fail per step, each failure triaged code-bug or spec-gap |
| Regression promotion | Do accepted scenarios live on as tests? | passing QA run | tests added to `shared/` regression suite |
| Release check | Shippable? | all repos | build, lint, typecheck, tests, diff hygiene, secret scan, dependency audit |
| Docs and PR draft | Can others understand and ship it? | diff, spec | docs, CHANGELOG entry, PR title and body |
| Rollout notes | What must the deploy change? | coder reports | flags, env, config, order of deploy |
| Retrospective | Did we learn a project-wide rule? | run record | proposed invariants as a PR to the shared repo |
| Metrics | What did it cost? | stage logs | `metrics.json`: tokens, time, rounds, estimated vs actual tier |

## Gates and loops

- Caps come from `limits`: review rounds, QA rounds, release-check rounds. At a cap, stop and report "not production-ready" with the open items.
- Auto-escalation: a blocker from the reviewer in tier 2 or 3 re-triages the run upward.
- Failure routing: code-bug goes to that repo's coder, then its hardener (tier 4), then reviewer re-check, then QA again. Spec-gap goes to the specifier; product decisions go to the requester.
- Human gates (tier 3 and 4): confirm before QA clones real data; confirm before any push or PR.
- Never trust a stage's own report when it ran on a different model or runner: re-run its key check (tests, mutation score, a failing QA step) before accepting.

## Run isolation

Each run works on its own branch or worktree per repo. A lock file `shared/locks/<slug>` stops two people from taking the same slug. Pre-flight records baseline SHAs and baseline health (build, lint, typecheck). A broken baseline is reported and fixed as its own increment, not folded into the feature.

## State

After every stage write `state.json`: stage, runner and session ids, rounds used, tier, baseline SHAs. `sentinel resume <slug>` continues from it. Nothing a later stage needs lives only in conversation.
