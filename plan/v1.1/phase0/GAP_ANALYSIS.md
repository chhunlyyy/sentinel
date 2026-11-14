# Gap Analysis

Sources:
- **C** = `plan/v1.1/SPEC_CORE.md` (core upgrade, Gate 2 = human review of the Gherkin)
- **D** = `plan/v1.1/SPEC_DASHBOARD.md`
- **P** = `plan/v1.1/IMPLEMENTATION_PLAN.md`

Status: **Impl** = implemented, **Part** = partially implemented, **Miss** = missing, **Refac** = exists but conflicts with the target, **Block** = needs a decision first (see section 3).

Baseline evidence: `python3 sentinel/scripts/selftest.py` gives 95 passed, 0 failed, on commit `aa1481c`.

## 1. Core specification (C)

| ID | Src | Requirement | Current location | Status | Required change | Depends | Verify |
|---|---|---|---|---|---|---|---|
| C-01 | C 2.1, 9 | Deterministic run state machine with validated transitions | `sentinel.py:401` `cmd_run_update` accepts any stage | Refac | Transition table (state, target, preconditions, actor, evidence); CLI rejects invalid transitions | C-30 | unit tests per transition, invalid ones rejected |
| C-02 | C 9 | Task (stage) state machine CREATED to COMPLETED/FAILED/CANCELLED/BLOCKED | none; stage is done or not done | Miss | Task records with lifecycle | C-01 | unit |
| C-03 | C 9 | TDD cycle state machine | none | Miss | Cycle records PLANNED to CYCLE_ACCEPTED | C-01, C-20 | unit |
| C-04 | C 9 | Approval state machine (draft, review, changes, rejected, approved) | none | Miss | Approval records | C-01 | unit |
| C-05 | C 2.1, 5.4 | Agents cannot change workflow state directly | orchestrator LLM calls `sentinel run update` freely | Refac | Engine checks evidence preconditions; approvals need a human-only path | C-01, Block B3 | test: agent-style call without evidence is rejected |
| C-06 | C 4.1 | Spec gate: generate, validate against schema, human approves, rejects or requests changes | specifier writes `specs/<slug>.md`; no gate | Part | Spec artifact with required sections, validator, review command, versioning | C-04 | acceptance table rows 1 to 4 |
| C-07 | C 4.1 | Spec has 16 required sections | specifier has 5 sections and says "keep it short" | Part | Tier-scaled template and validator | Block B5 | validator tests |
| C-08 | C 4.1 | Approval bound to version and content hash; material change invalidates | none | Miss | sha256 of the canonical artifact; approval stores the hash; recheck before every gated transition | C-04 | tests: edit after approval blocks coding |
| C-09 | C 4.2 | Gherkin gate: Test Designer writes `.feature` files with `@REQ`/`@AC` tags; human approves | Gherkin lives inside the spec Markdown (`specifier.md:21`) | Part | New `test_designer` stage writing `.feature` files; Gherkin parser and tag validator; review gate | C-06 | tests: untagged scenario, AC without scenario |
| C-10 | C 4.2 | Coverage categories considered and not just one scenario per requirement | specifier lists the mandatory categories | Part | Validator warns per category; human sees a coverage table | C-09 | validator tests |
| C-11 | C 4.3 | Autonomous after both approvals; human again only by policy | human gates exist for real-data clone and PR (`pipeline.md:74`) | Part | Policy list of human-required actions | C-01 | tests: security gate pauses |
| C-12 | C 5.1 | Common agent task contract (YAML) | brief Markdown plus CLI args in `run_stage.py` | Part | Task schema `task-v1`, brief generated from it | C-30 | schema tests |
| C-13 | C 5.2 | Provider adapter interface (capabilities, submit, start, status, result, cancel, resume) | `DEFAULT_RUNNERS` dict plus `build_command` (`run_stage.py:34`) | Part | Adapter class per provider kind; CLI adapter wraps current runner logic | C-12 | adapter contract tests with a fake CLI |
| C-14 | C 5.3 | Managed lifecycle: timeouts, retries, cancellation, result validation | timeout and heartbeat exist; retry is a prompt rule | Part | Retries and cancel in the engine; result validated against `agent-result-v1` | C-13 | tests with fake runner: timeout, retry, cancel |
| C-15 | C 5.3 | Adapters report real capabilities (resume, etc.) | `resume_flag` only | Part | `capabilities()` per adapter | C-13 | unit |
| C-16 | C 5.4 | Native subagent plus CLI fallback | subagent path is a skill instruction; CLI path is code | Part | Native path stays in skills but must go through the same task and result contract | C-12 | phase exit: same workflow on two providers |
| C-17 | C 5.4 | No nested delegation; overlapping files never run concurrently | `--concurrent` flag only tolerates; not prevented | Part | Scheduler checks declared write scopes for overlap | C-19 | test: overlapping tasks are refused |
| C-18 | C 5.4 | A2A adapter | none | Miss | Deferred (core spec section 5.4: after the contract is stable) | C-13 | n/a |
| C-19 | C 2.5, 6.6, 11 | Path-level write scopes, test vs production split per role | `boundary.py` is per whole repo and post-hoc | Part | Glob scopes per task; post-hoc diff check classifies each changed path; violation fails the task | Block B4 | tests: Green edits an approved test and is rejected |
| C-20 | C 6.1 | Red: tests only, run them, prove expected failure | `repro` stage leaves a failing test for bugs only | Part | `tdd_red` stage; Sentinel runs the test command itself | C-19, C-21 | acceptance rows 9, 10 |
| C-21 | C 6.1 | Classify Red failures (assertion vs compile, env, missing dep, pre-existing) | none | Miss | Failure classifier per profile (exit code plus output patterns plus baseline comparison) | C-20 | fixtures per profile |
| C-22 | C 6.2 | Green: minimal production change, approved tests untouched, tests pass | `coder` stage | Refac | Split `coder` into `tdd_green`; test paths read-only | C-19 | acceptance row 11 |
| C-23 | C 6.3 | Refactor: behavior preserved, re-run tests, reject on failure | `cleaner` stage, "tests still green" is a prompt rule | Part | Rename or extend as `tdd_refactor` with an engine-run test check | C-19 | acceptance row 13 |
| C-24 | C 6.4 | Repeat cycles per behavior | single coder pass | Miss | Cycle loop over approved scenario groups | C-03 | acceptance row 14 |
| C-25 | C 6.5 | Persisted cycle evidence: real command output, exit code, timestamps, counts | none | Miss | Evidence records written by Sentinel, never by agents | C-30 | tests: evidence present and hash-linked |
| C-26 | C 7 | Keep tiers; tiers decide rigor; docs-only has no code tests; bug fix adds a regression test | tiers exist; repro and promotion exist | Part | Map tiers to gate weight (see B5) | B5 | tier matrix tests |
| C-27 | C 7 | AI classification validated against deterministic policy | triage is the LLM using the `pipeline.md` matrix | Part | `sentinel triage` checks the submitted factors and computes the minimum tier | C-01 | unit |
| C-28 | C 8 | Independent verification (tests, build, lint, typecheck, security, migration, diff scope, mutation) | `release_check.py` runs build, lint, typecheck, test, secrets, deps | Part | Fold into a verification step that writes evidence records; add diff-scope check | C-25 | release-check tests plus new evidence tests |
| C-29 | C 8 | Separate `execution_status` and `acceptance_status`; acceptance rules | `outcome` field only | Refac | Two fields; acceptance computed from rules, not set by the agent | C-01 | tests: completed run with failed acceptance |
| C-30 | C 10 | Persistent run registry (SQLite suggested) | `state.json`, `metrics.json` files | Part | Registry with runs, tasks, approvals, evidence (see B2) | B2 | resume test from persisted state |
| C-31 | C 10 | Cross-machine resume | runs are git-ignored and local | Miss | Export or sync of run records (see B2) | C-30 | test: resume on a second workspace |
| C-32 | C 10 | Persist workflow, config version, commit SHAs, provider, model, cost | baseline SHAs, model, tokens partly | Part | Config snapshot hash per run; final SHA | C-30 | unit |
| C-33 | C 11 | Command execution policy, no unrestricted shell | provider CLIs run with `acceptEdits`; no command policy | Miss | Policy is limited by what each provider CLI allows; see risk R3 | B4 | documented, partial tests |
| C-34 | C 11 | Secret redaction | `scrub.py` | Impl | Apply to new evidence and report files | none | existing selftest plus new |
| C-35 | C 11 | Shared publishing disabled by default | `auto_sync_push: true` in template (`templates/sentinel.config.yaml:39`) | Refac | Default false for new configs; existing configs keep their value; doctor notes it | B6 | selftest update |
| C-36 | C 11 | Locking and concurrency control | slug lock (`shared.py:256`) | Part | Registry-level lock for run state writes | C-30 | concurrency test |
| C-37 | C 12 | Reports: execution, spec, Gherkin, history, TDD, verification, regression, review, files, acceptance, cost; JSON plus Markdown | change map HTML, metrics, chat report | Part | `sentinel report <slug>` writes both forms | C-25, C-29 | snapshot tests |
| C-38 | C 4.1, 4.2 | Agents cannot approve; agent statements are never proof | none | Miss | Approval only through a human-only channel (see B3) | B3 | acceptance row 22 |
| C-39 | C 3 | Target module layout | flat `scripts/` | Refac | Extract modules only when they hold real code | none | n/a |

