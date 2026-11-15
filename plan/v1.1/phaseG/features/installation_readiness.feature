@REQ-INS-02 @REQ-INS-03 @REQ-INS-04 @REQ-DSH-02 @REQ-DSH-03
Feature: Installation, health checks, readiness and the first-run guide
  The dashboard shows the installation and the running server, the health checks of
  "sentinel doctor" and the readiness of each project, all as the API reports them. A state is
  never shown as passed or ready unless an executed check says so. Steps the dashboard cannot
  perform in 1.1.0 (creating a project, adding repos, editing configuration) are shown with the
  command or file to use instead.

  Background:
    Given the built dashboard is served by the fake API server on 127.0.0.1 with fixture set "two-projects"
    And the browser holds a valid session cookie

  Rule: Installation and runtime

    @AC-INS-02a @e2e @P1 @cov-happy-path
    Scenario: The installation screen
      When the user opens "Settings", "Sentinel installation"
      Then it shows the Sentinel version, install path, Python version and install method from GET /api/v1/installation
      And it shows the server pid, port, start time and loaded projects from GET /api/v1/runtime

    @AC-INS-04a @e2e @P2 @cov-authz
    Scenario: The browser never starts or stops processes
      When the user opens "Settings", "Runtime connection"
      Then it shows "Connected to the running server" with its pid and port
      And the screen has no control to start, stop or restart a server or to choose an installation path
      And it states that the server is started with "sentinel dashboard" in a terminal

  Rule: Health checks

    @AC-INS-03a @e2e @P1 @cov-happy-path
    Scenario Outline: Each check shows its status and its fix
      Given GET /api/v1/installation/health answers check "<check>" with status "<status>" and fix "<fix>"
      When the user opens "Settings", "Health checks"
      Then check "<check>" shows the text "<label>"
      And the fix "<fix>" is shown next to it when the status is not "passed"
      And the status is shown as text and an icon with a text alternative, not by colour alone
      Examples:
        | check              | status         | label          | fix                                    |
        | git                | passed         | Passed         | none                                   |
        | jsonschema         | failed         | Failed         | uv tool install --reinstall sentinel   |
        | provider           | warning        | Warning        | install the codex CLI or set runners   |
        | provider           | not_configured | Not configured | add a runner in sentinel.config.yaml   |
        | registry_writable  | failed         | Failed         | check the permissions of .sentinel/    |

    @AC-INS-03b @e2e @P1 @cov-errors
    Scenario: A failed required check means not ready, whatever else passed
      Given GET /api/v1/installation/health answers every check "passed" except required check "registry_writable" "failed"
      When the user opens "Overview"
      Then the installation summary says "Not ready: 1 required check failed"
      And the word "Ready" is not shown as the installation state

    @AC-INS-03c @e2e @P1 @cov-external-failure
    Scenario Outline: Health checks that cannot be read are not shown as passed
      Given GET /api/v1/installation/health answers <answer>
      When the user opens "Settings", "Health checks"
      Then the screen shows "Connection unavailable" and a "Check again" button
      And no check is shown as "Passed"
      Examples:
        | answer                                    |
        | 500 with error code "E_INTERNAL"          |
        | nothing within 30 seconds                 |
        | 404 with error code "E_NOT_FOUND"         |

    @AC-INS-03d @e2e @P3 @cov-data-integrity
    Scenario: Checking again replaces old results
      Given the health checks were loaded at 10:00 with "git" failed
      When the user fixes git and presses "Check again"
      Then while the request runs the old results are marked "Checking" and none is shown as current
      And afterwards "git" shows "Passed" with the time of the new answer

  Rule: Project readiness

    @AC-DSH-03a @e2e @P1 @cov-happy-path
    Scenario Outline: The five readiness states
      Given GET /api/v1/projects/digital-hr/readiness answers state "<state>" with items <items>
      When the user opens project "digital-hr"
      Then the readiness panel shows "<label>"
      And the "Create task" button is <button>
      And <detail>
      Examples:
        | state                   | items                                                      | label                   | button   | detail                                                       |
        | ready                   | all passed                                                 | Ready                   | enabled  | no item is listed as a problem                                |
        | ready_with_warnings     | "knowledge" warning                                        | Ready with warnings     | enabled  | the warning for "knowledge" is listed with its fix            |
        | needs_configuration     | "test_command" not_configured for repo "backend"           | Needs configuration     | disabled | "test_command" of "backend" is listed with its fix            |
        | invalid_configuration   | schema error at "repos[1].role"                            | Invalid configuration   | disabled | the schema error path "repos[1].role" and its message are listed |
        | connection_unavailable  | repo "frontend" missing                                    | Connection unavailable  | disabled | repo "frontend" is listed as "Not reachable"                  |

    @AC-DSH-03b @unit @P1 @cov-data-integrity
    Scenario Outline: An item that was not checked is never shown as passed
      Given a readiness item "<item>" with status "<status>" and a configured value
      When the readiness panel renders it
      Then the item shows "<label>"
      Examples:
        | item           | status      | label          |
        | build_command  | not_checked | Not checked    |
        | test_command   | passed      | Validated      |
        | lint_command   | failed      | Failed         |
        | provider       | unknown     | Not checked    |

    @AC-DSH-03c @e2e @P2 @cov-boundary
    Scenario: Readiness depends on the selected workflow
      Given the project has no test command and readiness for workflow "docs" is "ready" while for "feature" it is "needs_configuration"
      When the user selects task type "docs" on the create task form
      Then the form calls GET /api/v1/projects/digital-hr/readiness?workflow=docs and "Create task" is enabled
      And when the user selects task type "feature", "Create task" is disabled and the missing test command is listed

  Rule: First-run guide

    @AC-DSH-02a @e2e @P1 @cov-empty-null
    Scenario: No project registered yet
      Given the fixture set is "fresh-install" with no registered project
      When the dashboard opens at "/"
      Then the overview shows the steps "Installation", "Health", "Create project", "Add repositories", "Configure", "Readiness" and "First task"
      And "Installation" and "Health" show the state from the API
      And "Create project", "Add repositories" and "Configure" show the commands "sentinel init" and "sentinel dashboard" to run in the workspace and the file "sentinel.config.yaml" to edit
      And the steps after "Health" are not marked done

    @AC-DSH-02b @e2e @P2 @cov-happy-path
    Scenario: The guide follows what the API reports
      Given the fixture set is "fresh-install" and the health checks all pass
      When the fake API starts listing project "digital-hr" with two repos and readiness "needs_configuration"
      And the event stream sends a "resync" message
      Then "Create project" and "Add repositories" are marked done
      And "Configure" is the current step with the missing items listed
      And "First task" is not offered until readiness is "ready" or "ready_with_warnings"
