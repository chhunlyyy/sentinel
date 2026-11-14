@REQ-VER-01 @REQ-CFG-11 @REQ-ORC-01
Feature: Verification checks by tier and config
  Once every cycle is accepted, the engine runs the checks that the run's tier and config
  snapshot require, itself, in each repo the run changed. Each check leaves one evidence row
  per repo. Only when every required check passes does the run move on to review (R14).

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos
    And repos "backend" and "frontend" use the test profile "fake-junit" whose build, lint, typecheck, test, targeted_test and mutate commands call the fake check tool
    And the profile "fake-junit" has the migration lane pattern "(^|/)db/migration/"
    And a version 2 run "leave-balance" in state VERIFYING on repos "backend" and "frontend" with both approvals valid
    And every cycle of "leave-balance" is CYCLE_ACCEPTED and both repos have changes since their baseline
    And the fake check tool passes every command unless a scenario says otherwise

  Rule: The tier decides which checks run

    @AC-VER-01a @integration @P1 @cov-happy-path
    Scenario Outline: Checks per tier
      Given the run is at tier <tier>
      And no file under a migration path changed
      When "sentinel verify leave-balance" is run
      Then it exits with code 0
      And evidence rows of kinds <kinds> exist for each of "backend" and "frontend" in verification round 1
      And no evidence row of kind <absent> exists
      Examples:
        | tier | kinds                                                                                       | absent      |
        | 1    | "targeted", "test", "build", "lint", "typecheck", "hygiene", "scope"                         | "secret"    |
        | 2    | "targeted", "test", "build", "lint", "typecheck", "hygiene", "scope", "secret", "deps"        | "mutation"  |
        | 3    | "targeted", "test", "build", "lint", "typecheck", "hygiene", "scope", "secret", "deps"        | "mutation"  |
        | 4    | "targeted", "test", "build", "lint", "typecheck", "hygiene", "scope", "secret", "deps", "mutation" | "migration" |

    @AC-VER-01b @integration @P1 @cov-happy-path
    Scenario Outline: Migration safety runs when a migration file changed
      Given the run is at tier <tier>
      And backend/db/migration/V7__leave_balance.sql was added with "ALTER TABLE leave ADD COLUMN carry_over INT"
      When "sentinel verify leave-balance" is run
      Then one evidence row of kind "migration" exists for "backend" and it passed
      And no evidence row of kind "migration" exists for "frontend"
      Examples:
        | tier |
        | 1    |
        | 3    |
        | 4    |

    @AC-VER-01c @integration @P1 @cov-happy-path
    Scenario: A docs-only run checks links and its docs build
      Given a version 2 docs-only run "leave-docs" in state VERIFYING on repo "backend" whose docs task is COMPLETED
      And the docs task changed backend/docs/leave.md, which links to backend/docs/policy.md
      And repo "backend" sets commands.docs to a fake docs build
      When "sentinel verify leave-docs" is run
      Then evidence rows of kinds "docs_links", "docs_build" and "scope" exist for "backend"
      And no evidence row of kind "test", "build" or "mutation" exists for "leave-docs"
      And the run state is REVIEWING

    @AC-VER-01d @integration @P2 @cov-boundary
    Scenario: A repo without changes is skipped except for the scope check
      Given repo "frontend" has no change since its baseline
      When "sentinel verify leave-balance" is run
      Then "frontend" has exactly one evidence row in round 1, of kind "scope", and it passed
      And the verification summary lists "frontend" as "unchanged"

  Rule: Targeted and full tests are judged against the baseline

    @AC-VER-01e @integration @P1 @cov-happy-path
    Scenario: The targeted check runs the tests of every accepted cycle of the repo
      Given cycles "remaining" and "carry-over" on repo "backend" are CYCLE_ACCEPTED with targeted tests ["RemainingBalanceTest"] and ["CarryOverTest"]
      When "sentinel verify leave-balance" is run
      Then the "targeted" evidence row of "backend" holds the profile's targeted_test command with "RemainingBalanceTest" and "CarryOverTest"
      And the "test" evidence row of "backend" holds the profile's full test command

    @AC-VER-01f @integration @P1 @cov-boundary
    Scenario Outline: The full suite fails only on a new failure
      Given the baseline of repo "backend" has the failing set <baseline>
      And the fake check tool reports the failing set <now> for the full test command of "backend"
      When "sentinel verify leave-balance" is run
      Then the "test" evidence row of "backend" has passed <passed>
      And its failing list is <now> and its pre-existing list is <preexisting>
      Examples:
        | baseline             | now                                   | passed  | preexisting          |
        | []                   | []                                    | "true"  | []                   |
        | ["LegacyTest.flaky"] | ["LegacyTest.flaky"]                  | "true"  | ["LegacyTest.flaky"] |
        | ["LegacyTest.flaky"] | []                                    | "true"  | []                   |
        | []                   | ["LeaveFormTest.submit"]              | "false" | []                   |
        | ["LegacyTest.flaky"] | ["LegacyTest.flaky", "PayTest.total"] | "false" | ["LegacyTest.flaky"] |

  Rule: The scope check compares the whole diff with the union of task write scopes

    @AC-VER-01g @integration @P1 @cov-authz
    Scenario Outline: Scope check outcomes
      Given the completed tasks of "leave-balance" had write scopes "backend/src/main/**", "backend/src/test/**" and "frontend/src/**"
      And since the baseline <change>
      When "sentinel verify leave-balance" is run
      Then the "scope" evidence row of "<repo>" has passed <passed> and lists <paths>
      Examples:
        | change                                                         | repo     | passed  | paths                          |
        | only paths inside those scopes changed                         | backend  | "true"  | nothing                        |
        | backend/build.gradle changed                                   | backend  | "false" | "build.gradle"                 |
        | frontend/package.json changed                                  | frontend | "false" | "package.json"                 |
        | sentinel.config.yaml changed                                   | backend  | "false" | "sentinel.config.yaml"         |
        | a commit was added on top of the baseline of repo "backend"    | backend  | "false" | "HEAD moved"                   |

    @AC-VER-01h @integration @P2 @cov-data-integrity
    Scenario: Changes present before the run started are not blamed on the run
      Given backend/README.md was already modified when the run was created and its hash was recorded in the run baseline
      And backend/README.md has the same hash now
      When "sentinel verify leave-balance" is run
      Then the "scope" evidence row of "backend" passed
      And the verification summary lists backend/README.md as "changed before the run"

  Rule: Config decides optional checks; tests and scope cannot be turned off

    @AC-CFG-11b @integration @P1 @cov-boundary
    Scenario Outline: verification.mutation decides when mutation runs
      Given the run is at tier <tier>
      And the config snapshot sets verification.mutation <setting>
      When "sentinel verify leave-balance" is run
      Then an evidence row of kind "mutation" exists for "backend": <exists>
      Examples:
        | tier | setting   | exists |
        | 4    | "tier4"   | yes    |
        | 3    | "tier4"   | no     |
        | 3    | "always"  | yes    |
        | 4    | "never"   | no     |

    @AC-CFG-11c @integration @P2 @cov-boundary
    Scenario Outline: verification.migration_check decides when migration safety runs
      Given the run is at tier 3
      And the config snapshot sets verification.migration_check <setting>
      And <change>
      When "sentinel verify leave-balance" is run
      Then an evidence row of kind "migration" exists for "backend": <exists>
      Examples:
        | setting  | change                                                 | exists |
        | "auto"   | backend/db/migration/V7__leave_balance.sql was added   | yes    |
        | "auto"   | no file under a migration path changed                 | no     |
        | "always" | no file under a migration path changed                 | yes    |
        | "never"  | backend/db/migration/V7__leave_balance.sql was added   | no     |

    @AC-CFG-11d @integration @P2 @cov-empty-null
    Scenario Outline: A check with no command or turned off by config is recorded, not run
      Given the run is at tier 2
      And <setup>
      When "sentinel verify leave-balance" is run
      Then the "lint" evidence row of "backend" has classification "<class>" and no command was run for it
      And the run state is REVIEWING
      Examples:
        | setup                                                      | class          |
        | the profile "fake-junit" sets commands.lint to ""          | not_configured |
        | the config snapshot sets verification.disabled ["lint"]    | disabled       |

    @AC-CFG-11e @unit @P1 @cov-invalid-input
    Scenario Outline: Config that would weaken mandatory checks is invalid
      Given sentinel.config.yaml sets <setting>
      When the config is validated
      Then validation fails naming <key>
      Examples:
        | setting                                   | key                         |
        | verification.disabled ["test"]            | "verification.disabled"     |
        | verification.disabled ["scope"]           | "verification.disabled"     |
        | verification.mutation "sometimes"         | "verification.mutation"     |
        | verification.migration_check "maybe"      | "verification.migration_check" |
        | verification.unknown_key true             | "verification"              |

    @AC-CFG-11f @unit @P1 @cov-regression
    Scenario: A config without a verification block is valid and uses the defaults
      Given sentinel.config.yaml has no verification key
      When the config is validated
      Then validation passes
      And the effective verification settings are mutation "tier4", migration_check "auto", disabled [] and extra []

    @AC-CFG-08c @integration @P1 @cov-data-integrity
    Scenario: Verification uses the run's config snapshot
      Given the run is at tier 3 and its config snapshot has no verification key
      And sentinel.config.yaml was changed after the run started to set verification.mutation "always"
      When "sentinel verify leave-balance" is run
      Then no evidence row of kind "mutation" exists

    @AC-CFG-11g @integration @P2 @cov-happy-path
    Scenario: Extra checks from the config become evidence rows
      Given the config snapshot sets verification.extra with an "added_lines" rule named "no-sysout" with pattern "System.out"
      And a production file in "backend" gained the line 'System.out.println("debug");'
      When "sentinel verify leave-balance" is run
      Then an evidence row of kind "extra" named "no-sysout" exists for "backend" and it failed
      And the row lists the file and the added line

    @AC-VER-01i @integration @P1 @cov-errors
    Scenario Outline: A required command that is missing stops verification
      Given the run is at tier <tier>
      And <missing>
      When "sentinel verify leave-balance" is run
      Then it exits with code 6
      And the run state is NEEDS_HUMAN with reason "<reason>"
      And no evidence row of round 1 exists
      Examples:
        | tier | missing                                              | reason                                  |
        | 1    | repo "backend" and its profile set no test command   | test command missing for repo backend   |
        | 4    | repo "backend" and its profile set no mutate command | mutate command missing for repo backend |

  Rule: R14 moves the run to review only when every required check passed

    @AC-ORC-01j @integration @P1 @cov-happy-path
    Scenario: All checks pass
      Given the run is at tier 3
      When "sentinel verify leave-balance" is run
      Then it exits with code 0
      And the run state is REVIEWING and the "run.state_changed" event names transition "R14" and actor kind "engine"
      And one "evidence.recorded" event exists per evidence row of round 1

    @AC-ORC-01k @integration @P1 @cov-authz
    Scenario: Nobody but the engine moves the run to review
      When the orchestrator asks the engine to move "leave-balance" to REVIEWING
      Then the request is refused with error "E_ACTOR"
      And the run state is still VERIFYING

    @AC-ORC-01l @integration @P1 @cov-data-integrity
    Scenario: A Gherkin edit before verification wins over R14
      Given features/balance.feature was edited after the Gherkin approval
      When "sentinel verify leave-balance" is run
      Then it exits with code 5
      And the run state is GHERKIN_REVIEW by R18
      And no evidence row of round 1 exists
