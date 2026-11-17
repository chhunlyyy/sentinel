@REQ-C-35 @REQ-OPS-03
Feature: Publishing to the shared repo is off by default
  New workspaces never push to the shared repo without a human asking.

  @AC-C-35a @integration @P1 @cov-happy-path
  Scenario: A new config turns automatic publishing off
    When "sentinel init --non-interactive --shape single --shared-repo <bare repo>" is run
    Then sentinel.config.yaml has state.auto_sync_push set to false

  @AC-C-35b @integration @P1 @cov-regression
  Scenario: An existing config keeps its own setting
    Given a workspace whose config sets state.auto_sync_push to true
    When "sentinel doctor" is run
    Then the config still sets state.auto_sync_push to true
    And doctor prints a note that automatic publishing is on

  @AC-C-35c @integration @P1 @cov-authz
  Scenario: Automatic push does nothing under the new default
    Given a new workspace created by sentinel init with a shared repo
    And a finished run "leave-balance"
    When "sentinel sync push leave-balance --auto" is run
    Then nothing is pushed to the shared repo
    And the output says automatic publishing is off
