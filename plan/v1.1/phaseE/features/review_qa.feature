@REQ-AGT-01 @REQ-ORC-01 @REQ-ORC-05 @REQ-ORC-06
Feature: Reviewer and QA stages and finding routing
  After verification the engine runs the review stages the tier needs as tasks. Findings are
  stored as rows. A blocker or major finding sends the run back to execution with a new cycle
  (R16); a spec gap goes to a human. Review and QA rounds are capped.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos
    And repos "backend" and "frontend" use the test profile "fake-junit" with test_globs ["src/test/**"] and production_globs ["src/main/**"]
    And sentinel.config.yaml sets single_model false and agents.reviewer, agents.qa, agents.promotion, agents.docs, agents.rollout, agents.retrospective and agents.tdd_red to runner "fake"
    And a version 2 run "leave-balance" on repos "backend" and "frontend" with both approvals valid
    And cycle "remaining" on repo "backend" covers Rule "Remaining balance" and changed backend/src/main/java/leave/Balance.java
    And cycle "request-form" on repo "frontend" covers Rule "Request form" and changed frontend/src/LeaveForm.tsx
    And both cycles are CYCLE_ACCEPTED and verification round 1 passed

  Rule: R14 creates the review stages the tier needs

    @AC-AGT-01f @integration @P1 @cov-happy-path
    Scenario Outline: Review tasks per tier
      Given the run is at tier <tier> in state VERIFYING
      When "sentinel verify leave-balance" is run and every check passes
      Then the run state is REVIEWING
      And the review tasks created are <tasks>
      And each task depends on the one before it in that list
      Examples:
        | tier | tasks                                                                     |
        | 3    | reviewer, qa, promotion, docs                                             |
        | 4    | reviewer, qa, promotion, docs, rollout, retrospective                     |

    @AC-AGT-01g @integration @P1 @cov-happy-path
    Scenario Outline: Low tiers complete without review tasks
      Given the run is at tier <tier> in state VERIFYING
      When "sentinel verify leave-balance" is run and every check passes, then "sentinel next leave-balance --json" is run
      Then no reviewer or qa task exists
      And the run state is COMPLETED by R15 and the output JSON has kind "done"
      Examples:
        | tier |
        | 1    |
        | 2    |

    @AC-AGT-01h @unit @P1 @cov-authz
    Scenario Outline: Review task inputs and write scopes
      Given the run is at tier 4 in state REVIEWING
      When the engine creates the <role> task
      Then task.json permissions.write is <write>
      And task.json input names the approved spec and Gherkin by sha256, the baseline SHAs and the latest verification round
      Examples:
        | role          | write                                                                   |
        | reviewer      | []                                                                      |
        | qa            | []                                                                      |
        | promotion     | [".sentinel/shared/regression/**"]                                      |
        | docs          | ["backend/docs/**", "backend/CHANGELOG.md", "frontend/docs/**", "frontend/CHANGELOG.md"] |
        | rollout       | []                                                                      |
        | retrospective | [".sentinel/shared/proposals/**"]                                       |

    @AC-AGT-01i @integration @P2 @cov-happy-path
    Scenario Outline: QA depth follows the tier
      Given the run is at tier <tier> in state REVIEWING with a COMPLETED reviewer task and no open finding
      When the engine creates the qa task
      Then the qa task brief sets the QA mode to "<mode>"
      Examples:
        | tier | mode     |
        | 3    | targeted |
        | 4    | full     |

  Rule: Findings are stored, and only blockers and majors are routed

    @AC-ORC-05o @integration @P1 @cov-happy-path
    Scenario: Minor findings are recorded and do not stop the run
      Given the run is at tier 3 in state REVIEWING
      And runners.fake is a fake reviewer that reports one "minor" finding at "backend/src/main/java/leave/Balance.java:14"
      When "sentinel task run" is run for the reviewer task
      Then one finding row exists with source "reviewer", severity "minor", that location and state "open"
      And a "finding.created" event is stored
      And the run state is REVIEWING and the qa task is QUEUED

    @AC-ORC-01m @integration @P1 @cov-errors
    Scenario: A blocker sends the run back to execution with a new cycle (R16)
      Given the run is at tier 3 in state REVIEWING
      And runners.fake is a fake reviewer that reports a "blocker" "balance can go negative" at "backend/src/main/java/leave/Balance.java:22"
      When "sentinel task run" is run for the reviewer task
      Then the run state is EXECUTING and the "run.state_changed" event names transition "R16" and actor kind "engine"
      And a new PLANNED cycle covers Rule "Remaining balance" on repo "backend" and links the finding
      And the finding state is "routed" with routed_to that cycle
      And the qa task is CANCELLED with reason "review finding routed"
      And the review round count is 1

    @AC-ORC-01n @integration @P1 @cov-happy-path
    Scenario: The finding is resolved by its cycle and the reviewer checks again
      Given a "blocker" finding was routed to a new cycle for Rule "Remaining balance"
      And that cycle ran Red, Green and Refactor and is CYCLE_ACCEPTED
      When "sentinel next leave-balance --json" is run, then "sentinel verify leave-balance" passes
      Then the finding state is "resolved"
      And the run state is REVIEWING with a new QUEUED reviewer task whose brief lists the resolved finding for re-check
      And verification round 2 exists

    @AC-ORC-01o @integration @P2 @cov-duplicate
    Scenario: Several findings on one behavior give one new cycle
      Given the run is at tier 3 in state REVIEWING
      And runners.fake is a fake reviewer that reports two "major" findings in backend/src/main/java/leave/Balance.java and one "blocker" in frontend/src/LeaveForm.tsx
      When "sentinel task run" is run for the reviewer task
      Then exactly two new PLANNED cycles exist, one for Rule "Remaining balance" linking both backend findings and one for Rule "Request form"
      And exactly one R16 event is stored

    @AC-ORC-01p @integration @P2 @cov-errors
    Scenario: A finding no cycle owns goes to a human
      Given the run is at tier 3 in state REVIEWING
      And runners.fake is a fake reviewer that reports a "major" finding at "backend/src/main/resources/application.yml:3", a file no cycle changed
      When "sentinel task run" is run for the reviewer task
      Then the run state is NEEDS_HUMAN with reason "finding has no owning cycle" and the finding text
      And no new cycle exists

    @AC-ORC-01q @integration @P1 @cov-errors
    Scenario Outline: QA findings route by category
      Given the run is at tier 3 in state REVIEWING with a COMPLETED reviewer task and no open finding
      And runners.fake is a fake QA that reports a "<severity>" finding with category "<category>" at "frontend/src/LeaveForm.tsx:40"
      When "sentinel task run" is run for the qa task
      Then the run state is <state>
      And <effect>
      Examples:
        | severity | category | state       | effect                                                                                         |
        | major    | code_bug | EXECUTING   | a new PLANNED cycle covers Rule "Request form" and its Red brief asks for a test reproducing the finding |
        | major    | spec_gap | NEEDS_HUMAN | the reason is "QA spec gap" with the finding text and no new cycle exists                      |
        | blocker  | none     | EXECUTING   | a new PLANNED cycle covers Rule "Request form"                                                 |
        | minor    | code_bug | REVIEWING   | the finding is stored "open" and the promotion task is QUEUED                                  |

    @AC-ORC-01r @integration @P1 @cov-authz
    Scenario: Nobody but the engine sends the run back to execution
      Given the run is at tier 3 in state REVIEWING
      When the orchestrator asks the engine to move "leave-balance" to EXECUTING
      Then the request is refused with error "E_ACTOR"
      And the run state is still REVIEWING

    @AC-ORC-03c @integration @P2 @cov-boundary
    Scenario: A review blocker at tier 3 raises the tier
      Given the run is at tier 3 in state REVIEWING
      And runners.fake is a fake reviewer that reports a "blocker" at "backend/src/main/java/leave/Balance.java:22"
      When "sentinel task run" is run for the reviewer task
      Then the run tier is 4 and a "run.tier_raised" event from 3 to 4 is stored
      And the run state is NEEDS_HUMAN with reason "security gate (tier 4) needs human approval before execution resumes"

  Rule: Review and QA rounds are capped

    @AC-ORC-05p @integration @P1 @cov-boundary
    Scenario Outline: Round caps
      Given sentinel.config.yaml sets limits.<key> <cap>
      And the run is at tier 4 in state REVIEWING and every <source> pass reports a "major" code_bug finding in backend/src/main/java/leave/Balance.java
      And every new cycle and verification round passes
      When the orchestrator follows "sentinel next leave-balance --json" until it returns a "human" step
      Then <routed> R16 transitions were stored for <source> findings
      And the run state is NEEDS_HUMAN with reason "<source> round cap reached" listing the open finding
      Examples:
        | key           | cap | source   | routed |
        | review_rounds | 1   | reviewer | 1      |
        | review_rounds | 2   | reviewer | 2      |
        | qa_rounds     | 1   | qa       | 1      |

    @AC-ORC-05q @integration @P2 @cov-errors
    Scenario: A human may waive an open finding, and the run completes rejected
      Given the run is NEEDS_HUMAN at the review round cap with open "major" finding "balance can go negative" and previous state REVIEWING
      When a human at a terminal resumes the run with a recorded decision that waives that finding with comment "accepted risk for pilot" (R20)
      Then the finding state is "waived" with the approver and the comment, and an audit row is stored
      And after "sentinel next leave-balance --json" the run state is COMPLETED
      And the acceptance status is "rejected" with reason "required reviews open: 1 waived major finding"

  Rule: Policy gates during review

    @AC-ORC-06g @integration @P1 @cov-authz
    Scenario: QA on a real-data clone waits for a human
      Given the run is at tier 4 in state REVIEWING with a COMPLETED reviewer task and no open finding
      And sentinel.config.yaml sets qa.db_clone for database "leave" and policies.human_required includes "real_data_clone"
      When "sentinel task run" is run for the qa task
      Then it exits with code 6
      And the qa task is still QUEUED and qa_data was not run
      And the run state is NEEDS_HUMAN with reason "QA needs a clone of real data (policy real_data_clone)"

    @AC-ORC-06h @integration @P2 @cov-perf-security
    Scenario: The promotion stage writes only to the local shared folder
      Given the run is at tier 3 in state REVIEWING with COMPLETED reviewer and qa tasks
      And state.auto_sync_push is true in the config snapshot
      When "sentinel task run" is run for the promotion task and it adds .sentinel/shared/regression/leave-balance.md
      Then the promotion task is COMPLETED
      And nothing was pushed to the shared repo remote
      And "sentinel next leave-balance --json" does not offer "sentinel sync push"
