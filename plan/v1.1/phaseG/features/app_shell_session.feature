@REQ-DSH-01 @REQ-DSH-04 @REQ-DSH-06 @REQ-INS-05 @REQ-SEC-01
Feature: Dashboard shell, session and API calls
  The single-page app is served by the Phase F server at "/" from the installed package. It
  reads the CSRF value from GET /api/v1/session, sends it as X-Sentinel-CSRF on every mutating
  call, and talks only to /api/v1 and /api/v1/events on its own origin. It shows what the API
  answered and never a result the API has not confirmed. Screens use hash routes ("#/...").

  Background:
    Given the built dashboard is served by the fake API server on 127.0.0.1 with fixture set "two-projects"
    And the browser holds a valid session cookie

  Rule: Navigation

    @AC-DSH-01a @e2e @P1 @cov-happy-path
    Scenario: The main navigation
      When the dashboard opens at "/"
      Then the navigation shows "Overview", "Projects", "Tasks", "My Approvals", "Runs", "Quality" and "Settings"
      And the navigation shows no "Notifications", "Reports", "Agents", "Providers" or "Users and Permissions" entry
      And "Overview" is the current page and its link has aria-current "page"

    @AC-DSH-01b @e2e @P2 @cov-happy-path
    Scenario Outline: Every screen has its own address
      When the browser opens "<route>" directly
      Then the screen titled "<title>" is shown
      And reloading the page shows the same screen
      Examples:
        | route                                           | title                     |
        | /#/projects                                     | Projects                  |
        | /#/projects/digital-hr                          | digital-hr                |
        | /#/projects/digital-hr/configuration            | Configuration             |
        | /#/tasks                                        | Tasks                     |
        | /#/tasks/new                                    | Create task               |
        | /#/approvals                                    | My Approvals              |
        | /#/projects/digital-hr/runs/leave-balance       | leave-balance             |
        | /#/projects/digital-hr/runs/leave-balance/trace | Trace                     |
        | /#/settings/installation                        | Sentinel installation     |

    @AC-DSH-01c @e2e @P2 @cov-invalid-input
    Scenario Outline: Unknown screens and unknown objects
      When the browser opens "<route>" directly
      Then the screen shows "<message>" with a link to "Overview"
      And no request other than GET is sent
      Examples:
        | route                                      | message            |
        | /#/no-such-screen                          | Page not found     |
        | /#/projects/no-such-project                | Project not found  |
        | /#/projects/digital-hr/runs/no-such-run    | Run not found      |

    @AC-DSH-01d @e2e @P2 @cov-boundary
    Scenario: A slug used in two projects opens the run of the project in the address
      Given projects "digital-hr" and "payroll" both have a run "leave-balance"
      When the browser opens "/#/projects/payroll/runs/leave-balance"
      Then every run request carries "?project=payroll"
      And the run header names project "payroll"

  Rule: Session and CSRF

    @AC-SEC-01y @e2e @P1 @cov-authn
    Scenario: The app reads the CSRF value once and sends it only on mutating calls
      When the dashboard opens and the user creates a task and cancels a run
      Then GET /api/v1/session was called exactly once
      And every POST carried header X-Sentinel-CSRF equal to the served value and Content-Type "application/json"
      And no GET carried the X-Sentinel-CSRF header
      And localStorage, sessionStorage, IndexedDB and document.cookie hold no token, session or CSRF value

    @AC-SEC-01z @e2e @P1 @cov-authn
    Scenario Outline: An ended session stops the app and says how to get a new one
      Given the fake API answers 401 with error code "E_AUTH" to <request>
      When the user is on the run view of "leave-balance"
      Then a blocking screen says "Session ended" and "Run sentinel dashboard in a terminal to open a new session"
      And the app sends no further API request until the page is reloaded
      And no form content is sent again
      Examples:
        | request                                   |
        | GET /api/v1/tasks/leave-balance           |
        | the event stream reconnect                |
        | POST /api/v1/tasks/leave-balance/control  |

    @AC-DSH-04c @e2e @P1 @cov-authz
    Scenario: A refused CSRF value is renewed but the action is not resent
      Given the fake API answers the next POST with 403 and error code "E_CSRF"
      When the user cancels run "leave-balance" with comment "wrong ticket"
      Then the app calls GET /api/v1/session again
      And the message "The action was not sent. Check the run state and try again." is shown
      And exactly one POST to /api/v1/tasks/leave-balance/control was sent
      And the run state shown is the one returned by a fresh GET /api/v1/tasks/leave-balance

  Rule: The UI never claims success before the API confirms it

    @AC-DSH-04a @e2e @P1 @cov-happy-path
    Scenario Outline: Pending, then the stored state
      Given the fake API delays the answer to <request> by 2 seconds
      When the user performs "<action>"
      Then during the delay the action button is disabled, shows "Sending" and no success message is shown
      And no state shown on the page has changed yet
      And after the answer the page shows "<shown>" taken from the answer body
      Examples:
        | action                             | request                                      | shown                           |
        | approve specification version 2    | POST /api/v1/tasks/leave-balance/approvals   | Specification approved          |
        | create task "leave-report"         | POST /api/v1/projects/digital-hr/tasks       | leave-report created: CREATED   |
        | cancel run "leave-balance"         | POST /api/v1/tasks/leave-balance/control     | Run state CANCELLED             |
        | retry task t-doc1                  | POST /api/v1/tasks/leave-balance/control     | Retry queued                    |
        | resume run "leave-balance"         | POST /api/v1/tasks/leave-balance/control     | Run state EXECUTING             |
        | confirm acceptance of "leave-form" | POST /api/v1/tasks/leave-form/acceptance     | Acceptance confirmed            |

    @AC-DSH-04b @e2e @P1 @cov-errors
    Scenario Outline: A failed or unanswered action is shown as not confirmed
      Given the fake API answers POST /api/v1/tasks/leave-balance/control with <failure>
      When the user cancels run "leave-balance" with comment "wrong ticket"
      Then the message "<message>" is shown
      And the page shows the run state from a fresh GET, not the state the user asked for
      Examples:
        | failure                                      | message                                                                 |
        | a dropped connection                         | Not confirmed: the server did not answer. Check the run state.          |
        | no answer within 30 seconds                  | Not confirmed: the server did not answer. Check the run state.          |
        | 500 and error code "E_INTERNAL"              | Not confirmed: server error. See the terminal running sentinel dashboard. |
        | 409 and error code "E_TRANSITION"            | Refused: the run moved on.                                               |

    @AC-DSH-04d @unit @P1 @cov-duplicate
    Scenario: The API client never repeats a mutating call by itself
      Given a mocked fetch that fails every call with a network error
      When the API client sends one POST and one GET
      Then fetch was called exactly once for the POST
      And the GET may be repeated at most twice with a delay of at least 1 second

    @AC-DSH-04e @e2e @P2 @cov-duplicate
    Scenario: Double clicks send one request
      When the user double-clicks "Create task" on a valid form
      Then exactly one POST /api/v1/projects/digital-hr/tasks is sent

  Rule: Errors carry their fix

    @AC-INS-05a @unit @P1 @cov-errors
    Scenario Outline: Error envelopes become actionable messages
      Given an API answer with status <status> and body {"error": {"code": "<code>", "message": "<message>", "details": <details>}}
      When the error view renders it
      Then it shows the text "<shown>" and the code "<code>"
      Examples:
        | status | code             | message                         | details                                      | shown                                                            |
        | 400    | E_VALIDATION     | invalid slug                    | {"field": "slug"}                            | invalid slug (field slug)                                        |
        | 409    | E_APPROVAL_STALE | approval is stale               | {"current_sha256": "9b..."}                  | A newer version is in review. Reload it before deciding.         |
        | 409    | E_TRANSITION     | not allowed in state COMPLETED  | {}                                           | Refused: the run moved on. not allowed in state COMPLETED        |
        | 422    | E_PRECONDITION   | workspace missing               | {"fix": "sentinel dashboard in the workspace"} | workspace missing. Fix: sentinel dashboard in the workspace     |
        | 409    | E_INTEGRITY      | artifact changed on disk        | {"sha256": "aa..."}                          | The file changed after it was stored. Its content is not shown.  |
        | 500    | E_INTERNAL       | internal error                  | {}                                           | Server error. See the terminal running sentinel dashboard.       |
        | 418    | E_SOMETHING_NEW  | new thing                       | {}                                           | new thing                                                        |

    @AC-INS-05b @unit @P2 @cov-errors
    Scenario Outline: Answers that are not an error envelope
      Given an API answer with status <status>, Content-Type "<type>" and body <body>
      When the error view renders it
      Then it shows "Unexpected answer (status <status>)"
      And the body is not rendered as HTML
      Examples:
        | status | type        | body                                  |
        | 502    | text/html   | "<h1>Bad gateway</h1>"                |
        | 500    | application/json | ""                               |
        | 400    | application/json | {"detail": "x"}                  |

  Rule: Own origin only

    @AC-DSH-06e @e2e @P1 @cov-perf-security
    Scenario: Every request of a full session goes to the server's own origin
      Given Playwright records every request the page makes
      When a scripted session visits every screen, approves a specification, creates a task, cancels a run and reads a log
      Then every request URL has the origin of the fake API server
      And every request path starts with "/api/v1/" or is a file listed in the build manifest
      And no request goes to a font, analytics, CDN or source-map host
