# Sentinel 1.1.0 Unified Specification

**Status:** Approved at gate G1 on 2026-11-14 by the project owner. Open questions Q1 to Q3 resolved at G1 (see end of file).
**Sources:** `plan/v1.1/SPEC_CORE.md` (C), `plan/v1.1/SPEC_DASHBOARD.md` (D), `plan/v1.1/IMPLEMENTATION_PLAN.md` (P), Phase 0 decisions `plan/v1.1/phase0/DECISIONS.md` (G0).
**Baseline:** 0.1.0b7, commit `aa1481c`, selftest 95 of 95 passing.

Every requirement has an ID and a source. `MUST` requirements are needed for 1.1.0. `SHOULD` requirements are in scope but may slip with a recorded reason. `LATER` items are recorded and explicitly not in 1.1.0.

---

## 1. Product vision and principles

| ID | Requirement | Source |
|---|---|---|
| VIS-01 | MUST: Sentinel is the control plane. Agents are workers. No agent authorizes its own work, approves anything, or declares a run accepted. | C 1 |
| VIS-02 | MUST: Users control requirements through two human approvals: the specification, then the Gherkin. Sentinel controls the process. Evidence produced by Sentinel decides trust. | C 2.3, D 1, G0 B5 |
| VIS-03 | MUST: Provider independence. Workflow definitions never name a provider. | C 2.2 |
| VIS-04 | MUST: Local-first. Every capability works on one machine with no network. The only remote exchange is the shared repo sync (git). | G0 B1 |
| VIS-05 | MUST: Incremental evolution. Existing CLI commands, config files and skills keep working. | C 2.7, D 22.19, P 13.3 |
| VIS-06 | MUST: The dashboard is a client of the engine. It never holds orchestration logic. | D 8, P 4.2 |
| VIS-07 | MUST: A new user can install Sentinel, open the dashboard, create a project, add repos, configure it, and start a task without editing files. | D 1, P 1 |

## 2. System architecture

| ID | Requirement | Source |
|---|---|---|
| ARC-01 | MUST: One engine (Python package `sentinel`) owns state, transitions, policy, approvals, dispatch, verification and persistence. CLI, skills and dashboard call it. | P 4.2 |
| ARC-02 | MUST: A local API server (`sentinel dashboard`) runs in the same installation and exposes engine functions over HTTP on loopback only. It is the trusted local companion of D 2.2. | D 2.2, D 20, G0 B1 |
| ARC-03 | MUST: The AI-tool orchestrator (skills) proposes transitions through the CLI. The engine accepts or refuses them. | C 2.1, G0 |
| ARC-04 | MUST: Modules are extracted only when they hold real code. No empty directories. | C 3, C 15 |
| ARC-05 | LATER: Remote Sentinel installations, hosted multi-user service, PostgreSQL, S3 storage, A2A adapter. | C 10, C 5.4, G0 B1 |

Details: `docs/architecture/system-architecture.md`.

## 3. Installation and runtime management

| ID | Requirement | Source |
|---|---|---|
| INS-01 | MUST: `sentinel dashboard` starts the local server and opens the browser at a URL that carries a one-time session token. | D 2.2 |
| INS-02 | MUST: The dashboard shows the detected installation: path, version, Python version, install method. | D 2.2 |
| INS-03 | MUST: Health checks, each Passed / Warning / Failed / Not Configured: installation, version supported, runtime dependencies (git, python, pyyaml, jsonschema), registry writable, at least one usable provider, storage, per-repo access. Readiness is never reported when a required check fails. | D 2.3 |
| INS-04 | MUST: The dashboard reports whether a server is already running (pid file plus port) and connects to it instead of starting a second one. | D 2.2 |
| INS-05 | MUST: Errors carry an actionable fix (the command or setting to change). | D 2.2 |
| INS-06 | MUST: The browser never executes local commands or reads arbitrary paths. Every filesystem or process operation is an allow-listed API operation with validated arguments. | D 2.2, D 18, P 5 |
| INS-07 | MUST: `sentinel doctor` stays, and uses the same health-check functions as the dashboard. | D 22.19 |
| INS-08 | SHOULD: The dashboard offers a directory picker served by the API, restricted to the user's home directory and configured workspace roots. | D 2.2 |

