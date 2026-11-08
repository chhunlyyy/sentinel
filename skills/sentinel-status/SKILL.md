---
name: sentinel-status
description: Shows the state of Sentinel in this project, covering setup health, the shared repo, open and finished runs, and cost statistics. Use when the user asks what Sentinel is doing, whether it is set up correctly, which runs are open, or for stats.
---

Report the state of Sentinel in this workspace. Read only; change nothing.

1. Run `sentinel doctor` and report its result in one line, plus each problem it lists.
2. Shared repo: run `git -C .sentinel/shared status -sb` and `git -C .sentinel/shared log --oneline -3`. Say whether it is cloned, which commit it is on, and whether it is behind or ahead of the remote.
3. Runs: read `.sentinel/runs/*/state.json`. For each run give the slug, the tier (and the starting tier if it changed), the completed stages, the rounds used, and whether it is open or finished with its outcome.
4. Run `sentinel stats` and summarize: the number of runs, the tier mix, escalations, average rounds, and tokens and seconds per stage when recorded.
5. Finish with the single most useful next action, for example `sentinel resume <slug>` for an open run, or `sentinel sync pull` when the shared repo is behind.
