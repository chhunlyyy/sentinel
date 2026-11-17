@REQ-SPA-08 @REQ-GHA-05 @REQ-GHA-06 @REQ-ART-01 @REQ-ORC-06
Feature: Artifact hashing, stale approvals and invalidation
  An approval holds only for the exact bytes the human saw.
  Any change to an approved artifact invalidates the approval and sends the run back to review.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder

  Rule: Hashes are sha256 over raw bytes, the Gherkin set in path order

    @AC-ART-01a @unit @P1 @cov-happy-path
    Scenario: The spec hash is the sha256 of the file bytes
      Given specs/leave-balance/spec.md holds exactly the 3 bytes "abc"
      When the engine hashes the specification of "leave-balance"
      Then the hash is "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    @AC-GHA-05d @unit @P1 @cov-data-integrity
    Scenario Outline: The Gherkin set hash covers path and bytes of every feature file
      Given specs/leave-balance/features holds <files>
      When the engine hashes the Gherkin set of "leave-balance"
      Then the hash is "<hash>"
      Examples:
        | files                                                                          | hash                                                             |
        | a.feature with "Feature: A" and LF, b.feature with "Feature: B" and LF          | 55133db39e515460c49c08d68269d97b894480c28a0128b5f71102a985b2961f |
        | a.feature with "Feature: A" and CRLF, b.feature with "Feature: B" and LF        | b88a68a0997f7b88ee807fc488c754537003b6032330eaae60dbb64bf4ac4d30 |
        | c.feature with "Feature: A" and LF, b.feature with "Feature: B" and LF          | f60aa394be8808985a51b3b9f438d222930ed6ab603bccaa6da99fd1ceedbf38 |
        | a.feature with "Feature: A" LF "Feature: B" LF                                 | 704e1bc94339c6136561786edc81d5cee464d9ea02c1f1dc4adf3e0bf8c26130 |

    @AC-GHA-05e @unit @P2 @cov-boundary
    Scenario: Creation order does not change the set hash
      Given b.feature with "Feature: B" and LF is written before a.feature with "Feature: A" and LF
      When the engine hashes the Gherkin set of "leave-balance"
      Then the hash is "55133db39e515460c49c08d68269d97b894480c28a0128b5f71102a985b2961f"

    @AC-GHA-05f @unit @P2 @cov-boundary
    Scenario Outline: Which files count in the set
      Given a Gherkin set with hash H for "leave-balance"
      When <change> under specs/leave-balance/features
      Then the set hash is <result>
      Examples:
        | change                                   | result       |
        | notes.md is added                        | still H      |
        | admin/approve.feature is added           | different    |
        | balance.feature is renamed to leave.feature | different |
        | balance.feature only has its mtime changed | still H      |

  Rule: A decision must match the current bytes

    @AC-SPA-08a @integration @P1 @cov-data-integrity
    Scenario: The specification changed after it was shown for review
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW with specification version 2 in review
      And "sentinel review leave-balance spec" showed a hash starting with "3f9a0c12"
      And then specs/leave-balance/spec.md was edited
      When a human at a terminal runs "sentinel approve leave-balance spec" and types "3f9a0c12"
      Then it exits with code 5
      And the error is "E_APPROVAL_STALE"
      And the output shows the new hash
      And specification version 3 is stored and a new approval for version 3 is IN_REVIEW
      And no approval is APPROVED
      And the run state is SPECIFICATION_REVIEW

    @AC-GHA-05g @integration @P1 @cov-data-integrity
    Scenario: The Gherkin set changed after it was shown for review
      Given a version 2 run "leave-balance" in state GHERKIN_REVIEW with Gherkin version 1 in review
      And a scenario was added to features/balance.feature after the review was shown
      When a human at a terminal approves the Gherkin with the prefix of version 1
      Then the error is "E_APPROVAL_STALE"
      And Gherkin version 2 is stored and its approval is IN_REVIEW
      And the run state is GHERKIN_REVIEW

    @AC-SPA-08b @integration @P1 @cov-concurrency
    Scenario: The file changes between the prompt and the typed confirmation
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW
      And a human at a terminal ran "sentinel approve leave-balance spec" and sees the prompt
      When specs/leave-balance/spec.md is edited by another process
      And the human types the prefix shown in the prompt
      Then the error is "E_APPROVAL_STALE"
      And no approval is APPROVED

    @AC-GHA-05h @unit @P1 @cov-data-integrity
    Scenario: A dashboard-style full-hash decision must also match
      Given a version 2 run "leave-balance" in state GHERKIN_REVIEW with Gherkin version 2 in review
      When a human submits decision "approve" for gate "gherkin" through the engine with the full hash of version 1
      Then the request is refused with error "E_APPROVAL_STALE"
      And the run state is still GHERKIN_REVIEW

  Rule: A spec change after approval invalidates both approvals and returns to specification review

    @AC-SPA-08c @unit @P1 @cov-data-integrity
    Scenario Outline: A spec edit in any active state after approval triggers R17
      Given a version 2 run "leave-balance" in state <state> with specification version 2 approved
      And the Gherkin approval is <gherkin_before>
      And specs/leave-balance/spec.md is edited
      When the engine loads run "leave-balance"
      Then the run state is SPECIFICATION_REVIEW
      And the "run.state_changed" event names transition "R17"
      And the specification approval for version 2 is INVALIDATED with reason "spec hash changed"
      And the Gherkin approval is <gherkin_after>
      And specification version 3 is stored and its approval is IN_REVIEW
      Examples:
        | state                  | gherkin_before | gherkin_after                                                      |
        | SPECIFICATION_APPROVED | absent         | absent                                                             |
        | GHERKIN_REVIEW         | IN_REVIEW      | INVALIDATED with reason "upstream specification approval invalidated" |
        | GHERKIN_APPROVED       | APPROVED       | INVALIDATED with reason "upstream specification approval invalidated" |
        | EXECUTING              | APPROVED       | INVALIDATED with reason "upstream specification approval invalidated" |
        | VERIFYING              | APPROVED       | INVALIDATED with reason "upstream specification approval invalidated" |
        | REVIEWING              | APPROVED       | INVALIDATED with reason "upstream specification approval invalidated" |
        | NEEDS_HUMAN            | APPROVED       | INVALIDATED with reason "upstream specification approval invalidated" |

    @AC-SPA-08d @unit @P1 @cov-regression
    Scenario: Both gates must be passed again after a spec change
      Given a version 2 run "leave-balance" returned to SPECIFICATION_REVIEW by R17 with unchanged feature files
      When a human approves specification version 3 at a terminal
      Then the run state is SPECIFICATION_APPROVED
      And the old Gherkin approval is still INVALIDATED
      And the Gherkin set is validated again against specification version 3 before a new Gherkin review opens
      And the engine refuses state EXECUTING with error "E_TRANSITION"

    @AC-SPA-08e @unit @P1 @cov-boundary
    Scenario Outline: Only a byte change invalidates
      Given a version 2 run "leave-balance" in state GHERKIN_APPROVED with both approvals valid
      When specs/leave-balance/spec.md gets this change: <change>
      And the engine loads run "leave-balance"
      Then the run state is <state>
      Examples:
        | change                                       | state                |
        | only the mtime is changed                    | GHERKIN_APPROVED     |
        | the same bytes are written again             | GHERKIN_APPROVED     |
        | one trailing space is added                  | SPECIFICATION_REVIEW |
        | line endings are converted from LF to CRLF   | SPECIFICATION_REVIEW |

    @AC-SPA-08f @unit @P1 @cov-empty-null
    Scenario: A deleted specification after approval invalidates and blocks approval
      Given a version 2 run "leave-balance" in state GHERKIN_APPROVED with both approvals valid
      And specs/leave-balance/spec.md is deleted
      When the engine loads run "leave-balance"
      Then the run state is SPECIFICATION_REVIEW
      And both approvals are INVALIDATED
      And "sentinel review leave-balance spec" shows the error "specs/leave-balance/spec.md not found"
      And "sentinel approve leave-balance spec" at a terminal is refused with error "E_VALIDATION"

    @AC-SPA-08g @unit @P2 @cov-invalid-input
    Scenario: A changed specification that no longer validates cannot be approved
      Given a version 2 run "leave-balance" in state GHERKIN_APPROVED with both approvals valid
      And the "Acceptance criteria" section is removed from specs/leave-balance/spec.md
      When the engine loads run "leave-balance"
      Then the run state is SPECIFICATION_REVIEW
      And "sentinel approve leave-balance spec" at a terminal is refused with error "E_VALIDATION" listing "missing section: Acceptance criteria"

  Rule: A Gherkin change after approval invalidates only the Gherkin approval

    @AC-GHA-05i @unit @P1 @cov-data-integrity
    Scenario Outline: A Gherkin edit after approval triggers R18
      Given a version 2 run "leave-balance" in state <state> with both approvals valid
      And <change> under specs/leave-balance/features
      When the engine loads run "leave-balance"
      Then the run state is GHERKIN_REVIEW
      And the "run.state_changed" event names transition "R18"
      And the Gherkin approval for version 1 is INVALIDATED with reason "Gherkin hash changed"
      And the specification approval is still APPROVED
      And Gherkin version 2 is stored and its approval is IN_REVIEW
      Examples:
        | state            | change                                       |
        | GHERKIN_APPROVED | a scenario is added to balance.feature       |
        | EXECUTING        | a Then step in balance.feature is reworded   |
        | VERIFYING        | request_form.feature is deleted              |
        | REVIEWING        | balance.feature is renamed to leave.feature  |

    @AC-GHA-05j @unit @P2 @cov-regression
    Scenario: A non-feature file under features changes nothing
      Given a version 2 run "leave-balance" in state EXECUTING with both approvals valid
      And notes.md is added under specs/leave-balance/features
      When the engine loads run "leave-balance"
      Then the run state is still EXECUTING
      And no "approval.invalidated" event is stored

  Rule: Execution starts only with both approvals valid by hash

    @AC-GHA-06a @unit @P1 @cov-happy-path
    Scenario: Both approvals valid start execution
      Given a version 2 run "leave-balance" in state GHERKIN_APPROVED with both approvals valid
      When the engine advances "leave-balance"
      Then the run state is EXECUTING
      And the "run.state_changed" event names transition "R12"

    @AC-GHA-06b @unit @P1 @cov-data-integrity
    Scenario: A feature file edited just before execution blocks it
      Given a version 2 run "leave-balance" in state GHERKIN_APPROVED with both approvals valid
      And features/balance.feature is edited
      When the engine advances "leave-balance"
      Then the run state is GHERKIN_REVIEW
      And the run never entered EXECUTING

    @AC-GHA-06c @unit @P1 @cov-db-failure
    Scenario: A missing approval record sends the run to a human
      Given a version 2 run "leave-balance" in state GHERKIN_APPROVED
      And the registry holds no APPROVED Gherkin approval for the run
      When the engine advances "leave-balance"
      Then the transition is refused with error "E_APPROVAL_MISSING"
      And the run state is NEEDS_HUMAN with reason "Gherkin approval missing"

  Rule: Tampering with stored copies or approval records is an integrity failure

    @AC-ART-01b @unit @P1 @cov-data-integrity
    Scenario: The stored copy of a version in review was modified
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW with specification version 2 in review
      And the stored copy of version 2 under .sentinel/runs/leave-balance/artifacts/ was modified
      When a human at a terminal approves the specification with the correct prefix
      Then it exits with code 5
      And the error is "E_INTEGRITY"
      And the specification approval is still IN_REVIEW
      And one audit row records action "integrity_failed" for "leave-balance/specification"

    @AC-ART-01c @unit @P1 @cov-data-integrity
    Scenario: An approval record whose hash does not match its artifact version
      Given a version 2 run "leave-balance" in state GHERKIN_APPROVED
      And the stored sha256 of the Gherkin approval was changed so it no longer matches Gherkin version 1
      When the engine advances "leave-balance"
      Then the transition is refused with error "E_INTEGRITY"
      And the run state is NEEDS_HUMAN with reason "approval record does not match artifact"

    @AC-ART-01d @unit @P2 @cov-data-integrity
    Scenario: Reading a stored artifact checks its hash
      Given a version 2 run "leave-balance" with specification version 2 stored
      And the stored copy of version 2 was modified
      When "sentinel review leave-balance spec" is run
      Then it exits with code 5
      And the error is "E_INTEGRITY"

  Rule: Legacy runs and earlier phases are untouched

    @AC-ORC-08d @integration @P1 @cov-regression
    Scenario: Editing a 0.1 run's spec changes no state
      Given a workspace with a 0.1 run "old-run" at tier 2 whose next stage is "coder"
      When specs/old-run/spec.md is edited
      And "sentinel resume old-run" is run
      Then resume names "coder" as the next stage
      And no artifact version, approval or "approval.invalidated" event exists for "old-run"
      And the file state.json of "old-run" is byte-for-byte unchanged

    @AC-TST-01a @integration @P1 @cov-regression
    Scenario: Existing checks stay green
      Given the Phase B code is installed
      When "python3 sentinel/scripts/selftest.py" is run
      Then the 95 baseline checks and every Phase A check pass
      And every Phase A unit test in tests/ passes