## 4. Project management

| ID | Requirement | Source |
|---|---|---|
| PRJ-01 | MUST: A project is a workspace directory containing `sentinel.config.yaml`. The file stays the source of truth. | D 3, VIS-05 |
| PRJ-02 | MUST: A user-level project registry lists known projects (`~/.config/sentinel/projects.json`, XDG aware). It stores paths and display data only. | D 3.1 |
| PRJ-03 | MUST: Create a project from the dashboard: name, description, type, languages, frameworks, workspace directory, default branch, owner, environment, optional instructions. Creation writes `sentinel.config.yaml` through the same code as `sentinel init`. | D 3.1 |
| PRJ-04 | MUST: Register an existing workspace. Edit, archive (registry flag) and remove from the registry. Removing never deletes files. | D 3.1, P 6 |
| PRJ-05 | MUST: Guided setup and an advanced view. | D 3.1 |

## 5. Repository management

| ID | Requirement | Source |
|---|---|---|
| REP-01 | MUST: A project holds one or more repos (`repos[]`). | D 3.2 |
| REP-02 | MUST: Add a local git repo by path, or a remote git URL that Sentinel clones into the workspace. Remote access uses the user's git credentials; Sentinel stores none. | D 3.2, G0 B1 |
| REP-03 | MUST: Per repo: id, path, remote, default branch, current branch, role, profile (language and framework), build, test, lint, typecheck and mutate commands, guidelines file. | D 3.2 |
| REP-04 | MUST: Validate existence, git status, remote, branch availability, write permission, profile compatibility. | D 3.2 |
| REP-05 | MUST: Add, edit, remove and reorder repos from the dashboard. Order drives `cross_repo.order`. | D 3.2 |
| REP-06 | MUST: Language and framework detection reuses `detect_profile`. | P 6 |
| REP-07 | MUST: A task targets one or more repos. Cross-repo order and the sync checkpoint follow the existing shape rules. | D 3.3 |

## 6. Configuration management

| ID | Requirement | Source |
|---|---|---|
| CFG-01 | MUST: Every setting that today needs a file edit has a dashboard form, where safe. | D 4 |
| CFG-02 | MUST: Scopes: global (`~/.config/sentinel/config.yaml`), project (`sentinel.config.yaml`), repo (`repos[]` entry), task (snapshot at run start). Precedence: task > repo > project > global > built-in default. | D 4.2, P 7 |
| CFG-03 | MUST: Validation against the JSON Schema before any save takes effect. Invalid config is never activated. | D 4.6 |
| CFG-04 | MUST: Save writes YAML while keeping comments and key order where possible. | D 4.7, VIS-05 |
| CFG-05 | MUST: Every saved version is kept in the registry (content, hash, author, time). History, diff between versions, restore. | D 4.6 |
| CFG-06 | MUST: Effective-config view shows each value and where it came from. | D 4.7 |
| CFG-07 | MUST: Import (validated) and export of a project config. | D 4.7 |
| CFG-08 | MUST: A run uses the config snapshot taken when it started. A config change never alters a running run. The dashboard shows the change impact. | D 4.6 |
| CFG-09 | MUST: Configuration can add gates and policies, never remove the two mandatory approvals. | D 4.3, D 4.4 |
| CFG-10 | MUST: Profiles (stack profiles) offer starting values for commands, test globs and verification. | D 4.5 |
| CFG-11 | MUST: The config schema gains, additively: `policies`, `tdd`, `verification`, `providers`, `agents`, `notifications`. Configs without them stay valid. | P 7 |

## 7. Provider management

