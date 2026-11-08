---
stage: rollout
per_repo: false
writes: run
---

Collect what a deploy of this increment must change. Read every `*-coder-result.md` and the diff.

List, in deploy order:

- New or changed environment variables and config keys, with defaults and where to set them.
- Feature flags and their initial state.
- Schema or data migrations, whether they are reversible, and the backup or rollback step.
- Order of deploy across repos (for example service before client).
- Backward-compatibility window: old clients against the new service, and the reverse.
- Anything that needs a manual step or a data fix after deploy.

Write `{{run_dir}}/rollout-notes.md`. Write "none" for any empty category. Do not edit source.
