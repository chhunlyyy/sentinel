@REQ-TDD-01 @REQ-ORC-04 @REQ-TDD-07
Feature: Cycle planning, repo assignment and the test baseline
  Once both approvals are valid the engine plans one TDD cycle per behavior group of the approved
  Gherkin: a Rule, or a Feature without Rules. Before the first Red in a repo the engine records
  which tests already fail, so Red can be judged against that baseline.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree
    And repos "backend" and "frontend" use the test profile "fake-junit" with test_globs ["src/test/**"] and production_globs ["src/main/**"]
    And sentinel.config.yaml sets single_model false and agents.tdd_red, agents.tdd_green and agents.tdd_refactor to runner "fake"
    And a version 2 run "leave-balance" at tier 3 on repos "backend" and "frontend"
    And the Gherkin set holds features/balance.feature tagged "@repo-backend" with Rule "Remaining balance" (scenarios "Employee sees remaining days" and "Balance never goes below zero") and Rule "Carry-over" (scenario "Unused days carry over")
    And it holds features/request_form.feature tagged "@repo-frontend" with no Rule and the scenario "Form shows the balance"

  Rule: R12 plans one cycle per behavior group

    @AC-TDD-01a @unit @P1 @cov-happy-path
    Scenario: Both approvals valid plans the cycles
      Given the run "leave-balance" is in state GHERKIN_APPROVED with both approvals valid
      When the engine advances "leave-balance"
      Then the run state is EXECUTING
      And three cycles are PLANNED:
        | behavior                                          | repo     | scenarios |
        | features/balance.feature :: Rule Remaining balance | backend  | 2         |
        | features/balance.feature :: Rule Carry-over        | backend  | 1         |
        | features/request_form.feature                      | frontend | 1         |
      And one "cycle.planned" event is stored per cycle
      And every approved scenario has exactly one "scenario" to "cycle" trace link

    @AC-TDD-01b @unit @P1 @cov-boundary
    Scenario Outline: How scenarios group into behaviors
      Given the approved feature file features/x.feature tagged "@repo-backend" holds <layout>
      When the engine plans cycles for "leave-balance"
      Then the cycles planned for features/x.feature are <cycles>
      Examples:
        | layout                                                 | cycles                                            |
        | 3 scenarios and no Rule                                | one cycle with 3 scenarios                        |
        | Rule "A" with 2 scenarios and Rule "B" with 1          | "Rule A" with 2 and "Rule B" with 1               |
        | 1 scenario before Rule "A", and Rule "A" with 2        | "(no rule)" with 1 and "Rule A" with 2            |
        | Rule "A" with 1 Scenario Outline of 4 Examples rows     | "Rule A" with 1 scenario                          |

    @AC-TDD-01c @unit @P1 @cov-invalid-input
    Scenario Outline: Repo assignment of a behavior group
      Given the run "leave-balance" uses repos <repos>
      And features/balance.feature carries the tags <feature_tags> and its Rule "Carry-over" carries <rule_tags>
      When the engine plans cycles for "leave-balance"
      Then the cycle for Rule "Carry-over" is <outcome>
      Examples:
        | repos                    | feature_tags    | rule_tags       | outcome                                                                  |
        | "backend"                | none            | none            | on repo "backend"                                                        |
        | "backend" and "frontend" | "@repo-backend" | none            | on repo "backend"                                                        |
        | "backend" and "frontend" | "@repo-backend" | "@repo-frontend" | on repo "frontend"                                                       |
        | "backend" and "frontend" | none            | none            | not planned; run NEEDS_HUMAN with reason "Rule Carry-over names no repo" |
        | "backend" and "frontend" | "@repo-mobile"  | none            | not planned; run NEEDS_HUMAN with reason "unknown repo mobile"           |

    @AC-TDD-01d @unit @P1 @cov-data-integrity
    Scenario: Planning stores all cycles or none
      Given the run "leave-balance" is in state GHERKIN_APPROVED with both approvals valid
      And storing the third cycle row fails with a database error
      When the engine advances "leave-balance"
      Then the run state is still GHERKIN_APPROVED
      And no cycle, no task and no trace link to a cycle is stored for "leave-balance"

    @AC-TDD-01e @unit @P1 @cov-happy-path
    Scenario: Cycles in one repo run in file order; other repos do not wait
      Given the run "leave-balance" is EXECUTING with the three cycles of AC-TDD-01a PLANNED
      When "sentinel next leave-balance --json" is run
      Then the tdd_red tasks of cycles "remaining" and "request-form" are QUEUED
      And the tdd_red task of cycle "carry-over" is CREATED and depends on cycle "remaining" being CYCLE_ACCEPTED

  Rule: The baseline records which tests fail before any Red

    @AC-TDD-03a @integration @P1 @cov-happy-path
    Scenario: The baseline is taken once per repo before its first Red
      Given the run "leave-balance" is EXECUTING with cycle "remaining" PLANNED
      And the fake test tool reports "LegacyTest.flaky" failing and 40 other tests passing in backend
      When the engine dispatches the tdd_red task of cycle "remaining"
      Then one evidence row of kind "baseline" is stored for repo "backend" before the task starts
      And it holds the full test command, exit code, classification "assertion", passed 40, failed 1 and the failing set ["LegacyTest.flaky"]
      And it holds the repo_sha of backend at that moment
      When the tdd_red task of cycle "carry-over" is dispatched later
      Then no second baseline row is stored for repo "backend"

    @AC-TDD-03b @integration @P1 @cov-external-failure
    Scenario Outline: A baseline that cannot run stops execution in that repo
      Given the run "leave-balance" is EXECUTING with cycle "remaining" PLANNED
      And the fake test tool for backend <outcome>
      When the engine dispatches the tdd_red task of cycle "remaining"
      Then the baseline row has classification "<class>"
      And the run state is NEEDS_HUMAN with reason "baseline for backend failed: <class>"
      And the tdd_red task of cycle "remaining" is not started
      Examples:
        | outcome                                                       | class              |
        | exits 1 with "error: cannot find symbol" before tests ran     | compile            |
        | exits 1 with "Connection refused"                             | environment        |
        | exits 1 with "Could not resolve com.acme:leave-core:1.0"      | missing_dependency |
        | exits 139 with no report and "Segmentation fault"             | unknown            |

    @AC-TDD-03m @unit @P2 @cov-empty-null
    Scenario: A repo with no tests at all has an empty baseline
      Given the fake test tool for backend reports 0 tests and exits 0
      When the engine takes the baseline for repo "backend"
      Then the baseline row has passed 0, failed 0 and an empty failing set
      And Red of cycle "remaining" can still be verified

  Rule: Red starts only under a valid Gherkin approval, and only the engine moves cycles

    @AC-TDD-01f @integration @P1 @cov-authz
    Scenario: A Gherkin edit before Red stops the Red phase
      Given the run "leave-balance" is EXECUTING with cycle "remaining" PLANNED
      When features/balance.feature is edited and "sentinel next leave-balance --json" is run
      Then the run state is GHERKIN_REVIEW by R18
      And cycle "remaining" never entered RED_RUNNING
      And no tdd_red task is RUNNING or QUEUED for "leave-balance"

    @AC-TDD-01g @unit @P1 @cov-authz
    Scenario Outline: Only the engine moves a cycle
      Given cycle "remaining" is in state <from>
      When the <actor> asks the engine to move cycle "remaining" to <to>
      Then the request is refused with error "E_ACTOR"
      And cycle "remaining" is still <from>
      Examples:
        | actor        | from              | to                |
        | orchestrator | PLANNED           | RED_RUNNING       |
        | orchestrator | RED_RUNNING       | RED_VERIFIED      |
        | human        | GREEN_RUNNING     | GREEN_VERIFIED    |
        | human        | REFACTOR_VERIFIED | CYCLE_ACCEPTED    |

  Rule: A bug fix starts with the repro test as cycle 1 Red

    @AC-TDD-07a @integration @P1 @cov-regression
    Scenario: The repro test stays as a regression test
      Given a version 2 run "leave-bug" of type "bug" at tier 2 on repo "backend" with both approvals valid
      And its approved Gherkin has Rule "Reproduce negative balance" first and Rule "Clamp at zero" second
      When the engine plans cycles for "leave-bug"
      Then cycle 1 covers Rule "Reproduce negative balance" and its tdd_red objective says to reproduce the reported bug
      When cycle 1 is CYCLE_ACCEPTED with the test file backend/src/test/java/leave/NegativeBalanceTest.java
      Then every later tdd_green and tdd_refactor task of "leave-bug" lists that file in permissions.readonly_approved
      And the related tests of every later refactor include the tests of that file
