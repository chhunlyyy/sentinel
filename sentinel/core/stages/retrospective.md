---
stage: retrospective
per_repo: false
writes: shared
---

Decide whether this run uncovered a project-wide rule that every future increment should satisfy.

1. Read the reviewer and QA results, the decisions file, and any bug a hardener's tests caught.
2. A candidate invariant must be general, testable in one sentence, and something that already caused or nearly caused a defect. A one-off fix is not an invariant.
3. For each candidate write an entry in the format from `{{shared_dir}}/invariants.md` (ID, rule, why, check) into `{{run_dir}}/proposed-invariants.md`.
4. Do not edit `invariants.md` directly. The sync step stores them as `proposals/<slug>.md` in the shared repo, where they wait until someone adds them to `invariants.md`.
5. If nothing qualifies, write "no new invariants" and stop.
