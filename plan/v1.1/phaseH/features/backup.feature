@REQ-OPS-05 @REQ-PER-05
Feature: Registry backup and restore check
  "sentinel backup" copies the workspace registry with the sqlite3 backup API into
  .sentinel/backups/ and checks the copy before it reports success. "sentinel backup --verify"
  checks an existing copy. "sentinel backup restore" puts a checked copy back, only from a
  terminal, only when nothing runs, and keeps the current file.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And workspace "digital-hr" with a registry holding 3 version 2 runs, 40 tasks, 300 events and 30 audit rows

  Rule: Backup

    @AC-OPS-05a @integration @P1 @cov-happy-path
    Scenario: A backup is a checked copy
      When "sentinel backup" is run
      Then .sentinel/backups/sentinel-<UTC time>.db exists with mode 0600 in a 0700 folder
      And PRAGMA integrity_check on the copy is "ok"
      And its schema_version, run, task, event and audit counts equal the source at the time of the copy
      And "sentinel audit verify" on the copy passes
      And the command prints JSON with path, sha256, size, schema_version and counts and exits 0

    @AC-OPS-05b @integration @P1 @cov-concurrency
    Scenario: Backup while a run writes
      Given a process appends events and task rows every 10 ms
      When "sentinel backup" is run
      Then it exits 0, the copy passes its checks, and the writer saw no "database is locked" error

    @AC-OPS-05c @integration @P2 @cov-happy-path
    Scenario: Backup to a chosen folder
      When "sentinel backup --out /tmp/x/bk" is run and /tmp/x/bk does not exist
      Then the folder is created with mode 0700 and the copy is written there

    @AC-OPS-05d @integration @P2 @cov-external-failure
    Scenario: The target cannot be written
      Given the target folder is on a file system with no free space
      When "sentinel backup --out <full folder>" is run
      Then it exits 1 with the reason and no partial file is left
      And the source registry is unchanged

    @AC-OPS-05e @integration @P2 @cov-empty-null
    Scenario: No registry yet
      Given workspace "fresh" has no .sentinel/sentinel.db
      When "sentinel backup" is run
      Then it exits 1 with "nothing to back up" and creates no registry

    @AC-OPS-05f @integration @P2 @cov-authz
    Scenario: A task process cannot back up or restore
      Given SENTINEL_TASK_ID is set in the environment
      When "sentinel backup" or "sentinel backup restore <file> --yes" is run
      Then each is refused with exit 5 "E_ACTOR"

    @AC-OPS-05g @integration @P2 @cov-happy-path
    Scenario: The backup is audited
      When "sentinel backup" is run
      Then an audit row with action "backup", the copy path and its sha256 is appended to the source registry after the copy

  Rule: Verify and restore

    @AC-OPS-05h @integration @P1 @cov-data-integrity
    Scenario Outline: Verify refuses a bad copy
      Given a backup file that <problem>
      When "sentinel backup --verify" is run on that file
      Then it exits 1 naming the problem
      Examples:
        | problem                                         |
        | has one byte changed in a table page            |
        | is truncated                                    |
        | is not a SQLite file                            |
        | has a schema_version newer than this Sentinel   |
        | has a broken audit chain                        |

    @AC-OPS-05i @integration @P1 @cov-happy-path
    Scenario: Restore from a terminal
      Given a checked backup B and no running task and no running server
      When a human at a pseudo-terminal runs "sentinel backup restore B" and types the first 8 characters of B's sha256
      Then the current registry is first copied to .sentinel/backups/pre-restore-<UTC time>.db
      And B is copied into place with the backup API and migrated to the current schema
      And an audit row "restore" naming B's sha256 is appended
      And "sentinel next leave-balance --json" answers from the restored state

    @AC-OPS-05j @security @P1 @cov-authz
    Scenario: Restore needs a terminal
      When "sentinel backup restore B" is run with stdin from a pipe
      Then it is refused with exit 5 "E_NOT_TTY" and the registry is unchanged

    @AC-OPS-05k @integration @P1 @cov-concurrency
    Scenario Outline: Restore refuses while something runs
      Given <condition>
      When a human runs "sentinel backup restore B" at a pseudo-terminal
      Then it is refused with exit 5 "E_LOCKED" naming <what> and the registry is unchanged
      Examples:
        | condition                                  | what                     |
        | task t-1 is RUNNING with a live process    | the task id              |
        | a Sentinel server is running               | the server pid and port  |

    @AC-OPS-05l @integration @P2 @cov-invalid-input
    Scenario: Restore refuses a copy of another workspace
      Given backup B was made in workspace "payroll"
      When it is restored into "digital-hr"
      Then it is refused with exit 1 naming both workspace registry ids

    @AC-OPS-05m @integration @P2 @cov-missing-fields
    Scenario Outline: Missing arguments
      When "<command>" is run
      Then it exits 2 with a usage message naming the missing argument and changes nothing
      Examples:
        | command                          |
        | sentinel backup restore          |
        | sentinel backup --verify         |
        | sentinel backup --out            |

    @AC-PER-05c @integration @P2 @cov-db-failure
    Scenario: A failed restore leaves the current registry in place
      Given the copy into place fails half way
      When the restore ends
      Then sentinel.db is byte-identical to before and the pre-restore copy is kept
