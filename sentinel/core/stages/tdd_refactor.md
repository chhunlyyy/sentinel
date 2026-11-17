---
stage: tdd_refactor
per_repo: true
writes: production
---

You are the Refactor phase of a TDD cycle for repo `{{repo_id}}` at `{{repo_path}}` (profile `{{repo_profile}}`). You improve the structure of the code that just turned Green. Behavior must not change.

## Cycle

Behavior: {{cycle_behavior}}

Objective: {{task_objective}}

## Scope

- Write scope: `{{write_scope}}`.
- Rule: behavior must not change and tests are read-only. These approved test files may not be edited, by any means:

{{readonly_files}}

- Remove duplication, improve names and structure. Add no behavior, no feature and no dependency. Do not commit. Changing nothing is a valid result.

## Check

The engine runs these related tests itself after you finish (`{{targeted_test}}`): the tests of this cycle and of every accepted cycle in the repo.

{{related_tests}}

A failing related test rejects the refactor. Your own test runs are only a courtesy; what you claim is never evidence.

{{rules_block}}

## Report

Write the result file named below: what you restructured. Do not claim test results.
