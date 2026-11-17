@REQ-TDD-04 @REQ-TDD-05 @REQ-VER-02
Feature: Green and Refactor phases
  Green writes production code until the approved tests pass, and never changes them. Refactor
  improves production code while the targeted and related tests keep passing. The engine runs
  the tests itself; agent claims never decide.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree
    And repo "backend" uses the test profile "fake-junit" with test_globs ["src/test/**"] and production_globs ["src/main/**"]
    And sentinel.config.yaml sets single_model false, agents.tdd_green and agents.tdd_refactor to runner "fake", tdd.green_retries 3 and tdd.refactor_retries 2
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 on repo "backend" with both approvals valid
    And cycle "remaining" is RED_VERIFIED with the approved test file backend/src/test/java/leave/RemainingBalanceTest.java and its sha256 stored

  Rule: Green makes the approved tests pass without touching them

    @AC-TDD-04a @integration @P1 @cov-happy-path
    Scenario: Green passes and Refactor can begin
      Given runners.fake is a fake CLI that edits backend/src/main/java/leave/LeaveBalance.java, writes a valid result.json and exits 0
      And the fake test tool reports both targeted tests passing
      When "sentinel task run" is run for the tdd_green task of cycle "remaining"
      Then it exits with code 0
      And cycle "remaining" moved GREEN_RUNNING, GREEN_VERIFIED
      And one evidence row of kind "green" holds the targeted command, exit code 0, passed 2 and failed 0
      And the changed file backend/src/main/java/leave/LeaveBalance.java is stored for the green phase with its sha256 before and after
      And the tdd_refactor task of cycle "remaining" is QUEUED

    @AC-TDD-04b @integration @P1 @cov-authz
    Scenario Outline: Green changing approved tests is rejected
      Given runners.fake is a fake CLI that edits backend/src/main/java/leave/LeaveBalance.java and <action>, then exits 0
      When "sentinel task run" is run for the tdd_green task of cycle "remaining"
      Then it exits with code 3
      And the tdd_green task is FAILED with error code "E_SCOPE" and a violation of kind <kind> listing <listed>
      And the engine ran no test command for this attempt
      And no retry tdd_green task is created
      And cycle "remaining" is GREEN_RUNNING and the run state is NEEDS_HUMAN
      And the changes are left in place
      Examples:
        | action                                                                   | kind                    | listed                                                   |
        | edits backend/src/test/java/leave/RemainingBalanceTest.java              | "approved_test_changed" | "backend/src/test/java/leave/RemainingBalanceTest.java"  |
        | deletes backend/src/test/java/leave/RemainingBalanceTest.java            | "approved_test_changed" | "backend/src/test/java/leave/RemainingBalanceTest.java"  |
        | renames backend/src/test/java/leave/RemainingBalanceTest.java to Old.java | "approved_test_changed" | "backend/src/test/java/leave/RemainingBalanceTest.java"  |
        | creates backend/src/test/java/leave/ExtraTest.java                       | "outside_write_scope"   | "backend/src/test/java/leave/ExtraTest.java"             |

    @AC-TDD-04c @integration @P2 @cov-boundary
    Scenario: An approved test rewritten with the same bytes is not a change
      Given runners.fake is a fake CLI that edits backend/src/main/java/leave/LeaveBalance.java and rewrites backend/src/test/java/leave/RemainingBalanceTest.java with identical bytes, then exits 0
      And the fake test tool reports both targeted tests passing
      When "sentinel task run" is run for the tdd_green task of cycle "remaining"
      Then it exits with code 0
      And cycle "remaining" is GREEN_VERIFIED

    @AC-TDD-04d @integration @P1 @cov-errors
    Scenario: Failing targeted tests send the work back to Green
      Given runners.fake is a fake CLI that edits backend/src/main/java/leave/LeaveBalance.java, writes a valid result.json and exits 0
      And the fake test tool reports "RemainingBalanceTest.balanceNeverBelowZero" failing
      When "sentinel task run" is run for the tdd_green task of cycle "remaining"
      Then it exits with code 1
      And the tdd_green task is COMPLETED and its green evidence row is rejected with reason "targeted tests fail: RemainingBalanceTest.balanceNeverBelowZero"
      And cycle "remaining" is still GREEN_RUNNING
      And a retry tdd_green task is QUEUED whose brief names the failing test and "attempt 2 of 4"

    @AC-TDD-04e @integration @P1 @cov-data-integrity
    Scenario: A claim that the tests passed is not evidence
      Given runners.fake is a fake CLI that edits backend/src/main/java/leave/LeaveBalance.java and writes a valid result.json claiming the command "./gradlew test" with exit code 0
      And the fake test tool reports "RemainingBalanceTest.employeeSeesRemainingDays" failing
      When "sentinel task run" is run for the tdd_green task of cycle "remaining"
      Then the engine ran the targeted tests itself
      And cycle "remaining" is still GREEN_RUNNING
      And the task report flags the claimed command as differing from the green evidence row

    @AC-TDD-04f @integration @P1 @cov-data-integrity
    Scenario: An approved test changed between Red and Green stops the cycle
      Given backend/src/test/java/leave/RemainingBalanceTest.java was edited by hand after RED_VERIFIED
      When the engine dispatches the tdd_green task of cycle "remaining"
      Then the dispatch is refused with error "E_INTEGRITY" naming the file
      And an "integrity_failed" audit row is stored
      And the tdd_green task is not started and the run state is NEEDS_HUMAN

  Rule: Refactor keeps the targeted and related tests passing

    @AC-TDD-05a @integration @P1 @cov-happy-path
    Scenario: A refactor that keeps the tests green is accepted
      Given cycle "remaining" is GREEN_VERIFIED and its tdd_refactor task is QUEUED
      And runners.fake is a fake CLI that renames a method in backend/src/main/java/leave/LeaveBalance.java, writes a valid result.json and exits 0
      And the fake test tool reports the targeted and related tests passing
      When "sentinel task run" is run for the tdd_refactor task
      Then it exits with code 0
      And cycle "remaining" moved REFACTOR_RUNNING, REFACTOR_VERIFIED, CYCLE_ACCEPTED
      And one evidence row of kind "refactor" lists the targeted and related test ids it ran

    @AC-TDD-05b @integration @P1 @cov-errors
    Scenario: A refactor that breaks a targeted test is rejected
      Given cycle "remaining" is GREEN_VERIFIED and its tdd_refactor task is QUEUED
      And runners.fake is a fake CLI that edits backend/src/main/java/leave/LeaveBalance.java and exits 0
      And the fake test tool reports "RemainingBalanceTest.employeeSeesRemainingDays" failing
      When "sentinel task run" is run for the tdd_refactor task
      Then it exits with code 1
      And one "refactor.rejected" event names the failing test
      And cycle "remaining" is still REFACTOR_RUNNING
      And a retry tdd_refactor task is QUEUED whose brief names the failing test
      And backend/src/main/java/leave/LeaveBalance.java keeps the refactor's content

    @AC-TDD-05c @integration @P1 @cov-regression
    Scenario: A refactor that breaks an earlier cycle's test is rejected
      Given cycle "carry-over" on repo "backend" is CYCLE_ACCEPTED with the test "CarryOverTest.unusedDaysCarryOver"
      And cycle "remaining" is GREEN_VERIFIED and its tdd_refactor task is QUEUED
      And the fake test tool reports the targeted tests passing and "CarryOverTest.unusedDaysCarryOver" failing
      When "sentinel task run" is run for the tdd_refactor task
      Then cycle "remaining" is still REFACTOR_RUNNING
      And the refactor evidence row is rejected with reason "related tests fail: CarryOverTest.unusedDaysCarryOver"

    @AC-TDD-05d @unit @P2 @cov-boundary
    Scenario Outline: Which tests are related
      Given cycle "remaining" on repo "backend" is GREEN_VERIFIED
      And cycle <other> on repo <repo> is <state>
      When the engine computes the related tests of the refactor of cycle "remaining"
      Then the tests of cycle <other> are included: <included>
      Examples:
        | other          | repo       | state          | included |
        | "carry-over"   | "backend"  | CYCLE_ACCEPTED | yes      |
        | "carry-over"   | "backend"  | PLANNED        | no       |
        | "request-form" | "frontend" | CYCLE_ACCEPTED | no       |

    @AC-TDD-05e @integration @P2 @cov-empty-null
    Scenario: A refactor that changes nothing is still verified by the engine
      Given cycle "remaining" is GREEN_VERIFIED and its tdd_refactor task is QUEUED
      And runners.fake is a fake CLI that changes no file, writes a valid result.json and exits 0
      And the fake test tool reports the targeted and related tests passing
      When "sentinel task run" is run for the tdd_refactor task
      Then cycle "remaining" is CYCLE_ACCEPTED
      And the refactor evidence row has an empty changed-file list and the tests it ran

    @AC-TDD-05f @integration @P1 @cov-authz
    Scenario: A refactor that touches a test file is a scope violation
      Given cycle "remaining" is GREEN_VERIFIED and its tdd_refactor task is QUEUED
      And runners.fake is a fake CLI that edits backend/src/test/java/leave/RemainingBalanceTest.java and exits 0
      When "sentinel task run" is run for the tdd_refactor task
      Then it exits with code 3
      And the tdd_refactor task is FAILED with error code "E_SCOPE" and kind "approved_test_changed"
      And the run state is NEEDS_HUMAN
