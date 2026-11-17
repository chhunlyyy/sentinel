@REQ-SM-02 @REQ-C-29
Feature: Execution status and acceptance status are separate
  A run can finish executing and still fail acceptance.

  Rule: Two independent statuses

    @AC-SM-02a @unit @P1
    Scenario: A new run is running and pending acceptance
      When the orchestrator creates version 2 run "leave-balance"
      Then the execution status is "running"
      And the acceptance status is "pending"

    @AC-SM-02b @unit @P1
    Scenario: A run that completes with missing evidence is rejected
      Given a version 2 run "leave-balance" in state REVIEWING
      And the run has no verification evidence
      When the engine completes the run
      Then the run state is COMPLETED
      And the execution status is "completed"
      And the acceptance status is "rejected"
      And the rejection reasons include "verification evidence missing"

    @AC-SM-02c @unit @P1 @cov-authz
    Scenario: The orchestrator cannot set the acceptance status
      Given a version 2 run "leave-balance" in state COMPLETED with acceptance status "rejected"
      When the orchestrator sets the acceptance status to "accepted"
      Then the request is refused with error "E_ACTOR"
      And the acceptance status is "rejected"

    @AC-SM-02d @unit @P1 @cov-authz
    Scenario: A human cannot turn a rejected run into an accepted one
      Given a version 2 run "leave-balance" in state COMPLETED with acceptance status "rejected"
      When a human at a terminal accepts the run
      Then the request is refused with error "E_PRECONDITION"
      And the acceptance status is "rejected"

  Rule: The legacy outcome keeps working

    @AC-SM-02e @integration @P1 @cov-regression
    Scenario Outline: run finish maps the outcome onto both statuses
      Given a version 2 run "leave-balance" in state <state>
      When "sentinel run finish leave-balance --outcome <outcome>" is run by a human
      Then the execution status is "<execution>"
      And the acceptance status is "<acceptance>"
      Examples:
        | state     | outcome   | execution | acceptance |
        | EXECUTING | stopped   | cancelled | rejected   |
        | EXECUTING | abandoned | cancelled | rejected   |
        | COMPLETED | passed    | completed | unchanged  |

    @AC-SM-02f @integration @P2 @cov-invalid-input
    Scenario: run finish passed on an unfinished version 2 run is refused
      Given a version 2 run "leave-balance" in state EXECUTING
      When "sentinel run finish leave-balance --outcome passed" is run
      Then it exits with code 5
      And the error is "E_PRECONDITION"
