@REQ-TDD-09 @REQ-TDD-02 @REQ-TDD-03 @REQ-VER-02 @REQ-SEC-06 @REQ-ORC-05
Feature: The QA-driven Red phase: scenario scripts, engine run, failure classes, retries and caps
  A qa_red task writes one automated script per scenario of the behavior group, under the QA cache
  folder only. The engine, not the agent, then runs the scripts through qa.scenario_run, reads the
  structured report, and classifies the run. Red is accepted only when every scenario of the group
  fails at a Then step for the right reason. The agent's own claim of a failure is never evidence.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repo "frontend" with role "frontend" is a git repo with a clean working tree and the test profile "fake-junit"
    And rules.no_permanent_frontend_tests is true and the fake QA driver is configured with qa.ports [4173]
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 on repo "frontend" with both approvals valid
    And cycle "Request form" with scenarios "AC-LB-01" and "AC-LB-02" is PLANNED with red_method "qa_scenario"

  Rule: The qa_red task writes scripts only

    @AC-TDD-09i @integration @P1 @cov-happy-path
    Scenario: The qa_red task starts with the narrow scope and the cycle enters RED_RUNNING
      When the qa_red task of cycle "Request form" is started
      Then cycle "Request form" is RED_RUNNING
      And the task write scope is exactly ".sentinel/cache/qa/tests/current/leave-balance/**" and the repo is read-only
      And the environment of the task process has SENTINEL_TASK_ID set to the task id
      And the stage brief names the scenarios "AC-LB-01" and "AC-LB-02" and states that no test file may be written

    @AC-TDD-09j @integration @P1 @cov-authorization
    Scenario Outline: A qa_red task that writes into a repo is a scope violation
      Given the fake agent of the qa_red task writes <path>
      When the task finishes
      Then the task is FAILED with error "E_SCOPE" and the violation names <path>
      And no evidence row of kind "red" is written and cycle "Request form" is not RED_VERIFIED
      Examples:
        | path                                    |
        | frontend/src/test/RequestForm.test.ts   |
        | frontend/src/main/RequestForm.ts        |
        | frontend/playwright.config.ts           |
        | frontend/e2e/request.spec.ts            |
        | sentinel.config.yaml                    |
        | .sentinel/shared/specs/leave-balance/spec.md |

    @AC-TDD-09k @integration @P1 @cov-authorization
    Scenario: A tdd_red task cannot be created for a QA-Red cycle
      When "sentinel task create leave-balance --role tdd_red --cycle <cycle id>" is run
      Then it exits with code 5 and error "E_PRECONDITION" says the cycle uses QA scenarios as Red evidence
      And no task is created

    @AC-TDD-09l @integration @P1 @cov-authorization
    Scenario: A qa_red task cannot widen its scope to repo test globs
      When a task is requested with role "qa_red" and write scope ["frontend/src/test/**"]
      Then the request is refused with error "E_SCOPE" and no task is created

  Rule: The engine runs the scripts and judges the result

    @AC-TDD-09m @integration @P1 @cov-happy-path
    Scenario: Every scenario fails at a Then step, so Red is accepted
      Given the scripts of the task bind to scenarios "AC-LB-01" and "AC-LB-02"
      And the fake QA driver reports both scenarios failed at their Then step with an assertion message
      When the engine verifies the qa_red task
      Then the red evidence row has verdict "accepted", classification "assertion", method "qa_scenario" and kind "red"
      And the row holds the command, the cwd, the exit code, the start and finish time, the task id and the repo SHA
      And the row lists the failing scenarios "AC-LB-01" and "AC-LB-02" and the sha256 of every script
      And cycle "Request form" is RED_VERIFIED with approved_scripts recorded and approved_tests empty
      And the tdd_green task of the cycle is created

    @AC-TDD-09n @integration @P1 @cov-errors
    Scenario Outline: Red is judged by the engine's own run, per failure class
      Given the fake QA driver run ends with <driver result>
      When the engine verifies the qa_red task
      Then the red evidence row has verdict "<verdict>" and classification "<class>"
      And the outcome is <outcome>
      Examples:
        | driver result                                                        | verdict     | class              | outcome                                       |
        | both scenarios failed at a Then step                                  | accepted    | assertion          | cycle RED_VERIFIED                            |
        | both scenarios passed                                                 | rejected    | unexpected_pass    | a retry qa_red task with a brief               |
        | one scenario failed at a Then step and one passed                     | rejected    | unexpected_pass    | a retry qa_red task naming the passing scenario |
        | a scenario failed at a Given step                                     | rejected    | setup_failure      | a retry qa_red task with a brief               |
        | a scenario failed at a When step with a missing selector              | rejected    | setup_failure      | a retry qa_red task with a brief               |
        | the script has a syntax error and the driver reports it               | rejected    | script_error       | a retry qa_red task with a brief               |
        | no result for scenario "AC-LB-02"                                     | rejected    | unbound_scenario   | a retry qa_red task naming the missing scenario |
        | a result for scenario "AC-LB-09" of another cycle                     | rejected    | unbound_scenario   | a retry qa_red task naming the extra key        |
        | the app is not listening on port 4173 on the run and on the engine rerun | needs_human | app_not_running    | the run is NEEDS_HUMAN, no agent retry         |
        | the driver binary is missing or the browser cannot start, twice       | needs_human | driver_error       | the run is NEEDS_HUMAN, no agent retry         |
        | the driver timed out on the run and on the rerun                      | needs_human | driver_error       | the run is NEEDS_HUMAN, no agent retry         |
        | exit code 1, no report file and no recognised pattern                 | needs_human | unknown            | the run is NEEDS_HUMAN, no agent retry         |

    @AC-TDD-09o @integration @P1 @cov-errors
    Scenario: A passing Red is not accepted even when the agent says it failed
      Given the agent's result.json says "all scenarios failed as expected"
      And the engine's run of the scripts passes every scenario
      When the engine verifies the qa_red task
      Then the red evidence row is "rejected" with classification "unexpected_pass"
      And the claim is not stored as evidence
      And the retry brief says the scenarios passed before any production change

    @AC-TDD-09p @integration @P1 @cov-errors
    Scenario: A scenario that passes already is reported as already implemented, not retried forever
      Given the fake QA driver passes scenario "AC-LB-01" on every attempt and fails "AC-LB-02" at a Then step
      When Red is attempted up to the retry cap
      Then the cycle is REJECTED with reason "red cap reached" and the run is NEEDS_HUMAN
      And the run reason names scenario "AC-LB-01" as passing before Green

    @AC-TDD-09q @integration @P2 @cov-errors
    Scenario: The engine reruns a failing scenario once and a flip is flaky
      Given the fake QA driver fails scenario "AC-LB-01" on the first run and passes it on the rerun
      When the engine verifies the qa_red task
      Then the red evidence row has classification "flaky" and verdict "rejected"
      And the evidence row holds both runs and a retry qa_red task is created

    @AC-TDD-09r @integration @P1 @cov-errors
    Scenario: An environment failure is retried once by the engine before it parks the run
      Given the fake QA driver reports the app not running on the first run and failing Then steps on the second
      When the engine verifies the qa_red task
      Then the evidence row records both runs with classes "app_not_running" then "assertion"
      And the verdict is "accepted" and no human is involved

  Rule: Retries, caps and routing

    @AC-ORC-09a @integration @P1 @cov-boundary
    Scenario Outline: The Red retry cap applies to QA-Red
      Given the retry cap for qa_red is <cap>
      And the fake QA driver passes every scenario on every attempt
      When the cycle's qa_red attempts are verified one after the other
      Then there are <attempts> qa_red tasks and the last evidence row is rejected
      And cycle "Request form" is REJECTED with reason "red cap reached"
      And the run is NEEDS_HUMAN with reason "cycle Request form: red cap reached; last rejection: red passed unexpectedly"
      Examples:
        | cap | attempts |
        | 0   | 1        |
        | 1   | 2        |
        | 2   | 3        |

    @AC-ORC-09b @integration @P1 @cov-happy-path
    Scenario: The retry task sees what was wrong and the earlier failures
      Given attempt 1 was rejected with classification "setup_failure" at step "Given the employee has 5 days left"
      When the retry qa_red task is created
      Then its brief says it is attempt 2 of the cap plus one and quotes the scrubbed driver output line
      And the scripts of attempt 1 are still in the QA cache folder for the retry to edit

    @AC-ORC-09c @integration @P1 @cov-errors
    Scenario: NEEDS_HUMAN for a driver error never counts as an agent attempt
      Given the fake QA driver reports "driver_error" on every run
      When the engine verifies the qa_red task
      Then the run is NEEDS_HUMAN with reason "cycle Request form: QA driver error: <scrubbed line>"
      And the cycle stays RED_RUNNING for a human decision and no retry task exists
      And the attempt counter of the cycle is unchanged

    @AC-ORC-09d @integration @P2 @cov-happy-path
    Scenario: A human resume after a driver error runs Red again
      Given the run is NEEDS_HUMAN after a "driver_error" class on Red
      When a human fixes the driver and resumes the run through the human resume decision
      Then the engine runs the scripts again without a new agent task and judges them

    @AC-ORC-09e @integration @P1 @cov-errors
    Scenario: A failed qa_red task retries like a failed tdd_red task
      Given the qa_red task exits with the runner error "E_RUNNER_CRASH"
      When the task finishes
      Then a retry qa_red task is created and cycle "Request form" goes back to PLANNED

  Rule: Evidence output is scrubbed and QA data stays in the cache

    @AC-SEC-11a @integration @P1 @cov-perf-security
    Scenario Outline: Driver output is scrubbed before it is stored or shown
      Given the fake QA driver prints <text> in its output and in an assertion message
      When the engine verifies the qa_red task
      Then the stored output artifact, the evidence "failing" detail, the retry brief and the run events do not contain <secret>
      And the sha256 of the evidence row equals the sha256 of the scrubbed output file
      Examples:
        | text                                          | secret               |
        | "password=Pw-9f3kq2"                          | "Pw-9f3kq2"          |
        | "token=ghp_abcdef123456"                      | "ghp_abcdef123456"   |
        | "jane.doe@corp-mail.com"                      | "jane.doe@corp-mail.com" |
        | "mysql://qa:Pw-9f3kq2@10.0.0.5/leave"         | "Pw-9f3kq2"          |
        | the workspace path                            | the workspace path   |

    @AC-SEC-11b @integration @P1 @cov-perf-security
    Scenario: Screenshots, traces and QA data stay in the cache and out of the registry and export
      Given the fake QA driver wrote a PNG screenshot and a trace file for each failed scenario under .sentinel/cache/qa/
      When the engine verifies the qa_red task and a human exports the run
      Then the evidence row stores the screenshot paths relative to the state folder only
      And the bundle holds no file under .sentinel/cache/

    @AC-SEC-11c @integration @P1 @cov-authorization
    Scenario: The real-data clone gate applies before a qa_red task starts
      Given sentinel.config.yaml sets qa.db_clone for MySQL and "real_data_clone" in policies.human_required and no clone approval exists
      When the qa_red task is dispatched
      Then the run is NEEDS_HUMAN with reason "QA needs a clone of real data (policy real_data_clone)" and the task did not start

    @AC-SEC-11d @integration @P1 @cov-authorization
    Scenario: A qa_red task cannot call engine decisions
      Given the fake agent of the qa_red task runs "sentinel verify leave-balance" and "sentinel accept leave-balance"
      When the task finishes
      Then both calls were refused with error "E_ACTOR" and the cycle state was moved only by the engine

    @AC-SEC-11e @integration @P1 @cov-authorization
    Scenario: The QA command and the start commands come from the config only
      Given the agent's result.json carries a "command" field with "rm -rf /"
      When the engine verifies the qa_red task
      Then the executed command is exactly qa.scenario_run with the cycle's script folder and report path filled in
      And the evidence row's command equals that string
