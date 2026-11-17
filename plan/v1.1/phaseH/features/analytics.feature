@REQ-ANL-01 @REQ-ANL-02
Feature: Local analytics from the registry
  One engine function computes metrics from the workspace registry (runs, tasks, approvals,
  cycles, evidence, findings, events) for a date range. "sentinel stats" keeps its 0.1 keys and
  adds a "v2" section with these metrics; GET /api/v1/reports/analytics returns the same
  function's answer and the dashboard Reports screen shows it. The function opens the registry
  read-only, never estimates a value, and never changes a gate or setting.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And workspace "digital-hr" with a valid sentinel.config.yaml
    And the registry fixture "analytics-small" with fixed times:
      | run   | type    | state     | created          | finished         | acceptance | spec versions | gherkin versions |
      | r-one | feature | COMPLETED | 2026-11-01 09:00 | 2026-11-01 13:00 | accepted   | 1             | 2                |
      | r-two | bug     | COMPLETED | 2026-11-02 09:00 | 2026-11-02 11:00 | rejected   | 2             | 1                |
      | r-thr | feature | FAILED    | 2026-11-03 09:00 | 2026-11-03 10:00 | pending    | 1             | 1                |
      | r-fou | feature | EXECUTING | 2026-11-04 09:00 |                  | pending    | 1             | 1                |

  Rule: Metrics

    @AC-ANL-01a @unit @P1 @cov-happy-path
    Scenario Outline: Each metric has a fixed definition
      When analytics are computed for 2026-11-01 to 2026-11-30
      Then metric "<metric>" equals <value>
      Examples:
        | metric                                      | value                                                   |
        | runs.total                                  | 4                                                       |
        | runs.by_state.COMPLETED                     | 2                                                       |
        | runs.by_type.feature                        | 3                                                       |
        | lead_time_seconds (finished runs)           | count 3, median 7200, p90 14400                         |
        | acceptance_rate                             | 0.5 (1 accepted of 2 decided)                           |
        | approval_wait_seconds.specification        | median of decided_at minus the approval.requested time  |
        | tasks.by_role.tdd_green.count               | the number of tdd_green task rows                       |
        | tasks.by_role.tdd_green.median_seconds      | the median of their seconds column                      |
        | retries.total                               | the number of task rows with retry_of set               |
        | provider_failure_rate.codex                 | E_PROVIDER failures of codex tasks / codex tasks finished |
        | tdd.cycles                                  | total, accepted, and rejected per phase (red, green, refactor) |
        | verification.pass_rate                      | passed verification evidence rows / all, per kind       |
        | verification.first_attempt_pass_rate        | runs whose first verification passed every check / runs verified |
        | rework.spec_revisions                       | 1 (runs with more than one specification version)       |
        | rework.gherkin_revisions                    | 1                                                       |
        | rework.changes_requested                    | approval.decided events with changes_requested          |
        | rework.findings_routed                      | finding.routed events                                   |

    @AC-ANL-01b @unit @P1 @cov-data-integrity
    Scenario: Metrics are recomputable from rows
      When analytics are computed twice from the same registry
      Then both answers are byte-identical JSON with sorted keys
      And every value can be recomputed by the SQL query named in tests/fixtures/analytics_queries.sql

    @AC-ANL-01c @unit @P1 @cov-happy-path
    Scenario: Cost by task, role and provider when every task reported it
      Given every task row of r-one has a cost
      When analytics are computed
      Then cost.by_task, cost.by_role and cost.by_provider are the sums of those values with partial false

    @AC-ANL-02d @unit @P1 @cov-empty-null
    Scenario: Partly reported cost is marked partial
      Given 6 of 10 task rows have a cost and 4 have null
      When analytics are computed
      Then cost.total is the sum of the 6 values with partial true, reported_tasks 6 and unreported_tasks 4
      And no cost is derived from tokens or a price table

    @AC-ANL-02e @unit @P1 @cov-empty-null
    Scenario Outline: Missing metrics are null with a reason
      Given <condition>
      When analytics are computed
      Then metric "<metric>" is null with reason "<reason>"
      Examples:
        | condition                                       | metric                       | reason                      |
        | no task row has a cost                          | cost.total                   | not reported                |
        | no run has a decided acceptance in the range    | acceptance_rate              | no decided runs             |
        | no run finished in the range                    | lead_time_seconds            | no finished runs            |
        | no approval was decided in the range            | approval_wait_seconds        | no decided approvals        |
        | no task used provider gemini                    | provider_failure_rate.gemini | no tasks for this provider  |

    @AC-ANL-02f @unit @P2 @cov-empty-null
    Scenario: An empty range
      When analytics are computed for 2025-01-01 to 2025-01-31
      Then runs.total is 0 and every rate and duration is null with reason "no runs in range"

    @AC-ANL-01d @unit @P2 @cov-boundary
    Scenario Outline: Date range bounds
      When analytics are computed with from "<from>" and to "<to>"
      Then the runs counted are <runs>
      Examples:
        | from       | to         | runs                       |
        | 2026-11-02 | 2026-11-02 | r-two                      |
        | 2026-11-01 | 2026-11-03 | r-one, r-two, r-thr        |
        | 2026-11-04 |            | r-fou                      |
        |            | 2026-11-01 | r-one                      |

    @AC-ANL-01e @unit @P2 @cov-boundary
    Scenario: Unfinished runs count but give no lead time
      When analytics are computed
      Then r-fou is counted in runs.total and runs.by_state.EXECUTING
      And it is not part of lead_time_seconds, acceptance_rate or verification rates

  Rule: sentinel stats

    @AC-ANL-01f @integration @P1 @cov-regression
    Scenario: The 0.1 keys are unchanged
      Given a 0.1 run "old-fix" with state.json and metrics.json
      When "sentinel stats" is run
      Then the output has the keys runs, by_tier, escalated_runs, outcomes, avg_rounds, stage_isolation, tokens_by_stage and seconds_by_stage with the same values as 0.1.0b7
      And it has a new key "v2" holding the analytics answer, which counts no 0.1 run

    @AC-ANL-01g @integration @P2 @cov-happy-path
    Scenario: Filters and Markdown output
      When "sentinel stats --from 2026-11-01 --to 2026-11-02 --format md" is run
      Then it prints a Markdown table of the v2 metrics for that range, with "not reported" for null values

    @AC-ANL-01h @integration @P2 @cov-invalid-input
    Scenario Outline: Bad arguments
      When "sentinel stats <args>" is run
      Then it exits 2 with a message naming the argument
      Examples:
        | args                                  |
        | --from 2026-13-01                     |
        | --from 2026-11-05 --to 2026-11-01     |
        | --format xml                          |

    @AC-ANL-01i @integration @P2 @cov-empty-null
    Scenario: A workspace without a registry
      Given workspace "fresh" has no .sentinel/sentinel.db
      When "sentinel stats" is run
      Then it exits 0, v2 is null with reason "no registry"
      And no .sentinel/sentinel.db is created

    @AC-ANL-01j @integration @P2 @cov-db-failure
    Scenario: The registry cannot be read
      Given .sentinel/sentinel.db is not a database
      When "sentinel stats" is run
      Then it exits 1 with "E_MIGRATION" or "E_INTEGRITY" and the path, and the file is unchanged

    @AC-ANL-01k @integration @P2 @cov-concurrency
    Scenario: Stats while runs write
      Given a process writes 200 task rows and events per second to the registry
      When "sentinel stats" runs 20 times meanwhile
      Then every run exits 0 with an answer consistent with one snapshot (task counts equal the sum per role)
      And no writer gets "database is locked"

    @AC-ANL-01l @unit @P2 @cov-authz
    Scenario: Analytics never write
      When analytics are computed through the CLI and the API
      Then the registry is opened with mode=ro and its sha256 is unchanged
      And no config file, policy or limit is changed

    @AC-ANL-01m @performance @P3 @cov-perf-security
    Scenario: 1000 runs within 2 seconds
      Given a registry with 1000 runs, 20000 tasks and 200000 events
      When analytics are computed for all time
      Then the answer is ready within 2 seconds on the CI machine

  Rule: Dashboard reports

    @AC-ANL-01n @integration @P1 @cov-happy-path
    Scenario: The analytics route returns the CLI answer
      Given a running server with project "digital-hr"
      When GET /api/v1/reports/analytics?project=digital-hr&from=2026-11-01&to=2026-11-30 is called with a valid session
      Then the body equals the v2 section of "sentinel stats --from 2026-11-01 --to 2026-11-30"

    @AC-ANL-01o @security @P2 @cov-invalid-input
    Scenario Outline: Analytics route validation
      When GET /api/v1/reports/analytics?<query> is called with a valid session
      Then the answer is <status> "<code>"
      Examples:
        | query                                        | status | code         |
        | project=nope                                 | 404    | E_NOT_FOUND  |
        | project=digital-hr&from=yesterday            | 400    | E_VALIDATION |
        | project=digital-hr&from=2026-11-05&to=2026-11-01 | 400 | E_VALIDATION |
        | project=digital-hr&sql=select                | 400    | E_VALIDATION |

    @AC-ANL-01p @e2e @P2 @cov-happy-path
    Scenario: The Reports screen
      Given the built dashboard is served by the fake API server with fixture "analytics-small"
      When the user opens Reports and picks the range 2026-11-01 to 2026-11-30
      Then tables show runs, lead time, acceptance rate, approval wait, retries, provider failure rate, TDD cycles, verification pass rate, rework and cost
      And every null value shows "Not reported" with its reason, never 0

    @AC-ANL-02g @e2e @P2 @cov-empty-null
    Scenario: Partial cost is labelled on screen
      Given the analytics answer has cost.total partial true with 4 unreported tasks
      When the user opens Reports
      Then the cost total is labelled "partial: 4 tasks did not report cost"
