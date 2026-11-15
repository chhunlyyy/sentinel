# Phase H: Notifications, analytics, audit, security suite, docs and release 1.1.0 (Gherkin for review)

Scope (from `SPEC.md`, `IMPLEMENTATION_STATUS.md` row PH-01): NOT-01 to NOT-03 (local notifications: dashboard, terminal, optional browser desktop notifications; read state in `~/.config/sentinel/user.db`), ANL-01 and ANL-02 (metrics from the registry, `sentinel stats` extended, `GET /api/v1/reports/analytics` and a Reports screen), SEC-07 (append-only audit with a hash chain, `sentinel audit export` and `sentinel audit verify`), OPS-05 and PER-05 (`sentinel backup` with the sqlite backup API, verify and restore), TST-05, SEC-02, SEC-04, SEC-06, SEC-09 (executable security suite for the threat model of `docs/architecture/security-architecture.md` section 8 and residual risks R1 and R3), VIS-04 (no outbound network), SEC-08, OPS-04, OPS-03 (user guide for the version 2 flow, migration guide 0.1 to 1.1, residual risks stated plainly, SPEC.md LATER marks per decision G-1, new rows DSH-07 and SEC-09), OPS-01, OPS-02, TST-01, TST-03, TST-04 (version 1.1.0, wheel contents, offline install, upgrade of a 0.1.0b7 workspace, changelog, release gate over all phases). Decisions used: G0 B1 (local only), B7 (version 1.1.0), A-1 (`run new` creates version 2 unless `--legacy`, `--tier` or `--adhoc`), the Phase F decision dropping pause and "request intervention", G-1 (dashboard projects, repos and configuration read only in 1.1.0). Contracts: `docs/contracts/api-contracts.md` ("Other" routes and CLI rows `backup`, `audit export`), `docs/contracts/event-contracts.md` section 4 (notification rules), `docs/architecture/data-architecture.md` sections 1 to 3 (user.db, audit, migrations).

- PH-01 features: `notifications.feature`, `analytics.feature`, `audit_export.feature`, `backup.feature`, `security_suite.feature`, `docs_spec.feature`, `release.feature`.

Not in Phase H: every dashboard write deferred by G-1 (project, repo, configuration, provider and agent changes, directory picker, publishing), pause and request intervention, task attachments, templates and provider preference (marked LATER in SPEC.md by `AC-OPS-04i` and `AC-OPS-04j`), cost analytics beyond what tasks report (no price tables, ANL-02), provider comparisons and "insights" beyond the listed metrics, multi-user RBAC (SEC-05 LATER), OS-level notifications through `notify-send` or similar (point 2), push or e-mail notifications (VIS-04). Phase H depends on Phases D to G being built: scenarios that use cycles, verification, the server or the dashboard run after those tests pass.

## Files

| Feature | Scenarios | Outline rows | Main requirements |
|---|---|---|---|
| `features/notifications.feature` | 26 | 29 | NOT-01, NOT-02, NOT-03, VIS-04, SEC-06 |
| `features/analytics.feature` | 20 | 33 | ANL-01, ANL-02 |
| `features/audit_export.feature` | 17 | 16 | SEC-07 |
| `features/backup.feature` | 14 | 10 | OPS-05, PER-05 |
| `features/security_suite.feature` | 18 | 43 | TST-05, SEC-02, SEC-04, SEC-06, SEC-09 |
| `features/docs_spec.feature` | 12 | 46 | OPS-04, SEC-08, OPS-03 |
| `features/release.feature` | 17 | 45 | OPS-01, OPS-02, OPS-03, TST-01, TST-03, TST-04 |
| Total | 124 | 222 | |

By type: 58 `@integration`, 32 `@unit`, 18 `@security`, 10 `@e2e`, 5 `@regression`, 1 `@performance`.

All seven files load with `sentinel/scripts/artifacts.py` `parse_gherkin` with no errors; every scenario has one `@AC` tag, one type tag, one priority tag and at least one known `@cov-` tag.

