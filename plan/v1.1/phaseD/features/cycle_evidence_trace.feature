@REQ-TDD-06 @REQ-TRC-01 @REQ-TRC-02 @REQ-SEC-06
Feature: Cycle evidence and trace links
  Every phase of a cycle leaves evidence rows written by the engine. A cycle is accepted only
  when that evidence is complete and intact. Trace links chain requirement, criterion, scenario,
  cycle, tests, changed files and evidence.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repo "backend" is a git repo with a clean working tree
    And repo "backend" uses the test profile "fake-junit" with test_globs ["src/test/**"] and production_globs ["src/main/**"]
    And sentinel.config.yaml sets single_model false and agents.tdd_red, agents.tdd_green and agents.tdd_refactor to runner "fake" with model "fake-model"
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 on repo "backend" with both approvals valid
    And the approved spec links REQ-2 to AC-3 and AC-4, and scenario "Employee sees remaining days" is tagged with AC-3 and "Balance never goes below zero" with AC-4
    And cycle "remaining" covers Rule "Remaining balance" of features/balance.feature

  Rule: The engine writes complete evidence for every phase

    @AC-TDD-06a @integration @P1 @cov-happy-path
    Scenario: An accepted cycle holds full evidence
      Given cycle "remaining" ran Red, Green and Refactor with fake CLIs and the fake test tool
      When cycle "remaining" is CYCLE_ACCEPTED
      Then evidence rows of kind "red", "green" and "refactor" exist for cycle "remaining"
      And each row holds command, cwd, exit_code, classification, passed, failed, skipped, started_at, finished_at, env and repo_sha
      And each row's started_at is not after its finished_at
      And each row links a stored output file and the sha256 of that file
      And each row names its task id, provider "fake" and model "fake-model"
      And the changed files of each phase are stored with path and sha256 before and after
      And the cycle row stores the red, green and refactor task ids and accepted_at

    @AC-TDD-06b @unit @P1 @cov-missing-fields
    Scenario Outline: Incomplete evidence blocks acceptance
      Given cycle "remaining" is REFACTOR_VERIFIED
      And <gap>
      When the engine tries to move cycle "remaining" to CYCLE_ACCEPTED
      Then the move is refused with error "E_PRECONDITION" listing <item>
      And cycle "remaining" is still REFACTOR_VERIFIED
      And the run state is NEEDS_HUMAN with reason "evidence incomplete for cycle remaining"
      Examples:
        | gap                                                | item                  |
        | the red evidence row is missing                     | "red evidence"        |
        | the green evidence row has no output file           | "green output"        |
        | the refactor evidence row has no repo_sha           | "refactor repo_sha"   |
        | the changed-file rows of the green phase are missing | "green changed files" |
        | the red evidence row has classification "compile"   | "red classification"  |

    @AC-TDD-06c @integration @P1 @cov-data-integrity
    Scenario: A changed evidence output file is an integrity failure
      Given cycle "remaining" is REFACTOR_VERIFIED with complete evidence
      And the stored output file of the green evidence row is edited
      When the engine tries to move cycle "remaining" to CYCLE_ACCEPTED
      Then the move is refused with error "E_INTEGRITY"
      And an "integrity_failed" audit row is stored
      And the run state is NEEDS_HUMAN

    @AC-TDD-06d @integration @P1 @cov-perf-security
    Scenario: Captured test output is scrubbed before it is stored
      Given the fake test tool prints "password=hunter2" and "AKIAABCDEFGHIJKLMNOP" during the Red run of cycle "remaining"
      When the red evidence row is stored
      Then its stored output file does not contain "hunter2" or "AKIAABCDEFGHIJKLMNOP"
      And the output sha256 in the row is the sha256 of the scrubbed file
      And no file under .sentinel holds the unscrubbed output

    @AC-TDD-06e @unit @P1 @cov-authz
    Scenario: Agent results never create evidence rows
      Given the tdd_green task of cycle "remaining" returns a valid result.json with claimed_commands and claimed_changed_files
      When the engine finishes the task
      Then every evidence row of cycle "remaining" was written by the engine's own test run
      And the claimed changed files differ from the git changes and are flagged in the task report

    @AC-TDD-06f @unit @P2 @cov-db-failure
    Scenario: A failed evidence write leaves the cycle where it was
      Given cycle "remaining" is GREEN_RUNNING and the targeted tests pass
      And writing the green evidence row fails with a database error
      When the engine verifies Green of cycle "remaining"
      Then cycle "remaining" is still GREEN_RUNNING
      And no "cycle.state_changed" event to GREEN_VERIFIED is stored
      And "sentinel next leave-balance --json" verifies Green again from the persisted task

  Rule: Trace links chain each requirement to its evidence

    @AC-TRC-01a @integration @P1 @cov-happy-path
    Scenario: An accepted cycle completes the trace chain
      Given cycle "remaining" is CYCLE_ACCEPTED
      When the trace of "leave-balance" is read from the registry
      Then it holds the chain:
        | from_kind | from_id                                                 | to_kind   | to_id                                                  |
        | req       | REQ-2                                                   | ac        | AC-3                                                   |
        | ac        | AC-3                                                    | scenario  | features/balance.feature :: Employee sees remaining days |
        | scenario  | features/balance.feature :: Employee sees remaining days | cycle     | cycle "remaining"                                      |
        | scenario  | features/balance.feature :: Employee sees remaining days | test      | RemainingBalanceTest.employeeSeesRemainingDays          |
        | cycle     | cycle "remaining"                                       | test_file | backend/src/test/java/leave/RemainingBalanceTest.java  |
        | cycle     | cycle "remaining"                                       | file      | backend/src/main/java/leave/LeaveBalance.java          |
        | cycle     | cycle "remaining"                                       | evidence  | the red, green and refactor evidence ids               |

    @AC-TRC-01b @unit @P1 @cov-data-integrity
    Scenario Outline: Links are added as the cycle moves
      When cycle "remaining" reaches <state>
      Then the links from cycle "remaining" are of kinds <kinds>
      Examples:
        | state          | kinds                                 |
        | PLANNED        | none (only scenario to cycle exists)  |
        | RED_VERIFIED   | test_file                             |
        | GREEN_VERIFIED | test_file and file                    |
        | CYCLE_ACCEPTED | test_file, file and evidence          |

    @AC-TRC-01c @unit @P2 @cov-duplicate
    Scenario: A retried Red replaces its test links
      Given the first Red attempt of cycle "remaining" was rejected after linking test "RemainingBalanceTest.old"
      When the retry Red attempt is verified with the tests of AC-TDD-02a
      Then no link to "RemainingBalanceTest.old" remains
      And each scenario of cycle "remaining" has exactly one link per current test

  Rule: Gaps are reported apart from failures

    @AC-TRC-02a @unit @P1 @cov-errors
    Scenario: The trace report separates gaps and failures
      Given cycle "remaining" is REJECTED after its Green cap
      And cycle "carry-over" is PLANNED with no test yet
      When the engine builds the trace report of "leave-balance"
      Then "gaps" lists "features/balance.feature :: Unused days carry over" with "no test" and cycle "carry-over" with "no evidence"
      And "failures" lists cycle "remaining" with "rejected: Green cap reached"
      And no item appears in both lists