| ID | Requirement | Source |
|---|---|---|
| PRV-01 | MUST: Providers are the existing runners (claude, codex, gemini, agy, custom). The dashboard lists them with install status and capabilities. | D 4.2 |
| PRV-02 | MUST: Enable or disable, choose default, choose model, provider options, fallback order. | D 4.2 |
| PRV-03 | MUST: Connectivity test reuses `doctor --check-models`. | D 4.2 |
| PRV-04 | MUST: Sentinel 1.1.0 stores no provider API keys. Provider CLIs keep their own credentials. If a later adapter needs a key, it goes to a 0600 secrets file and is never returned by the API. | D 4.2, D 18 |
| PRV-05 | MUST: `single_model` keeps its meaning: every stage runs in the current tool. | VIS-05 |

## 8. Agent registry and execution

| ID | Requirement | Source |
|---|---|---|
| AGT-01 | MUST: Roles: planner (triage), specifier, test_designer, tdd_red, tdd_green, tdd_refactor, hardener, reviewer, qa, promotion, docs, rollout, retrospective. Existing stages map onto them. | C 3, C 6 |
| AGT-02 | MUST: Every task uses the task contract `task-v1` and returns `agent-result-v1`. | C 5.1 |
| AGT-03 | MUST: Adapter interface: `capabilities`, `submit`, `status`, `result`, `cancel`, `resume`. `resume` and `cancel` only when capabilities say so. | C 5.2 |
| AGT-04 | MUST: CLI adapter (from `run_stage.py`) and native adapter (in-tool subagent through the same files). | C 5.4 |
| AGT-05 | MUST: Timeouts, retry limits, cancellation, result validation, provider-failure policy (fallback provider or fail). | C 5.3 |
| AGT-06 | MUST: Agents cannot widen their permissions, approve, or change run state. No nested delegation. | C 5.4 |
| AGT-07 | MUST: Tasks with overlapping write scopes never run at the same time. | C 5.4 |
| AGT-08 | MUST: Dashboard manages role to provider and model assignment, limits, timeouts and retries per role. | D 4.3 |
| AGT-09 | LATER: A2A adapter, API adapters. | C 5.4 |

Details: `docs/architecture/agent-runtime.md`.

## 9. Deterministic orchestration

| ID | Requirement | Source |
|---|---|---|
| ORC-01 | MUST: Every transition is defined in one table: from, to, actor, preconditions, required evidence, policy, failure handling. Undefined transitions are refused. | C 9 |
| ORC-02 | MUST: Actors: `engine`, `orchestrator` (the AI tool through the CLI), `human` (TTY or authenticated dashboard). | C 2.1 |
| ORC-03 | MUST: Triage: the orchestrator submits factor values; the engine computes the minimum tier from the matrix in `pipeline.md`. The tier only rises. | C 7 |
| ORC-04 | MUST: The workflow graph is generated per run from tier, shape, repos and approved scenarios. | D 8 |
| ORC-05 | MUST: Retry and round caps come from `limits` and `policies`. At a cap the run goes to `NEEDS_HUMAN` or `FAILED` per policy. | C 5.3 |
| ORC-06 | MUST: Human-required actions by policy: security gate (tier 4 or auth change), destructive migration, real-data QA clone, publishing to the shared repo, PR creation, spec or Gherkin change after approval, unresolved policy violation. | C 4.3 |
| ORC-07 | MUST: A resumed run reads only persisted state. | C 10 |
| ORC-08 | MUST: Runs created before 1.1.0 (no `schema_version`) continue in legacy mode. | VIS-05 |

Details: `docs/architecture/orchestration-architecture.md`.

## 10. Workflow state machine

