@REQ-TSK-01 @REQ-TSK-02 @REQ-TSK-03 @REQ-DSH-04
Feature: Task list and task creation
  A task created in the dashboard is a run created through POST /api/v1/projects/{pid}/tasks.
  It is queued for the AI tool: it waits in CREATED until an AI tool session picks it up with
  "/sentinel resume <slug>". Creating it authorizes nothing, and the screen says so.

  Background:
    Given the built dashboard is served by the fake API server on 127.0.0.1 with fixture set "two-projects"
    And the browser holds a valid session cookie
    And project "digital-hr" has repos "backend" and "frontend" and readiness "ready"

  Rule: Task list

    @AC-TSK-01i @e2e @P1 @cov-happy-path
    Scenario: Runs of every project
      When the user opens "Tasks"
      Then a table lists the runs of "digital-hr" and "payroll" with project, slug, type, tier, state, execution status, acceptance status and last update
      And a 0.1 run is labelled "Legacy (0.1)" and its page shows only its state and the CLI command to continue it

    @AC-TSK-01j @e2e @P2 @cov-boundary
    Scenario: Paging and filters
      Given project "digital-hr" has 120 runs
      When the user opens the "Runs" tab of "digital-hr"
      Then 50 runs are shown with a "Load more" button
      And pressing "Load more" twice shows all 120 runs once each and removes the button
      And filtering by state "EXECUTING" shows only runs in that state

    @AC-TSK-01k @e2e @P3 @cov-empty-null
    Scenario: A project with no runs
      Given project "payroll" has no runs
      When the user opens the "Runs" tab of "payroll"
      Then the page says "No runs yet" with a link to "Create task"

  Rule: Creating a task

    @AC-TSK-01l @e2e @P1 @cov-happy-path
    Scenario: Creating a task queues it for the AI tool
      When the user opens "Create task", picks project "digital-hr" and fills slug "leave-report", request "Report leave per team", type "feature", repos "backend", priority "high" and ticket "HR-12"
      And presses "Create task"
      Then POST /api/v1/projects/digital-hr/tasks is sent with body {"slug": "leave-report", "request": "Report leave per team", "type": "feature", "repos": ["backend"], "priority": "high", "ticket": "HR-12"}
      And after the 201 answer the run page of "leave-report" opens with state "CREATED"
      And the page says "Queued for the AI tool. In your AI tool session run /sentinel resume leave-report" with a button that copies "/sentinel resume leave-report"

    @AC-TSK-02b @e2e @P1 @cov-authz
    Scenario: The form says that creating a task approves nothing
      When the user opens "Create task"
      Then the form says "Creating a task does not approve anything. The specification and the Gherkin scenarios need your approval before any code is written."
      And the form has no field that sets an approval, skips a gate or starts a task

    @AC-TSK-01m @e2e @P2 @cov-boundary
    Scenario Outline: Tier and repository choices
      When the user opens "Create task" for project "digital-hr"
      And <action>
      Then <outcome>
      Examples:
        | action                                          | outcome                                                                                |
        | leaves every repository checked                 | the body holds no "repos" field, so every repo of the project is used                   |
        | unchecks every repository                       | "Create task" is disabled and the repos field says "Pick at least one repository"       |
        | opens the tier list                             | the list offers "Decided at triage", 1, 2, 3 and 4 and says "A tier can only raise the triage result" |
        | picks tier 3                                    | the body holds "tier": 3                                                                |
        | leaves the tier at "Decided at triage"          | the body holds no "tier" field                                                          |

    @AC-TSK-01n @unit @P1 @cov-invalid-input @cov-missing-fields
    Scenario Outline: The form checks fields before sending
      Given the create task form with a valid value in every field
      When field "<field>" is set to <value>
      Then the field shows "<message>" and the "Create task" button is disabled
      Examples:
        | field   | value         | message                                                    |
        | slug    | "Bad Slug"    | Use lower-case letters, digits and single hyphens          |
        | slug    | "a..b"        | Use lower-case letters, digits and single hyphens          |
        | slug    | ""            | Required                                                   |
        | request | "   "         | Required                                                   |
        | type    | none          | Required                                                   |

    @AC-TSK-01o @e2e @P1 @cov-invalid-input
    Scenario Outline: Server refusals are shown at the field
      Given the fake API answers the create call with <status> and error code "<code>" and details naming "<field>"
      When the user submits a filled create task form
      Then field "<field>" shows the server message
      And the user stays on the form with every value kept
      And no run page opens
      Examples:
        | status | code            | field    |
        | 400    | E_VALIDATION    | type     |
        | 400    | E_VALIDATION    | repos    |
        | 422    | E_PRECONDITION  | slug     |
        | 409    | E_LOCKED        | slug     |
        | 422    | E_PRECONDITION  | repos    |

    @AC-TSK-01p @e2e @P2 @cov-data-integrity
    Scenario: The request text keeps its form
      When the user enters a request of 3 lines with a blank line between them
      And creates the task
      Then the body "request" holds the same text with its newlines
      And the run page shows the request as plain text with its line breaks

  Rule: Waiting for the AI tool

    @AC-TSK-03j @e2e @P1 @cov-happy-path
    Scenario Outline: Steps that wait for the AI tool are shown, not hidden
      Given GET /api/v1/tasks/leave-balance/next answers kind "<kind>" with label "<label>" and command "<command>"
      When the user opens run "leave-balance"
      Then the run page shows a banner "<label>"
      And the banner shows the command "<command>" with a copy button
      Examples:
        | kind         | label                     | command                         |
        | orchestrator | waiting for AI tool       | /sentinel resume leave-balance  |
        | task         | waiting for orchestrator  | /sentinel resume leave-balance  |

    @AC-TSK-03k @e2e @P2 @cov-happy-path
    Scenario: A human step of the run links to where it is decided
      Given GET /api/v1/tasks/leave-balance/next answers kind "human" for the specification approval
      When the user opens run "leave-balance"
      Then the banner says "Your approval is needed: specification version 2" with a link to its review page
