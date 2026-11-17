@REQ-ART-01 @REQ-ANL-02 @REQ-SEC-06 @REQ-TRC-02 @REQ-VER-02
Feature: Run reports
  "sentinel report" writes a machine-readable report.json and a Markdown report.md rendered from
  it. The report is built from the registry only, is scrubbed, marks missing values as missing,
  and is reproducible, so a human can accept a run by the report's hash.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos
    And a version 2 run "leave-balance" at tier 3 on repos "backend" and "frontend" in state COMPLETED with acceptance "accepted"
    And its tasks ran on runner "fake" with model "fake-model", and two of them reported tokens and cost while the others reported none

  Rule: The report holds every section and is rendered from JSON

    @AC-ART-01e @integration @P1 @cov-happy-path
    Scenario: report.json holds every section
      When "sentinel report leave-balance --json" is run
      Then it exits with code 0
      And .sentinel/runs/leave-balance/report.json is written and printed
      And it has the sections "execution", "specification", "gherkin", "agents", "cycles", "verification", "regression", "findings", "changed_files", "acceptance", "trace" and "cost"
      And "specification" and "gherkin" hold the approved version, sha256, approver and decision time
      And "acceptance" holds the computed result with reasons and the human decision, which is "pending"
      And "agents" lists every task with role, adapter, provider, model, attempt, state, error code, started and finished times

    @AC-ART-01f @integration @P1 @cov-happy-path
    Scenario: report.md is rendered from report.json
      When "sentinel report leave-balance" is run
      Then .sentinel/runs/leave-balance/report.md has one heading per section of report.json in the same order
      And every number and hash shown in report.md appears in report.json
      And the output ends with the two file paths

    @AC-ART-01g @integration @P1 @cov-data-integrity
    Scenario: The report is reproducible
      Given "sentinel report leave-balance" was run and report.json has sha256 H
      When "sentinel report leave-balance" is run again with no new event
      Then report.json has sha256 H
      And report.json holds the id of the last event it was built from and no wall-clock generation time

    @AC-ART-01h @integration @P2 @cov-data-integrity
    Scenario: The report is registered as an artifact
      When "sentinel report leave-balance" is run
      Then an artifact row of kind "report" with the sha256 of report.json is stored
      And the run state, the acceptance status and the task rows are unchanged

  Rule: Missing values are shown as missing

    @AC-ANL-02a @unit @P1 @cov-empty-null
    Scenario: Unreported cost is null with a reason, never zero
      When the engine builds the report for "leave-balance"
      Then each task that reported no tokens has tokens null and cost null with reason "not reported by provider"
      And the run total cost is the sum of the two reported costs, marked "partial" with the count of tasks that reported none
      And report.md shows "not reported" for those tasks, not "0"

    @AC-ANL-02b @unit @P2 @cov-empty-null
    Scenario: A report of an unfinished run marks later sections as not reached
      Given a version 2 run "leave-form" in state EXECUTING with one CYCLE_ACCEPTED cycle and one GREEN_RUNNING cycle
      When "sentinel report leave-form --json" is run
      Then "verification", "findings" and "acceptance" are marked "not reached"
      And the acceptance status in the report is "pending"
      And "cycles" lists both cycles with their current state

  Rule: Regression, claims and trace gaps are reported separately from failures

    @AC-VER-02d @unit @P1 @cov-data-integrity
    Scenario: Claims that disagree with evidence are flagged
      Given the tdd_green task of cycle "remaining" claimed it changed backend/src/main/java/leave/Balance.java and backend/src/main/java/leave/Policy.java
      And the engine recorded only backend/src/main/java/leave/Balance.java as changed
      When the engine builds the report for "leave-balance"
      Then the "agents" entry of that task flags the claim "backend/src/main/java/leave/Policy.java" as "not in evidence"
      And the report "changed_files" section lists only backend/src/main/java/leave/Balance.java for that task

    @AC-VER-02e @unit @P2 @cov-happy-path
    Scenario: The regression section compares the full suite with the baseline
      Given the baseline of repo "backend" had the failing set ["LegacyTest.flaky", "OldTest.broken"]
      And the latest "test" row of "backend" has the failing set ["LegacyTest.flaky"]
      When the engine builds the report for "leave-balance"
      Then "regression" for "backend" lists new failures [], still failing ["LegacyTest.flaky"] and now passing ["OldTest.broken"]

    @AC-TRC-02c @unit @P1 @cov-missing-fields
    Scenario: Trace gaps and failing checks are in different lists
      Given scenario "Unused days carry over" has no "scenario -> test" link
      And the "lint" row of "frontend" in the latest round failed
      When the engine builds the report for "leave-balance"
      Then "trace.gaps" lists "scenario Unused days carry over has no test link" and nothing else
      And "verification.failures" lists "frontend lint" and nothing else

  Rule: Reports are scrubbed and need a version 2 run

    @AC-SEC-06b @integration @P1 @cov-perf-security
    Scenario: Report files are scrubbed
      Given a task summary of "leave-balance" contains "token=ghp_abcdef123456" and the path "/home/alice/work/leave"
      When "sentinel report leave-balance" is run
      Then neither report.json nor report.md contains "ghp_abcdef123456" or "/home/alice"
      And both contain "[REDACTED:secret]" and "$HOME"

    @AC-ART-01i @integration @P2 @cov-invalid-input
    Scenario Outline: Report requests that are refused
      Given a 0.1 run "old-fix" created with "sentinel run new old-fix --tier 2"
      When "sentinel report <slug>" is run
      Then it exits with code <code>
      And the error is <error>
      Examples:
        | slug        | code | error           |
        | no-such-run | 5    | "E_NOT_FOUND"   |
        | ../x        | 5    | "E_VALIDATION"  |
        | old-fix     | 5    | "E_TRANSITION"  |
