@REQ-SPA-01 @REQ-SPA-02 @REQ-SPA-03
Feature: Specification artifact validation
  The engine checks the specification before a human sees it.
  Only a valid specification opens the specification review.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder

  Rule: A valid specification opens the review as a new stored version

    @AC-SPA-01a @unit @P1 @cov-happy-path
    Scenario: A valid tier 3 specification opens the specification review
      Given a version 2 run "leave-balance" in state PLANNED at tier 3
      And specs/leave-balance/spec.md has all 16 full sections and front matter run "leave-balance", version 1, tier 3
      When the specifier task for "leave-balance" completes
      Then the run state is SPECIFICATION_REVIEW
      And artifact version 1 of kind "spec" is stored with the sha256 of specs/leave-balance/spec.md
      And a copy of version 1 is stored under .sentinel/runs/leave-balance/artifacts/
      And a specification approval in state IN_REVIEW references version 1 and its sha256
      And one "artifact.version_created" and one "approval.requested" event are stored

    @AC-SPA-01b @unit @P1 @cov-missing-fields
    Scenario: A specification outside the shared folder is not found
      Given a version 2 run "leave-balance" in state PLANNED at tier 3
      And the specifier wrote .sentinel/runs/leave-balance/spec.md instead of specs/leave-balance/spec.md
      When the specifier task for "leave-balance" completes
      Then the run state is still PLANNED
      And the validation errors include "specs/leave-balance/spec.md not found"

  Rule: Required sections depend on the tier and the task type

    @AC-SPA-02a @unit @P1 @cov-boundary
    Scenario Outline: The section set follows the tier
      Given a version 2 run "leave-balance" of type <type> in state PLANNED at tier <tier>
      And specs/leave-balance/spec.md has exactly the <set> sections, each with content
      When the specifier task for "leave-balance" completes
      Then the run state is <state>
      And the validation errors are <errors>
      Examples:
        | type    | tier | set       | state                | errors                                   |
        | feature | 1    | lite      | SPECIFICATION_REVIEW | none                                     |
        | feature | 2    | lite      | SPECIFICATION_REVIEW | none                                     |
        | feature | 3    | lite      | PLANNED              | missing "Objectives" and 7 other sections |
        | feature | 3    | full      | SPECIFICATION_REVIEW | none                                     |
        | feature | 4    | full      | SPECIFICATION_REVIEW | none                                     |
        | feature | 1    | docs-only | PLANNED              | missing "Out of scope" and 5 other sections |
        | docs    | 1    | docs-only | SPECIFICATION_REVIEW | none                                     |
        | docs    | 4    | docs-only | SPECIFICATION_REVIEW | none                                     |

    @AC-SPA-02b @unit @P1 @cov-missing-fields
    Scenario Outline: A missing required section is reported by name
      Given a version 2 run "leave-balance" of type <type> in state PLANNED at tier <tier>
      And specs/leave-balance/spec.md has every required section except "<section>"
      When the specifier task for "leave-balance" completes
      Then the run state is still PLANNED
      And the validation errors are exactly "missing section: <section>"
      Examples:
        | type    | tier | section               |
        | feature | 1    | Acceptance criteria   |
        | feature | 2    | Security considerations |
        | feature | 3    | Database changes      |
        | feature | 4    | Risks and assumptions |
        | docs    | 2    | Expected deliverables |

    @AC-SPA-02c @unit @P1 @cov-invalid-input
    Scenario Outline: A full-spec section marked not applicable needs a reason
      Given a version 2 run "leave-balance" in state PLANNED at tier 3
      And specs/leave-balance/spec.md has all 16 full sections
      And the "Database changes" section body is "<body>"
      When the specifier task for "leave-balance" completes
      Then the run state is <state>
      And the validation errors are <errors>
      Examples:
        | body                                          | state                | errors                                          |
        | Not applicable: no schema change in this task. | SPECIFICATION_REVIEW | none                                            |
        | Not applicable.                               | PLANNED              | "Database changes: not applicable needs a reason" |
        | not applicable                                | PLANNED              | "Database changes: not applicable needs a reason" |

    @AC-SPA-02d @unit @P1 @cov-empty-null
    Scenario Outline: Empty content is refused
      Given a version 2 run "leave-balance" in state PLANNED at tier 1
      And specs/leave-balance/spec.md is <content>
      When the specifier task for "leave-balance" completes
      Then the run state is still PLANNED
      And the validation errors include <error>
      Examples:
        | content                                               | error                                  |
        | a file of 0 bytes                                     | "missing front matter" and all 8 lite sections |
        | a file holding only spaces and newlines               | "missing front matter" and all 8 lite sections |
        | complete except the "Scope" heading has no text under it | "Scope: section is empty"            |
        | complete except "Edge cases" holds only an HTML comment | "Edge cases: section is empty"       |

    @AC-SPA-02e @unit @P2 @cov-invalid-input
    Scenario Outline: Only second-level headings count as sections
      Given a version 2 run "leave-balance" in state PLANNED at tier 1
      And specs/leave-balance/spec.md has every lite section, with the scope heading written as "<heading>"
      When the specifier task for "leave-balance" completes
      Then the run state is <state>
      Examples:
        | heading     | state                |
        | ## Scope    | SPECIFICATION_REVIEW |
        | ## scope    | SPECIFICATION_REVIEW |
        | ##  Scope   | SPECIFICATION_REVIEW |
        | ### Scope   | PLANNED              |
        | # Scope     | PLANNED              |
        | **Scope**   | PLANNED              |

    @AC-SPA-02f @unit @P2 @cov-happy-path
    Scenario: Extra sections are allowed
      Given a version 2 run "leave-balance" in state PLANNED at tier 1
      And specs/leave-balance/spec.md has every lite section and an extra section "Glossary"
      When the specifier task for "leave-balance" completes
      Then the run state is SPECIFICATION_REVIEW
      And there are no validation warnings

    @AC-SPA-02g @unit @P1 @cov-invalid-input
    Scenario Outline: The front matter must match the run
      Given a version 2 run "leave-balance" in state PLANNED at tier 3
      And specs/leave-balance/spec.md has all 16 full sections and front matter <front_matter>
      When the specifier task for "leave-balance" completes
      Then the run state is still PLANNED
      And the validation errors include "<error>"
      Examples:
        | front_matter                        | error                                   |
        | missing                             | missing front matter                    |
        | run "other-run", version 1, tier 3  | front matter run "other-run" does not match "leave-balance" |
        | run "leave-balance", version 1, tier 2 | front matter tier 2 does not match run tier 3 |
        | run "leave-balance", version 1, tier "high" | front matter tier must be an integer from 1 to 4 |
        | run "leave-balance", tier 3         | front matter version is missing         |
        | not valid YAML                      | front matter is not valid YAML          |

  Rule: Requirement and criterion IDs are unique and every criterion is linked

    @AC-SPA-03a @unit @P1 @cov-happy-path
    Scenario: Linked IDs are accepted and stored as trace links
      Given a version 2 run "leave-balance" in state PLANNED at tier 1
      And the spec lists requirements REQ-1 and REQ-2
      And the spec lists criteria "AC-1 (REQ-1)" and "AC-2 (REQ-1, REQ-2)"
      When the specifier task for "leave-balance" completes
      Then the run state is SPECIFICATION_REVIEW
      And the registry stores trace links REQ-1 to AC-1, REQ-1 to AC-2 and REQ-2 to AC-2

    @AC-SPA-03b @unit @P1 @cov-invalid-input
    Scenario Outline: Broken IDs are refused
      Given a version 2 run "leave-balance" in state PLANNED at tier 1
      And the spec lists requirements <requirements>
      And the spec lists criteria <criteria>
      When the specifier task for "leave-balance" completes
      Then the run state is still PLANNED
      And the validation errors include "<error>"
      Examples:
        | requirements        | criteria                         | error                              |
        | REQ-1, REQ-2, REQ-2 | AC-1 (REQ-1), AC-2 (REQ-2)       | duplicate id REQ-2                 |
        | REQ-1               | AC-1 (REQ-1), AC-1 (REQ-1)       | duplicate id AC-1                  |
        | REQ-1               | AC-1                             | AC-1 is not linked to a requirement |
        | REQ-1               | AC-1 (REQ-9)                     | AC-1 links unknown REQ-9           |
        | REQ-one             | AC-1 (REQ-one)                   | invalid requirement id "REQ-one"   |
        | none                | AC-1 (REQ-1)                     | no requirements found              |
        | REQ-1               | none                             | no acceptance criteria found       |

    @AC-SPA-03c @unit @P2 @cov-boundary
    Scenario: A requirement without a criterion is a warning, not an error
      Given a version 2 run "leave-balance" in state PLANNED at tier 1
      And the spec lists requirements REQ-1 and REQ-2
      And the spec lists criteria "AC-1 (REQ-1)"
      When the specifier task for "leave-balance" completes
      Then the run state is SPECIFICATION_REVIEW
      And the validation warnings are exactly "REQ-2 has no acceptance criterion"

  Rule: An invalid specification goes back to the specifier

    @AC-SPA-03d @unit @P1 @cov-errors
    Scenario: Validation errors go into the next specifier brief
      Given a version 2 run "leave-balance" in state PLANNED at tier 1
      And specs/leave-balance/spec.md is missing the "Edge cases" section
      When the specifier task for "leave-balance" completes
      Then the run state is still PLANNED
      And no specification approval exists for "leave-balance"
      And no spec artifact version is stored
      And the next specifier brief contains "missing section: Edge cases"

    @AC-SPA-03e @unit @P2 @cov-errors
    Scenario: Repeated invalid specifications stop at the retry cap
      Given a version 2 run "leave-balance" in state PLANNED at tier 1
      And the config allows 2 specifier retries
      When the specifier task completes with an invalid specification 3 times
      Then the run state is NEEDS_HUMAN
      And the recorded reason is "specification invalid after 2 retries"

  Rule: Legacy runs keep the 0.1 specification flow

    @AC-SPA-01c @integration @P1 @cov-regression
    Scenario: A 0.1 run with a free-form spec is not validated
      Given a workspace with a 0.1 run "old-run" at tier 2
      And specs/old-run/spec.md has no front matter and none of the required sections
      When "sentinel spec set old-run --status draft" is run
      Then it exits with code 0
      And the spec index lists "old-run" with status "draft"
      And no spec artifact version and no approval exist for "old-run"
      And the file state.json of "old-run" has no schema_version
