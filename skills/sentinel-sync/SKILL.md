---
name: sentinel-sync
description: Publishes a finished Sentinel run's specs, regression tests and proposed invariants to the team's shared repo straight into its main branch, after scrubbing secrets, with no pull request. Use when the user asks to push, publish or share the results of a Sentinel run.
---

Publish a finished run to the team's shared repo. Asking for this skill is the approval to publish. Content goes straight into the shared repo's main branch: no pull request and no human review, so the scrub check is the gate.

1. Identify the run: ask for the slug, or list `.sentinel/runs/*/state.json` and ask. The run should be finished or at least have passed the release check; if it is not, say so and ask whether to continue.
2. Run `sentinel sync pull` first so you start from the latest shared repo.
3. Run `sentinel scrub`, then `sentinel scrub --check`. If the check fails, show the files and kinds of findings it prints (never the secret values) and stop; the user must remove the data first.
4. Show what will be published: `git -C .sentinel/shared status --short`, and the contents of `.sentinel/runs/<slug>/proposed-invariants.md` if it exists.
5. Run `sentinel sync push <slug> --yes`. It commits to the shared repo's main branch, merges what others pushed meanwhile, pushes, and never force-pushes. Conflicts in the shared repo are for you to resolve, not a human. If `sentinel sync push` exits 4, it lists the conflicted files in `.sentinel/shared`. For each one: open it, keep the intent of both sides, and remove every conflict marker. `specs/index.json` and `index.md`: keep every entry from both sides. `invariants.md` and `proposals/`: keep every rule from both sides, renumbering an ID only when two different rules got the same one. Another run's content always stays; re-apply this run's change on top of it. Never force-push. Then run `sentinel sync push <slug> --continue`, which checks that no markers or unmerged files remain, scrubs, commits the merge and pushes. If two changes truly contradict and you cannot reconcile them safely, run `git -C .sentinel/shared merge --abort`, leave the run unpublished and say so in the final report.
6. Run `sentinel run finish <slug> --outcome passed` if the run is not already closed, so its lock is released.
7. If the shared repo is on GitHub and the user wants CI, `sentinel shared ci` writes the workflow file; pushing it needs a token with the workflow permission.
