@REQ-AGT-04 @REQ-AGT-06 @REQ-ORC-02 @REQ-TSK-03
Feature: Native adapter for subagents inside the AI tool
  A native task waits for the orchestrator. The orchestrator launches the subagent and
  calls "sentinel task complete". The engine then decides COMPLETED or FAILED.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree
    And sentinel.config.yaml sets single_model true
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 with both approvals valid
    And a QUEUED "docs" task for "leave-balance" on repo "backend" with write scope "backend/docs/**"

  Rule: Submitting a native task hands it to the orchestrator

    @AC-AGT-04d @integration @P1 @cov-happy-path
    Scenario: Native task run waits for the orchestrator
      When "sentinel task run" is run for the docs task
      Then it exits with code 0
      And the docs task is WAITING_FOR_INPUT with waiting_on "orchestrator"
      And task.json and prompt.md exist under .sentinel/runs/leave-balance/tasks/<task-id>/
      And the boundary snapshot of every repo is stored as before.json in the same folder
      And no process was started by Sentinel
      And the output JSON holds the prompt path, the result path and the next command "sentinel task complete <task-id>"
      And the stored events for the task are, in order, "task.queued", "task.started", "task.waiting"
      And the "task.waiting" event names waiting_on "orchestrator"

    @AC-AGT-04e @integration @P1 @cov-happy-path
    Scenario: Task complete with a valid result completes the task
      Given the docs task is WAITING_FOR_INPUT after "sentinel task run"
      And the subagent wrote backend/docs/leave.md and a valid result.json
      When "sentinel task complete" is run for the docs task
      Then it exits with code 0
      And the docs task is COMPLETED
      And the task's changed files are ["backend/docs/leave.md"]
      And the "task.finished" event names actor kind "engine"
      And one audit row records actor kind "orchestrator", action "task_complete" and the task id

  Rule: The orchestrator can only ask; the engine decides

    @AC-ORC-02d @integration @P1 @cov-authz
    Scenario Outline: Task complete with a bad outcome fails the task
      Given the docs task is WAITING_FOR_INPUT after "sentinel task run"
      And the subagent <did>
      When "sentinel task complete" is run for the docs task
      Then it exits with code <code>
      And the docs task is FAILED with error code <error>
      Examples:
        | did                                                       | code | error             |
        | wrote no result.json                                      | 1    | "E_RESULT_SCHEMA" |
        | wrote a result.json with "status": "ok"                   | 1    | "E_RESULT_SCHEMA" |
        | wrote a valid result.json with status "failed"            | 1    | "E_AGENT"         |
        | wrote frontend/stray.txt and a valid result.json          | 3    | "E_SCOPE"         |
        | committed in backend and wrote a valid result.json        | 3    | "E_SCOPE"         |

    @AC-ORC-02e @integration @P1 @cov-authz
    Scenario: Task complete has no way to choose the state
      Given the docs task is WAITING_FOR_INPUT after "sentinel task run"
      When "sentinel task complete <task-id> --state COMPLETED" is run
      Then it exits with code 2
      And the docs task is still WAITING_FOR_INPUT

    @AC-ORC-02f @unit @P1 @cov-authz
    Scenario Outline: The orchestrator cannot move a task through the engine directly
      Given the docs task is WAITING_FOR_INPUT after "sentinel task run"
      When the orchestrator asks the engine to move the docs task to <state>
      Then the request is refused with error "E_ACTOR"
      And the docs task is still WAITING_FOR_INPUT
      Examples:
        | state     |
        | COMPLETED |
        | FAILED    |
        | CANCELLED |

    @AC-ORC-02g @integration @P1 @cov-invalid-input
    Scenario Outline: Task complete is refused unless a native task is waiting
      Given the docs task is <state> with adapter <adapter>
      When "sentinel task complete" is run for the docs task
      Then it exits with code 5
      And the error is <error>
      And the docs task is still <state>
      Examples:
        | state     | adapter  | error            |
        | QUEUED    | "native" | "E_TRANSITION"   |
        | CREATED   | "native" | "E_TRANSITION"   |
        | RUNNING   | "cli"    | "E_PRECONDITION" |
        | COMPLETED | "native" | "E_TRANSITION"   |
        | FAILED    | "native" | "E_TRANSITION"   |
        | CANCELLED | "native" | "E_TRANSITION"   |

    @AC-ORC-02h @integration @P2 @cov-duplicate
    Scenario: A second task complete changes nothing
      Given the docs task was completed by "sentinel task complete"
      When "sentinel task complete" is run for the docs task again
      Then it exits with code 5
      And the error is "E_TRANSITION"
      And exactly one "task.finished" event is stored for the task

    @AC-ORC-02i @integration @P2 @cov-concurrency
    Scenario: Two task complete calls at the same time finish the task once
      Given the docs task is WAITING_FOR_INPUT after "sentinel task run"
      And the subagent wrote a valid result.json
      When two processes run "sentinel task complete" for the docs task at the same time
      Then exactly one exits with code 0 and the other exits with code 5 with "E_TRANSITION"
      And exactly one "task.finished" event is stored for the task

  Rule: Native tasks keep the same limits as CLI tasks

    @AC-AGT-05i @integration @P2 @cov-errors
    Scenario: A native task past its timeout fails at the next engine call
      Given the docs task has constraints.timeout_seconds 2
      And the docs task is WAITING_FOR_INPUT after "sentinel task run"
      And 3 seconds pass
      When "sentinel next leave-balance --json" is run
      Then the docs task is FAILED with error code "E_TIMEOUT"
      And the output tells the orchestrator to stop the subagent of the docs task

    @AC-AGT-05j @integration @P1 @cov-happy-path
    Scenario: Cancelling a native task is cooperative
      Given the docs task is WAITING_FOR_INPUT after "sentinel task run"
      When a human cancels the docs task through the engine
      Then the docs task is CANCELLED
      And "sentinel next leave-balance --json" tells the orchestrator to stop the subagent of the docs task
      And a later "sentinel task complete" for the docs task exits with code 5 with "E_TRANSITION"
      And a result.json written after the cancel is not stored as the task result

  Rule: Without an AI tool session, CLI-routed tasks run and native tasks queue (decision Q2)

    @AC-TSK-03a @unit @P1 @cov-happy-path
    Scenario: Dispatch without a session runs only CLI tasks
      Given a version 2 run "leave-form" in state EXECUTING whose config snapshot sets single_model false, agents.docs to runner "fake" and no route for "qa"
      And runners.fake is a fake CLI that writes backend/docs/leave.md and a valid result.json, then exits 0
      And a QUEUED "docs" task for "leave-form" on repo "backend" with write scope "backend/docs/**"
      And a QUEUED "qa" task for "leave-form" on repo "frontend" with an empty write scope
      When the engine dispatches the ready tasks of "leave-form" with no orchestrator session
      Then the docs task of "leave-form" is COMPLETED with adapter "cli"
      And the qa task of "leave-form" is still QUEUED with adapter "native"
      And "sentinel next leave-form --json" reports the qa task with label "waiting for orchestrator"
