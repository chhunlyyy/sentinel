@REQ-ORC-05 @REQ-ORC-06 @REQ-VER-01 @REQ-TDD-08
Feature: Routing of failed verification checks
  A failed check never moves the run on. The engine routes each failure to the agent that may fix
  it, in the repo that owns it, and runs verification again. Failures no agent may fix go to a
  human. The number of verification rounds is capped.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos
    And repos "backend" and "frontend" use the test profile "fake-junit" with test_globs ["src/test/**"] and production_globs ["src/main/**"]
    And the profile "fake-junit" has build, lint, typecheck, test, targeted_test and mutate commands that call the fake check tool, and the migration lane pattern "(^|/)db/migration/"
    And sentinel.config.yaml sets single_model false and agents.tdd_green and agents.hardener to runner "fake"
    And a version 2 run "leave-balance" in state VERIFYING at tier 4 on repos "backend" and "frontend" with both approvals valid
    And every cycle of "leave-balance" is CYCLE_ACCEPTED and backend/src/test/java/leave/RemainingBalanceTest.java is an approved test file
    And the fake check tool passes every command unless a scenario says otherwise

  Rule: Each failing check kind goes to the agent allowed to fix it

    @AC-ORC-05i @integration @P1 @cov-errors
    Scenario Outline: Routing per failing check
      Given the fake check tool makes the <kind> check of "backend" fail with <output>
      When "sentinel verify leave-balance" is run
      Then it exits with code 1
      And the run state is VERIFYING
      And one <role> task is QUEUED for repo "backend" with write scope <write> and readonly_approved ["backend/src/test/java/leave/RemainingBalanceTest.java"]
      And its brief quotes the scrubbed output of the failed <kind> row and names verification round 1
      And a "finding.routed" event links the failed evidence row to that task
      Examples:
        | kind        | output                                         | role       | write                   |
        | "test"      | "LeaveFormTest.submit failed"                  | tdd_green  | ["backend/src/main/**"] |
        | "targeted"  | "RemainingBalanceTest.balanceNeverBelowZero"   | tdd_green  | ["backend/src/main/**"] |
        | "build"     | "error: cannot find symbol LeaveBalance"       | tdd_green  | ["backend/src/main/**"] |
        | "lint"      | "src/main/java/leave/Balance.java:12 unused"   | tdd_green  | ["backend/src/main/**"] |
        | "typecheck" | "src/main/java/leave/Balance.java:4 type"      | tdd_green  | ["backend/src/main/**"] |
        | "hygiene"   | "debug output added in Balance.java"           | tdd_green  | ["backend/src/main/**"] |
        | "secret"    | "possible secret in src/main/resources/app.yml" | tdd_green  | ["backend/src/main/**"] |
        | "deps"      | "audit: 1 high vulnerability in leftpad 1.0"   | tdd_green  | ["backend/src/main/**"] |
        | "mutation"  | "3 mutants survived in Balance.java"           | hardener   | ["backend/src/test/**"] |

    @AC-ORC-05j @integration @P1 @cov-happy-path
    Scenario: After the fix, verification runs again and passes
      Given verification round 1 failed on "lint" of "backend" and its tdd_green fix task is QUEUED
      And runners.fake is a fake CLI that fixes the lint problem inside backend/src/main/** and writes a valid result.json
      When the orchestrator runs the fix task with "sentinel task run" and then runs "sentinel next leave-balance --json"
      Then the fix task is COMPLETED
      And the "next" output has kind "orchestrator" and command "sentinel verify leave-balance"
      When "sentinel verify leave-balance" is run
      Then round 2 passed and the run state is REVIEWING

    @AC-ORC-05k @integration @P1 @cov-concurrency
    Scenario: Failures in two repos give one fix task per repo
      Given policies.max_parallel_tasks is 2
      And the fake check tool makes "test" of "backend" and "lint" and "typecheck" of "frontend" fail
      When "sentinel verify leave-balance" is run
      Then exactly one fix task is QUEUED for "backend" and one for "frontend"
      And the "frontend" fix task brief quotes both the lint and the typecheck failure
      And both fix tasks can be RUNNING at the same moment
      And "sentinel next leave-balance --json" offers "sentinel verify leave-balance" only after both are COMPLETED

    @AC-TDD-08d @integration @P1 @cov-authz
    Scenario Outline: A failure only an approved test change could fix goes to a human
      Given the fake check tool makes the <kind> check of "backend" fail at backend/src/test/java/leave/RemainingBalanceTest.java line 9
      When "sentinel verify leave-balance" is run
      Then it exits with code 6
      And no fix task is created
      And the run state is NEEDS_HUMAN with reason "fix needs a change to approved test file backend/src/test/java/leave/RemainingBalanceTest.java"
      Examples:
        | kind     |
        | "lint"   |
        | "secret" |

    @AC-TDD-08e @integration @P1 @cov-authz
    Scenario: A fix task that edits an approved test file fails on scope
      Given verification round 1 failed on "test" of "backend" and its tdd_green fix task is QUEUED
      And runners.fake is a fake CLI that edits backend/src/test/java/leave/RemainingBalanceTest.java
      When "sentinel task run" is run for the fix task
      Then it exits with code 3
      And the fix task is FAILED with error code "E_SCOPE" and kind "approved_test_changed"
      And the run state is NEEDS_HUMAN

  Rule: Failures that need a human decision are never routed to an agent

    @AC-ORC-06a @integration @P1 @cov-authz
    Scenario: A scope failure stops for a human
      Given backend/build.gradle changed since the baseline and no task had it in its write scope
      When "sentinel verify leave-balance" is run
      Then it exits with code 6
      And no fix task is created
      And the run state is NEEDS_HUMAN with reason "changes outside every task scope: backend/build.gradle"
      And nothing in the working tree was reverted

    @AC-ORC-06b @integration @P1 @cov-authz
    Scenario: A destructive migration needs a human
      Given backend/db/migration/V8__drop_legacy.sql was added with "ALTER TABLE leave DROP COLUMN legacy_days"
      When "sentinel verify leave-balance" is run
      Then the "migration" evidence row of "backend" failed with classification "destructive" listing the DROP COLUMN statement
      And the run state is NEEDS_HUMAN with reason "destructive migration needs human approval (policy destructive_migration)"
      And no fix task is created

    @AC-ORC-06c @integration @P1 @cov-authz
    Scenario: After a human approves the destructive migration, verification can pass
      Given verification round 1 stopped at the destructive migration backend/db/migration/V8__drop_legacy.sql
      When a human at a terminal resumes the run with a recorded decision approving that migration file by its sha256 (R20)
      Then an approval of gate "migration" with the file sha256, the approver and channel "tty" is stored
      And an audit row is stored
      When "sentinel verify leave-balance" is run
      Then the "migration" row of round 2 passed with classification "destructive_approved"
      And the run state is REVIEWING

    @AC-ORC-06d @integration @P2 @cov-data-integrity
    Scenario: A migration approval is void once the file changes
      Given a human approved backend/db/migration/V8__drop_legacy.sql at its current sha256
      And the file was edited afterwards
      When "sentinel verify leave-balance" is run
      Then the "migration" row failed with classification "destructive"
      And the run state is NEEDS_HUMAN

    @AC-ORC-06e @integration @P2 @cov-errors
    Scenario: Editing an already applied migration is routed as a defect
      Given backend/db/migration/V3__leave.sql existed at the baseline and was modified
      When "sentinel verify leave-balance" is run
      Then the "migration" row of "backend" failed with classification "applied_migration_changed"
      And a tdd_green fix task is QUEUED for "backend" whose brief names V3__leave.sql

    @AC-ORC-06f @integration @P1 @cov-errors
    Scenario Outline: Test runs that cannot be judged go to a human
      Given the fake check tool <outcome> for the full test command of "backend"
      When "sentinel verify leave-balance" is run
      Then the "test" row of "backend" has classification "<class>"
      And the run state is NEEDS_HUMAN with reason naming "<class>" and repo "backend"
      And no fix task is created
      Examples:
        | outcome                                           | class       |
        | exits 2 and writes no test report                 | unknown     |
        | prints "Connection refused" and exits 1           | environment |

  Rule: Verification rounds are capped

    @AC-ORC-05l @integration @P1 @cov-boundary
    Scenario Outline: Cap on verification rounds
      Given sentinel.config.yaml sets limits.release_check_rounds <cap>
      And every fix task completes but the "lint" check of "backend" fails in every round
      When the orchestrator follows "sentinel next leave-balance --json" until it returns a "human" step
      Then <rounds> verification rounds were recorded and <fixes> fix tasks were run
      And the run state is NEEDS_HUMAN with reason "verification failed after <rounds> rounds" listing the open "lint" failure
      Examples:
        | cap | rounds | fixes |
        | 1   | 1      | 0     |
        | 3   | 3      | 2     |

    @AC-ORC-05m @integration @P2 @cov-errors
    Scenario: A fix task that keeps failing uses the task retry cap
      Given verification round 1 failed on "build" of "backend"
      And runners.fake is a fake CLI that always exits 1
      And sentinel.config.yaml sets agents.tdd_green.max_retries 1
      When the orchestrator runs every "task" step that "sentinel next leave-balance --json" returns
      Then 2 tdd_green fix tasks ran and both are FAILED with error code "E_EXIT"
      And the run state is NEEDS_HUMAN with reason naming the fix task and "retry cap reached"

    @AC-ORC-05n @integration @P2 @cov-data-integrity
    Scenario: Fix tasks are part of the scope union and the trace
      Given verification round 1 failed on "lint" of "backend" and its fix task changed backend/src/main/java/leave/Balance.java
      When "sentinel verify leave-balance" is run and round 2 passes
      Then the "scope" row of round 2 passed
      And trace links "evidence -> task" from the failed lint row to the fix task and "task -> file" to backend/src/main/java/leave/Balance.java exist
