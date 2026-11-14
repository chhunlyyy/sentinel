# Sentinel Upgrade Specification
## Deterministic AI Engineering Orchestration, Cross-Provider Subagents & Human-Gated TDD

**Document Type:** Master Engineering Upgrade Specification  
**Project:** Sentinel  
**Priority:** Critical  
**Implementation Approach:** Incremental evolution of the existing codebase  
**Primary Objective:** Transform Sentinel into a deterministic AI engineering orchestration and verification platform with intelligent, provider-independent agent execution and human-approved TDD workflows.

---

# 1. Mission

Upgrade Sentinel from an AI agent workflow system into a deterministic engineering orchestration platform.

Sentinel must provide:

1. Intelligent workflow planning.
2. Provider-independent subagent execution.
3. Deterministic task orchestration and state management.
4. Human-approved specifications and Gherkin scenarios.
5. TDD-first software development.
6. Independent verification and regression testing.
7. Persistent execution history and evidence.
8. Cross-project and cross-machine portability.

Sentinel must support different AI providers without making its orchestration logic dependent on a particular provider's capabilities.

## Core architectural principle

**Sentinel is the control plane. Agents are execution workers.**

Sentinel controls:
- Workflow selection and execution.
- Task creation and scheduling.
- Agent selection and provider routing.
- Permissions and write scopes.
- State transitions.
- Human approval gates.
- TDD enforcement.
- Verification and acceptance.
- Recovery and audit history.

Agents are responsible for:
- Understanding assigned tasks.
- Producing plans and recommendations.
- Writing tests and implementation code within their assigned permissions.
- Reviewing and analyzing changes.
- Returning structured results and evidence.

No agent may authorize its own work, bypass approval requirements, or independently declare a workflow successful.

---

# 2. Required Architectural Principles

The upgraded Sentinel must follow these principles.

### 2.1 Deterministic orchestration

AI agents can recommend actions and workflow changes, but Sentinel must validate and authorize all actions.

Workflow execution must be controlled by explicit state transitions and policy rules.

### 2.2 Provider independence

Workflow definitions must not contain provider-specific execution logic.

Claude, Codex, Gemini, local models, and future providers must be usable through adapters implementing a common interface.

### 2.3 Human-controlled requirements

Humans must approve the specification and Gherkin scenarios before autonomous implementation begins.

The human must be able to inspect, edit, reject, or request changes to either artifact.

### 2.4 TDD-first implementation

All applicable software coding tasks must follow:

**Red → Green → Refactor**

Each cycle must produce independently verifiable evidence.

### 2.5 Least-privilege execution

Every agent must receive only the permissions required for its assigned task.

### 2.6 Traceability

Every implementation must be traceable to:
- Original user request.
- Approved specification.
- Approved Gherkin scenarios.
- Agent tasks.
- TDD cycles.
- Verification results.
- Final Git commit.

### 2.7 Incremental implementation

Do not rewrite Sentinel from scratch.

Inspect the existing codebase, identify reusable components, and evolve the current architecture while preserving working functionality.

---

# 3. Target Architecture

Organize the architecture around the following logical modules. Adapt names and locations to the existing repository conventions.

```text
sentinel/
├── core/
│   ├── orchestration/
│   ├── task_graph/
│   ├── scheduler/
│   ├── state_machine/
│   ├── policy/
│   ├── permissions/
│   ├── recovery/
│   └── events/
│
├── intelligence/
│   ├── task_classifier/
│   ├── workflow_planner/
│   ├── dependency_analyzer/
│   └── risk_analyzer/
│
├── agents/
│   ├── contracts/
│   ├── registry/
│   ├── dispatcher/
│   ├── planner/
│   ├── architect/
│   ├── specifier/
│   ├── test_designer/
│   ├── tdd_red/
│   ├── tdd_green/
│   ├── tdd_refactor/
│   ├── reviewer/
│   ├── hardener/
│   └── qa/
│
├── providers/
│   ├── base/
│   ├── claude/
│   ├── codex/
│   ├── gemini/
│   ├── local/
│   └── a2a/
│
├── workflows/
│   ├── bug_fix/
│   ├── feature/
│   ├── api/
│   ├── fullstack/
│   ├── security_change/
│   └── documentation/
│
├── verification/
│   ├── tdd/
│   ├── tests/
│   ├── regression/
│   ├── mutation/
│   ├── security/
│   ├── diff/
│   └── evidence/
│
├── storage/
│   ├── run_registry/
│   ├── artifacts/
│   ├── events/
│   └── knowledge/
│
└── reporting/
    ├── execution/
    ├── quality/
    └── cost/
```