## 2. Dashboard specification (D)

Nothing in this section exists in the repository. The CLI equivalents are noted where they exist.

| ID | Src | Requirement | CLI equivalent today | Status | Depends |
|---|---|---|---|---|---|
| D-01 | D 2.2, 20 | Local companion service with authentication and an explicit trust boundary | none | Miss | B1, C core |
| D-02 | D 2.2, 2.3 | Connect an installation, detect version, health checks | `sentinel --version`, `sentinel doctor` | Part (CLI) | D-01 |
| D-03 | D 3.1 | Multiple projects, create, edit, archive | one `sentinel.config.yaml` per workspace; `sentinel init` | Part (CLI, single project) | project registry |
| D-04 | D 3.2, 3.3 | Multiple repositories, local or remote, validated | `repos[]`, shapes, profile detection, doctor checks | Part (CLI, local paths only) | D-03 |
| D-05 | D 4.1 to 4.4 | Configuration center for providers, agents, workflows, policies, TDD, verification, git, storage, notifications, users | YAML plus schema | Part (file only) | D-01 |
| D-06 | D 4.2 | Provider secrets stored securely, never returned | none; provider CLIs hold their own credentials | Miss | D-01 |
| D-07 | D 4.5 | Configuration profiles | stack profiles in `sentinel/profiles/` | Part | none |
| D-08 | D 4.6 | Configuration validation, versioning, history, audit, snapshot per task | schema validation only | Part | C-32 |
| D-09 | D 4.7 | Effective config view with source of each setting, import, export | none | Miss | D-08 |
| D-10 | D 5 | Readiness screen based on real validation | `doctor` | Part (CLI) | D-02 |
| D-11 | D 6 | Task creation from the UI | `/sentinel` in an AI tool | Miss (UI) | C core |
| D-12 | D 7 | Approval center with diff between versions and audit | none | Miss | C-04, C-08 |
| D-13 | D 11 | Live workflow graph from the real execution graph, controls (pause, resume, cancel, retry) | `sentinel resume` prints next stage | Miss | C-02, C-14 |
| D-14 | D 12 | Requirement-to-code traceability with gap detection | none | Miss | C-09, C-25 |
| D-15 | D 13 | Verification and quality center | release-check console output | Miss (UI) | C-28 |
| D-16 | D 14 | Diffs (inline, side by side), commits, PR links | change map HTML | Part | none |
| D-17 | D 16 | Notifications | none | Miss | D-01 |
| D-18 | D 17 | Analytics (cost, failure rates, approval wait) | `sentinel stats` | Part | C-30 |
| D-19 | D 18 | RBAC roles, backend-enforced | none; single local user | Miss | D-01 |
| D-20 | D 20 | REST API plus SSE | none | Miss | D-01 |
| D-21 | D 22.19 | Existing CLI and file config stay compatible | n/a | constraint | all |

