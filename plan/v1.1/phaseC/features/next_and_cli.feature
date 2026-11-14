@REQ-ORC-02 @REQ-ARC-03 @REQ-VIS-05 @REQ-ORC-08
Feature: The next, task run and task complete commands
  "sentinel next" tells the orchestrator what is allowed now. "sentinel task run" and
  "sentinel task complete" are its only ways to act on tasks. 0.1 runs keep "stage run".

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree

  Rule: Next reports exactly one step

    @AC-ARC-03a @integration @P1 @cov-happy-path
    Scenario Outline: Next per run state
      Given a version 2 run "leave-balance" at tier <tier> in state <state> <extra>
      When "sentinel next leave-balance --json" is run
      Then it exits with code <code>
      And the output JSON has kind <kind> and <detail>
      Examples:
        | tier | state                | extra                                             | code | kind           | detail                                                        |
        | none | CREATED              | with no other records                             | 0    | "orchestrator" | command "sentinel triage leave-balance --factors ..."         |
        | 3    | TRIAGED              | with no decisions.md                              | 0    | "orchestrator" | the action "write .sentinel/runs/leave-balance/decisions.md"  |
        | 3    | PLANNED              | with a QUEUED specifier task                      | 0    | "task"         | the specifier task id, role, adapter and command "sentinel task run <task-id>" |
        | 3    | SPECIFICATION_REVIEW | with specification version 1 in review            | 6    | "human"        | commands "sentinel review leave-balance spec" and "sentinel approve leave-balance spec" |
        | 3    | GHERKIN_REVIEW       | with Gherkin version 1 in review                  | 6    | "human"        | commands "sentinel review leave-balance gherkin" and "sentinel approve leave-balance gherkin" |
        | 3    | EXECUTING            | with one RUNNING task and no QUEUED task           | 0    | "wait"         | the running task id                                            |
        | 3    | NEEDS_HUMAN          | with reason "docs task failed after 2 retries"    | 6    | "human"        | the reason "docs task failed after 2 retries"                  |
        | 3    | BLOCKED              | with reason "runner not installed: codex"         | 6    | "human"        | the reason and the fix                                         |
        | 3    | COMPLETED            | with acceptance "accepted"                        | 0    | "done"         | execution "completed" and acceptance "accepted"                |
        | 3    | CANCELLED            | with no other records                             | 0    | "done"         | execution "cancelled"                                          |

    @AC-ARC-03b @integration @P1 @cov-happy-path
    Scenario: Next plans a low-tier run and offers the specifier task
      Given a version 2 run "fix-typo" in state TRIAGED at tier 1
      When "sentinel next fix-typo --json" is run
      Then the run state is PLANNED and the "run.state_changed" event names transition "R3" and actor kind "engine"
      And one "specifier" task is QUEUED for "fix-typo"
      And the output is a "task" step for the specifier task

    @AC-ARC-03c @integration @P2 @cov-happy-path
    Scenario: Next without --json prints the step for a person
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW with specification version 1 in review
      When "sentinel next leave-balance" is run
      Then it exits with code 6
      And the output says "Human action: review and approve the specification" and shows "sentinel approve leave-balance spec"

    @AC-ARC-03d @integration @P2 @cov-data-integrity
    Scenario: Next never starts a task
      Given a version 2 run "leave-balance" in state EXECUTING with a QUEUED "docs" task routed to a fake CLI
      When "sentinel next leave-balance --json" is run 3 times
      Then the docs task is still QUEUED
      And the fake CLI was never started
      And the three outputs are identical

  Rule: Completed specifier and test_designer tasks drive the approval gates

    @AC-ARC-03e @integration @P1 @cov-happy-path
    Scenario: A completed specifier task opens the specification review
      Given a version 2 run "leave-balance" in state PLANNED at tier 3 with a native "specifier" task WAITING_FOR_INPUT
      And the subagent wrote a valid specs/leave-balance/spec.md and a valid result.json
      When "sentinel task complete" is run for the specifier task
      Then the specifier task is COMPLETED
      And the run state is SPECIFICATION_REVIEW and the "run.state_changed" event names transition "R4"
      And "sentinel next leave-balance --json" returns a "human" step for the specification

    @AC-ARC-03f @integration @P1 @cov-errors
    Scenario: A completed specifier task with an invalid specification goes back to the specifier
      Given a version 2 run "leave-balance" in state PLANNED at tier 3 with a native "specifier" task WAITING_FOR_INPUT
      And the subagent wrote a specs/leave-balance/spec.md without the "Edge cases" section and a valid result.json
      When "sentinel task complete" is run for the specifier task
      Then the specifier task is COMPLETED
      And the run state is still PLANNED
      And a new "specifier" task is QUEUED whose brief contains "missing section: Edge cases"

    @AC-ARC-03g @integration @P1 @cov-happy-path
    Scenario: Approving the specification queues the test_designer task
      Given a version 2 run "leave-balance" in state SPECIFICATION_REVIEW with specification version 1 in review
      When a human at a terminal approves the specification with the typed hash prefix
      Then one "test_designer" task is QUEUED for "leave-balance" whose input.specification holds the approved sha256
      And the test_designer task has write scope on specs/leave-balance/features/** only

  Rule: The commands check their arguments

    @AC-ARC-03h @integration @P2 @cov-invalid-input
    Scenario Outline: Bad arguments are refused
      Given a version 2 run "leave-balance" in state EXECUTING
      When "<command>" is run
      Then it exits with code <code>
      And the error is <error>
      Examples:
        | command                                   | code | error          |
        | sentinel next no-such-run                 | 5    | "E_NOT_FOUND"  |
        | sentinel next ../x                        | 5    | "E_VALIDATION" |
        | sentinel task run                         | 2    | usage          |
        | sentinel task run ../../etc/passwd        | 5    | "E_VALIDATION" |
        | sentinel task run t-000000000000          | 5    | "E_NOT_FOUND"  |
        | sentinel task complete t-zzzz             | 5    | "E_VALIDATION" |
        | sentinel task complete                    | 2    | usage          |

    @AC-ARC-03i @integration @P2 @cov-empty-null
    Scenario: A run with no tasks yet and nothing to do
      Given a version 2 run "leave-balance" in state EXECUTING with no tasks
      When "sentinel next leave-balance --json" is run
      Then it exits with code 6
      And the output is a "human" step with reason "no task planned for EXECUTING"

  Rule: 0.1 runs and the stage run command keep working

    @AC-ORC-08e @integration @P1 @cov-regression
    Scenario Outline: Stage run keeps its 0.1 exit codes
      Given a 0.1 run "demo" at tier 2 created with "sentinel run new demo --tier 2"
      And runners.<runner> is a fake CLI that <action>
      When "sentinel stage run --slug demo --stage coder --repo backend --runner <runner>" is run
      Then it exits with code <code>
      And no task row and no task event exist for "demo"
      Examples:
        | runner | action                              | code |
        | fake   | writes backend/ok.txt and exits 0   | 0    |
        | stray  | writes frontend/stray.txt           | 3    |
        | commit | commits in backend                  | 3    |
        | broken | exits 1                             | 1    |

    @AC-ORC-08f @integration @P1 @cov-regression
    Scenario Outline: The new commands refuse 0.1 runs
      Given a 0.1 run "old-run" at tier 2
      When "<command>" is run
      Then it exits with code 5
      And the error is "E_TRANSITION"
      And state.json of "old-run" is unchanged
      Examples:
        | command                    |
        | sentinel next old-run      |
        | sentinel next old-run --json |

    @AC-ORC-08g @integration @P1 @cov-regression
    Scenario: Stage run is refused on a version 2 run
      Given a version 2 run "leave-balance" in state EXECUTING
      When "sentinel stage run --slug leave-balance --stage coder --repo backend --runner fake" is run
      Then it exits with code 5
      And the error is "E_TRANSITION" naming "sentinel task run"
      And the fake CLI was never started

    @AC-ORC-08h @integration @P1 @cov-regression
    Scenario: Stage run with an adhoc slug that has no run keeps working
      Given no run named "scratch" exists
      And runners.fake is a fake CLI that writes backend/ok.txt and exits 0
      When "sentinel stage run --slug scratch --stage coder --repo backend --runner fake" is run
      Then it exits with code 0

    @AC-TST-01b @integration @P1 @cov-regression
    Scenario: Existing checks stay green
      When "python3 sentinel/scripts/selftest.py" and "python3 -m unittest discover -s tests" are run
      Then the 95 baseline selftest checks pass
      And every Phase A and Phase B test passes
