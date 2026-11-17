@REQ-AGT-02 @REQ-AGT-06 @REQ-VER-02
Feature: Task contract task-v1 and agent result contract agent-result-v1
  The engine writes every task as a task-v1 file and accepts only an agent-result-v1 file back.
  The result is validated, kept for the report, and never used as evidence.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 with both approvals valid

  Rule: The engine writes a valid task-v1 file for every task it creates

    @AC-AGT-02a @unit @P1 @cov-happy-path
    Scenario: A created task has a schema-valid task file
      When the engine creates a "docs" task for "leave-balance" on repo "backend" with write scope "backend/docs/**"
      Then .sentinel/runs/leave-balance/tasks/<task-id>/task.json exists
      And it validates against the schema "task-v1"
      And it holds the run id "leave-balance", the role "docs", the repos ["backend"] and permissions.write ["backend/docs/**"]
      And input.specification and input.gherkin hold the paths and sha256 of the approved versions
      And constraints.timeout_seconds is 5400
      And expected_output is {"schema": "agent-result-v1", "path": "result.json"}
      And the task row is CREATED and stores the sha256 of task.json
      And one "task.created" event is stored with the role, repo, provider, model and adapter

    @AC-AGT-02b @unit @P1 @cov-missing-fields
    Scenario Outline: A task that would break task-v1 is never created
      When the engine is asked to create a task for "leave-balance" with <problem>
      Then the request is refused with error "E_VALIDATION"
      And the error names the field <field>
      And no task row and no task folder are created
      Examples:
        | problem                          | field                         |
        | no objective                     | "objective"                   |
        | an empty objective               | "objective"                   |
        | no repos                         | "repos"                       |
        | role "coder"                     | "role"                        |
        | timeout_seconds 0                | "constraints.timeout_seconds" |
        | timeout_seconds -5               | "constraints.timeout_seconds" |
        | max_retries -1                   | "constraints.max_retries"     |
        | repo "mobile" not in the config  | "repos"                       |

    @AC-AGT-02c @unit @P2 @cov-boundary
    Scenario Outline: Timeout and retry limits come from task, then policy, then default
      Given sentinel.config.yaml sets <config>
      When the engine creates a "docs" task for "leave-balance" with <task_setting>
      Then constraints.timeout_seconds is <timeout> and constraints.max_retries is <retries>
      Examples:
        | config                                                       | task_setting       | timeout | retries |
        | nothing under policies                                       | no limits          | 5400    | 2       |
        | policies.task_timeout_seconds 600                            | no limits          | 600     | 2       |
        | policies.task_timeout_seconds 600 and agents.docs.max_retries 4 | no limits       | 600     | 4       |
        | policies.task_timeout_seconds 600                            | timeout_seconds 30 | 30      | 2       |

    @AC-AGT-02d @unit @P2 @cov-empty-null
    Scenario: A read-only role gets an empty write scope
      When the engine creates a "reviewer" task for "leave-balance" on repo "backend"
      Then permissions.write in task.json is an empty list
      And permissions.read is ["backend/**"]

  Rule: A missing or invalid result fails the task with E_RESULT_SCHEMA

    @AC-AGT-02e @unit @P1 @cov-happy-path
    Scenario: A valid result completes the task
      Given a RUNNING "docs" task for "leave-balance" whose process exited with code 0
      And result.json is {"schema": "agent-result-v1", "task_id": "<task-id>", "status": "completed", "summary": "Docs updated"}
      When the engine finishes the task
      Then the task state is COMPLETED
      And the result is stored as an artifact referenced by sha256 from the task row
      And one "task.finished" event is stored with state "COMPLETED", no error code and the duration in seconds

    @AC-AGT-02f @unit @P1 @cov-invalid-input
    Scenario Outline: A broken result fails the task
      Given a RUNNING "docs" task for "leave-balance" whose process exited with code 0
      And result.json <content>
      When the engine finishes the task
      Then the task state is FAILED with error code "E_RESULT_SCHEMA"
      And the error details name <problem>
      And the agent's output log is kept under the task folder
      And the "task.finished" event carries error code "E_RESULT_SCHEMA"
      Examples:
        | content                                                         | problem                    |
        | does not exist                                                  | "result.json missing"      |
        | is not JSON ("Done! All good.")                                 | "not valid JSON"           |
        | has no "summary"                                                | "summary"                  |
        | has "status": "done"                                            | "status"                   |
        | has "schema": "agent-result-v0"                                 | "schema"                   |
        | has "task_id" of another task                                   | "task_id"                  |
        | has "findings" with severity "critical"                         | "findings[0].severity"     |
        | is a JSON list instead of an object                             | "must be an object"        |

    @AC-AGT-02g @unit @P2 @cov-empty-null
    Scenario Outline: An empty result fails the task
      Given a RUNNING "docs" task for "leave-balance" whose process exited with code 0
      And result.json is <content>
      When the engine finishes the task
      Then the task state is FAILED with error code "E_RESULT_SCHEMA"
      Examples:
        | content            |
        | 0 bytes            |
        | only whitespace    |
        | the JSON value {}  |
        | the JSON value null |

    @AC-AGT-02h @unit @P2 @cov-boundary
    Scenario: Unknown extra fields in a result are kept and do not fail the task
      Given a RUNNING "docs" task for "leave-balance" whose process exited with code 0
      And a valid result.json that also has the field "mood": "confident"
      When the engine finishes the task
      Then the task state is COMPLETED
      And the stored result keeps the field "mood"

  Rule: The result status cannot overrule the engine

    @AC-AGT-02i @unit @P1 @cov-errors
    Scenario Outline: Process outcome and result status together decide the task state
      Given a RUNNING "docs" task for "leave-balance"
      And its process exited with code <exit>
      And result.json is valid with status <status>
      When the engine finishes the task
      Then the task state is <state>
      And the error code is <code>
      Examples:
        | exit | status      | state     | code       |
        | 0    | "completed" | COMPLETED | none       |
        | 0    | "failed"    | FAILED    | "E_AGENT"  |
        | 1    | "completed" | FAILED    | "E_EXIT"   |
        | 1    | "failed"    | FAILED    | "E_EXIT"   |
        | 0    | "blocked"   | BLOCKED   | none       |

    @AC-AGT-02j @unit @P1 @cov-data-integrity
    Scenario: Changed files are taken from git, not from the result
      Given a RUNNING "docs" task for "leave-balance" on repo "backend"
      And the process changed only backend/docs/leave.md
      And result.json is valid and claims changed files ["backend/docs/leave.md", "backend/docs/api.md"]
      When the engine finishes the task
      Then the task state is COMPLETED
      And the task's changed files are ["backend/docs/leave.md"]
      And the task report flags the claim "backend/docs/api.md" as "claimed but not changed"

    @AC-VER-02a @unit @P1 @cov-data-integrity
    Scenario: Claimed commands never create evidence
      Given a RUNNING "docs" task for "leave-balance"
      And result.json is valid and claims the command "./gradlew test" with exit code 0
      When the engine finishes the task
      Then the task state is COMPLETED
      And no evidence row exists for "leave-balance"
      And the claimed command is kept in the stored result only

    @AC-AGT-02k @unit @P1 @cov-authz
    Scenario: A result cannot change the run state
      Given a RUNNING "docs" task for "leave-balance"
      And result.json is valid with status "completed" and the extra field "run_state": "COMPLETED"
      When the engine finishes the task
      Then the task state is COMPLETED
      And the run state is still EXECUTING
      And no "run.state_changed" event is stored for the task

  Rule: The agent cannot widen its own task

    @AC-AGT-06a @unit @P1 @cov-authz
    Scenario: A task file edited during the task fails the task
      Given a RUNNING "docs" task for "leave-balance" with write scope "backend/docs/**"
      And during the task its task.json is edited to add the write glob "backend/**"
      When the engine finishes the task
      Then the task state is FAILED with error code "E_INTEGRITY"
      And the scope check used the stored write scope "backend/docs/**"
      And the run state is NEEDS_HUMAN with reason "task file changed during task <task-id>"
      And one audit row records action "integrity_failed" for the task