This is a target architecture, not an instruction to create empty directories. Implement actual functionality and extract modules incrementally.

---

# 4. Human-in-the-Loop Approval Architecture

This is a mandatory feature.

Sentinel must have two required human approval gates before autonomous coding starts.

## 4.1 Gate 1: Specification approval

Workflow:

1. User submits a natural-language request.
2. Sentinel inspects the repository and relevant project context.
3. Planner and Architect analyze the request.
4. Specifier produces a structured specification.
5. Sentinel validates the specification against its schema and completeness rules.
6. Sentinel presents the specification to the human.
7. Human reviews and chooses:
   - Approve.
   - Request changes.
   - Reject.
8. If changes are requested, the Specifier revises the document.
9. The revised specification must be reviewed again.
10. Only an approved specification can advance to Gherkin design.

The specification must contain:

- Problem statement.
- Objectives.
- Scope.
- Out-of-scope items.
- Functional requirements.
- Non-functional requirements.
- Acceptance criteria.
- Business rules.
- Edge cases.
- Validation rules.
- Security considerations.
- API or interface changes.
- Database changes, if applicable.
- Dependencies.
- Risks and assumptions.
- Expected deliverables.

### Approval rules

- Approval must be an explicit human action.
- Agent-generated approval is prohibited.
- An approval must reference a specific specification version and content hash.
- Any material change after approval invalidates the approval.
- A revised specification must go through the approval gate again.
- Sentinel must persist approval identity, timestamp, version, and decision.

## 4.2 Gate 2: Gherkin scenario approval

This gate occurs only after specification approval. The reviewed artifact is a set of Gherkin `.feature` files, not a free-form test matrix.

Workflow:

1. Test Designer reads the approved specification.
2. Test Designer inspects the existing code and test architecture.
3. Test Designer writes Gherkin features and scenarios (Given / When / Then) covering the approved behavior.
4. Sentinel validates Gherkin syntax and traceability (tags to requirement and acceptance criterion IDs).
5. Sentinel presents the Gherkin scenarios to the human.
6. Human reviews the scenarios and coverage.
7. Human can:
   - Approve.
   - Request additional scenarios.
   - Request scenario modifications.
   - Reject.
8. Test Designer revises the Gherkin when necessary.
9. Revised Gherkin must be reviewed again.
10. Only approved Gherkin can authorize the Red phase.

Gherkin requirements:

- One `Feature` per behavior group, with a business-readable description.
- Each `Scenario` or `Scenario Outline` carries tags: `@REQ-<id>`, `@AC-<id>`, test type, and priority (for example `@P1`).
- Steps use declarative business language, not implementation details.
- `Background` only for shared preconditions.
- `Scenario Outline` with `Examples` tables for boundary and invalid-input data.
- Expected errors and authorization outcomes are explicit `Then` steps.
- Regression considerations are tagged `@regression`.
- Every acceptance criterion maps to at least one scenario.

### Required coverage categories

Consider applicable categories for every feature:

1. Happy paths.
2. Invalid input.
3. Missing required fields.
4. Boundary conditions.
5. Empty and null values.
6. Authentication.
7. Authorization.
8. Data integrity.
9. Duplicate submissions.
10. Concurrency.
11. Error handling.
12. External service failures.
13. Database failures.
14. Regression scenarios.
15. Performance and security where relevant.

Sentinel must not claim complete coverage simply because every requirement has one scenario. Coverage must be evaluated against relevant scenarios and risk.

### Red phase binding

- The TDD Red agent implements automated tests (step definitions or equivalent project-native tests) that execute the approved scenarios.
- Each automated test must reference its scenario by feature path and scenario name or ID.
- The Red agent cannot add, remove, or reword approved scenarios.

### Approval rules

- Human approval must be explicit.
- Approval must reference the Gherkin version and content hash (hash over all approved `.feature` files).
- Changed Gherkin invalidates its previous approval.
- Adding, removing, or materially modifying approved scenarios requires renewed human approval.
- Test execution must use the approved Gherkin.
- Agents cannot approve their own Gherkin.

---

## 4.3 Autonomous execution after approval

Once both gates are approved:

**The normal coding workflow must not require additional human intervention between Red, Green, Refactor, and routine verification.**

Sentinel should execute autonomously:

- Test creation.
- Test execution.
- Implementation.
- Refactoring.
- Test reruns.
- Regression verification.
- Code review.
- QA.
- Failure routing.
- Recovery.

However, human approval must still be required when policy demands it, including:

- High-risk security or authorization changes.
- Destructive database operations.
- Production deployment.
- Publishing shared artifacts or knowledge.
- Changes to the approved specification.
- Changes to the approved acceptance criteria or Gherkin scenarios.
- Unresolvable policy violations.
- Explicitly configured approval requirements.

The removal of humans from the routine implementation loop must not remove human control over requirements, scope, and high-impact actions.

## 4.4 Approval state model

```text
SPECIFICATION_DRAFT
    ↓
SPECIFICATION_REVIEW
    ├── CHANGES_REQUESTED → SPECIFICATION_DRAFT
    ├── REJECTED → TERMINATED
    └── APPROVED
            ↓
GHERKIN_DRAFT
    ↓
GHERKIN_REVIEW
    ├── CHANGES_REQUESTED → GHERKIN_DRAFT
    ├── REJECTED → TERMINATED
    └── APPROVED
            ↓
AUTONOMOUS_EXECUTION
```

Persist approval decisions and revisions. Never use an agent's conversational statement as proof of approval.

---

# 5. Provider-Neutral Subagent System

Replace the assumption that an agent is merely a background script with a managed logical subagent system.

The system must support:

1. Native provider subagents.
2. CLI-based agents.
3. API-based agents.
4. Remote agents through an interoperability adapter.

## 5.1 Common agent task contract

Every agent receives a standardized task.

Example:

```yaml
task:
  id: task-001
  run_id: run-001
  role: tdd_green
  objective: Implement the approved leave balance behavior

  provider:
    name: codex
    model: configured-default

  input:
    specification_ref: spec-001
    gherkin_ref: gherkin-001
    context:
      - backend/src/main
      - backend/src/test

  permissions:
    read:
      - backend/**
    write:
      - backend/src/main/**

  constraints:
    must_follow_tdd: true
    max_retries: 2

  expected_output:
    schema: agent-result-v1
```

The contract must support:
- Task identity.
- Run identity.
- Agent role.
- Objective.
- Input references.
- Repository context.
- Provider configuration.
- Permissions.
- Constraints.
- Timeouts.
- Retry policies.
- Expected output schema.

## 5.2 Provider adapter interface

Define a provider-neutral interface with capabilities equivalent to:

```python
class AgentProvider:
    def capabilities(self):
        ...

    def submit(self, task):
        ...

    def start(self, task_id):
        ...

    def status(self, task_id):
        ...

    def result(self, task_id):
        ...

    def cancel(self, task_id):
        ...

    def resume(self, task_id):
        ...
```

This is illustrative. Adapt it to the existing language and architecture.

Provider-specific behavior must remain inside adapters.

## 5.3 Managed task lifecycle

```text
CREATED
  ↓
QUEUED
  ↓
RUNNING
  ├── WAITING_FOR_INPUT
  ├── BLOCKED
  ├── FAILED
  ├── CANCELLED
  └── COMPLETED
```

Sentinel must manage:
- Task lifecycle.
- Timeouts.
- Retries.
- Cancellation.
- Result validation.
- Artifact collection.
- Provider failures.
- Session recovery.
- Resource usage.

Do not assume every provider supports session resumption. The adapter must report its actual capabilities.

## 5.4 Delegation rules

- The orchestrator can create subagent tasks.
- Sentinel validates and schedules each task.
- Agents cannot expand their own permissions.
- Agents cannot authorize other agents.
- Agents cannot modify workflow state directly.
- Nested delegation is disabled initially.
- Parallel execution requires conflict and dependency checks.
- Tasks modifying overlapping files must not run concurrently without an explicit safe coordination strategy.

Implement native subagent support where available and CLI/API fallbacks for providers without native delegation.

A2A interoperability can be added through an adapter after the internal task contract is stable.

---

# 6. TDD-First Development Engine

All applicable software coding workflows must follow Red-Green-Refactor.

The development loop is repeated for each behavior or meaningful test group.

## 6.1 RED phase

Responsible agent: TDD Red Agent.

Responsibilities:

- Read the approved specification.
- Read the approved Gherkin scenarios.
- Create tests for the assigned behavior.
- Follow existing project test conventions.
- Avoid production code changes.
- Execute the targeted tests.
- Prove that the intended behavior fails.

