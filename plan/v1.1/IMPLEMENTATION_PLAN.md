# SENTINEL — MASTER IMPLEMENTATION PLAN

**Document Type:** Implementation Execution Plan  
**Project:** Sentinel  
**Status:** Ready for Agent Execution  
**Purpose:** Consolidate two existing specifications into one coherent Sentinel platform and implement the upgrade through controlled, verifiable phases.

---

# 1. Mission

Upgrade the existing Sentinel project into a complete AI software engineering platform.

The upgraded Sentinel must provide:

1. A deterministic orchestration engine.
2. A provider-neutral subagent runtime.
3. Human-controlled specification and Gherkin approvals.
4. TDD-first autonomous implementation.
5. Independent verification and evidence collection.
6. A dashboard for managing the entire engineering workflow.
7. Project and multi-repository management.
8. A dashboard-based configuration center.
9. First-run installation and onboarding.
10. Persistent execution history, artifacts, and engineering knowledge.

The goal is to allow a new user to install Sentinel, open the dashboard, connect their installation, create a project, configure repositories and providers, and start their first engineering task without manually editing configuration files.

**Sentinel must remain one coherent platform, not two independently implemented systems.**

---

# 2. Source Specifications

The agent must locate and inspect the two existing specification files.

For this plan, refer to them as:

- **Spec 1:** Sentinel Core Upgrade Specification.
- **Spec 2:** Sentinel Dashboard Specification.

These documents are the primary functional requirements.

If the actual filenames differ, identify them from the repository or ask the user to identify them. Do not invent replacement specifications.

## 2.1 Authority and conflict resolution

Use the following rules:

1. Both specifications must be considered.
2. The core upgrade specification defines orchestration, agent execution, approvals, TDD, and verification behavior.
3. The dashboard specification defines installation onboarding, projects, repositories, configuration, task management, monitoring, and user experience.
4. Shared requirements must be consolidated rather than duplicated.
5. The deterministic backend remains the source of truth.
6. The dashboard must not introduce an independent orchestration engine.
7. Security, human approval, and verification requirements must not be weakened to resolve conflicts.
8. If requirements conflict or are ambiguous, document the conflict and present a recommended resolution for human approval.

Do not silently discard requirements.

---

# 3. Phase 0 — Repository Discovery and Gap Analysis

**Objective:** Understand the existing Sentinel architecture before changing anything.

The agent must inspect:

- Complete repository structure.
- Existing backend architecture.
- Existing frontend/dashboard architecture.
- Existing CLI interfaces.
- Existing agent execution mechanism.
- Existing provider integrations.
- Existing workflow implementation.
- Existing task and run state management.
- Existing configuration files.
- Existing persistence and storage.
- Existing tests and regression suites.
- Existing documentation and agent instructions.

Identify the actual capabilities rather than relying on documentation alone.

## 3.1 Gap analysis

Classify every requirement from both specifications into:

| Classification | Meaning |
|---|---|
| Implemented | Already works and is verified |
| Partially Implemented | Exists but does not fully satisfy the requirement |
| Missing | Not implemented |
| Needs Refactoring | Exists but conflicts with the target architecture |
| Blocked | Requires an unresolved dependency or decision |

Each requirement must have:

- Requirement ID.
- Source specification.
- Description.
- Current implementation location.
- Current status.
- Required changes.
- Dependencies.
- Verification method.

## 3.2 Phase 0 deliverables

Produce:

1. `GAP_ANALYSIS.md`
2. `CURRENT_ARCHITECTURE.md`
3. `DEPENDENCY_ANALYSIS.md`
4. `IMPLEMENTATION_RISKS.md`

Do not begin large-scale implementation during this phase.

**Human approval gate:** Review the discovery results and proposed architecture before moving to implementation planning.

---

# 4. Phase 1 — Unified Specification and Architecture

**Objective:** Consolidate both specifications into one authoritative specification.

## 4.1 Create the master specification

Create:

`SPEC.md`

The document must include all requirements from both source specifications.

Organize it into:

1. Product vision and principles.
2. System architecture.
3. Installation and runtime management.
4. Project management.
5. Repository management.
6. Configuration management.
7. Provider management.
8. Agent registry and execution.
9. Deterministic orchestration.
10. Workflow state machine.
11. Specification approval.
12. Gherkin approval.
13. TDD engine.
14. Independent verification.
15. Dashboard.
16. Task management.
17. Workflow monitoring.
18. Code changes and Git integration.
19. Requirement-to-code traceability.
20. Artifact and knowledge management.
21. Notifications.
22. Analytics.
23. Security and permissions.
24. API contracts.
25. Persistence and event architecture.
26. Testing and acceptance criteria.
27. Deployment and operational requirements.

Every requirement must remain traceable to its source.

## 4.2 Architecture principles

The unified architecture must enforce:

- One authoritative backend.
- One deterministic orchestration engine.
- One consistent task state model.
- Provider-independent agent execution.
- Shared project and repository management.
- Versioned configuration.
- Version-bound approvals.
- Evidence-based verification.
- Persistent execution history.
- Secure dashboard-to-runtime communication.

The dashboard is a client of Sentinel's backend, not another execution engine.

## 4.3 Architecture deliverables

Create:

- `docs/architecture/system-architecture.md`
- `docs/architecture/orchestration-architecture.md`
- `docs/architecture/agent-runtime.md`
- `docs/architecture/security-architecture.md`
- `docs/architecture/data-architecture.md`
- `docs/contracts/api-contracts.md`
- `docs/contracts/event-contracts.md`
- `docs/contracts/configuration-schemas.md`

**Human approval gate:** The unified specification, architecture, data model, and API contracts must be reviewed and approved before major implementation begins.

---

# 5. Phase 2 — Installation and Runtime Foundation

**Objective:** Make Sentinel manageable through the dashboard from a fresh installation.

Implement:

- Installation discovery.
- Installation path configuration.
- Runtime validation.
- Runtime connection.
- Runtime launch and lifecycle management.
- Version detection.
- Dependency health checks.
- Secure local communication.
- Runtime authentication.
- Connection recovery.

The dashboard must not directly execute arbitrary local commands or access arbitrary filesystem paths.

Use a trusted local companion service or equivalent secured runtime integration.

Support a local installation first. Keep remote runtime support possible through the same abstraction.

## Acceptance criteria

- User can provide a Sentinel installation path.
- Installation is validated.
- Runtime version is detected.
- Missing dependencies are explained.
- Runtime can be securely connected or launched.
- Connection failures are handled correctly.
- Unauthorized local operations are rejected.
- Existing CLI usage remains functional.

---

# 6. Phase 3 — Project and Repository Management

**Objective:** Allow users to prepare their engineering projects through the dashboard.

Implement:

## Project management

- Create project.
- Edit project.
- Delete or archive project with appropriate safeguards.
- Project details.
- Project settings.
- Project workspace.
- Project knowledge.
- Project readiness validation.

## Repository management

- Add local Git repository.
- Add remote Git repository.
- Remove repository.
- Edit repository configuration.
- Inspect repository.
- Detect language and framework.
- Detect branches.
- Validate access.
- Configure build and test commands.

## Multi-repository support

Support projects containing:

- Backend repositories.
- Frontend repositories.
- Mobile repositories.
- Shared libraries.
- Infrastructure repositories.
- Documentation repositories.

Tasks must be able to target one or multiple repositories.

## Acceptance criteria

A user must be able to create a project and connect multiple repositories entirely through the dashboard.

Repository access, project relationships, and dependencies must be validated by the backend.

---

# 7. Phase 4 — Configuration Center

**Objective:** Eliminate manual configuration-file editing as a requirement for ordinary users.

Implement dashboard interfaces for:

1. Global Sentinel settings.
2. Runtime settings.
3. Project settings.
4. Repository settings.
5. AI providers.
6. Agent registry.
7. Agent assignments.
8. Workflow templates.
9. Execution policies.
10. TDD settings.
11. Verification settings.
12. Build and test commands.
13. Knowledge sources.
14. Git conventions.
15. Artifact storage.
16. Notifications.
17. Permissions.

## Configuration requirements

Every configuration must support appropriate:

