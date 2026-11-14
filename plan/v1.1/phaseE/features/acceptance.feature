@REQ-VER-03 @REQ-VER-04 @REQ-SM-02 @REQ-TRC-01 @REQ-TRC-02 @REQ-SEC-03 @REQ-SEC-07
Feature: Run completion, computed acceptance and final human acceptance
  The engine completes a reviewed run (R15) and computes acceptance from evidence: accepted only
  when every rule of VER-03 holds, otherwise rejected with every reason. A human at a terminal
  may then confirm acceptance or reject the run (R25); nothing turns a rejected run into an
  accepted one, and no agent decides.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos
    And a version 2 run "leave-balance" at tier 3 on repos "backend" and "frontend" with both approvals valid
    And cycles "remaining" on repo "backend" and "request-form" on repo "frontend" are CYCLE_ACCEPTED with complete evidence and trace links

  Rule: R15 completes the run and computes acceptance

    @AC-VER-03a @integration @P1 @cov-happy-path
    Scenario: A clean run completes accepted
      Given the run is REVIEWING, verification round 1 passed and every review task is COMPLETED with no open blocker or major finding
      When "sentinel next leave-balance --json" is run
      Then the run state is COMPLETED and the "run.state_changed" event names transition "R15" and actor kind "engine"
      And the execution status is "completed" and the acceptance status is "accepted" with no reasons
      And the output JSON has kind "done" with human acceptance "pending" and the command "sentinel accept leave-balance"
      And it exits with code 0

    @AC-VER-03b @integration @P1 @cov-happy-path
    Scenario: Completion records final SHAs, writes the report and releases the lock
      Given the run is REVIEWING and ready for R15
      When "sentinel next leave-balance --json" is run
      Then run_repos holds a final_sha for "backend" and "frontend"
      And .sentinel/runs/leave-balance/report.json and report.md exist
      And the lock on slug "leave-balance" is released
      And a "run.status_changed" event holds execution "completed", acceptance "accepted" and reasons []

    @AC-VER-03c @integration @P1 @cov-errors
    Scenario Outline: Each acceptance rule gives its own rejection reason
      Given the run is REVIEWING and ready for R15
      And <gap>
      When the engine computes acceptance for "leave-balance"
      Then the result is "rejected" and the reasons include "<reason>"
      Examples:
        | gap                                                                                       | reason                                         |
        | the specification approval is INVALIDATED                                                 | specification approval missing or invalid      |
        | the Gherkin approval is missing                                                           | gherkin approval missing or invalid            |
        | the approved spec file was edited after approval                                          | specification approval missing or invalid      |
        | cycle "request-form" is REFACTOR_VERIFIED                                                 | cycles incomplete: request-form                |
        | the "test" row of "backend" in the latest round failed                                    | required tests fail: backend test              |
        | no "scope" row exists for "frontend" in the latest round                                  | verification evidence missing: frontend scope  |
        | the latest verification round has no "finished" record                                    | verification evidence missing                  |
        | the "scope" row of "backend" failed                                                       | scope exceeded: backend                        |
        | a "major" finding is "waived"                                                             | required reviews open: 1 waived major finding  |
        | the qa task is CANCELLED                                                                  | required reviews open: qa                      |
        | the run is at tier 4 and no "security" approval is APPROVED                               | required human approval missing: security      |
        | a destructive migration was verified with no valid "migration" approval                   | required human approval missing: migration     |

    @AC-VER-03d @unit @P1 @cov-errors
    Scenario: All reasons are reported, not only the first
      Given the Gherkin approval is missing, cycle "request-form" is GREEN_VERIFIED and the "lint" row of "frontend" failed
      When the engine computes acceptance for "leave-balance"
      Then the reasons are exactly "gherkin approval missing or invalid", "cycles incomplete: request-form" and "required tests fail: frontend lint" in that order

    @AC-VER-03e @unit @P1 @cov-boundary
    Scenario Outline: Checks that were not run do not count as missing
      Given the latest verification round passed except that <row>
      When the engine computes acceptance for "leave-balance"
      Then the result is "accepted"
      And the report lists <row> under "not run"
      Examples:
        | row                                                    |
        | the "lint" row of "frontend" is "not_configured"       |
        | the "typecheck" row of "backend" is "disabled"         |

    @AC-VER-03f @unit @P1 @cov-data-integrity
    Scenario: Acceptance ignores agent claims
      Given every task result of "leave-balance" claims every test passed
      And the "test" row of "backend" in the latest round failed
      When the engine computes acceptance for "leave-balance"
      Then the result is "rejected" with reason "required tests fail: backend test"

    @AC-SM-02g @integration @P1 @cov-errors
    Scenario: R15 is refused while review work is open
      Given the run is REVIEWING with the qa task RUNNING
      When the engine checks R15 for "leave-balance"
      Then the run state is still REVIEWING
      And no "run.state_changed" event to COMPLETED is stored

  Rule: Trace links chain requirement to acceptance and gaps are not failures

    @AC-TRC-01d @integration @P1 @cov-happy-path
    Scenario: The full trace chain exists at completion
      Given the run is REVIEWING and ready for R15
      When "sentinel next leave-balance --json" is run
      Then for every approved scenario the registry links REQ -> AC -> scenario -> cycle -> test -> file -> evidence
      And a "run -> acceptance" link points to the computed acceptance record

    @AC-TRC-02b @unit @P1 @cov-missing-fields
    Scenario: A missing trace link is a gap, not a failed check
      Given the run is COMPLETED and accepted
      And the "cycle -> evidence" link of cycle "request-form" is missing while its evidence rows exist
      When the engine builds the trace report for "leave-balance"
      Then the trace report lists one gap "cycle request-form has no evidence link" under "gaps"
      And the "failures" list of the trace report is empty
      And the acceptance status is still "accepted"

  Rule: Final human acceptance is human-only and never turns rejected into accepted

    @AC-VER-04a @integration @P1 @cov-happy-path
    Scenario: A human confirms an accepted run
      Given the run is COMPLETED with acceptance "accepted"
      When a human runs "sentinel accept leave-balance -m 'pilot ok'" at an interactive terminal and types the first 8 hex characters of the report sha256
      Then it exits with code 0
      And an approval of gate "acceptance" with decision "accept", the report sha256, the approver, channel "tty" and comment "pilot ok" is stored
      And the run state is still COMPLETED and the acceptance status is "accepted"
      And an "acceptance" audit row and a "run.status_changed" event are stored

    @AC-VER-04b @integration @P1 @cov-happy-path
    Scenario: A human rejects an accepted run
      Given the run is COMPLETED with acceptance "accepted"
      When a human runs "sentinel accept leave-balance --reject -m 'wrong rounding'" at an interactive terminal and types the hash prefix
      Then the acceptance status is "rejected" with reason "rejected by human: wrong rounding"
      And the "run.state_changed" event names transition "R25"

    @AC-VER-04c @integration @P1 @cov-authz
    Scenario Outline: A rejected run can never become accepted
      Given the run is COMPLETED with acceptance "rejected" because <cause>
      When a human runs "sentinel accept leave-balance" at an interactive terminal and types the hash prefix
      Then it exits with code 5
      And the error is "E_PRECONDITION" listing the rejection reasons
      And the acceptance status is still "rejected"
      And a "acceptance_refused" audit row is stored
      Examples:
        | cause                                    |
        | the engine computed "required tests fail" |
        | a human rejected it earlier              |

    @AC-VER-04d @integration @P1 @cov-authz
    Scenario Outline: Acceptance outside an interactive human terminal is refused
      Given the run is COMPLETED with acceptance "accepted"
      When "sentinel accept leave-balance" is run <how>
      Then it exits with code 5
      And the error is "<error>"
      And no "acceptance" approval is stored and the acceptance status is "accepted" with human acceptance "pending"
      And a "acceptance_refused" audit row with the channel and the error is stored
      Examples:
        | how                                                         | error     |
        | with stdin not a terminal                                    | E_NOT_TTY |
        | by the orchestrator through the CLI with stdin from a pipe   | E_NOT_TTY |
        | inside a task process with SENTINEL_TASK_ID set              | E_ACTOR   |

    @AC-VER-04e @unit @P1 @cov-authz
    Scenario: The orchestrator cannot record acceptance through the engine
      Given the run is COMPLETED with acceptance "accepted"
      When the orchestrator calls the engine acceptance decision with decision "accept"
      Then the request is refused with error "E_ACTOR"
      And no "acceptance" approval is stored

    @AC-SEC-03e @integration @P1 @cov-invalid-input
    Scenario Outline: A wrong hash prefix or a changed report is refused
      Given the run is COMPLETED with acceptance "accepted"
      When a human runs "sentinel accept leave-balance" at an interactive terminal and <input>
      Then it exits with code 5
      And the error is "<error>"
      And no "acceptance" approval is stored
      Examples:
        | input                                                                            | error            |
        | types "00000000"                                                                 | E_VALIDATION     |
        | types nothing                                                                    | E_VALIDATION     |
        | types the prefix of a report.json that was regenerated with different content   | E_APPROVAL_STALE |

    @AC-VER-04f @integration @P1 @cov-invalid-input
    Scenario Outline: Acceptance is only for completed runs
      Given the run is in state <state>
      When a human runs "sentinel accept leave-balance" at an interactive terminal
      Then it exits with code 5
      And the error is "E_TRANSITION"
      Examples:
        | state       |
        | REVIEWING   |
        | NEEDS_HUMAN |
        | CANCELLED   |

    @AC-VER-04g @integration @P1 @cov-data-integrity
    Scenario Outline: Integrity is checked again before a human confirms
      Given the run is COMPLETED with acceptance "accepted"
      And <change>
      When a human runs "sentinel accept leave-balance" at an interactive terminal and types the hash prefix
      Then it exits with code 5
      And the error is "<error>"
      And the acceptance status is "accepted" with human acceptance "pending"
      Examples:
        | change                                                                    | error            |
        | the approved spec file was edited after completion                        | E_APPROVAL_STALE |
        | the stored output file of the "test" evidence row of "backend" was edited | E_INTEGRITY      |

    @AC-VER-04h @integration @P2 @cov-happy-path
    Scenario: A human can still reject a run whose artifacts changed
      Given the run is COMPLETED with acceptance "accepted"
      And the approved spec file was edited after completion
      When a human runs "sentinel accept leave-balance --reject -m 'spec drifted'" at an interactive terminal and types the hash prefix
      Then it exits with code 0
      And the acceptance status is "rejected"

    @AC-VER-04i @integration @P2 @cov-duplicate
    Scenario Outline: A second human decision
      Given the run is COMPLETED and a human already confirmed acceptance
      When a human runs "sentinel accept leave-balance <flags>" at an interactive terminal and types the hash prefix
      Then it exits with code <code>
      And the acceptance status is "<status>"
      Examples:
        | flags                     | code | status   |
        |                           | 5    | accepted |
        | --reject -m 'regression'  | 0    | rejected |

    @AC-VER-04j @integration @P2 @cov-concurrency
    Scenario: Two terminals decide at the same moment
      Given the run is COMPLETED with acceptance "accepted"
      When one human confirms acceptance and another rejects it at the same moment, each at an interactive terminal
      Then the two decisions are stored one after the other, never interleaved
      And the final acceptance status is "rejected" in either order
      And the confirming call exits with code 0 only if its decision was stored before the rejection, otherwise with code 5

    @AC-SEC-04b @integration @P1 @cov-regression
    Scenario: Generated agent configs still deny the accept command
      When "sentinel sync-adapters" is run
      Then .claude/settings.json permissions.deny contains "Bash(sentinel accept:*)" and "Bash(sentinel --dir * accept *)"
      And every generated agent file states that agents never run "sentinel accept"