New AC ids (none used by Phases A to G, their READMEs, `tests/`, `sentinel/`, `docs/` or `SPEC.md`; checked with grep): `AC-NOT-01a`-`q`, `AC-NOT-02a`-`d`, `AC-NOT-03a`-`c`, `AC-VIS-04a`, `AC-ANL-01a`-`p`, `AC-ANL-02d`-`g`, `AC-SEC-02l`, `AC-SEC-04d`, `AC-SEC-06i`-`l`, `AC-SEC-07c`-`s`, `AC-SEC-08a`-`c`, `AC-SEC-09a`-`c`, `AC-OPS-01g`-`k`, `AC-OPS-02a`-`b`, `AC-OPS-03a`-`e`, `AC-OPS-04e`-`l`, `AC-OPS-05a`-`m`, `AC-PER-05c`, `AC-TST-01k`-`m`, `AC-TST-03a`, `AC-TST-04a`-`b`, `AC-TST-05a`-`j`. `AC-SEC-01*` and `AC-SEC-03*` are used up to `z`, so new HTTP security checks use `AC-TST-05*`.

## Coverage table

| Category | Status |
|---|---|
| Happy path | covered (each notification rule, CLI and dashboard read state, bell and list, desktop notification after consent, each metric definition, cost when reported, stats Markdown output, analytics route and Reports screen, audit chain and verify, export with filters and CSV, backup with checks, restore from a terminal, guides and new SPEC rows, version and changelog, wheel contents, uv install, new run in an upgraded workspace) |
| Invalid input | covered (malformed and unknown notification ids, bad stats arguments, bad analytics query, bad audit export arguments, backup of another workspace) |
| Missing required fields | covered (backup restore, verify and out without their argument) |
| Boundary | covered (events without a rule, paging over projects, date range bounds, unfinished runs, permission never asked on load, wheel holds nothing extra) |
| Empty / null | covered (fresh install has no notifications and creates no user.db, partial and missing metrics null with a reason, empty range, workspace without registry for stats and backup, export with no matching rows) |
| Authentication | covered (token removed from URL and history; earlier cookie and token checks re-run through the manifest) |
| Authorization | covered (mark read needs CSRF, opening a notification never decides, notification has no decision control, no desktop notification without consent, analytics never write, task process cannot export audit, back up or restore, restore needs a terminal, CSRF from another local origin, DNS rebinding, simple agent forgery refused, R1 pseudo-terminal and token cases recorded as residual, deny rules for the new human commands) |
| Data integrity | covered (user.db private and content-free, restored registry keeps new events unread, metrics recomputable by SQL, audit append-only triggers and chain, export marks scrubbed rows, backup integrity and counts, bad backups refused, SPEC MUST rows met or LATER) |
| Duplicate submissions | covered (mark read twice keeps first time, one desktop notification for two tabs, export overwrite only with --force) |
| Concurrency | covered (parallel mark read, stats during writes, export during appends, backup during writes, restore refused while a task or the server runs) |
| Error handling | covered (downgrade explained, release gate stops on a skipped AC) |
| External service failure | covered (unavailable project in notifications, full disk for backup, offline install in a network namespace) |
| Database failure | covered (user.db read-only, unreadable registry for stats, locked registry for export, failed restore keeps the registry, pre-release registry backed up before migration) |
| Regression | covered (0.1 runs give no notifications, stats 0.1 keys unchanged, existing audit rows chained, dashboard audit view equals export, every documented command exists, links and versions, 0.1.0b7 workspace untouched, runtime dependencies unchanged, every earlier suite green, every phase hash unchanged, every AC has a passing test, the 23 core scenarios automated, the 20 dashboard criteria accounted for) |
| Performance / security | security covered (no network for notifications, scrubbed notification text, canary sweep across every output, prompts free of secrets, backup sensitivity, stripped agent environment, path traversal in every path-like argument, XSS on the new screens, link allow-list, plain desktop text, CSV formula injection, residual risks stated); performance covered (analytics over 1000 runs within 2 s) |

## How the tests will run

