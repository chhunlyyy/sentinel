# Quickstart

The short path from install to an accepted change. The full walkthroughs are the [dashboard user guide](gui-guide.md) and the [command-line guide](cli-guide.md).

## 1. Install

Install the Sentinel engine:

```bash
uv tool install sentinel-pipeline
sentinel --version
```

The release wheel includes the dashboard. (A git install, `uv tool install git+https://github.com/chhunlyyy/sentinel`, has the CLI but not the dashboard UI; see [the dashboard UI](installation.md#the-dashboard-ui).)

No `uv`? `pipx install sentinel-pipeline` works the same way. Upgrade with `uv tool upgrade sentinel-pipeline` (or `pipx upgrade sentinel-pipeline`). Remove it with `uv tool uninstall sentinel-pipeline` (or `pipx uninstall sentinel-pipeline`).

Optional AI tool skills (what your agent sees as `/sentinel`) can be installed into your AI coding tool:

```bash
npx skills@latest add chhunlyyy/sentinel@v2.0.0 --skill '*' -a claude-code
```

## 2. Start the dashboard

From any workspace folder or terminal:

```bash
sentinel dashboard
```

`sentinel dashboard` starts the Sentinel background service detached, prints a one-time session URL, and opens your browser. Closing the terminal leaves the service running; stop it with `sentinel stop`.

## 3. Create a project in the wizard

In the dashboard, click **Create project** (or open `/projects/new`):

1. **Repositories**: Enter a project name, workspace path, and add your local repository folders.
2. **Detected setup**: Sentinel auto-detects stack profiles (e.g. `spring-gradle`, `nextjs`, `python`), test/build/lint commands, and tracked branches.
3. **Shared knowledge**: Connect your team's empty private git repository (or local folder). Click **Test access** to verify connectivity; optionally enable historical commit backfill.
4. **AI team**: Review deterministic suggested routing per role (cheap/fast models for triage, gherkin, planner, knowledge; strong models for specifier, coder, reviewer).
5. **Check and create**: Review configuration summary and click **Create project**. Sentinel initializes `.sentinel/` and runs health checks.

## 4. Send your first task

1. Click **New task** (or open `/tasks/new`).
2. Choose the kind (Feature, Bug fix or Docs only) and describe the task in plain words (for example, "Add a CSV export button to the reports page").
3. Click **Create task**. The Sentinel service creates the version 2 run and immediately starts driving it.

## 5. Watch the Factory Floor

The dashboard lands on the **Factory Floor** (`/floor`):

- **Station path**: Watch your task token advance: Intake > Triage > Spec > Gate Spec > Gherkin > Gate Gherkin > Build > Verify > Report > Gate Accept > Knowledge.
- **Active agents**: Neurons show running agents with their role, runner, model, and elapsed time.
- **Build lanes**: During execution, the build station fans out into parallel lanes per behavior, executing Red (failing test), Green (pass), and Refactor phases.
- **Controls**: Pause or resume the run, cancel it, or send a note that the next agent task reads once.

## 6. Review, approvals and acceptance

Human gates keep you in control:

1. **Specification approval**: When the task reaches Gate Spec, open My Approvals. Review the generated specification and requirement diff, type the first 8 characters of the hash to confirm, and approve (or request changes).
2. **Gherkin approval**: At Gate Gherkin, review the behavior scenarios and approve with the typed hash confirmation.
3. **Build & Verify**: The engine executes TDD cycles and independent in-process verification.
4. **Acceptance**: At Gate Accept, inspect the final report, test evidence, and traceability matrix. Type the hash prefix to accept.
5. **Knowledge harvest**: On acceptance, a detached worker automatically indexes verified change records and module summaries into the team knowledge base.

## 7. Same thing from the terminal

Every GUI action has a direct CLI counterpart:

```bash
# 1. Initialize workspace and check configuration
sentinel init
sentinel doctor

# 2. Start an engine-driven run with request text
sentinel run new leave-export --type feature --driver engine --request "Add CSV export button"

# 3. Review and approve specification
sentinel review leave-export spec
sentinel approve leave-export spec

# 4. Review and approve Gherkin scenarios
sentinel review leave-export gherkin
sentinel approve leave-export gherkin

# 5. Run verification and generate report
sentinel verify leave-export
sentinel report leave-export

# 6. Accept result and publish to shared repo
sentinel accept leave-export
sentinel sync push leave-export

# 7. Check service status or stop
sentinel service status
sentinel stop
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `sentinel.config.yaml not found` | Run from inside the workspace, or pass `--dir`. |
| `slug X is locked by another run` | A teammate or an earlier run holds it. Pick another slug, or delete a stale lock: `git push origin :refs/sentinel/locks/<slug>` from `.sentinel/shared`. |
| `routing preflight failed` | An engine-driven run needs a CLI runner for every role. Configure `agents.<role>.runner` in `sentinel.config.yaml`, then run `sentinel resolve <slug> --refresh-config -m "configured runner"`. |
| `scrub check failed; nothing pushed` | `sentinel scrub --check` lists the files. Remove the data, or run `sentinel scrub --shared` to redact it. |
| `doctor` says a runner CLI is not installed | Install it, or route that stage to another runner. |
| Exit code 3 from `run_stage.py` | The stage broke its write boundary. Review the listed files; nothing was reverted automatically. |
