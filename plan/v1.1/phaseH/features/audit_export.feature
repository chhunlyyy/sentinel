@REQ-SEC-07
Feature: Audit export and append-only proof
  The audit table is append-only. A migration adds triggers that refuse UPDATE and DELETE and a
  hash chain: each row stores row_sha (sha256 of its canonical JSON) and chain_sha
  (sha256 of the previous chain_sha and its row_sha), written in the same transaction as the row.
  "sentinel audit export" writes a scrubbed JSON Lines or CSV file with filters, and
  "sentinel audit verify" checks the chain in the registry or in an exported file.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And workspace "digital-hr" whose audit table holds 30 rows from approvals, acceptance, cancel, resume and retry with channels tty and dashboard

  Rule: Append-only

    @AC-SEC-07c @integration @P1 @cov-data-integrity
    Scenario Outline: The registry refuses changes to audit rows
      When a connection runs "<statement>" on the registry
      Then it fails with "audit is append-only" and the table is unchanged
      Examples:
        | statement                                      |
        | UPDATE audit SET actor = 'agent' WHERE id = 3  |
        | DELETE FROM audit WHERE id = 3                 |
        | DELETE FROM audit                              |

    @AC-SEC-07d @unit @P1 @cov-data-integrity
    Scenario: Each new row extends the chain
      When the engine records an approval
      Then the new row's chain_sha is sha256 of the previous chain_sha and its row_sha
      And row and chain are written in the same transaction as the approval

    @AC-SEC-07e @integration @P1 @cov-regression
    Scenario: Existing rows are chained by the migration
      Given a registry at the schema version before Phase H with 30 audit rows
      When it is opened by Phase H code
      Then a backup sentinel.db.bak-<previous version> is made first
      And every row gets row_sha and chain_sha in id order, and "sentinel audit verify" passes

    @AC-SEC-07f @integration @P1 @cov-data-integrity
    Scenario Outline: Verify finds tampering
      Given <tampering> with the triggers dropped by a direct SQLite connection
      When "sentinel audit verify" is run
      Then it exits 1 and names the first broken row id
      Examples:
        | tampering                                 |
        | row 12 has its actor changed              |
        | row 12 is deleted                         |
        | a row is inserted between ids 12 and 13   |
        | the triggers are missing                  |

    @AC-SEC-07g @integration @P2 @cov-happy-path
    Scenario: Verify passes on an untouched registry
      When "sentinel audit verify" is run
      Then it exits 0 and prints the row count and the head chain_sha

  Rule: Export

    @AC-SEC-07h @integration @P1 @cov-happy-path
    Scenario: Export to a JSON Lines file
      When "sentinel audit export --out audit.jsonl" is run by a human
      Then audit.jsonl is mode 0600 with a header line holding format "sentinel-audit-v1", project, sentinel version, exported_at, filters, row count and head chain_sha
      And one line per row with id, at, actor, channel, action, target, before_sha, after_sha, reason, row_sha, prev_chain_sha and chain_sha
      And "sentinel audit verify --file audit.jsonl" exits 0

    @AC-SEC-07i @integration @P1 @cov-happy-path
    Scenario Outline: Filters
      When "sentinel audit export --out a.jsonl <filter>" is run
      Then only rows matching <filter> are written and the header records the filter
      And verify of the file passes, checking each row against its own prev_chain_sha
      Examples:
        | filter                                   |
        | --from 2026-11-01 --to 2026-11-02        |
        | --actor dev                              |
        | --channel dashboard                      |
        | --action approve                         |
        | --run leave-balance                      |

    @AC-SEC-07j @integration @P2 @cov-happy-path
    Scenario: CSV export
      When "sentinel audit export --format csv --out audit.csv" is run
      Then audit.csv has a header row and one row per audit row
      And a value starting with "=", "+", "-" or "@" is written with a leading "'" so a spreadsheet does not run it

    @AC-SEC-07k @integration @P1 @cov-perf-security
    Scenario: The export is scrubbed and marks scrubbed rows
      Given audit row 7 has reason "token=abcd1234efgh5678" and row 8 has the workspace path in its target
      When the audit is exported
      Then the file does not hold "abcd1234efgh5678" or the workspace path
      And rows 7 and 8 are marked "scrubbed": true, and verify checks their chain link but not their row_sha

    @AC-SEC-07l @integration @P2 @cov-empty-null
    Scenario: Nothing matches
      When "sentinel audit export --out a.jsonl --actor nobody" is run
      Then the file holds only the header with row count 0 and the command exits 0

    @AC-SEC-07m @integration @P2 @cov-invalid-input
    Scenario Outline: Bad arguments
      When "sentinel audit export <args>" is run
      Then it exits <code> with a message naming the problem and writes no file
      Examples:
        | args                                       | code |
        | --out a.jsonl --from 2026-99-01            | 2    |
        | --out a.jsonl --format xml                 | 2    |
        | --out existing.jsonl                       | 1    |
        | --out /nonexistent/dir/a.jsonl             | 1    |

    @AC-SEC-07n @integration @P2 @cov-duplicate
    Scenario: Overwrite only with --force
      Given existing.jsonl exists
      When "sentinel audit export --out existing.jsonl --force" is run
      Then the file is replaced through a temporary file and rename

    @AC-SEC-07o @integration @P2 @cov-authz
    Scenario: A task process cannot export the audit
      Given SENTINEL_TASK_ID is set in the environment
      When "sentinel audit export --out a.jsonl" is run
      Then it is refused with exit 5 "E_ACTOR" and no file is written

    @AC-SEC-07p @integration @P2 @cov-happy-path
    Scenario: The export itself is audited
      When the audit is exported
      Then a new audit row with action "audit_exported", the filters and the file sha256 is appended after the exported rows

    @AC-SEC-07q @integration @P2 @cov-concurrency
    Scenario: Export while approvals are written
      Given another process appends 50 audit rows during the export
      When the export finishes
      Then the file holds a consistent snapshot whose head chain_sha matches a row in the registry
      And verify of the file passes

    @AC-SEC-07r @integration @P2 @cov-db-failure
    Scenario: The registry is locked for writing
      Given another connection holds an exclusive lock for 10 seconds
      When "sentinel audit export --out a.jsonl" is run
      Then it exits 1 with "E_LOCKED" after its busy timeout and leaves no partial file

    @AC-SEC-07s @integration @P2 @cov-regression
    Scenario: The dashboard audit view uses the same rows
      Given a running server
      When GET /api/v1/audit?project=digital-hr is called
      Then the rows equal those of the export without filters, with row_sha and chain_sha added
