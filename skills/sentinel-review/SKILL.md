---
name: sentinel-review
description: Runs only the Sentinel reviewer stage on its own, without the full pipeline, to review the current uncommitted changes skeptically against a spec or brief, the project invariants, correctness and security, without editing anything. Use when asked for a review, a second opinion, or a check before committing. The full pipeline (/sentinel) runs this same stage.
---

You run one stage on its own: review the current changes. `/sentinel` runs the same stage inside the full pipeline, with the same instructions. `sentinel` below is the Sentinel command line tool; if it is not found, tell the requester to install it with `uv tool install git+https://github.com/chhunlyyy/sentinel` and stop.

## Steps

1. Run `sentinel doctor`. No `sentinel.config.yaml`: use the `sentinel-setup` skill first. Other problems: show them and continue only if this stage does not need them.
2. Pick the run. If the requester names an open run, use its slug and folder. Otherwise create a standalone one, which needs no lock and no shared repo: `sentinel run new review-$(date +%Y%m%d-%H%M) --adhoc`. Note the slug it prints.
3. Ask only for what is missing, in one round: what the change is supposed to do (a spec path, a short description, or just "review the diff"), which repos to look at, and any uncommitted files that are not part of this change. Write it to `.sentinel/runs/<slug>/reviewer-brief.md`, with the exact paths involved.
4. Run `sentinel routing --stage reviewer`. If the mode is `headless`, the team chose a runner and model for this stage: run `sentinel stage run --stage reviewer --slug <slug> --brief <brief file>` (it applies them) and skip to step 5. Otherwise run `sentinel stage render --stage reviewer --slug <slug>`, which prints the complete instructions for this project. Do the stage in its own fresh context, not in this conversation, so the result is not marked by what you already know. Use the first of these your tool offers:
   - A subagent: give it the rendered instructions and the brief as its task. In Claude Code use the Agent tool with a general-purpose agent. In Antigravity call `invoke_subagent` with the built-in `self` subagent. In other tools use their subagent, delegate or task feature.
   - A fresh headless session: `sentinel stage run --stage reviewer --slug <slug> --brief <brief file> --runner <claude|agy|codex|gemini>`. Exit 3 means the stage wrote outside its repo, committed or touched the config (show the files, revert nothing without agreement); exit 1 means the tool failed (retry once).
   - Inline, only if neither exists. Say so at once. Do not run this stage inline: ask the requester how to proceed.
5. Record how it ran: `sentinel run update <slug> --stage reviewer --session reviewer=subagent` (or `headless`, `inline`).
6. Read the result (reviewer-result.md) in `.sentinel/runs/<slug>/` and check the claims yourself (re-run the failing test, the command, the finding) before you report. Show the requester the verdict and any findings. The reviewer writes nothing but the result file. Fixes go to `/sentinel-code`.
7. For a standalone run, close it: `sentinel run finish <slug> --outcome passed|stopped`.

## Rules

- This skill does not run any other stage. Findings that belong to another stage are reported, not fixed here.
- Never commit or push.
- The active rules in `sentinel.config.yaml` are already inside the rendered stage; follow them in your own output too.