The failure must be caused by the expected assertion or missing behavior.

Invalid Red outcomes include:
- Compilation failures.
- Missing dependencies.
- Broken database configuration.
- Environment failures.
- Unrelated pre-existing test failures.

Sentinel must classify failures before accepting the Red phase.

Red must not proceed to Green without verified expected failure evidence.

## 6.2 GREEN phase

Responsible agent: TDD Green Agent.

Responsibilities:

- Implement the minimum production code needed to satisfy the approved tests.
- Preserve approved tests.
- Avoid unrelated refactoring.
- Avoid changing acceptance criteria.
- Run targeted tests.
- Return changed-file information and test evidence.

Sentinel must reject unauthorized modifications to approved test files.

Green must pass before Refactor begins.

## 6.3 REFACTOR phase

Responsible agent: TDD Refactor Agent.

Responsibilities:

- Improve code structure.
- Reduce duplication.
- Improve naming.
- Improve maintainability.
- Preserve behavior.
- Avoid introducing unrelated functionality.

Run relevant tests after every refactor.

If tests fail, reject the refactor and route the failure for correction.

## 6.4 Repeat the cycle

Repeat Red → Green → Refactor until all approved behaviors are implemented.

Do not force an artificial single-cycle implementation for a large feature.

## 6.5 TDD evidence

Every cycle must create a persistent record.

Example:

```yaml
cycle:
  id: cycle-001
  behavior_id: LEAVE-API-003
  state: VERIFIED

  red:
    task_id: task-red-001
    test_files:
      - src/test/java/LeaveControllerTest.java
    command: ./gradlew test --tests LeaveControllerTest
    exit_code: 1
    failure_type: assertion
    expected_failure_confirmed: true

  green:
    task_id: task-green-001
    changed_files:
      - src/main/java/LeaveController.java
    tests_passed: true

  refactor:
    task_id: task-refactor-001
    changed_files:
      - src/main/java/LeaveController.java
    tests_passed: true

  verification:
    accepted: true
    evidence_id: evidence-001
```

Capture actual command output, timestamps, test counts, commit or working-tree references, and environment metadata where available.

Never fabricate evidence from an agent's response.

## 6.6 TDD permissions

| Role | Test files | Production files |
|---|---|---|
| Test Designer | Read/write | Read |
| TDD Red | Read/write within approved test scope | Read |
| TDD Green | Read-only by default | Read/write within scope |
| TDD Refactor | Read-only by default | Read/write within scope |
| Reviewer | Read | Read |
| QA | Read | Read |

Any exception must require explicit Sentinel authorization and be recorded.

A Gherkin change must return to human review.

---

# 7. Workflow Intelligence and Tier Integration

Preserve the existing Sentinel tier system.

Tiers determine workflow rigor. TDD determines the coding method.

| Tier | Expected workflow |
|---|---|
| Tier 1 | Lightweight specification and test approval, small TDD cycle, basic verification |
| Tier 2 | Bug reproduction, approved Gherkin scenarios, TDD, targeted regression |
| Tier 3 | Full specification, comprehensive Gherkin suite, multiple TDD cycles, independent review and QA |
| Tier 4 | Full specification, security analysis, complete TDD, extensive regression, human approval and controlled release |

Documentation-only tasks should not generate unnecessary code tests.

Bug fixes should create permanent regression tests.

Features should derive tests from approved acceptance criteria.

Task classification can use AI, but Sentinel must validate the selected workflow against deterministic policies.

---

# 8. Verification and Acceptance Engine

Implement an independent verification layer.

Required checks where applicable:

- Targeted unit tests.
- Integration tests.
- Full relevant test suite.
- Regression tests.
- Build.
- Lint.
- Type checking.
- Security checks.
- Database migration validation.
- API contract validation.
- Diff and scope validation.
- Mutation testing where appropriate.

Verification must run independently of implementation agents.

An agent saying "all tests passed" is not sufficient.

Sentinel must execute or independently validate the required commands and collect evidence.

## Acceptance rules

A run cannot be accepted if:

- Specification approval is missing.
- Gherkin approval is missing.
- Required TDD cycles are incomplete.
- Required tests fail.
- Required verification evidence is missing.
- Changes exceed authorized scope.
- Required reviews are incomplete.
- Required human approvals are missing.

Separate these statuses:

- `execution_status`: whether execution terminated.
- `acceptance_status`: whether the engineering work passed its acceptance criteria.