- Create.
- Read.
- Update.
- Delete.
- Validate.
- Preview.
- Save.
- Version history.
- Audit history.
- Rollback where supported.

Use configuration scopes:

- Global.
- Project.
- Repository.
- Task.

Define explicit precedence and inheritance rules.

Sensitive credentials must be encrypted or stored through a secure secret-management mechanism. Never return secret values to the frontend.

Support advanced import/export and effective-configuration inspection.

## Project readiness

Implement a readiness check that evaluates the actual requirements of the selected workflow.

A project can be:

- Ready.
- Ready with warnings.
- Needs configuration.
- Invalid.
- Runtime unavailable.

Do not require optional components that a particular task does not need.

## Acceptance criteria

A new user can configure a project, provider, agent assignments, workflows, and validation commands without manually editing configuration files.

---

# 8. Phase 5 — Deterministic Orchestration and Agent Runtime

**Objective:** Upgrade the core Sentinel execution engine.

This is the central engineering capability of Sentinel.

## 8.1 Deterministic orchestration

Implement:

- Explicit task lifecycle.
- Workflow state machine.
- State transition validation.
- Preconditions and postconditions.
- Execution dependencies.
- Retry and timeout policies.
- Failure handling.
- Recovery.
- Human intervention.
- Event history.
- Persistent execution state.

Suggested lifecycle:

```text
CREATED
   |
   v
TRIAGED
   |
   v
PLANNING
   |
   v
SPECIFICATION_REVIEW
   |
   v
GHERKIN_REVIEW
   |
   v
READY
   |
   v
EXECUTING
   |
   v
VERIFYING
   |
   v
REVIEWING
   |
   v
COMPLETED
   |
   v
ACCEPTED
```

Additional states:

- BLOCKED
- NEEDS_HUMAN
- FAILED
- CANCELLED

Execution completion, verification, and human acceptance must remain separate.

Only the deterministic engine can authorize state transitions.

## 8.2 Provider-neutral subagent runtime

Implement a common agent invocation contract.

Support:

- Provider adapters.
- Model selection.
- Agent role selection.
- Native subagent delegation where available.
- External agent execution.
- Structured inputs and outputs.
- Execution events.
- Artifact references.
- Timeout and retry.
- Cancellation where supported.
- Capability discovery.

Do not assume all providers support identical capabilities.

## Acceptance criteria

The same orchestration interface can execute agents through different providers without changing workflow logic.

---

# 9. Phase 6 — Human Approval and TDD Engine

**Objective:** Enforce the engineering workflow before implementation.

## 9.1 Specification approval

The agent generates a specification.

The user can:

- Review.
- Edit.
- Comment.
- Request changes.
- Reject.
- Approve.

Approval must record:

- Reviewer.
- Exact version.
- Content hash.
- Decision.
- Timestamp.
- Comments.

No coding can begin before approval.

## 9.2 Gherkin approval

Generate Gherkin features and scenarios, tagged to:

- Requirements.
- Acceptance criteria.
- Positive cases.
- Negative cases.
- Edge cases.
- Security cases.
- Regression cases.

The user must approve the Gherkin scenarios before implementation.

Material changes invalidate previous approval.

## 9.3 TDD execution

Enforce:

```text
RED → GREEN → REFACTOR
```

Red must prove the expected behavior fails for the intended reason.

Green must demonstrate that the implementation satisfies the approved test.

Refactor must preserve passing tests.

Store:

- Test IDs.
- Requirement IDs.
- Commands.
- Outputs.
- Changed files.
- Execution history.
- Agent and provider.
- Timestamps.
- Evidence.

Agents cannot silently modify approved tests.

## Acceptance criteria

No implementation starts without both approvals, and each TDD cycle produces verifiable evidence.

---

# 10. Phase 7 — Dashboard Integration

**Objective:** Expose the completed platform capabilities through the dashboard.

Implement:

- Overview.
- Installation setup.
- Projects.
- Repository management.
- Configuration center.
- Tasks.
- Approval center.
- Workflow visualization.
- Agent monitoring.
- Provider monitoring.
- TDD monitoring.
- Verification center.
- Code changes and Git diffs.
- Artifacts.
- Notifications.
- Reports.
- Users and permissions.

