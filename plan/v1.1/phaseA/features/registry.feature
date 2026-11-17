@REQ-PER-01 @REQ-PER-02 @REQ-PER-03 @REQ-PER-04 @REQ-PER-05
Feature: Run registry in SQLite
  Run state lives in .sentinel/sentinel.db. state.json is a view for older skills.

  Rule: The registry is created and migrated safely

    @AC-PER-01a @integration @P1
    Scenario: The first command creates the registry
      Given a workspace with no .sentinel/sentinel.db
      When "sentinel run new leave-balance" is run
      Then .sentinel/sentinel.db exists
      And its journal mode is WAL
      And its schema version is the latest migration number

    @AC-PER-05a @unit @P1 @cov-db-failure
    Scenario: A failing migration leaves the database untouched
      Given a registry at schema version 1 holding run "old-run"
      And migration 2 fails halfway
      When the registry is opened
      Then opening fails with error "E_MIGRATION"
      And the registry is still at schema version 1
      And run "old-run" is still readable
      And a backup file "sentinel.db.bak-1" exists

    @AC-PER-05b @unit @P2 @cov-regression
    Scenario: Opening an up-to-date registry runs no migration
      Given a registry at the latest schema version
      When the registry is opened twice
      Then no backup file is created

  Rule: Events and audit records are append-only

    @AC-PER-03a @unit @P1 @cov-data-integrity
    Scenario: Events cannot be changed through the registry API
      Given a registry with one stored event
      When code tries to update or delete that event through the registry
      Then the attempt fails
      And the event is unchanged

  Rule: Legacy runs are indexed, not rewritten

    @AC-ORC-08a @integration @P1 @cov-regression
    Scenario: A 0.1 run is indexed on first open
      Given a workspace with a 0.1 run "old-run" whose state.json has no schema_version
      When the registry is opened for the first time
      Then the registry lists run "old-run" with workflow version "0.1"
      And the file state.json of "old-run" is byte-for-byte unchanged

    @AC-ORC-08b @integration @P1 @cov-regression
    Scenario: A legacy run keeps the 0.1 commands
      Given a workspace with a 0.1 run "old-run" at tier 2
      When "sentinel run update old-run --stage repro" is run
      And "sentinel resume old-run" is run
      Then resume names "coder" as the next stage

    @AC-ORC-08c @integration @P1 @cov-invalid-input
    Scenario: run update is refused on a version 2 run
      Given a version 2 run "leave-balance" in state CREATED
      When "sentinel run update leave-balance --stage coder" is run
      Then it exits with code 5
      And the error is "E_TRANSITION"

  Rule: state.json is kept as a view

    @AC-PER-04a @integration @P1 @cov-regression
    Scenario: Every transition rewrites the state.json view
      Given a version 2 run "leave-balance" in state CREATED
      When the orchestrator submits triage factors for "leave-balance"
      Then runs/leave-balance/state.json has schema_version 2
      And it has state "TRIAGED", the tier, the baseline SHAs and the stage list
      And its execution_status and acceptance_status match the registry

    @AC-PER-02a @integration @P2
    Scenario: A new run stores its config snapshot and baseline commits
      Given a workspace with repos "backend" and "frontend" at known commits
      When "sentinel run new leave-balance" is run
      Then the registry stores both baseline commits for "leave-balance"
      And the run references a stored config version whose hash matches sentinel.config.yaml

  Rule: Concurrent writers do not corrupt state

    @AC-C-36a @integration @P2 @cov-concurrency
    Scenario: Two processes transition the same run at once
      Given a version 2 run "leave-balance" in state CREATED
      When two processes submit triage factors for "leave-balance" at the same time
      Then exactly one succeeds
      And the other is refused with error "E_TRANSITION"
      And exactly one "run.state_changed" event exists for CREATED to TRIAGED
