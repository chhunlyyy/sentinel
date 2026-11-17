@REQ-CFG-10 @REQ-AGT-06 @REQ-TDD-08
Feature: Path-level write scopes from test and production globs
  Profiles and repos name which paths hold tests and which hold production code. A task's write
  scope is a list of path globs, and after the task the engine checks every changed path against
  them. The repo-level boundary of 0.1 stays for `sentinel stage run`.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree
    And backend holds the files src/main/java/leave/LeaveBalance.java, src/test/java/leave/LeaveBalanceTest.java and docs/leave.md
    And sentinel.config.yaml sets single_model false and agents.docs to runner "fake"
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 with both approvals valid

  Rule: Profiles and repos provide test and production globs

    @AC-CFG-10a @unit @P1 @cov-happy-path
    Scenario Outline: Every shipped code profile names its globs and test tooling
      When the profile "<profile>" is loaded
      Then it has a non-empty "test_globs" list and a non-empty "production_globs" list
      And it has "targeted_test", "test_report", "failure_patterns" and "scenario_ref"
      And its "commands" and "lanes" are the same as in Sentinel 0.1
      Examples:
        | profile       |
        | spring-gradle |
        | python        |
        | node          |
        | nextjs        |
        | flutter       |

    @AC-CFG-10b @unit @P1 @cov-happy-path
    Scenario: A repo entry overrides the profile globs key by key
      Given repo "backend" uses the profile "spring-gradle"
      And its repos[] entry sets test_globs ["src/test/**", "src/it/**"]
      When the effective globs of repo "backend" are computed from the run's config snapshot
      Then test_globs are ["src/test/**", "src/it/**"]
      And production_globs are the profile's ["src/main/**"]

    @AC-CFG-10c @unit @P1 @cov-invalid-input
    Scenario Outline: An invalid glob list is refused by config validation
      Given sentinel.config.yaml sets repos[backend].<key> to <value>
      When the config is validated
      Then validation fails on "repos[backend].<key>"
      Examples:
        | key              | value              |
        | test_globs       | "src/test/**"      |
        | test_globs       | ["/abs/src/**"]    |
        | production_globs | ["../frontend/**"] |
        | production_globs | [""]               |
        | test_globs       | [42]               |

    @AC-CFG-10d @unit @P1 @cov-empty-null
    Scenario Outline: A code repo without usable globs cannot start execution
      Given repo "backend" uses the profile "generic"
      And its repos[] entry sets <setting>
      And the run "leave-balance" is in state GHERKIN_APPROVED with both approvals valid
      When the engine advances "leave-balance"
      Then the run state is NEEDS_HUMAN with reason "repo backend has no <missing>"
      And no cycle is stored for "leave-balance"
      Examples:
        | setting                                    | missing          |
        | no test_globs and no production_globs      | test_globs       |
        | test_globs ["tests/**"] and no production  | production_globs |
        | test_globs [] and production_globs ["**"]  | test_globs       |

    @AC-CFG-10e @unit @P2 @cov-boundary
    Scenario Outline: A path that matches both lists counts as a test file
      Given repo "backend" has test_globs ["src/**/*Test.java"] and production_globs ["src/**"]
      When the engine classifies the backend path <path>
      Then the path kind is <kind>
      Examples:
        | path                                       | kind       |
        | "src/main/java/leave/LeaveBalanceTest.java" | test       |
        | "src/main/java/leave/LeaveBalance.java"     | production |
        | "build.gradle"                              | other      |

    @AC-CFG-08b @integration @P1 @cov-data-integrity
    Scenario: A config change during the run does not widen a running scope
      Given a RUNNING "docs" task for "leave-balance" on repo "backend" with write scope "backend/docs/**"
      And runners.fake is a fake CLI that writes backend/src/main/java/leave/Extra.java and a valid result.json
      When sentinel.config.yaml is edited to set repos[backend].test_globs ["**"] while the task runs
      And the task finishes
      Then the docs task is FAILED with error code "E_SCOPE"
      And the scope check used the write scope stored in the task row

  Rule: Glob matching is repo-relative, case-sensitive and segment-aware

    @AC-AGT-06f @unit @P1 @cov-boundary
    Scenario Outline: Glob matching
      Given a task on repo "backend" with write scope <glob>
      When the engine checks the changed backend path <path>
      Then the path is <result>
      Examples:
        | glob                    | path                                     | result  |
        | "backend/src/main/**"   | "src/main/java/leave/LeaveBalance.java"  | allowed |
        | "backend/src/main/**"   | "src/mainx/A.java"                       | outside |
        | "backend/src/main/*"    | "src/main/A.java"                        | allowed |
        | "backend/src/main/*"    | "src/main/java/A.java"                   | outside |
        | "backend/**/*Test.java" | "LeaveBalanceTest.java"                  | allowed |
        | "backend/**/*Test.java" | "src/test/java/leave/LeaveBalanceTest.java" | allowed |
        | "backend/src/main/**"   | "SRC/main/A.java"                        | outside |
        | "backend/src/main/**"   | "src/main/.hidden/A.java"                | allowed |
        | "backend/docs/a b.md"   | "docs/a b.md"                            | allowed |
        | "frontend/src/**"       | "src/App.tsx"                            | outside |
        | an empty write scope    | "docs/leave.md"                          | outside |

  Rule: Every changed path is checked against the task's write scope

    @AC-AGT-06g @integration @P1 @cov-authz
    Scenario Outline: Writes inside and outside the scope
      Given a QUEUED "docs" task for "leave-balance" on repo "backend" with write scope "backend/docs/**" routed to "fake"
      And runners.fake is a fake CLI that <action>, writes a valid result.json and exits 0
      When "sentinel task run" is run for the docs task
      Then it exits with code <code>
      And the docs task is <state>
      And the scope violations listed are <listed>
      Examples:
        | action                                                     | code | state                       | listed                                          |
        | edits backend/docs/leave.md                                | 0    | COMPLETED                   | none                                            |
        | creates backend/docs/new/guide.md                          | 0    | COMPLETED                   | none                                            |
        | edits backend/src/main/java/leave/LeaveBalance.java        | 3    | FAILED with "E_SCOPE"       | "backend/src/main/java/leave/LeaveBalance.java" |
        | deletes backend/src/test/java/leave/LeaveBalanceTest.java  | 3    | FAILED with "E_SCOPE"       | "backend/src/test/java/leave/LeaveBalanceTest.java" |
        | renames backend/docs/leave.md to backend/leave.md          | 3    | FAILED with "E_SCOPE"       | "backend/leave.md"                              |
        | creates backend/build/out.txt ignored by backend/.gitignore | 0   | COMPLETED                   | none                                            |

    @AC-AGT-06h @integration @P1 @cov-authz
    Scenario: Every violation is listed, kept in place and sent to a human
      Given a QUEUED "docs" task for "leave-balance" on repo "backend" with write scope "backend/docs/**" routed to "fake"
      And runners.fake is a fake CLI that edits backend/docs/leave.md, backend/build.gradle and backend/src/main/java/leave/LeaveBalance.java and exits 0
      When "sentinel task run" is run for the docs task
      Then it exits with code 3
      And one "task.scope_violation" event lists "backend/build.gradle" and "backend/src/main/java/leave/LeaveBalance.java" with kind "outside_write_scope"
      And the event does not list "backend/docs/leave.md"
      And no retry task is created
      And the run state is NEEDS_HUMAN with reason naming "scope violation" and the docs task id
      And all three files keep the fake CLI's content

    @AC-AGT-06i @integration @P1 @cov-data-integrity
    Scenario Outline: Changes already present before the task are judged by content hash
      Given backend/src/main/java/leave/LeaveBalance.java has an uncommitted change before the task starts
      And a QUEUED "docs" task for "leave-balance" on repo "backend" with write scope "backend/docs/**" routed to "fake"
      And runners.fake is a fake CLI that <action> and exits 0
      When "sentinel task run" is run for the docs task
      Then it exits with code <code>
      Examples:
        | action                                                                 | code |
        | edits backend/docs/leave.md only                                       | 0    |
        | edits backend/src/main/java/leave/LeaveBalance.java again              | 3    |
        | rewrites backend/src/main/java/leave/LeaveBalance.java with equal bytes | 0   |

    @AC-AGT-06j @integration @P1 @cov-authz
    Scenario Outline: Specification and Gherkin authors write only their own shared files
      Given a version 2 run "leave-plan" in state <run_state>
      And a QUEUED <role> task for "leave-plan" routed to "fake"
      And runners.fake is a fake CLI that writes <path>, writes a valid result.json and exits 0
      When "sentinel task run" is run for the <role> task
      Then it exits with code <code>
      Examples:
        | run_state              | role            | path                                                   | code |
        | PLANNED                | "specifier"     | .sentinel/shared/specs/leave-plan/spec.md              | 0    |
        | PLANNED                | "specifier"     | .sentinel/shared/specs/leave-plan/features/a.feature   | 3    |
        | SPECIFICATION_APPROVED | "test_designer" | .sentinel/shared/specs/leave-plan/features/a.feature   | 0    |
        | SPECIFICATION_APPROVED | "test_designer" | .sentinel/shared/specs/leave-plan/notes.md             | 3    |
        | SPECIFICATION_APPROVED | "test_designer" | backend/src/test/java/leave/PlanTest.java              | 3    |

  Rule: Two tasks running in one repo are judged by their own globs

    @AC-AGT-06k @integration @P1 @cov-concurrency
    Scenario: Writes inside another running task's scope are attributed to that task
      Given policies.max_parallel_tasks is 2
      And task "A" for "leave-balance" on repo "backend" has write scope "backend/docs/**"
      And task "B" for "leave-balance" on repo "backend" has write scope "backend/src/main/**"
      And both are routed to fake CLIs that sleep 2 seconds, write inside their own scope and exit 0
      When "sentinel task run" is run for "A" and for "B" at the same time
      Then both tasks are COMPLETED
      And no "task.scope_violation" event is stored

    @AC-AGT-06l @integration @P2 @cov-concurrency
    Scenario: A write that matches no running task is blamed on every task running in that repo
      Given policies.max_parallel_tasks is 2
      And task "A" for "leave-balance" on repo "backend" has write scope "backend/docs/**"
      And task "B" for "leave-balance" on repo "backend" has write scope "backend/src/main/**"
      And task "B" is routed to a fake CLI that also writes backend/build.gradle
      When "sentinel task run" is run for "A" and for "B" at the same time
      Then tasks "A" and "B" are both FAILED with error code "E_SCOPE" listing "backend/build.gradle"
      And the run state is NEEDS_HUMAN

  Rule: 0.1 stage runs keep the repo-level boundary

    @AC-ORC-08i @integration @P1 @cov-regression
    Scenario Outline: Stage run on a 0.1 run checks whole repos as before
      Given a 0.1 run "demo" at tier 2 created with "sentinel run new demo --tier 2"
      And runners.fake is a fake CLI that <action> and exits 0
      When "sentinel stage run --slug demo --stage coder --repo backend --runner fake <flags>" is run
      Then it exits with code <code>
      And no profile glob was read for the check
      Examples:
        | action                                         | flags                 | code |
        | edits backend/build.gradle                     |                       | 0    |
        | edits backend/src/test/java/leave/X.java       |                       | 0    |
        | writes frontend/stray.txt                      |                       | 3    |
        | writes frontend/stray.txt                      | --concurrent frontend | 0    |
        | commits in backend                             |                       | 3    |
