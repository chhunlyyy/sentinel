@REQ-INS-03 @REQ-INS-06 @REQ-INS-07 @REQ-DSH-03 @REQ-REP-03 @REQ-REP-04 @REQ-CFG-05 @REQ-CFG-06 @REQ-GIT-01 @REQ-SEC-06
Feature: Read routes the dashboard needs, added to the Phase F server
  Phase F answers 404 for the health, readiness, repository, configuration and change routes
  of api-contracts.md section 2. Phase G adds only their GET forms, with the Phase F checks
  (Host, Origin, session cookie, envelopes, scrubbing). No mutating route is added: creating or
  registering projects, adding repos, saving, restoring or importing configuration, the
  directory picker, provider tests and publishing still answer 404.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And workspace "digital-hr" with repos "backend" and "frontend" and a .env file that sets DB_PASSWORD to "hunter2-secret" is registered as project "digital-hr"
    And the server listens on 127.0.0.1 port P and the client holds session cookie S and CSRF value C

  Rule: Health checks are the doctor checks

    @AC-INS-03e @integration @P1 @cov-happy-path
    Scenario: The health answer
      When GET /api/v1/installation/health is called
      Then the status is 200 with items holding name, required, status, message and fix
      And the names are "installation", "version", "git", "python", "pyyaml", "jsonschema", "registry_writable", "provider", "storage" and "repo_access"
      And each status is one of "passed", "warning", "failed" and "not_configured"
      And the answer holds "ready" false when any required item is "failed", else true

    @AC-INS-07a @contract @P1 @cov-regression
    Scenario: The API and "sentinel doctor" run the same checks
      When GET /api/v1/installation/health is called and "sentinel doctor" is run in the same workspace with the same HOME
      Then both list the same check names with the same statuses
      And both came from the same health-check function, as a mock of that function shows

    @AC-INS-03f @integration @P2 @cov-external-failure
    Scenario Outline: A missing dependency fails its check with a fix
      Given <problem>
      When GET /api/v1/installation/health is called
      Then item "<item>" has status "failed" and a non-empty fix
      And "ready" is false
      Examples:
        | problem                                       | item               |
        | git is not on PATH of the server process      | git                |
        | the registry folder is read-only              | registry_writable  |
        | no runner command of the config is installed  | provider           |

  Rule: Readiness of a project

    @AC-DSH-03d @integration @P1 @cov-happy-path
    Scenario: The readiness answer
      When GET /api/v1/projects/digital-hr/readiness is called
      Then the status is 200 with a state among "ready", "ready_with_warnings", "needs_configuration", "invalid_configuration" and "connection_unavailable"
      And the items hold name, repo, required, status, message, fix and checked_at
      And no item status is "passed" unless its check ran during this call

    @AC-DSH-03e @integration @P1 @cov-perf-security
    Scenario: Readiness never runs project commands
      Given repo "backend" has build and test commands that write a marker file when run
      When GET /api/v1/projects/digital-hr/readiness is called
      Then no marker file exists
      And the build and test command items check only that their executable is found on PATH, with status "not_checked" for anything further

    @AC-DSH-03f @integration @P2 @cov-invalid-input
    Scenario Outline: Readiness inputs and broken configurations
      Given <setup>
      When GET /api/v1/projects/digital-hr/readiness<query> is called
      Then <outcome>
      Examples:
        | setup                                        | query               | outcome                                                                                 |
        | the config is valid                          | ?workflow=party     | the status is 400 with error code "E_VALIDATION" listing the allowed workflows           |
        | sentinel.config.yaml fails the schema        |                     | the state is "invalid_configuration" with each schema error path and message             |
        | the folder of repo "frontend" was deleted    |                     | the state is "connection_unavailable" and repo "frontend" is named                       |
        | the config sets no test command              | ?workflow=docs      | the state is "ready" because docs runs need no test command                              |
        | the config sets no test command              | ?workflow=feature   | the state is "needs_configuration" naming the test command                               |

  Rule: Repositories

    @AC-REP-03a @integration @P1 @cov-happy-path
    Scenario: The repository list
      When GET /api/v1/projects/digital-hr/repositories is called
      Then the items hold id, path, remote, default branch, current branch, role, profile, the build, test, lint, typecheck and mutate commands and the guidelines file
      And the items are in the order of repos[] in sentinel.config.yaml

    @AC-REP-03c @integration @P1 @cov-perf-security
    Scenario: Remote URLs are served without credentials
      Given repo "backend" has remote "https://dev:ghp_abc123secret@git.example/acme/backend.git"
      When GET /api/v1/projects/digital-hr/repositories is called
      Then the remote of "backend" is "https://git.example/acme/backend.git"
      And the answer does not contain "ghp_abc123secret"

    @AC-REP-04a @integration @P2 @cov-external-failure
    Scenario Outline: Repository validation
      Given <problem> for repo "frontend"
      When GET /api/v1/projects/digital-hr/repositories is called
      Then repo "frontend" has validation item "<item>" with status "failed" and a fix
      And repo "backend" has every validation item "passed"
      Examples:
        | problem                                        | item         |
        | the folder does not exist                      | exists       |
        | the folder is not a git repo                   | git          |
        | the default branch "main" does not exist       | branch       |
        | the folder is not writable                     | writable     |
        | the profile "fake-junit" does not match        | profile      |

  Rule: Configuration, read only

    @AC-CFG-06a @integration @P1 @cov-happy-path
    Scenario: The effective configuration with its sources
      Given the global config sets limits.task_timeout 900, the project sets 1200 and repo "backend" sets commands.test
      When GET /api/v1/projects/digital-hr/configuration is called
      Then each value is listed with its key path, value and source among "default", "global", "project" and "repo:<id>"
      And limits.task_timeout is 1200 from "project" with the overridden global value 900 listed
      And the answer holds the sha256 of sentinel.config.yaml as read

    @AC-CFG-06c @integration @P1 @cov-perf-security
    Scenario: Configuration values are scrubbed
      Given sentinel.config.yaml holds a command "deploy --password hunter2-secret" and policies.redact_env lists "DB_PASSWORD"
      When GET /api/v1/projects/digital-hr/configuration and GET /api/v1/projects/digital-hr/configuration/history are called
      Then neither answer contains "hunter2-secret"

    @AC-CFG-05a @integration @P1 @cov-happy-path
    Scenario: Configuration history
      Given config_versions holds 3 versions for project "digital-hr" from run snapshots
      When GET /api/v1/projects/digital-hr/configuration/history is called
      Then the items hold id, scope, sha256, author, channel, created_at and comment, newest first, in the Phase F list envelope

    @AC-CFG-05b @integration @P2 @cov-invalid-input
    Scenario Outline: Diff between two versions
      When GET /api/v1/projects/digital-hr/configuration/diff?a=<a>&b=<b> is called
      Then <outcome>
      Examples:
        | a          | b          | outcome                                                       |
        | 1          | 3          | the status is 200 with a unified diff of the scrubbed contents |
        | 2          | 2          | the status is 200 with an empty diff                           |
        | 1          | 99         | the status is 404 with error code "E_NOT_FOUND"                |
        | 1          | x          | the status is 400 with error code "E_VALIDATION"               |
        | 1          | current    | the status is 200 with the diff from version 1 to the file as read now |
        | other-proj | 1          | the status is 400 with error code "E_VALIDATION"               |

    @AC-CFG-05c @integration @P2 @cov-db-failure
    Scenario: The registry cannot be read
      Given .sentinel/sentinel.db of "digital-hr" cannot be opened
      When GET /api/v1/projects/digital-hr/configuration/history is called
      Then the status is 422 with error code "E_PRECONDITION" and a message without a traceback

  Rule: Changes and diffs of a run

    @AC-GIT-01a @integration @P1 @cov-happy-path
    Scenario: The changes of a run
      Given run "leave-balance" changed 2 files in "backend" and 1 in "frontend" since their baseline SHAs
      When GET /api/v1/tasks/leave-balance/changes is called
      Then each repo item holds base sha, branch, head sha and its files
      And each file holds path, status, additions, deletions, binary and the ids of the cycles and tasks whose scope covers it

    @AC-GIT-01b @integration @P1 @cov-invalid-input
    Scenario Outline: Diff of one file
      When GET /api/v1/tasks/leave-balance/changes/diff?repo=<repo>&path=<path>&mode=<mode> is called
      Then <outcome>
      Examples:
        | repo     | path                         | mode    | outcome                                                                    |
        | backend  | src/main/Leave.java          | inline  | the status is 200 with hunks of the scrubbed diff                          |
        | backend  | src/main/Leave.java          | split   | the status is 200 with paired old and new lines                            |
        | backend  | src/main/Leave.java          | wide    | the status is 400 with error code "E_VALIDATION"                           |
        | backend  | src/main/Unchanged.java      | inline  | the status is 404 with error code "E_NOT_FOUND"                            |
        | backend  | ../../../etc/passwd          | inline  | the status is 404 with error code "E_NOT_FOUND"                            |
        | backend  | /home/dev/.config/sentinel/server.json | inline | the status is 404 with error code "E_NOT_FOUND"                |
        | mobile   | src/main/Leave.java          | inline  | the status is 404 with error code "E_NOT_FOUND"                            |

    @AC-SEC-06h @integration @P1 @cov-perf-security
    Scenario: Diffs are scrubbed
      Given run "leave-balance" added the line "DB_PASSWORD=hunter2-secret" to "backend" file "src/main/resources/app.properties"
      When the diff of that file is requested in mode inline and in mode split
      Then neither answer contains "hunter2-secret"

    @AC-GIT-01c @integration @P2 @cov-boundary
    Scenario Outline: Binary and large files
      Given run "leave-balance" changed <file>
      When its diff is requested
      Then <outcome>
      Examples:
        | file                                         | outcome                                                               |
        | the binary file "logo.png"                   | the answer holds binary true and no content                            |
        | a text file whose diff is 3 MB               | the answer holds the first 1 MB of whole lines and truncated true      |
        | a text file with no change in its content    | the file is not listed by the changes route                            |

    @AC-GIT-01d @performance @P3 @cov-perf-security
    Scenario: A diff of a 5000-line file is served fast
      Given run "leave-balance" rewrote a 5000-line file
      When its diff is requested 10 times
      Then every answer arrives within 1 second on the test machine

  Rule: The allow-list stays closed for writes

    @AC-INS-06a @security @P1 @cov-authz
    Scenario Outline: Mutating routes of the contract are still not offered
      When <request> is sent with cookie S, CSRF header C and a valid JSON body
      Then the status is 404 with error code "E_NOT_FOUND"
      And no file under HOME or the workspace changed
      Examples:
        | request                                                         |
        | POST /api/v1/projects                                           |
        | POST /api/v1/projects/register                                  |
        | PATCH /api/v1/projects/digital-hr                               |
        | DELETE /api/v1/projects/digital-hr                              |
        | POST /api/v1/projects/digital-hr/repositories                   |
        | PUT /api/v1/projects/digital-hr/configuration                   |
        | POST /api/v1/projects/digital-hr/configuration/restore/1        |
        | POST /api/v1/projects/digital-hr/configuration/import           |
        | GET /api/v1/fs/dirs?path=/                                      |
        | POST /api/v1/providers/claude/test                              |
        | POST /api/v1/tasks/leave-balance/publish                        |

    @AC-INS-06b @security @P1 @cov-authn
    Scenario Outline: The new routes have the Phase F checks
      When GET <route> is sent <variant>
      Then the status is <status>
      Examples:
        | route                                                   | variant                                 | status |
        | /api/v1/installation/health                             | without a cookie                        | 401    |
        | /api/v1/projects/digital-hr/readiness                   | without a cookie                        | 401    |
        | /api/v1/projects/digital-hr/configuration               | with Host "evil.example:P"              | 403    |
        | /api/v1/tasks/leave-balance/changes/diff?repo=backend&path=a&mode=inline | with Origin "http://evil.example" | 403 |
        | /api/v1/projects/digital-hr/repositories                | with cookie S and no CSRF header        | 200    |
