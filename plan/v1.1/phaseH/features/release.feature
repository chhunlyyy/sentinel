@REQ-OPS-01 @REQ-OPS-02 @REQ-OPS-03 @REQ-TST-01 @REQ-TST-03 @REQ-TST-04
Feature: Version 1.1.0 release
  The release is one wheel with the dashboard build, migrations, schemas, profiles, templates and
  skills. It installs offline from a local wheelhouse, upgrades a 0.1.0b7 workspace without
  touching legacy runs, and passes every earlier suite. tools/release_gate.py runs the gate and
  writes its evidence.

  Rule: Version and changelog

    @AC-OPS-02a @unit @P1 @cov-happy-path
    Scenario: The version is 1.1.0 everywhere
      Then sentinel/VERSION holds "1.1.0"
      And "sentinel --version" prints "1.1.0"
      And the built wheel is named sentinel-1.1.0-py3-none-any.whl and its METADATA says Version: 1.1.0
      And GET /api/v1/installation answers version "1.1.0"

    @AC-OPS-02b @unit @P1 @cov-happy-path
    Scenario Outline: The changelog has a 1.1.0 entry
      When CHANGELOG.md is read
      Then it has a heading "## 1.1.0" with sections Added, Changed, Removed and Security
      And the entry mentions "<item>"
      Examples:
        | item                                       |
        | version 2 runs with two approvals          |
        | TDD cycles and independent verification    |
        | local dashboard and API                    |
        | notifications, stats, audit export, backup |
        | sentinel submit removed                    |
        | auto_sync_push off when not set            |
        | residual risks R1 and R3                   |
        | link to docs/migration-1.1.md              |

  Rule: Wheel contents and offline install

    @AC-OPS-01g @integration @P1 @cov-happy-path
    Scenario Outline: The wheel holds every runtime file
      Given the release wheel built from a clean checkout with SENTINEL_RELEASE=1
      When its file list is read
      Then it holds <files>
      Examples:
        | files                                                          |
        | sentinel/dashboard_dist/index.html and every file in its manifest |
        | every sentinel/scripts/migrations/*.sql of the checkout        |
        | every sentinel/core/schema/*.json of the checkout              |
        | the user.db migrations                                         |
        | sentinel/profiles/*.json and sentinel/templates/**             |
        | sentinel/skills/** generated from skills/                      |

    @AC-OPS-01h @integration @P1 @cov-boundary
    Scenario: The wheel holds nothing it should not
      When the wheel file list is read
      Then it holds no tests, no dashboard/node_modules, no dashboard/src, no source maps, no .env, no __pycache__ and no plan/ files

    @AC-OPS-01i @integration @P1 @cov-external-failure
    Scenario: Offline install from the wheel
      Given a wheelhouse folder with the release wheel and wheels of its declared dependencies
      When "pip install --no-index --find-links wheelhouse sentinel" runs in a fresh virtual environment inside a network namespace with only loopback
      Then it succeeds and "sentinel --version", "sentinel selftest" and "sentinel dashboard --no-open" under a pseudo-terminal work
      And the served page loads with every asset from the installed package

    @AC-OPS-01j @integration @P2 @cov-happy-path
    Scenario: uv tool install from the wheel
      When "uv tool install ./sentinel-1.1.0-py3-none-any.whl" runs with UV_OFFLINE=1 and a filled cache
      Then "sentinel --version" prints "1.1.0"

    @AC-OPS-01k @unit @P2 @cov-regression
    Scenario: Runtime dependencies are unchanged
      When the wheel METADATA is read
      Then Requires-Dist lists only pyyaml>=6 and jsonschema>=4 and Requires-Python is >=3.10

  Rule: Upgrading a 0.1 workspace

    @AC-OPS-03b @integration @P1 @cov-regression
    Scenario: A 0.1.0b7 workspace keeps working
      Given the fixture tests/fixtures/ws-0.1.0b7.tar.gz made by 0.1.0b7, with an open run "old-open" and a finished run "old-done"
      And the sha256 of every file under its .sentinel/runs and of sentinel.config.yaml is recorded
      When 1.1.0 runs "sentinel doctor", "sentinel stats" and "sentinel resume old-open" in it
      Then every recorded file is byte-identical
      And .sentinel/sentinel.db exists with old-open and old-done as workflow_version "0.1"
      And "sentinel resume old-open" points at the same next stage as 0.1.0b7 did
      And "sentinel doctor" lists the optional new settings and exits 0

    @AC-OPS-03c @integration @P1 @cov-db-failure
    Scenario: A pre-release registry is backed up before it is migrated
      Given a workspace whose registry has schema_version 3 from a 1.1.0 development build
      When 1.1.0 opens it
      Then sentinel.db.bak-3 is written with the sqlite backup API before the first migration
      And the registry ends at the latest schema_version with every row kept

    @AC-OPS-03d @integration @P2 @cov-regression
    Scenario: A new version 2 run in an upgraded workspace
      Given the upgraded 0.1.0b7 fixture workspace
      When "sentinel run new new-feature --type feature" is run
      Then a version 2 run is created and "sentinel next new-feature --json" asks for triage
      And the legacy runs are unchanged

    @AC-OPS-03e @integration @P2 @cov-errors
    Scenario: Downgrading is refused clearly
      Given a registry migrated by 1.1.0
      When 0.1.0b7 runs "sentinel resume old-open" in the workspace
      Then it still works on state.json, because 0.1.0b7 never reads the registry
      And docs/migration-1.1.md says that 1.1.0-only runs are not visible to 0.1.0b7

  Rule: Release gate

    @AC-TST-01k @regression @P1 @cov-regression
    Scenario: Every earlier suite is green
      When tools/release_gate.py runs on a clean checkout
      Then "python3 sentinel/scripts/selftest.py" reports 0 failed with every baseline check present
      And "python3 -W default -m unittest discover -s tests" passes with no ResourceWarning and no leaked process
      And the security suite, the dashboard npm test, e2e, lint and typecheck pass
      And the gate writes the counts, durations and commit to the evidence file it names

    @AC-TST-01l @regression @P1 @cov-regression
    Scenario Outline: Each phase's Gherkin is still the approved set
      When the set hash of plan/v1.1/<phase>/features is computed
      Then it equals the approved hash recorded in IMPLEMENTATION_STATUS.md
      Examples:
        | phase  |
        | phaseA |
        | phaseB |
        | phaseC |
        | phaseD |
        | phaseE |
        | phaseF |
        | phaseG |
        | phaseH |

    @AC-TST-01m @regression @P1 @cov-regression
    Scenario: Every approved AC has a passing test
      When the AC ids of plan/v1.1/phase*/features are compared with the test names of tests/, tests/security/ and dashboard/
      Then every AC id is in at least one test name, and every such test passed in the gate run
      And the gate lists any AC id marked manual with its recorded evidence

    @AC-TST-03a @regression @P1 @cov-regression
    Scenario Outline: The mandatory scenarios of SPEC_CORE section 14 are automated
      When the gate reads tests/release/core14.json
      Then "<scenario>" maps to at least one AC id whose test passed
      Examples:
        | scenario                                       |
        | User submits a feature request                 |
        | Specification has not been approved            |
        | Human requests specification changes           |
        | Approved specification changes                 |
        | Gherkin has not been approved                  |
        | Human finds missing edge cases                 |
        | Approved Gherkin changes                       |
        | Both approvals are valid                       |
        | Red produces expected assertion failure        |
        | Red fails due to environment                   |
        | Green modifies approved tests                  |
        | Green passes                                   |
        | Refactor breaks tests                          |
        | More behaviors remain                          |
        | All cycles pass                                |
        | Provider is unavailable                        |
        | Agent exceeds write scope                      |
        | Agent claims tests passed without evidence     |
        | Process is interrupted                         |
        | Two tasks modify overlapping files             |
        | Security gate requires human approval          |
        | Agent attempts to approve its own work         |
        | Publishing is attempted without authorization  |

    @AC-TST-04a @regression @P1 @cov-regression
    Scenario: The 20 dashboard criteria are each accounted for
      When the gate reads tests/release/dashboard22.json
      Then each of the 20 criteria of SPEC_DASHBOARD section 22 is "automated" with passing AC ids, "manual" with a recorded check, or "LATER" with the G-1 reference
      And the list is copied into the release evidence

    @AC-TST-04b @integration @P2 @cov-errors
    Scenario: The gate stops on the first missing piece
      Given one AC test is skipped without a recorded reason
      When tools/release_gate.py runs
      Then it exits 1 naming the AC id and does not write "release ready" to the evidence
