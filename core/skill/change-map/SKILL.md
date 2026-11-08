---
name: sentinel-change-map
description: Builds an interactive HTML change map of everything a Sentinel run changed across all configured repos. Files are laid out in columns along the request flow (UI, state, API client, controllers, services, data, migrations, config, tests) with links between files that use each other. Click a file to see what it does, what changed and the key diff lines, or pick a flow to walk a feature end to end. Run it as the last step of every run, after the release check passes and before the final report. Also use it when asked what changed, which files were touched and why, or to review uncommitted work before committing.
---

# Sentinel change map

A run can touch 100+ files across several repos, and a plain diff does not show what each file does or how the pieces connect. This turns the run's changes into one self-contained HTML page opened locally. The page contains source code: keep it on the requester's machine and never publish it.

- Columns come from each repo's stack profile (`lanes` in `{{sentinel_home}}/profiles/<profile>.json`). Repos with different stacks get their own columns side by side.
- Links connect files that use each other: imports, class references, HTTP calls from a client repo to a server endpoint, entity to migration table. Unchanged files a changed file connects to are shown dashed.
- Clicking a file shows its role, what changed, its links, and key diff blocks. Flows walk a feature as numbered steps.

## Workflow

Run commands from the workspace root. Replace `<slug>` with the run slug; files live in `.sentinel/runs/<slug>/`.

### 1. Scope

Base revisions default to HEAD, which covers all uncommitted work. If part of the run was already committed, pass the baseline SHAs from `state.json` (`baseline`) with `--base <repo_id>=<sha>`. Files that were uncommitted before the run started must be marked as pre-existing in their notes.

### 2. Collect

```bash
python3 {{sentinel_home}}/scripts/change_map/collect_changes.py \
  --config sentinel.config.yaml --out .sentinel/runs/<slug>/changes.json \
  [--base <repo_id>=<sha>]
```

It prints the changed files (your checklist for notes) and the unchanged context files they connect to. If a changed file looks like a secret (`.env`, keys, credentials) it exits with code 2 and writes nothing. Tell the requester and ask how to proceed. Never put such a file in the page.

### 3. Understand before describing

Read the decisions file, the spec, each stage result, and the diffs, one column at a time:

```bash
python3 {{sentinel_home}}/scripts/change_map/dump_diffs.py .sentinel/runs/<slug>/changes.json --lane service
```

Block numbers it prints are the `key_hunks` indexes. Never describe a file from its name alone.

### 4. Ask when something is unclear

If you cannot tell why a file changed, collect every such file and ask the requester once, before rendering. Name the file and what you saw. If the requester cannot answer, or you cannot reach them, write an honest "unclear" note and add the question to `questions` in notes.json. Do not guess.

### 5. Write notes.json

Save as `.sentinel/runs/<slug>/notes.json`:

```json
{
  "title": "Short run title",
  "overview": "Plain paragraph: what users can do now and the main moving parts.",
  "questions": [],
  "flows": [
    {
      "id": "submit",
      "name": "Submit a request",
      "description": "One sentence on what the user does.",
      "steps": [
        {"node": "<repo_id>:<path>", "note": "What this hop does."},
        {"node": "<repo_id>:<path>", "note": "Next hop."}
      ]
    }
  ],
  "files": {
    "<repo_id>:<path>": {"role": "What the file is for.", "summary": "What changed in this run.", "key_hunks": [0]}
  }
}
```

- Keys are the exact ids from the collect step.
- `summary` is required for every changed file outside the tests column, except barrels (index files that only re-export) and binary files. Say what behavior changed, not "updated method".
- `role` for every new file and any file whose purpose is not obvious.
- `key_hunks`: 0-based diff block indexes that carry the change. Skip import-only or rename-only blocks. Omit to show the first two.
- Write 2 to 5 flows, one per user-visible capability or important internal path. Order steps the way a request travels, give each a note, use only ids present in changes.json, and do not invent hops.
- Plain short sentences for a teammate who missed the run.

### 6. Render

```bash
python3 {{sentinel_home}}/scripts/change_map/render_map.py \
  --changes .sentinel/runs/<slug>/changes.json \
  --notes .sentinel/runs/<slug>/notes.json \
  --out .sentinel/runs/<slug>/change-map.html --strict
```

Add `--no-em-dashes` when the `no_em_dashes` rule is on. `--strict` refuses to write when a changed file has no summary, a note key matches no file, there are fewer than 2 or more than 5 flows, a flow has an unknown or note-less step or fewer than 2 steps, or a `key_hunks` index is out of range or repeated. Fix the notes and re-run.

### 7. Hand over

Give the requester the absolute path of the HTML file and list any open questions in the report. Re-running with the same slug overwrites the files: after a small fix, re-collect and update only the notes for files that changed.
