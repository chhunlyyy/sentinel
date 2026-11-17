@REQ-PRJ-02 @REQ-PRJ-04 @REQ-REP-03 @REQ-REP-04 @REQ-CFG-01 @REQ-CFG-02 @REQ-CFG-05 @REQ-CFG-06 @REQ-CFG-08 @REQ-SEC-07
Feature: Projects, repositories and the configuration center
  Projects, repositories and configuration are shown read only in 1.1.0. sentinel.config.yaml
  stays the source of truth; the screens say which command or file changes a value. The
  configuration center shows the effective values with their sources, the saved versions from
  config_versions and the diff between two versions.

  Background:
    Given the built dashboard is served by the fake API server on 127.0.0.1 with fixture set "two-projects"
    And the browser holds a valid session cookie

  Rule: Projects

    @AC-PRJ-02a @e2e @P1 @cov-happy-path
    Scenario: The project list
      When the user opens "Projects"
      Then a table lists "digital-hr" and "payroll" with name, path, status and the number of active runs
      And each name links to the project page

    @AC-PRJ-02b @e2e @P1 @cov-external-failure
    Scenario: An unavailable project shows its reason
      Given GET /api/v1/projects lists "payroll" with status "unavailable" and reason "workspace missing"
      When the user opens "Projects"
      Then "payroll" shows "Unavailable: workspace missing"
      And opening "payroll" shows the reason and no runs, repositories or readiness panels

    @AC-PRJ-02c @e2e @P2 @cov-empty-null
    Scenario: No project registered
      Given GET /api/v1/projects answers items []
      When the user opens "Projects"
      Then the page says "No project registered" and shows "Run sentinel dashboard inside a workspace to register it"

    @AC-PRJ-04a @e2e @P2 @cov-authz
    Scenario: The dashboard offers no project or repository change in 1.1.0
      When the user opens project "digital-hr" and its "Repositories" tab
      Then there is no control to create, register, edit, archive or remove a project
      And there is no control to add, edit, remove or reorder a repository
      And the page names "sentinel.config.yaml" as the place to change repositories

    @AC-PRJ-02d @e2e @P2 @cov-happy-path
    Scenario: The project page
      When the user opens project "digital-hr"
      Then it shows the tabs "Overview", "Repositories", "Configuration", "Runs" and "Audit"
      And "Overview" shows the readiness panel and the latest 5 runs

  Rule: Repositories

    @AC-REP-03b @e2e @P1 @cov-happy-path
    Scenario: The repository table
      When the user opens the "Repositories" tab of "digital-hr"
      Then each repository shows id, path, remote, default branch, current branch, role, profile, its commands and its guidelines file
      And the repositories are listed in the order the API returned them, labelled "Cross-repo order"

    @AC-REP-04b @e2e @P2 @cov-errors
    Scenario: Repository problems are shown with their fix
      Given repo "frontend" has validation item "branch" failed with fix "git fetch origin main"
      When the user opens the "Repositories" tab of "digital-hr"
      Then repo "frontend" shows "Branch: Failed" and the fix "git fetch origin main"
      And repo "backend" shows every validation item as "Passed"

  Rule: Configuration center, read only

    @AC-CFG-06b @e2e @P1 @cov-happy-path
    Scenario: Effective values grouped by category with their source
      When the user opens the "Configuration" tab of "digital-hr"
      Then the values are grouped under "Project", "Repositories", "Providers", "Agents", "Workflow and policies", "TDD", "Verification" and "Limits"
      And each value shows its key path and a source label "Default", "Global", "Project" or "Repo backend" as text

    @AC-CFG-02a @e2e @P2 @cov-boundary
    Scenario: An overridden value shows what it overrides
      Given limits.task_timeout is 1200 from "project" and overrides 900 from "global"
      When the user opens the "Configuration" tab of "digital-hr"
      Then limits.task_timeout shows 1200 with source "Project"
      And expanding it shows "Overrides Global: 900"

    @AC-CFG-01a @e2e @P1 @cov-authz
    Scenario: The configuration cannot be edited from the dashboard in 1.1.0
      When the user opens the "Configuration" tab of "digital-hr"
      Then no value is shown in an editable input
      And there is no "Save", "Restore", "Import" or "Export" control
      And the tab says "Edit sentinel.config.yaml; the change appears here after Reload"
      And no PUT or POST request is sent from the tab

    @AC-CFG-05d @e2e @P1 @cov-happy-path
    Scenario: History and diff between versions
      Given the configuration history has versions 1, 2 and 3
      When the user opens "History", selects versions 1 and 3 and presses "Compare"
      Then GET /api/v1/projects/digital-hr/configuration/diff?a=1&b=3 is called
      And the diff is shown with added and removed lines marked by "+" and "-" signs as well as colour
      And each version shows its sha256 prefix, author, channel, time and comment

    @AC-CFG-05e @e2e @P3 @cov-empty-null
    Scenario: A project with no saved versions
      Given the configuration history is empty
      When the user opens "History"
      Then the page says "No saved versions yet" and the "Compare" button is disabled

    @AC-CFG-08e @e2e @P2 @cov-data-integrity
    Scenario: A run shows the configuration it uses
      Given run "leave-balance" started with config snapshot version 2 and the project configuration is now version 3
      When the user opens run "leave-balance"
      Then the run header shows "Config snapshot 2" with its sha256 prefix
      And a note says "The project configuration changed after this run started. This run keeps using snapshot 2." with a link to the diff of versions 2 and 3

  Rule: Audit

    @AC-SEC-07b @e2e @P2 @cov-happy-path
    Scenario: The audit tab
      When the user opens the "Audit" tab of "digital-hr"
      Then it lists actor, channel, action, target, before and after hash prefix, reason and time, newest first
      And a "Load more" button follows the next cursor until it is null
