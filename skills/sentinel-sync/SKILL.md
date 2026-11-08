---
name: sentinel-sync
description: Publishes a finished Sentinel run's specs, regression tests and proposed invariants to the team's shared repo for review, after scrubbing secrets and asking for approval. Use when the user asks to push, publish or share the results of a Sentinel run.
---

Publish a finished run to the team's shared repo. Pushing sends content outside the machine, so every step that publishes needs the user's explicit approval.

1. Identify the run: ask for the slug, or list `.sentinel/runs/*/state.json` and ask. The run should be finished or at least have passed the release check; if it is not, say so and ask whether to continue.
2. Run `sentinel sync pull` first so you start from the latest shared repo.
3. Run `sentinel scrub`, then `sentinel scrub --check`. If the check fails, show the files and kinds of findings it prints (never the secret values) and stop; the user must remove the data first.
4. Show what would be published: `git -C .sentinel/shared status --short`, and the contents of `.sentinel/runs/<slug>/proposed-invariants.md` if it exists. Ask for approval to push.
5. After approval, run `sentinel sync push <slug> --yes`. It creates a `sentinel/<slug>` branch in the shared repo and never force-pushes. Tell the user to open a pull request from that branch.
6. Run `sentinel run finish <slug> --outcome passed` if the run is not already closed, so its lock is released.
7. If the shared repo is on GitHub and the user wants CI, `sentinel shared ci` writes the workflow file; pushing it needs a token with the workflow permission.