The dashboard must use existing backend services and approved API contracts.

Do not duplicate business logic in frontend components.

Use real backend data for core functionality. Mock data may only be used in isolated UI development and tests.

Support live updates with SSE or an appropriate event mechanism, including reconnect and state refresh.

## Acceptance criteria

A user can complete the full workflow through the dashboard:

```text
Connect Sentinel
      |
      v
Create Project
      |
      v
Add Repositories
      |
      v
Configure Environment
      |
      v
Validate Readiness
      |
      v
Create Task
      |
      v
Approve Specification
      |
      v
Approve Gherkin
      |
      v
Monitor TDD Execution
      |
      v
Review Verification
      |
      v
Accept Result
```

---

# 11. Phase 8 — Verification, Traceability, and Git

**Objective:** Establish trustworthy evidence for engineering results.

Implement:

- Unit test reporting.
- Integration test reporting.
- Regression reporting.
- Build verification.
- Lint and type checking.
- Security verification.
- API contract verification.
- Database migration verification.
- Code review findings.
- QA results.

Maintain traceability:

```text
Requirement
    |
    v
Acceptance Criterion
    |
    v
Approved Test Scenario
    |
    v
TDD Cycle
    |
    v
Changed Files
    |
    v
Verification Evidence
    |
    v
Human Acceptance
```

Support:

- Repository and branch information.
- Base commit.
- Changed files.
- Inline diff.
- Side-by-side diff.
- Commit history.
- Pull request references where supported.

Verification must be based on independent evidence, not agent claims.

---

# 12. Phase 9 — Analytics, Security, and Production Readiness

**Objective:** Complete the operational capabilities.

Implement:

- Execution analytics.
- Quality analytics.
- Cost analytics.
- Provider comparisons.
- Notifications.
- RBAC.
- Audit history.
- Secret protection.
- Artifact access control.
- Runtime security.
- Error handling.
- Logging.
- Monitoring.
- Backup and recovery.
- Documentation.

Do not fabricate unavailable metrics.

Do not weaken quality requirements to improve reported performance.

---

# 13. Development Methodology

All implementation must follow a controlled engineering process.

## 13.1 Contract-first

Before implementing a module:

1. Define its responsibilities.
2. Define its API contract.
3. Define its data model.
4. Define its events.
5. Define its permissions.
6. Define its acceptance criteria.
7. Define its test plan.
8. Obtain required human approval.

## 13.2 TDD

For implementation tasks:

1. Write approved tests.
2. Run tests and prove the expected failure.
3. Implement the minimum solution.
4. Run tests and prove success.
5. Refactor.
6. Run regression tests.
7. Record evidence.

## 13.3 Code quality

- Follow existing project conventions where appropriate.
- Avoid unnecessary architectural rewrites.
- Avoid duplicate implementations.
- Avoid excessive comments.
- Prefer clear naming.
- Keep modules independently testable.
- Maintain CLI compatibility.
- Do not introduce unnecessary dependencies.

## 13.4 Regression

Every completed phase must run its relevant regression suite.

Existing working features must not be broken by the upgrade.

---

# 14. Human Approval Gates

The implementation must stop at the following gates.

| Gate | Required deliverable | Approval |
|---|---|---|
| G0 | Gap analysis | Human |
| G1 | Unified specification | Human |
| G2 | Architecture and contracts | Human |
| G3 | Installation and project design | Human |
| G4 | Configuration design | Human |
| G5 | Orchestration and runtime design | Human |
| G6 | Approval and TDD design | Human |
| G7 | Dashboard integration design | Human |
| G8 | Verification and security design | Human |
| G9 | Final acceptance | Human |

For individual engineering tasks, specification and Gherkin approval remain mandatory.

The agent must not interpret approval of this implementation plan as approval to bypass future design or task-level approval gates.

---

# 15. Implementation Tracking

Create and maintain:

`IMPLEMENTATION_STATUS.md`

Track every phase and task.

Suggested structure:

