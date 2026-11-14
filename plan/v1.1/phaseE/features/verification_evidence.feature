@REQ-VER-01 @REQ-VER-02 @REQ-SEC-06 @REQ-PER-02
Feature: Verification evidence and the verify command
  Verification evidence is written by the engine from commands it ran itself. Agent claims are
  kept for the report and never count. Output is scrubbed before it is stored. "sentinel verify"
  is the only way to run verification, one run at a time, and it survives interruption.

  Background:
    Given a workspace with a valid sentinel.config.yaml and a local-only shared folder
    And repo "backend" is a git repo
    And repo "backend" uses the test profile "fake-junit" whose build, lint, typecheck, test, targeted_test and mutate commands call the fake check tool
    And a version 2 run "leave-balance" in state VERIFYING at tier 3 on repo "backend" with both approvals valid
    And every cycle of "leave-balance" is CYCLE_ACCEPTED and repo "backend" has changes since its baseline
    And the fake check tool passes every command unless a scenario says otherwise

  Rule: Each evidence row is complete and written by the engine

    @AC-VER-01j @integration @P1 @cov-happy-path
    Scenario: A verification evidence row holds the full record
      When "sentinel verify leave-balance" is run
      Then every evidence row of round 1 holds kind, repo, command, cwd, exit_code, classification, passed, failed, skipped, started_at, finished_at, env and repo_sha
      And every row's started_at is not after its finished_at
      And every row links a stored output file under .sentinel/runs/leave-balance/verification/round-1/ and the sha256 of that file
      And every row has an empty task id and actor kind "engine"
      And the row env names the Python version, the OS and the tool versions the profile declares

    @AC-VER-02b @integration @P1 @cov-data-integrity
    Scenario: Agent claims do not count as verification evidence
      Given the last tdd_refactor task of "backend" wrote a result.json claiming "./gradlew test" exited 0
      And the fake check tool makes the full test command of "backend" fail with "LeaveFormTest.submit"
      When "sentinel verify leave-balance" is run
      Then the "test" evidence row of "backend" failed
      And the run state is VERIFYING
      And the verification summary flags the claim of the tdd_refactor task as "contradicted by evidence"

    @AC-VER-02c @integration @P1 @cov-data-integrity
    Scenario: A finished check is never skipped because an agent ran it
      Given every task result of "leave-balance" claims build, lint, typecheck and test passed
      When "sentinel verify leave-balance" is run
      Then the fake check tool was called for build, lint, typecheck, targeted and full test of "backend"

  Rule: Stored output is scrubbed

    @AC-SEC-06a @integration @P1 @cov-perf-security
    Scenario Outline: Secrets and personal data never reach stored output
      Given the fake check tool prints <text> during the full test command of "backend"
      When "sentinel verify leave-balance" is run
      Then the stored output file of the "test" evidence row does not contain <secret>
      And it contains <marker>
      And the output sha256 in the row is the sha256 of the scrubbed file
      Examples:
        | text                                              | secret                    | marker                        |
        | "password=hunter2x9"                              | "hunter2x9"               | "[REDACTED:secret]"           |
        | "key AKIAABCDEFGHIJKLMNOP"                        | "AKIAABCDEFGHIJKLMNOP"    | "[REDACTED:aws key]"          |
        | "jdbc://app:s3cretpw@db.internal/leave"           | "s3cretpw"                | "[REDACTED:credentials]"      |
        | "mail sent to jane.doe@corp-mail.com"             | "jane.doe@corp-mail.com"  | "[REDACTED:email]"            |
        | the value of DB_PASSWORD from backend/.env        | that value                | "[REDACTED:env]"              |

  Rule: Rounds keep history and a changed output file is caught

    @AC-VER-01k @integration @P1 @cov-data-integrity
    Scenario: A second round adds rows and keeps the first
      Given verification round 1 of "leave-balance" failed on "lint" and the fix task is COMPLETED
      When "sentinel verify leave-balance" is run
      Then the evidence rows of round 1 are unchanged
      And a full set of round 2 rows exists
      And the acceptance computation reads round 2 only

    @AC-VER-01l @integration @P1 @cov-data-integrity
    Scenario: An edited evidence output file is an integrity failure
      Given verification round 1 of "leave-balance" passed and the run is REVIEWING
      And the stored output file of the "test" evidence row of round 1 is edited
      When the engine computes acceptance for "leave-balance"
      Then the computation fails with error "E_INTEGRITY" naming the file
      And an "integrity_failed" audit row is stored
      And the run state is NEEDS_HUMAN

  Rule: sentinel verify runs only when verification is allowed

    @AC-VER-01m @integration @P1 @cov-invalid-input
    Scenario Outline: verify in other run states is refused
      Given a version 2 run "leave-form" in state <state>
      When "sentinel verify leave-form" is run
      Then it exits with code 5
      And the error is "<error>"
      And no evidence row exists for "leave-form"
      Examples:
        | state                | error        |
        | EXECUTING            | E_TRANSITION |
        | GHERKIN_REVIEW       | E_TRANSITION |
        | REVIEWING            | E_TRANSITION |
        | COMPLETED            | E_TRANSITION |
        | NEEDS_HUMAN          | E_TRANSITION |

    @AC-VER-01n @integration @P2 @cov-regression
    Scenario: verify on a 0.1 run points to the release check
      Given a 0.1 run "old-fix" created with "sentinel run new old-fix --tier 2"
      When "sentinel verify old-fix" is run
      Then it exits with code 5
      And the error is "E_TRANSITION" and the message names "sentinel release-check"
      And "sentinel release-check --repo backend" still behaves as before Phase E

    @AC-ARC-03j @integration @P1 @cov-happy-path
    Scenario: next tells the orchestrator to run verification
      When "sentinel next leave-balance --json" is run
      Then it exits with code 0
      And the output JSON has kind "orchestrator" and command "sentinel verify leave-balance"
      And no evidence row exists for "leave-balance"

    @AC-ARC-03k @integration @P2 @cov-happy-path
    Scenario: verify prints one line per check and a result line
      When "sentinel verify leave-balance" is run
      Then the output has one line per evidence row with repo, kind and "pass", "fail", "not_configured" or "disabled"
      And the last line is "VERIFICATION PASSED (round 1)"

  Rule: Verification is safe under concurrency and interruption

    @AC-AGT-07t @integration @P1 @cov-concurrency
    Scenario: Two verify calls at once run verification once
      Given the fake check tool sleeps 2 seconds on the full test command
      When "sentinel verify leave-balance" is run twice at the same time
      Then one call exits with code 0
      And the other exits with code 5 with error "E_LOCKED" naming the verification in progress
      And exactly one set of round 1 rows exists

    @AC-AGT-07u @integration @P1 @cov-concurrency
    Scenario: Verification waits while a task of the run is running
      Given the run is VERIFYING after a failed round and its fix task is RUNNING
      When "sentinel verify leave-balance" is run
      Then it exits with code 5
      And the error is "E_PRECONDITION" naming the running task
      And no evidence row of round 2 exists

    @AC-ORC-07e @integration @P1 @cov-db-failure
    Scenario: An interrupted verification is started again from the beginning
      Given "sentinel verify leave-balance" was killed after writing the "build" row of round 1
      When "sentinel verify leave-balance" is run again
      Then the partial round 1, which has no "finished" record, is marked "interrupted" and is not used for acceptance
      And a complete round 2 exists
      And the verification lock of round 1 does not block the new call

    @AC-ORC-07f @integration @P2 @cov-db-failure
    Scenario: A failed registry write leaves an open round that is never used
      Given the registry refuses writes after the third evidence row of round 1
      When "sentinel verify leave-balance" is run
      Then it exits with code 1 and names the database error
      And round 1 has no "finished" record and the run state is VERIFYING
      And the acceptance computation for "leave-balance" reports "verification evidence missing"
      When the registry accepts writes again and "sentinel verify leave-balance" is run
      Then round 1 is marked "interrupted" and a complete round 2 exists