| ID | Requirement | Source |
|---|---|---|
| SM-01 | MUST: Run states: `CREATED, TRIAGED, PLANNED, SPECIFICATION_REVIEW, SPECIFICATION_APPROVED, GHERKIN_REVIEW, GHERKIN_APPROVED, EXECUTING, VERIFYING, REVIEWING, NEEDS_HUMAN, COMPLETED, FAILED, CANCELLED, BLOCKED`. | C 9, G0 B8 |
| SM-02 | MUST: `execution_status` (running, completed, failed, cancelled) and `acceptance_status` (pending, accepted, rejected) are separate. A completed run may be rejected. | C 8 |
| SM-03 | MUST: Task states: `CREATED, QUEUED, RUNNING, WAITING_FOR_INPUT, BLOCKED, FAILED, CANCELLED, COMPLETED`. | C 5.3 |
| SM-04 | MUST: Approval states: `DRAFT, IN_REVIEW, CHANGES_REQUESTED, REJECTED, APPROVED, INVALIDATED`. | C 4.4 |
| SM-05 | MUST: TDD cycle states: `PLANNED, RED_RUNNING, RED_VERIFIED, GREEN_RUNNING, GREEN_VERIFIED, REFACTOR_RUNNING, REFACTOR_VERIFIED, CYCLE_ACCEPTED`, with `REJECTED` per phase. | C 9 |

Full table: `docs/contracts/state-transitions.md` (part of the API contract set).

## 11. Specification approval (Gate 1)

| ID | Requirement | Source |
|---|---|---|
| SPA-01 | MUST: The specifier writes `specs/<slug>/spec.md` in the shared folder. | C 4.1 |
| SPA-02 | MUST: Required sections scale by tier. Tier 3 and 4: all 16 sections of C 4.1. Tier 1 and 2: problem, scope, out of scope, functional requirements (`REQ-n`), acceptance criteria (`AC-n`), edge cases, security considerations, risks. Docs-only: problem, scope, deliverables. Each omitted section in a full spec says "not applicable" and why. | C 4.1, G0 B5 |
| SPA-03 | MUST: The engine validates the spec (sections, unique `REQ` and `AC` ids, every AC linked to a REQ) before review. | C 4.1 |
| SPA-04 | MUST: Review shows the spec, the diff from the last reviewed version, and validation warnings. | D 7 |
| SPA-05 | MUST: Decisions: approve, request changes (with comments), reject. Changes go back to the specifier with the comments. Reject terminates the run. | C 4.1 |
| SPA-06 | MUST: Approval stores approver, time, version, sha256, decision, comment. | C 4.1 |
| SPA-07 | MUST: Every tier needs spec approval before Gherkin design starts. | G0 B5 |
| SPA-08 | MUST: A spec change after approval invalidates the spec approval and any Gherkin approval, and returns the run to `SPECIFICATION_REVIEW`. | C 4.1, G0 B5 |

## 12. Gherkin approval (Gate 2)

| ID | Requirement | Source |
|---|---|---|
| GHA-01 | MUST: The test designer writes `specs/<slug>/features/*.feature` from the approved spec only. | C 4.2 |
| GHA-02 | MUST: Each Scenario or Scenario Outline has `@REQ-n`, `@AC-n`, a type tag (`@unit`, `@integration`, `@e2e`, `@security`, `@regression`) and a priority tag (`@P1` to `@P3`). | C 4.2 |
| GHA-03 | MUST: Validation: parses as Gherkin (supported subset: Feature, Rule, Background, Scenario, Scenario Outline, Examples, tags, Given/When/Then/And/But, doc strings, data tables), every AC has at least one scenario, every tag points at an existing REQ or AC. | C 4.2 |
| GHA-04 | MUST: A coverage table per C 4.2 categories (happy path, invalid input, missing fields, boundary, empty/null, authn, authz, data integrity, duplicate, concurrency, errors, external failure, DB failure, regression, performance/security) marks each covered, not applicable (with a reason), or missing. Missing items are warnings shown to the human; one scenario per requirement is never reported as complete coverage. | C 4.2 |
| GHA-05 | MUST: Same review decisions, storage and invalidation as SPA-04 to SPA-06. Hash covers all `.feature` files, sorted by path. | C 4.2 |
| GHA-06 | MUST: Only an approved Gherkin set authorizes Red. | C 4.2 |
| GHA-07 | MUST: Docs-only tasks skip Gate 2. | C 7 |

## 13. TDD engine

