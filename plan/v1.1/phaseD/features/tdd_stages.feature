@REQ-AGT-01 @REQ-TDD-08 @REQ-AGT-04
Feature: Stage templates and permissions for test_designer and the TDD roles
  The roles test_designer, tdd_red, tdd_green and tdd_refactor get stage templates, so both the
  CLI adapter and the native adapter can run them. The engine sets each role's write scope from
  the permission matrix; no task can ask for more. The 0.1 stage templates do not change.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree
    And repo "backend" uses the test profile "fake-junit" with test_globs ["src/test/**"] and production_globs ["src/main/**"]
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 with both approvals valid
    And the approved Gherkin set holds features/balance.feature with Rule "Remaining balance" (scenarios "Employee sees remaining days" and "Balance never goes below zero") and Rule "Carry-over" (scenario "Unused days carry over")
    And cycle "remaining" covers Rule "Remaining balance" on repo "backend"

  Rule: Each new role has a template that renders without gaps

    @AC-AGT-01a @unit @P1 @cov-happy-path
    Scenario Outline: The new stage templates render
      When the stage template "<stage>" is rendered for a task of cycle "remaining" on repo "backend"
      Then rendering succeeds with no unresolved placeholder
      And the front matter says stage "<stage>", per_repo <per_repo> and writes "<writes>"
      Examples:
        | stage         | per_repo | writes     |
        | test_designer | false    | gherkin    |
        | tdd_red       | true     | tests      |
        | tdd_green     | true     | production |
        | tdd_refactor  | true     | production |

    @AC-AGT-01b @unit @P1 @cov-happy-path
    Scenario: The Red prompt names the scenarios, the scope and the rules
      When the prompt of the tdd_red task of cycle "remaining" is rendered
      Then it lists the scenario keys "features/balance.feature :: Employee sees remaining days" and "features/balance.feature :: Balance never goes below zero"
      And it shows the scenario text of both scenarios from the approved Gherkin version
      And it names the write scope "backend/src/test/**" and the targeted test command of the profile
      And it shows the scenario reference format of the profile
      And it says that feature files, production files and commits are not allowed
      And it names the result path .sentinel/runs/leave-balance/tasks/<task-id>/result.json

    @AC-AGT-01c @unit @P1 @cov-happy-path
    Scenario: The Green prompt names the approved tests as read-only
      Given cycle "remaining" is RED_VERIFIED with the approved test file backend/src/test/java/leave/RemainingBalanceTest.java
      When the prompt of the tdd_green task of cycle "remaining" is rendered
      Then it names the write scope "backend/src/main/**"
      And it lists backend/src/test/java/leave/RemainingBalanceTest.java as read-only
      And it lists the failing test ids from the Red evidence row
      And it says the engine runs the targeted tests itself after the task

    @AC-AGT-01d @unit @P2 @cov-happy-path
    Scenario: The Refactor prompt names the related tests
      Given cycle "remaining" is GREEN_VERIFIED and cycle "carry-over" is CYCLE_ACCEPTED on repo "backend"
      When the prompt of the tdd_refactor task of cycle "remaining" is rendered
      Then it names the write scope "backend/src/main/**"
      And it lists the related tests of both cycles
      And it says behavior must not change and tests are read-only

    @AC-AGT-01e @unit @P2 @cov-missing-fields
    Scenario: A missing profile value stops rendering with a clear error
      Given repo "backend" has no targeted_test in its profile or repos[] entry
      When the engine creates the tdd_red task of cycle "remaining"
      Then the request is refused with error "E_PRECONDITION" naming "targeted_test" and repo "backend"
      And the run state is NEEDS_HUMAN

  Rule: The engine sets each role's write scope from the permission matrix

    @AC-TDD-08a @unit @P1 @cov-authz
    Scenario Outline: Write scope and read-only files per role
      Given cycle "remaining" is in state <cycle_state>
      And once Red is verified the approved test file of cycle "remaining" is backend/src/test/java/leave/RemainingBalanceTest.java
      When the engine creates the <role> task of cycle "remaining"
      Then task.json permissions.write is <write>
      And task.json permissions.readonly_approved is <readonly>
      Examples:
        | cycle_state    | role           | write                                               | readonly                                                     |
        | PLANNED        | "tdd_red"      | ["backend/src/test/**"]                             | []                                                           |
        | RED_VERIFIED   | "tdd_green"    | ["backend/src/main/**"]                             | ["backend/src/test/java/leave/RemainingBalanceTest.java"]    |
        | GREEN_VERIFIED | "tdd_refactor" | ["backend/src/main/**"]                             | ["backend/src/test/java/leave/RemainingBalanceTest.java"]    |

    @AC-TDD-08b @unit @P1 @cov-authz
    Scenario Outline: Read-only roles get an empty write scope
      When the engine creates a <role> task for "leave-balance" on repo "backend"
      Then task.json permissions.write is []
      Examples:
        | role       |
        | "reviewer" |
        | "qa"       |

    @AC-TDD-08c @unit @P1 @cov-authz
    Scenario Outline: A TDD task that asks for more than its role allows is never created
      When the engine is asked to create a <role> task for cycle "remaining" with write scope <write>
      Then the request is refused with error "E_POLICY" naming the role and the glob <write>
      And no task row and no task folder are created
      Examples:
        | role           | write                                         |
        | "tdd_red"      | "backend/src/main/**"                         |
        | "tdd_green"    | "backend/src/test/**"                         |
        | "tdd_refactor" | "backend/**"                                  |
        | "tdd_green"    | ".sentinel/shared/specs/leave-balance/**"     |

  Rule: Both adapters run the TDD roles

    @AC-AGT-04f @integration @P1 @cov-happy-path
    Scenario: The CLI adapter runs a tdd_red task with the rendered prompt
      Given sentinel.config.yaml sets single_model false and agents.tdd_red to runner "fake"
      And the tdd_red task of cycle "remaining" is QUEUED
      And runners.fake is a fake CLI that records its prompt, writes a valid result.json and exits 0
      When "sentinel task run" is run for the tdd_red task
      Then the fake CLI was started in the backend repo with the prompt of AC-AGT-01b
      And the task was not refused with "E_PRECONDITION"

    @AC-AGT-04g @integration @P1 @cov-happy-path
    Scenario: A native tdd_green task gets the same checks at task complete
      Given sentinel.config.yaml sets single_model true
      And cycle "remaining" is RED_VERIFIED and its tdd_green task is QUEUED
      When "sentinel task run" is run for the tdd_green task
      Then the tdd_green task is WAITING_FOR_INPUT with waiting_on "orchestrator"
      When backend/src/test/java/leave/RemainingBalanceTest.java is edited and "sentinel task complete" is run for the tdd_green task
      Then it exits with code 3
      And the tdd_green task is FAILED with error code "E_SCOPE" and kind "approved_test_changed"

  Rule: The 0.1 stage templates are unchanged

    @AC-ORC-08j @unit @P1 @cov-regression
    Scenario Outline: 0.1 stages render byte for byte as before Phase D
      Given the rendered output of stage "<stage>" for repo "backend" recorded before Phase D
      When "sentinel/scripts/render_stage.py --stage <stage> --repo backend --slug demo" is run with the same config
      Then the output is byte-identical to the recorded output
      Examples:
        | stage     |
        | coder     |
        | specifier |
        | repro     |
        | hardener  |
        | reviewer  |
