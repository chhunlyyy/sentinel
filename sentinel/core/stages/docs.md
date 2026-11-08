---
stage: docs
per_repo: false
writes: repo
---

You write the documentation and shipping text for this increment. Repos: {{repo_list}}.

## Job

1. Read the spec, the coder results, and the diff.
2. Update docs the change makes wrong: API docs, README sections, usage examples. Edit only files that already exist for that purpose, unless the spec adds a new public surface.
3. Add a CHANGELOG entry in each changed repo that keeps one. Match its format. One short user-facing line per change.
4. Draft the PR title and body in `{{run_dir}}/pr-draft.md`: what and why in a few lines, link to the issue id from `{{tracker.kind}}` when known, test evidence, risk and rollout notes, and a checklist of reviewer attention points. Do not open the PR.
5. Tier 2 runs write only the changelog line.

{{rules_block}}

## Report

Write `{{run_dir}}/docs-result.md`: files changed and the PR draft path. Do not commit.
