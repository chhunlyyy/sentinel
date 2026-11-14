@REQ-AGT-07 @REQ-SM-03
Feature: Scheduler: dependencies, write-scope overlap and the parallel limit
  A task is queued only when its dependencies are complete. It starts only when no running
  task has an overlapping write scope and the parallel limit allows it.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree
    And backend holds the files src/main/java/leave/LeaveBalance.java, src/test/java/leave/LeaveBalanceTest.java and docs/leave.md
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 with both approvals valid

  Rule: Dependencies decide when a task is queued

    @AC-AGT-07a @unit @P1 @cov-happy-path
    Scenario: A task is queued when its last dependency completes
      Given tasks "A" and "B" for "leave-balance" are CREATED with no dependencies
      And task "C" is CREATED and depends on "A" and "B"
      When the engine schedules "leave-balance"
      Then tasks "A" and "B" are QUEUED and task "C" is still CREATED
      When task "A" completes
      Then task "C" is still CREATED
      When task "B" completes
      Then task "C" is QUEUED
      And one "task.queued" event is stored for task "C"

    @AC-AGT-07b @integration @P1 @cov-invalid-input
    Scenario: A task with open dependencies cannot be run
      Given task "A" for "leave-balance" is QUEUED
      And task "C" is CREATED and depends on "A"
      When "sentinel task run" is run for task "C"
      Then it exits with code 5
      And the error is "E_TRANSITION" with details listing the open dependency "A"
      And task "C" is still CREATED

    @AC-AGT-07c @integration @P1 @cov-happy-path
    Scenario: Next offers tasks in dependency order
      Given task "A" for "leave-balance" is QUEUED
      And task "C" is CREATED and depends on "A"
      When "sentinel next leave-balance --json" is run
      Then the output is a "task" step for task "A"
      When task "A" completes and "sentinel next leave-balance --json" is run
      Then the output is a "task" step for task "C"

    @AC-AGT-07d @unit @P1 @cov-errors
    Scenario: A dependency satisfied by its retry
      Given task "A" for "leave-balance" failed and its retry "A2" completed
      And task "C" is CREATED and depends on "A"
      When the engine schedules "leave-balance"
      Then task "C" is QUEUED

    @AC-AGT-07e @unit @P2 @cov-errors
    Scenario: Dependents of a cancelled task are cancelled
      Given task "A" for "leave-balance" is QUEUED
      And task "C" is CREATED and depends on "A"
      And task "D" is CREATED and depends on "C"
      When a human cancels task "A" through the engine
      Then tasks "C" and "D" are CANCELLED by the engine with reason "dependency A cancelled"

    @AC-AGT-07f @unit @P2 @cov-invalid-input
    Scenario Outline: An invalid dependency graph is refused when it is stored
      When the engine is asked to store a task graph for "leave-balance" where <graph>
      Then the request is refused with error "E_VALIDATION"
      And no task of the graph is stored
      Examples:
        | graph                                  |
        | "A" depends on "B" and "B" on "A"      |
        | "A" depends on itself                  |
        | "A" depends on unknown task "Z"        |
        | "A" depends on a task of another run   |

  Rule: Tasks with overlapping write scopes never run at the same time

    @AC-AGT-07g @unit @P1 @cov-concurrency
    Scenario Outline: Write-scope overlap test
      Given policies.max_parallel_tasks is 4
      And task "A" for "leave-balance" is RUNNING with write scope <running>
      And task "B" is QUEUED with write scope <queued>
      When the engine checks whether task "B" may start
      Then the answer is <answer>
      Examples:
        | running                     | queued                               | answer |
        | "backend/src/main/**"       | "backend/src/main/java/leave/**"     | no     |
        | "backend/src/main/**"       | "backend/src/test/**"                | yes    |
        | "backend/**"                | "frontend/**"                        | yes    |
        | "backend/**/*.java"         | "backend/src/test/**"                | no     |
        | "backend/docs/*.md"         | "backend/src/**"                     | yes    |
        | "backend/src/main/**"       | "backend/src/main/java/new/**"       | no     |
        | "backend/docs/leave.md"     | "backend/docs/leave.md"              | no     |
        | "backend/src/main/**"       | an empty write scope                 | yes    |

    @AC-AGT-07h @integration @P1 @cov-concurrency
    Scenario: An overlapping task stays queued while the other runs
      Given policies.max_parallel_tasks is 2
      And task "A" for "leave-balance" is RUNNING with write scope "backend/src/main/**"
      And task "B" is QUEUED with write scope "backend/src/main/java/leave/**"
      When "sentinel task run" is run for task "B"
      Then it exits with code 5
      And the error is "E_PRECONDITION" with details naming the overlapping task "A" and the glob pair
      And task "B" is still QUEUED
      And "sentinel next leave-balance --json" returns a "wait" step naming task "A"

    @AC-AGT-07i @integration @P1 @cov-concurrency
    Scenario: A native task waiting for the orchestrator still holds its write scope
      Given policies.max_parallel_tasks is 2
      And task "A" for "leave-balance" is WAITING_FOR_INPUT with write scope "backend/docs/**"
      And task "B" is QUEUED with write scope "backend/docs/**"
      When "sentinel task run" is run for task "B"
      Then it exits with code 5
      And the error is "E_PRECONDITION"
      And task "B" is still QUEUED

    @AC-AGT-07j @integration @P1 @cov-concurrency
    Scenario: Two processes start overlapping tasks at the same moment
      Given policies.max_parallel_tasks is 2
      And tasks "A" and "B" for "leave-balance" are QUEUED, both with write scope "backend/src/main/**"
      When two processes run "sentinel task run" for "A" and for "B" at the same time
      Then exactly one of the tasks is RUNNING or finished
      And the other process exits with code 5 and its task is still QUEUED

    @AC-AGT-07k @integration @P2 @cov-duplicate
    Scenario: The same task run twice at once starts once
      Given task "A" for "leave-balance" is QUEUED and routed to a fake CLI that sleeps 2 seconds and finishes well
      When two processes run "sentinel task run" for "A" at the same time
      Then exactly one fake CLI process was started
      And the other process exits with code 5 with "E_TRANSITION"

  Rule: The parallel limit caps running tasks

    @AC-AGT-07l @integration @P1 @cov-boundary
    Scenario Outline: Parallel limit
      Given policies.max_parallel_tasks is <limit>
      And task "A" for "leave-balance" is RUNNING with write scope "backend/src/main/**"
      And task "B" is QUEUED with write scope "frontend/src/**"
      When "sentinel task run" is run for task "B"
      Then the outcome is <outcome>
      Examples:
        | limit   | outcome                                                          |
        | not set | exit 5, "E_PRECONDITION" naming "max_parallel_tasks 1", B QUEUED |
        | 1       | exit 5, "E_PRECONDITION" naming "max_parallel_tasks 1", B QUEUED |
        | 2       | B starts and is RUNNING                                          |

    @AC-AGT-07m @unit @P2 @cov-invalid-input
    Scenario Outline: An invalid parallel limit is refused by config validation
      Given sentinel.config.yaml sets policies.max_parallel_tasks to <value>
      When the config is validated
      Then validation fails on "policies.max_parallel_tasks"
      Examples:
        | value |
        | 0     |
        | -1    |
        | "two" |

  Rule: Tasks start only while the run allows execution

    @AC-AGT-07n @integration @P1 @cov-authz
    Scenario Outline: No task starts while the run is parked or under review
      Given a QUEUED "docs" task for "leave-balance"
      And the run "leave-balance" is in state <state>
      When "sentinel task run" is run for the docs task
      Then it exits with code 5
      And the error is "E_PRECONDITION" naming the run state <state>
      And the docs task is still QUEUED
      Examples:
        | state                |
        | NEEDS_HUMAN          |
        | BLOCKED              |
        | SPECIFICATION_REVIEW |
        | GHERKIN_REVIEW       |

    @AC-AGT-07o @unit @P1 @cov-authz
    Scenario: A task cannot create tasks
      Given a RUNNING "docs" task for "leave-balance"
      And its result.json is valid and lists a follow-up task in "out_of_lane"
      When the engine finishes the task
      Then the docs task is COMPLETED
      And no new task is created for "leave-balance"
      And the out-of-lane note is kept in the task report