A completed run may have a failed acceptance status.

---

# 9. State Machine

Implement deterministic state machines for runs, tasks, approvals, and TDD cycles.

## Run states

```text
CREATED
TRIAGED
PLANNED
SPECIFICATION_REVIEW
SPECIFICATION_APPROVED
GHERKIN_REVIEW
GHERKIN_APPROVED
EXECUTING
VERIFYING
REVIEWING
NEEDS_HUMAN
ACCEPTED
COMPLETED
FAILED
CANCELLED
BLOCKED
```

## TDD states

```text
PLANNED
RED_RUNNING
RED_VERIFIED
GREEN_RUNNING
GREEN_VERIFIED
REFACTOR_RUNNING
REFACTOR_VERIFIED
CYCLE_ACCEPTED
```

Each transition must define:

- Current state.
- Target state.
- Preconditions.
- Authorized actor.
- Required evidence.
- Policy validation.
- Failure handling.

Invalid transitions must be rejected.

---

# 10. Persistence and Portability

Sentinel must work across projects and machines.

Use appropriate storage abstractions.

Initial recommendations:

- SQLite for local run registry.
- Git for workflow definitions, specifications, and reusable engineering knowledge.
- Local artifact storage for the first implementation.
- MinIO/S3-compatible artifact storage as a future option.
- PostgreSQL for future multi-user centralized execution.

Persist:

- Run ID.
- Task IDs.
- Workflow version.
- Configuration version.
- Repository commit SHA.
- Agent role.
- Provider and model.
- Task inputs and outputs.
- Approval decisions and content hashes.
- Specification and Gherkin versions.
- TDD cycle evidence.
- Verification results.
- Review findings.
- Execution duration.
- Cost and token usage when available.
- Final commit SHA.

A resumed run must use persisted data, not conversation history as its source of truth.

---

# 11. Security and Reliability

Implement:

- Enforced write scopes.
- Least-privilege agent permissions.
- Command execution policies.
- Task timeouts.
- Retry limits.
- Cancellation.
- Locking and concurrency control.
- Provider failure handling.
- Secret redaction.
- Artifact integrity checks.
- Approval audit history.
- Safe Git operations.
- Explicit publishing authorization.

Set automatic shared publishing to disabled by default.

Never allow an agent to execute an unrestricted shell command simply because its provider supports it.

---

# 12. Reporting

Every run should generate:

1. Execution report.
2. Approved specification.
3. Approved Gherkin scenarios.
4. Agent execution history.
5. TDD cycle report.
6. Verification report.
7. Regression report.
8. Review findings.
9. Changed-file summary.
10. Final acceptance report.
11. Cost and duration report, when available.

Provide both:
- Machine-readable JSON artifacts.
- Human-readable Markdown reports.

Do not make a dashboard a prerequisite for these capabilities.

---

# 13. Implementation Roadmap

Implement incrementally in the following order.

## Phase 1: Deterministic Core

- Inspect and document the existing architecture.
- Define run, task, result, approval, and evidence schemas.
- Implement state transition validation.
- Implement task graph and dependency management.
- Enforce write scopes.
- Separate execution and acceptance statuses.
- Disable automatic shared publishing by default.
- Add orchestration integration tests.

Exit criteria: Sentinel controls workflow state and rejects unauthorized transitions and modifications.

## Phase 2: Human Approval Gates

- Implement specification generation and validation.
- Implement specification review and approval.
- Implement Gherkin generation and validation.
- Implement human review and approval of the Gherkin.
- Persist versioned approval decisions.
- Invalidate approvals after material changes.
- Block autonomous coding until both approvals exist.

Exit criteria: No coding task can begin without valid human approvals for both the specification and Gherkin scenarios.

## Phase 3: Provider-Neutral Subagents

- Define the common agent task contract.
- Implement provider registry and adapters.
- Implement managed task lifecycle.
- Implement one native-subagent adapter.
- Implement one independent CLI adapter.
- Implement timeouts, retries, cancellation, and structured results.
- Add adapter compatibility tests.

Exit criteria: The same workflow can delegate to two different providers without changing its workflow definition.

## Phase 4: TDD Engine

- Implement Test Designer.
- Implement TDD Red Agent.
- Implement TDD Green Agent.
- Implement TDD Refactor Agent.
- Implement Red failure classification.
- Implement phase-specific permissions.
- Implement cycle evidence.
- Integrate TDD with all applicable tiers.

