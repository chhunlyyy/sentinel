---
name: sentinel-release-check
description: Runs only the Sentinel release check on its own, the production-readiness gate (build, lint, tests, secret scan, migration and dependency notices, project extra checks). Use when asked to check if the changes are ready to ship, run the release check, or verify a build. The full pipeline (/sentinel) runs the same gate.
---

You run the release check on its own. `/sentinel` runs the same gate inside the full pipeline. `sentinel` below is the Sentinel command line tool; if it is not found, tell the requester to install it with `uv tool install git+https://github.com/chhunlyyy/sentinel` and stop.

## Steps

1. Run `sentinel doctor`. No `sentinel.config.yaml`: use the `sentinel-setup` skill first.
2. Run `sentinel release-check`. Pass `--repo <id>` for each repo the change touched (the default checks every repo with uncommitted changes, including unrelated work in progress). Pass `--skip build` when a dev server is running on that repo, because a build overwrites its output folder.
3. Report `RELEASE CHECK PASSED` or each failure with its repo and output line. Do not fix failures here: send each to `/sentinel-code` for the owning repo, then run the check again.

## Rules

- Never commit or push.
- A failing check means the change is not ready to ship; say so plainly.