## 3. Decisions needed (Blocked items)

| ID | Question | Recommendation |
|---|---|---|
| B1 | Release scope. The dashboard spec describes a new product (server, auth, web UI, RBAC). Does it ship in this release? | Core first (C items) in this release; dashboard in the next release on top of the core API. Matches C 12 "Do not make a dashboard a prerequisite." |
| B2 | Storage for runs. SQLite (core spec section 10), or the existing JSON files? | SQLite through stdlib `sqlite3` (no new dependency) as the registry at `.sentinel/sentinel.db`; artifacts and evidence stay as files with sha256 references. Cross-machine resume via `sentinel run export/import` bundles. |
| B3 | How to make an approval provably human when agents have a shell and can run `sentinel` themselves. | `sentinel approve` requires an interactive TTY and a typed confirmation of the hash prefix; refuses non-TTY. Records git user plus OS user. Generated agent configs deny `sentinel approve*` where the tool supports deny rules. The dashboard (later) adds token-authenticated approval. State the residual risk honestly (R1). |
| B4 | Write scopes: pre-enforcement is not possible for external CLIs. | Post-hoc enforcement: per-task glob scopes, diff after the task, violation fails the task and its changes are listed (not auto-reverted without consent, as today). Optional git worktree per task later. |
| B5 | Gate weight per tier. Tier 1 today is a single coder call; two full human gates on a typo fix is heavy. | Tier 1: one combined human review (short spec plus Gherkin in one approval, both hashed). Tier 2: spec-lite plus Gherkin, two approvals. Tier 3 and 4: full spec plus Gherkin, two approvals. Docs-only: spec approval only, no Gherkin. Keeps "human approves before coding" for every tier. |
| B6 | `auto_sync_push` default changes from on to off. | New configs get `false`. Existing configs keep their explicit value. `doctor` prints a one-line note when it is on. |
| B7 | Version number. The package is `0.1.0b7`; the plan calls the target `1.1.0`. | Ask the owner. Options: `0.2.0` (still beta, honest), or `1.0.0` when core gates ship. |
| B8 | Lifecycle names differ across the three documents (C 9 vs D 6 vs P 8.1, ordering of COMPLETED and ACCEPTED, READY state). | Use the C 9 run states as canonical. Drop `ACCEPTED` as a run state; use `acceptance_status` instead. `READY` = `GHERKIN_APPROVED`. |
| B9 | Phase order. P puts dashboard installation (P phases 2 to 4) before the core engine (phase 5). | Reorder: core engine and gates before any dashboard phase. |
| B10 | Rule `no_permanent_frontend_tests` conflicts with TDD permanent tests. | Under TDD, frontend Red tests are kept unless the rule is on; when it is on, the frontend workflow uses QA scenarios as the Red evidence and the conflict is reported. |

## 4. Summary

- Implemented: 1 (secret redaction).
- Partially implemented: most core items. The foundations (tiers, stages, Gherkin in specs, runners, boundary check, release check, mutation, locks) are reusable.
- Needs refactoring: state handling (`run update`), `outcome`, `coder` to TDD split, auto-publish default, module layout.
- Missing: approvals and hashes, state machines, TDD evidence, adapter interface, registry, reports, and the whole dashboard.
- The largest architectural change: **moving authority for state transitions from the orchestrator LLM to the CLI engine**, while keeping the skills-driven, provider-neutral execution model.
