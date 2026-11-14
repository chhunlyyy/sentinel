# Phase B: Approval gates (Gherkin for review)

Scope (from `SPEC.md`, `IMPLEMENTATION_STATUS.md` rows PB-01 and PB-02): SPA-01 to SPA-08, GHA-01 to GHA-07, SEC-03, SEC-04 (approve and accept deny rules only), SEC-07 (approval audit rows), ART-01 (hash check on read), VIS-01 (no agent approval), ORC-06 (spec or Gherkin change after approval needs a human). Transitions R4 to R12, R12d, R17, R18 of `docs/contracts/state-transitions.md`. Decision B5: every tier, tier 1 included, gets two separate approvals, the specification first and then the Gherkin. Docs-only runs need the specification approval only.

- PB-01: spec and Gherkin artifacts, validators, coverage table (`spec_artifact.feature`, `gherkin_artifact.feature`).
- PB-02: review and approve over TTY, hashing, invalidation (`approval_tty.feature`, `hashing_invalidation.feature`).

Not in Phase B: dashboard approvals and the HTTP approval endpoint (Phase F and later), real specifier and test_designer tasks (Phase C; Phase B tests complete them through the engine), TDD cycles and Red binding (Phase D), final acceptance (Phase E). Some scenarios use EXECUTING, VERIFYING or REVIEWING as a starting state; the tests put the run into that state directly through the registry.

## Files

| Feature | Scenarios | Outline rows | Main requirements |
|---|---|---|---|
| `features/spec_artifact.feature` | 15 | 39 | SPA-01, SPA-02, SPA-03, R4 |
| `features/gherkin_artifact.feature` | 18 | 33 | GHA-01, GHA-02, GHA-03, GHA-04, GHA-07, R8, R12d |
| `features/approval_tty.feature` | 26 | 29 | SPA-04 to SPA-07, GHA-05, SEC-03, SEC-04, SEC-07, VIS-01, R5 to R11 |
| `features/hashing_invalidation.feature` | 23 | 23 | SPA-08, GHA-05, GHA-06, ART-01, ORC-06, R12, R17, R18 |
| Total | 82 | 124 | |

## Coverage table

| Category | Status |
|---|---|
| Happy path | covered (valid spec and Gherkin open review; approve, request changes, reject for both gates; R12 start) |
| Invalid input | covered (broken IDs, bad tags, unsupported Gherkin, bad front matter, wrong headings, wrong state, bad CLI args) |
| Missing required fields | covered (missing sections, missing criterion scenario, request changes with no comment, spec in wrong place) |
| Boundary | covered (section set per tier, tag inheritance, typed prefix trim and case, byte-only change, file set membership) |
| Empty / null | covered (0-byte and whitespace spec, empty section, empty features dir, empty feature file, deleted spec) |
| Authentication | not applicable: the CLI channel has no login; the human channel is the TTY (covered as authorization). Dashboard token auth is Phase F |
| Authorization | covered (non-TTY refused E_NOT_TTY, agent process refused, orchestrator and engine refused E_ACTOR, wrong prefix, gates cannot be configured away, deny rules in agent configs) |
| Data integrity | covered (hash vectors, stale approvals, R17, R18, tampered copies and records E_INTEGRITY, coverage never "complete" by count) |
| Duplicate submissions | covered (second approval of the same version) |
| Concurrency | covered (two terminals approve at once, approve vs request changes, file edited between prompt and typed prefix) |
| Error handling | covered (errors back into specifier and test_designer briefs, retry cap to NEEDS_HUMAN, closed prompt) |
| External service failure | not applicable: Phase B makes no provider or network call |
| Database failure | covered (event write failure during approval, missing approval record before execution) |
| Regression | covered (0.1 runs untouched by spec set, approve and spec edits; tier 1 still needs both approvals; 95 selftest checks and Phase A tests green) |
| Performance / security | security covered under authorization and data integrity; performance not applicable (artifacts are small text files) |

## How the tests will run

- Unit scenarios: stdlib `unittest` in `tests/`, one test per scenario (one subtest per Examples row), test names carry the AC id (for example `test_AC_SEC_03a_non_tty_approval_is_refused`).
- Integration scenarios: new checks in `sentinel/scripts/selftest.py`, named after the AC id. TTY scenarios use a pseudo-terminal (`pty.openpty` or `pty.fork`) to drive `sentinel approve`; non-TTY scenarios pipe stdin.
- Hash vectors in `AC-ART-01a` and `AC-GHA-05d` are fixed values; they were computed with Python `hashlib` over the exact bytes described.
- Concurrency scenarios use two processes against the same `.sentinel/sentinel.db`, as in Phase A `AC-C-36a`.
- Gate for Phase B completion: all Phase B tests pass, all Phase A tests and the 95 baseline selftest checks pass, evidence recorded in `IMPLEMENTATION_STATUS.md`.

## Set hash

Command, run from `plan/v1.1/phaseB`:

```sh
find features -name '*.feature' | sort | while read f; do printf '%s\0' "$f"; cat "$f"; printf '\0'; done | sha256sum
```

Hash: `aca8bae64794fb4fe5e986a818f9a8279bb779950849aa644e07231381fa9278`

## Open points for the reviewer

Each point is a choice made where the documents conflict or say nothing. Approving this set approves these choices.

