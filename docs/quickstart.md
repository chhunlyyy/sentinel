# Quickstart

## 1. Install

Two parts, once per machine: the engine (the `sentinel` command) and the skills (what your AI tool shows as `/sentinel`).

```bash
uv tool install git+https://github.com/chhunlyyy/sentinel
```

No `uv`? `pipx install git+https://github.com/chhunlyyy/sentinel` works the same way. Upgrade with `uv tool upgrade sentinel`.

The skills are installed in step 5, after the project is set up. The [installation guide](installation.md) has prerequisites, per-tool details and troubleshooting.

## 2. Create the team's shared repo (required, once per team)

Sentinel will not run without it. Create an **empty private** git repository on your own git server (GitHub, Gitea, GitLab, and so on), for example `myteam-sentinel-shared`. Leave the README, `.gitignore` and license options off. It holds the team's project invariants, specs and regression suite, so every teammate and CI sees the same ones. Specs describe your internal systems, so keep it private and give your teammates write access.

You only need its clone URL. Sentinel fills an empty repo with starter files (`README.md`, `invariants.md`, `guidelines/`, `specs/index.*`) the first time you connect. CI is optional: `sentinel shared ci` writes the workflow into `.sentinel/shared` for you to commit. On GitHub, pushing a workflow file needs a token with the `workflow` scope (classic) or the Workflows permission (fine-grained). For a quick local trial with no server, a bare repo on disk works: `git init --bare ~/sentinel-shared.git`, then use that path as the URL.

## 3. Initialize your workspace

The workspace is the folder that contains your repos, or the repo itself for a single project.

```bash
cd my-workspace
sentinel init
```

`init` asks for:

1. **The shared repo URL** (required; it will not continue without one). It checks the repo is reachable and clones it into `.sentinel/shared/`. If the repo was empty, it commits the starter files locally and prints the one command that publishes them: `git -C .sentinel/shared push -u origin main`. Run that once.
2. The project shape: single, fullstack, fullstack-mobile, or custom.
3. For each repo: its path and its stack profile (auto-detected from files such as `pubspec.yaml`, `package.json`, `build.gradle`).

It writes `sentinel.config.yaml`, creates `.sentinel/`, and adds the state folders to `.gitignore`. If the repo is not reachable yet (no access, VPN off), the config is still saved with a warning; once you have access run `sentinel sync pull`. A teammate joining an existing setup runs `sentinel init` with the same URL, or `sentinel shared set <url>` in a workspace that already has a config. For unattended setup:

```bash
sentinel init --shape fullstack --non-interactive --shared-repo <url> --set backend.path=./api --set frontend.path=./web
```

Then open `sentinel.config.yaml` and:

- set `routing` and `runners` for the AI tools your team uses (see [config.md](config.md)),
- turn on the `rules` you want (all default to off),
- set `qa` for how to start your services and which driver to use.

## 4. Check the setup

```bash
sentinel doctor
sentinel sync pull
```

`doctor` validates the config and reports missing tools, repo paths, runner CLIs, and a missing or not-yet-cloned shared repo; it fails until the shared repo is connected, and `sentinel run new` refuses to start a run in that state. `sync pull` fetches the latest version of the shared repo into `.sentinel/shared/`.

## 5. Install the skills into your AI tool

```bash
npx skills@latest add chhunlyyy/sentinel -a claude-code
```

Use the agent name of your tool: `claude-code`, `antigravity-cli`, `codex`, `cursor`, `opencode`, `devin`, `windsurf`, `amp`, `pi`, and more. Repeat `-a` for several tools, or leave `-a` off to pick from a list. The skills go into the project (your tool's skills folder, such as `.claude/skills/` or `.agents/skills/`), so commit them and your teammates get them with the repo. Add `-g` to install only for yourself.

You get `/sentinel`, `/sentinel-setup`, `/sentinel-resume`, `/sentinel-status`, `/sentinel-sync` and `/sentinel-change-map`. Nothing project-specific is generated: when a stage runs, the skill asks `sentinel stage render` for that stage's instructions, built from your config, rules and guidelines. Update later with `npx skills@latest update`.

The skills run with your agent's full permissions, so read them before installing; they are plain markdown. To pin a version, add the tag and keep `--skill '*'`: `npx skills@latest add chhunlyyy/sentinel@v0.1.0b4 --skill '*' -a <agent>`.

### Legacy: generated agent files

`sentinel sync-adapters --tool claude|agents|codex|gemini|cursor` still writes per-project agent files (named stage agents under `.claude/agents/`, or a Sentinel block in `AGENTS.md`). Use it only if you want fixed named agents; the skills above do not need it.

## 6. Run a task

Ask your agent: `/sentinel add an export button to the report page`. The agent follows the `sentinel` skill:

1. Picks the tier and prints one line with the reason.
2. For tier 3 and 4, interviews you about decisions and records them in `.sentinel/runs/<slug>/decisions.md`.
3. Runs `sentinel run new <slug> --tier N` (locks the slug for the team), then walks the stages.
4. Records progress with `sentinel run update` after each stage.

If a session stops or hits a usage limit, `sentinel resume <slug>` shows the next stage, the session ids, and which loops hit their cap.

## 7. Finish

- `sentinel scrub` clears tokens, emails, credentials, and home paths from runs and cache.
- `sentinel sync push <slug> --auto` (by default; with `state.auto_sync_push: false`, `--yes` after you approve) merges the new specs, regression tests, and proposed invariants into the shared repo's main branch, with no pull request. If the merge conflicts, the agent resolves it and runs `sentinel sync push <slug> --continue`. It refuses if the scrub check fails.
- `sentinel run finish <slug>` closes the run and releases the lock.
- `sentinel stats` shows tier mix, escalations, average rounds, and cost per stage.
- `sentinel clean` prunes old runs and cache. `sentinel clean --db` also drops the throwaway QA schemas.

## Running a stage by hand or on another tool

```bash
sentinel stage run --stage coder --repo backend --slug add-export --brief .sentinel/runs/add-export/backend-coder-brief.md
```

The runner is chosen from `routing` (or `--runner`). Before and after the stage it snapshots every repo and exits with code 3 if the stage wrote outside its repo, committed, or changed the Sentinel config.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `sentinel.config.yaml not found` | Run from inside the workspace, or pass `--dir`. |
| `slug X is locked by another run` | A teammate or an earlier run holds it. Pick another slug, or delete a stale lock: `git push origin :refs/sentinel/locks/<slug>` from `.sentinel/shared`. |
| `scrub check failed; nothing pushed` | `sentinel scrub --check` lists the files. Remove the data, or run `sentinel scrub --shared` to redact it. |
| `doctor` says a runner CLI is not installed | Install it, or route that stage to another runner. |
| Exit code 3 from `run_stage.py` | The stage broke its write boundary. Review the listed files; nothing was reverted automatically. |
