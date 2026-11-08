# Quickstart

## 1. Install

```bash
uv tool install git+https://github.com/chhunlyyy/sentinel
sentinel --version
```

No `uv`? `pipx install git+https://github.com/chhunlyyy/sentinel` works the same way, or use `pip install` inside a virtual environment. Upgrade with `uv tool upgrade sentinel` (or `pipx upgrade sentinel`). To pin a release, add `@<tag>` to the URL. After an upgrade, run `sentinel sync-adapters` again in each project so the generated agents and skills match the new version.

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

## 5. Generate files for your AI tool

```bash
sentinel sync-adapters --tool claude
sentinel sync-adapters --tool gemini
sentinel sync-adapters --tool codex
sentinel sync-adapters --tool cursor
```

- `claude` writes agent files into `.claude/agents/` and the skills into `.claude/skills/`.
- `agents`, `codex`, `gemini`, and `cursor` write a managed Sentinel block into `AGENTS.md` (your own text outside the block is kept), plus `GEMINI.md` or `.cursor/rules/sentinel.mdc`, and put the rendered prompts in `.sentinel/generated/`.

Each teammate runs this once after cloning. The generated agents, skills and the `AGENTS.md` block call the `sentinel` command and contain no machine paths, so teammates only need `sentinel` installed. Re-run `sync-adapters` after upgrading Sentinel.

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
