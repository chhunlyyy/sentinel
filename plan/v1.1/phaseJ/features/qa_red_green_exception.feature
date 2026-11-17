@REQ-TDD-09 @REQ-TDD-04 @REQ-TDD-05 @REQ-TDD-06 @REQ-TRC-01 @REQ-VER-03 @REQ-ART-01
Feature: Green against the same scenarios, evidence, the recorded exception and acceptance
  After a QA-Red, Green must make the same scenarios pass, with the same unchanged scripts. The
  cycle is accepted only with complete evidence for all three phases, and the run, the evidence,
  the report and the acceptance reasons all record that QA scenarios replaced a test file.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repo "frontend" with role "frontend" is a git repo with a clean working tree and the test profile "fake-junit"
    And rules.no_permanent_frontend_tests is true and the fake QA driver is configured
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 on repo "frontend" with both approvals valid
    And cycle "Request form" with scenarios "AC-LB-01" and "AC-LB-02" is RED_VERIFIED by QA-Red with approved scripts

  Rule: Green and Refactor reuse the approved scripts

    @AC-TDD-09s @integration @P1 @cov-happy-path
    Scenario: Green makes the failing scenarios pass and the cycle is accepted
      Given the fake CLIs change only src/main files and the fake QA driver passes both scenarios after Green and Refactor
      When the orchestrator loops "sentinel next leave-balance --json" and runs each "task" step with "sentinel task run"
      Then cycle "Request form" moved RED_VERIFIED, GREEN_RUNNING, GREEN_VERIFIED, REFACTOR_RUNNING, REFACTOR_VERIFIED, CYCLE_ACCEPTED
      And the green evidence row has kind "green", method "qa_scenario", classification "pass" and lists the scenarios that passed
      And the repo has no test file and no Playwright or runner config left behind

    @AC-TDD-09t @integration @P1 @cov-authorization
    Scenario: Green gets the approved scripts read-only and no test glob
      When the tdd_green task of cycle "Request form" is created
      Then its write scope is the production globs of the repo only
      And its read-only list holds the approved scripts and their folder under the QA cache
      And its brief gives the scenario steps and says the scripts are the specification

    @AC-TDD-09u @integration @P1 @cov-errors
    Scenario Outline: Green is rejected for a result that is not a clean pass
      Given the fake QA driver run after Green ends with <result>
      When the engine verifies the tdd_green task
      Then the green evidence row is "rejected" with classification "<class>"
      And a retry tdd_green task is created with a brief naming <what>
      Examples:
        | result                                       | class       | what                            |
        | scenario "AC-LB-02" still failing at a Then step | assertion | scenario AC-LB-02               |
        | a scenario missing from the report           | unbound_scenario | the missing scenario        |
        | both scenarios skipped                       | unbound_scenario | the skipped scenarios        |

    @AC-TDD-09v @integration @P1 @cov-errors
    Scenario: A driver error during Green is not an agent failure
      Given the fake QA driver reports "app_not_running" after Green on both runs
      When the engine verifies the tdd_green task
      Then the run is NEEDS_HUMAN with the reason naming the class and the cycle stays GREEN_RUNNING
      And no retry tdd_green task is created

    @AC-TDD-09w @integration @P1 @cov-data-integrity
    Scenario Outline: A changed script after QA-Red stops the cycle
      Given the approved script of cycle "Request form" is <change> after Red
      When the engine verifies a phase of the cycle
      Then the engine refuses with error "E_INTEGRITY" and an "integrity_failed" audit row, and the run is NEEDS_HUMAN
      Examples:
        | change                                 |
        | edited by the Green agent              |
        | deleted                                |
        | replaced by a script with the same name and another hash |

    @AC-TDD-09x @integration @P2 @cov-happy-path
    Scenario: Refactor runs the scripts again and must keep them green
      Given cycle "Request form" is GREEN_VERIFIED and the fake QA driver fails scenario "AC-LB-01" after Refactor
      When the engine verifies the tdd_refactor task
      Then the refactor evidence row is "rejected" and a retry tdd_refactor task is created

  Rule: Evidence rows and trace links

    @AC-TRC-03a @integration @P1 @cov-happy-path
    Scenario: A QA-Red cycle has the full chain from scenario to evidence
      Given cycle "Request form" is CYCLE_ACCEPTED
      Then scenario "AC-LB-01" links to the cycle, to the QA script entry ".sentinel/cache/qa/tests/current/leave-balance/<cycle id>/AC-LB-01.spec" and to the cycle's red, green and refactor evidence rows
      And the cycle has no link of kind "test_file" and no scenario has a link of kind "test"
      And "sentinel trace leave-balance" shows no gap for these scenarios

    @AC-TRC-03b @integration @P1 @cov-errors
    Scenario: A missing QA script link is a trace gap, not a failure
      Given the link scenario "AC-LB-02" to its QA script entry was removed from the registry
      When the trace report is built
      Then it lists a gap "scenario AC-LB-02 has no QA script link" apart from the failures

    @AC-TDD-09y @unit @P1 @cov-data-integrity
    Scenario: The red evidence row of a QA-Red cycle carries the exception
      Given cycle "Request form" is RED_VERIFIED by QA-Red
      Then the red evidence row has method "qa_scenario" and exception {"rule":"no_permanent_frontend_tests","replaced":"test_file","by":"qa_scenario","repo":"frontend"}
      And green and refactor rows of the cycle have method "qa_scenario" and the same exception reference
      And a "tdd.exception_recorded" event names the cycle, the evidence id, the rule, the scenario keys and actor kind "engine"

    @AC-TDD-09z @unit @P1 @cov-duplicate
    Scenario: The exception is recorded once per cycle, not once per retry
      Given Red was rejected twice and accepted on attempt 3
      Then exactly one "tdd.exception_recorded" event exists for the cycle and it names the accepted evidence row

    @AC-VER-05a @integration @P1 @cov-errors
    Scenario Outline: The cycle is not accepted with incomplete QA-Red evidence
      Given cycle "Request form" is REFACTOR_VERIFIED
      And <gap>
      When the engine tries to accept the cycle
      Then the cycle stays REFACTOR_VERIFIED, the run is NEEDS_HUMAN and the error is "<code>"
      And the reason includes "<missing>"
      Examples:
        | gap                                                    | code            | missing                    |
        | the red row has no method                              | E_PRECONDITION  | red method                 |
        | the red row has no script manifest                     | E_PRECONDITION  | red scripts                |
        | the red row has no exception field                     | E_PRECONDITION  | red exception              |
        | no "tdd.exception_recorded" event exists               | E_PRECONDITION  | red exception event        |
        | the green row lists fewer scenarios than the cycle has | E_PRECONDITION  | green scenarios            |
        | the red output file was edited                         | E_INTEGRITY     | red output                 |
        | the red row classification is "pass"                   | E_PRECONDITION  | red classification         |

    @AC-VER-05b @integration @P1 @cov-happy-path
    Scenario: The accepted cycle holds all three rows and the links
      When cycle "Request form" is accepted by the engine
      Then it is CYCLE_ACCEPTED and holds trace links to the accepted red, green and refactor evidence rows
      And a "cycle.state_changed" event to CYCLE_ACCEPTED carries red_method "qa_scenario"

  Rule: Acceptance and the report record the exception

    @AC-VER-05c @integration @P1 @cov-happy-path
    Scenario: A completed run reports the exception and is still accepted
      Given the run is REVIEWING with every verification check passed and cycle "Request form" CYCLE_ACCEPTED by QA-Red
      When "sentinel next leave-balance --json" is run
      Then the acceptance status is "accepted" and report.json holds "tdd_exceptions" with one entry
      And the entry has the repo, the cycle, the rule, the method "qa_scenario", the red evidence id, the green evidence id, the scenario count, the scenarios failed before Green and the script hashes
      And report.md has a section "TDD exceptions" listing the entry and the sentence "QA scenarios were the Red evidence; no test files were committed"

    @AC-VER-05d @integration @P1 @cov-errors
    Scenario Outline: Missing exception evidence rejects the run with its own reason
      Given the run is REVIEWING and ready for R15 and <gap>
      When the engine computes acceptance for "leave-balance"
      Then the result is "rejected" and the reasons include "tdd exception evidence missing: frontend Request form"
      Examples:
        | gap                                                     |
        | the "tdd.exception_recorded" event of the cycle is missing |
        | the exception field of the red row was removed            |
        | the script hashes of the red row no longer match the QA cache files |

    @AC-VER-05e @integration @P1 @cov-regression
    Scenario: The hygiene rule applies to the whole frontend repo without an exception
      Given the run is VERIFYING and a stray file frontend/src/Form.test.ts exists in the repo
      When "sentinel verify leave-balance" is run
      Then the "hygiene" row of "frontend" fails with "test infrastructure left behind: src/Form.test.ts"
      And no approved cycle file is skipped because the cycle has no approved test file

    @AC-VER-05f @integration @P1 @cov-regression
    Scenario: Rule off keeps the interim hygiene behavior for test-file cycles
      Given rules.no_permanent_frontend_tests is true only on a client repo whose cycle has red_method "test_file" from an older run
      When "sentinel verify leave-balance" is run
      Then the hygiene row still skips that cycle's approved test files as in the existing TDD_09 tests
      And a stray unapproved test file still fails the row

    @AC-ART-04a @integration @P1 @cov-happy-path
    Scenario: The report is reproducible and shows the exception from the registry alone
      Given a completed run with a QA-Red cycle
      When "sentinel report leave-balance" is run twice
      Then both outputs are byte-identical and the "TDD exceptions" section matches the registry rows

    @AC-ART-04b @integration @P2 @cov-empty
    Scenario: A run with no exception has no empty section
      Given a completed run whose cycles all have red_method "test_file"
      When "sentinel report leave-balance" is run
      Then report.json has "tdd_exceptions" equal to [] and report.md has no "TDD exceptions" heading

    @AC-ART-04c @integration @P2 @cov-happy-path
    Scenario: Export and import keep the exception
      Given a completed run with a QA-Red cycle
      When a human exports the run and imports the bundle into a fresh workspace
      Then the imported cycle has red_method "qa_scenario" and the evidence rows keep method, exception and script hashes
      And the QA script files are not in the bundle and the report lists them as "not exported"

    @AC-TDD-09aa @api @P2 @cov-happy-path
    Scenario: The existing TDD and verification answers expose the method
      Given cycle "Request form" is CYCLE_ACCEPTED by QA-Red
      When "GET /api/runs/leave-balance/tdd" and "GET /api/runs/leave-balance/verification" are requested with a valid token
      Then each cycle object has "red_method" and an "exception" object or null
      And no new endpoint exists and no field holds a secret or a script body

  Rule: Invalidation, caps and concurrency

    @AC-ORC-09f @integration @P1 @cov-data-integrity
    Scenario Outline: An invalidated approval stops open QA-Red cycles
      Given cycle "Request form" is <state> and its qa_red or tdd task is RUNNING
      When the <gate> approval is INVALIDATED by a changed file hash
      Then the run moves by <rule> and the running task is cancelled
      And the cycle is REJECTED with reason "approval invalidated"
      And the QA script files stay in the QA cache and are never used again for the cycle
      Examples:
        | state       | gate          | rule |
        | RED_RUNNING | specification | R17  |
        | RED_RUNNING | Gherkin       | R18  |
        | GREEN_RUNNING | Gherkin     | R18  |

    @AC-ORC-09g @integration @P1 @cov-data-integrity
    Scenario: Re-approved Gherkin replans QA-Red only for changed groups
      Given the Gherkin was changed in the scenarios of "Request form" only and approved again
      When the run enters EXECUTING again (R12)
      Then a new cycle "Request form" is planned with red_method "qa_scenario" and the old row stays as history
      And the unchanged accepted cycles keep their evidence and their exception event
      And exactly one "tdd.exception_planned" event exists for the new cycle

    @AC-ORC-09h @integration @P1 @cov-concurrency
    Scenario: Two groups of one client repo wait for each other as for tests
      Given cycles "Request form" and "Balance card" are both on repo "frontend"
      When the orchestrator asks for the next tasks
      Then the qa_red task of "Balance card" is QUEUED behind cycle "Request form" with the blocker "cycle <id>"

    @AC-ORC-09i @integration @P1 @cov-concurrency
    Scenario: QA driver runs of different cycles never overlap
      Given repos "frontend" and "mobile" with role "mobile" each have one QA-Red cycle and both qa_red tasks COMPLETED at once
      When two engine processes verify the two tasks
      Then the driver runs are serialized by the QA driver lock and their evidence time windows do not overlap
      And neither run reports a port-in-use or "app_not_running" failure and both red rows are accepted

    @AC-ORC-09j @integration @P1 @cov-concurrency
    Scenario: Two verify calls for the same task write one evidence row
      Given the qa_red task of cycle "Request form" is COMPLETED
      When two processes call the verify of that task at the same time
      Then exactly one evidence row of kind "red" exists for the task and the other call is refused with "E_LOCKED"

    @AC-ORC-09k @integration @P2 @cov-errors
    Scenario: A killed engine during the QA run is recovered
      Given the engine process is killed while the driver runs for the qa_red task
      When "sentinel next leave-balance --json" is run again
      Then the stale driver lock does not block it, the driver runs again once and a single evidence row of kind "red" results

    @AC-SM-06a @integration @P1 @cov-regression
    Scenario: Cycle and run state machines are unchanged
      When the cycle and run transition tables are read
      Then they hold the same states and moves as before Phase J and the QA-Red cycle uses only PLANNED, RED_RUNNING, RED_VERIFIED, GREEN_RUNNING, GREEN_VERIFIED, REFACTOR_RUNNING, REFACTOR_VERIFIED, CYCLE_ACCEPTED and REJECTED

    @AC-TST-06a @integration @P1 @cov-regression
    Scenario: A bug run reproduces the bug as a QA scenario
      Given a version 2 run "leave-bug" of type "bug" with one frontend behavior group and the rule on
      When the first cycle runs its QA-Red
      Then the qa_red brief starts with "Reproduce the reported bug" and the red evidence row is accepted only for a failing Then step
