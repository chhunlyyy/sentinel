# Current Architecture (as of 0.1.0b7, commit aa1481c)

Source of truth: the code, not the docs. Every claim below cites a file.

## 1. Shape of the system

Sentinel today is a **file-based pipeline contract plus a small Python CLI**. There is no server, no database, no frontend, and no long-running process.

```text
AI tool session (Claude Code, Codex, Antigravity, ...)
   |  reads skills/sentinel/SKILL.md + pipeline.md      <- the orchestrator is the LLM itself
   |
   +-- calls `sentinel ...` CLI for state, rendering, checks
   |        sentinel/scripts/sentinel.py (argparse, 710 lines)
   |
   +-- runs each stage as one of:
   |     a) subagent of the same tool          (instructions in SKILL.md, not enforced by code)
   |     b) headless CLI via `sentinel stage run` (sentinel/scripts/run_stage.py)
   |     c) inline (discouraged, must be disclosed)
   |
   +-- files on disk
         <workspace>/sentinel.config.yaml       config (one per workspace)
         <workspace>/.sentinel/runs/<slug>/     state.json, decisions.md, briefs, results, metrics.json (git-ignored)
         <workspace>/.sentinel/cache/           prompts, live logs, QA output (git-ignored)
         <workspace>/.sentinel/shared/          clone of the team's private shared repo: invariants, specs, regression suite
```

**Key fact:** orchestration decisions (which stage next, when to loop, when to stop, whether a result is trustworthy) are made by the LLM following `skills/sentinel/SKILL.md`. The CLI records what the LLM tells it and does not validate transitions.

## 2. Components

| Component | Location | What it does |
|---|---|---|
| CLI entry | `sentinel/scripts/sentinel.py` | `init`, `doctor`, `routing`, `sync-adapters`, `run new/update/finish`, `resume`, `sync pull/push`, `spec set`, `metrics record`, `stats`, `shared set/ci`, `clean`, `scrub`, passthrough to scripts |
| Tier table | `sentinel.py:19` `TIER_STAGES` | fixed stage list per tier 1 to 4 |
| Run state | `sentinel.py:365-431` | `state.json`: tier, initial_tier, stages, completed, sessions, rounds, baseline SHAs. `run update` appends any stage name to `completed` with no precondition check. Tier can only go up (`sentinel.py:413`). |
| Run outcome | `sentinel.py:452` | `passed / stopped / abandoned`. One field, mixes "execution ended" and "work accepted". |
| Stage templates | `sentinel/core/stages/*.md` | 11 prompt templates with frontmatter `per_repo` and `writes` (`repo`, `shared`, `cache`, `run`, `none`) |
| Stage renderer | `sentinel/scripts/render_stage.py` | fills `{{placeholders}}` from config, profile, rules, guidelines |
| Headless runner | `sentinel/scripts/run_stage.py` | builds a CLI command per runner (`claude`, `codex`, `gemini`, `agy` built in, extendable in config), streams output with 30 s heartbeat, timeout default 5400 s, parses JSON output for `agy`, then checks the write boundary. Exit 3 = boundary violation, 1 = tool failure. Synchronous, one process. |
| Routing | `run_stage.py:49-75` | per stage, per repo-stage, or per stage group, to a runner and model. `single_model: true` (default) ignores routing and runs everything in the current tool. |
| Write boundary | `sentinel/scripts/boundary.py` | snapshot before and after a stage: HEAD per repo, a digest of the working-tree diff and untracked files, and a digest of config, `.claude/agents`, `.claude/skills` and `AGENTS.md`. Detects writes to other repos, commits, and config edits **after the fact**. Granularity: whole repo, not paths inside a repo. |
| Shared repo | `sentinel/scripts/shared.py` | clone, scaffold, push with auto-merge and conflict hand-off (exit 4), slug lock as a git ref `refs/sentinel/locks/<slug>` (or a lock file in local mode), spec index (`specs/index.json`, status `draft / implemented / superseded`) |
| Release check | `sentinel/scripts/release_check.py` | runs build, lint, typecheck and test commands from the profile, diff hygiene (debug output, TODO), secret scan, dependency audit, extra checks, rebuild after QA. This is Sentinel executing commands itself. |
| Scrubber | `sentinel/scripts/scrub.py` | redacts tokens, credentials, emails, home paths; `--check` blocks sync push |
| QA data | `sentinel/scripts/qa_data.py` | MySQL clone and drop of throwaway `_qa` and `_fresh` schemas with guards |
| Change map | `sentinel/scripts/change_map/` | HTML map of a run's diffs across repos |
| Adapters | `sentinel/adapters/claude/sync.py`, `sentinel/adapters/agents/sync.py` | generate Claude Code agent files, or an AGENTS.md block for other tools, from the stage templates |
| Profiles | `sentinel/profiles/*.json` | per stack: detect markers, build, lint, typecheck, test and mutate commands, QA driver |
| Config schema | `sentinel/core/schema/config.schema.json` | JSON Schema; `doctor` validates against it |
| Skills | `skills/*/SKILL.md` | main orchestrator skill, one skill per stage, setup, status, resume, sync, change map |
| Self-test | `sentinel/scripts/selftest.py` | 95 end-to-end checks in temp workspaces. No unit-test framework. **Baseline: 95 passed, 0 failed.** |

## 3. Existing pipeline (by tier)

```text
Tier 1  coder
Tier 2  [repro] coder release_check metrics changelog
Tier 3  specifier retriage coder cleaner reviewer qa promotion release_check docs metrics
Tier 4  specifier retriage coder cleaner hardener reviewer qa promotion release_check docs rollout retrospective metrics
```

Tier 3 and 4 runs start with a requester interview written to `.sentinel/runs/<slug>/decisions.md`.

## 4. Things that already match the target direction

- **The specifier already writes Gherkin** (`core/stages/specifier.md:21`): Given/When/Then with permission, invalid-input, empty, failure, workflow and invariant scenarios, plus a QA procedure and a size and risk estimate.
- Provider neutrality is a founding principle: plain-file stages, several runners, generated adapters.
- Stages communicate through files, not chat memory (`pipeline.md:3`, `pipeline.md:83`).
- The rule that a stage's own report must not be trusted, and that the orchestrator re-runs key checks (`pipeline.md:75`, `SKILL.md:44`). This is a prompt rule, not code.
- Escalate-only tiering, round caps (`limits`), failure routing (code bug vs spec gap).
- Independent command execution exists for the release gate.
- Mutation testing exists (hardener).
- A slug lock that prevents two people running the same increment.

## 5. Things that do not exist at all

- Any HTTP API, server, daemon, or companion process.
- Any dashboard or frontend.
- A database. All state is JSON and Markdown files.
- A multi-project registry. One config file equals one project (a workspace).
- Human approval records, version hashes, or approval invalidation.
- A state machine with validated transitions.
- Separate execution and acceptance statuses.
- Test-file vs production-file write scopes.
- A provider adapter interface with status, cancel, or capability discovery.
- Machine-readable run reports beyond `state.json` and `metrics.json`.
- Unit tests.
