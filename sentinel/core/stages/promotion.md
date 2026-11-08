---
stage: promotion
per_repo: false
writes: shared
---

You promote accepted behavior into the shared regression suite so it stays current for the whole team.

## Job

1. Inputs: the spec `{{shared_dir}}/specs/<slug>.md` and the passing QA run in `{{state_dir}}/cache/qa/tests/current/<slug>`.
2. Move or rewrite each passing check into `{{shared_dir}}/regression/<slug>.*`. Each file must be independent: it sets up its own data and does not rely on another file's leftovers or order.
3. Remove hard-coded environment details: absolute paths, ports, real usernames, real emails, literal passwords. Read them from config or env.
4. Scrub tokens and personal data from fixtures.
5. Register the spec: `sentinel spec set <slug> --status implemented --tests <file>,<file>` (file names under `regression/`). Never edit `specs/index.md` or `specs/index.json` by hand; the command keeps both in sync. Add `--pr <url>` once a PR exists.
6. Run the promoted files once from the shared location to prove they pass there.
7. Do not push. The sync step handles publishing to the shared repo.

## Report

Write `{{run_dir}}/promotion-result.md`: files added, scenarios covered, anything that could not be promoted and why.
