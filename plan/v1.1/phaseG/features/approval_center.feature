@REQ-SPA-04 @REQ-SPA-05 @REQ-SPA-06 @REQ-SPA-08 @REQ-GHA-04 @REQ-GHA-05 @REQ-SEC-03 @REQ-DSH-04
Feature: Approval center for the specification and the Gherkin set
  The reviewer sees the exact version in review with its full sha256, its validation, the diff
  to the previous version and, for Gherkin, every scenario with its tags and the coverage table.
  Approving needs the reviewer to type the first 8 characters of that sha256; the request
  carries the full sha256 the reviewer saw and the typed confirmation (Phase F point 1).
  Requesting changes needs a comment. Rejecting needs a second confirmation. The page never
  shows a decision as stored before the API answer says so.

  Background:
    Given the built dashboard is served by the fake API server on 127.0.0.1 with fixture set "two-projects"
    And the browser holds a valid session cookie
    And run "leave-balance" of "digital-hr" is SPECIFICATION_REVIEW with specification version 2 in review
    And the sha256 of version 2 is H2, which starts with "3f9a0c12"

  Rule: My Approvals

    @AC-SEC-03x @e2e @P1 @cov-happy-path
    Scenario: Approvals waiting across projects
      Given run "tax-form" of "payroll" is GHERKIN_REVIEW with Gherkin version 1 in review
      When the user opens "My Approvals"
      Then GET /api/v1/approvals?state=IN_REVIEW is called
      And the list shows project, run, gate, version, sha256 prefix and the time the review was requested for both
      And the navigation entry "My Approvals" shows the count 2 as text

    @AC-SEC-03y @e2e @P3 @cov-empty-null
    Scenario: Nothing to approve
      Given no approval is IN_REVIEW
      When the user opens "My Approvals"
      Then the page says "Nothing waits for your approval"

  Rule: Reviewing the specification

    @AC-SPA-04d @e2e @P1 @cov-happy-path
    Scenario: The specification review page
      When the user opens the specification review of "leave-balance"
      Then it shows "Version 2" and the full sha256 H2 in a monospace field with a copy button
      And it shows the validation result with each finding
      And it shows the specification text as plain text with its headings, REQ and AC ids readable
      And a "Changes since version 1" tab shows the diff to version 1
      And a "Versions" list links each earlier version with its sha256 prefix, decision, reviewer, channel and time

    @AC-SPA-04e @e2e @P2 @cov-happy-path
    Scenario: An earlier version is shown read only
      When the user opens version 1 from the "Versions" list
      Then GET /api/v1/tasks/leave-balance/specification/versions/1 is called
      And the page says "Version 1 is not in review" and has no decision controls

  Rule: Reviewing the Gherkin set

    @AC-GHA-04f @e2e @P1 @cov-happy-path
    Scenario: The Gherkin review page
      Given the run is GHERKIN_REVIEW with Gherkin version 1 in review whose set hash is G1
      When the user opens the Gherkin review of "leave-balance"
      Then it shows "Version 1" and the full set hash G1
      And it lists each feature file with its scenarios, each scenario with its AC, type, priority and coverage tags
      And the coverage table shows each of the 15 categories with "covered by N scenarios", "not applicable" and its reason, or "missing"
      And a missing category is marked by the word "Missing" and an icon with a text alternative

    @AC-GHA-04g @e2e @P2 @cov-boundary
    Scenario: A large Gherkin set stays usable
      Given the Gherkin set has 12 feature files and 400 scenarios
      When the user opens the Gherkin review of "leave-balance"
      Then the page is interactive within 2 seconds on the test machine
      And a filter by AC id or tag narrows the list
      And the decision panel stays reachable without scrolling through every scenario

  Rule: Approving needs the typed hash prefix

    @AC-SPA-05e @e2e @P1 @cov-happy-path
    Scenario: Approving the specification
      When the user opens the specification review, chooses "Approve", types "3f9a0c12" in the field labelled "Type the first 8 characters of the sha256 to confirm" and presses "Approve version 2"
      Then POST /api/v1/tasks/leave-balance/approvals is sent with body {"gate": "specification", "sha256": H2, "confirmation": "3f9a0c12", "decision": "approve", "comment": null}
      And after the 200 answer the page shows "Approved" with approver, channel "dashboard" and time from the answer
      And the decision controls are gone

    @AC-SEC-03z @unit @P1 @cov-invalid-input
    Scenario Outline: The approve button stays disabled until the prefix matches
      Given the decision panel for sha256 H2 with decision "approve"
      When the user types <typed>
      Then the "Approve version 2" button is <state>
      And the field hint says "<hint>"
      Examples:
        | typed         | state    | hint                                      |
        | ""            | disabled | Type the first 8 characters               |
        | "3f9a0c1"     | disabled | Type the first 8 characters               |
        | "3f9a0c13"    | disabled | Does not match                            |
        | "3F9A0C12"    | disabled | Does not match                            |
        | " 3f9a0c12"   | disabled | Does not match                            |
        | "3f9a0c12"    | enabled  | Matches                                   |

    @AC-SPA-06i @e2e @P1 @cov-perf-security
    Scenario: The prefix is never filled in for the reviewer
      When the user opens the decision panel
      Then the confirmation field is empty, has autocomplete "off" and is not pre-filled from the hash
      And no control of the page copies the hash or its prefix into the field
      And pasting the full sha256 into it leaves the field not matching, because only 8 characters are compared
      And the request sent is built from the sha256 loaded with the page, never fetched again at click time

    @AC-GHA-05k @e2e @P1 @cov-happy-path
    Scenario: Approving the Gherkin set
      Given the run is GHERKIN_REVIEW with Gherkin version 1 in review whose set hash is G1
      When the user types the first 8 characters of G1 and presses "Approve version 1"
      Then the body holds gate "gherkin", sha256 G1 and decision "approve"
      And after the 200 answer the page shows "Approved"

  Rule: Requesting changes and rejecting

    @AC-SPA-05f @e2e @P1 @cov-missing-fields
    Scenario Outline: Requesting changes needs a comment
      When the user chooses "Request changes", types "3f9a0c12" and enters the comment <comment>
      Then the "Request changes" button is <state>
      Examples:
        | comment                         | state    |
        | ""                              | disabled |
        | "   "                           | disabled |
        | "Add the carry-over rule"       | enabled  |

    @AC-SPA-05g @e2e @P1 @cov-happy-path
    Scenario: Requesting changes
      When the user requests changes with "3f9a0c12" and comment "Add the carry-over rule"
      Then the body holds decision "changes" and comment "Add the carry-over rule"
      And after the 200 answer the page shows "Changes requested" and the run state from the answer

    @AC-SPA-05h @e2e @P1 @cov-authz
    Scenario: Rejecting needs a second confirmation
      When the user chooses "Reject", types "3f9a0c12", enters comment "Not needed" and presses "Reject version 2"
      Then a dialog says "Rejecting cancels run leave-balance. This cannot be undone." with "Cancel" focused
      And no request is sent until the user presses "Reject run" in the dialog
      And then the body holds decision "reject"

  Rule: Stale and changed versions

    @AC-SPA-08h @e2e @P1 @cov-data-integrity
    Scenario: A stale hash is shown, never retried with the new hash
      Given the fake API answers the approval with 409, error code "E_APPROVAL_STALE" and details.current_sha256 H3
      When the user approves version 2 with "3f9a0c12"
      Then the page says "A newer version is in review. Nothing was approved."
      And exactly one POST was sent and no POST carries H3
      And the page offers "Load the version in review", which loads version 3 with an empty confirmation field

    @AC-SPA-08i @e2e @P1 @cov-concurrency
    Scenario: A new version arrives while the reviewer reads
      Given the reviewer has typed "3f9a0c12" on version 2
      When the event stream sends an "approval.state_changed" event for "leave-balance" that puts version 3 in review
      Then a banner says "Version 3 replaced the version you are reading" and the decision controls are disabled
      And the typed confirmation is cleared

    @AC-SPA-06j @e2e @P2 @cov-concurrency
    Scenario: Someone else decided first
      Given the fake API answers the approval with 409 and error code "E_TRANSITION" because a terminal approval won
      When the user approves version 2 with "3f9a0c12"
      Then the page says "Refused: the run moved on." and shows the approval state from a fresh GET
      And no success message was shown

    @AC-SPA-06k @e2e @P2 @cov-db-failure
    Scenario: The server could not store the decision
      Given the fake API answers the approval with 500 and error code "E_INTERNAL"
      When the user approves version 2 with "3f9a0c12"
      Then the page says "Not confirmed: server error. See the terminal running sentinel dashboard."
      And the approval is still shown as "In review" and the typed confirmation is kept for one deliberate retry

    @AC-SPA-06l @e2e @P2 @cov-duplicate
    Scenario: Two tabs decide the same approval
      Given the specification review is open in two tabs
      When the user approves in the first tab and then in the second
      Then the first shows "Approved"
      And the second receives 409 "E_TRANSITION" and shows the stored decision from a fresh GET

  Rule: Opening a review is never a decision

    @AC-SPA-05i @e2e @P1 @cov-authz
    Scenario: Reading, navigating and reconnecting send no decision
      When the user opens the review pages of both gates, follows every link on them, reloads them and the event stream reconnects
      Then no POST to /api/v1/tasks/leave-balance/approvals was sent
