---
name: sentinel-clean
description: Runs only the Sentinel cleaner stage on its own, without the full pipeline, to refactor recently changed code in one repo for readability without changing behavior. Use when asked to clean up, tidy or simplify the code just written. The full pipeline (/sentinel) runs this same stage.
---

You run one stage on its own: refactor recent changes for readability. `/sentinel` runs the same stage inside the full pipeline, with the same instructions. `sentinel` below is the Sentinel command line tool; if it is not found, tell the requester to install it with `uv tool install git+https://github.com/chhunlyyy/sentinel` and stop.

## Steps

1. Run `sentinel doctor`. No `sentinel.config.yaml`: use the `sentinel-setup` skill first. Other problems: show them and continue only if this stage does not need them.
2. Pick the run. If the requester names an open run, use its slug and folder. Otherwise create a standalone one, which needs no lock and no shared repo: `sentinel run new clean-$(date +%Y%m%d-%H%M) --adhoc`. Note the slug it prints.
3. Ask only for what is missing, in one round: the repo and, if not obvious from git, which changes to clean. Write it to `.sentinel/runs/<slug>/<repo>-cleaner-brief.md`, with the exact paths involved.
   Ask which repo (one of the `repos` ids in `sentinel.config.yaml`) if it is not obvious; for several repos, run the stage once per repo, in parallel if your tool can.
4. Run `sentinel routing --stage cleaner --repo <id>`. If the mode is `headless`, the team chose a runner and model for this stage: run `sentinel stage run --stage cleaner --repo <id> --slug <slug> --brief <brief file>` (it applies them) and skip to step 5. Otherwise run `sentinel stage render --stage cleaner --repo <id> --slug <slug>`, which prints the complete instructions for this project. Do the stage in its own fresh context, not in this conversation, so the result is not marked by what you already know. Use the first of these your tool offers:
   - A subagent: give it the rendered instructions and the brief as its task. In Claude Code use the Agent tool with a general-purpose agent. In Antigravity call `invoke_subagent` with the built-in `self` subagent. In other tools use their subagent, delegate or task feature.
   - A fresh headless session: `sentinel stage run --stage cleaner --repo <id> --slug <slug> --brief <brief file> --runner <claude|agy|codex|gemini>`. Exit 3 means the stage wrote outside its repo, committed or touched the config (show the files, revert nothing without agreement); exit 1 means the tool failed (retry once).
   - Inline, only if neither exists. Say so at once. State in your report that it ran in the same context.
5. Record how it ran: `sentinel run update <slug> --stage cleaner --session cleaner=subagent` (or `headless`, `inline`).
6. Read the result (<repo>-cleaner-result.md) in `.sentinel/runs/<slug>/` and check the claims yourself (re-run the failing test, the command, the finding) before you report. Show the requester the verdict and any findings. Behavior must not change: the tests the cleaner ran are listed in the result.
7. For a standalone run, close it: `sentinel run finish <slug> --outcome passed|stopped`.

## Rules

- This skill does not run any other stage. Findings that belong to another stage are reported, not fixed here.
- Never commit or push.
- The active rules in `sentinel.config.yaml` are already inside the rendered stage; follow them in your own output too.