| ID | Phase | Task | Status | Dependencies | Evidence |
|---|---|---|---|---|---|
| P0-01 | Discovery | Inspect architecture | Pending | None | |
| P0-02 | Discovery | Gap analysis | Pending | P0-01 | |
| P1-01 | Architecture | Unified SPEC.md | Pending | P0 | |
| P2-01 | Runtime | Installation connection | Pending | P1 | |
| P3-01 | Projects | Project management | Pending | P2 | |
| P4-01 | Config | Configuration center | Pending | P3 | |
| P5-01 | Core | Deterministic orchestration | Pending | P1 | |
| P5-02 | Core | Agent runtime | Pending | P5-01 | |
| P6-01 | TDD | Approval and TDD engine | Pending | P5 | |
| P7-01 | Dashboard | Dashboard integration | Pending | P2-P6 | |
| P8-01 | Quality | Verification and traceability | Pending | P6-P7 | |
| P9-01 | Release | Production readiness | Pending | P8 | |

Statuses:

- Pending
- In Progress
- Blocked
- Needs Approval
- Completed
- Failed

The tracking file must reflect actual implementation and test evidence, not optimistic agent estimates.

---

# 16. Required Repository Structure

The agent should adapt this structure to the existing project rather than forcing an unnecessary restructure.

```text
sentinel/
├── SPEC.md
├── IMPLEMENTATION_PLAN.md
├── IMPLEMENTATION_STATUS.md
├── agent.md
│
├── docs/
│   ├── architecture/
│   ├── modules/
│   ├── contracts/
│   ├── implementation/
│   └── decisions/
│
├── backend/
├── dashboard/
├── runtime/
├── agents/
├── workflows/
├── policies/
├── tests/
├── artifacts/
└── scripts/
```

Do not move or rename existing components without understanding their dependencies.

---

# 17. Agent Execution Instructions

The implementation agent must follow these instructions.

## First execution

Do not immediately start coding.

First:

1. Locate both source specifications.
2. Read both completely.
3. Inspect the Sentinel repository.
4. Perform the gap analysis.
5. Identify conflicts and missing requirements.
6. Map existing capabilities to the target architecture.
7. Produce the unified `SPEC.md`.
8. Produce the architecture and contract documents.
9. Produce the implementation roadmap.
10. Present findings and request human approval.

## After approval

Implement one phase at a time.

For each phase:

1. Review requirements.
2. Define module contracts.
3. Create or update the Gherkin scenarios.
4. Request required human approval.
5. Implement using TDD.
6. Run regression tests.
7. Verify security and permissions.
8. Record evidence.
9. Update implementation status.
10. Present results for human review.

Do not mark a phase completed merely because code has been written.

A phase is complete only when its acceptance criteria pass and the required evidence exists.

## Failure handling

If blocked:

- Stop dependent implementation.
- Record the blocker.
- Explain the root cause.
- Identify affected requirements.
- Propose a resolution.
- Request human input when a decision is required.

Do not silently change approved architecture, requirements, tests, or policies.

---

# 18. Final Definition of Done

The unified Sentinel upgrade is complete when:

- A new user can connect a Sentinel installation.
- Projects can be created through the dashboard.
- Multiple repositories can belong to a project.
- Configuration can be managed through the dashboard.
- Providers and agents are replaceable.
- Agent execution is provider-neutral.
- Orchestration is deterministic.
- Workflow transitions are validated.
- Specification approval is mandatory.
- Gherkin approval is mandatory.
- TDD follows Red-Green-Refactor.
- Verification is independent and evidence-based.
- Tasks and execution history persist.
- Workflow and agent execution are observable.
- Requirements are traceable to code and verification.
- Git changes can be inspected.
- Permissions and audit history are enforced.
- Existing CLI workflows remain compatible.
- Regression tests pass.
- Documentation is updated.
- All required acceptance criteria are verified.

---

# 19. Final Engineering Principle

Do not build Sentinel as a dashboard with AI features attached.

Build Sentinel as a deterministic engineering platform with replaceable AI agents and a dashboard that provides complete human control and visibility.

**The architecture must outlive individual AI providers, models, agents, dashboards, and machines.**

The user owns the requirements and approvals. Sentinel owns orchestration, execution policy, and verification. AI agents perform assigned engineering work. Evidence establishes whether the result can be trusted.