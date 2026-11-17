# SENTINEL DASHBOARD
## Updated Product & Engineering Specification

**Document status:** Consolidated specification  
**Update:** First-Run Setup, Project Creation, Repository Management, and Dashboard-Based Configuration

---

## 1. Product Vision

The Sentinel Dashboard is the human command center for AI-driven software engineering.

A new user should be able to:

1. Install Sentinel.
2. Open the Sentinel Dashboard.
3. Connect the dashboard to their Sentinel installation.
4. Create a project.
5. Add one or more repositories.
6. Configure the project and engineering environment through the dashboard.
7. Validate the configuration.
8. Create their first task and start working immediately.

**The goal is to eliminate manual configuration-file editing as a requirement for normal onboarding and everyday project management.**

The dashboard is the presentation and management layer. Sentinel's backend remains the authoritative orchestration and verification engine.

Product principle:

> Users control the requirements. Sentinel controls the engineering process. AI agents execute the work. Independent verification establishes trust.

---

## 2. First-Run Setup & Onboarding

This is a new major module and a core part of the product.

### 2.1 Expected user journey

```text
Install Sentinel
      |
      v
Launch Sentinel Dashboard
      |
      v
Connect Sentinel Installation
      |
      v
Validate Installation
      |
      v
Create First Project
      |
      v
Add Repositories
      |
      v
Configure Project Through Dashboard
      |
      v
Validate Project Configuration
      |
      v
Project Ready
      |
      v
Create First Task
      |
      v
Start Sentinel Workflow
```

The first-run experience should guide users through this process without requiring them to understand Sentinel's internal configuration structure.

### 2.2 Connect Sentinel installation

The dashboard must provide a setup screen where the user can connect an existing Sentinel installation.

Required capabilities:

- Provide the Sentinel installation directory/path.
- Browse or select the installation location where supported.
- Validate that the selected directory contains a recognized Sentinel installation.
- Detect the installed Sentinel version.
- Check required runtime dependencies.
- Check required configuration and permissions.
- Detect whether Sentinel is already running.
- Connect to or launch the Sentinel runtime.
- Display installation and connection status.
- Provide actionable setup errors and troubleshooting instructions.

Example:

```text
Sentinel Setup

Installation Path:
[/home/user/.sentinel              ] [Browse]

Installation Status: Detected
Version: 1.x
Runtime: Ready
Configuration: Needs Setup

[Validate Installation] [Connect]
```

**Important architectural requirement:**

The web frontend must not directly execute arbitrary local commands or access the user's filesystem. Local installation discovery and process management must be handled through a trusted Sentinel Desktop component, local companion service, or another explicitly secured integration.

The connection mechanism must:

- Authenticate the dashboard to the local Sentinel runtime.
- Restrict access to authorized users.
- Validate requested operations.
- Avoid exposing secrets or credentials.
- Prevent arbitrary command execution through dashboard inputs.
- Provide explicit permission boundaries for process launch, repository access, and filesystem operations.

Support a local installation first, while keeping the architecture extensible to remote Sentinel installations later.

### 2.3 Installation health check

Before allowing project creation, the dashboard should validate:

| Check | Expected result |
|---|---|
| Sentinel installation | Detected |
| Sentinel version | Supported |
| Runtime dependencies | Available |
| Runtime connection | Connected |
| Configuration directory | Accessible |
| Agent runtime | Available or clearly marked optional |
| Provider configuration | At least one usable provider |
| Storage | Available |
| Repository access | Permission verified when needed |

Show each check as Passed, Warning, Failed, or Not Configured.

Do not report the installation as ready when a required component is unavailable.

---

## 3. Project Management

Projects are the primary organizational unit in Sentinel.

A project represents a software system and contains its repositories, configurations, engineering knowledge, workflows, and task history.

### 3.1 Create a project

Users must be able to create projects directly from the dashboard.

Project information:

- Project name
- Description
- Project type
- Programming languages
- Frameworks
- Project directory or workspace
- Default branch
- Project owner
- Environment
- Optional documentation and instructions

The dashboard should support both guided setup and advanced configuration.

### 3.2 Add repositories

A project can contain multiple repositories.

Examples:

- Backend
- Frontend
- Mobile application
- Shared libraries
- Infrastructure
- Documentation

Repository connection methods should support:

- Existing local Git repository.
- Local repository path.
- Remote Git URL.
- Supported Git provider integrations.
- Multiple repositories belonging to one project.

Repository information:

- Repository name
- Local path or remote URL
- Git provider
- Default branch
- Current branch
- Primary language
- Framework
- Build commands
- Test commands
- Lint and validation commands
- Repository-specific instructions

