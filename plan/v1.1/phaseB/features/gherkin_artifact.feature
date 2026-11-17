@REQ-GHA-01 @REQ-GHA-02 @REQ-GHA-03 @REQ-GHA-04 @REQ-GHA-07
Feature: Gherkin artifact validation and coverage table
  The engine checks the Gherkin set against the approved specification
  and builds a coverage table before a human reviews it.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And a version 2 run "leave-balance" at tier 3 whose specification version 2 is approved
    And the approved specification lists REQ-1, REQ-2, "AC-1 (REQ-1)", "AC-2 (REQ-1)" and "AC-3 (REQ-2)"

  Rule: A valid Gherkin set opens the Gherkin review

    @AC-GHA-01a @unit @P1 @cov-happy-path
    Scenario: Valid feature files open the Gherkin review
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And specs/leave-balance/features/balance.feature has scenarios tagged "@AC-1 @unit @P1" and "@AC-2 @integration @P1"
      And specs/leave-balance/features/request_form.feature has a scenario tagged "@AC-3 @e2e @P2"
      When the test_designer task for "leave-balance" completes
      Then the run state is GHERKIN_REVIEW
      And artifact version 1 of kind "gherkin" is stored with the set hash of both files
      And a copy of both files is stored under .sentinel/runs/leave-balance/artifacts/
      And a Gherkin approval in state IN_REVIEW references version 1 and the set hash
      And a coverage table is stored with Gherkin version 1
      And the registry stores trace links AC-1, AC-2 and AC-3 to their scenarios

    @AC-GHA-01b @unit @P1 @cov-authz
    Scenario: Gherkin cannot be submitted before the specification is approved
      Given a version 2 run "fix-typo" in state SPECIFICATION_REVIEW at tier 1
      And specs/fix-typo/features/typo.feature exists and is valid
      When the engine is asked to open the Gherkin review for "fix-typo"
      Then the request is refused with error "E_TRANSITION"
      And the run state is still SPECIFICATION_REVIEW
      And no Gherkin artifact version exists for "fix-typo"

    @AC-GHA-01c @unit @P2 @cov-happy-path
    Scenario: Every supported construct parses
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And one feature file uses Feature, Rule, Background, Scenario, Scenario Outline, Examples, tags, Given, When, Then, And, But, a doc string and a data table
      And every criterion AC-1 to AC-3 has a tagged scenario
      When the test_designer task for "leave-balance" completes
      Then the run state is GHERKIN_REVIEW
      And there are no validation errors

  Rule: Every scenario carries a criterion, a type and a priority tag

    @AC-GHA-02a @unit @P1 @cov-invalid-input
    Scenario Outline: Scenario tags are checked
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And the only scenario for AC-1 in features/balance.feature is tagged "<tags>"
      And AC-2 and AC-3 have valid scenarios
      When the test_designer task for "leave-balance" completes
      Then the run state is <state>
      And the validation errors are <errors>
      Examples:
        | tags                                   | state                  | errors                                             |
        | @AC-1 @unit @P1                        | GHERKIN_REVIEW         | none                                               |
        | @AC-1 @security @regression @P3        | GHERKIN_REVIEW         | none                                               |
        | @unit @P1                              | SPECIFICATION_APPROVED | "features/balance.feature:7: scenario has no @AC tag" and "AC-1 has no scenario" |
        | @AC-1 @P1                              | SPECIFICATION_APPROVED | "features/balance.feature:7: scenario has no type tag" |
        | @AC-1 @unit                            | SPECIFICATION_APPROVED | "features/balance.feature:7: scenario has no priority tag" |
        | @AC-1 @unit @P4                        | SPECIFICATION_APPROVED | "features/balance.feature:7: unknown priority tag @P4" |
        | @AC-1 @unit @P1 @P2                    | SPECIFICATION_APPROVED | "features/balance.feature:7: more than one priority tag" |
        | @AC-1 @smoke @P1                       | SPECIFICATION_APPROVED | "features/balance.feature:7: scenario has no type tag" |

    @AC-GHA-02b @unit @P1 @cov-boundary
    Scenario Outline: Only the requirement tag is inherited from Feature or Rule
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And features/balance.feature has <feature_tags> on the Feature, <rule_tags> on the Rule and <scenario_tags> on its scenario for AC-1
      And AC-2 and AC-3 have valid scenarios
      When the test_designer task for "leave-balance" completes
      Then the run state is <state>
      Examples:
        | feature_tags | rule_tags | scenario_tags     | state                  |
        | @REQ-1       | none      | @AC-1 @unit @P1   | GHERKIN_REVIEW         |
        | none         | @REQ-1    | @AC-1 @unit @P1   | GHERKIN_REVIEW         |
        | @AC-1        | none      | @unit @P1         | SPECIFICATION_APPROVED |
        | @unit @P1    | none      | @AC-1             | SPECIFICATION_APPROVED |
        | none         | @unit     | @AC-1 @P1         | SPECIFICATION_APPROVED |

    @AC-GHA-02c @unit @P2 @cov-data-integrity
    Scenario: A criterion tagged under the wrong requirement is a warning
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And a scenario is tagged "@REQ-2 @AC-1 @unit @P1"
      And every criterion has a scenario
      When the test_designer task for "leave-balance" completes
      Then the run state is GHERKIN_REVIEW
      And the validation warnings include "AC-1 is not linked to REQ-2 in the approved specification"

  Rule: Tags trace to the approved specification and every criterion has a scenario

    @AC-GHA-03a @unit @P1 @cov-invalid-input
    Scenario Outline: A tag that points at nothing is refused
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And every criterion has a scenario
      And one more scenario is tagged "<tags>"
      When the test_designer task for "leave-balance" completes
      Then the run state is still SPECIFICATION_APPROVED
      And the validation errors include "<error>"
      Examples:
        | tags                  | error                                           |
        | @AC-9 @unit @P1       | AC-9 is not in approved specification version 2 |
        | @REQ-7 @AC-1 @unit @P1 | REQ-7 is not in approved specification version 2 |

    @AC-GHA-03b @unit @P1 @cov-missing-fields
    Scenario: A criterion with no scenario is refused
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And the feature files have scenarios for AC-1 and AC-2 only
      When the test_designer task for "leave-balance" completes
      Then the run state is still SPECIFICATION_APPROVED
      And the validation errors are exactly "AC-3 has no scenario"

    @AC-GHA-03c @unit @P1 @cov-invalid-input
    Scenario Outline: Gherkin outside the supported subset is refused with file and line
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And every criterion has a valid scenario
      And features/balance.feature has <problem>
      When the test_designer task for "leave-balance" completes
      Then the run state is still SPECIFICATION_APPROVED
      And the validation errors include "features/balance.feature:<line>: <error>"
      Examples:
        | problem                                          | line | error                                  |
        | a Given step on line 3 before any Scenario       | 3    | step outside a scenario                |
        | a Scenario Outline on line 9 with no Examples    | 9    | Scenario Outline has no Examples       |
        | an Examples table on line 14 with a header only  | 14   | Examples table has no rows             |
        | a "Scenario Template:" keyword on line 9         | 9    | unsupported keyword "Scenario Template" |
        | a "# language: fr" header on line 1              | 1    | only English Gherkin is supported      |
        | a second "Feature:" on line 20                   | 20   | more than one Feature in a file        |
        | a step on line 11 using a placeholder that no Examples column defines | 11 | placeholder has no Examples column |

    @AC-GHA-03d @unit @P1 @cov-empty-null
    Scenario Outline: An empty Gherkin set is refused
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And specs/leave-balance/features is <content>
      When the test_designer task for "leave-balance" completes
      Then the run state is still SPECIFICATION_APPROVED
      And the validation errors include "<error>"
      Examples:
        | content                                        | error                                          |
        | missing                                        | no feature files in specs/leave-balance/features |
        | an empty directory                             | no feature files in specs/leave-balance/features |
        | a directory holding only notes.md              | no feature files in specs/leave-balance/features |
        | one balance.feature file of 0 bytes            | features/balance.feature: file is empty         |
        | one balance.feature with a Feature line only   | features/balance.feature: Feature has no scenarios |

    @AC-GHA-03e @unit @P1 @cov-errors
    Scenario: Validation errors go into the next test_designer brief
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And the feature files have scenarios for AC-1 and AC-2 only
      When the test_designer task for "leave-balance" completes
      Then no Gherkin approval exists for "leave-balance"
      And no Gherkin artifact version is stored
      And the next test_designer brief contains "AC-3 has no scenario"

  Rule: The coverage table marks each category covered, not applicable or missing

    @AC-GHA-04a @unit @P1 @cov-happy-path
    Scenario: The table always lists the 15 categories
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And a valid Gherkin set
      When the test_designer task for "leave-balance" completes
      Then the coverage table has one row for each of happy-path, invalid-input, missing-fields, boundary, empty-null, authn, authz, data-integrity, duplicate, concurrency, errors, external-failure, db-failure, regression and perf-security
      And each row has the status covered, not applicable or missing

    @AC-GHA-04b @unit @P1 @cov-boundary
    Scenario Outline: The status of one category comes from tags and the spec
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And a valid Gherkin set where <gherkin>
      And the Edge cases section of the approved spec contains <declaration>
      When the test_designer task for "leave-balance" completes
      Then the coverage row "<category>" has status "<status>"
      And the coverage warnings are <warnings>
      Examples:
        | category    | gherkin                                          | declaration                                   | status                                  | warnings |
        | authz       | one scenario is tagged @cov-authz                | nothing                                       | covered by 1 scenario                   | none for authz |
        | authn       | no scenario is tagged @cov-authn                 | "- n/a @cov-authn: no login in this change"   | not applicable: no login in this change | none for authn |
        | concurrency | no scenario is tagged @cov-concurrency           | nothing                                       | missing                                 | "concurrency: missing" |
        | authn       | no scenario is tagged @cov-authn                 | "- n/a @cov-authn:" with no reason            | missing                                 | "authn: missing" and "n/a for authn has no reason" |
        | regression  | one scenario has the type tag @regression        | nothing                                       | covered by 1 scenario                   | none for regression |
        | happy-path  | two scenarios carry no @cov tag                  | nothing                                       | covered by 2 scenarios                  | none for happy-path |

    @AC-GHA-04c @unit @P1 @cov-data-integrity
    Scenario: One scenario per requirement is never reported as complete coverage
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And each of AC-1, AC-2 and AC-3 has exactly one scenario with no @cov tag
      And the approved spec declares no category not applicable
      When the test_designer task for "leave-balance" completes
      Then the coverage row "happy-path" is covered
      And the other 14 rows are missing
      And the coverage summary reads "coverage incomplete: 14 categories missing"
      And the word "complete" never appears without "incomplete"

    @AC-GHA-04d @unit @P1 @cov-errors
    Scenario: Missing categories are warnings and do not block the review
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And a valid Gherkin set with no scenario tagged @cov-concurrency
      When the test_designer task for "leave-balance" completes
      Then the run state is GHERKIN_REVIEW
      And "sentinel review leave-balance gherkin" shows the warning "concurrency: missing"

    @AC-GHA-04e @unit @P2 @cov-invalid-input
    Scenario: An unknown coverage tag is a warning
      Given the run "leave-balance" is in state SPECIFICATION_APPROVED
      And a valid Gherkin set where one scenario is tagged @cov-speed
      When the test_designer task for "leave-balance" completes
      Then the run state is GHERKIN_REVIEW
      And the coverage warnings include "unknown coverage tag @cov-speed"

  Rule: Docs-only runs skip the Gherkin gate

    @AC-GHA-07a @unit @P1 @cov-happy-path
    Scenario: A docs-only run goes from specification approval to execution
      Given a version 2 run "update-readme" of type docs in state SPECIFICATION_APPROVED at tier 1
      When the engine advances "update-readme"
      Then the run state is EXECUTING
      And the "run.state_changed" event names transition "R12d"
      And no Gherkin approval exists for "update-readme"

    @AC-GHA-07b @unit @P2 @cov-invalid-input
    Scenario: A Gherkin approval on a docs-only run is refused
      Given a version 2 run "update-readme" of type docs in state SPECIFICATION_APPROVED at tier 1
      When a human at a terminal runs "sentinel approve update-readme gherkin"
      Then it exits with code 5
      And the error is "E_PRECONDITION"
      And the message says docs-only runs have no Gherkin gate
