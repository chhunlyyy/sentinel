# Quickstart

## 1. Install

```bash
git clone <your sentinel repo url> ~/sentinel
export SENTINEL_HOME=~/sentinel
export PATH="$SENTINEL_HOME/bin:$PATH"
pip install pyyaml jsonschema
```

Add the two `export` lines to your shell profile.

## 2. Create a shared repo (once per team)

Create an empty private git repository for the team, for example `myteam-sentinel-shared`. It will hold the specs, project invariants, and the regression suite. Copy `templates/ci/shared-repo.github.yml` to `.github/workflows/sentinel-shared.yml` in that repo and set the repo variables `SENTINEL_URL` (where to clone Sentinel from) and `REGRESSION_COMMAND` (how to run your regression suite).

Specs describe your internal systems, so keep this repo private.

## 3. Initialize your workspace

The workspace is the folder that contains your repos, or the repo itself for a single project.

```bash
cd my-workspace
sentinel init
```

`init` asks for:

1. The project shape: single, fullstack, fullstack-mobile, or custom.
2. For each repo: its path and its stack profile (auto-detected from files such as `pubspec.yaml`, `package.json`, `build.gradle`).

It writes `sentinel.config.yaml`, creates `.sentinel/`, and adds the state folders to `.gitignore`. For unattended setup:

```bash
sentinel init --shape fullstack --non-interactive --set backend.path=./api --set frontend.path=./web
```

Then open `sentinel.config.yaml` and:

- set `state.shared_repo` to the shared repo URL,
- set `routing` and `runners` for the AI tools your team uses (see [config.md](config.md)),
- turn on the `rules` you want (all default to off),
- set `qa` for how to start your services and which driver to use.

## 4. Check the setup

```bash
sentinel doctor
sentinel sync pull
```

`doctor` validates the config and reports missing tools, repo paths, runner CLIs, and an empty `shared_repo`. `sync pull` clones the shared repo into `.sentinel/shared/`.

## 5. Generate files for your AI tool

```bash
sentinel sync-adapters --tool claude
sentinel sync-adapters --tool gemini
sentinel sync-adapters --tool codex
sentinel sync-adapters --tool cursor
```

- `claude` writes agent files into `.claude/agents/` and the skills into `.claude/skills/`.
- `agents`, `codex`, `gemini`, and `cursor` write a managed Sentinel block into `AGENTS.md` (your own text outside the block is kept), plus `GEMINI.md` or `.cursor/rules/sentinel.mdc`, and put the rendered prompts in `.sentinel/generated/`.

Each teammate runs this once after cloning. The Claude adapter writes the absolute path of your Sentinel checkout into `.claude/skills/`, so do not commit those skill files; the `AGENTS.md` block and `.sentinel/generated/` use `$SENTINEL_HOME` and contain no machine paths.

## 6. Run a task

Ask your agent: "Run Sentinel on: add an export button to the report page". The agent follows the orchestrator skill:

1. Picks the tier and prints one line with the reason.
2. For tier 3 and 4, interviews you about decisions and records them in `.sentinel/runs/<slug>/decisions.md`.
3. Runs `sentinel run new <slug> --tier N` (locks the slug for the team), then walks the stages.
4. Records progress with `sentinel run update` after each stage.

If a session stops or hits a usage limit, `sentinel resume <slug>` shows the next stage, the session ids, and which loops hit their cap.

## 7. Finish

- `sentinel scrub` clears tokens, emails, credentials, and home paths from runs and cache.
- `sentinel sync push <slug> --yes` (only after you approve) pushes a `sentinel/<slug>` branch of the new specs, regression tests, and proposed invariants to the shared repo for review. It refuses if the scrub check fails.
- `sentinel run finish <slug>` closes the run and releases the lock.
- `sentinel stats` shows tier mix, escalations, average rounds, and cost per stage.
- `sentinel clean` prunes old runs and cache. `sentinel clean --db` also drops the throwaway QA schemas.

## Running a stage by hand or on another tool

```bash
python3 "$SENTINEL_HOME/scripts/run_stage.py" --stage coder --repo backend --slug add-export --brief .sentinel/runs/add-export/backend-coder-brief.md
```

The runner is chosen from `routing` (or `--runner`). Before and after the stage it snapshots every repo and exits with code 3 if the stage wrote outside its repo, committed, or changed the Sentinel config.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `sentinel.config.yaml not found` | Run from inside the workspace, or pass `--dir`. |
| `slug X is locked by another run` | A teammate or an earlier run holds it. Pick another slug, or delete a stale lock: `git push origin :refs/sentinel/locks/<slug>` from `.sentinel/shared`. |
| `scrub check failed; nothing pushed` | `sentinel scrub --check` lists the files. Remove the data or run `python3 "$SENTINEL_HOME/scripts/scrub.py" .sentinel/shared`. |
| `doctor` says a runner CLI is not installed | Install it, or route that stage to another runner. |
| Exit code 3 from `run_stage.py` | The stage broke its write boundary. Review the listed files; nothing was reverted automatically. |
