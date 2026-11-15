@REQ-TST-05 @REQ-SEC-02 @REQ-SEC-04 @REQ-SEC-06 @REQ-SEC-09
Feature: Executable security suite for the threat model
  tests/security/ holds one runnable suite ("python3 -m unittest discover -s tests/security", also
  run by the release gate) for the threats of docs/architecture/security-architecture.md section 8
  and residual risks R1 and R3. A manifest maps each threat to its checks; earlier phase tests are
  referenced by AC id and re-run, and the end-to-end checks below are new. Every check uses fake
  runners, temporary HOME folders and loopback only.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And workspace "digital-hr" with a .env holding canary secrets "CANARY_DB_PASSWORD=cn-7f3a9e1b2c" and "API_TOKEN=cn-tok-55aa66bb77cc"
    And the process environment holds "AWS_SECRET_ACCESS_KEY=cn-aws-0123456789abcdef" and policies.redact_env lists it

  Rule: Threat manifest

    @AC-TST-05a @unit @P1 @cov-regression
    Scenario Outline: Every threat has at least one passing check
      When tests/security/manifest.json is read
      Then threat "<threat>" lists at least one check, each check exists as a test id, and each passes in the suite run
      Examples:
        | threat                                              |
        | wrong Host (DNS rebinding)                          |
        | wrong Origin                                        |
        | missing session cookie                              |
        | missing or wrong CSRF value                         |
        | token left in the URL after /auth                   |
        | path traversal in artifact, log and static routes   |
        | path traversal in notification and backup arguments |
        | oversized body                                      |
        | non-TTY approval and acceptance                     |
        | stale-hash approval                                 |
        | agent environment holds the token or secrets        |
        | secrets in logs, evidence, reports and bundles      |
        | secrets in prompts and task files                   |
        | untrusted content rendered as HTML (XSS)            |
        | approval forgery by a same-user agent (R1)          |
        | commands run by a provider during a task (R3)       |

    @AC-TST-05b @unit @P2 @cov-regression
    Scenario: A threat without a check fails the suite
      Given a manifest entry whose check list is empty or names a test that does not exist
      When the suite runs
      Then it fails naming the threat

  Rule: Request attacks against a real server

    @AC-TST-05c @security @P1 @cov-authz
    Scenario: DNS rebinding from a page on another name
      Given "sentinel dashboard --no-open" runs on 127.0.0.1 port P
      And a test resolver maps "rebind.example" to 127.0.0.1
      When a headless browser loads a page from http://rebind.example:P/ and its script calls fetch("/api/v1/projects")
      Then every answer is 403 "E_HOST" and the script reads no project data

    @AC-TST-05d @security @P1 @cov-authz
    Scenario Outline: Cross-site request forgery from another local origin
      Given a logged-in dashboard tab and a second page served by a test server on 127.0.0.1 port Q
      When the second page submits <request> to http://127.0.0.1:P<path>
      Then the server refuses it with <answer> and no approval, run, control or read state changes
      Examples:
        | request                                       | path                                      | answer                           |
        | an HTML form POST (text/plain)                | /api/v1/tasks/leave-balance/approvals     | 403 E_ORIGIN                     |
        | fetch POST with mode no-cors                  | /api/v1/tasks/leave-balance/control       | 403 E_ORIGIN                     |
        | fetch POST with credentials and JSON          | /api/v1/notifications/digital-hr:1/read   | 403 E_ORIGIN (no CORS preflight answer) |
        | an image GET                                  | /api/v1/projects                          | no cookie sent (SameSite=Strict) and 401 |

    @AC-TST-05e @security @P1 @cov-perf-security
    Scenario Outline: Path traversal in every path-like argument
      When <call> is made with "<value>"
      Then it is refused with <answer> and no file outside the allowed folder is read or written
      Examples:
        | call                                            | value                               | answer                  |
        | GET /api/v1/tasks/leave-balance/artifacts/{aid} | ../../../../.config/sentinel/server.json | 404 E_NOT_FOUND    |
        | GET /api/v1/tasks/leave-balance/logs/{task_id}  | ..%2F..%2Fsentinel.db               | 404 E_NOT_FOUND         |
        | GET /assets/{file}                              | %2e%2e/%2e%2e/VERSION               | 404                     |
        | POST /api/v1/notifications/{id}/read            | ../user.db:1                        | 400 E_VALIDATION        |
        | sentinel backup restore                         | ../../etc/passwd                    | exit 1, not a backup    |
        | sentinel task complete                          | t-1/../../../x                      | exit 2, invalid task id |

    @AC-TST-05f @security @P1 @cov-authn
    Scenario: The token never stays in the URL or browser history
      When a browser opens the printed /auth?t=T URL
      Then after the redirect the address is "/" and window.history holds no entry with "t="
      And the Referer of every later request holds no token

  Rule: Secrets never leave the scrubber

    @AC-SEC-06j @security @P1 @cov-perf-security
    Scenario: Canary sweep after a full fake run
      Given fake runners that print every canary value to stdout and stderr, write them into result.json details and into a changed file's test output
      When a version 2 run goes from creation through both approvals, one TDD cycle, verification, report, acceptance, export, audit export, notifications and analytics, with the server running and a client streaming events
      Then no canary value appears in any file under .sentinel/runs, .sentinel/cache and .sentinel/generated except the repo files the agent wrote
      And none appears in the export bundle, the audit export, the report files, the server log, any API answer, any SSE message, any notification or the stats output

    @AC-SEC-06k @security @P1 @cov-perf-security
    Scenario: Prompts and task files hold no secret from the environment
      When every prompt, task.json and task.sealed.json written during the canary run is read
      Then none holds a canary value, the dashboard token or a value of a policies.redact_env variable

    @AC-SEC-06l @security @P2 @cov-perf-security
    Scenario: A backup is as sensitive as the registry
      When "sentinel backup" is run after the canary run
      Then the backup holds only values the registry holds, is mode 0600, and lies under the git-ignored .sentinel folder

  Rule: Agent environment

    @AC-SEC-02l @security @P1 @cov-perf-security
    Scenario Outline: The agent environment is stripped
      Given a running server with token T and a fake <adapter> runner that writes its environment and open file descriptors to a file
      When a task is dispatched through <path>
      Then the recorded environment has no SENTINEL_DASHBOARD_TOKEN, no T, no AWS_SECRET_ACCESS_KEY and no variable from policies.redact_env
      And no open descriptor points at server.json, server.lock or user.db
      Examples:
        | adapter | path                                       |
        | cli     | sentinel task run started by an orchestrator |
        | cli     | the server's Q2 dispatch                    |
        | native  | the native task files read by a subagent    |

    @AC-SEC-04d @security @P1 @cov-authz
    Scenario Outline: Generated agent configs deny the human commands
      When "sentinel sync-adapters" runs for <tool>
      Then the generated config or instructions forbid "sentinel approve", "sentinel accept", "sentinel backup restore", "sentinel audit export" and reading ~/.config/sentinel/server.json
      Examples:
        | tool        |
        | claude      |
        | codex       |
        | gemini      |
        | agy         |

  Rule: Residual risks are tested as residual

    @AC-TST-05g @security @P1 @cov-authz
    Scenario Outline: Simple forgery attempts by an agent fail
      Given a fake agent process with SENTINEL_TASK_ID set and stdin from a pipe
      When it tries <attempt>
      Then it is refused with <answer> and the approval is still IN_REVIEW
      Examples:
        | attempt                                                   | answer      |
        | sentinel approve leave-balance spec                       | E_NOT_TTY   |
        | sentinel accept leave-balance                             | E_NOT_TTY   |
        | sentinel dashboard --no-open to get a URL                 | E_ACTOR     |
        | POST /api/v1/tasks/leave-balance/approvals without cookie | 401 E_AUTH  |
        | reading the token from its environment                    | not present |

    @AC-TST-05h @security @P1 @cov-authz
    Scenario: A same-user agent driving a pseudo-terminal is recorded, not stopped (R1)
      Given a fake agent process that opens a pseudo-terminal with Python's pty module and types the hash prefix
      When it runs "sentinel approve leave-balance spec" through that terminal
      Then the approval succeeds with channel "tty" and the approver identity of the OS user
      And the test asserts this outcome and that docs/security.md describes it under R1, so a silent change in either direction fails the suite

    @AC-TST-05i @security @P2 @cov-authz
    Scenario: A same-user agent reading server.json can call the API (R1)
      Given a running server
      When a fake agent process reads ~/.config/sentinel/server.json and calls /auth with the token
      Then it gets a session, and its approval is recorded with channel "dashboard"
      And the test asserts that docs/security.md names this case under R1

    @AC-TST-05j @security @P2 @cov-perf-security
    Scenario: A provider command during a task is detected after the fact (R3)
      Given a fake runner that writes a file outside its write scope and runs "git commit"
      When the task finishes
      Then the task is FAILED with E_SCOPE naming both effects and the run is NEEDS_HUMAN
      And nothing undoes the effects, as docs/security.md says under R3

  Rule: Untrusted content

    @AC-SEC-09a @e2e @P1 @cov-perf-security
    Scenario Outline: Payloads from runs are shown as text on the new screens
      Given the fake API server serves "<payload>" in <field>
      When the user opens <screen>
      Then the payload is shown as literal text, no element is created from it, no dialog opens and no request leaves the page
      Examples:
        | payload                                   | field                         | screen                  |
        | <img src=x onerror=alert(1)>              | a notification text           | the notification list   |
        | <script>fetch('//evil.example')</script>  | a run slug in a notification  | the notification list   |
        | javascript:alert(1)                       | a notification link           | the notification list   |
        | <svg onload=alert(1)>                     | a provider name in analytics  | Reports                 |
        | "><iframe src=//evil.example>             | an audit reason               | the audit tab           |

    @AC-SEC-09b @unit @P1 @cov-perf-security
    Scenario: Notification links are dashboard routes only
      Given a notification whose link is "javascript:alert(1)", "//evil.example/x" or "/api/v1/tasks/x/approvals"
      When the notification is computed
      Then the link is replaced with the run page route, or with none when the run is unknown

    @AC-SEC-09c @e2e @P2 @cov-perf-security
    Scenario: Desktop notification text is plain
      When a notification text holds "<b>bold</b>"
      Then the browser Notification body is the literal text "<b>bold</b>" and has no icon or image URL from content
