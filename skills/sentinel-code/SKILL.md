---
name: sentinel-code
description: Runs only the Sentinel coder stage on its own, without the full pipeline, to implement a change in one repo, following its commands, guidelines and the active rules. Use when asked to implement, build or fix something in a specific repo without the full pipeline. The full pipeline (/sentinel) runs this same stage.
---

You run one stage on its own: implement a change in one repo. `/sentinel` runs the same stage inside the full pipeline, with the same instructions. `sentinel` below is the Sentinel command line tool; if it is not found, tell the requester to install it with `uv tool install git+https://github.com/chhunlyyy/sentinel` and stop.

## Steps

1. Run `sentinel doctor`. No `sentinel.config.yaml`: use the `sentinel-setup` skill first. Other problems: show them and continue only if this stage does not need them.
2. Pick the run. If the requester names an open run, use its slug and folder. Otherwise create a standalone one, which needs no lock and no shared repo: `sentinel run new code-$(date +%Y%m%d-%H%M) --adhoc`. Note the slug it prints.
3. Ask only for what is missing, in one round: what to build or fix, the repo, the files involved, and the spec or contract if there is one. Write it to `.sentinel/runs/<slug>/<repo>-coder-brief.md`, with the exact paths involved.
   Ask which repo (one of the `repos` ids in `sentinel.config.yaml`) if it is not obvious; for several repos, run the stage once per repo, in parallel if your tool can.
4. Run `sentinel stage render --stage coder --repo <id> --slug <slug>`. It prints the complete instructions for this project. Do the stage in its own fresh context, not in this conversation, so the result is not marked by what you already know. Use the first of these your tool offers:
   - A subagent: give it the rendered instructions and the brief as its task. In Claude Code use the Agent tool with a general-purpose agent. In Antigravity call `invoke_subagent` with the built-in `self` subagent. In other tools use their subagent, delegate or task feature.
   - A fresh headless session: `sentinel stage run --stage coder --repo <id> --slug <slug> --brief <brief file> --runner <claude|agy|codex|gemini>`. Exit 3 means the stage wrote outside its repo, committed or touched the config (show the files, revert nothing without agreement); exit 1 means the tool failed (retry once).
   - Inline, only if neither exists. Say so at once. State in your report that it ran in the same context.
5. Record how it ran: `sentinel run update <slug> --stage coder --session coder=subagent` (or `headless`, `inline`).
6. Read the result (<repo>-coder-result.md) in `.sentinel/runs/<slug>/` and check the claims yourself (re-run the failing test, the command, the finding) before you report. Show the requester the verdict and any findings. The coder never commits or pushes.
7. For a standalone run, close it: `sentinel run finish <slug> --outcome passed|stopped`.

## Rules

- This skill does not run any other stage. Findings that belong to another stage are reported, not fixed here.
- Never commit or push.
- The active rules in `sentinel.config.yaml` are already inside the rendered stage; follow them in your own output too.
