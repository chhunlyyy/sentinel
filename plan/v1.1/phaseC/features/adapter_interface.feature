@REQ-AGT-03 @REQ-AGT-04 @REQ-PRV-05 @REQ-VIS-03 @REQ-CFG-08
Feature: Adapter interface, capabilities and provider neutrality
  Every adapter offers capabilities, submit, status, result, cancel and resume.
  The engine picks the adapter from the config; the workflow never names a provider.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree

  Rule: Each adapter reports what it supports

    @AC-AGT-03a @unit @P1 @cov-happy-path
    Scenario Outline: Capabilities come from the runner definition
      Given the runner table holds <runner> as defined by DEFAULT_RUNNERS
      When the engine asks the adapter for <runner> for its capabilities
      Then model_select is <model_select>, resume is <resume>, cancel is <cancel>, json_output is <json_output> and native is <native>
      Examples:
        | runner   | model_select | resume | cancel        | json_output | native |
        | "claude" | true         | false  | "signal"      | false       | false  |
        | "codex"  | true         | false  | "signal"      | false       | false  |
        | "gemini" | true         | false  | "signal"      | false       | false  |
        | "agy"    | true         | true   | "signal"      | true        | false  |
        | "native" | false        | false  | "cooperative" | true        | true   |

    @AC-AGT-03b @unit @P2 @cov-boundary
    Scenario: A custom runner's capabilities follow its fields
      Given sentinel.config.yaml defines runners.local with command "local-agent" and no model_flag and no resume_flag
      When the engine asks the adapter for "local" for its capabilities
      Then model_select is false, resume is false and cancel is "signal"

    @AC-AGT-03c @unit @P1 @cov-invalid-input
    Scenario Outline: Resume is refused when the adapter does not support it
      Given a version 2 run "leave-balance" in state EXECUTING with both approvals valid
      And a WAITING_FOR_INPUT "docs" task for "leave-balance" handled by <adapter> with session id <session>
      When the engine asks the adapter to resume the task with the message "Use ISO dates"
      Then the outcome is <outcome>
      Examples:
        | adapter        | session  | outcome                                                             |
        | "agy"          | "conv-9" | the runner is started again with "--conversation conv-9"            |
        | "agy"          | none     | refused with error "E_PRECONDITION" naming "no session id"          |
        | "codex"        | "x"      | refused with error "E_PRECONDITION" naming "resume not supported"   |
        | "native"       | none     | refused with error "E_PRECONDITION" naming "resume not supported"   |

    @AC-AGT-03d @unit @P2 @cov-invalid-input
    Scenario: A model on a runner without model_flag is refused before the task starts
      Given sentinel.config.yaml sets single_model false and agents.docs to runner "local" with model "big"
      And runners.local has no model_flag
      And a version 2 run "leave-balance" in state EXECUTING with a QUEUED "docs" task
      When "sentinel task run" is run for the docs task
      Then it exits with code 5
      And the error is "E_VALIDATION" naming "runners.local has no model_flag"
      And the docs task is still QUEUED

  Rule: The engine picks the adapter from config, not from the workflow

    @AC-PRV-05a @unit @P1 @cov-happy-path
    Scenario Outline: Adapter selection per role
      Given sentinel.config.yaml sets <config>
      When the engine creates a "<role>" task for "leave-balance" on repo "backend"
      Then the task adapter is <adapter> and its provider is <provider> with model <model>
      Examples:
        | config                                                                     | role     | adapter  | provider | model    |
        | single_model true and routing.reviewer runner "codex"                      | reviewer | "native" | "native" | none     |
        | no single_model key and routing.reviewer runner "codex"                    | reviewer | "native" | "native" | none     |
        | single_model false and routing.reviewer runner "codex" model "gpt-5"       | reviewer | "cli"    | "codex"  | "gpt-5"  |
        | single_model false and routing.backend-reviewer runner "gemini"            | reviewer | "cli"    | "gemini" | none     |
        | single_model false and no routing entry for reviewer                       | reviewer | "native" | "native" | none     |
        | single_model false and agents.docs runner "codex" model "gpt-5"            | docs     | "cli"    | "codex"  | "gpt-5"  |
        | single_model false, agents.docs runner "codex" and routing.docs "gemini"   | docs     | "cli"    | "codex"  | none     |

    @AC-CFG-08a @unit @P2 @cov-data-integrity
    Scenario: A config change after the run started does not change the adapter
      Given a version 2 run "leave-balance" in state EXECUTING whose config snapshot sets single_model false and agents.docs runner "codex"
      And then sentinel.config.yaml is changed to single_model true
      When the engine creates a "docs" task for "leave-balance" on repo "backend"
      Then the task adapter is "cli" and its provider is "codex"

    @AC-VIS-03a @unit @P1 @cov-regression
    Scenario: Workflow definitions name no provider
      When the engine plans the task graph of a tier 3 run "leave-balance"
      Then no task in the graph has a provider or adapter before the config is applied
      And the stored workflow graph contains no runner name from the runner table

  Rule: The same contract runs on every provider

    @AC-VIS-03b @integration @P1 @cov-happy-path
    Scenario Outline: The same task completes the same way on different runners
      Given sentinel.config.yaml sets single_model false and agents.docs to runner "<runner>"
      And runners.<runner> is a fake CLI shaped like <shape> that writes backend/docs/leave.md and a valid result.json, then exits 0
      And a version 2 run "leave-balance" in state EXECUTING with a QUEUED "docs" task on repo "backend" with write scope "backend/docs/**"
      When "sentinel task run" is run for the docs task
      Then it exits with code 0
      And the docs task is COMPLETED
      And task.json is the same for every runner except provider.name
      And the stored events for the task are, in order, "task.queued", "task.started", "task.finished"
      And the "task.started" event names provider "<runner>" and adapter "cli"
      And the task's changed files are ["backend/docs/leave.md"]
      Examples:
        | runner | shape                                                   |
        | fakec  | claude (prompt flag "-p", model flag "--model")         |
        | fakex  | codex (prompt as last argument, no prompt flag)         |
        | fakes  | a stdin runner (input: stdin)                           |
        | fakea  | agy (output json_response with a conversation_id)       |

    @AC-VIS-03c @integration @P1 @cov-happy-path
    Scenario: The native adapter reaches the same end state as the CLI adapter
      Given sentinel.config.yaml sets single_model true
      And a version 2 run "leave-balance" in state EXECUTING with a QUEUED "docs" task on repo "backend" with write scope "backend/docs/**"
      When "sentinel task run" is run for the docs task
      And the orchestrator's subagent writes backend/docs/leave.md and a valid result.json
      And "sentinel task complete" is run for the docs task
      Then the docs task is COMPLETED
      And the result, changed files and "task.finished" event have the same shape as in AC-VIS-03b
      And the "task.started" event names provider "native" and adapter "native"

    @AC-AGT-03e @unit @P2 @cov-happy-path
    Scenario: The session id of a json runner is stored on the task
      Given runners.fakea is a fake CLI shaped like agy that returns conversation_id "conv-42"
      And a docs task for "leave-balance" routed to "fakea" has finished
      When the engine reads the task row
      Then the task handle stores session id "conv-42"
