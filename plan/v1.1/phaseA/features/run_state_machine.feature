@REQ-ORC-01 @REQ-SM-01
Feature: Run state machine refuses anything not in the transition table
  Sentinel, not the orchestrator, decides when a run changes state.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder

  Rule: Defined transitions move the run and record an event in one step

    @AC-ORC-01a @unit @P1
    Scenario: Orchestrator triages a newly created run
      Given a version 2 run "leave-balance" in state CREATED
      When the orchestrator submits triage factors for "leave-balance"
      Then the run state is TRIAGED
      And exactly one "run.state_changed" event from CREATED to TRIAGED is stored
      And the event names the actor kind "orchestrator"

    @AC-ORC-01b @unit @P1 @cov-data-integrity
    Scenario: A failure while writing the event leaves the state unchanged
      Given a version 2 run "leave-balance" in state CREATED
      And the event store fails on the next write
      When the orchestrator submits triage factors for "leave-balance"
      Then the command fails
      And the run state is still CREATED
      And no new event is stored

  Rule: Undefined transitions are refused

    @AC-ORC-01c @unit @P1 @cov-invalid-input
    Scenario Outline: Jumping over the gates is refused
      Given a version 2 run "leave-balance" in state <from>
      When the orchestrator requests state <to>
      Then the request is refused with error "E_TRANSITION"
      And the run state is still <from>
      Examples:
        | from                   | to                     |
        | CREATED                | EXECUTING              |
        | TRIAGED                | SPECIFICATION_APPROVED |
        | SPECIFICATION_REVIEW   | GHERKIN_REVIEW         |
        | SPECIFICATION_APPROVED | EXECUTING              |
        | GHERKIN_REVIEW         | EXECUTING              |

    @AC-ORC-01d @unit @P1 @cov-invalid-input
    Scenario Outline: A finished run cannot move again
      Given a version 2 run "leave-balance" in state <final>
      When the orchestrator requests state TRIAGED
      Then the request is refused with error "E_TRANSITION"
      Examples:
        | final     |
        | COMPLETED |
        | FAILED    |
        | CANCELLED |

    @AC-ORC-01e @unit @P2 @cov-invalid-input
    Scenario: An unknown state name is refused
      Given a version 2 run "leave-balance" in state CREATED
      When the orchestrator requests state "DONE"
      Then the request is refused with error "E_TRANSITION"

  Rule: Only the allowed actor can perform a transition

    @AC-ORC-02a @unit @P1 @cov-authz
    Scenario: The orchestrator cannot approve a specification
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW
      When the orchestrator requests state SPECIFICATION_APPROVED
      Then the request is refused with error "E_ACTOR"
      And the run state is still SPECIFICATION_REVIEW

    @AC-ORC-02b @unit @P1 @cov-authz
    Scenario: The orchestrator cannot cancel a run
      Given a version 2 run "leave-balance" in state EXECUTING
      When the orchestrator requests state CANCELLED
      Then the request is refused with error "E_ACTOR"

    @AC-ORC-02c @unit @P1 @cov-happy-path
    Scenario: A human can cancel an active run
      Given a version 2 run "leave-balance" in state EXECUTING
      When a human at a terminal requests state CANCELLED
      Then the run state is CANCELLED
      And the execution status is "cancelled"
      And the slug lock for "leave-balance" is released

  Rule: Preconditions are checked by the engine

    @AC-ORC-03a @unit @P1 @cov-missing-fields
    Scenario: A tier 3 run cannot be planned without recorded decisions
      Given a version 2 run "leave-balance" in state TRIAGED at tier 3
      And the run has no decisions.md file
      When the orchestrator requests state PLANNED
      Then the request is refused with error "E_PRECONDITION"
      And the error lists "decisions.md"

    @AC-ORC-03b @unit @P2 @cov-happy-path
    Scenario: A tier 1 run can be planned without decisions
      Given a version 2 run "fix-typo" in state TRIAGED at tier 1
      When the orchestrator requests state PLANNED
      Then the run state is PLANNED

  Rule: The tier is computed by the engine and only rises

    @AC-ORC-04a @unit @P1 @cov-boundary
    Scenario Outline: The engine takes the highest tier among the factors
      Given a version 2 run "leave-balance" in state CREATED
      When the orchestrator submits factors <factors> and requests tier <requested>
      Then the run tier is <tier>
      Examples:
        | factors                                   | requested | tier |
        | repos=1, files=1                          | 1         | 1    |
        | repos=1, files=2                          | 1         | 2    |
        | repos=1, files=2, auth=new_rules          | 2         | 4    |
        | repos=2, files=1                          | 4         | 4    |

    @AC-ORC-04b @unit @P1 @cov-invalid-input
    Scenario: Lowering the tier after triage is refused
      Given a version 2 run "leave-balance" at tier 3
      When the orchestrator asks to set tier 2
      Then the request is refused with error "E_POLICY"
      And the run tier is 3
