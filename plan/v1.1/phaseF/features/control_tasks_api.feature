@REQ-TSK-01 @REQ-TSK-02 @REQ-TSK-03 @REQ-MON-02 @REQ-API-03 @REQ-SEC-07
Feature: Creating runs and controlling them from the dashboard
  A run created through the API is queued for the AI tool: it waits in CREATED until an AI tool
  session triages it with "/sentinel resume". Creating it authorizes nothing. While the server
  runs, ready tasks of dashboard-created runs that are routed to a CLI provider are started
  through "sentinel task run", the same path as the CLI; native tasks wait for the orchestrator.
  Controls (cancel, resume, retry) are engine transitions with actor "human" and channel
  "dashboard", and each one is audited.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And workspace "digital-hr" with repos "backend" and "frontend" is registered as project "digital-hr"
    And the server listens on 127.0.0.1 port P and the client holds session cookie S and CSRF value C

  Rule: Creating a run queues it for the AI tool

    @AC-TSK-01a @integration @P1 @cov-happy-path
    Scenario: Creating a run from the dashboard
      When POST /api/v1/projects/digital-hr/tasks is sent with cookie S, CSRF header C and body {"slug": "leave-balance", "request": "Show the remaining leave balance", "type": "feature", "repos": ["backend", "frontend"], "priority": "high"}
      Then the status is 201 and the answer holds run "leave-balance" in state CREATED with workflow version "2"
      And the run has baseline SHAs for "backend" and "frontend", a config snapshot and the slug lock
      And the "run.created" event has actor kind "human" and channel "dashboard"
      And the audit log has a row with channel "dashboard", action "run_created" and target "leave-balance"

    @AC-TSK-03b @integration @P1 @cov-happy-path
    Scenario: The new run waits for the AI tool
      Given run "leave-balance" was created through the API
      When GET /api/v1/tasks/leave-balance/next is called
      Then the step has kind "orchestrator", action "triage" and the label "waiting for AI tool"
      And the step names the command "/sentinel resume leave-balance"
      And no task of "leave-balance" exists

    @AC-TSK-02a @integration @P1 @cov-authz
    Scenario: Creating a run authorizes nothing
      Given run "leave-balance" was created through the API with a "tier" of 4 requested
      Then no approval of "leave-balance" is APPROVED or IN_REVIEW
      And no task was started and no runner process was launched
      And the working trees of "backend" and "frontend" are unchanged
      And the run tier is not set until the orchestrator submits the triage factors, and the requested tier 4 is stored as requested_tier

    @AC-TSK-01b @integration @P1 @cov-invalid-input
    Scenario Outline: Invalid run bodies
      When POST /api/v1/projects/digital-hr/tasks is sent with body <body>
      Then the status is 400 with error code "E_VALIDATION" naming "<field>"
      And no run row and no run folder exist for the slug
      Examples:
        | body                                                                                    | field    |
        | {"slug": "Bad Slug", "request": "x", "type": "feature", "repos": ["backend"]}            | slug     |
        | {"slug": "a..b", "request": "x", "type": "feature", "repos": ["backend"]}                | slug     |
        | {"slug": "lb", "request": "x", "type": "party", "repos": ["backend"]}                    | type     |
        | {"slug": "lb", "request": "x", "type": "feature", "repos": ["mobile"]}                   | repos    |
        | {"slug": "lb", "request": "x", "type": "feature", "repos": ["../etc"]}                   | repos    |
        | {"slug": "lb", "request": "x", "type": "feature", "repos": ["backend"], "tier": 7}        | tier     |
        | {"slug": "lb", "request": "x", "type": "feature", "repos": ["backend"], "priority": "now"} | priority |

    @AC-TSK-01c @integration @P2 @cov-missing-fields
    Scenario Outline: Required run fields
      When POST /api/v1/projects/digital-hr/tasks is sent with a valid body that lacks <field>
      Then the status is 400 with error code "E_VALIDATION" naming <field>
      Examples:
        | field   |
        | slug    |
        | request |
        | type    |

    @AC-TSK-01d @integration @P2 @cov-empty-null
    Scenario Outline: Empty values
      When POST /api/v1/projects/digital-hr/tasks is sent with a valid body where <field> is <value>
      Then the status is 400 with error code "E_VALIDATION" naming <field>
      Examples:
        | field   | value  |
        | request | ""     |
        | request | "   "  |
        | repos   | []     |
        | slug    | null   |

    @AC-TSK-01e @integration @P2 @cov-boundary
    Scenario: Repos may be left out
      When POST /api/v1/projects/digital-hr/tasks is sent with {"slug": "lb", "request": "x", "type": "feature"}
      Then the status is 201 and the run uses every repo of the project, as "sentinel run new" does without --repos

    @AC-TSK-01f @integration @P1 @cov-duplicate
    Scenario Outline: A slug that is taken
      Given <existing>
      When POST /api/v1/projects/digital-hr/tasks is sent with slug "leave-balance" and a valid body
      Then the status is <status> with error code "<code>"
      And the existing run is unchanged
      Examples:
        | existing                                                  | status | code            |
        | a version 2 run "leave-balance" exists                    | 422    | E_PRECONDITION  |
        | a 0.1 run "leave-balance" exists                          | 422    | E_PRECONDITION  |
        | an active run holds the lock on slug "leave-balance"      | 409    | E_LOCKED        |

    @AC-TSK-01g @integration @P2 @cov-concurrency
    Scenario: Two creations of the same slug at the same moment
      When two POSTs creating run "leave-balance" are sent at the same moment
      Then exactly one answers 201
      And the other answers 409 or 422 with the engine's error code
      And exactly one "run.created" event exists for "leave-balance"

    @AC-TSK-01h @integration @P2 @cov-external-failure
    Scenario: A repo that is no longer a git repo
      Given the folder of repo "frontend" no longer holds a git repo
      When POST /api/v1/projects/digital-hr/tasks is sent with repos ["backend", "frontend"]
      Then the status is 422 with error code "E_PRECONDITION" naming "frontend"
      And no run row exists for the slug

  Rule: CLI-routed stages of dashboard runs run directly, native stages wait

    @AC-TSK-03c @integration @P1 @cov-happy-path
    Scenario: The server starts a ready CLI task of a dashboard run
      Given run "leave-balance" was created through the API and the orchestrator has triaged and planned it
      And the config snapshot sets single_model false and agents.specifier to runner "fake"
      And runners.fake is a fake CLI that writes a valid spec and result.json and exits 0
      When the specifier task becomes QUEUED
      Then within 2 seconds the server starts "sentinel task run" for it as a separate process in its own process group
      And the task becomes COMPLETED with adapter "cli" and the run moves to SPECIFICATION_REVIEW by R4
      And the "task.started" event has actor kind "engine"

    @AC-TSK-03d @integration @P1 @cov-happy-path
    Scenario: A native task of a dashboard run waits for the AI tool
      Given run "leave-balance" was created through the API with single_model true in its config snapshot
      And the orchestrator has triaged and planned it
      When the specifier task becomes QUEUED
      Then the server does not start it
      And GET /api/v1/tasks/leave-balance/next shows that task with label "waiting for orchestrator"

    @AC-TSK-03e @integration @P1 @cov-regression
    Scenario: Runs created at the CLI are not dispatched by the server
      Given run "cli-run" was created with "sentinel run new cli-run --type feature" and has a QUEUED CLI-routed task
      When the server has been running for 5 seconds
      Then that task is still QUEUED and no runner process was launched by the server

    @AC-TSK-03f @integration @P1 @cov-concurrency
    Scenario: The server and the orchestrator start the same task at the same moment
      Given a QUEUED CLI-routed task t-spec1 of dashboard run "leave-balance"
      When the server dispatch and an orchestrator "sentinel task run t-spec1" start at the same moment
      Then exactly one runner process is launched
      And the other call is refused with "E_TRANSITION" and changes nothing

    @AC-TSK-03g @integration @P2 @cov-boundary
    Scenario: Server dispatch respects the scheduler
      Given dashboard run "leave-balance" has three QUEUED CLI-routed tasks, two of them with overlapping write scopes
      And execution.max_parallel_tasks is 2
      When the server dispatches ready tasks
      Then at most 2 tasks run at once and the two overlapping tasks never run at the same time

    @AC-TSK-03h @integration @P2 @cov-external-failure
    Scenario: A missing runner blocks the run, as at the CLI
      Given dashboard run "leave-balance" has a QUEUED task routed to runner "fake" whose command is not installed
      When the server dispatches ready tasks
      Then the task stays QUEUED and the run is BLOCKED by R21 with reason naming runner "fake"
      And the server does not retry the start until the run leaves BLOCKED

    @AC-TSK-03i @integration @P2 @cov-errors
    Scenario: Stopping the server does not kill a running task
      Given the server started CLI task t-spec1 of dashboard run "leave-balance" and the fake runner sleeps 3 seconds
      When the server receives SIGTERM
      Then the "sentinel task run" process of t-spec1 keeps running and finishes the task as COMPLETED

  Rule: Controls are engine transitions

    @AC-MON-02a @integration @P1 @cov-happy-path
    Scenario: Cancelling a run from the dashboard
      Given run "leave-balance" is EXECUTING with a RUNNING CLI task whose runner process group is alive
      When POST /api/v1/tasks/leave-balance/control is sent with body {"action": "cancel", "comment": "wrong ticket"}
      Then the status is 200 and the answer holds run state CANCELLED as stored by R23
      And the running task is CANCELLED and its process group received SIGTERM
      And the slug lock is released
      And the "run.state_changed" event names transition "R23", actor kind "human" and channel "dashboard"
      And the audit log has a row with channel "dashboard", action "cancel", target "leave-balance" and reason "wrong ticket"

    @AC-MON-02b @integration @P1 @cov-happy-path
    Scenario: Cancelling one task
      Given run "leave-balance" is EXECUTING with QUEUED task t-red2 and its dependent t-green2
      When POST /api/v1/tasks/leave-balance/control is sent with body {"action": "cancel", "task_id": "t-red2"}
      Then the status is 200
      And t-red2 and t-green2 are CANCELLED with actor "human" and the run stays EXECUTING
      And the audit log has a row with channel "dashboard", action "cancel" and target "leave-balance/t-red2"

    @AC-MON-02c @integration @P1 @cov-happy-path
    Scenario: Resuming a run that needs a human
      Given run "leave-balance" went from EXECUTING to NEEDS_HUMAN by R19 with reason "red retry cap reached"
      When POST /api/v1/tasks/leave-balance/control is sent with body {"action": "resume", "comment": "test data fixed"}
      Then the status is 200 and the run is EXECUTING by R20
      And the "run.state_changed" event has actor kind "human", channel "dashboard" and reason "test data fixed"

    @AC-MON-02d @integration @P2 @cov-happy-path
    Scenario: Retrying a failed task
      Given run "leave-balance" is EXECUTING and task t-doc1 is FAILED with "E_EXIT" after its retry cap
      When POST /api/v1/tasks/leave-balance/control is sent with body {"action": "retry", "task_id": "t-doc1"}
      Then the status is 200 and a new task with retry_of "t-doc1" is QUEUED
      And the audit log has a row with channel "dashboard" and action "retry"

    @AC-MON-02e @integration @P1 @cov-errors
    Scenario Outline: Controls refused by the engine
      Given <state>
      When POST /api/v1/tasks/leave-balance/control is sent with body <body>
      Then the status is <status> with error code "<code>"
      And the run state and task states are unchanged
      Examples:
        | state                                                   | body                                                     | status | code           |
        | run "leave-balance" is COMPLETED                        | {"action": "cancel"}                                     | 409    | E_TRANSITION   |
        | run "leave-balance" is CANCELLED                        | {"action": "cancel"}                                     | 409    | E_TRANSITION   |
        | run "leave-balance" is EXECUTING                        | {"action": "resume", "comment": "go"}                    | 409    | E_TRANSITION   |
        | task t-doc1 is COMPLETED                                | {"action": "retry", "task_id": "t-doc1"}                 | 409    | E_TRANSITION   |
        | task t-doc1 is COMPLETED                                | {"action": "cancel", "task_id": "t-doc1"}                | 409    | E_TRANSITION   |
        | task t-other belongs to another run                     | {"action": "cancel", "task_id": "t-other"}               | 404    | E_NOT_FOUND    |
        | "leave-balance" is a 0.1 run                            | {"action": "cancel"}                                     | 409    | E_TRANSITION   |

    @AC-MON-02f @integration @P2 @cov-invalid-input
    Scenario Outline: Unknown or incomplete control bodies
      Given run "leave-balance" is NEEDS_HUMAN
      When POST /api/v1/tasks/leave-balance/control is sent with body <body>
      Then the status is 400 with error code "E_VALIDATION"
      Examples:
        | body                                       |
        | {"action": "pause"}                        |
        | {"action": "delete"}                       |
        | {}                                         |
        | {"action": "resume"}                       |
        | {"action": "resume", "comment": ""}        |
        | {"action": "retry"}                        |

    @AC-MON-02g @integration @P1 @cov-concurrency
    Scenario: Cancel races with a task that finishes
      Given run "leave-balance" is EXECUTING with RUNNING CLI task t-green1 whose runner exits 0 at the same moment
      When POST /api/v1/tasks/leave-balance/control with {"action": "cancel"} is sent at that moment
      Then the run ends CANCELLED or the cancel is refused with "E_TRANSITION" because the run moved on first
      And if the run is CANCELLED, t-green1 is CANCELLED and its late result never overwrites that state
      And the event log holds no transition after the run's final state

    @AC-MON-02h @integration @P2 @cov-concurrency
    Scenario: Dashboard cancel and terminal finish at the same moment
      When POST /api/v1/tasks/leave-balance/control with {"action": "cancel"} and "sentinel run finish leave-balance --outcome stopped" run at the same moment
      Then the run is CANCELLED once and exactly one R23 "run.state_changed" event exists
      And the losing call is refused with "E_TRANSITION"

    @AC-MON-02i @integration @P2 @cov-db-failure
    Scenario: The registry write fails during a cancel
      Given run "leave-balance" is EXECUTING with a RUNNING CLI task
      And the registry is set to fail the next write transaction
      When POST /api/v1/tasks/leave-balance/control is sent with body {"action": "cancel"}
      Then the status is 500 with error code "E_INTERNAL"
      And the run is still EXECUTING with no partial event, and the task process was not signalled
