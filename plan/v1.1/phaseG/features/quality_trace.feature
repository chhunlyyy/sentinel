@REQ-TDD-06 @REQ-VER-02 @REQ-VER-03 @REQ-VER-04 @REQ-GIT-01 @REQ-GIT-03 @REQ-TRC-01 @REQ-TRC-02
Feature: TDD cycles, verification evidence, final acceptance, diffs and trace
  The quality views show what the engine stored: cycles with their phase tasks and evidence,
  the evidence rows of the latest verification round, the computed acceptance with its reasons,
  the changes per repo with their diffs, and the chain REQ to AC to scenario to cycle to files to
  evidence to acceptance with gaps listed apart from failures. Agent claims are never shown as
  evidence. Final acceptance needs the typed prefix of the report sha256.

  Background:
    Given the built dashboard is served by the fake API server on 127.0.0.1 with fixture set "two-projects"
    And the browser holds a valid session cookie
    And run "leave-balance" of "digital-hr" is REVIEWING at tier 3 with 3 cycles, evidence rows, changes and trace links

  Rule: TDD cycles

    @AC-TDD-06g @e2e @P1 @cov-happy-path
    Scenario: The cycles of a run
      When the user opens the "TDD" tab of run "leave-balance"
      Then each cycle shows its behavior, repo, state and the Red, Green and Refactor phases
      And each phase shows its task id, state, attempt and a link to each evidence row by id
      And the cycle states are shown as text, with CYCLE_ACCEPTED, REJECTED and the running states told apart in words

    @AC-TDD-06h @e2e @P2 @cov-happy-path
    Scenario: The evidence of a phase
      When the user opens the Red evidence of cycle "remaining"
      Then it shows command, exit code, test counts, classification, start and end time, provider, model and the changed files with their sha256 prefix
      And the captured output is loaded from GET /api/v1/tasks/leave-balance/artifacts/{aid} and shown as plain text

    @AC-TDD-06i @e2e @P2 @cov-data-integrity
    Scenario: Evidence output that changed on disk
      Given GET /api/v1/tasks/leave-balance/artifacts/a-out1 answers 409 with error code "E_INTEGRITY" and the stored sha256
      When the user opens that output
      Then the panel says "The file changed after it was stored. Its content is not shown." with the stored sha256
      And no content is shown

    @AC-TDD-06j @e2e @P3 @cov-empty-null
    Scenario: A run before execution has no cycles
      Given GET /api/v1/tasks/leave-balance/tdd answers no cycles
      When the user opens the "TDD" tab
      Then the tab says "No TDD cycles yet. Cycles are planned after the Gherkin approval."

  Rule: Verification evidence

    @AC-VER-02f @e2e @P1 @cov-happy-path
    Scenario: The evidence rows of the latest round
      When the user opens the "Verification" tab of run "leave-balance"
      Then it shows round number and time, and per repo each check with kind, status, exit code, test counts, time and a link to its output
      And rows with status "not_configured" or "disabled" are listed under "Not run" and never under "Missing" or "Failed"
      And missing evidence is listed under "Missing evidence"

    @AC-VER-02g @e2e @P1 @cov-data-integrity
    Scenario: Agent claims are not shown as evidence
      Given the result.json of the tdd_green task claims "all tests pass" and there is no evidence row for it
      When the user opens the "Verification" tab
      Then the tab shows only rows of the verification answer
      And the claim is not shown on this tab and the missing row is listed under "Missing evidence"

    @AC-VER-03g @e2e @P1 @cov-errors
    Scenario: The computed acceptance and its reasons
      Given the verification answer has computed acceptance "rejected" with reasons "required tests fail" and "required reviews open"
      When the user opens the "Verification" tab
      Then the acceptance panel says "Computed: rejected" and lists both reasons in the engine's order
      And each reason links to the view that shows it

  Rule: Final acceptance

    @AC-VER-04n @e2e @P1 @cov-happy-path
    Scenario: Confirming acceptance
      Given run "leave-form" is COMPLETED with computed acceptance "accepted" and report sha256 R starting with "77ab01cd"
      When the user opens the acceptance panel of "leave-form", reads the report, types "77ab01cd" and presses "Confirm acceptance"
      Then POST /api/v1/tasks/leave-form/acceptance is sent with body {"sha256_of_report": R, "confirmation": "77ab01cd", "decision": "accept", "comment": null}
      And after the 200 answer the panel shows "Acceptance confirmed" with approver, channel "dashboard" and time from the answer

    @AC-VER-04o @e2e @P1 @cov-authz
    Scenario Outline: Acceptance cannot be confirmed when the engine does not allow it
      Given <state>
      When the user opens the acceptance panel of "leave-form"
      Then "Confirm acceptance" is <confirm> and "Reject" is <reject>
      And <text>
      Examples:
        | state                                                         | confirm      | reject       | text                                                         |
        | run "leave-form" is COMPLETED with computed acceptance "rejected" | not shown | enabled      | the panel says "The engine rejected this run" with the reasons |
        | run "leave-form" is REVIEWING                                 | not shown    | not shown    | the panel says "Acceptance is possible when the run is COMPLETED" |
        | a human already confirmed "leave-form"                        | not shown    | enabled      | the panel shows the confirmation record                      |
        | a human already rejected "leave-form"                         | not shown    | not shown    | the panel shows the rejection record and "This cannot change" |

    @AC-VER-04p @e2e @P2 @cov-missing-fields
    Scenario: Rejecting a run needs a comment and a second confirmation
      Given run "leave-form" is COMPLETED with computed acceptance "accepted"
      When the user chooses "Reject", types "77ab01cd" and leaves the comment empty
      Then the "Reject" button is disabled
      And after entering comment "wrong totals" and pressing "Reject", a dialog asks again before the POST with decision "reject" is sent

    @AC-VER-04q @e2e @P2 @cov-data-integrity
    Scenario: The report changed after the page loaded
      Given the fake API answers the acceptance with 409 and error code "E_APPROVAL_STALE"
      When the user confirms acceptance with "77ab01cd"
      Then the panel says "The report changed. Nothing was confirmed. Reload the report."
      And no second POST is sent

  Rule: Changes and diffs

    @AC-GIT-01e @e2e @P1 @cov-happy-path
    Scenario: The change map of a run
      When the user opens the "Changes" tab of run "leave-balance"
      Then each repo shows branch, base commit, head commit, number of files, additions and deletions
      And each file shows its status, additions, deletions and links to its cycles and tasks

    @AC-GIT-01f @e2e @P1 @cov-happy-path
    Scenario Outline: Inline and side-by-side diffs
      When the user opens the diff of "backend" file "src/main/Leave.java" in mode "<mode>"
      Then GET /api/v1/tasks/leave-balance/changes/diff?repo=backend&path=src%2Fmain%2FLeave.java&mode=<mode> is called
      And <layout>
      And added and removed lines carry "+" and "-" signs and a text alternative, not only colour
      Examples:
        | mode   | layout                                                              |
        | inline | one column shows old and new line numbers and the lines in order    |
        | split  | two columns show the old lines left and the new lines right         |

    @AC-GIT-01g @e2e @P2 @cov-boundary
    Scenario Outline: Binary and truncated diffs
      Given the diff answer for the file has <flag>
      When the user opens its diff
      Then the panel says "<message>"
      Examples:
        | flag             | message                                                  |
        | binary true      | Binary file. No diff shown.                              |
        | truncated true   | The diff is longer than 1 MB. Only the start is shown.   |

    @AC-GIT-03a @e2e @P3 @cov-happy-path
    Scenario: The change map is part of the run view
      When the user opens run "leave-balance"
      Then the run overview shows the changed file count and additions and deletions per repo with a link to the "Changes" tab

  Rule: Trace

    @AC-TRC-01e @e2e @P1 @cov-happy-path
    Scenario: The full chain
      When the user opens the "Trace" tab of run "leave-balance"
      Then each REQ lists its ACs, each AC its scenarios, each scenario its cycle, each cycle its changed files and evidence, and the run its acceptance
      And each item links to its view: scenario to the Gherkin review, cycle to the TDD tab, file to its diff, evidence to its row

    @AC-TRC-02d @e2e @P1 @cov-data-integrity
    Scenario: Gaps are shown apart from failures
      Given the trace answer has gap "AC-3 has no scenario" and evidence "test" of cycle "remaining" failed
      When the user opens the "Trace" tab
      Then "AC-3 has no scenario" is listed under "Gaps (missing links)"
      And the failed evidence is listed under "Failures (failing checks)"
      And neither list holds the other's item

    @AC-TRC-02e @e2e @P3 @cov-empty-null
    Scenario: A run with no trace links yet
      Given the trace answer has no links and no gaps
      When the user opens the "Trace" tab
      Then the tab says "No trace links yet" and shows no "Gaps" or "Failures" heading