| ID | Requirement | Source |
|---|---|---|
| TDD-01 | MUST: Approved scenarios are grouped into behaviors; each behavior runs one Red, Green, Refactor cycle. | C 6.4 |
| TDD-02 | MUST: Red writes native tests (project framework) that reference their scenario (`feature path :: scenario name` in a comment-free form such as the test name or an annotation, per profile). Only test globs are writable. | C 6.1, R8 |
| TDD-03 | MUST: The engine runs the targeted tests and classifies the result: `assertion` (accepted), `compile`, `environment`, `missing_dependency`, `preexisting_failure`, `unknown`. Only `assertion` failures of the new tests, with the rest of the suite unchanged from baseline, verify Red. `unknown` goes to `NEEDS_HUMAN`. | C 6.1 |
| TDD-04 | MUST: Green writes production globs only. Any change to an approved test file fails the task. The engine re-runs the targeted tests; they must pass. | C 6.2 |
| TDD-05 | MUST: Refactor writes production globs only. The engine re-runs the relevant tests; a failure rejects the refactor and routes it back. | C 6.3 |
| TDD-06 | MUST: Each cycle stores evidence written by the engine: commands, exit codes, captured output (scrubbed), test counts, timestamps, changed files with hashes, working-tree reference, provider and model, task ids. | C 6.5 |
| TDD-07 | MUST: Bug fixes start with the repro test as cycle 1 Red and keep it as a regression test. | C 7 |
| TDD-08 | MUST: Permission matrix of C 6.6. Any exception is an explicit, recorded engine authorization. | C 6.6 |
| TDD-09 | MUST: With `no_permanent_frontend_tests` on, frontend repos use QA scenarios as Red evidence and the run records the exception. | G0 B10 |

## 14. Independent verification and acceptance

| ID | Requirement | Source |
|---|---|---|
| VER-01 | MUST: The engine runs: targeted tests, full test command, build, lint, typecheck, secret scan, dependency audit, diff-scope check, migration safety (when a schema changed), mutation (tier 4). Reuses `release_check.py`. | C 8 |
| VER-02 | MUST: Agent claims are never evidence. | C 8 |
| VER-03 | MUST: Acceptance is refused when: an approval is missing or invalid by hash, cycles are incomplete, required tests fail, evidence is missing, scope was exceeded, required reviews are open, required human approvals are missing. | C 8 |
| VER-04 | MUST: Final human acceptance in the dashboard or CLI records the human decision on top of the computed result. It cannot accept a run the engine rejects. | D 6, D 12 |

## 15. Dashboard

| ID | Requirement | Source |
|---|---|---|
| DSH-01 | MUST: Navigation of D 19, local single-user. | D 19 |
| DSH-02 | MUST: First-run wizard: installation, health, create project, add repos, configure, readiness, first task. | D 2.1 |
| DSH-03 | MUST: Readiness states: Ready, Ready with warnings, Needs configuration, Invalid configuration, Connection unavailable. Based on executed checks only. Only the needs of the selected workflow are required. | D 5 |
| DSH-04 | MUST: The UI never claims success before the API confirms it. | D 11 |
| DSH-05 | MUST: Live updates through SSE with reconnect and full state refresh. | D 20 |
| DSH-06 | MUST: Works fully offline. All assets are served by the local server; no CDN. | VIS-04 |

Details: `docs/architecture/system-architecture.md` section 5.

## 16. Task management

| ID | Requirement | Source |
|---|---|---|
| TSK-01 | MUST: Create a task: request text, project, target repos, priority, type (feature, bug, docs, refactor, ...), optional tier override (raise only), optional provider preference, branch or ticket reference, attachments. | D 6 |
| TSK-02 | MUST: Creating a task does not authorize implementation. | D 6 |
| TSK-03 | MUST: A dashboard-created task runs through the same engine. The AI work is dispatched to the configured providers by the CLI adapter; native subagent stages need an AI tool session and are shown as "waiting for orchestrator". | D 8, G0 |
| TSK-04 | MUST: Templates for common task types. Templates cannot skip gates. | D 15 |

## 17. Workflow monitoring

