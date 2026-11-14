@REQ-API-01 @REQ-API-03 @REQ-SEC-06
Feature: Mapping engine errors to HTTP answers
  The server never decides business rules. It calls the engine function and turns a
  SentinelError into the envelope {"error": {"code", "message", "details"}} with a fixed status
  per code. Errors raised by the server itself use HTTP-only codes. Unexpected exceptions become
  a 500 with no traceback.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And workspace "digital-hr" is registered as project "digital-hr" with a version 2 run "leave-balance"
    And the server listens on 127.0.0.1 port P and the client holds session cookie S and CSRF value C

  Rule: Every engine code has one status

    @AC-API-03c @unit @P1 @cov-errors
    Scenario Outline: Engine error codes and their statuses
      Given the engine function behind POST /api/v1/tasks/leave-balance/control raises SentinelError "<code>" with message "m" and details {"k": "v"}
      When POST /api/v1/tasks/leave-balance/control is sent with body {"action": "cancel"}
      Then the status is <status>
      And the body is exactly {"error": {"code": "<code>", "message": "m", "details": {"k": "v"}}}
      Examples:
        | code               | status |
        | E_VALIDATION       | 400    |
        | E_ACTOR            | 403    |
        | E_POLICY           | 403    |
        | E_NOT_TTY          | 403    |
        | E_NOT_FOUND        | 404    |
        | E_TRANSITION       | 409    |
        | E_APPROVAL_STALE   | 409    |
        | E_LOCKED           | 409    |
        | E_INTEGRITY        | 409    |
        | E_PRECONDITION     | 422    |
        | E_APPROVAL_MISSING | 422    |
        | E_SCOPE            | 422    |
        | E_RESULT_SCHEMA    | 422    |
        | E_PROVIDER         | 422    |
        | E_EXIT             | 500    |
        | E_TIMEOUT          | 500    |
        | E_AGENT            | 500    |
        | E_MIGRATION        | 500    |

    @AC-API-03d @unit @P1 @cov-regression
    Scenario: Every code in errors.CODES has a status
      When the status table of the server is compared with errors.CODES
      Then every code in errors.CODES has exactly one status
      And the table has no code that errors.CODES lacks

    @AC-API-03e @unit @P2 @cov-errors
    Scenario Outline: Server-side codes
      When <request>
      Then the status is <status> with error code "<code>"
      Examples:
        | request                                                         | status | code            |
        | a request without a valid session cookie is sent                | 401    | E_AUTH          |
        | a POST without the CSRF header is sent                          | 403    | E_CSRF          |
        | a request with Host "attacker.example:P" is sent                | 403    | E_HOST          |
        | a request with Origin "http://attacker.example" is sent         | 403    | E_ORIGIN        |
        | an unknown route is called                                      | 404    | E_NOT_FOUND     |
        | DELETE is sent to a GET route                                   | 405    | E_METHOD        |
        | a body of 2 MB is sent                                          | 413    | E_BODY_TOO_LARGE |
        | a text/plain body is sent                                       | 415    | E_MEDIA_TYPE    |

    @AC-API-03f @integration @P1 @cov-errors
    Scenario: An unexpected exception becomes a 500 without internals
      Given the engine function behind GET /api/v1/tasks/leave-balance raises a ZeroDivisionError
      When GET /api/v1/tasks/leave-balance is called
      Then the status is 500 with error code "E_INTERNAL" and message "internal error; see the server log"
      And the body holds no traceback, file path or Python type name
      And the server log holds the traceback once
      And the next request to the server answers normally

    @AC-SEC-06g @integration @P2 @cov-perf-security
    Scenario: Error messages are scrubbed
      Given workspace "digital-hr" has a .env file that sets DB_PASSWORD to "hunter2-secret"
      And the engine raises SentinelError "E_PRECONDITION" with message "cannot reach postgres://u:hunter2-secret@db"
      When the client calls the endpoint that triggers it
      Then the error message in the answer does not contain "hunter2-secret"

  Rule: Mutating calls answer with what the engine stored

    @AC-API-03g @integration @P1 @cov-data-integrity
    Scenario: A successful mutating call returns the stored state
      Given run "leave-balance" is EXECUTING
      When POST /api/v1/tasks/leave-balance/control is sent with body {"action": "cancel"}
      Then the answer equals what GET /api/v1/tasks/leave-balance returns right after
      And the answer is built from a registry read after the commit, not from the request

    @AC-API-03h @unit @P1 @cov-authz
    Scenario: Mutating routes call the CLI's engine functions with actor human and channel dashboard
      When the route table of the server is inspected
      Then POST approvals calls Engine.decide, POST acceptance calls the Phase E acceptance function, POST control calls the run cancel, R20 resume, task cancel and task retry functions, and POST tasks calls Engine.create_run
      And each is called with actor "human", channel "dashboard" and the OS user of the server process as approver
      And no route function writes to the registry or the run folder except through those engine functions
