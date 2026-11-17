@REQ-TDD-02 @REQ-TDD-03 @REQ-VER-02
Feature: Red phase: binding to approved scenarios and failure classification
  Red writes tests for the scenarios of its cycle and nothing else. The engine runs the tests
  itself and classifies the result. Only assertion failures of the new tests, with no new
  failure elsewhere compared with the baseline, verify Red.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree
    And repo "backend" uses the test profile "fake-junit" with test_globs ["src/test/**"] and production_globs ["src/main/**"]
    And the profile "fake-junit" has failure_patterns compile ["error: cannot find symbol"], environment ["Connection refused"] and missing_dependency ["Could not resolve"]
    And the profile "fake-junit" has scenario_ref pattern '@Scenario\("([^"]+)"\)'
    And sentinel.config.yaml sets single_model false, agents.tdd_red to runner "fake" and tdd.red_retries 2
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 on repo "backend" with both approvals valid
    And the approved Gherkin set holds features/balance.feature with Rule "Remaining balance" (scenarios "Employee sees remaining days" and "Balance never goes below zero") and Rule "Carry-over" (scenario "Unused days carry over")
    And the baseline of repo "backend" has the failing set ["LegacyTest.flaky"]
    And cycle "remaining" covers Rule "Remaining balance" and its tdd_red task is QUEUED

  Rule: Red is verified only by assertion failures of the new tests

    @AC-TDD-03c @integration @P1 @cov-happy-path
    Scenario: Red produces the expected assertion failures
      Given runners.fake is a fake CLI that writes backend/src/test/java/leave/RemainingBalanceTest.java with two tests, each referencing one scenario of cycle "remaining", writes a valid result.json and exits 0
      And the fake test tool reports both new tests failing with assertion errors and "LegacyTest.flaky" failing
      When "sentinel task run" is run for the tdd_red task
      Then it exits with code 0
      And the tdd_red task is COMPLETED
      And cycle "remaining" moved PLANNED, RED_RUNNING, RED_VERIFIED with one "cycle.state_changed" event per move
      And one evidence row of kind "red" holds the targeted command, a non-zero exit code, classification "assertion" and failed 2
      And the evidence row lists the new failing tests "RemainingBalanceTest.employeeSeesRemainingDays" and "RemainingBalanceTest.balanceNeverBelowZero"
      And backend/src/test/java/leave/RemainingBalanceTest.java is stored as an approved test file of cycle "remaining" with its sha256
      And the tdd_green task of cycle "remaining" is QUEUED

    @AC-TDD-03d @integration @P1 @cov-errors
    Scenario Outline: Classification and routing of a Red run
      Given runners.fake is a fake CLI that writes backend/src/test/java/leave/RemainingBalanceTest.java referencing both scenarios and exits 0
      And the fake test tool <outcome>
      When "sentinel task run" is run for the tdd_red task
      Then the red evidence row has classification "<class>"
      And cycle "remaining" is <cycle_state>
      And a retry tdd_red task is created: <retry>
      And the run state is <run_state>
      And it exits with code <code>
      Examples:
        | outcome                                                                         | class               | cycle_state | retry | run_state   | code |
        | exits 1 with "error: cannot find symbol" before tests ran                       | compile             | PLANNED     | yes   | EXECUTING   | 1    |
        | exits 1 with "Could not resolve com.acme:leave-core:1.0"                        | missing_dependency  | PLANNED     | yes   | EXECUTING   | 1    |
        | exits 1 with "Connection refused" while the new tests run                       | environment         | PLANNED     | yes   | EXECUTING   | 1    |
        | reports only "LegacyTest.flaky" failing and the new tests absent from the report | preexisting_failure | PLANNED     | yes   | EXECUTING   | 1    |
        | exits 139 with no report and "Segmentation fault"                               | unknown             | RED_RUNNING | no    | NEEDS_HUMAN | 6    |
        | reports the new tests as errors, not failures, and no pattern matches           | unknown             | RED_RUNNING | no    | NEEDS_HUMAN | 6    |

    @AC-TDD-03e @unit @P2 @cov-boundary
    Scenario Outline: Classification precedence when several signals appear
      Given a Red test run whose output and report show <signals>
      When the engine classifies it against the baseline of repo "backend"
      Then the classification is "<class>"
      Examples:
        | signals                                                                        | class              |
        | build exit 1 with "error: cannot find symbol" and also "Connection refused"    | compile            |
        | "Could not resolve" and "Connection refused"                                    | missing_dependency |
        | "Connection refused" and new tests failing with assertion errors               | environment        |
        | new tests failing with assertion errors and "LegacyTest.flaky" failing         | assertion          |

    @AC-TDD-03f @unit @P1 @cov-errors
    Scenario: The retry brief carries the classified output
      Given the first Red attempt of cycle "remaining" was classified "compile" with the output line "RemainingBalanceTest.java:12: error: cannot find symbol"
      When the engine creates the retry tdd_red task
      Then its brief.md names the classification "compile", the output line, and "attempt 2 of 3"
      And its task row has retry_of set to the first tdd_red task

    @AC-TDD-03g @integration @P1 @cov-regression
    Scenario: A new failure outside the new tests rejects Red
      Given runners.fake is a fake CLI that writes backend/src/test/java/leave/RemainingBalanceTest.java referencing both scenarios and exits 0
      And the fake test tool reports both new tests failing with assertion errors and "BalanceServiceTest.total" failing, which passed at baseline
      When "sentinel task run" is run for the tdd_red task
      Then cycle "remaining" is PLANNED
      And the red evidence row is rejected with reason "new failure outside the new tests: BalanceServiceTest.total"
      And a retry tdd_red task is created

    @AC-TDD-03h @unit @P2 @cov-boundary
    Scenario: A baseline failure that now passes does not block Red
      Given the new tests fail with assertion errors and "LegacyTest.flaky" now passes
      When the engine verifies Red of cycle "remaining"
      Then cycle "remaining" is RED_VERIFIED

  Rule: Red must fail before Green starts

    @AC-TDD-03i @integration @P1 @cov-errors
    Scenario: New tests that already pass are refused
      Given runners.fake is a fake CLI that writes backend/src/test/java/leave/RemainingBalanceTest.java referencing both scenarios and exits 0
      And the fake test tool reports both new tests passing
      When "sentinel task run" is run for the tdd_red task
      Then it exits with code 1
      And cycle "remaining" is PLANNED with reason "new tests pass before Green: RemainingBalanceTest.employeeSeesRemainingDays, RemainingBalanceTest.balanceNeverBelowZero"
      And no tdd_green task exists for cycle "remaining"
      And a retry tdd_red task is created with that reason in its brief

    @AC-TDD-03j @unit @P1 @cov-boundary
    Scenario: One passing new test refuses Red even if the other fails
      Given the new test "RemainingBalanceTest.employeeSeesRemainingDays" fails with an assertion error
      And the new test "RemainingBalanceTest.balanceNeverBelowZero" passes
      When the engine verifies Red of cycle "remaining"
      Then cycle "remaining" is PLANNED with reason naming "RemainingBalanceTest.balanceNeverBelowZero"

    @AC-TDD-03k @integration @P2 @cov-empty-null
    Scenario: A Red task that changes no test file is refused
      Given runners.fake is a fake CLI that writes only a valid result.json claiming "tests written" and exits 0
      When "sentinel task run" is run for the tdd_red task
      Then cycle "remaining" is PLANNED with reason "no test file changed"
      And the claim in result.json is kept in the task report and flagged as differing from the evidence

  Rule: Red binds every test to an approved scenario of its cycle

    @AC-TDD-02a @integration @P1 @cov-happy-path
    Scenario: Tests reference their scenarios by feature path and name
      Given the tests of RemainingBalanceTest.java carry @Scenario("features/balance.feature :: Employee sees remaining days") and @Scenario("features/balance.feature :: Balance never goes below zero")
      When Red of cycle "remaining" is verified
      Then a "scenario" to "test" trace link is stored for each scenario and its test id
      And a "cycle" to "test_file" trace link is stored for backend/src/test/java/leave/RemainingBalanceTest.java

    @AC-TDD-02b @integration @P1 @cov-invalid-input
    Scenario Outline: A binding problem refuses Red
      Given the new tests of cycle "remaining" fail with assertion errors
      And the scenario references in the changed test files are <refs>
      When Red of cycle "remaining" is verified
      Then cycle "remaining" is PLANNED with reason <reason>
      And a retry tdd_red task is created
      Examples:
        | refs                                                                                      | reason                                                                       |
        | only "features/balance.feature :: Employee sees remaining days"                           | "scenario without test: features/balance.feature :: Balance never goes below zero" |
        | both scenarios and "features/balance.feature :: Employee sees all days"                    | "unknown scenario: features/balance.feature :: Employee sees all days"       |
        | both scenarios and "features/balance.feature :: Unused days carry over"                    | "scenario of another cycle: features/balance.feature :: Unused days carry over" |
        | "features/balance.feature :: employee sees remaining days" and the second scenario        | "unknown scenario: features/balance.feature :: employee sees remaining days" |
        | none                                                                                      | "no scenario reference found"                                                |

    @AC-TDD-02c @integration @P1 @cov-authz
    Scenario: Red cannot edit an approved scenario
      Given runners.fake is a fake CLI that rewords a step of features/balance.feature, writes a valid result.json and exits 0
      When "sentinel task run" is run for the tdd_red task
      Then it exits with code 3
      And the tdd_red task is FAILED with error code "E_SCOPE" listing ".sentinel/shared/specs/leave-balance/features/balance.feature"
      And the Gherkin approval is INVALIDATED and the run state is GHERKIN_REVIEW by R18
      And cycle "remaining" is REJECTED with reason "approval invalidated"

    @AC-TDD-02d @integration @P1 @cov-authz
    Scenario Outline: Red writes outside the test globs
      Given runners.fake is a fake CLI that writes backend/src/test/java/leave/RemainingBalanceTest.java and <action>, then exits 0
      When "sentinel task run" is run for the tdd_red task
      Then it exits with code 3
      And the tdd_red task is FAILED with error code "E_SCOPE" listing <listed>
      And the engine ran no test command for this attempt
      And no retry tdd_red task is created
      And cycle "remaining" is RED_RUNNING and the run state is NEEDS_HUMAN
      Examples:
        | action                                              | listed                                            |
        | edits backend/src/main/java/leave/LeaveBalance.java | "backend/src/main/java/leave/LeaveBalance.java"   |
        | edits backend/build.gradle                          | "backend/build.gradle"                            |
        | commits in backend                                  | "backend: HEAD moved"                             |