The system should validate:

- Repository existence and accessibility.
- Git repository status.
- Remote configuration where applicable.
- Branch availability.
- Workspace permissions.
- Repository compatibility.

The user should be able to add, remove, edit, and reorder repositories without editing configuration files manually.

### 3.3 Multi-repository project support

Sentinel must understand that one project may contain several interconnected repositories.

For example:

```text
MEF Digital HR
|
|-- backend
|   |-- Spring Boot
|   |-- Java
|   |-- MySQL
|
|-- frontend
|   |-- Next.js
|   |-- TypeScript
|
|-- mobile
    |-- Flutter
    |-- Dart
```

Sentinel should support:

- Cross-repository dependencies.
- Repository-specific instructions.
- Repository-specific test commands.
- Shared project-level requirements.
- Cross-repository task planning.
- Coordinated execution order.
- Changes affecting multiple repositories.
- Traceability between tasks and repository changes.

A task should be able to target one repository or multiple repositories.

---

## 4. Dashboard-Based Configuration Center

**Core requirement: Configuration normally performed manually through files or terminal commands must have a corresponding dashboard management experience wherever it is safe and practical.**

Users should not need to understand internal YAML, JSON, TOML, environment files, or CLI configuration commands to use Sentinel.

### 4.1 Configuration categories

| Category | Dashboard capabilities |
|---|---|
| Sentinel runtime | Installation, runtime connection, startup settings |
| Projects | Project details, workspace, project defaults |
| Repositories | Paths, remotes, branches, build/test commands |
| AI providers | Provider selection, model selection, connection status |
| Agent registry | Agent roles, availability, capabilities |
| Workflows | Templates, stage configuration, retry policies |
| Policies | Approval rules, permissions, risk settings |
| TDD | Test commands, test requirements, coverage policies |
| Verification | Build, lint, test, security, regression checks |
| Knowledge | Architecture documents, instructions, coding standards |
| Git | Branch naming, commit conventions, publishing permissions |
| Storage | Artifact storage and retention settings |
| Notifications | Event and notification preferences |
| Users | Roles, project access, permissions |

### 4.2 Provider configuration

Users should be able to configure AI providers from the dashboard.

Capabilities:

- Add and configure a provider.
- Enter or securely connect credentials.
- Select a default provider.
- Select a default model.
- Configure provider-specific options.
- Test provider connectivity.
- View supported capabilities.
- Enable or disable providers.
- Configure provider fallback policies.

Secrets must be stored securely and never returned to the frontend after submission.

Provider configuration should be scoped appropriately: global, project, or task level.

### 4.3 Agent configuration

Users should be able to manage:

- Agent registry.
- Agent role.
- Provider and model assignment.
- Agent capabilities.
- Tool permissions.
- Task eligibility.
- Execution limits.
- Timeout and retry policies.

Agent configuration must not allow users to bypass mandatory workflow policies or human approvals.

### 4.4 Workflow and policy configuration

Provide dashboard interfaces for:

- Workflow templates.
- Task-type routing.
- Stage dependencies.
- Retry limits.
- Timeout policies.
- Failure handling.
- Human approval gates.
- Risk-based execution rules.
- Provider fallback rules.

The dashboard may let authorized users customize workflow behavior, but the deterministic orchestration engine must validate every configuration and transition.

### 4.5 Configuration profiles

Support reusable configuration profiles.

Examples:

- Spring Boot Backend
- Next.js Frontend
- Flutter Mobile
- Full-Stack Application
- Database Migration
- Documentation Project

A profile can provide suggested:

- Agent roles.
- Workflow templates.
- Build and test commands.
- Verification requirements.
- Coding standards.
- Repository conventions.

Profiles are starting points, not permission to skip project validation or approval gates.

### 4.6 Configuration validation and history

Every configuration screen should support:

- Save.
- Validate.
- Preview changes.
- Show validation errors.
- Show warnings.
- Show the impact of a change.
- Version history.
- Restore previous versions where permitted.
- Audit history.

Important configuration changes must be validated before becoming active.

Configuration changes that materially affect an active task must not silently alter its approved execution contract. Use versioned configuration snapshots and define whether the task must be paused, restarted, or explicitly migrated.

### 4.7 Advanced configuration

Some advanced users will still want direct access to configuration files.

Provide an advanced view that can:

- Display effective configuration.
- Show the source of each setting.
- Explain which settings are inherited or overridden.
- Export configuration.
- Import validated configuration.
- Show differences between versions.

The dashboard should remain the preferred configuration interface, while file-based configuration remains supported for automation and advanced users.

---

## 5. Project Readiness

