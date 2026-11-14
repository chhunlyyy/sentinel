@REQ-SEC-01 @REQ-SEC-03 @REQ-SEC-04 @REQ-SEC-07 @REQ-API-03 @REQ-VER-04
Feature: Human decisions through the dashboard channel
  A human in the dashboard decides an approval or the final acceptance with the session cookie,
  the CSRF header, the full sha256 the reviewer saw and the 8-character confirmation the
  reviewer typed. The server calls the same engine function as the TTY command, with actor
  "human" and channel "dashboard". Every decision and every refused attempt is audited.

  Background:
    Given HOME is a temporary folder for OS user "dev" and git user.name is "Dev User"
    And workspace "digital-hr" is registered as project "digital-hr"
    And the server listens on 127.0.0.1 port P and the client holds session cookie S and CSRF value C
    And a version 2 run "leave-balance" at tier 3 is SPECIFICATION_REVIEW with specification version 2 in review
    And the sha256 of version 2 is H2, which starts with "3f9a0c12"

  Rule: Approving, requesting changes and rejecting

    @AC-SEC-03f @integration @P1 @cov-happy-path
    Scenario: A human approves the specification in the dashboard
      When POST /api/v1/tasks/leave-balance/approvals is sent with cookie S, CSRF header C and body {"gate": "specification", "sha256": H2, "confirmation": "3f9a0c12", "decision": "approve", "comment": "Looks right"}
      Then the status is 200 and the answer holds the run state SPECIFICATION_APPROVED as the engine stored it
      And the specification approval is APPROVED with version 2, sha256 H2, decision "approve" and comment "Looks right"
      And the approval records approver "dev", git name "Dev User", channel "dashboard" and the decision time
      And an "approval.decided" event has actor kind "human" and channel "dashboard"
      And the audit log has a row with actor "dev", channel "dashboard", action "approved", target "leave-balance/specification" and after hash H2

    @AC-SEC-03g @integration @P1 @cov-happy-path
    Scenario Outline: Requesting changes and rejecting
      When POST /api/v1/tasks/leave-balance/approvals is sent with body {"gate": "specification", "sha256": H2, "confirmation": "3f9a0c12", "decision": "<decision>", "comment": "<comment>"}
      Then the status is 200
      And the run state is <state>
      And the approval has decision "<decision>" and channel "dashboard"
      Examples:
        | decision | comment                       | state     |
        | changes  | Add the carry-over rule       | PLANNED   |
        | reject   | Not needed                    | CANCELLED |

    @AC-SEC-03h @integration @P1 @cov-happy-path
    Scenario: Approving the Gherkin set
      Given the run is GHERKIN_REVIEW with Gherkin version 1 in review whose set hash is G1
      When POST /api/v1/tasks/leave-balance/approvals is sent with body {"gate": "gherkin", "sha256": G1, "confirmation": the first 8 characters of G1, "decision": "approve"}
      Then the status is 200 and the run state is GHERKIN_APPROVED
      And the Gherkin approval has channel "dashboard"

    @AC-API-03b @contract @P1 @cov-data-integrity
    Scenario: The dashboard and the terminal store the same decision
      Given two copies of the same run in SPECIFICATION_REVIEW
      When the first is approved at a terminal with "sentinel approve leave-balance spec -m ok" and the prefix "3f9a0c12"
      And the second is approved through the API with sha256 H2, confirmation "3f9a0c12" and comment "ok"
      Then the approval rows, events and resulting run states are equal except for channel and times

  Rule: The hash and the confirmation must match the artifact in review

    @AC-SEC-03i @security @P1 @cov-data-integrity
    Scenario: A hash from an older version is stale
      Given the sha256 of specification version 1 is H1
      When POST /api/v1/tasks/leave-balance/approvals is sent with sha256 H1, the first 8 characters of H1 as confirmation and decision "approve"
      Then the status is 409 with error code "E_APPROVAL_STALE" and details.current_sha256 H2
      And the approval stays IN_REVIEW and the run stays SPECIFICATION_REVIEW
      And the audit log has a row with channel "dashboard", action "approve_refused" and reason "E_APPROVAL_STALE"

    @AC-SEC-03j @security @P1 @cov-data-integrity
    Scenario: The spec changes while the reviewer looks at it
      Given the reviewer loaded version 2 with sha256 H2
      And then the specifier wrote version 3 with sha256 H3 and the engine put version 3 in review
      When POST /api/v1/tasks/leave-balance/approvals is sent with sha256 H2, confirmation "3f9a0c12" and decision "approve"
      Then the status is 409 with error code "E_APPROVAL_STALE" and details.current_sha256 H3
      And no approval is APPROVED

    @AC-SEC-03k @security @P1 @cov-invalid-input
    Scenario Outline: Bad hash or confirmation
      When POST /api/v1/tasks/leave-balance/approvals is sent with sha256 <sha256>, confirmation <confirmation> and decision "approve"
      Then the status is 400 with error code "E_VALIDATION"
      And the approval stays IN_REVIEW
      And the audit log has a row with channel "dashboard", action "approve_refused" and reason "E_VALIDATION"
      Examples:
        | sha256                                  | confirmation          |
        | "3f9a0c12"                              | "3f9a0c12"            |
        | H2 with its last character changed      | "3f9a0c12"            |
        | 64 hex characters of no known version   | the first 8 of those  |
        | H2                                      | "3f9a0c13"            |
        | H2                                      | "3f9a0c1"             |
        | H2                                      | ""                    |

    @AC-SEC-03l @security @P1 @cov-missing-fields
    Scenario Outline: Missing fields
      When POST /api/v1/tasks/leave-balance/approvals is sent with a body that lacks <field>
      Then the status is 400 with error code "E_VALIDATION" naming <field>
      And the approval stays IN_REVIEW
      Examples:
        | field        |
        | gate         |
        | sha256       |
        | confirmation |
        | decision     |

    @AC-SEC-03m @integration @P2 @cov-empty-null
    Scenario Outline: Requesting changes needs a comment
      When POST /api/v1/tasks/leave-balance/approvals is sent with sha256 H2, confirmation "3f9a0c12", decision "changes" and comment <comment>
      Then the status is 400 with error code "E_VALIDATION" and message "requesting changes needs a comment"
      Examples:
        | comment  |
        | absent   |
        | null     |
        | ""       |
        | "   "    |

    @AC-SEC-03n @integration @P2 @cov-invalid-input
    Scenario Outline: Gate, decision and state refusals use the engine's codes
      Given <state>
      When POST /api/v1/tasks/leave-balance/approvals is sent with gate "<gate>", decision "<decision>" and a matching sha256 and confirmation
      Then the status is <status> with error code "<code>"
      Examples:
        | state                                         | gate          | decision | status | code               |
        | the run is SPECIFICATION_REVIEW               | tests         | approve  | 400    | E_VALIDATION       |
        | the run is SPECIFICATION_REVIEW               | specification | maybe    | 400    | E_VALIDATION       |
        | the run is EXECUTING                          | specification | approve  | 409    | E_TRANSITION       |
        | the run is a docs run in SPECIFICATION_APPROVED | gherkin     | approve  | 422    | E_PRECONDITION     |
        | the run is a 0.1 run                          | specification | approve  | 409    | E_TRANSITION       |

    @AC-SEC-03o @security @P1 @cov-data-integrity
    Scenario: An approved artifact is re-hashed before the decision is stored
      Given the spec file on disk was changed after version 2 was stored, without a new version yet
      When POST /api/v1/tasks/leave-balance/approvals is sent with sha256 H2, confirmation "3f9a0c12" and decision "approve"
      Then the engine stores the changed file as specification version 3 in review before it checks the hash
      And the status is 409 with error code "E_APPROVAL_STALE" and details.current_sha256 the hash of version 3
      And no approval is APPROVED

  Rule: Only a human with a session decides

    @AC-SEC-03p @security @P1 @cov-authz
    Scenario Outline: Calls without a full session cannot decide
      When POST /api/v1/tasks/leave-balance/approvals is sent with a valid body and <credentials>
      Then the status is <status>
      And the approval stays IN_REVIEW and no "approval.decided" event exists
      Examples:
        | credentials                                     | status |
        | no cookie and CSRF header C                     | 401    |
        | cookie S and no CSRF header                     | 403    |
        | cookie S, CSRF header C and Origin "http://evil.example" | 403 |

    @AC-SEC-03q @security @P1 @cov-authz
    Scenario: An agent launched by Sentinel has no way to the token through Sentinel
      Given the server dispatched a CLI task whose fake runner dumps its environment and arguments and tries "sentinel dashboard --no-open"
      When the task finishes
      Then the dumped environment holds no SENTINEL_DASHBOARD_TOKEN and no value equal to the token
      And the arguments and prompt.md hold no token
      And the runner's "sentinel dashboard" call exited with code 5 and error "E_ACTOR"

    @AC-SEC-04c @integration @P2 @cov-authz
    Scenario: Generated agent configs forbid reading the dashboard token
      Given a workspace with runner "claude" configured
      When "sentinel sync-adapters" is run
      Then the generated Claude settings deny reading "~/.config/sentinel/server.json"
      And the generated agent instructions state that agents never read the dashboard token or call the local API

  Rule: Final acceptance through the dashboard

    @AC-VER-04k @integration @P1 @cov-happy-path
    Scenario: A human confirms acceptance in the dashboard
      Given run "leave-form" is COMPLETED with acceptance "accepted" and report.json sha256 R, which starts with "77ab01cd"
      When POST /api/v1/tasks/leave-form/acceptance is sent with cookie S, CSRF header C and body {"sha256_of_report": R, "confirmation": "77ab01cd", "decision": "accept", "comment": "Shipped"}
      Then the status is 200
      And an "acceptance" approval records decision "accept", sha256 R, approver "dev" and channel "dashboard"
      And the audit log has a row with channel "dashboard" and action "accepted"

    @AC-VER-04l @integration @P1 @cov-authz
    Scenario Outline: The dashboard cannot accept what the engine rejects or change a rejection
      Given <state>
      When POST /api/v1/tasks/leave-form/acceptance is sent with the matching report hash, confirmation and decision "accept"
      Then the status is <status> with error code "<code>"
      And the acceptance status of "leave-form" is unchanged
      Examples:
        | state                                                                  | status | code            |
        | run "leave-form" is COMPLETED with computed acceptance "rejected"      | 409    | E_TRANSITION    |
        | a human already rejected "leave-form"                                  | 409    | E_TRANSITION    |
        | a human already confirmed "leave-form"                                 | 409    | E_TRANSITION    |
        | run "leave-form" is REVIEWING                                          | 409    | E_TRANSITION    |

    @AC-VER-04m @integration @P2 @cov-missing-fields
    Scenario: Rejecting in the dashboard needs a comment
      Given run "leave-form" is COMPLETED with acceptance "accepted"
      When POST /api/v1/tasks/leave-form/acceptance is sent with the matching report hash, confirmation and decision "reject" and no comment
      Then the status is 400 with error code "E_VALIDATION"

  Rule: Two humans, one decision

    @AC-SEC-03r @integration @P1 @cov-concurrency
    Scenario: Dashboard and terminal approve the same approval at the same moment
      Given a human at a pseudo-terminal has run "sentinel approve leave-balance spec" and is at the hash prompt
      When the terminal human types "3f9a0c12" and the dashboard POST with sha256 H2 and confirmation "3f9a0c12" is sent at the same moment
      Then exactly one of them succeeds
      And the other is refused: the API with 409 "E_TRANSITION", or the terminal with exit code 5 and "E_TRANSITION"
      And there is exactly one "approval.decided" event and one approval row with state APPROVED, whose channel is the winner's
      And the audit log has one "approved" row and one "approve_refused" row

    @AC-SEC-03s @integration @P2 @cov-duplicate
    Scenario: The same dashboard decision sent twice
      When two POSTs with the same approval body are sent at the same time from two browser tabs
      Then one answers 200 and the other answers 409 with error code "E_TRANSITION"
      And exactly one "approval.decided" event exists

    @AC-SEC-03t @integration @P2 @cov-concurrency
    Scenario: A request-changes and an approve race
      When a dashboard POST with decision "changes" and a terminal approval of H2 run at the same moment
      Then exactly one decision is stored and the run state matches that decision
      And the losing call is refused with "E_TRANSITION"

  Rule: A failed write leaves the approval undecided

    @AC-SEC-03u @integration @P2 @cov-db-failure
    Scenario: The registry write fails during a dashboard approval
      Given the registry is set to fail the next write transaction
      When POST /api/v1/tasks/leave-balance/approvals is sent with sha256 H2, confirmation "3f9a0c12" and decision "approve"
      Then the status is 500 with error code "E_INTERNAL" and a message without a traceback
      And the approval stays IN_REVIEW, the run stays SPECIFICATION_REVIEW and no "approval.decided" event exists
      And a repeated POST after the fault is cleared answers 200
