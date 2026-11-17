@REQ-AGT-04 @REQ-AGT-05 @REQ-AGT-06 @REQ-SEC-02
Feature: CLI adapter runs headless providers through run_stage
  The CLI adapter reuses the run_stage runner table, live log, heartbeat and boundary check.
  The engine, not the runner, decides the task state.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repos "backend" and "frontend" are git repos with a clean working tree
    And sentinel.config.yaml sets single_model false and agents.docs to runner "fake"
    And a version 2 run "leave-balance" in state EXECUTING at tier 3 with both approvals valid
    And a QUEUED "docs" task for "leave-balance" on repo "backend" with write scope "backend/docs/**"

  Rule: A well-behaved runner completes the task

    @AC-AGT-04a @integration @P1 @cov-happy-path
    Scenario: Headless task run
      Given runners.fake is a fake CLI that writes backend/docs/leave.md and a valid result.json, then exits 0
      When "sentinel task run" is run for the docs task
      Then it exits with code 0
      And the docs task is COMPLETED
      And the fake CLI ran with backend as its working directory
      And the prompt it received was rendered from task.json and the docs stage template
      And the prompt names the absolute path of result.json
      And prompt.md, output.log and stderr.log are stored under .sentinel/runs/leave-balance/tasks/<task-id>/
      And the task row stores the provider "fake", the adapter "cli", started_at, finished_at and seconds
      And the output is JSON with the task id, state "COMPLETED" and the log path

    @AC-AGT-04b @integration @P2 @cov-happy-path
    Scenario: The heartbeat is stored as progress events
      Given the heartbeat interval is set to 1 second for tests
      And runners.fake is a fake CLI that writes a file every second for 3 seconds, writes a valid result.json and exits 0
      When "sentinel task run" is run for the docs task
      Then at least 2 "task.progress" events are stored for the task
      And each holds elapsed_seconds, output_bytes and changed_files
      And stderr shows lines like "[backend-docs] running 0m01s"

    @AC-AGT-04c @integration @P2 @cov-happy-path
    Scenario: The output log can be read while the task runs
      Given runners.fake is a fake CLI that prints "step 1", then waits 3 seconds, then finishes well
      When "sentinel task run" is run for the docs task in the background
      Then within 2 seconds output.log of the task contains "step 1"
      And the task state is RUNNING

  Rule: Process failures fail the task

    @AC-AGT-05a @integration @P1 @cov-errors
    Scenario: A non-zero exit fails the task
      Given runners.fake is a fake CLI that writes a valid result.json and exits 7
      When "sentinel task run" is run for the docs task
      Then it exits with code 1
      And the docs task is FAILED with error code "E_EXIT"
      And the "task.finished" event records exit code 7
      And the last 20 lines of the runner's stderr are printed

    @AC-AGT-05b @integration @P1 @cov-errors
    Scenario: A task that runs past its timeout is killed and fails
      Given the docs task has constraints.timeout_seconds 2
      And the heartbeat interval is set to 1 second for tests
      And runners.fake is a fake CLI that starts a child process and both sleep for 60 seconds
      When "sentinel task run" is run for the docs task
      Then it exits with code 1 within 15 seconds
      And the docs task is FAILED with error code "E_TIMEOUT"
      And neither the fake CLI nor its child process is still alive
      And stderr.log of the task ends with "timeout"

    @AC-AGT-05c @integration @P2 @cov-boundary
    Scenario: A task that finishes just before its timeout completes
      Given the docs task has constraints.timeout_seconds 5
      And the heartbeat interval is set to 1 second for tests
      And runners.fake is a fake CLI that sleeps 2 seconds, writes a valid result.json and exits 0
      When "sentinel task run" is run for the docs task
      Then it exits with code 0
      And the docs task is COMPLETED

    @AC-AGT-05d @integration @P1 @cov-errors
    Scenario: An invalid result from a successful process fails the task
      Given runners.fake is a fake CLI that prints "All done" and exits 0 without writing result.json
      When "sentinel task run" is run for the docs task
      Then it exits with code 1
      And the docs task is FAILED with error code "E_RESULT_SCHEMA"
      And output.log of the task contains "All done"

  Rule: The boundary check runs after every task and exits with 3

    @AC-AGT-06b @integration @P1 @cov-authz
    Scenario Outline: A boundary violation fails the task and is not retried
      Given runners.fake is a fake CLI that <action>, writes a valid result.json and exits 0
      When "sentinel task run" is run for the docs task
      Then it exits with code 3
      And the docs task is FAILED with error code "E_SCOPE"
      And one "task.scope_violation" event lists <listed> with kind <kind>
      And no retry task is created
      And the run state is NEEDS_HUMAN with reason naming "scope violation" and the docs task id
      And the changes are left in place
      Examples:
        | action                                        | listed                    | kind             |
        | writes frontend/stray.txt                     | "frontend/stray.txt"      | "repo_not_allowed" |
        | commits in backend                            | "backend: HEAD moved"     | "head_moved"     |
        | edits sentinel.config.yaml                    | "sentinel.config.yaml"    | "config_changed" |
        | edits a file under .claude/skills             | ".claude/skills"          | "config_changed" |
        | creates backend/.sentinel/runs/x.json         | "backend/.sentinel"       | "state_in_repo"  |

    @AC-AGT-06c @integration @P1 @cov-authz
    Scenario: A read-only task that writes anything is a violation
      Given a QUEUED "reviewer" task for "leave-balance" on repo "backend" with an empty write scope routed to "fake"
      And runners.fake is a fake CLI that writes backend/notes.txt, writes a valid result.json and exits 0
      When "sentinel task run" is run for the reviewer task
      Then it exits with code 3
      And the reviewer task is FAILED with error code "E_SCOPE"

    @AC-AGT-06d @integration @P2 @cov-errors
    Scenario: A scope violation wins over a non-zero exit
      Given runners.fake is a fake CLI that writes frontend/stray.txt and exits 1
      When "sentinel task run" is run for the docs task
      Then it exits with code 3
      And the docs task is FAILED with error code "E_SCOPE"

  Rule: The child process is isolated from Sentinel's own authority

    @AC-SEC-02a @integration @P1 @cov-perf-security
    Scenario: Secrets and the dashboard token are not passed to the runner
      Given sentinel.config.yaml sets policies.redact_env to ["DATABASE_URL"]
      And the environment holds SENTINEL_DASHBOARD_TOKEN "tok", DATABASE_URL "postgres://x" and HOME
      And runners.fake is a fake CLI that dumps its environment to output.log, writes a valid result.json and exits 0
      When "sentinel task run" is run for the docs task
      Then output.log contains HOME
      And output.log contains SENTINEL_TASK_ID with the docs task id
      And output.log contains neither SENTINEL_DASHBOARD_TOKEN nor DATABASE_URL

    @AC-AGT-06e @integration @P1 @cov-authz
    Scenario Outline: A task process cannot start or complete tasks
      Given another QUEUED "qa" task for "leave-balance"
      And runners.fake is a fake CLI that runs "<command>" for the qa task and records its exit code
      When "sentinel task run" is run for the docs task
      Then the recorded exit code is 5 with error "E_ACTOR"
      And the qa task is still QUEUED
      And one audit row records action "task_refused" with a reason naming the docs task id
      Examples:
        | command                 |
        | sentinel task run       |
        | sentinel task complete  |

  Rule: A missing runner blocks the run instead of failing the task

    @AC-AGT-05e @integration @P1 @cov-external-failure
    Scenario: The runner command is not installed and no fallback exists
      Given runners.fake has command "no-such-agent-cli" which is not on PATH
      And sentinel.config.yaml has no providers.fallback
      When "sentinel task run" is run for the docs task
      Then it exits with code 6
      And the docs task is still QUEUED
      And no retry is counted for the docs task
      And the run state is BLOCKED with reason "runner not installed: no-such-agent-cli"
      And the "run.state_changed" event names transition "R21"
      And the output names the fix "install no-such-agent-cli or change agents.docs"

    @AC-AGT-05f @integration @P1 @cov-external-failure
    Scenario: The run resumes once the runner is installed
      Given the run "leave-balance" is BLOCKED because runner "no-such-agent-cli" is not installed, from state EXECUTING
      And then "no-such-agent-cli" is placed on PATH
      When "sentinel next leave-balance --json" is run
      Then the run state is EXECUTING
      And the "run.state_changed" event names transition "R22"
      And the output is a "task" step for the docs task

    @AC-AGT-05g @integration @P2 @cov-external-failure
    Scenario: The fallback provider runs the task when the runner is missing
      Given runners.fake has command "no-such-agent-cli" which is not on PATH
      And sentinel.config.yaml sets providers.fallback to ["fake2"]
      And runners.fake2 is a fake CLI that writes backend/docs/leave.md and a valid result.json, then exits 0
      When "sentinel task run" is run for the docs task
      Then it exits with code 0
      And the docs task is COMPLETED with provider "fake2"
      And the "task.started" event records fallback from "fake" to "fake2"

    @AC-AGT-05h @integration @P2 @cov-external-failure
    Scenario Outline: A disabled or missing provider in the fallback list is skipped
      Given runners.fake has command "no-such-agent-cli" which is not on PATH
      And sentinel.config.yaml sets providers.fallback to <fallback> and providers.disabled to <disabled>
      When "sentinel task run" is run for the docs task
      Then the outcome is <outcome>
      Examples:
        | fallback          | disabled   | outcome                                         |
        | ["fake2"]         | ["fake2"]  | exit 6 and the run is BLOCKED                   |
        | ["gone", "fake2"] | []         | exit 0 and the task is COMPLETED on "fake2"     |
        | []                | []         | exit 6 and the run is BLOCKED                   |
