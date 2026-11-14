@REQ-API-01 @REQ-API-03 @REQ-MON-01 @REQ-MON-03 @REQ-SEC-02 @REQ-SEC-06 @REQ-SEC-07
Feature: Read endpoints for projects, runs, tasks, approvals, evidence and logs
  The read endpoints return what the engine stored, in the envelopes of api-contracts.md section 1.
  Run routes use the contract path /api/v1/tasks/{slug}. Artifact, log, report and evidence
  output is read through the registry, re-hashed, and scrubbed before it is served.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And workspace "digital-hr" with a .env file that sets DB_PASSWORD to "hunter2-secret" is registered as project "digital-hr"
    And the server listens on 127.0.0.1 port P and the client holds session cookie S and CSRF value C

  Rule: Projects

    @AC-API-01o @integration @P1 @cov-happy-path
    Scenario: Listing the registered projects
      Given projects.json lists "digital-hr" and "payroll"
      And "digital-hr" has 2 active runs and "payroll" has none
      When GET /api/v1/projects is called
      Then the status is 200 with items for "digital-hr" and "payroll" and next null
      And each item holds id, name, path, status "available" and the number of active runs

    @AC-API-01p @integration @P2 @cov-external-failure
    Scenario Outline: A project that cannot be opened is listed as unavailable
      Given projects.json lists "digital-hr" and "payroll"
      And <problem> for "payroll"
      When GET /api/v1/projects is called
      Then "digital-hr" has status "available"
      And "payroll" has status "unavailable" with reason "<reason>"
      And GET /api/v1/projects/payroll/tasks answers 422 with error code "E_PRECONDITION" and that reason
      Examples:
        | problem                                                       | reason                          |
        | the workspace folder was deleted                              | workspace missing               |
        | sentinel.config.yaml is invalid                               | invalid configuration           |
        | .sentinel/sentinel.db has a newer schema version than Sentinel | E_MIGRATION                     |

    @AC-API-01q @integration @P2 @cov-empty-null
    Scenario: No project registered
      Given projects.json lists no project
      When GET /api/v1/projects is called
      Then the status is 200 with items [] and next null

    @AC-API-01r @integration @P2 @cov-invalid-input
    Scenario: An unknown project id
      When GET /api/v1/projects/no-such-project is called
      Then the status is 404 with error code "E_NOT_FOUND"

  Rule: Runs and run detail

    @AC-API-01s @integration @P1 @cov-happy-path
    Scenario: Listing the runs of a project
      Given project "digital-hr" has version 2 runs "leave-balance" (EXECUTING, tier 3) and "leave-form" (COMPLETED, accepted) and a 0.1 run "old-fix"
      When GET /api/v1/projects/digital-hr/tasks is called
      Then the items hold slug, type, tier, state, execution_status, acceptance_status, workflow_version and updated_at of the three runs
      And "old-fix" has workflow_version "0.1" and state as indexed from its state.json
      And the items are ordered by updated_at, newest first

    @AC-API-01t @integration @P2 @cov-boundary
    Scenario Outline: Paging through runs
      Given project "digital-hr" has 120 runs
      When GET /api/v1/projects/digital-hr/tasks<query> is called
      Then the status is <status>
      And <outcome>
      Examples:
        | query                        | status | outcome                                                      |
        |                              | 200    | 50 items are returned with a non-null next cursor            |
        | ?limit=200                   | 200    | 120 items are returned with next null                        |
        | ?limit=1                     | 200    | 1 item is returned with a non-null next cursor               |
        | ?limit=0                     | 400    | the error code is "E_VALIDATION"                             |
        | ?limit=201                   | 400    | the error code is "E_VALIDATION"                             |
        | ?limit=abc                   | 400    | the error code is "E_VALIDATION"                             |
        | ?cursor=not-a-cursor         | 400    | the error code is "E_VALIDATION"                             |

    @AC-API-01u @integration @P2 @cov-data-integrity
    Scenario: Following cursors returns every run once
      Given project "digital-hr" has 120 runs
      When the client follows next cursors with limit 50 until next is null
      And a new run is created between the first and the second page
      Then every one of the 120 runs appears exactly once across the pages

    @AC-API-01v @integration @P1 @cov-happy-path
    Scenario: Run detail
      Given run "leave-balance" is EXECUTING at tier 3 on repos "backend" and "frontend" with both approvals APPROVED
      When GET /api/v1/tasks/leave-balance is called
      Then the answer holds slug, project "digital-hr", type, tier, initial tier, state "EXECUTING", execution_status and acceptance_status
      And it holds for each repo the baseline SHA, the branch and final_sha null
      And it holds the specification and Gherkin approval states with version and sha256
      And it holds task counts by state and the step "sentinel next leave-balance --json" would return

    @AC-API-01w @integration @P1 @cov-invalid-input
    Scenario Outline: Bad or unknown run slugs
      When GET /api/v1/tasks/<slug> is called
      Then the status is <status> with error code "<code>"
      Examples:
        | slug          | status | code          |
        | no-such-run   | 404    | E_NOT_FOUND   |
        | Leave_Balance | 400    | E_VALIDATION  |
        | a..b          | 400    | E_VALIDATION  |
        | x.lock        | 400    | E_VALIDATION  |

    @AC-API-01x @integration @P2 @cov-boundary
    Scenario Outline: A slug used in two projects needs the project parameter
      Given projects "digital-hr" and "payroll" both have a run "leave-balance"
      When GET /api/v1/tasks/leave-balance<query> is called
      Then <outcome>
      Examples:
        | query               | outcome                                                                                       |
        |                     | the status is 400 with error code "E_VALIDATION" and details.projects ["digital-hr", "payroll"] |
        | ?project=payroll    | the status is 200 and the answer names project "payroll"                                       |
        | ?project=nope       | the status is 404 with error code "E_NOT_FOUND"                                                |

    @AC-API-03a @contract @P1 @cov-data-integrity
    Scenario: The next endpoint returns what the CLI returns
      Given run "leave-balance" is EXECUTING with a QUEUED native task
      When GET /api/v1/tasks/leave-balance/next is called
      And "sentinel next leave-balance --json" is run in the workspace
      Then the JSON of both is equal

  Rule: Tasks of a run

    @AC-MON-01a @integration @P1 @cov-happy-path
    Scenario: The workflow graph shows the real tasks
      Given run "leave-balance" has a COMPLETED specifier task, a FAILED tdd_green task with a QUEUED retry, and a native qa task WAITING_FOR_INPUT
      When GET /api/v1/tasks/leave-balance/workflow is called
      Then the nodes hold each task id, role, repo, state, adapter, provider, model, attempt, retry_of, error_code, started_at, finished_at and seconds
      And the edges hold the task dependencies
      And the gates hold the specification and Gherkin approvals with their states
      And the qa node is labelled "waiting for orchestrator"

    @AC-MON-01b @integration @P2 @cov-happy-path
    Scenario Outline: Other run views
      Given run "leave-balance" is REVIEWING with cycles, evidence rows, trace links and a report
      When GET /api/v1/tasks/leave-balance/<view> is called
      Then the status is 200 and the answer holds <content>
      Examples:
        | view          | content                                                                                 |
        | tdd           | each cycle with behavior, state, phase task ids and evidence ids                        |
        | verification  | the evidence rows of the latest round and the acceptance computation with reasons       |
        | trace         | the trace links and the gaps reported apart from failures                               |
        | specification | the current version, its sha256, the validation result and the diff to the previous one |
        | gherkin       | the feature files, scenarios with tags, the coverage table and the set hash             |
        | report        | report.json of the run                                                                  |

    @AC-MON-01c @integration @P2 @cov-empty-null
    Scenario: A new run has empty views, not errors
      Given run "leave-form" is CREATED with no tasks, cycles or evidence
      When GET /api/v1/tasks/leave-form/workflow, /tdd, /verification and /trace are called
      Then each answers 200 with empty lists
      And GET /api/v1/tasks/leave-form/report answers 422 with error code "E_PRECONDITION" because the run has no report yet

  Rule: Approvals waiting for a human

    @AC-API-01y @integration @P1 @cov-happy-path
    Scenario: Listing approvals in review across projects
      Given run "leave-balance" of "digital-hr" is SPECIFICATION_REVIEW and run "tax-form" of "payroll" is GHERKIN_REVIEW
      When GET /api/v1/approvals?state=IN_REVIEW is called
      Then the items hold project, slug, gate, version, sha256 and the time the review was requested for both
      And no item is listed for runs whose approvals are APPROVED

    @AC-API-01z @integration @P2 @cov-invalid-input
    Scenario: An unknown approval state filter
      When GET /api/v1/approvals?state=MAYBE is called
      Then the status is 400 with error code "E_VALIDATION" listing the allowed states

  Rule: Artifacts, logs and evidence output are hash-checked and scrubbed

    @AC-SEC-06c @integration @P1 @cov-perf-security
    Scenario Outline: Served content is scrubbed
      Given <file> of run "leave-balance" contains the line "password=hunter2-secret"
      When <request> is called
      Then the answer does not contain "hunter2-secret"
      And it contains the scrubber's replacement marker in that line
      Examples:
        | file                                         | request                                                          |
        | the evidence output artifact a-out1          | GET /api/v1/tasks/leave-balance/artifacts/a-out1                 |
        | output.log of task t-green1                  | GET /api/v1/tasks/leave-balance/logs/t-green1                    |
        | report.md                                    | GET /api/v1/tasks/leave-balance/report?format=md                 |
        | the result.json artifact a-res1              | GET /api/v1/tasks/leave-balance/artifacts/a-res1                 |

    @AC-SEC-06d @integration @P1 @cov-data-integrity
    Scenario: An artifact changed on disk is not served as if valid
      Given artifact a-spec2 of run "leave-balance" is stored with sha256 H
      And its file was edited after it was stored
      When GET /api/v1/tasks/leave-balance/artifacts/a-spec2 is called
      Then the status is 409 with error code "E_INTEGRITY" and details naming the stored sha256 H
      And the file content is not returned

    @AC-SEC-06e @integration @P2 @cov-authz
    Scenario Outline: Artifacts and logs are looked up by id within the run
      When <request> is called
      Then the status is 404 with error code "E_NOT_FOUND"
      Examples:
        | request                                                         |
        | GET /api/v1/tasks/leave-balance/artifacts/a-of-another-run      |
        | GET /api/v1/tasks/leave-balance/artifacts/a-unknown             |
        | GET /api/v1/tasks/leave-balance/logs/t-of-another-run           |

    @AC-MON-03a @integration @P1 @cov-happy-path
    Scenario: Tailing a live log by offset
      Given task t-green1 of run "leave-balance" is RUNNING and its output.log has 3 complete lines of 40 bytes each
      When GET /api/v1/tasks/leave-balance/logs/t-green1?offset=0 is called
      Then the answer holds the 3 lines and next_offset 120 and running true
      And after the runner writes 2 more lines, GET with offset=120 returns only those 2 lines

    @AC-MON-03b @integration @P2 @cov-boundary
    Scenario Outline: Log offsets
      Given output.log of task t-green1 has 120 bytes ending with a newline and 15 more bytes with no newline yet
      When GET /api/v1/tasks/leave-balance/logs/t-green1?offset=<offset> is called
      Then <outcome>
      Examples:
        | offset | outcome                                                                                  |
        | 120    | the answer holds no lines and next_offset 120, because a partial line is never served   |
        | 135    | the status is 400 with error code "E_VALIDATION" because the offset is not a line start  |
        | 9999   | the status is 400 with error code "E_VALIDATION" because the offset is past the end      |
        | -1     | the status is 400 with error code "E_VALIDATION"                                         |

    @AC-MON-03c @integration @P3 @cov-empty-null
    Scenario: A task that has not started has an empty log
      Given task t-qa1 of run "leave-balance" is QUEUED and has no output.log
      When GET /api/v1/tasks/leave-balance/logs/t-qa1 is called
      Then the status is 200 with no lines, next_offset 0 and running false

  Rule: Audit, installation and runtime

    @AC-SEC-07a @integration @P2 @cov-happy-path
    Scenario: Reading the audit log of a project
      Given project "digital-hr" has audit rows for a TTY approval and a dashboard cancel
      When GET /api/v1/audit?project=digital-hr is called
      Then the items hold actor, channel, action, target, before and after hash, reason and time, newest first
      And the dashboard row has channel "dashboard"

    @AC-SEC-02k @integration @P3 @cov-happy-path
    Scenario: Installation and runtime information
      When GET /api/v1/installation and GET /api/v1/runtime are called
      Then the installation answer holds the Sentinel version, install path, Python version and install method
      And the runtime answer holds pid, port P, start time and the loaded projects
      And neither answer holds the token, the CSRF value or the content of server.json

    @AC-MON-01d @performance @P2 @cov-perf-security
    Scenario: Reads stay fast on a large run
      Given run "big-run" has 500 tasks, 200 evidence rows and 10000 events
      When GET /api/v1/tasks/big-run and GET /api/v1/tasks/big-run/workflow are each called 10 times
      Then every answer arrives within 1 second on the test machine

    @AC-MON-01e @integration @P2 @cov-concurrency
    Scenario: Reads during CLI writes do not fail
      Given a CLI process writes 200 events to run "leave-balance" as fast as it can
      When 8 client threads call GET /api/v1/tasks/leave-balance 50 times each at the same time
      Then every answer has status 200
      And no answer has error code "E_INTERNAL" or mentions "database is locked"
