# Migrating from 0.1.0b7 to 1.1.0

1.1.0 adds a second kind of run (version 2: two human approvals, TDD cycles, independent verification), a local dashboard and a registry. Everything 0.1.0b7 did still works for the runs it started. This page lists what you do to upgrade, what changes, what stays untouched, and how to go back. (For upgrading from 1.x to Sentinel 2.0, see [Migrating to 2.0](migration-2.0.md).)

## Upgrade

1. Install the new engine and check the version:

   ```bash
   uv tool install --force sentinel-pipeline
   sentinel --version
   ```

   (pipx: `pipx install --force sentinel-pipeline`.) If you installed 0.1.0b7 from git, the tool is registered as `sentinel`; remove it first, because `uv tool install sentinel-pipeline` would otherwise leave two installs that both provide the `sentinel` command: `uv tool uninstall sentinel && uv tool install sentinel-pipeline` (pipx: `pipx uninstall sentinel && pipx install sentinel-pipeline`). The PyPI wheel (`sentinel_pipeline-1.1.0-py3-none-any.whl`) includes the dashboard. A git install (`git+https://github.com/chhunlyyy/sentinel@v2.1.0`) has the CLI but not the dashboard UI (see [installation](installation.md#the-dashboard-ui)). Requirements are unchanged: Python 3.10 or newer, `pyyaml` and `jsonschema`.
2. Update the skills (`npx skills@latest update`, or pin with `npx skills@latest add chhunlyyy/sentinel@v2.1.0 --skill '*' -a <agent>`) so `/sentinel` drives version 2 runs.
3. In each workspace run `sentinel doctor`. It exits 0 for a 0.1.0b7 config and lists the optional new settings the config does not have (`policies`, `providers`, `agents`, `tdd`, `verification`, `notifications`). None is required; see [config](config.md).
4. If you use Claude Code, run `sentinel sync-adapters` again to get the new deny rules (below).

The first command that needs the registry creates `.sentinel/sentinel.db` and indexes the 0.1 runs it finds. Nothing else has to be migrated.

## What changes

- `sentinel run new <slug>` creates a **version 2 run** unless you pass `--legacy`, `--tier` or `--adhoc`. Use `--legacy` (or `--tier N`) to keep creating 0.1 runs; use `--type feature|bug|docs|refactor|migration|security|chore` for version 2.
- `sentinel run update`, `sentinel resume` and `sentinel stage run` are refused for version 2 runs (exit 5). Use `sentinel next <slug>` and `sentinel task run` instead; the commands work as before on 0.1 runs.
- `sentinel run finish` on a version 2 run needs an interactive terminal. Run it yourself at your terminal; the agent cannot.
- Configs that do not set `state.auto_sync_push` now mean **off** (they meant on). Configs created by 0.1 `sentinel init` contain `auto_sync_push: true`, so they stay **on** after the upgrade (`sentinel doctor` notes it). Set `auto_sync_push: false` to stop automatic publishing; only new 1.1.0 configs default to false. Version 2 runs never auto-push, whatever the setting; publish with `sentinel sync push`.
- `sentinel sync-adapters` adds deny rules to `.claude/settings.json` for `sentinel approve`, `sentinel accept`, `sentinel resolve`, the dashboard command and the token file (`server.json` in `~/.config/sentinel`). They are advisory; see [security](security.md#residual-risks). Run it again after upgrading.
- A registry `.sentinel/sentinel.db` is created in each workspace and 0.1 runs are indexed (read only, as workflow version 0.1). Add `.sentinel/` to `.gitignore` if it is not there (`sentinel init` does).
- `sentinel stats` keeps its 0.1 keys (counting 0.1 runs) and adds a `v2` section; use `--from`, `--to` and `--format md` for ranges and tables.
- Use the new commands: `sentinel next`, `review`, `approve`, `accept`, `report`, `resolve`, `verify`, `task`, `triage`, `dashboard`, `notifications`, `audit` and `backup`. Read [workflow](workflow.md), [dashboard](dashboard.md) and [operations](operations.md).

- Configs with `rules.no_permanent_frontend_tests: true` and no QA scenario driver are now refused at R12 for frontend and mobile repos (run NEEDS_HUMAN, `E_PRECONDITION`, no cycle, no task). Before 1.1.0 the rule only produced the release check. To fix it, set `qa.driver`, `qa.scenario_run`, `qa.scenario_report` and a `qa.start_commands` entry for each client repo (see [config](config.md#qa)) and run `sentinel resolve <slug> --refresh-config -m "driver configured"` on the parked run; Sentinel shows which config keys change and asks you to type the first 8 characters of the new config hash. Or turn the rule off (`rules.no_permanent_frontend_tests: false`) and refresh the same way; frontend behaviors then use test files like backend ones.

## What is removed

- `sentinel submit` is removed. It existed only in development builds of the version 2 flow; a version 2 task is run with `sentinel task run <task-id>`, and a native task is finished with `sentinel task complete <task-id>`.
- The 0.1 stage pipeline is not removed; it only no longer applies to version 2 runs.

## What is untouched

- Existing 0.1 runs: `.sentinel/runs/<slug>/state.json` and every file in it are not rewritten by 1.1.0. `sentinel resume <slug>` prints the same next stage as before, `sentinel stats` still counts them, and `sentinel run update` and `sentinel run finish` still work on them.
- `sentinel.config.yaml` is not rewritten. Unknown-to-0.1 keys are optional.
- The shared repo, its locks and `sentinel sync push` for 0.1 runs.
- Stage skills (`/sentinel-review`, `/sentinel-qa`, and so on) and `sentinel stage run`.

## Rollback

You can go back to 0.1.0b7 at any time:

```bash
uv tool install --force git+https://github.com/chhunlyyy/sentinel@v0.1.0b7
```

0.1.0b7 never reads the registry, so it keeps working on `state.json` of the 0.1 runs. Runs created by 1.1.0 (version 2 runs) are **not visible to 0.1.0b7**: they live only in the registry, which it ignores. Finish or export them first (`sentinel run export <slug>`). Leaving `.sentinel/sentinel.db` in place is harmless; a later 1.1.0 install picks it up. A registry from a development build of 1.1.0 is copied to `sentinel.db.bak-<schema version>` before it is migrated.