| ID | Requirement | Source |
|---|---|---|
| MON-01 | MUST: Show the real run graph, stage status, dependencies, agent, provider, model, timings, retries, failures, logs, artifacts, blockers, human actions. | D 11 |
| MON-02 | MUST: Controls: pause, resume, cancel, retry, request intervention. Each is an engine transition. | D 11 |
| MON-03 | MUST: Live log tail of running tasks (from the existing live log files). | D 11 |

## 18. Code changes and Git

| ID | Requirement | Source |
|---|---|---|
| GIT-01 | MUST: Per repo: branch, base commit, changed files, additions and deletions, diff (inline and side by side), linked task and cycle. | D 14 |
| GIT-02 | MUST: Branch creation, commits, PRs and shared-repo publishing follow policy; publishing is off unless configured; agents never commit. | C 11, D 14 |
| GIT-03 | SHOULD: The change map is embedded in the run view. | D 14 |

## 19. Requirement-to-code traceability

| ID | Requirement | Source |
|---|---|---|
| TRC-01 | MUST: Chain REQ to AC to scenario to cycle to changed files to evidence to human acceptance, stored as links in the registry. | C 2.6, D 12 |
| TRC-02 | MUST: Gaps are reported separately from failures (missing link vs failing check). | D 12 |

## 20. Artifact and knowledge management

| ID | Requirement | Source |
|---|---|---|
| ART-01 | MUST: Artifacts live under `.sentinel/runs/<slug>/` and are referenced by sha256 in the registry. Integrity is checked on read. | C 11 |
| ART-02 | MUST: Knowledge (invariants, guidelines, specs, regression suite) stays in the shared folder; the dashboard can view and edit it, and publishing to the remote shared repo needs authorization. | D 15, C 11 |
| ART-03 | MUST: `sentinel run export` / `import` produce and read a scrubbed bundle for moving a run between machines. | C 10 |
| ART-04 | MUST: Retention follows `state.retention`. | existing |

## 21. Notifications

| ID | Requirement | Source |
|---|---|---|
| NOT-01 | MUST: In-dashboard notifications for: pending approvals, changes requested, run start and end, agent failure, blocked, provider unavailable, verification failure, human intervention. | D 16 |
| NOT-02 | SHOULD: Desktop notification through the browser Notification API when permitted. | D 16 |
| NOT-03 | MUST: Opening a notification is never an approval. | D 16 |

## 22. Analytics

| ID | Requirement | Source |
|---|---|---|
| ANL-01 | MUST: Task count and duration, approval wait time, retries, provider failure rate, TDD results, verification pass rate, rework, cost by task, role and provider (when reported). | D 17 |
| ANL-02 | MUST: Missing metrics are shown as missing, never estimated silently. | D 17 |

## 23. Security and permissions

| ID | Requirement | Source |
|---|---|---|
| SEC-01 | MUST: Server binds 127.0.0.1 only. Rejects requests whose Host or Origin is not the server's own. A random token (32 bytes) per server start authenticates every request; the browser holds it in a session cookie (`HttpOnly`, `SameSite=Strict`). | D 18, R12 |
| SEC-02 | MUST: The token file is 0600 and never readable through the API. Agents launched by Sentinel do not receive it in their environment. | B3, R1 |
| SEC-03 | MUST: CLI approvals require an interactive TTY and typing the hash prefix. Non-interactive calls are refused. | B3 |
| SEC-04 | MUST: Generated agent configs deny or forbid `sentinel approve` and dashboard token access. | R1 |
| SEC-05 | MUST: Local single user. Roles from D 18 are stored in the data model with the local user as Admin. Multi-user RBAC is LATER. | D 18, G0 B1 |
| SEC-06 | MUST: Secret redaction (scrubber) on every evidence, log and report file the API serves. | C 11 |
| SEC-07 | MUST: Audit log for every human action, approval, config change and publish. | C 11, D 16 |
| SEC-08 | MUST: `docs/security.md` states the residual risks R1 and R3 plainly. | R1, R3 |

