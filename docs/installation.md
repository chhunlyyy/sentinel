# Installation

Sentinel has two parts, installed separately:

| Part | What it is | Installed with | Scope |
|---|---|---|---|
| The engine | The `sentinel` command: config, run state, stage prompts, release check, shared-repo sync | `uv tool install` (or `pipx`) | once per machine |
| The skills | `/sentinel`, `/sentinel-setup` and four more, which your AI tool loads | `npx skills` | once per project (committed) or once per machine (`-g`) |

Linux is the only platform tested so far.

## 1. Prerequisites

| Tool | Needed for | Check | Install |
|---|---|---|---|
| Python 3.10 or newer | the engine | `python3 --version` | `uv` can fetch one for you |
| [uv](https://docs.astral.sh/uv/) (or pipx) | installing the engine | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | `npx`, to install the skills | `node --version` | https://nodejs.org or your package manager |
| git | the shared repo | `git --version` | your package manager |
| An AI coding tool | running the skills | | Claude Code, Antigravity, Codex, Cursor, OpenCode, Devin, Windsurf, Amp, Pi, and others |

Only if you use them: `mysql` and `mysqldump` for the MySQL QA data plugin, and Playwright for browser QA.

## 2. Install the engine

```bash
uv tool install git+https://github.com/chhunlyyy/sentinel
sentinel --version
```

If `sentinel` is not found afterwards, run `uv tool update-shell` and open a new terminal (the command lives in `~/.local/bin`).

No `uv`: `pipx install git+https://github.com/chhunlyyy/sentinel` does the same. As a last resort, `pip install git+https://github.com/chhunlyyy/sentinel` inside a virtual environment.

## 3. Install the skills

Run this in the project you want to use Sentinel in (the workspace folder that holds your repos, or the repo itself):

```bash
npx skills@latest add chhunlyyy/sentinel -a claude-code
```

Use your tool's agent name. Repeat `-a` for several tools, or leave it off to choose from a list.

| Tool | `-a` name | Where the skills end up |
|---|---|---|
| Claude Code | `claude-code` | `.claude/skills/` |
| Antigravity CLI | `antigravity-cli` | `.agents/skills/` |
| Codex | `codex` | `.agents/skills/` |
| Cursor | `cursor` | `.agents/skills/` |
| OpenCode | `opencode` | `.agents/skills/` |
| Amp | `amp` | `.agents/skills/` |
| Pi | `pi` | `.agents/skills/` |
| Gemini CLI | `gemini-cli` | `.agents/skills/` |
| Devin | `devin` | `.devin/skills/` |
| Windsurf | `windsurf` | `.windsurf/skills/` |

Tools in the `.agents/skills/` group read that folder directly. Claude Code, Devin and Windsurf use their own folder: with only one of them selected, the skills are copied there; when you select them together with a tool from the shared group, `.agents/skills/` holds the one copy and they get links to it (add `--copy` for real copies). Other agents are supported too: `npx skills@latest add --help` lists them.

Useful options:

| Option | Effect |
|---|---|
| `-g` | install for you (your home folder) instead of the project |
| `-s <name>` | install only some skills, for example `-s sentinel -s sentinel-setup` |
| `--copy` | copy files instead of linking them |
| `-l` | list the skills without installing |
| `-y` | do not ask for confirmation |

**Read before you install.** Skills run with your agent's full permissions. Sentinel's are plain markdown in [skills/](../skills/): they tell the agent to run `sentinel` commands, git commands in the shared repo, and your project's build and test commands. To pin a version so an update cannot change them unnoticed, add a tag and keep `--skill '*'`: `npx skills@latest add chhunlyyy/sentinel@v0.1.0b1 --skill '*' -a <agent>`. Without `--skill` the installer reads the tag as a skill name and installs nothing.

What you get:

| Command | What it does |
|---|---|
| `/sentinel <task>` | runs a feature or bug fix through the pipeline at the right tier |
| `/sentinel-setup` | connects the team's shared repo, picks the project shape, writes the config |
| `/sentinel-resume` | continues an interrupted run |
| `/sentinel-status` | setup health, open runs, statistics |
| `/sentinel-sync` | publishes a finished run to the shared repo, after approval |
| `/sentinel-change-map` | builds the HTML map of what a run changed |

How each tool shows a skill differs. Some list it as a slash command; others load it automatically when your request matches its description. If a tool shows no slash command, just ask: "run sentinel on: <task>".

## 4. Set up the project

Once per project. In your tool, run `/sentinel-setup`, or in a terminal:

```bash
sentinel init
sentinel doctor
```

You need the URL of an empty private git repository your team owns (the shared repo). Without it Sentinel does not run a task. For a quick trial with no server, use a bare repo on disk: `git init --bare ~/sentinel-shared.git`. The full walkthrough is in [quickstart.md](quickstart.md).

## 5. Verify the install

```bash
sentinel --version        # prints the version
sentinel selftest         # builds a throwaway workspace and checks the engine; ends with "0 failed"
sentinel doctor           # inside your project: checks config, tools and the shared repo
npx skills@latest list    # lists the installed skills
```

Then in your AI tool, start a new session (many tools only load skills at startup) and type `/sentinel`.

## 6. Roll it out to a team

1. One person does steps 2 to 4 and commits the skills folder(s) (`.agents/skills/`, plus `.claude/skills/` and the like), `skills-lock.json` and `sentinel.config.yaml`. `sentinel init` already git-ignores `.sentinel/`.
2. Each teammate installs the engine (step 2), pulls the repo, and runs `sentinel sync pull` to clone the shared repo into `.sentinel/shared/`. They need access to that repo.
3. If your QA tests use aliases for real accounts, each teammate also keeps their own `.sentinel/qa-users.json` and sets `QA_PASSWORD`; never commit those.

## 7. Upgrade

```bash
uv tool upgrade sentinel
npx skills@latest update
```

Upgrade both parts together. Pinned installs stay on their tag until you reinstall with a new one.

## 8. Uninstall

```bash
npx skills@latest remove          # choose the Sentinel skills
uv tool uninstall sentinel
```

Your `sentinel.config.yaml` and `.sentinel/` folder are not touched; delete them yourself if you want them gone. If you used the older `sentinel sync-adapters`, delete the generated files it made: `.claude/agents/` stage agents and the managed block in `AGENTS.md`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `sentinel: command not found` | `uv tool update-shell`, then a new terminal. Check `~/.local/bin` is on `PATH`. |
| `npx: command not found` | Install Node.js. It is only needed for installing the skills. |
| The skill does not show up in the tool | Start a new session; check that `.agents/skills/sentinel/SKILL.md` exists (or your tool's folder from the table above); run `npx skills@latest list`. |
| `/sentinel` says the command is missing | The engine is not installed or not on `PATH` for that tool's shell. Install it (step 2) and restart the tool. |
| `sentinel doctor` says the shared repo is missing or not cloned | `sentinel shared set <url>` (or `sentinel sync pull` if the URL is already in the config). |
| `npx skills add` cannot read the repo | If it is private, it uses your git credentials; check `git ls-remote https://github.com/chhunlyyy/sentinel.git` works for you. |
| The skills and the engine disagree after an upgrade | Upgrade both: `uv tool upgrade sentinel` and `npx skills@latest update`. |
| A tool runs old per-project agents instead of the skills | Delete the generated `.claude/agents/` files from the legacy `sync-adapters`. |

## What has and has not been tested

Verified: the engine installs from a wheel and from GitHub with `uv` on Python 3.13 and 3.14, passes its self-test, and `npx skills` discovers and installs all six skills for nine agents into one `.agents/skills/` folder with the links shown above. Not verified: how each AI tool lists and runs the skills after install, and any platform other than Linux. Please report what you see; see [beta-testing.md](beta-testing.md).