- Python tests use stdlib `unittest` under `tests/`, with temporary HOME folders, fixture workspaces and fake runners as in Phases C to G. Test names carry the AC id; Examples rows are `subTest` rows.
- Notifications: `tests/test_notifications.py` (engine function over fixture event rows, CLI `sentinel notifications [--unread] [--json] [read <id>|--all]`), `tests/test_notifications_api.py` against `sentinel dashboard --no-open` under a pseudo-terminal. Dashboard parts (`AC-NOT-01q`, `AC-NOT-02*`, `AC-NOT-03a`, `AC-SEC-09*`, `AC-ANL-01p`, `AC-ANL-02g`) are Playwright tests against the Phase G fake API server with new fixtures recorded by `test_dashboard_fixtures`; the browser Notification API is stubbed through Playwright permissions and an init script that records constructed notifications.
- Analytics: `tests/test_analytics.py` on the fixture registry `analytics-small` with fixed times; `tests/fixtures/analytics_queries.sql` holds one independent query per metric (`AC-ANL-01b`). The 1000-run registry for `AC-ANL-01m` is generated by the test.
- Audit and backup: `tests/test_audit_export.py`, `tests/test_backup.py`. Tampering uses a direct `sqlite3` connection that drops the triggers. The full-disk case uses a small loop-mounted or tmpfs folder with a size limit when available, otherwise a fault-injected writer; the skip reason is recorded.
- Security suite: `tests/security/` with `manifest.json` (threat to check ids, each check marked `blocking` or `residual`). It re-runs the earlier security tests by AC id (Phase F `AC-SEC-01l`-`x`, `AC-SEC-02*`, `AC-API-01h`-`n`; Phase G `AC-INS-06*`; Phases B, C, E approval, scope and scrub tests) and adds the checks of `security_suite.feature`. DNS rebinding and CSRF use Playwright Chromium with `--host-resolver-rules` mapping `rebind.example` to 127.0.0.1 and a second loopback test server. Canary values are unique random strings per run.
- Docs: `tests/test_docs.py` parses Markdown for commands, links and version strings and runs `sentinel <sub> --help` for each command found. `AC-OPS-04l` reads all approved feature sets and SPEC.md.
- Release: `tools/release_gate.py` runs selftest, unittest, the security suite, the dashboard npm scripts, the phase hash checks, the AC-to-test check, `tests/release/core14.json` and `tests/release/dashboard22.json`, builds the wheel with `SENTINEL_RELEASE=1`, and installs it offline in a network namespace (`unshare -rn`; skipped with a recorded reason where user namespaces are not allowed, then run in CI). The 0.1.0b7 fixture workspace tarball is made once by the 0.1.0b7 wheel and checked in.
- Gate for Phase H and for G9 (final acceptance): all Phase H tests pass, `tools/release_gate.py` exits 0 on a clean checkout, the manual checks (screen reader pass from Phase G, any `manual` item of `dashboard22.json`) are recorded, evidence in `IMPLEMENTATION_STATUS.md`.

## Set hash

Command, run from `plan/v1.1/phaseH`:

```sh
find features -name '*.feature' | LC_ALL=C sort | while read f; do printf '%s\0' "$f"; cat "$f"; printf '\0'; done | sha256sum
```

Hash: `d61984bef91e27725b81c9d4723e298e7a5e2b94716e246c11b6b8d54e994012`

## Open points for the reviewer

Each point is a choice made where the documents conflict or say nothing. Approving this set approves these choices.

