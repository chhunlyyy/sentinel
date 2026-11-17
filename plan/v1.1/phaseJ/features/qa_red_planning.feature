@REQ-TDD-09 @REQ-CFG-08 @REQ-TDD-01
Feature: QA scenarios as Red evidence: when they apply and when R12 refuses
  With rules.no_permanent_frontend_tests on, a behavior group on a client repo (role "frontend"
  or "mobile") has no permanent test file. Its Red phase is a QA task that runs the group's Gherkin
  scenarios through the configured QA driver, and the engine records the exception. Anything else
  (rule off, backend roles, docs-only runs, 0.1 runs) keeps today's behavior. A missing QA driver
  is refused at R12, never a silent fall back to test files.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" with role "backend" and "frontend" with role "frontend" are git repos with a clean working tree
    And repos "backend" and "frontend" use the test profile "fake-junit" with test_globs ["src/test/**"] and production_globs ["src/main/**"]
    And sentinel.config.yaml sets qa.driver "playwright", qa.scenario_run to the fake QA driver script and qa.scenario_report to "qa-report.xml"
    And a version 2 run "leave-balance" at tier 3 on repos "backend" and "frontend" with both approvals valid
    And the Gherkin approves Rule "Remaining days" tagged @repo-backend and Rule "Request form" tagged @repo-frontend

  Rule: The method is chosen per cycle at R12 and kept for the whole run

    @AC-TDD-09a @integration @P1 @cov-happy-path
    Scenario: A client repo with the rule on plans a QA-Red cycle
      Given rules.no_permanent_frontend_tests is true
      When the run enters EXECUTING (R12)
      Then cycle "Request form" has red_method "qa_scenario" and cycle "Remaining days" has red_method "test_file"
      And the first task of cycle "Request form" has role "qa_red" and the first task of cycle "Remaining days" has role "tdd_red"
      And a "tdd.exception_planned" event names rule "no_permanent_frontend_tests", repo "frontend", the cycle and the scenario keys
      And no "tdd.exception_planned" event exists for repo "backend"

    @AC-TDD-09b @unit @P1 @cov-boundary
    Scenario Outline: The method follows the rule and the repo role
      Given rules.no_permanent_frontend_tests is <rule>
      And repo "frontend" has role "<role>"
      When the run enters EXECUTING (R12)
      Then cycle "Request form" has red_method "<method>"
      Examples:
        | rule  | role     | method      |
        | true  | frontend | qa_scenario |
        | true  | mobile   | qa_scenario |
        | true  | backend  | test_file   |
        | true  | app      | test_file   |
        | false | frontend | test_file   |
        | false | mobile   | test_file   |

    @AC-TDD-09c @integration @P1 @cov-regression
    Scenario: Rule off behaves exactly as before
      Given rules.no_permanent_frontend_tests is false
      When the run enters EXECUTING (R12) and cycle "Request form" runs Red, Green and Refactor with the fake CLIs
      Then every task of the cycle has a role in tdd_red, tdd_green or tdd_refactor
      And the red evidence row has method "test_file" and no exception field
      And no event of kind "tdd.exception_planned" or "tdd.exception_recorded" exists
      And the report has no "TDD exceptions" section

    @AC-TDD-09d @integration @P1 @cov-data-integrity
    Scenario: A config edit after R12 does not change the method of a running run
      Given rules.no_permanent_frontend_tests was true at R12 and cycle "Request form" is PLANNED with red_method "qa_scenario"
      When rules.no_permanent_frontend_tests is set to false in sentinel.config.yaml
      And "sentinel next leave-balance --json" is run
      Then the next task of cycle "Request form" has role "qa_red"
      And the run uses its config snapshot from R12

    @AC-TDD-09e @integration @P2 @cov-boundary
    Scenario: Docs-only runs are unaffected
      Given a version 2 run "docs-refresh" of type "docs" on repo "frontend" with the rule on
      When the run enters EXECUTING (R12)
      Then no cycle is planned and no task has role "qa_red"
      And the docs task is created as before

    @AC-TDD-09f @integration @P1 @cov-regression
    Scenario: Legacy 0.1 runs are untouched
      Given a 0.1 spec folder with a Gherkin file and rules.no_permanent_frontend_tests true
      When "sentinel release-check" and the 0.1 commands are run
      Then no qa_red role, no red_method and no exception event is created
      And the release check output is byte-identical to the output of the commit before Phase J

  Rule: R12 refuses a frontend QA-Red cycle that has no usable QA driver

    @AC-CFG-12a @integration @P1 @cov-errors
    Scenario Outline: A missing or unusable QA driver is refused at R12
      Given rules.no_permanent_frontend_tests is true
      And sentinel.config.yaml has <config>
      When the run tries to enter EXECUTING (R12)
      Then the engine refuses with error "E_PRECONDITION" naming repo "frontend" and "<reason>"
      And the run is NEEDS_HUMAN with that reason, no cycle row is created and no task is created
      And no repo has a test file and the cycle method is not downgraded to "test_file"
      Examples:
        | config                                              | reason                                                   |
        | qa.driver "none"                                    | QA driver is none                                        |
        | no qa section                                       | QA driver is not configured                              |
        | qa.driver "playwright" and no qa.scenario_run       | qa.scenario_run is not configured                        |
        | qa.driver "playwright" and no qa.scenario_report    | qa.scenario_report is not configured                     |
        | no qa.start_commands entry for repo "frontend"      | no QA start command for repo frontend                    |
        | qa.scenario_run pointing to a missing script        | qa.scenario_run does not exist                           |

    @AC-CFG-12b @integration @P1 @cov-errors
    Scenario: The refusal names the way out and does not touch backend cycles
      Given rules.no_permanent_frontend_tests is true and qa.driver is "none"
      When the run tries to enter EXECUTING (R12)
      Then the refusal text says to configure the QA driver or to turn the rule off
      And the audit log has an "engine" row "tdd_exception_refused" for slug "leave-balance"

    @AC-CFG-12c @integration @P2 @cov-happy-path
    Scenario: A human fixes the config and the run resumes with QA-Red
      Given the run is NEEDS_HUMAN after an R12 refusal for a missing qa.scenario_run
      When a human sets qa.scenario_run, takes a new config snapshot through the human resume decision and resumes the run
      Then the run enters EXECUTING and cycle "Request form" has red_method "qa_scenario"

    @AC-CFG-12d @unit @P1 @cov-invalid-input
    Scenario Outline: The new qa keys are validated
      Given sentinel.config.yaml sets <key> to <value>
      When the config is validated
      Then the result is <outcome>
      Examples:
        | key                  | value                      | outcome                              |
        | qa.scenario_run      | "node qa/run.js {scripts}" | valid                                |
        | qa.scenario_run      | ""                         | invalid: qa.scenario_run is empty    |
        | qa.scenario_run      | 5                          | invalid: qa.scenario_run not a string |
        | qa.scenario_report   | "qa-report.xml"            | valid                                |
        | qa.scenario_report   | "../outside.xml"           | invalid: report path leaves the QA folder |
        | qa.unknown_key       | "x"                        | invalid: unknown key                 |

    @AC-CFG-12e @unit @P2 @cov-regression
    Scenario: A config without the new qa keys stays valid
      Given a config with only qa.driver, qa.ports, qa.start_commands, qa.db_clone and qa.fixtures
      When the config is validated and "sentinel release-check" runs
      Then both succeed as before

  Rule: Mixed runs keep one method per repo

    @AC-TDD-09g @integration @P1 @cov-happy-path
    Scenario: A backend cycle and a frontend cycle run side by side
      Given rules.no_permanent_frontend_tests is true
      And fake CLIs that make every phase succeed and a fake QA driver that fails every scenario before Green and passes after
      When the orchestrator loops "sentinel next leave-balance --json" and runs each "task" step with "sentinel task run"
      Then cycle "Remaining days" is CYCLE_ACCEPTED with a red evidence row of method "test_file"
      And cycle "Request form" is CYCLE_ACCEPTED with a red evidence row of method "qa_scenario"
      And the run moved to VERIFYING by R13
      And repo "backend" holds an approved test file and repo "frontend" holds none

    @AC-TDD-09h @integration @P1 @cov-errors
    Scenario: A backend failure does not change the frontend method and the reverse
      Given the "Remaining days" Red is rejected up to the cap and the run is NEEDS_HUMAN
      Then cycle "Request form" keeps red_method "qa_scenario" and no qa_red task of it was started after the park
