# Data Architecture (1.1.0, draft for G1)

Requirements: `SPEC.md` section 25.

## 1. Stores

| Store | Location | Scope | Shared remotely? |
|---|---|---|---|
| Project config | `<workspace>/sentinel.config.yaml` | project | no (user's choice to commit it) |
| Workspace registry | `<workspace>/.sentinel/sentinel.db` | runs, tasks, approvals, evidence, events, config history | no |
| Run artifacts | `<workspace>/.sentinel/runs/<slug>/` | briefs, task files, results, outputs, reports | no (export bundle only) |
| Cache | `<workspace>/.sentinel/cache/` | prompts, live logs | no |
| Shared knowledge | `<workspace>/.sentinel/shared/` | invariants, guidelines, specs, features, regression suite | yes, through git sync only |
| User registry | `~/.config/sentinel/` | `projects.json`, `config.yaml`, `server.json`, `user.db` (global config history, notifications read state) | no |

Specs and Gherkin live in the shared folder (`specs/<slug>/spec.md`, `specs/<slug>/features/*.feature`), as specs do today, so the team receives them through sync.

## 2. Workspace schema (SQLite, WAL)

```sql
meta(key TEXT PRIMARY KEY, value TEXT);                       -- schema_version

runs(id TEXT PRIMARY KEY, slug TEXT UNIQUE, request TEXT, type TEXT,
     tier INTEGER, initial_tier INTEGER, state TEXT,
     execution_status TEXT, acceptance_status TEXT,
     workflow_version TEXT, config_snapshot_id INTEGER,
     created_at TEXT, updated_at TEXT, finished_at TEXT, adhoc INTEGER);

run_repos(run_id TEXT, repo_id TEXT, baseline_sha TEXT, final_sha TEXT, branch TEXT,
          PRIMARY KEY (run_id, repo_id));

artifacts(id TEXT PRIMARY KEY, run_id TEXT, kind TEXT,        -- spec, gherkin, brief, result, output, report
          version INTEGER, path TEXT, sha256 TEXT, created_at TEXT);

approvals(id TEXT PRIMARY KEY, run_id TEXT, gate TEXT,       -- specification | gherkin | security | publish | acceptance
          artifact_id TEXT, version INTEGER, sha256 TEXT, state TEXT,
          decision TEXT, approver TEXT, channel TEXT, comment TEXT,
          decided_at TEXT, invalidated_at TEXT, invalidated_reason TEXT);

tasks(id TEXT PRIMARY KEY, run_id TEXT, role TEXT, repo_id TEXT, cycle_id TEXT,
      state TEXT, provider TEXT, model TEXT, adapter TEXT, retry_of TEXT,
      task_path TEXT, result_artifact_id TEXT, error_code TEXT,
      created_at TEXT, started_at TEXT, finished_at TEXT,
      tokens INTEGER, cost REAL, seconds REAL);

task_deps(task_id TEXT, depends_on TEXT, PRIMARY KEY (task_id, depends_on));

cycles(id TEXT PRIMARY KEY, run_id TEXT, behavior TEXT, state TEXT,
       red_task TEXT, green_task TEXT, refactor_task TEXT, accepted_at TEXT);

evidence(id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, cycle_id TEXT,
         kind TEXT,                                          -- test, build, lint, typecheck, scope, secret, deps, mutation, migration
         command TEXT, cwd TEXT, exit_code INTEGER, classification TEXT,
         passed INTEGER, failed INTEGER, skipped INTEGER,
         output_artifact_id TEXT, started_at TEXT, finished_at TEXT, env TEXT);

findings(id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, source TEXT,
         severity TEXT, location TEXT, text TEXT, state TEXT, routed_to TEXT);

trace_links(run_id TEXT, from_kind TEXT, from_id TEXT, to_kind TEXT, to_id TEXT);
         -- REQ->AC, AC->scenario, scenario->cycle, cycle->file, cycle->evidence, run->acceptance

config_versions(id INTEGER PRIMARY KEY, scope TEXT, content TEXT, sha256 TEXT,
                author TEXT, channel TEXT, created_at TEXT, comment TEXT);

events(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, task_id TEXT,
       type TEXT, actor TEXT, payload TEXT, at TEXT);        -- append-only

audit(id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, channel TEXT, action TEXT,
      target TEXT, before_sha TEXT, after_sha TEXT, at TEXT,
      reason TEXT);                                          -- append-only
```

Rules:
- Every state change and its event are written in one transaction.
- `events` and `audit` are never updated or deleted (retention removes whole finished runs only, after `retention.runs`).
- IDs are short prefixed random strings (`t-`, `c-`, `e-`, `a-`).

## 3. Migrations

- `registry/migrations/NNNN_name.sql`, applied in order at open, recorded in `meta.schema_version`.
- Before a migration the engine copies the database with the sqlite backup API to `sentinel.db.bak-<version>`. Failure leaves the original untouched.
- Legacy runs: on first open, existing `runs/*/state.json` files are indexed as `runs` rows with `workflow_version = "0.1"`; their files are not changed.

## 4. Hashing

- sha256 over raw bytes. Spec: the file. Gherkin set: concatenation of `path + "\0" + bytes + "\0"` for each `.feature` file sorted by path.
- Artifacts are re-hashed when read for a decision; a mismatch is an integrity failure (`E_INTEGRITY`).

## 5. Export bundle

`sentinel run export <slug>` writes `<slug>.sentinel-run.tar.gz`: a JSON dump of the run's rows, its run directory, and the referenced shared spec and features. Scrubbed. `import` checks hashes and refuses on mismatch or if the slug exists.

## 6. state.json compatibility view

After each transition the engine writes `runs/<slug>/state.json` with the 0.1 keys (`slug`, `tier`, `stages`, `completed`, `rounds`, `baseline`, ...) plus `schema_version: 2`, `state`, `execution_status`, `acceptance_status`. It is a view; the database is the source of truth.
