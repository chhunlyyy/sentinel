@REQ-OPS-04 @REQ-SEC-08 @REQ-OPS-03
Feature: Documentation and SPEC.md updates
  The user documents describe the version 2 flow, a migration guide covers 0.1 to 1.1, and
  docs/security.md states the residual risks plainly. SPEC.md records decision G-1 and the other
  1.1.0 scope decisions with LATER marks and gains DSH-07 and SEC-09. A docs check
  (tests/test_docs.py) keeps commands, links and versions true.

  Rule: User and migration guides

    @AC-OPS-04e @unit @P1 @cov-happy-path
    Scenario Outline: Each guide covers its topics
      When <file> is read
      Then it has sections on <topics>
      Examples:
        | file                     | topics                                                                                                                  |
        | docs/workflow.md         | the version 2 flow: run new, triage, spec review and approve, Gherkin review and approve, TDD cycles, verify, accept, report |
        | docs/workflow.md         | 0.1 runs (--legacy, --tier, --adhoc) and what still works for them                                                       |
        | docs/dashboard.md        | starting the dashboard, the session URL, screens, what is read only in 1.1.0 and the CLI command for each change         |
        | docs/config.md           | policies, tdd, verification, providers, agents, notifications and test and production globs                             |
        | docs/operations.md       | notifications, stats and analytics, audit export and verify, backup, verify and restore                                 |
        | docs/migration-1.1.md    | upgrading from 0.1.0b7: install, what changes, what is untouched, doctor, removed and changed commands, rollback        |
        | README.md                | the version 2 flow in brief, the dashboard, and links to every guide above                                               |

    @AC-OPS-04f @integration @P1 @cov-regression
    Scenario: Every command in the docs exists
      When every "sentinel ..." command in README.md, docs/*.md and skills/**/*.md is collected
      Then for each, "sentinel <subcommand> --help" exits 0 and every flag shown appears in that help
      And no doc names "sentinel submit"

    @AC-OPS-04g @unit @P2 @cov-regression
    Scenario: Every relative link resolves
      When every relative Markdown link and image in README.md and docs/ is checked
      Then each target file and heading anchor exists

    @AC-OPS-04h @unit @P2 @cov-regression
    Scenario: Version mentions are current
      When README.md, docs/ and skills/ are searched for "0.1.0b7" and "v0.1.0b7"
      Then they appear only in docs/migration-1.1.md and CHANGELOG.md
      And install pin examples use "v1.1.0"

    @AC-OPS-03a @unit @P1 @cov-happy-path
    Scenario Outline: The migration guide lists each behaviour change
      When docs/migration-1.1.md is read
      Then it explains "<change>" with what to do instead
      Examples:
        | change                                                                     |
        | sentinel run new creates a version 2 run unless --legacy, --tier or --adhoc |
        | sentinel submit is removed (use task run and task complete)                 |
        | run update and resume refuse version 2 runs                                 |
        | run finish on version 2 runs needs a terminal                               |
        | stage run is refused on version 2 runs                                      |
        | configs without auto_sync_push now mean off                                 |
        | sync-adapters adds deny rules for approve, accept and the token file        |
        | a registry .sentinel/sentinel.db is created and 0.1 runs are indexed        |

  Rule: Security document

    @AC-SEC-08a @unit @P1 @cov-perf-security
    Scenario Outline: docs/security.md states the residual risks plainly
      When docs/security.md is read
      Then it has a section "Residual risks" that says <statement>
      Examples:
        | statement                                                                                                           |
        | R1: an agent running as the same OS user can drive a pseudo-terminal and approve, or read server.json and use the dashboard |
        | R1: deny rules in generated agent configs are advisory; the terminal check and the recorded channel and identity are the controls |
        | R1: strong separation needs another OS user or a sandbox, which 1.1.0 does not provide                            |
        | R3: Sentinel cannot stop a provider CLI from running a command during a task; it detects file and git effects afterwards and does not undo them |
        | the scrubber is a safety net, not a guarantee, and backups and the registry hold unscrubbed request text           |
        | the audit hash chain detects edits by other tools but not a same-user attacker who rewrites the whole chain        |

    @AC-SEC-08b @unit @P2 @cov-regression
    Scenario: The security document matches the suite
      When the threat names of tests/security/manifest.json are compared with docs/security.md
      Then every threat is named in the document and every residual risk in the document has a check marked residual

    @AC-SEC-08c @unit @P2 @cov-regression
    Scenario: The old auto-push sentence is gone
      When docs/security.md is read
      Then it does not say auto_sync_push is on by default, and says version 2 runs never push by themselves

  Rule: SPEC.md scope marks

    @AC-OPS-04i @unit @P1 @cov-data-integrity
    Scenario Outline: Deferred dashboard writes are marked LATER per G-1
      When SPEC.md row "<id>" is read
      Then it marks "<part>" as LATER with the reference "G-1"
      Examples:
        | id     | part                                                                                    |
        | VIS-07 | creating a project, adding repos and configuring without editing files                  |
        | DSH-02 | the create project, add repos and configure steps of the first-run wizard               |
        | PRJ-03 | creating a project from the dashboard                                                   |
        | PRJ-04 | registering, editing, archiving and removing from the dashboard                         |
        | PRJ-05 | guided setup and advanced view                                                          |
        | REP-02 | adding a repo or cloning a remote from the dashboard                                    |
        | REP-05 | adding, editing, removing and reordering repos from the dashboard                       |
        | CFG-01 | dashboard forms for settings                                                            |
        | CFG-03 | validation of a dashboard save                                                          |
        | CFG-04 | saving YAML from the dashboard                                                          |
        | CFG-05 | restore from the dashboard                                                              |
        | CFG-07 | import and export of a project config                                                   |
        | INS-08 | the directory picker                                                                    |
        | PRV-01 | the providers screen                                                                    |
        | PRV-02 | changing providers from the dashboard                                                   |
        | PRV-03 | the connectivity test from the dashboard                                                |
        | AGT-08 | role assignment from the dashboard                                                      |
        | GIT-02 | publishing from the dashboard                                                           |
        | ART-02 | viewing and editing knowledge in the dashboard                                          |

    @AC-OPS-04j @unit @P1 @cov-data-integrity
    Scenario Outline: Other 1.1.0 scope decisions are recorded
      When SPEC.md row "<id>" is read
      Then it says "<text>"
      Examples:
        | id     | text                                                                              |
        | MON-02 | pause and request intervention are LATER (no paused state in 1.1.0)               |
        | TSK-01 | attachments and provider preference are LATER                                     |
        | TSK-04 | LATER                                                                             |
        | NOT-02 | desktop notifications use the browser Notification API only                       |

    @AC-OPS-04k @unit @P1 @cov-happy-path
    Scenario Outline: New requirement rows
      When SPEC.md is read
      Then it has row "<id>" in section "<section>" stating "<text>"
      Examples:
        | id     | section                    | text                                                                                                    |
        | DSH-07 | Dashboard                  | MUST: every screen meets WCAG 2.1 AA, works with the keyboard alone and labels every control             |
        | SEC-09 | Security and permissions   | MUST: content from runs, users and agents is rendered as text, never as HTML, and links in it are not followed |

    @AC-OPS-04l @unit @P2 @cov-data-integrity
    Scenario: Every MUST row is met or explained
      When the requirement ids of SPEC.md are compared with the AC tags of plan/v1.1/phase*/features and the LATER marks
      Then every MUST id is either tagged by at least one scenario or carries a LATER mark with a reference
      And the check prints the list it used, which is stored as release evidence