After project creation and configuration, Sentinel should provide a dedicated readiness screen.

Example:

```text
Project: Digital HR

Project Status: Ready

Repositories
  Backend                 Connected
  Frontend                Connected
  Mobile                  Connected

Configuration
  Provider                Configured
  Agents                  Configured
  Workflow                Valid
  Build Commands          Validated
  Test Commands           Validated
  Verification            Configured
  Knowledge               Loaded

[Create First Task]
```

Readiness should be based on actual validation, not merely whether a configuration field contains a value.

Use clear states:

- Ready
- Ready with warnings
- Needs configuration
- Invalid configuration
- Connection unavailable

Allow users to start tasks when all requirements for the selected workflow are satisfied. Do not require optional integrations that the task does not need.

---

## 6. Task Management

Users can create tasks from the dashboard after selecting a project.

Task creation supports:

- Natural-language requirements.
- Project selection.
- One or more repository targets.
- Priority.
- Task type.
- Optional workflow.
- Optional provider/model preference.
- Branch or ticket references.
- Additional documentation and context.

Task creation does not authorize implementation.

The task lifecycle:

```text
CREATED
  → TRIAGED
  → PLANNING
  → SPECIFICATION_REVIEW
  → GHERKIN_REVIEW
  → EXECUTING
  → VERIFYING
  → REVIEWING
  → COMPLETED
  → ACCEPTED
```

Additional states include BLOCKED, NEEDS_HUMAN, FAILED, and CANCELLED.

Execution completion, verification, and human acceptance must remain distinct.

---

## 7. Human Approval Center

Human approval is mandatory for:

1. Specification generation and review.
2. Gherkin scenario and coverage review.

Specification approval must be tied to an exact version and content hash.

Gherkin approval must be tied to an exact version and content hash.

Material changes invalidate the previous approval.

The approval interface supports:

- Approve.
- Request changes.
- Reject.
- Comments.
- Version comparison.
- Change history.
- Reviewer identity.
- Timestamp and audit history.

No implementation may begin before both required approvals are recorded.

---

## 8. Deterministic Orchestration

The dashboard must never become a second orchestration engine.

Sentinel's backend owns:

- Task state.
- Workflow transitions.
- Preconditions.
- Permissions.
- Approval validation.
- Agent scheduling.
- Provider routing.
- TDD enforcement.
- Verification outcomes.
- Retry and recovery policies.

Agents may propose actions and results, but only Sentinel's deterministic core authorizes state transitions.

The workflow graph must be generated from the actual task execution graph, not a hardcoded universal pipeline.

---

## 9. Cross-Provider Subagent Runtime

Provide a provider-neutral agent invocation contract.

The runtime must support:

- Provider adapters.
- Native subagent delegation where available.
- External agent execution through adapters.
- Structured input and output.
- Execution events.
- Artifact references.
- Cancellation where supported.
- Timeout and retry policies.
- Provider capability discovery.

Do not assume every provider supports the same tools, context, streaming, cancellation, or session-resume behavior.

---

## 10. TDD-First Execution

The coding workflow must follow:

```text
RED → GREEN → REFACTOR
```

- Red: prove the approved test fails for the intended reason.
- Green: implement the smallest change that makes the test pass.
- Refactor: improve implementation while preserving passing tests.

Record commands, outputs, test IDs, changed files, provider/agent, timestamps, and cycle history.

Agents cannot silently modify approved tests or acceptance criteria.

---

## 11. Workflow, Agent, and Run Monitoring

The dashboard must display:

- Actual workflow graph.
- Stage status and dependencies.
- Agent activity.
- Provider and model.
- Start time and duration.
- Retries and failures.
- Logs and artifacts.
- Blockers.
- Human interventions.

Authorized users may pause, resume, cancel, retry, or request intervention.

Every action must be validated by the backend. The UI must not claim success until the backend confirms it.

---

## 12. Requirement-to-Code Traceability

Maintain this relationship:

```text
Requirement
   → Acceptance Criterion
   → Approved Test Scenario
   → TDD Cycle
   → Changed Files
   → Verification Evidence
   → Human Acceptance
```

Detect missing links and distinguish traceability gaps from actual quality failures.

---

## 13. Verification & Quality Center

Display independently verifiable evidence for:

- Unit tests.
- Integration tests.
- Regression tests.
- Build.
- Lint.
- Type checking.
- Security checks.
- API contract checks.
- Database migration validation.
- Code review.
- QA.

Each result should include its execution method, status, timestamp, exit code, test counts, failure summary, and artifact reference.

An agent's claim alone is not verification evidence.

---

## 14. Code Changes and Git

