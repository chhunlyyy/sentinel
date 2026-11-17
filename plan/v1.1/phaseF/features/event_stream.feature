@REQ-API-02 @REQ-DSH-05 @REQ-PER-03 @REQ-SEC-06
Feature: Server-sent event stream with resume
  GET /api/v1/events streams committed rows of the events table of every registered workspace,
  in id order per project, in the envelope of event-contracts.md section 1. The SSE id is
  "<project>:<id>". A client that reconnects with Last-Event-ID gets every newer row it missed.
  Events written by CLI and AI-tool processes reach the stream through polling.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And workspaces "digital-hr" and "payroll" are registered as projects "digital-hr" and "payroll"
    And the server listens on 127.0.0.1 port P with poll interval 500 ms and heartbeat interval 15 s
    And the client holds session cookie S

  Rule: Stream format and order

    @AC-API-02a @integration @P1 @cov-happy-path
    Scenario: A stream delivers new events in order
      Given the client opened GET /api/v1/events?project=digital-hr with cookie S
      When a CLI process writes events 41, 42 and 43 for run "leave-balance" of "digital-hr"
      Then the response has Content-Type "text/event-stream" and Cache-Control "no-store"
      And the client receives three messages with ids "digital-hr:41", "digital-hr:42" and "digital-hr:43" in that order
      And each message has the event field set to the event type and a data line with the envelope id, type, at, project, run, task, actor and payload
      And the first message arrives within 1 second of its row being committed

    @AC-API-02b @integration @P1 @cov-happy-path
    Scenario: A dashboard decision shows its channel in the stream
      Given the client opened GET /api/v1/events?project=digital-hr
      When a human approves the specification of "leave-balance" through the API
      Then the client receives an "approval.decided" message whose actor has kind "human", name "dev" and channel "dashboard"
      And it receives the "run.state_changed" message of R5 after it

    @AC-API-02c @integration @P2 @cov-happy-path
    Scenario Outline: Filters
      Given events are written for run "leave-balance" and run "leave-form" of "digital-hr" and run "tax-form" of "payroll"
      When the client opens GET /api/v1/events<query>
      Then it receives only the events of <runs>
      Examples:
        | query                                    | runs                                     |
        | ?project=digital-hr                      | "leave-balance" and "leave-form"         |
        | ?project=digital-hr&run=leave-balance    | "leave-balance"                          |
        | ?project=payroll                         | "tax-form"                               |
        |                                          | "leave-balance", "leave-form" and "tax-form" |

    @AC-API-02d @integration @P2 @cov-invalid-input
    Scenario Outline: Bad filters
      When the client opens GET /api/v1/events<query>
      Then the status is <status> with error code "<code>" and no stream is opened
      Examples:
        | query                                  | status | code          |
        | ?project=nope                          | 404    | E_NOT_FOUND   |
        | ?project=digital-hr&run=no-such-run    | 404    | E_NOT_FOUND   |
        | ?project=digital-hr&run=Bad..Slug      | 400    | E_VALIDATION  |

    @AC-API-02e @integration @P1 @cov-data-integrity
    Scenario: Only committed events are streamed
      Given the client opened GET /api/v1/events?project=digital-hr
      When an engine transaction writes an event and then rolls back
      And another transaction commits event 44
      Then the client never receives the rolled-back event
      And it receives "digital-hr:44"

    @AC-API-02f @integration @P2 @cov-boundary
    Scenario: A new stream starts at the current head
      Given project "digital-hr" already has events 1 to 40
      When the client opens GET /api/v1/events?project=digital-hr without Last-Event-ID
      Then no message for events 1 to 40 is sent
      And the first message is the next event written

    @AC-API-02g @integration @P2 @cov-boundary
    Scenario: Heartbeats keep an idle stream open
      Given the server was started with a heartbeat interval of 200 ms for the test
      When the client keeps GET /api/v1/events?project=digital-hr open for 1 second with no new events
      Then it receives at least 4 comment lines starting with ":" and no event message

  Rule: Resume with Last-Event-ID

    @AC-DSH-05a @integration @P1 @cov-happy-path
    Scenario: A reconnecting client gets every missed event
      Given the client received "digital-hr:42" on GET /api/v1/events?project=digital-hr and was disconnected
      And events 43 to 47 were written while it was away
      When it reconnects with Last-Event-ID "digital-hr:42"
      Then it receives "digital-hr:43" to "digital-hr:47" in order, each exactly once
      And then it receives new events live

    @AC-DSH-05b @integration @P1 @cov-errors
    Scenario Outline: A Last-Event-ID that cannot be resumed exactly asks for a refresh
      Given project "digital-hr" has events 1 to 50
      When the client reconnects to GET /api/v1/events?project=digital-hr with Last-Event-ID <id>
      Then the first message has event "resync" and data naming project "digital-hr" and the reason "<reason>"
      And the stream continues from the current head
      Examples:
        | id                    | reason             |
        | "digital-hr:900"      | unknown event id   |
        | "digital-hr:abc"      | malformed id       |
        | "garbage"             | malformed id       |
        | "unknown-project:12"  | unknown project    |

    @AC-DSH-05c @integration @P2 @cov-boundary
    Scenario: Resume of a stream without a project filter
      Given the client received "digital-hr:42" on GET /api/v1/events and was disconnected
      And events 43 and 44 of "digital-hr" and events 7 and 8 of "payroll" were written while it was away
      When it reconnects with Last-Event-ID "digital-hr:42"
      Then it receives "digital-hr:43" and "digital-hr:44"
      And it receives a "resync" message naming project "payroll" so the client re-fetches it
      And then it receives new events of both projects live

    @AC-DSH-05d @integration @P2 @cov-external-failure
    Scenario: The database is replaced by an older backup
      Given the client received "digital-hr:50" and "digital-hr" has events up to 50
      When .sentinel/sentinel.db of "digital-hr" is restored from a backup whose last event id is 30
      Then the client receives a "resync" message naming project "digital-hr" within 2 seconds
      And it receives the next new event of "digital-hr" live

  Rule: Events from every writer, with scrubbed payloads

    @AC-API-02h @integration @P1 @cov-happy-path
    Scenario: Events written by other processes reach the stream
      Given the client opened GET /api/v1/events
      When "sentinel next leave-balance" in a terminal, a "sentinel task run" process and an AI-tool "sentinel task complete" each write an event
      Then the client receives all three within 1 second of each commit

    @AC-SEC-06f @integration @P1 @cov-perf-security
    Scenario: Event payloads are scrubbed when served
      Given workspace "digital-hr" has a .env file that sets DB_PASSWORD to "hunter2-secret"
      And the client opened GET /api/v1/events?project=digital-hr
      When a human requests changes at a terminal with the comment "use password hunter2-secret"
      Then the "approval.decided" message does not contain "hunter2-secret"
      And the stored event row is unchanged

    @AC-API-02i @integration @P2 @cov-db-failure
    Scenario: One unreadable workspace does not stop the others
      Given the client opened GET /api/v1/events
      When .sentinel/sentinel.db of "payroll" becomes unreadable
      Then the client receives one "resync" message naming "payroll" with reason "project unavailable"
      And it keeps receiving events of "digital-hr"
      And when "payroll" is readable again its new events are streamed after a "resync" message

    @AC-API-02j @integration @P2 @cov-boundary
    Scenario: A project added while streaming is included
      Given the client opened GET /api/v1/events with no filter
      When workspace "hr-docs" is registered in projects.json and writes event 1
      Then within 2 seconds the client receives "hr-docs:1"

  Rule: Many clients and slow clients

    @AC-API-02k @performance @P2 @cov-concurrency
    Scenario: Several clients receive the same events
      Given 20 clients opened GET /api/v1/events?project=digital-hr
      When 100 events are written by a CLI process
      Then every client receives the same 100 ids in the same order within 2 seconds of the last commit

    @AC-API-02l @integration @P2 @cov-concurrency
    Scenario: A client that stops reading does not block the others
      Given client A opened the stream and stops reading from its socket, and client B reads normally
      When 5000 events are written
      Then client B receives every event within 2 seconds of each commit
      And the server closes the connection of client A once its send buffer stays full for 10 seconds
      And client A, reconnecting with its Last-Event-ID, receives every event it missed

    @AC-API-02m @integration @P3 @cov-errors
    Scenario: A closed client frees its thread
      Given 10 clients opened GET /api/v1/events and then closed their connections
      When 2 seconds have passed
      Then the server has no thread left serving those streams
      And the server log has no traceback

    @AC-API-02n @security @P2 @cov-authn
    Scenario: The stream ends when the session is no longer valid
      Given the client holds an open stream
      When the server is restarted
      Then the stream is closed
      And reconnecting with the old cookie and a Last-Event-ID answers 401 with error code "E_AUTH"
