@REQ-MON-01 @REQ-MON-02 @REQ-MON-03 @REQ-DSH-05 @REQ-ANL-02
Feature: Run monitoring with live updates
  The run page shows the real run graph from GET /api/v1/tasks/{slug}/workflow and keeps it
  current from the event stream. The stream only tells the page what to re-fetch; the shown
  state always comes from a REST answer. Controls are cancel, resume and retry, each sent to
  POST /api/v1/tasks/{slug}/control. Pause and "request intervention" are not offered.

  Background:
    Given the built dashboard is served by the fake API server on 127.0.0.1 with fixture set "two-projects"
    And the browser holds a valid session cookie
    And run "leave-balance" of "digital-hr" is EXECUTING at tier 3

  Rule: The run graph

    @AC-MON-01f @e2e @P1 @cov-happy-path
    Scenario: Nodes, edges and gates of the run
      Given the workflow answer has a COMPLETED specifier task, a FAILED tdd_green task with a QUEUED retry and a native qa task WAITING_FOR_INPUT
      When the user opens the "Workflow" tab of run "leave-balance"
      Then each task is a node showing role, repo, state, adapter, provider, model, attempt, start time and duration
      And the edges show the task dependencies
      And the specification and Gherkin gates show their approval states
      And the retry node shows "Retry of" the failed task and the failed node shows its error code
      And the qa node shows "waiting for orchestrator"

    @AC-MON-01g @e2e @P1 @cov-happy-path
    Scenario: The graph has a list view with the same content
      When the user switches the "Workflow" tab to "List"
      Then a table shows every node with the same fields as the graph, one row per task, in dependency order
      And each row's dependencies are named in text

    @AC-MON-01h @e2e @P2 @cov-empty-null
    Scenario: A run with no tasks yet
      Given the workflow answer has no nodes and no edges
      When the user opens the "Workflow" tab
      Then the tab says "No tasks yet" and shows the step from GET /api/v1/tasks/leave-balance/next

    @AC-MON-01i @e2e @P2 @cov-boundary
    Scenario: A run with 500 tasks
      Given the workflow answer has 500 nodes
      When the user opens the "Workflow" tab
      Then the tab is interactive within 2 seconds on the test machine
      And a filter by state and by role narrows the nodes

    @AC-ANL-02c @unit @P2 @cov-empty-null
    Scenario Outline: Missing values are shown as missing
      Given a task node whose field "<field>" is null with reason "<reason>"
      When the node details render
      Then the field shows "Not reported" and the reason "<reason>"
      And no number is shown for it
      Examples:
        | field    | reason                       |
        | model    | runner does not report it    |
        | tokens   | runner does not report it    |
        | cost     | runner does not report it    |
        | seconds  | task has not finished        |

  Rule: Live log tail

    @AC-MON-03d @e2e @P1 @cov-happy-path
    Scenario: Following the log of a running task
      Given task t-green1 is RUNNING and its log has 3 lines
      When the user opens the log of t-green1
      Then the 3 lines are shown and GET /api/v1/tasks/leave-balance/logs/t-green1 is called again with offset next_offset while running is true
      And new lines are appended in order, never repeated
      And polling stops when the answer says running false

    @AC-MON-03e @e2e @P2 @cov-boundary
    Scenario: A long log stays usable
      Given the log of t-green1 grows to 20000 lines
      When the user follows it
      Then at most the last 5000 lines are kept on the page with a note "Older lines are hidden"
      And scrolling up pauses auto-scroll until the user presses "Follow"

    @AC-MON-03f @e2e @P3 @cov-errors
    Scenario: A log that cannot be read
      Given GET /api/v1/tasks/leave-balance/logs/t-green1 answers 404 with error code "E_NOT_FOUND"
      When the user opens the log of t-green1
      Then the log panel says "Log not available" and polling stops

  Rule: Controls are cancel, resume and retry

    @AC-MON-02j @e2e @P1 @cov-happy-path
    Scenario Outline: Controls offered by run and task state
      Given <state>
      When the user opens run "leave-balance"
      Then the controls shown are <controls>
      And no "Pause" or "Request intervention" control is shown
      Examples:
        | state                                                     | controls                                 |
        | the run is EXECUTING                                      | "Cancel run"                             |
        | the run is NEEDS_HUMAN with reason "red retry cap reached" | "Cancel run" and "Resume"               |
        | task t-doc1 is FAILED                                     | "Cancel run" and "Retry" on t-doc1       |
        | task t-red2 is QUEUED                                     | "Cancel run" and "Cancel task" on t-red2 |
        | the run is COMPLETED                                      | none                                     |
        | the run is CANCELLED                                      | none                                     |
        | the run is a 0.1 run                                      | none                                     |

    @AC-MON-02k @e2e @P1 @cov-happy-path
    Scenario Outline: Each control sends one engine action
      Given <state>
      When the user uses "<control>" and confirms in the dialog with comment <comment>
      Then POST /api/v1/tasks/leave-balance/control is sent with body <body>
      And the page shows the state from the answer
      Examples:
        | state                         | control      | comment             | body                                                         |
        | the run is EXECUTING          | Cancel run   | "wrong ticket"      | {"action": "cancel", "comment": "wrong ticket"}              |
        | task t-red2 is QUEUED         | Cancel task  | none                | {"action": "cancel", "task_id": "t-red2"}                    |
        | the run is NEEDS_HUMAN        | Resume       | "test data fixed"   | {"action": "resume", "comment": "test data fixed"}           |
        | task t-doc1 is FAILED         | Retry        | none                | {"action": "retry", "task_id": "t-doc1"}                     |

    @AC-MON-02l @e2e @P1 @cov-missing-fields
    Scenario: Resume needs a reason
      Given the run is NEEDS_HUMAN
      When the user opens the "Resume" dialog and leaves the comment empty or blank
      Then the "Resume" button of the dialog is disabled and the field says "Say what was fixed"

    @AC-MON-02m @e2e @P1 @cov-authz
    Scenario: Cancelling asks first and names its effect
      Given the run is EXECUTING with 2 RUNNING tasks
      When the user presses "Cancel run"
      Then a dialog says "Cancel run leave-balance? 2 running tasks are stopped. This cannot be undone." with "Keep running" focused
      And no request is sent when the user presses "Keep running" or Escape

    @AC-MON-02n @e2e @P2 @cov-errors
    Scenario: A control refused by the engine
      Given the fake API answers the control call with 409 and error code "E_TRANSITION"
      When the user cancels the run
      Then the page says "Refused: the run moved on." and shows the run state from a fresh GET

  Rule: Live updates and reconnect

    @AC-DSH-05e @e2e @P1 @cov-happy-path
    Scenario: Events refresh the views they touch
      Given the run page of "leave-balance" is open
      When the event stream sends "task.state_changed" for task t-green1 of "leave-balance"
      Then within 1 second the page calls GET /api/v1/tasks/leave-balance/workflow and shows the new state from its answer
      And an event for run "leave-form" causes no request for "leave-balance"

    @AC-DSH-05f @unit @P1 @cov-data-integrity
    Scenario: State is taken from REST answers, never from event payloads
      Given the run store holds state EXECUTING from GET /api/v1/tasks/leave-balance
      When a "run.state_changed" event with payload state "COMPLETED" arrives and the re-fetch answers state "VERIFYING"
      Then the store holds "VERIFYING"
      And at no time did it hold "COMPLETED"

    @AC-DSH-05g @e2e @P1 @cov-external-failure
    Scenario: The connection drops and comes back
      Given the run page of "leave-balance" is open with the stream connected
      When the fake API closes the stream and refuses connections for 5 seconds
      Then a status line with role "status" says "Connection lost. Reconnecting." within 2 seconds
      And the controls and decision buttons are disabled while disconnected
      And after the stream reconnects with Last-Event-ID the status says "Connected" and the open views are re-fetched once

    @AC-DSH-05h @e2e @P1 @cov-errors
    Scenario Outline: A resync message re-fetches the named projects
      Given the run page of "leave-balance" of "digital-hr" is open
      When the stream sends event "resync" with data naming project "<project>" and reason "<reason>"
      Then <outcome>
      Examples:
        | project     | reason               | outcome                                                                       |
        | digital-hr  | unknown event id     | every open view of "digital-hr" is re-fetched once                            |
        | payroll     | project unavailable  | no view of "digital-hr" is re-fetched and the project list marks "payroll" unavailable after its re-fetch |
        | digital-hr  | database restored    | every open view of "digital-hr" is re-fetched once                            |

    @AC-DSH-05i @e2e @P2 @cov-concurrency
    Scenario: A burst of events causes few requests
      When the stream sends 200 events for run "leave-balance" within 1 second
      Then GET /api/v1/tasks/leave-balance/workflow is called at most 3 times
      And the last call starts after the last event arrived

    @AC-DSH-05j @unit @P2 @cov-invalid-input
    Scenario Outline: Unusable stream messages are ignored
      Given the event client receives a message with event "<event>" and data <data>
      When it handles the message
      Then no exception escapes, no state changes and the message is counted as ignored
      Examples:
        | event              | data                        |
        | task.state_changed | not json                    |
        | task.state_changed | {"project": null}           |
        | something.new      | {"project": "digital-hr"}   |
