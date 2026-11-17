@REQ-SM-03 @REQ-SM-04 @REQ-SM-05
Feature: Task, approval and TDD cycle state machines
  Each record moves only along its own table, and only the allowed actor moves it.

  Rule: Tasks

    @AC-SM-03a @unit @P1
    Scenario Outline: Allowed task transitions
      Given a task in state <from>
      When the <actor> moves it to <to>
      Then the task state is <to>
      Examples:
        | from              | to                | actor  |
        | CREATED           | QUEUED            | engine |
        | QUEUED            | RUNNING           | engine |
        | RUNNING           | WAITING_FOR_INPUT | engine |
        | WAITING_FOR_INPUT | RUNNING           | orchestrator |
        | RUNNING           | COMPLETED         | engine |
        | RUNNING           | FAILED            | engine |
        | QUEUED            | CANCELLED         | human  |

    @AC-SM-03b @unit @P1 @cov-authz
    Scenario: The orchestrator cannot mark a task completed itself
      Given a task in state RUNNING
      When the orchestrator moves it to COMPLETED
      Then the request is refused with error "E_ACTOR"

    @AC-SM-03c @unit @P2 @cov-invalid-input
    Scenario: A completed task cannot be restarted
      Given a task in state COMPLETED
      When the engine moves it to RUNNING
      Then the request is refused with error "E_TRANSITION"

  Rule: Approvals

    @AC-SM-04a @unit @P1 @cov-authz
    Scenario Outline: Only a human decides an approval
      Given an approval in state IN_REVIEW
      When the <actor> moves it to APPROVED
      Then the outcome is <outcome>
      Examples:
        | actor        | outcome            |
        | human        | state APPROVED     |
        | orchestrator | refused E_ACTOR    |
        | engine       | refused E_ACTOR    |

    @AC-SM-04b @unit @P1
    Scenario: The engine can invalidate an approved approval
      Given an approval in state APPROVED
      When the engine moves it to INVALIDATED with reason "hash changed"
      Then the approval state is INVALIDATED
      And the reason "hash changed" is stored

    @AC-SM-04c @unit @P2 @cov-invalid-input
    Scenario: A rejected approval cannot be approved later
      Given an approval in state REJECTED
      When a human moves it to APPROVED
      Then the request is refused with error "E_TRANSITION"

  Rule: TDD cycles

    @AC-SM-05a @unit @P1
    Scenario: A cycle walks red, green, refactor in order
      Given a cycle in state PLANNED
      When the engine moves it through RED_RUNNING, RED_VERIFIED, GREEN_RUNNING, GREEN_VERIFIED, REFACTOR_RUNNING, REFACTOR_VERIFIED and CYCLE_ACCEPTED
      Then every step is accepted
      And the cycle state is CYCLE_ACCEPTED

    @AC-SM-05b @unit @P1 @cov-invalid-input
    Scenario Outline: A cycle cannot skip a phase
      Given a cycle in state <from>
      When the engine moves it to <to>
      Then the request is refused with error "E_TRANSITION"
      Examples:
        | from          | to               |
        | PLANNED       | GREEN_RUNNING    |
        | RED_RUNNING   | GREEN_RUNNING    |
        | RED_VERIFIED  | REFACTOR_RUNNING |
        | GREEN_VERIFIED| CYCLE_ACCEPTED   |

    @AC-SM-05c @unit @P2 @cov-authz
    Scenario: Only the engine moves a cycle
      Given a cycle in state RED_RUNNING
      When the orchestrator moves it to RED_VERIFIED
      Then the request is refused with error "E_ACTOR"
