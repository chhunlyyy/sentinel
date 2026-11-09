---
name: sentinel-retro
description: Runs only the Sentinel retrospective stage on its own, without the full pipeline, to propose new project-wide invariants from a change or a run. Use when asked what rules this work suggests or for a retrospective. The full pipeline (/sentinel) runs this same stage.
---

You run one stage on its own: propose new project invariants from a change. `/sentinel` runs the same stage inside the full pipeline, with the same instructions. `sentinel` below is the Sentinel command line tool; if it is not found, tell the requester to install it with `uv tool install git+https://github.com/chhunlyyy/sentinel` and stop.

## Steps

1. Run `sentinel doctor`. No `sentinel.config.yaml`: use the `sentinel-setup` skill first. Other problems: show them and continue only if this stage does not need them.
2. Pick the run. If the requester names an open run, use its slug and folder. Otherwise create a standalone one, which needs no lock and no shared repo: `sentinel run new retro-$(date +%Y%m%d-%H%M) --adhoc`. Note the slug it prints.
3. Ask only for what is missing, in one round: the run or the change to look back on. Write it to `.sentinel/runs/<slug>/retrospective-brief.md`, with the exact paths involved.
4. Run `sentinel routing --stage retrospective`. If the mode is `headless`, the team chose a runner and model for this stage: run `sentinel stage run --stage retrospective --slug <slug> --brief <brief file>` (it applies them) and skip to step 5. Otherwise run `sentinel stage render --stage retrospective --slug <slug>`, which prints the complete instructions for this project. Do the stage in its own fresh context, not in this conversation, so the result is not marked by what you already know. Use the first of these your tool offers:
   - A subagent: give it the rendered instructions and the brief as its task. In Claude Code use the Agent tool with a general-purpose agent. In Antigravity call `invoke_subagent` with the built-in `self` subagent. In other tools use their subagent, delegate or task feature.
   - A fresh headless session: `sentinel stage run --stage retrospective --slug <slug> --brief <brief file> --runner <claude|agy|codex|gemini>`. Exit 3 means the stage wrote outside its repo, committed or touched the config (show the files, revert nothing without agreement); exit 1 means the tool failed (retry once).
   - Inline, only if neither exists. Say so at once. State in your report that it ran in the same context.
5. Record how it ran: `sentinel run update <slug> --stage retrospective --session retrospective=subagent` (or `headless`, `inline`).
6. Read the result (proposed-invariants.md) in `.sentinel/runs/<slug>/` and check the claims yourself (re-run the failing test, the command, the finding) before you report. Show the requester the verdict and any findings. It only proposes; adding an invariant is a pull request on the shared repo.
7. For a standalone run, close it: `sentinel run finish <slug> --outcome passed|stopped`.

## Rules

- This skill does not run any other stage. Findings that belong to another stage are reported, not fixed here.
- Never commit or push.
- The active rules in `sentinel.config.yaml` are already inside the rendered stage; follow them in your own output too.
