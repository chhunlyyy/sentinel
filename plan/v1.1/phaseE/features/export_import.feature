@REQ-ART-03 @REQ-ART-01 @REQ-SEC-06 @REQ-SEC-07 @REQ-ORC-07
Feature: Run export and import
  "sentinel run export" writes a scrubbed bundle of one run: its registry rows, its run folder
  and its approved spec and features, with a manifest of sha256 hashes. "sentinel run import"
  checks every hash before it writes anything, and refuses a tampered bundle or a slug that
  already exists. Both are human actions.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repo "backend" is a git repo
    And a version 2 run "leave-balance" at tier 3 on repo "backend" in state COMPLETED with acceptance "accepted"
    And the run has tasks, cycles, evidence rows, findings, trace links, events and audit rows
    And backend/.env holds DB_PASSWORD "Pw-9f3kq2" and qa.db_clone in sentinel.config.yaml reads its connection from backend/.env

  Rule: Export writes a complete, scrubbed bundle

    @AC-ART-03a @integration @P1 @cov-happy-path
    Scenario: A human exports a run
      When a human runs "sentinel run export leave-balance" at an interactive terminal and confirms
      Then it exits with code 0
      And leave-balance.sentinel-run.tar.gz is written with file mode 0600
      And the bundle holds manifest.json, rows.json, run/ and shared/specs/leave-balance/spec.md and shared/specs/leave-balance/features/
      And manifest.json names format "sentinel-run-bundle-v1", the Sentinel version, the registry schema version, the slug and the sha256 and size of every other file in the bundle
      And rows.json holds the run's rows of runs, run_repos, artifacts, approvals, tasks, task_deps, cycles, evidence, findings, trace_links, events and audit, and its config snapshot
      And a "run_exported" audit row with the bundle sha256 is stored

    @AC-ART-03b @integration @P1 @cov-perf-security
    Scenario Outline: Secrets and QA data never enter the bundle
      Given <source> contains <text>
      When a human exports "leave-balance" at an interactive terminal
      Then no file in the bundle contains <secret>
      And "sentinel scrub --check" over the unpacked bundle exits 0
      Examples:
        | source                                                    | text                                   | secret                  |
        | the output.log of the qa task                             | "DB_PASSWORD=Pw-9f3kq2"                | "Pw-9f3kq2"             |
        | the result.json summary of the reviewer task              | "token=ghp_abcdef123456"               | "ghp_abcdef123456"      |
        | the brief.md of a tdd_green task                          | "jane.doe@corp-mail.com"               | "jane.doe@corp-mail.com" |
        | the payload of a "task.waiting" event                     | "mysql://qa:Pw-9f3kq2@10.0.0.5/leave"  | "Pw-9f3kq2"             |
        | .sentinel/runs/leave-balance/decisions.md                 | "AKIAABCDEFGHIJKLMNOP"                 | "AKIAABCDEFGHIJKLMNOP"  |
        | an evidence output file                                   | the workspace path                     | the workspace path      |

    @AC-ART-03c @integration @P1 @cov-perf-security
    Scenario: Files that hold secrets or QA data are left out entirely
      Given .sentinel/cache/qa/storage/leave_qa.sql, .sentinel/cache/runs/leave-balance/live.log and backend/.env exist
      When a human exports "leave-balance" at an interactive terminal
      Then the bundle holds no path under .sentinel/cache/, no file named .env or .env.*, no sentinel.db and no server.json
      And the bundle holds no file of another run

    @AC-ART-03d @integration @P2 @cov-boundary
    Scenario: Binary files are excluded and listed
      Given .sentinel/runs/leave-balance/tasks contains a PNG screenshot written by the qa task
      When a human exports "leave-balance" at an interactive terminal
      Then the PNG is not in the bundle
      And manifest.json lists its path under "excluded" with reason "binary"

    @AC-ART-03e @integration @P1 @cov-data-integrity
    Scenario: Scrubbed artifacts carry the hash of the scrubbed bytes
      Given the stored output file of an evidence row contains "/home/alice/work"
      When a human exports "leave-balance" at an interactive terminal
      Then the artifact row of that file in rows.json has the sha256 of the scrubbed file and "scrubbed" true with the original sha256
      And the manifest sha256 of that file matches its bytes in the bundle

    @AC-ART-03f @integration @P1 @cov-data-integrity
    Scenario: An approved spec that scrubbing would change stops the export
      Given the approved spec of "leave-balance" contains "AKIAABCDEFGHIJKLMNOP"
      When a human exports "leave-balance" at an interactive terminal
      Then it exits with code 5
      And the error is "E_POLICY" naming specs/leave-balance/spec.md and "approval hash would change"
      And no bundle file is left behind

  Rule: Export is a human action on a stable run

    @AC-ART-03g @integration @P1 @cov-authz
    Scenario Outline: Who may export
      When "sentinel run export leave-balance --yes" is run <how>
      Then it exits with code <code>
      And <result>
      Examples:
        | how                                              | code | result                                                         |
        | by a human at an interactive terminal            | 0    | the bundle is written without a confirmation question          |
        | with stdin not a terminal                        | 5    | the error is "E_NOT_TTY" and no bundle is written              |
        | inside a task process with SENTINEL_TASK_ID set  | 5    | the error is "E_ACTOR" and no bundle is written                |

    @AC-ART-03h @integration @P2 @cov-invalid-input
    Scenario Outline: Export requests that are refused
      Given <setup>
      When a human runs "sentinel run export <slug>" at an interactive terminal
      Then it exits with code 5
      And the error is "<error>"
      Examples:
        | setup                                                          | slug          | error          |
        | no run "no-such-run" exists                                    | no-such-run   | E_NOT_FOUND    |
        | a 0.1 run "old-fix" created with "sentinel run new old-fix --tier 2" | old-fix | E_TRANSITION   |
        | leave-balance.sentinel-run.tar.gz already exists               | leave-balance | E_PRECONDITION |

    @AC-ART-03i @integration @P1 @cov-concurrency
    Scenario: A run with a task or verification in progress is not exported
      Given a version 2 run "leave-form" in state EXECUTING with a RUNNING tdd_green task
      When a human runs "sentinel run export leave-form" at an interactive terminal
      Then it exits with code 5
      And the error is "E_PRECONDITION" naming the running task

  Rule: Import checks the whole bundle before it writes anything

    @AC-ART-03j @integration @P1 @cov-happy-path
    Scenario: A bundle is imported on another machine
      Given a bundle exported from "leave-balance"
      And a second workspace with a valid sentinel.config.yaml, repo "backend" and no run "leave-balance"
      When a human runs "sentinel run import leave-balance.sentinel-run.tar.gz" in the second workspace at an interactive terminal
      Then it exits with code 0
      And the second registry holds the run with state COMPLETED, acceptance "accepted" and every exported row
      And specs/leave-balance/spec.md and its features are in the second shared folder with the approved sha256
      And the specification and Gherkin approvals are still APPROVED when re-hashed
      And a "run.imported" event and a "run_imported" audit row with the bundle sha256 are stored
      And each imported event keeps its original id in its payload

    @AC-ART-03k @integration @P1 @cov-data-integrity
    Scenario Outline: A tampered bundle is refused
      Given a bundle exported from "leave-balance"
      And <tamper>
      When a human imports the bundle into a second workspace at an interactive terminal
      Then it exits with code 5
      And the error is "<error>" naming <what>
      And the second workspace has no row, no run folder and no shared spec for "leave-balance"
      Examples:
        | tamper                                                          | error        | what                          |
        | one byte of run/report.json was changed                         | E_INTEGRITY  | "run/report.json"             |
        | rows.json was edited to set acceptance_status "accepted" on a rejected run | E_INTEGRITY | "rows.json"            |
        | shared/specs/leave-balance/spec.md was replaced                 | E_INTEGRITY  | "spec.md"                     |
        | a file listed in manifest.json was removed                      | E_INTEGRITY  | the missing path              |
        | a file not listed in manifest.json was added                    | E_INTEGRITY  | the unlisted path             |
        | manifest.json was removed                                       | E_VALIDATION | "manifest.json"               |
        | manifest.json names format "sentinel-run-bundle-v9"             | E_VALIDATION | "format"                      |

    @AC-ART-03l @integration @P1 @cov-perf-security
    Scenario Outline: Unsafe archive entries are refused
      Given a bundle for "leave-balance" whose archive holds <entry>, listed in its manifest with a matching sha256
      When a human imports the bundle into a second workspace at an interactive terminal
      Then it exits with code 5
      And the error is "E_VALIDATION" naming that entry
      And no file was written outside a temporary folder, and that folder is removed
      Examples:
        | entry                                        |
        | a file "../../.bashrc"                       |
        | a file "/etc/cron.d/x"                       |
        | a symbolic link "run/link" to "/etc/passwd"  |
        | a hard link "run/hard" to "rows.json"        |

    @AC-ART-03m @integration @P1 @cov-data-integrity
    Scenario Outline: An existing slug is never overwritten
      Given a bundle exported from "leave-balance"
      And the second workspace already has <existing>
      When a human imports the bundle into the second workspace at an interactive terminal
      Then it exits with code 5
      And the error is "E_PRECONDITION" naming "slug exists" and <existing>
      And the existing data is unchanged
      Examples:
        | existing                                         |
        | a run row "leave-balance"                        |
        | a folder .sentinel/runs/leave-balance/           |
        | a folder .sentinel/shared/specs/leave-balance/   |

    @AC-ART-03n @integration @P1 @cov-authz
    Scenario Outline: Who may import
      Given a bundle exported from "leave-balance"
      When "sentinel run import leave-balance.sentinel-run.tar.gz" is run in a second workspace <how>
      Then it exits with code 5
      And the error is "<error>"
      And the second workspace has no row for "leave-balance"
      Examples:
        | how                                              | error     |
        | with stdin not a terminal                        | E_NOT_TTY |
        | inside a task process with SENTINEL_TASK_ID set  | E_ACTOR   |

    @AC-ART-03o @integration @P2 @cov-invalid-input
    Scenario: A bundle from a newer registry schema is refused
      Given a bundle whose manifest names a registry schema version higher than the second workspace supports
      When a human imports the bundle into the second workspace at an interactive terminal
      Then it exits with code 5
      And the error is "E_VALIDATION" with the fix "upgrade Sentinel"

    @AC-ART-03p @integration @P1 @cov-db-failure
    Scenario: A failed registry write leaves nothing behind
      Given a bundle exported from "leave-balance"
      And the second registry refuses writes after the first 10 rows of the import
      When a human imports the bundle into the second workspace at an interactive terminal
      Then it exits with code 1 and names the database error
      And the second workspace has no row, no run folder and no shared spec for "leave-balance"

    @AC-ART-03q @integration @P2 @cov-concurrency
    Scenario: Two imports of one bundle at the same time
      Given a bundle exported from "leave-balance"
      When two humans import it into the same second workspace at the same moment
      Then one import exits with code 0
      And the other exits with code 5 with error "E_PRECONDITION" naming "slug exists"
      And the second registry holds exactly one copy of each exported row

  Rule: An imported active run continues from its persisted state

    @AC-ORC-07g @integration @P1 @cov-happy-path
    Scenario: An imported run in progress resumes on the other machine
      Given a version 2 run "leave-form" in state EXECUTING with no RUNNING task, exported to a bundle
      And a second workspace whose repo "backend" contains the baseline commit of "leave-form"
      When a human imports the bundle into the second workspace at an interactive terminal
      Then the lock on slug "leave-form" is held by the second workspace
      And "sentinel next leave-form --json" in the second workspace returns the same step as it did in the first before export

    @AC-ORC-07h @integration @P2 @cov-external-failure
    Scenario: An imported run whose baseline commit is missing is blocked
      Given a version 2 run "leave-form" in state EXECUTING exported to a bundle
      And a second workspace whose repo "backend" does not contain the baseline commit of "leave-form"
      When a human imports the bundle and "sentinel next leave-form --json" is run in the second workspace
      Then the run state is BLOCKED with reason naming the missing commit and repo "backend"
      And the output JSON has kind "human"
