# Workstream G: housekeeping report

## 1. Flaky `test_release::Installed::test_AC_OPS_01i`
- Cause: the test runs the installed `sentinel selftest`. Selftest check `AC-TSK-03b` (phase F) creates a run through the
  API of a live server, asks `next` over the API, then asks `next` again through the CLI and expects both to say
  "driven by the engine". The server's engine loop owns that run and, because the selftest workspace has no CLI runner,
  parks it BLOCKED (routing preflight) on its next tick. On a loaded machine the CLI answer arrives after the tick, so
  it was the blocker step (no `driven_by`), and the check crashed with `KeyError: 'driven_by'`. Reproduced: 6 parallel
  phase-F runs under CPU load, one hit it.
- Fix (`sentinel/scripts/selftest.py`): each answer is judged against the state it names (CREATED: engine wait;
  BLOCKED by the routing preflight: engine's blocker); either way the skill is handed no task. No sleep or retry.
- Result: 8 parallel phase-F runs under load, all clean; 5 consecutive `-k 01i` runs and the full file: see section 5.
  (The test ends as `skipped` on this machine by design: user namespaces are not allowed here.)

## 2. Test isolation
- Cause: `backup.restore` asks `userdir.config_dir()` (XDG_CONFIG_HOME or `~/.config/sentinel`) whether a server runs;
  two tests did not pass a config folder, so they saw the owner's real service (E_LOCKED).
- Fix: both tests now pass `config_dir=` a temporary folder (`test_backup.py`, `test_phase_h_b_review.py`).
- A global `tests/conftest.py` was tried and dropped: `REQ-TST-02` forbids a conftest (stdlib unittest only) and a global
  XDG variable changes the output of the deny-rule and factory pause tests. Verified with the real service running
  (port 34441): all of `test_backup.py`, `test_phase_h_b_review.py` pass.

## 3. Accessibility
- `dashboard/e2e/accessibility_xss.spec.ts` (axe-core via `@axe-core/playwright`, already in package.json): added the
  factory floor (light, dark, waiting gate), Tasks, Runs, Quality, Reports (light, dark), Knowledge, Settings pages and
  the run overview; plus 5 role/name/landmark tests: header (one banner, one main, named Main nav, named status, no
  unnamed header control), the More menu (state, links, Escape), the notification bell panel, the floor regions, station
  buttons and the cancel dialog, and the pause button.
- Real violations found and fixed:
  - Floor station buttons: `label-content-name-mismatch` (visible "In", "Tr" vs name "Intake: Done"). The glyph is now
    CSS generated content (`data-glyph`, `floor.css`; `NeuronButton.tsx`), so the visible text is the name. Minimal
    change in `components/floor/`.
  - Knowledge: record buttons had the same mismatch (removed the `aria-label`); two scrollable `pre` blocks were not
    keyboard focusable (`tabIndex=0`, `role=region`, named).
- Docs: README Status, `docs/security.md` (Residual risks) and `docs/beta-testing.md` say plainly that a manual
  screen-reader pass has not been done.

## 4. Gemini adapter against the real CLI (0.60.0)
- Two real calls were made on a throwaway git repo. Both exited 55: `IneligibleTierError: This client is no longer
  supported for Gemini Code Assist for individuals` (the owner's account is refused). No successful answer was seen, so
  the JSON output format was not adopted and text output is kept.
- What the real CLI did show, and fixed:
  - Headless gemini refuses a folder it does not trust ("not running in a trusted directory ... use `--skip-trust`")
    and downgrades `--approval-mode` to default there. The built-in runner now passes
    `--approval-mode auto_edit --skip-trust`, `--include-directories` for extra dirs, and `--yolo` as the unsafe flag
    (`run_stage.py`). All flags confirmed in the real `--help`; the CLI accepts them (`--version` with all flags exits 0).
  - The live model check (`sentinel.py model_problems`) reported the last line of stderr, which for gemini is a stack
    frame; it now reports the error line (`_failure_line`) and passes the runner's args (`--skip-trust`).
- Tests: `tests/test_gemini_adapter.py` with fixtures `tests/fixtures/gemini_0.60.0_help.txt` and
  `gemini_0.60.0_headless_ineligible.stderr` (real output, home path anonymized).
- Docs updated (beta-testing, config, installation): gemini was run for real only as far as a refused account allows.
  Codex and Cursor still say "untried".

## 5. Results
See the final message (pytest counts, dashboard checks).

## Unfinished / owner items
- A successful Gemini answer (and its JSON format, session id, exit codes on success) needs an account the CLI accepts.
- Manual screen-reader pass.