Display:

- Repository.
- Branch.
- Base commit.
- Changed files.
- Diff summary.
- Additions and deletions.
- Related task and TDD cycle.
- Commits.
- Pull request link where available.

Support inline and side-by-side diffs.

Branch creation, commits, publishing, and pull-request operations must follow configured permissions and policies. Publishing must remain disabled unless explicitly configured.

---

## 15. Projects, Knowledge, and Templates

Project knowledge includes:

- Architecture rules.
- Coding standards.
- API conventions.
- Database conventions.
- Security requirements.
- Regression suites.
- Project instructions.
- Engineering decisions.
- Reusable lessons.

The Git repository or configured knowledge store remains the source of truth.

Provide task templates for bug fixes, APIs, full-stack features, migrations, authentication, refactoring, performance, documentation, and infrastructure.

Templates cannot bypass approvals or policy.

---

## 16. Notifications and Human Intervention

Notify authorized users about:

- Pending specification approval.
- Pending Gherkin approval.
- Requested changes.
- Execution start and completion.
- Agent failure.
- Blocked tasks.
- Provider unavailability.
- Regression or verification failure.
- Required human intervention.

Opening a notification is not an approval.

Record all critical human actions in an audit history.

---

## 17. Analytics and Engineering Intelligence

Provide execution, quality, and cost reports.

Metrics include:

- Task count and duration.
- Approval wait time.
- Retry and provider failure rates.
- TDD results.
- Regression results.
- Verification pass rate.
- Rework.
- Cost by task, agent, and provider.
- Actual versus estimated usage.

Engineering insights can identify provider suitability, recurring failures, bottlenecks, and quality trends.

Never fabricate missing metrics or automatically weaken quality gates to improve reported performance.

---

## 18. Security and Permissions

Suggested roles:

- Admin
- Project Owner
- Reviewer
- Developer
- Viewer

Enforce permissions on the backend.

Protect provider credentials, local runtime access, repository access, artifacts, and approval endpoints.

Validate configuration changes, audit critical actions, redact secrets from logs, and use secure authentication and session protections.

The dashboard's local runtime connection must use an explicit trust boundary and narrowly scoped permissions.

---

## 19. Dashboard Navigation

Recommended navigation:

1. Overview
2. Projects
   - All Projects
   - Create Project
   - Project Details
   - Repositories
   - Configuration
   - Knowledge
   - Settings
3. Tasks
   - All Tasks
   - Create Task
   - My Approvals
   - Archived
4. Runs
5. Workflow
6. Agents
7. Providers
8. Quality
   - TDD
   - Tests
   - Regression
   - Verification
9. Reports
10. Notifications
11. Settings
    - Sentinel Installation
    - Runtime Connection
    - Global Configuration
    - Users and Permissions

---

## 20. API and Architecture Requirements

Use the existing backend architecture where possible. Inspect the repository before introducing new services or API boundaries.

Suggested API groups:

```text
/api/installation
/api/runtime
/api/projects
/api/projects/{projectId}/repositories
/api/projects/{projectId}/configuration
/api/projects/{projectId}/readiness
/api/providers
/api/agents
/api/workflows
/api/policies
/api/tasks
/api/tasks/{taskId}/specification
/api/tasks/{taskId}/gherkin
/api/tasks/{taskId}/workflow
/api/tasks/{taskId}/tdd
/api/tasks/{taskId}/verification
/api/tasks/{taskId}/artifacts
/api/runs
/api/notifications
/api/reports
```

These are proposed boundaries, not mandatory duplicate endpoints. Reuse existing services and contracts.

Architecture:

```text
Sentinel Dashboard
       |
       v
Dashboard API / BFF
       |
       v
Authentication & Authorization
       |
       v
Sentinel Backend
       |
       +-- Installation & Runtime Management
       +-- Project & Repository Management
       +-- Configuration Management
       +-- Provider & Agent Registry
       +-- Task Management
       +-- Approval Services
       +-- Deterministic Orchestrator
       +-- Subagent Runtime
       +-- TDD & Verification
       +-- Artifact & Knowledge Management
       |
       v
Persistence / Events / Artifacts
```

For local installations, a secured local companion component handles filesystem discovery and permitted runtime operations. The dashboard communicates through an authenticated interface.

Use REST for commands and queries, SSE initially for live updates, and WebSockets only where justified. Support reconnection and state refresh.

---

## 21. Implementation Roadmap

### Phase 1: Installation and First-Run Onboarding
- Installation path connection.
- Runtime detection and validation.
- Secure runtime connection.
- First-run setup wizard.
- Health checks.
- First project creation.