1. **How a spec or Gherkin set is submitted in Phase B.** R4 and R8 need a completed specifier or test_designer task, and tasks arrive in Phase C. Phase B adds the engine step "specifier (or test_designer) task completes" and tests call it directly. Phase C wires it to real tasks.
2. **Where the hash is checked.** The engine re-hashes the shared spec and feature files whenever it loads a version 2 run (any command, including `review`, `approve`, and every engine-driven transition). A new hash creates a new artifact version and applies R17 or R18 at once.
3. **E_APPROVAL_STALE vs E_INTEGRITY.** `data-architecture.md` section 4 calls any mismatch E_INTEGRITY, but R17 and R18 treat a changed shared file as a normal new version. Choice: an edit to the shared file is a new version (R17, R18, or E_APPROVAL_STALE for a decision on the old hash). E_INTEGRITY is only for the engine's own records: a modified stored copy under `.sentinel/runs/<slug>/artifacts/`, or an approval row whose sha256 does not match its artifact row. E_INTEGRITY on a decision refuses it; E_INTEGRITY before execution sends the run to NEEDS_HUMAN. Both write an `integrity_failed` audit row.
4. **Stored copies.** Each validated version is copied under `.sentinel/runs/<slug>/artifacts/` so review diffs and integrity checks do not depend on the editable shared file. Invalid versions are not stored; they go back to the author with the errors.
5. **Wrong prefix error code.** A typed prefix that is not the current hash returns E_VALIDATION. E_APPROVAL_STALE is kept for a decision made on an older hash (the hash shown at review or at the prompt, or a full hash sent through the engine). Input is trimmed and lower-cased and must equal exactly the first 8 characters. A longer prefix, or the full hash, is refused.
6. **Exit codes.** E_NOT_TTY, E_VALIDATION, E_APPROVAL_STALE, E_INTEGRITY and E_TRANSITION exit with 5 (the `errors.py` default). Ending input at the prompt (EOF or Ctrl-C) exits with 1 and stores nothing.
7. **Refused approval attempts are audited** (`approve_refused` with the error code) so attempts by an agent show up (residual risk R1). SEC-07 only names performed actions.
8. **Request changes needs a non-blank comment** (SPA-05 says "with comments"); reject and approve take an optional comment.
9. **Spec changed while the Gherkin is in review.** The approval table only defines APPROVED to INVALIDATED. Choice: R17 also moves an IN_REVIEW Gherkin approval to INVALIDATED. This adds one row to the approval table in `state-transitions.md`.
10. **After R17 the Gherkin must be approved again even if its bytes did not change** (B5: a spec change invalidates both approvals). The Gherkin set is also validated again against the new spec version.
11. **A spec that becomes invalid after approval** (edited or deleted) still moves the run to SPECIFICATION_REVIEW by R17, not back to PLANNED. `approve` is refused with E_VALIDATION until the file validates again. R4 is not re-run.
12. **Any byte change is material.** No whitespace or line-ending normalization. Only an mtime change, or rewriting the same bytes, keeps the approval.
13. **Gherkin set membership.** Paths are relative to `specs/<slug>/` (for example `features/a.feature`) with `/` separators, include subfolders, only `*.feature`, sorted by UTF-8 byte order (not locale order). Note: the README command above uses the shell `sort`, which follows the locale; run it with `LC_ALL=C` for byte order. For the current file names both orders are the same.
14. **Spec format rules not stated in the docs:** headings must be `##`, matched without regard to case or extra spaces; extra sections are allowed; an empty section (or one holding only an HTML comment) is an error; "Not applicable" needs a reason after a colon; front matter needs `run` equal to the slug, `version`, and `tier` equal to the run tier (the engine's artifact version number is the one stored); a REQ with no AC is a warning, not an error.
15. **Gherkin tag rules not stated in the docs:** only `@REQ` is inherited from Feature or Rule; `@AC`, type and priority tags must be on the scenario; at least one type tag; exactly one priority tag `@P1` to `@P3`; unknown plain tags (for example `@smoke`) are allowed but do not count as a type; an `@AC` tagged under the wrong `@REQ` is a warning. Only English Gherkin and the keywords listed in GHA-03 are accepted (so `Scenario Template` is refused).
16. **Coverage table rules:** a scenario with no `@cov-*` tag counts as happy path; the type tag `@regression` counts as regression coverage; a category is not applicable only when the spec's Edge cases section has a line `- n/a @cov-<category>: <reason>`; an n/a line with no reason counts as missing; unknown `@cov-*` tags are warnings. Category tag names: `happy-path, invalid-input, missing-fields, boundary, empty-null, authn, authz, data-integrity, duplicate, concurrency, errors, external-failure, db-failure, regression, perf-security`. Missing categories are warnings and never block the review.
17. **`sentinel review` needs no TTY.** The contract lists it as human; it is read-only and prints nothing secret, so any caller may run it.
18. **Specifier retry cap.** No config key exists. Choice: `limits.specifier_retries` and `limits.test_designer_retries`, default 2, then NEEDS_HUMAN.
19. **SEC-04 deny rules** are tested here because they protect the approval command. If you prefer, `AC-SEC-04a` can move to PE-02, where adapters are regenerated.
20. **Running tasks during R17 or R18** (EXECUTING state) are out of Phase B; Phase C and D decide whether they are cancelled. Phase B only checks state and approvals.
21. **`sentinel approve` on a 0.1 run** returns E_TRANSITION (same code Phase A uses for `run update` on a version 2 run).
