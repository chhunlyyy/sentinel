@REQ-TST-01 @REQ-DSH-06 @REQ-SEC-03 @REQ-API-03
Feature: The CLI is unchanged and the server stays offline
  The server is optional. Without it every CLI command behaves as before Phase F, and with it
  the TTY channel keeps working. The server is stdlib only, makes no outbound connection and
  serves only local assets.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And a workspace "digital-hr" with a valid sentinel.config.yaml

  Rule: Nothing changes when no server runs

    @AC-TST-01e @regression @P1 @cov-regression
    Scenario: All earlier checks stay green
      Given ~/.config/sentinel does not exist
      When "sentinel selftest" and the test suites of Phases A to E are run
      Then the 95 selftest checks pass and every Phase A to E test passes
      And ~/.config/sentinel still does not exist

    @AC-TST-01f @regression @P1 @cov-regression
    Scenario Outline: CLI commands do not need or create server files
      Given no Sentinel server is running and ~/.config/sentinel does not exist
      When "<command>" is run in workspace "digital-hr"
      Then it gives the same exit code and output as before Phase F
      And no server.json, server.lock or projects.json is created
      Examples:
        | command                                                    |
        | sentinel run new leave-balance --type feature              |
        | sentinel next leave-balance --json                         |
        | sentinel review leave-balance spec                         |
        | sentinel doctor                                            |
        | sentinel stats                                             |

    @AC-TST-01g @unit @P2 @cov-regression
    Scenario: The CLI does not load the server code unless it is asked for
      When "sentinel next leave-balance --json" is run with an import tracer
      Then no module of the server package was imported

    @AC-TST-01h @regression @P2 @cov-regression
    Scenario: The 0.1 flow is untouched by the server
      Given a 0.1 run "old-fix" and a running server
      When "sentinel run update old-fix" and "sentinel run finish old-fix --outcome done" are run
      Then they behave as before Phase F
      And GET /api/v1/tasks/old-fix shows the run read-only with workflow_version "0.1"

  Rule: The TTY channel still works while the server runs

    @AC-SEC-03v @integration @P1 @cov-regression
    Scenario: Terminal approval with a running server
      Given a running server and a client with an open event stream for "digital-hr"
      And run "leave-balance" is SPECIFICATION_REVIEW
      When a human at a pseudo-terminal approves the specification with the typed hash prefix
      Then the approval has channel "tty"
      And the client receives the "approval.decided" message with channel "tty"

    @AC-SEC-03w @integration @P1 @cov-authz
    Scenario: A running server gives no new way to approve without a terminal
      Given a running server
      When "sentinel approve leave-balance spec" is run with stdin from a pipe
      Then it is refused with exit code 5 and "E_NOT_TTY" as before Phase F

  Rule: Offline and stdlib only

    @AC-DSH-06a @security @P1 @cov-perf-security
    Scenario: No outbound network connection
      Given a socket audit hook records every connect call of the server process
      When a test session starts the server, authenticates, reads every Phase F route, approves, creates a run, dispatches a fake CLI task, streams events and stops the server
      Then every recorded connect targets 127.0.0.1 or a Unix socket
      And no DNS lookup is made by the server process

    @AC-DSH-06b @security @P2 @cov-perf-security
    Scenario: The served page loads nothing from the network
      When GET / is called with a valid session
      Then the page and every asset it references are served by the server from the installed package
      And no reference starts with "http:", "https:" or "//" except links to 127.0.0.1 port P

    @AC-DSH-06c @unit @P2 @cov-regression
    Scenario: The server uses the standard library only
      When the imports of the server package are listed
      Then every imported module is from the Python standard library or from the sentinel package
      And the declared runtime dependencies of the package are unchanged by Phase F

    @AC-DSH-06d @integration @P3 @cov-empty-null
    Scenario: The dashboard UI is not built yet
      Given the package has no built dashboard assets
      When GET / is called with a valid session
      Then the status is 200 with a page that says the dashboard UI is not installed and lists the API base path
      And the page has the Content-Security-Policy of every response