### Phase 2: Project and Repository Management
- Project CRUD.
- Multiple repositories.
- Local and remote repository connections.
- Repository inspection.
- Multi-repository workspace support.

### Phase 3: Configuration Center
- Provider setup.
- Agent configuration.
- Workflow configuration.
- Policies.
- TDD and verification settings.
- Knowledge management.
- Configuration validation, versioning, and history.

### Phase 4: Task Management and Human Approvals
- Task creation.
- Specification review.
- Human review of the Gherkin.
- Version-bound approvals.

### Phase 5: Workflow and Agent Monitoring
- Actual execution graph.
- Agent/provider monitoring.
- Run controls.
- Logs and artifacts.

### Phase 6: TDD, Traceability, and Quality
- Red-Green-Refactor monitoring.
- Requirement-to-code traceability.
- Verification evidence.
- Regression and security checks.

### Phase 7: Git, Analytics, and Team Management
- Diff viewer.
- Git operations.
- Notifications.
- Reports.
- RBAC and audit improvements.

---

## 22. Acceptance Criteria for the New Onboarding Capability

The implementation is not complete until:

1. A new user can install Sentinel and open the dashboard.
2. The user can provide or select the Sentinel installation path.
3. The dashboard can securely validate the installation.
4. The dashboard can connect to or launch the Sentinel runtime through the trusted local integration.
5. The dashboard clearly reports missing dependencies and configuration.
6. The user can create a project without manually editing configuration files.
7. The user can add multiple repositories to a project.
8. The dashboard validates repository paths and access.
9. The user can configure providers and agents through the dashboard.
10. The user can configure workflows and project policies through the dashboard.
11. The user can configure build, test, lint, and verification commands.
12. The dashboard validates configuration before activation.
13. Configuration changes are versioned and auditable.
14. A project readiness check identifies missing required configuration.
15. A ready project allows the user to create and start a task immediately.
16. The first task still follows mandatory specification and Gherkin approval.
17. A user can return later and manage projects and configuration without terminal-based setup.
18. Local runtime access and repository permissions are secured.
19. Existing CLI and file-based configuration workflows remain compatible.
20. The system does not create a second orchestration engine inside the dashboard.

---

## 23. Instructions for the Implementation Agent

Before implementation:

1. Inspect the existing Sentinel repository.
2. Read the master Sentinel upgrade specification.
3. Inspect the existing dashboard specification and architecture.
4. Identify existing installation, runtime, project, repository, provider, agent, and configuration capabilities.
5. Identify which configuration currently requires manual file editing or terminal commands.
6. Map each configuration capability to a dashboard screen and backend contract.
7. Design the trusted local runtime connection and its security boundaries.
8. Define API contracts and data models.
9. Produce an implementation plan and Gherkin scenarios.
10. Submit the specification and Gherkin scenarios for human approval.

During implementation:

- Follow contract-first development.
- Follow Red-Green-Refactor.
- Preserve existing CLI compatibility.
- Reuse existing backend services.
- Avoid duplicate orchestration logic.
- Do not expose secrets.
- Do not allow arbitrary local command execution from dashboard inputs.
- Test installation discovery, invalid paths, permissions, runtime connection failures, repository access, configuration validation, and recovery.
- Test both fresh installations and existing installations.
- Do not replace real backend behavior with mock-only implementations.

If backend functionality is missing, define and approve the backend contract and tests before implementing the dashboard integration.

---

## 24. Definition of Done

The Sentinel Dashboard is ready when:

- A new user can connect a Sentinel installation.
- A user can create and configure a project through the dashboard.
- A project can contain multiple repositories.
- Providers and agents can be configured through the UI.
- Workflows and policies can be managed through the UI.
- Project readiness is validated.
- The user can immediately create and start a task.
- Specification and Gherkin approvals remain mandatory.
- Execution follows deterministic orchestration and TDD.
- Workflow, agents, and verification are observable.
- Results have traceable evidence.
- Configuration and critical actions are auditable.
- Existing CLI workflows remain compatible.

## 25. North Star

The onboarding experience should answer:

1. **How do I start?** Connect my Sentinel installation.
2. **What am I working on?** Create a project.
3. **Where is my code?** Add repositories.
4. **How should Sentinel work?** Configure providers, agents, workflows, and policies.
5. **Is everything ready?** Validate the project.
6. **What should Sentinel do?** Create a task.
7. **Can I trust the result?** Review approvals, TDD, verification, and evidence.

**Final product principle:**

A user should not need to understand Sentinel's internal configuration files to use Sentinel. They should be able to install it, open the dashboard, connect their installation, configure their projects, and begin their first engineering task through one guided experience.