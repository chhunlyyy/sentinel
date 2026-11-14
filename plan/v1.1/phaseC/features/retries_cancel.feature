@REQ-AGT-05 @REQ-ORC-05 @REQ-ORC-07 @REQ-SM-03
Feature: Retries with a cap, cancellation and recovery
  A failed task is retried as a new task up to its cap; then a human decides.
  A cancelled task stops its process and stays cancelled.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree
    And sentinel.config.yaml sets single_model false and agents.docs to runner "fake"
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 with both approvals valid

  Rule: A failed task is retried as a new task until the cap

    @AC-AGT-05k @integration @P1 @cov-errors
    Scenario: A failed task gets a retry with the failure reason in its brief
      Given a QUEUED "docs" task for "leave-balance" with constraints.max_retries 2
      And runners.fake is a fake CLI that exits 1 with stderr "error: cannot write docs/leave.md"
      When "sentinel task run" is run for the docs task
      Then it exits with code 1
      And the docs task is FAILED with error code "E_EXIT"
      And a new "docs" task is QUEUED with retry_of set to the failed task and attempt 2
      And the new task's brief contains "E_EXIT" and "error: cannot write docs/leave.md"
      And the new task has the same role, repos, write scope and constraints as the failed task
      And the output names the retry task id

    @AC-ORC-05a @integration @P1 @cov-boundary
    Scenario Outline: The retry cap sends the run to a human
      Given a QUEUED "docs" task for "leave-balance" with constraints.max_retries <cap>
      And runners.fake is a fake CLI that always exits 1
      When "sentinel task run" is run for each new docs task until no docs task is QUEUED
      Then the docs task ran <attempts> times
      And the last "sentinel task run" exits with code 6
      And the run state is NEEDS_HUMAN with reason "docs task failed after <cap> retries"
      And the "run.state_changed" event names transition "R19"
      And no further docs task is QUEUED
      Examples:
        | cap | attempts |
        | 0   | 1        |
        | 1   | 2        |
        | 2   | 3        |

    @AC-ORC-05b @integration @P1 @cov-errors
    Scenario: A retry that succeeds ends the chain
      Given a QUEUED "docs" task for "leave-balance" with constraints.max_retries 2
      And runners.fake is a fake CLI that exits 1 the first time and succeeds with a valid result.json the second time
      When "sentinel task run" is run for the docs task and then for its retry
      Then the first docs task is FAILED and the retry is COMPLETED
      And the run state is still EXECUTING

    @AC-ORC-05c @unit @P1 @cov-errors
    Scenario Outline: Which failures are retried
      Given a RUNNING "docs" task for "leave-balance" with constraints.max_retries 2
      When the task fails with error code <code>
      Then a retry is created: <retried>
      And the run state is <run_state>
      Examples:
        | code              | retried | run_state   |
        | "E_EXIT"          | yes     | EXECUTING   |
        | "E_TIMEOUT"       | yes     | EXECUTING   |
        | "E_RESULT_SCHEMA" | yes     | EXECUTING   |
        | "E_AGENT"         | yes     | EXECUTING   |
        | "E_SCOPE"         | no      | NEEDS_HUMAN |
        | "E_INTEGRITY"     | no      | NEEDS_HUMAN |

    @AC-ORC-05d @unit @P2 @cov-errors
    Scenario: An agent that reports blocked asks a human
      Given a RUNNING "docs" task for "leave-balance"
      And its result.json is valid with status "blocked" and the question "Which date format?"
      When the engine finishes the task
      Then the docs task is BLOCKED
      And no retry is created
      And the run state is NEEDS_HUMAN with reason "docs task blocked: Which date format?"

  Rule: Cancelling a running task kills its process

    @AC-AGT-05l @integration @P1 @cov-happy-path
    Scenario: A human cancels a running CLI task
      Given a QUEUED "docs" task for "leave-balance"
      And runners.fake is a fake CLI that starts a child process and both sleep for 60 seconds
      And "sentinel task run" is running for the docs task in another process
      When a human cancels the docs task through the engine
      Then within 15 seconds neither the fake CLI nor its child process is alive
      And the docs task is CANCELLED
      And the "sentinel task run" process exits with code 1 and reports state "CANCELLED"
      And one "task.finished" event is stored with state "CANCELLED" and actor kind "human"
      And no retry is created
      And the run state is still EXECUTING

    @AC-AGT-05m @integration @P2 @cov-boundary
    Scenario: A runner that ignores SIGTERM is killed after 10 seconds
      Given a QUEUED "docs" task for "leave-balance"
      And runners.fake is a fake CLI that traps SIGTERM and sleeps for 60 seconds
      And "sentinel task run" is running for the docs task in another process
      When a human cancels the docs task through the engine
      Then the fake CLI receives SIGTERM first
      And the fake CLI is not alive 10 to 15 seconds after the cancel
      And the docs task is CANCELLED

    @AC-AGT-05n @integration @P1 @cov-data-integrity
    Scenario: The finishing task run does not overwrite a cancel
      Given a QUEUED "docs" task for "leave-balance"
      And runners.fake is a fake CLI that writes a valid result.json and then sleeps for 60 seconds
      And "sentinel task run" is running for the docs task in another process
      When a human cancels the docs task through the engine
      Then the docs task is CANCELLED
      And it is never FAILED or COMPLETED afterwards
      And exactly one "task.finished" event is stored for the task

    @AC-AGT-05o @unit @P1 @cov-authz
    Scenario Outline: Only a human or the engine can cancel a task
      Given a RUNNING "docs" task for "leave-balance"
      When the <actor> cancels the docs task through the engine
      Then the outcome is <outcome>
      Examples:
        | actor        | outcome                  |
        | human        | task CANCELLED           |
        | engine       | task CANCELLED           |
        | orchestrator | refused with "E_ACTOR"   |

    @AC-AGT-05p @unit @P2 @cov-invalid-input
    Scenario Outline: A finished task cannot be cancelled
      Given a "docs" task for "leave-balance" in state <state>
      When a human cancels the docs task through the engine
      Then the request is refused with error "E_TRANSITION"
      And the docs task is still <state>
      Examples:
        | state     |
        | COMPLETED |
        | FAILED    |
        | CANCELLED |

    @AC-AGT-05q @integration @P1 @cov-happy-path
    Scenario: Cancelling the run cancels its running and queued tasks
      Given a RUNNING "docs" task for "leave-balance" whose fake CLI sleeps for 60 seconds
      And a QUEUED "qa" task for "leave-balance"
      When "sentinel run finish leave-balance --outcome stopped" is run
      Then the run state is CANCELLED and the "run.state_changed" event names transition "R23"
      And the docs task and the qa task are CANCELLED
      And the fake CLI of the docs task is not alive within 15 seconds
      And the slug lock for "leave-balance" is released

    @AC-AGT-05r @integration @P2 @cov-data-integrity
    Scenario: A specification change during execution cancels the running tasks
      Given a RUNNING "docs" task for "leave-balance" whose fake CLI sleeps for 60 seconds
      When specs/leave-balance/spec.md is edited and the engine applies R17
      Then the run state is SPECIFICATION_REVIEW
      And the docs task is CANCELLED by the engine with reason "approval invalidated"
      And the fake CLI of the docs task is not alive within 15 seconds

  Rule: Recovery reads only persisted state

    @AC-ORC-07a @integration @P1 @cov-db-failure
    Scenario: A task whose Sentinel process died is failed and retried
      Given a RUNNING "docs" task for "leave-balance" with constraints.max_retries 2
      And the "sentinel task run" process and the runner it started were killed with SIGKILL
      When "sentinel next leave-balance --json" is run
      Then the docs task is FAILED with error code "E_EXIT" and reason "process lost"
      And a retry docs task is QUEUED
      And the output is a "task" step for the retry task

    @AC-ORC-07b @integration @P2 @cov-db-failure
    Scenario: A reused process id is not mistaken for the runner
      Given a RUNNING "docs" task for "leave-balance" whose stored pid now belongs to an unrelated process started later
      When "sentinel next leave-balance --json" is run
      Then the docs task is FAILED with reason "process lost"
      And the unrelated process is not signalled

    @AC-ORC-07c @unit @P1 @cov-db-failure
    Scenario: An event write failure while finishing a task leaves the task running
      Given a RUNNING "docs" task for "leave-balance" whose process exited with code 0 and wrote a valid result.json
      And the event store fails on the next write
      When the engine finishes the task
      Then the command fails
      And the docs task is still RUNNING
      And no "task.finished" event is stored
      And result.json is still in the task folder
      And the next "sentinel next leave-balance --json" finishes the task as COMPLETED from the stored files
