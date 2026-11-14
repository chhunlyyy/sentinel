@REQ-SPA-04 @REQ-SPA-05 @REQ-SPA-06 @REQ-SPA-07 @REQ-GHA-05 @REQ-SEC-03 @REQ-SEC-07 @REQ-VIS-01
Feature: Human review and approval at a terminal
  Every tier needs two human approvals: the specification first, then the Gherkin.
  A CLI approval needs an interactive terminal and the typed 8-character hash prefix.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And the OS user is "dev" and git user.name is "Dev User"

  Rule: Review shows the artifact, its hash, the diff and the warnings

    @AC-SPA-04a @integration @P1 @cov-happy-path
    Scenario: Reviewing a revised specification
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW at tier 3
      And specification version 1 had changes requested and version 2 is in review
      When "sentinel review leave-balance spec" is run
      Then it exits with code 0
      And the output shows the text of specification version 2
      And the output shows the full sha256 of version 2
      And the output shows the diff from version 1 to version 2
      And the output lists the validation warnings of version 2

    @AC-SPA-04b @integration @P2 @cov-boundary
    Scenario: Reviewing a first version has no diff
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW with specification version 1 only
      When "sentinel review leave-balance spec" is run
      Then the output says "no previous reviewed version"

    @AC-GHA-05a @integration @P1 @cov-happy-path
    Scenario: Reviewing the Gherkin set
      Given a version 2 run "leave-balance" in state GHERKIN_REVIEW
      When "sentinel review leave-balance gherkin" is run
      Then the output lists every feature file and every scenario with its tags
      And the output shows the coverage table with its warnings
      And the output shows the full set hash of Gherkin version 1

    @AC-SPA-04c @integration @P2 @cov-invalid-input
    Scenario Outline: Review refuses bad arguments
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW
      When "sentinel review <slug> <gate>" is run
      Then it exits with code <code>
      And the error is <error>
      Examples:
        | slug          | gate     | code | error         |
        | leave-balance | tests    | 2    | usage         |
        | no-such-run   | spec     | 5    | "E_NOT_FOUND" |

  Rule: Approving at a terminal with the typed hash prefix records the decision

    @AC-SPA-06a @integration @P1 @cov-happy-path
    Scenario: A human approves the specification
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW with specification version 2 in review
      And the sha256 of version 2 starts with "3f9a0c12"
      When a human at a terminal runs "sentinel approve leave-balance spec -m 'Looks right'"
      And the command shows the full sha256 and asks for its first 8 characters
      And the human types "3f9a0c12"
      Then it exits with code 0
      And the run state is SPECIFICATION_APPROVED
      And the specification approval is APPROVED with version 2, the full sha256, decision "approve" and comment "Looks right"
      And the approval records approver OS user "dev", git name "Dev User", channel "tty" and the decision time
      And one "approval.decided" event and one "run.state_changed" event naming transition "R5" are stored
      And one audit row records actor "dev", channel "tty", action "approve", target "leave-balance/specification" and the sha256

    @AC-GHA-05b @integration @P1 @cov-happy-path
    Scenario: A human approves the Gherkin set
      Given a version 2 run "leave-balance" in state GHERKIN_REVIEW with Gherkin version 1 in review
      And the specification approval is still valid
      When a human at a terminal runs "sentinel approve leave-balance gherkin" and types the first 8 characters of the set hash
      Then the run state is GHERKIN_APPROVED
      And the Gherkin approval is APPROVED with version 1 and the full set hash
      And the "run.state_changed" event names transition "R9"

    @AC-SPA-06b @unit @P2 @cov-boundary
    Scenario Outline: The typed prefix is trimmed and case-insensitive
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW whose spec sha256 starts with "3f9a0c12"
      When a human at a terminal runs "sentinel approve leave-balance spec" and types <typed>
      Then the run state is SPECIFICATION_APPROVED
      Examples:
        | typed          |
        | "3f9a0c12"     |
        | "3F9A0C12"     |
        | "  3f9a0c12 "  |

  Rule: Both approvals are needed at every tier and config cannot remove them

    @AC-SPA-07a @unit @P1 @cov-regression
    Scenario Outline: Specification approval alone never starts execution
      Given a version 2 run "<slug>" of type feature in state SPECIFICATION_REVIEW at tier <tier>
      And a human has approved the specification at a terminal
      When the engine requests state EXECUTING
      Then the request is refused with error "E_TRANSITION"
      And the run state is still SPECIFICATION_APPROVED
      Examples:
        | slug          | tier |
        | fix-typo      | 1    |
        | leave-balance | 2    |
        | leave-balance | 3    |
        | leave-balance | 4    |

    @AC-SPA-07b @unit @P1 @cov-authz
    Scenario: An empty human_required policy keeps both gates
      Given sentinel.config.yaml sets policies.human_required to an empty list
      And a version 2 run "fix-typo" of type feature at tier 1
      When the run is driven forward with no human decision
      Then the run stops in SPECIFICATION_REVIEW
      And after a human approves the specification the run stops in GHERKIN_REVIEW

  Rule: Request changes and reject send the work back or end the run

    @AC-SPA-05a @integration @P1 @cov-happy-path
    Scenario: Requesting specification changes returns the run to the specifier
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW with specification version 1 in review
      When a human at a terminal runs "sentinel approve leave-balance spec --request-changes -m 'Add the half-day case'" and types the hash prefix
      Then the run state is PLANNED
      And the specification approval for version 1 is CHANGES_REQUESTED with comment "Add the half-day case"
      And the next specifier brief contains "Add the half-day case"
      And the "run.state_changed" event names transition "R6"

    @AC-SPA-05b @integration @P1 @cov-missing-fields
    Scenario Outline: Requesting changes needs a comment
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW
      When a human at a terminal runs "sentinel approve leave-balance spec <flags>"
      Then it exits with code 5
      And the error is "E_VALIDATION"
      And no hash prompt is shown
      And the run state is still SPECIFICATION_REVIEW
      Examples:
        | flags                      |
        | --request-changes          |
        | --request-changes -m ''    |
        | --request-changes -m '  '  |

    @AC-SPA-05c @integration @P1 @cov-happy-path
    Scenario: A revised specification is reviewed again
      Given a version 2 run "leave-balance" in state PLANNED after changes were requested on specification version 1
      When the specifier task completes with a valid specification version 2
      Then the run state is SPECIFICATION_REVIEW
      And a new specification approval in state IN_REVIEW references version 2
      And the approval for version 1 is still CHANGES_REQUESTED
      And "sentinel review leave-balance spec" shows the diff from version 1

    @AC-SPA-05d @integration @P1
    Scenario Outline: Rejecting either artifact cancels the run
      Given a version 2 run "leave-balance" in state <state>
      When a human at a terminal runs "sentinel approve leave-balance <gate> --reject -m 'Out of scope'" and types the hash prefix
      Then the run state is CANCELLED
      And the <gate_name> approval is REJECTED
      And the execution status is "cancelled" and the acceptance status is "rejected"
      And the slug lock for "leave-balance" is released
      And the "run.state_changed" event names transition "<transition>"
      Examples:
        | state                | gate    | gate_name     | transition |
        | SPECIFICATION_REVIEW | spec    | specification | R7         |
        | GHERKIN_REVIEW       | gherkin | Gherkin       | R11        |

    @AC-GHA-05c @integration @P1 @cov-happy-path
    Scenario: Requesting Gherkin changes returns the run to the test designer
      Given a version 2 run "leave-balance" in state GHERKIN_REVIEW with Gherkin version 1 in review
      When a human at a terminal runs "sentinel approve leave-balance gherkin --request-changes -m 'Add a negative balance case'" and types the hash prefix
      Then the run state is SPECIFICATION_APPROVED
      And the Gherkin approval for version 1 is CHANGES_REQUESTED
      And the specification approval is still APPROVED
      And the next test_designer brief contains "Add a negative balance case"
      And the "run.state_changed" event names transition "R10"

  Rule: Only a human at an interactive terminal can decide

    @AC-SEC-03a @integration @P1 @cov-authz
    Scenario Outline: A non-interactive call is refused
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW
      When "sentinel approve leave-balance spec <flags>" is run with stdin not a terminal
      Then it exits with code 5
      And the error is "E_NOT_TTY"
      And no hash prompt is shown
      And the specification approval is still IN_REVIEW
      And the run state is still SPECIFICATION_REVIEW
      And one audit row records action "approve_refused" with reason "E_NOT_TTY"
      Examples:
        | flags                           |
        |                                 |
        | --request-changes -m 'x'        |
        | --reject -m 'x'                 |

    @AC-SEC-03b @integration @P1 @cov-authz
    Scenario: An agent process launched by Sentinel cannot approve
      Given a version 2 run "leave-balance" in state GHERKIN_REVIEW
      And a task process launched by Sentinel with no terminal attached
      When that process runs "sentinel approve leave-balance gherkin"
      Then it exits with code 5
      And the error is "E_NOT_TTY"
      And the run state is still GHERKIN_REVIEW

    @AC-SEC-03c @integration @P1 @cov-authz
    Scenario Outline: A wrong hash prefix is refused
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW whose spec sha256 starts with "3f9a0c12"
      When a human at a terminal runs "sentinel approve leave-balance spec" and types <typed>
      Then it exits with code 5
      And the error is "E_VALIDATION"
      And the specification approval is still IN_REVIEW
      And the run state is still SPECIFICATION_REVIEW
      Examples:
        | typed        |
        | "00000000"   |
        | "3f9a0c1"    |
        | "3f9a0c13"   |
        | "3f9a0c12ab" |
        | ""           |

    @AC-SEC-03d @integration @P2 @cov-errors
    Scenario: Closing the prompt without typing stores nothing
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW
      When a human at a terminal runs "sentinel approve leave-balance spec" and ends input at the prompt
      Then it exits with code 1
      And the specification approval is still IN_REVIEW
      And no "approval.decided" event is stored

    @AC-VIS-01a @unit @P1 @cov-authz
    Scenario Outline: The engine refuses a decision from a non-human actor
      Given a version 2 run "leave-balance" in state <state>
      When the <actor> submits decision "approve" for gate "<gate>" with the correct full hash
      Then the request is refused with error "E_ACTOR"
      And the run state is still <state>
      Examples:
        | state                | gate          | actor        |
        | SPECIFICATION_REVIEW | specification | orchestrator |
        | SPECIFICATION_REVIEW | specification | engine       |
        | GHERKIN_REVIEW       | gherkin       | orchestrator |

    @AC-SEC-04a @integration @P2 @cov-authz
    Scenario: Generated agent configs forbid approve and accept
      Given a workspace with runner "claude" configured
      When "sentinel sync-adapters" is run
      Then the generated Claude settings deny "sentinel approve" and "sentinel accept" commands
      And the generated agent instructions state that agents never run "sentinel approve" or "sentinel accept"

  Rule: A decision is only possible on an artifact in review

    @AC-SPA-06c @unit @P1 @cov-invalid-input
    Scenario Outline: Approving in the wrong state is refused
      Given a version 2 run "leave-balance" in state <state>
      When a human at a terminal runs "sentinel approve leave-balance <gate>" and types the hash prefix
      Then it exits with code 5
      And the error is "E_TRANSITION"
      And the run state is still <state>
      Examples:
        | state                  | gate    |
        | PLANNED                | spec    |
        | SPECIFICATION_REVIEW   | gherkin |
        | GHERKIN_APPROVED       | spec    |
        | EXECUTING              | gherkin |

    @AC-SPA-06d @unit @P1 @cov-duplicate
    Scenario: A second approval of the same version is refused
      Given a version 2 run "leave-balance" whose specification version 2 was just approved at a terminal
      When a human at a terminal runs "sentinel approve leave-balance spec" again and types the same hash prefix
      Then it exits with code 5
      And the error is "E_TRANSITION"
      And exactly one "approval.decided" event exists for specification version 2

    @AC-SPA-06e @integration @P1 @cov-regression
    Scenario: A 0.1 run has no approval gates
      Given a workspace with a 0.1 run "old-run" at tier 2
      When a human at a terminal runs "sentinel approve old-run spec"
      Then it exits with code 5
      And the error is "E_TRANSITION"
      And the file state.json of "old-run" is byte-for-byte unchanged

  Rule: Approvals are written atomically and only once under concurrency

    @AC-SPA-06f @integration @P1 @cov-concurrency
    Scenario: Two terminals approve the same specification at once
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW
      When two humans at two terminals approve the specification at the same time with the correct prefix
      Then exactly one command exits with code 0
      And the other exits with code 5 and error "E_TRANSITION"
      And exactly one "approval.decided" event and one "approve" audit row exist for the specification

    @AC-SPA-06g @integration @P2 @cov-concurrency
    Scenario: Approve and request changes race
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW
      When one terminal approves and another requests changes at the same time
      Then exactly one decision is stored
      And the run state is SPECIFICATION_APPROVED if the approval won, or PLANNED if the change request won

    @AC-SPA-06h @unit @P1 @cov-db-failure
    Scenario: A failed event write leaves the approval undecided
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW
      And the event store fails on the next write
      When a human at a terminal approves the specification with the correct prefix
      Then the command fails
      And the specification approval is still IN_REVIEW
      And the run state is still SPECIFICATION_REVIEW
      And no audit row for the approval is stored