Details: `docs/architecture/security-architecture.md`.

## 24. API contracts

| ID | Requirement | Source |
|---|---|---|
| API-01 | MUST: REST under `/api`, JSON, versioned by `/api/v1`. Groups of D 20 that map to engine functions. | D 20 |
| API-02 | MUST: SSE stream `/api/v1/events` with event ids for resume after reconnect. | D 20 |
| API-03 | MUST: Every mutating endpoint calls the same engine function as the CLI. | VIS-06 |

Details: `docs/contracts/api-contracts.md`, `docs/contracts/event-contracts.md`.

## 25. Persistence and events

| ID | Requirement | Source |
|---|---|---|
| PER-01 | MUST: Registry `.sentinel/sentinel.db` (stdlib sqlite3, WAL mode) per workspace; user-level registry for projects and global config history. | C 10, G0 B2 |
| PER-02 | MUST: Persist run, task, workflow version, config snapshot hash, repo SHAs (baseline and final), role, provider, model, inputs and outputs (by reference), approvals, versions, cycles, evidence, verification, findings, durations, cost. | C 10 |
| PER-03 | MUST: Append-only event table; every state change emits an event. | C 3 |
| PER-04 | MUST: `state.json` is still written as a compatibility view. | VIS-05 |
| PER-05 | MUST: Schema migrations are versioned and run at startup; a failed migration leaves the old database untouched. | P 13 |

Details: `docs/architecture/data-architecture.md`, `docs/contracts/configuration-schemas.md`.

## 26. Testing and acceptance criteria

| ID | Requirement | Source |
|---|---|---|
| TST-01 | MUST: All 95 existing selftest checks stay green. | P 13.4 |
| TST-02 | MUST: New unit tests with stdlib `unittest` under `tests/`. | R10 |
| TST-03 | MUST: The 23 scenarios of C 14 are automated tests. | C 14 |
| TST-04 | MUST: The 20 criteria of D 22 are verified (automated where possible, otherwise a recorded manual check). | D 22 |
| TST-05 | MUST: API security tests: wrong Host, wrong Origin, missing token, path traversal, disallowed operation. | D 23 |
| TST-06 | MUST: This upgrade itself is built test-first, phase by phase, with evidence in `IMPLEMENTATION_STATUS.md`. | C 15, P 13 |

## 27. Deployment and operations

| ID | Requirement | Source |
|---|---|---|
| OPS-01 | MUST: Ships as one Python package (`uv tool install`), with dashboard assets inside the wheel. No Node needed at runtime. | VIS-04 |
| OPS-02 | MUST: `sentinel/VERSION` = `1.1.0` at release. | G0 B7 |
| OPS-03 | MUST: Upgrade path: existing workspaces work without changes; `sentinel doctor` lists optional new settings. | VIS-05 |
| OPS-04 | MUST: Docs updated: README, `docs/workflow.md`, `docs/config.md`, `docs/security.md`, skills. | C 15 |
| OPS-05 | MUST: Backup: `sentinel backup` copies the registry with the sqlite backup API. | P 12 |

---

## Questions resolved at G1

| ID | Question | Decision |
|---|---|---|
| Q1 | Dashboard frontend technology. | React + TypeScript + Vite in `dashboard/`, built at release time into `sentinel/dashboard_dist/` inside the wheel. Node is needed only to build, never at runtime. Server stays Python stdlib (`ThreadingHTTPServer`). |
| Q2 | Can a dashboard-created task run without an AI tool session open? | Stages routed to a CLI provider run directly. With `single_model: true`, the dashboard queues the task and an AI tool session picks it up with `/sentinel resume`. |
| Q3 | Approval channel for dashboard users. | Dashboard approvals by token possession (SEC-01, SEC-02); CLI approvals by TTY (SEC-03). Both recorded with the channel used. |
| Q4 | Location of design documents. | As the plan says: `SPEC.md` and `IMPLEMENTATION_STATUS.md` at the root, `docs/architecture/`, `docs/contracts/`. |
