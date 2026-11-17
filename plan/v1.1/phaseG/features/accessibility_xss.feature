@REQ-DSH-01 @REQ-INS-06 @REQ-SEC-01
Feature: Accessibility and safe rendering of untrusted content
  Every screen can be used with a keyboard alone, every control has a label, text and status
  colours meet WCAG 2.1 AA contrast in the light and the dark theme, and no state is shown by
  colour alone. Content from runs (specification, Gherkin, logs, diffs, evidence output, request
  text, comments, names, error messages and event payloads) is written by agents or users and is
  always rendered as text, never as HTML, so it cannot run script in the dashboard origin.

  Background:
    Given the built dashboard is served by the fake API server on 127.0.0.1 with fixture set "two-projects"
    And the browser holds a valid session cookie

  Rule: Automated accessibility checks

    @AC-DSH-01e @e2e @P1 @cov-perf-security
    Scenario Outline: No serious or critical axe violation on any screen
      When the user opens "<screen>" in the <theme> theme
      Then axe-core with the WCAG 2.1 A and AA rules reports no violation of impact "serious" or "critical"
      Examples:
        | screen                              | theme |
        | Overview                            | light |
        | Overview                            | dark  |
        | Projects                            | light |
        | Configuration of digital-hr         | light |
        | Health checks                       | light |
        | Create task                         | light |
        | Create task                         | dark  |
        | My Approvals                        | light |
        | Specification review                | light |
        | Specification review                | dark  |
        | Gherkin review                      | light |
        | Run workflow graph                  | light |
        | Run workflow graph                  | dark  |
        | Task log                            | dark  |
        | Verification                        | light |
        | Changes with a split diff           | light |
        | Changes with a split diff           | dark  |
        | Trace                               | light |
        | Session ended                       | light |

    @AC-DSH-01f @unit @P2 @cov-perf-security
    Scenario Outline: Colour tokens meet contrast
      Given the colour tokens of the <theme> theme
      When the contrast of each text token on each background token it is used on is computed
      Then normal text reaches at least 4.5 to 1 and large text and focus outlines at least 3 to 1
      Examples:
        | theme |
        | light |
        | dark  |

  Rule: Keyboard use

    @AC-DSH-01g @e2e @P1 @cov-happy-path
    Scenario: Approving a specification with the keyboard only
      Given run "leave-balance" is SPECIFICATION_REVIEW with version 2 in review, sha256 starting with "3f9a0c12"
      When the user, with the keyboard only, goes from "Overview" to "My Approvals", opens the review, chooses "Approve", types "3f9a0c12" and presses Enter on "Approve version 2"
      Then the approval request is sent once
      And every focused element showed a visible focus outline
      And after the answer focus moves to the result message, which is announced through a live region

    @AC-DSH-01h @e2e @P1 @cov-happy-path
    Scenario: Cancelling a run and creating a task with the keyboard only
      When the user, with the keyboard only, creates a task and then cancels run "leave-balance" from its page
      Then both requests are sent once
      And the cancel dialog traps focus, closes on Escape without sending, and returns focus to "Cancel run"

    @AC-DSH-01i @e2e @P2 @cov-boundary
    Scenario: The page skips to its content and has no keyboard trap
      When the user presses Tab once on any screen
      Then a "Skip to content" link is focused and moves focus to the main region
      And tabbing through the whole page returns to the address bar without getting stuck

  Rule: Labels and announcements

    @AC-DSH-01j @e2e @P1 @cov-missing-fields
    Scenario: Every form control has a label
      When the create task form, the decision panels, the control dialogs and the filters are opened
      Then every input, select, textarea and button has an accessible name
      And every field error is tied to its field with aria-describedby and the field has aria-invalid "true"

    @AC-DSH-01k @e2e @P2 @cov-happy-path
    Scenario: Live changes are announced politely
      When a task of the open run changes state through the event stream
      Then the change is announced through a polite live region with the task role and new state
      And the connection status line has role "status"

  Rule: Untrusted content is rendered as text

    @AC-INS-06c @e2e @P1 @cov-perf-security
    Scenario Outline: Markup in run content is shown literally and never runs
      Given the fake API returns <place> holding the text <payload>
      When the user opens the view that shows it
      Then the text is shown literally
      And the page has no element created from the payload
      And no dialog opened, no script ran and no request went to "evil.example"
      Examples:
        | place                                   | payload                                                   |
        | the specification text of version 2     | "<script>alert(1)</script>"                               |
        | a Gherkin scenario name                 | "<img src=x onerror=alert(1)>"                            |
        | a line of the log of t-green1           | "<svg onload=alert(1)>"                                   |
        | a line of the diff of Leave.java        | "<iframe src=//evil.example>"                             |
        | the output of evidence a-out1           | "</pre><script>fetch('//evil.example')</script>"          |
        | the request text of run leave-balance   | "<a href=javascript:alert(1)>click</a>"                   |
        | an approval comment                     | "<b onmouseover=alert(1)>x</b>"                           |
        | a project name                          | "<style>body{display:none}</style>"                       |
        | an error message of an API answer       | "<img src=x onerror=alert(1)>"                            |
        | a finding text in the verification view | "{{constructor.constructor('alert(1)')()}}"               |
        | an event payload reason                 | "<script>alert(1)</script>"                               |

    @AC-INS-06d @e2e @P1 @cov-perf-security
    Scenario Outline: Links from run content are never script or remote links
      Given the fake API returns a specification whose text holds the link "<link>"
      When the user opens the specification review
      Then <outcome>
      Examples:
        | link                                    | outcome                                                    |
        | javascript:alert(1)                     | the text is shown and no clickable link is created          |
        | data:text/html;base64,PHNjcmlwdD4=      | the text is shown and no clickable link is created          |
        | https://evil.example/x                  | the text is shown and no clickable link is created          |

    @AC-INS-06e @unit @P1 @cov-perf-security
    Scenario: The source has no raw HTML sink
      When the lint and the source check run over dashboard/src
      Then no file uses dangerouslySetInnerHTML, innerHTML, outerHTML, insertAdjacentHTML, document.write, eval or new Function
      And the ESLint rules "react/no-danger" and "no-implied-eval" are set to error

    @AC-INS-06f @e2e @P1 @cov-perf-security
    Scenario: The built page runs under the server's Content-Security-Policy
      Given the fake API sends the Phase F headers including "Content-Security-Policy: default-src 'self'; frame-ancestors 'none'"
      When a scripted session visits every screen
      Then the browser reports no Content-Security-Policy violation
      And the built index.html has no inline script, no inline style element and no style attribute

    @AC-INS-06g @e2e @P2 @cov-perf-security
    Scenario: Values from run content never reach the API path unencoded
      Given a log line holds "../../../../home/dev/.config/sentinel/server.json"
      When the user follows every link the log view offers
      Then every request path built by the app uses only ids and slugs from API answers, percent-encoded
      And no request path holds ".."
