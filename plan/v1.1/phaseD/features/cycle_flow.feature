@REQ-SM-05 @REQ-ORC-01 @REQ-ORC-05 @REQ-AGT-07
Feature: TDD cycle flow, caps, R13, concurrency and invalidation
  The engine drives each cycle through Red, Green and Refactor without a human, stops at a cap,
  and moves the run to verification when every cycle is accepted. Cycles in different repos
  can run at once; overlapping scopes never do. An invalidated approval stops open cycles.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree
    And repos "backend" and "frontend" use the test profile "fake-junit" with test_globs ["src/test/**"] and production_globs ["src/main/**"]
    And sentinel.config.yaml sets single_model false and agents.tdd_red, agents.tdd_green and agents.tdd_refactor to runner "fake"
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 on repos "backend" and "frontend" with both approvals valid
    And cycles "remaining" and "carry-over" on repo "backend" and cycle "request-form" on repo "frontend" are planned

  Rule: A cycle runs Red, Green and Refactor without a human

    @AC-SM-05d @integration @P1 @cov-happy-path
    Scenario: A full cycle, then the next behavior begins
      Given fake CLIs and the fake test tool that make each phase of cycle "remaining" succeed
      When the orchestrator loops "sentinel next leave-balance --json" and runs each "task" step with "sentinel task run"
      Then cycle "remaining" moved PLANNED, RED_RUNNING, RED_VERIFIED, GREEN_RUNNING, GREEN_VERIFIED, REFACTOR_RUNNING, REFACTOR_VERIFIED, CYCLE_ACCEPTED
      And no "human" step was returned while cycle "remaining" ran
      And the next "task" step for repo "backend" is the tdd_red task of cycle "carry-over"

    @AC-SM-05e @unit @P1 @cov-invalid-input
    Scenario Outline: Undefined cycle moves are refused
      Given cycle "remaining" is in state <from>
      When the engine moves cycle "remaining" to <to>
      Then the move is refused with error "E_TRANSITION"
      Examples:
        | from              | to             |
        | PLANNED           | GREEN_RUNNING  |
        | RED_VERIFIED      | CYCLE_ACCEPTED |
        | GREEN_VERIFIED    | CYCLE_ACCEPTED |
        | CYCLE_ACCEPTED    | RED_RUNNING    |
        | REJECTED          | PLANNED        |

  Rule: A phase cap rejects the cycle and asks a human

    @AC-ORC-05e @integration @P1 @cov-boundary
    Scenario Outline: Cap per phase
      Given sentinel.config.yaml sets tdd.<key> <cap>
      And every attempt of the <phase> phase of cycle "remaining" is rejected by the engine
      When the orchestrator runs every "task" step that "sentinel next leave-balance --json" returns
      Then <attempts> <phase> tasks were run for cycle "remaining"
      And cycle "remaining" is REJECTED with reason "<phase> cap reached"
      And the run state is NEEDS_HUMAN with reason naming cycle "remaining" and the last rejection
      And the last "sentinel task run" exited with code 6
      Examples:
        | phase    | key              | cap | attempts |
        | red      | red_retries      | 2   | 3        |
        | green    | green_retries    | 3   | 4        |
        | refactor | refactor_retries | 2   | 3        |
        | red      | red_retries      | 0   | 1        |

    @AC-ORC-05f @unit @P2 @cov-boundary
    Scenario Outline: Where the cap comes from
      Given sentinel.config.yaml sets <settings>
      When the engine computes the Red cap of cycle "remaining"
      Then the cap is <cap>
      Examples:
        | settings                                   | cap |
        | tdd.red_retries 1 and limits.red_retries 4 | 1   |
        | limits.red_retries 4 only                  | 4   |
        | neither                                    | 2   |

    @AC-ORC-05g @integration @P1 @cov-errors
    Scenario: Task failures and engine rejections share the phase cap
      Given sentinel.config.yaml sets tdd.green_retries 1
      And the first tdd_green task of cycle "remaining" exits 1 with "E_EXIT"
      And the second tdd_green task completes but the targeted tests fail
      When the engine finishes the second tdd_green task
      Then cycle "remaining" is REJECTED
      And the run state is NEEDS_HUMAN

    @AC-ORC-05h @integration @P2 @cov-errors
    Scenario: After a human resumes, a rejected cycle is replanned as a new cycle
      Given cycle "remaining" is REJECTED and the run is NEEDS_HUMAN with previous state EXECUTING
      When a human resumes the run with a recorded decision (R20)
      Then the run state is EXECUTING
      And cycle "remaining" stays REJECTED
      And a new PLANNED cycle covers Rule "Remaining balance" with retry_of set to cycle "remaining"

  Rule: R13 moves the run to verification when every cycle is accepted

    @AC-ORC-01f @integration @P1 @cov-happy-path
    Scenario Outline: When R13 applies
      Given <situation>
      When "sentinel next leave-balance --json" is run
      Then the run state is <state>
      Examples:
        | situation                                                                                | state       |
        | all three cycles are CYCLE_ACCEPTED                                                      | VERIFYING   |
        | two cycles are CYCLE_ACCEPTED and "request-form" is REFACTOR_VERIFIED with full evidence | VERIFYING   |
        | two cycles are CYCLE_ACCEPTED and "request-form" is GREEN_RUNNING                        | EXECUTING   |
        | the run is at tier 4, all cycles are CYCLE_ACCEPTED and the hardener task is RUNNING     | EXECUTING   |
        | the run is at tier 4, all cycles are CYCLE_ACCEPTED and the hardener task is COMPLETED   | VERIFYING   |

    @AC-ORC-01g @integration @P1 @cov-authz
    Scenario: Nobody but the engine can request verification
      Given two cycles are CYCLE_ACCEPTED and "request-form" is GREEN_RUNNING
      When the orchestrator asks the engine to move "leave-balance" to VERIFYING
      Then the request is refused with error "E_ACTOR"
      And the run state is still EXECUTING

    @AC-ORC-01h @unit @P2 @cov-happy-path
    Scenario: A docs-only run reaches verification without cycles
      Given a version 2 docs-only run "leave-docs" in state EXECUTING whose docs task is COMPLETED
      When the engine checks R13 for "leave-docs"
      Then the run state is VERIFYING
      And no cycle exists for "leave-docs"

    @AC-ORC-01i @integration @P1 @cov-data-integrity
    Scenario: A Gherkin edit at the last moment wins over R13
      Given all three cycles are CYCLE_ACCEPTED
      And features/balance.feature was edited after the Gherkin approval
      When "sentinel next leave-balance --json" is run
      Then the run state is GHERKIN_REVIEW by R18
      And no "run.state_changed" event to VERIFYING is stored

  Rule: Cycles in different repos run at once; overlapping scopes never do

    @AC-AGT-07p @integration @P1 @cov-concurrency
    Scenario: Two cycles in different repos run in parallel
      Given policies.max_parallel_tasks is 2
      And the tdd_green task of cycle "remaining" and the tdd_red task of cycle "request-form" are QUEUED
      And both fake CLIs sleep 2 seconds and then succeed
      When "sentinel task run" is run for both tasks at the same time
      Then both tasks were RUNNING at the same moment
      And each engine test run used only its own repo
      And cycle "remaining" is GREEN_VERIFIED and cycle "request-form" is RED_VERIFIED

    @AC-AGT-07q @integration @P1 @cov-concurrency
    Scenario: A task overlapping a running cycle task waits
      Given policies.max_parallel_tasks is 2
      And the tdd_green task of cycle "remaining" is RUNNING with write scope "backend/src/main/**"
      And a "hardener" task is QUEUED with write scope "backend/**"
      When "sentinel task run" is run for the hardener task
      Then it exits with code 5
      And the error is "E_PRECONDITION" naming the tdd_green task and the glob pair
      And the hardener task is still QUEUED

    @AC-AGT-07r @integration @P1 @cov-concurrency
    Scenario: Two cycles in one repo never run at once
      Given policies.max_parallel_tasks is 4
      And the tdd_green task of cycle "remaining" is RUNNING
      When "sentinel task run" is run for the tdd_red task of cycle "carry-over"
      Then it exits with code 5
      And the error is "E_TRANSITION" naming the open dependency on cycle "remaining"

    @AC-AGT-07s @integration @P2 @cov-boundary
    Scenario: The parallel limit still applies to disjoint cycles
      Given policies.max_parallel_tasks is 1
      And the tdd_green task of cycle "remaining" is RUNNING
      When "sentinel task run" is run for the tdd_red task of cycle "request-form"
      Then it exits with code 5
      And the error is "E_PRECONDITION" naming "max_parallel_tasks 1"

  Rule: An invalidated approval stops open cycles and their tasks

    @AC-SM-05f @integration @P1 @cov-data-integrity
    Scenario Outline: R17 and R18 cancel running TDD tasks
      Given cycle "carry-over" is CYCLE_ACCEPTED
      And the tdd_green task of cycle "remaining" is RUNNING with a fake CLI that sleeps for 60 seconds
      And the tdd_red task of cycle "request-form" is QUEUED
      When <file> is edited and the engine applies <rule>
      Then the run state is <state>
      And the tdd_green and tdd_red tasks are CANCELLED by the engine with reason "approval invalidated"
      And the fake CLI of the tdd_green task is not alive within 15 seconds
      And cycles "remaining" and "request-form" are REJECTED with reason "approval invalidated"
      And cycle "carry-over" is still CYCLE_ACCEPTED
      And the changes in backend are left in place
      Examples:
        | file                     | rule | state                |
        | spec.md                  | R17  | SPECIFICATION_REVIEW |
        | features/balance.feature | R18  | GHERKIN_REVIEW       |

    @AC-SM-05g @integration @P1 @cov-data-integrity
    Scenario Outline: Re-approval keeps accepted cycles whose scenarios did not change
      Given cycle "carry-over" is CYCLE_ACCEPTED and the run went to GHERKIN_REVIEW by R18 after <edit>
      When the human approves the new Gherkin version and the engine advances "leave-balance"
      Then the run state is EXECUTING
      And cycle "carry-over" is <carry_over>
      And a new PLANNED cycle covers Rule "Remaining balance"
      Examples:
        | edit                                                   | carry_over                                       |
        | a step of "Employee sees remaining days" was reworded  | still CYCLE_ACCEPTED and not replanned           |
        | a step of "Unused days carry over" was reworded        | kept as history and a new PLANNED cycle covers it |

  Rule: An interrupted cycle resumes from persisted state

    @AC-ORC-07d @integration @P1 @cov-db-failure
    Scenario: Sentinel dies after a task but before verification
      Given the tdd_green task of cycle "remaining" is COMPLETED and cycle "remaining" is GREEN_RUNNING with no green evidence row
      And the Sentinel process that ran it was killed with SIGKILL
      When "sentinel next leave-balance --json" is run
      Then the engine runs the targeted tests and stores the green evidence row
      And cycle "remaining" is GREEN_VERIFIED
      And the tdd_green task was not run again

  Rule: Existing behavior is unchanged

    @AC-CFG-11a @unit @P1 @cov-regression
    Scenario: A config without tdd keys or glob overrides stays valid
      Given the sentinel.config.yaml of Sentinel 0.1 with no "tdd" key and no repos[].test_globs
      When the config is validated
      Then validation passes
      And tdd.red_retries, tdd.green_retries and tdd.refactor_retries resolve to 2, 3 and 2

    @AC-TST-01c @integration @P1 @cov-regression
    Scenario: Existing checks stay green
      When "python3 sentinel/scripts/selftest.py" and "python3 -m unittest discover -s tests" are run
      Then the 95 baseline selftest checks pass
      And every Phase A, Phase B and Phase C test passes
