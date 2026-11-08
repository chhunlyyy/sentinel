---
name: sentinel-resume
description: Continues a Sentinel run that was interrupted by a usage limit, a closed session or a crash. Use when the user says resume, continue the run, or pick up where we left off with Sentinel.
---

Continue an interrupted Sentinel run.

1. If the user gave no run name, list `.sentinel/runs/*/state.json`. A run without an `outcome` field is still open. Show each open run's slug, tier and last completed stage, and ask which to continue.
2. Run `sentinel resume <slug>`. It prints the next stage, the pending stages, the rounds used, and any loop that hit its cap.
3. If the run has an `outcome`, it is finished; say so and stop.
4. If a loop is capped, do not continue. Say the increment is not production-ready, list the open findings from the latest result files, and ask the user how to proceed.
5. Otherwise read `.sentinel/runs/<slug>/decisions.md` and the newest `*-result.md` files in that folder, then continue from the next stage by following the `sentinel` skill (its "Running a stage" and "Pipeline" sections). Do not redo stages already in `completed`, and re-verify the last stage's result before building on it.
