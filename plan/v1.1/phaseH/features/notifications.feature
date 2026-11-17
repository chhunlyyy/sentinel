@REQ-NOT-01 @REQ-NOT-02 @REQ-NOT-03 @REQ-VIS-04 @REQ-SEC-06
Feature: Local notifications
  Notifications are computed by one engine function from the append-only events table of each
  registered workspace, using the rule table of event-contracts section 4. They are shown in the
  dashboard, listed by "sentinel notifications" in a terminal, and optionally raised as desktop
  notifications through the browser Notification API. Read state is kept per OS user in
  ~/.config/sentinel/user.db. Nothing is sent over the network. Opening a notification never
  decides anything.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And workspace "digital-hr" is registered as project "digital-hr" with a version 2 run "leave-balance"

  Rule: Which events notify

    @AC-NOT-01a @unit @P1 @cov-happy-path
    Scenario Outline: An event that matches a rule gives one notification
      Given the events table of "digital-hr" holds a "<event>" event with <payload> for run "leave-balance"
      When notifications are computed for project "digital-hr"
      Then there is exactly one notification with level "<level>", a text containing "<text>" and a link to "<link>"
      And its id is "digital-hr:" followed by the id of that event
      Examples:
        | event                | payload                                                    | level   | text                                  | link                              |
        | approval.requested   | gate specification, version 1                              | action  | Specification ready for review        | /tasks/leave-balance/specification |
        | approval.requested   | gate gherkin, version 2                                    | action  | Gherkin ready for review              | /tasks/leave-balance/gherkin      |
        | approval.decided     | decision changes_requested, gate specification             | info    | Changes requested                     | /tasks/leave-balance/specification |
        | run.created          | tier 2, type feature                                       | info    | Run started                           | /tasks/leave-balance              |
        | run.state_changed    | to NEEDS_HUMAN, reason "unknown Red failure"               | action  | unknown Red failure                   | /tasks/leave-balance              |
        | run.state_changed    | to BLOCKED, reason "runner codex not installed"            | warning | runner codex not installed            | /tasks/leave-balance              |
        | task.finished        | state FAILED, role tdd_green, error_code E_EXIT            | warning | tdd_green failed: E_EXIT              | /tasks/leave-balance/workflow     |
        | task.finished        | state FAILED, error_code E_PROVIDER, provider codex        | warning | Provider codex unavailable            | /tasks/leave-balance/workflow     |
        | evidence.recorded    | kind lint, passed false (verification)                     | warning | Verification failed: lint             | /tasks/leave-balance/verification |
        | run.status_changed   | execution_status completed, acceptance_status pending      | action  | Run completed, waiting for acceptance | /tasks/leave-balance/verification |
        | run.status_changed   | execution_status completed, acceptance_status accepted     | info    | Run accepted                          | /tasks/leave-balance              |
        | run.status_changed   | execution_status completed, acceptance_status rejected     | warning | Run rejected                          | /tasks/leave-balance              |
        | run.status_changed   | execution_status failed                                    | warning | Run failed                            | /tasks/leave-balance              |

    @AC-NOT-01b @unit @P1 @cov-boundary
    Scenario Outline: Events without a rule give no notification
      Given the events table holds only a "<event>" event for run "leave-balance"
      When notifications are computed for project "digital-hr"
      Then the list is empty
      Examples:
        | event                                         |
        | task.progress                                 |
        | task.started                                  |
        | run.state_changed to EXECUTING                |
        | approval.decided with decision approved       |
        | task.finished with state COMPLETED            |
        | evidence.recorded with passed true            |

    @AC-NOT-01c @integration @P1 @cov-happy-path
    Scenario: Events written by the CLI notify like events written by the server
      Given a running server and a dashboard client with an open event stream
      When an orchestrator process runs "sentinel task complete" and the engine moves run "leave-balance" to SPECIFICATION_REVIEW
      Then within 2 seconds the client receives the "approval.requested" event and re-fetches GET /api/v1/notifications
      And the answer lists the notification "Specification ready for review" as unread

    @AC-NOT-01d @unit @P2 @cov-empty-null
    Scenario: A fresh installation has no notifications
      Given no workspace has events
      When GET /api/v1/notifications and "sentinel notifications --json" are called
      Then both answer an empty list and an unread count of 0
      And ~/.config/sentinel/user.db is not created by a read

    @AC-NOT-01e @integration @P2 @cov-boundary
    Scenario: Notifications from several projects, newest first, with paging
      Given project "digital-hr" has 120 notifications and project "payroll" has 30
      When GET /api/v1/notifications?limit=50 is called
      Then 50 notifications are returned, newest first by event time, each naming its project
      And a cursor returns the next 50 and the last page holds 50 with no further cursor
      And GET /api/v1/notifications?project=payroll returns only the 30 of "payroll"

    @AC-NOT-01f @integration @P2 @cov-external-failure
    Scenario: An unavailable project does not hide the others
      Given the registry of project "payroll" cannot be opened
      When GET /api/v1/notifications is called
      Then the notifications of "digital-hr" are returned
      And the answer lists "payroll" under "unavailable" with the reason, and no notification is invented for it

    @AC-NOT-01g @integration @P2 @cov-regression
    Scenario: 0.1 runs give no notifications
      Given a 0.1 run "old-fix" with events from the legacy indexer
      When notifications are computed
      Then no notification links to "old-fix"

  Rule: Read state

    @AC-NOT-01h @integration @P1 @cov-happy-path
    Scenario: Marking a notification read in the dashboard
      Given a running server and an authenticated client with CSRF value C
      And notification "digital-hr:42" is unread
      When POST /api/v1/notifications/digital-hr:42/read is sent with header X-Sentinel-CSRF C
      Then the answer is 200 with read_at set
      And user.db holds a row for project "digital-hr" and event 42 with the time
      And the unread count drops by one in GET /api/v1/notifications and in "sentinel notifications"

    @AC-NOT-01i @integration @P1 @cov-happy-path
    Scenario: Listing and marking read in a terminal
      Given 3 unread notifications
      When "sentinel notifications" is run
      Then it prints the 3 notifications with project, time, level, text and the CLI command that acts on each
      When "sentinel notifications read --all" is run
      Then "sentinel notifications --unread" prints nothing and exits 0

    @AC-NOT-01j @security @P1 @cov-authz
    Scenario: Marking read needs the session and the CSRF value
      When POST /api/v1/notifications/digital-hr:42/read is sent without the CSRF header
      Then the answer is 403 "E_CSRF" and user.db is unchanged

    @AC-NOT-01k @integration @P2 @cov-invalid-input
    Scenario Outline: Unknown or malformed notification ids
      When POST /api/v1/notifications/<id>/read is sent with a valid session and CSRF value
      Then the answer is <status> "<code>"
      Examples:
        | id                    | status | code         |
        | digital-hr:999999     | 404    | E_NOT_FOUND  |
        | nope:1                | 404    | E_NOT_FOUND  |
        | digital-hr:abc        | 400    | E_VALIDATION |
        | ..%2F..%2Fuser.db:1   | 400    | E_VALIDATION |

    @AC-NOT-01l @integration @P2 @cov-duplicate
    Scenario: Marking read twice keeps the first time
      Given notification "digital-hr:42" was marked read at 09:00
      When it is marked read again at 09:05 from the terminal
      Then the command succeeds and read_at stays 09:00

    @AC-NOT-01m @integration @P2 @cov-concurrency
    Scenario: Dashboard and terminal mark read at the same time
      When 20 dashboard requests and 20 terminal commands mark the same 10 notifications read in parallel
      Then every call succeeds or retries within 5 seconds and user.db holds exactly 10 rows

    @AC-NOT-01n @integration @P2 @cov-db-failure
    Scenario: user.db cannot be written
      Given ~/.config/sentinel/user.db is read-only
      When a notification is marked read
      Then the dashboard answer is 500 "E_INTERNAL" with a fix naming the file and its mode
      And the notification list still loads, showing every notification as unread

    @AC-NOT-01o @unit @P2 @cov-data-integrity
    Scenario: user.db is created private and migrated like the registry
      When user.db is first written
      Then it is mode 0600 in the 0700 user folder, uses WAL and records its schema_version
      And it holds no event text, only project id, event id and read time

    @AC-NOT-01p @integration @P3 @cov-data-integrity
    Scenario: A restored workspace registry does not mark new events read
      Given notifications up to event 50 of "digital-hr" were read
      And the registry is restored from a backup that ends at event 40 and new events 41 to 45 are written after it
      When notifications are computed
      Then events 41 to 45 are shown unread, because read state also stores the event time and workspace registry id

  Rule: Dashboard and desktop

    @AC-NOT-01q @e2e @P1 @cov-happy-path
    Scenario: The bell shows the unread count and the list
      Given the built dashboard is served by the fake API server with 4 unread notifications
      When the user opens Overview
      Then the header shows a "Notifications" button with the text "4 unread" for screen readers
      And opening it lists the 4 notifications with level, project, time and text as plain text

    @AC-NOT-03a @e2e @P1 @cov-authz
    Scenario: Opening an approval notification does not approve
      Given notification "Specification ready for review" for run "leave-balance"
      When the user opens it
      Then the specification review page of "leave-balance" opens
      And the only request sent besides reads is POST /notifications/{id}/read
      And no request is sent to /tasks/leave-balance/approvals or /acceptance

    @AC-NOT-03b @integration @P1 @cov-authz
    Scenario: Reading notifications leaves approvals and audit unchanged
      Given run "leave-balance" is SPECIFICATION_REVIEW
      When every notification is listed and marked read through the API and the CLI
      Then the specification approval is still IN_REVIEW
      And the audit table has no new row

    @AC-NOT-03c @unit @P2 @cov-authz
    Scenario: A notification carries no decision control
      When the notification payload served by the API is checked
      Then it holds only id, project, run, level, text, link, at and read_at
      And the link is a dashboard route, never an API POST route

    @AC-NOT-02a @e2e @P2 @cov-happy-path
    Scenario: Desktop notifications after the user enables them
      Given notifications.desktop is true in the project config
      And the user pressed "Enable desktop notifications" and the browser granted permission
      When a new "approval.requested" event arrives on the stream
      Then one browser Notification is shown with the title "Sentinel" and the notification text
      And clicking it focuses the dashboard tab and opens the review page without deciding

    @AC-NOT-02b @e2e @P2 @cov-authz
    Scenario Outline: No desktop notification without consent
      Given <condition>
      When a new "approval.requested" event arrives on the stream
      Then no browser Notification is shown and the in-page list still updates
      Examples:
        | condition                                                        |
        | the browser permission is "denied"                               |
        | the user never pressed "Enable desktop notifications"            |
        | notifications.desktop is false in the project config             |

    @AC-NOT-02c @e2e @P3 @cov-boundary
    Scenario: The page never asks for permission on load
      When the user opens every screen with permission "default"
      Then Notification.requestPermission is called only after a click on "Enable desktop notifications"

    @AC-NOT-02d @e2e @P3 @cov-duplicate
    Scenario: Two tabs raise one desktop notification
      Given two dashboard tabs are open with desktop notifications enabled
      When one new "run.state_changed" event to NEEDS_HUMAN arrives
      Then exactly one browser Notification is shown, using the notification id as its tag

  Rule: Local only and scrubbed

    @AC-VIS-04a @security @P1 @cov-perf-security
    Scenario: Notifications make no network connection
      Given a socket audit hook records every connect of the server and CLI processes
      When notifications are computed, listed, marked read and raised on the desktop in a full session
      Then every connect targets 127.0.0.1 or a Unix socket and no DNS lookup is made
      And the built dashboard registers no service worker and uses no Push API

    @AC-SEC-06i @security @P1 @cov-perf-security
    Scenario Outline: Notification text is scrubbed
      Given a "<event>" event whose payload holds "<secret>"
      When the notification is served by the API, printed by the CLI and raised on the desktop
      Then none of them holds "<secret>"
      Examples:
        | event              | secret                                       |
        | run.state_changed  | password=hunter2hunter2                      |
        | task.finished      | Bearer eyJhbGciOiJIUzI1NiJ9.e30.abc123def456 |
        | run.status_changed | the workspace path /home/dev/work/digital-hr |