Exit criteria: Sentinel enforces approved Gherkin scenarios and verified Red-Green-Refactor cycles.

## Phase 5: Verification and Recovery

- Independent verification.
- Regression integration.
- Security checks.
- Review and QA.
- Persistent run registry.
- Cross-machine resume.
- Artifact storage abstraction.

Exit criteria: Interrupted workflows resume from persisted execution state and retain evidence.

## Phase 6: Workflow Intelligence

- Repository understanding.
- Dependency analysis.
- Intelligent workflow planning.
- Risk analysis.
- Dynamic provider/model selection.
- Safe parallel execution.
- Cross-project knowledge reuse.

Exit criteria: Sentinel converts a natural-language request into an explainable, policy-validated execution plan.

## Phase 7: Team Platform

- Central dashboard.
- Provider and agent analytics.
- Cost and quality analytics.
- Shared workflow templates.
- Remote agent registry.
- A2A integration.
- CI/CD integration.

Exit criteria: Multiple projects and developers can use shared orchestration infrastructure.

---

# 14. Mandatory Acceptance Tests

The upgrade is not complete until these scenarios are tested.

| Scenario | Expected behavior |
|---|---|
| User submits a feature request | Sentinel generates a specification |
| Specification has not been approved | Coding is blocked |
| Human requests specification changes | Specifier revises it |
| Approved specification changes | Approval is invalidated |
| Gherkin has not been approved | Red phase is blocked |
| Human finds missing edge cases | Test Designer updates Gherkin |
| Approved Gherkin changes | Gherkin approval is invalidated |
| Both approvals are valid | Autonomous execution begins |
| Red produces expected assertion failure | Red is accepted |
| Red fails due to environment | Red is rejected |
| Green modifies approved tests | Unauthorized modification is rejected |
| Green passes | Refactor can begin |
| Refactor breaks tests | Refactor is rejected |
| More behaviors remain | Another TDD cycle begins |
| All cycles pass | Independent verification begins |
| Provider is unavailable | Configured failure or fallback policy applies |
| Agent exceeds write scope | Modification is blocked |
| Agent claims tests passed without evidence | Sentinel independently executes checks |
| Process is interrupted | Sentinel resumes from persisted state |
| Two tasks modify overlapping files | Unsafe concurrent execution is prevented |
| Security gate requires human approval | Workflow pauses |
| Agent attempts to approve its own work | Approval is rejected |
| Publishing is attempted without authorization | Publishing is blocked |

---

# 15. Instructions to the Implementing Agent

Before writing implementation code:

1. Inspect the entire existing Sentinel repository.
2. Read the current README, architecture documents, agent skills, workflow definitions, provider adapters, tests, and storage implementation.
3. Identify what already exists and what is missing.
4. Produce a gap analysis mapping current components to this specification.
5. Identify backward-compatibility risks.
6. Propose an incremental implementation plan.
7. Identify the first implementation milestone and its tests.

Do not immediately rewrite the repository.

During implementation:

- Follow contract-first development.
- Use Sentinel's own human-approved specification and Gherkin gates.
- Apply TDD to applicable code changes.
- Keep changes small and independently testable.
- Preserve existing working workflows.
- Add migration and compatibility support where necessary.
- Do not create unused abstractions or empty modules.
- Do not claim a feature is complete without verification evidence.
- Update documentation alongside implementation.
- Keep provider-specific logic outside the orchestration core.

For this upgrade, the implementing agent must not bypass the new human approval requirements. It should first prepare the implementation specification and Gherkin scenarios for human approval before beginning the coding work.

## Final Definition of Done

Sentinel is considered upgraded when:

1. It deterministically controls its workflows.
2. It can manage subagents across different AI providers through a common contract.
3. Humans approve specifications before Gherkin design proceeds.
4. Humans approve Gherkin scenarios before Red begins.
5. Routine implementation after approval is autonomous.
6. Applicable coding tasks follow enforced Red-Green-Refactor cycles.
7. Every phase produces verifiable evidence.
8. Independent verification controls acceptance.
9. Run state and artifacts are persistent and portable.
10. Security, permissions, recovery, and approval policies are enforced.

**Final product principle:**

Sentinel understands engineering work, coordinates specialized AI agents, enforces human-approved requirements, drives TDD development, and independently verifies the resulting software.

**AI agents do the engineering. Humans approve what should be built and tested. Sentinel controls how the work is executed and whether the result is trustworthy.**