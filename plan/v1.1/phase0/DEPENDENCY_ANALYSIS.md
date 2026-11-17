# Dependency Analysis

## 1. Runtime dependencies today

| Dependency | Where | Note |
|---|---|---|
| Python >= 3.10 | `pyproject.toml` | stdlib `sqlite3`, `hashlib`, `json`, `subprocess` cover registry, hashing and processes |
| `pyyaml>=6` | config, frontmatter | keep |
| `jsonschema>=4` | `doctor` | reuse for the new task, result, spec and approval schemas |
| git | everywhere | locks, baselines, boundary digests, shared repo |
| Provider CLIs (`claude`, `codex`, `gemini`, `agy`) | `run_stage.py` | optional per routing |
| `mysql`, `mysqldump` | QA data plugin | optional |
| Node and `npx` | skill install only | optional |

**Proposed new dependencies for the core release: none.** A Gherkin parser is small enough to write for the subset we validate (Feature, Background, Scenario, Scenario Outline, Examples, tags, steps). If full Gherkin fidelity is required later, `gherkin-official` is the candidate.

The dashboard release will need a web framework and a frontend toolchain; that choice is deferred to that release's design gate (G7).

## 2. Internal dependency graph (target build order)

```text
                 schemas (run, task, result, approval, evidence, spec, gherkin)
                                   |
                         registry (SQLite + artifact files)
                                   |
                     state machines (run, task, approval, TDD)
                    /              |                  \
         approval gates      write-scope policy     provider adapters
         (spec, gherkin)     (globs, test/prod)     (CLI, native contract)
                    \              |                  /
                         TDD engine (red, green, refactor)
                                   |
                  independent verification + acceptance
                                   |
                             reports (JSON, MD)
                                   |
                  ---------- core release line ----------
                                   |
                  local API + companion (auth, SSE)
                                   |
                  dashboard (onboarding, projects, config, approvals, monitoring)
```

## 3. Requirement dependencies (critical path)

1. Schemas, then registry (C-30), then state machines (C-01 to C-04).
2. Approvals (C-04, C-06, C-08, C-09, C-38) depend on state machines and on decision B3.
3. Write scopes (C-19) depend on decision B4; the TDD split (C-20 to C-24) depends on write scopes.
4. Evidence (C-25) and acceptance (C-29) depend on the registry and on independent command execution (reuse `release_check.py`).
5. Adapters (C-12 to C-16) can proceed in parallel with approvals once task and result schemas exist.
6. Every dashboard item (D-01 to D-20) depends on the core API, which depends on all of the above.

## 4. Existing code that the upgrade touches

| File | Change type | Risk |
|---|---|---|
| `sentinel/scripts/sentinel.py` | new subcommands (`approve`, `review`, `report`, `triage`, `run export/import`), stricter `run update` | high: CLI compatibility |
| `sentinel/scripts/run_stage.py` | moves behind an adapter interface | medium |
| `sentinel/scripts/boundary.py` | from repo-level to path-level scopes | medium |
| `sentinel/scripts/release_check.py` | writes evidence records | low |
| `sentinel/core/stages/*.md` | new `test_designer`, `tdd_red`, `tdd_green`, `tdd_refactor`; specifier template expanded | medium: skill and adapter generation |
| `skills/sentinel/SKILL.md`, `pipeline.md` | orchestrator must call the engine for every transition and stop at gates | high: behavior of every AI tool |
| `sentinel/adapters/*/sync.py`, `tools/gen_standalone_skills.py` | regenerate for new stages | low |
| `sentinel/core/schema/config.schema.json` | new keys (policies, tdd, scopes) | low, additive |
| `sentinel/scripts/selftest.py` | new checks; existing 95 must stay green | n/a |