1. **Notifications are computed, not stored.** The rule table of event-contracts section 4 is applied on read to the events table; the notification id is `<project>:<event id>`. No `notification.created` row is written (it would duplicate the triggering event), so that event type is removed from the contract. The dashboard re-fetches `/notifications` when a matching event arrives on the stream. Rule set: the contract rows plus "run started" (`run.created`) and run accepted, rejected or failed (NOT-01 "run start and end").
2. **Desktop means the browser.** NOT-02 is met with the browser Notification API after an explicit click and permission, gated by `notifications.desktop` (default true; off hides the option). No `notify-send`, OS notification daemon, service worker or Push API. "Terminal" means `sentinel notifications`; nothing is printed into other running terminals.
3. **Read state is not audited.** Marking a notification read is not a critical action; it is stored only in user.db (project id, workspace registry id, event id, event time, read time) and adds no audit row (`AC-NOT-03b`).
4. **`sentinel stats` keeps its 0.1 JSON and adds `v2`.** The selftest parses the 0.1 keys, so they stay as they are and count 0.1 runs only; the new `v2` key counts version 2 runs only. `--from`, `--to` (on run creation date, inclusive, UTC) and `--format json|md` are new. Stats open the registry read-only and never create it.
5. **Metric definitions.** Lead time is created to finished for finished runs (median and p90); acceptance rate is accepted over decided; approval wait is from the `approval.requested` event to `decided_at`; provider failure rate counts `E_PROVIDER` only. Cost is summed only from task rows; partial sums are labelled, nothing is estimated from tokens. Reviewer: confirm or change these definitions before Red.
6. **Audit hash chain.** "Append-only proof" is two controls: SQLite triggers refuse UPDATE and DELETE, and a per-row hash chain written with the row, checked by `sentinel audit verify`. A same-user attacker can drop the triggers and rewrite the whole chain; this is stated in `docs/security.md` (`AC-SEC-08a`). Needs a registry migration (number taken in merge order) that backfills existing rows.
7. **Audit export and backup are human-only but need no terminal.** Both are refused in a task process (`SENTINEL_TASK_ID` set, `E_ACTOR`) and denied in generated agent configs; restore additionally needs a terminal and the typed hash prefix because it replaces state. The contract lists both as actor H.
8. **Backup scope.** `sentinel backup` copies the workspace registry only, into `.sentinel/backups/` (git-ignored). user.db, config files and run folders are not included (run folders are files the user can copy; `sentinel run export` exists for runs). No automatic pruning of old backups. Restore is added beyond the contract's "copy registry" because a backup without a tested restore path is not a backup.
9. **"Registry created with backup" on upgrade.** A 0.1.0b7 workspace has no registry, so nothing is backed up; its run files are proven byte-identical instead (`AC-OPS-03b`). The backup-before-migration rule applies to registries from development builds (`AC-OPS-03c`), as Phase A built it.
10. **SPEC.md LATER list.** `AC-OPS-04i` lists the rows proposed for LATER marks under G-1: VIS-07, DSH-02, PRJ-03, PRJ-04, PRJ-05, REP-02, REP-05, CFG-01, CFG-03, CFG-04, CFG-05 (restore), CFG-07, INS-08, PRV-01, PRV-02, PRV-03, AGT-08, GIT-02 (dashboard publish), ART-02 (dashboard knowledge). Plus MON-02 pause and intervention, TSK-01 attachments and provider preference, TSK-04 (`AC-OPS-04j`). VIS-07 is a product-level MUST; marking it LATER means 1.1.0 does not meet the dashboard Definition of Done items for project creation and configuration. `AC-OPS-04l` enforces that every MUST row is tested or marked LATER.
11. **DSH-07 and SEC-09 are added in this phase** with the wording in `AC-OPS-04k`; this set already tags `@REQ-SEC-09`, which is valid once the row exists.
12. **New docs files.** `docs/dashboard.md`, `docs/operations.md`, `docs/migration-1.1.md` and `CHANGELOG.md` are new; `docs/workflow.md`, `docs/config.md`, `docs/security.md` and `README.md` are rewritten where needed. `docs/security.md` also drops the outdated "auto_sync_push on by default" sentence.
13. **Release gate checks every phase hash and every AC.** `AC-TST-01m` requires each AC id of phases A to H in a passing test name, so any AC left untested blocks the release unless it is recorded as manual. This may surface gaps in earlier phases late; that is intended.
14. **Offline install needs a wheelhouse.** "pip install offline from the wheel" cannot fetch pyyaml and jsonschema, so the test prepares a wheelhouse with them first, then installs with `--no-index` in a network namespace.
15. **Classifier.** `pyproject.toml` stays "Development Status :: 4 - Beta" unless the owner wants "5 - Production/Stable" for 1.1.0; no scenario checks it.
