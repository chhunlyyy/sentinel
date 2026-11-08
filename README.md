# Sentinel

Sentinel is a tiered build pipeline for AI coding agents. You describe a feature or a bug. Sentinel decides how much rigor the task needs, then runs only the stages that size of task requires: repro, spec, code, clean, harden, review, QA, regression promotion, release check, docs, rollout notes, and retrospective.

It is provider-neutral. The pipeline is plain files and a small Python CLI. Any agent that can read a prompt and edit files can run a stage: Claude Code, Codex, Gemini CLI, Antigravity, Cursor, or a human.

## Why

- One run of "implement this properly" usually means five or six hand-written agent prompts, a QA setup, and a lot of logs. Sentinel packages that as config.
- Effort scales with the task. A typo fix is one coder call. A change to authorization rules runs the full pipeline.
- The knowledge a team builds up (specs, project invariants, the regression suite) lives in one shared repo, so it stays current for everyone. Logs and caches stay local and disposable.

## How it works

```
Tier 1  Coder
Tier 2  [Repro, bugs only] > Coder > Release check > Metrics > Changelog line
Tier 3  Specifier > Re-triage > Coder > Cleaner > Reviewer > Targeted QA > Regression promotion
        > Release check > Docs and PR draft > Metrics
Tier 4  Specifier > Re-triage > Coder > Cleaner > Hardener > Reviewer > Full QA > Regression promotion
        > Release check > Docs and PR draft > Rollout notes > Retrospective > Metrics
```

The tier depends only on the size and risk of the task (repos touched, files changed, schema change, auth change, security surface). Any single high-risk factor raises the whole run. A reviewer blocker in tier 2 or 3 raises the tier automatically.

Details: [core/pipeline.md](core/pipeline.md).

## Project shapes

`sentinel init` asks for the shape of your project and generates the repo list, agents, and cross-repo steps.

| Shape | Repos | Behavior |
|---|---|---|
| single | one repo, role `app` | no cross-repo steps |
| fullstack | backend and frontend | backend first, one sync checkpoint, then frontend |
| fullstack-mobile | backend, frontend, mobile | backend first, one sync checkpoint, then frontend and mobile in parallel |
| custom | any number of repos and roles | you define the order |

Each repo has its own stack profile (`flutter`, `spring-gradle`, `nextjs`, `node`, `python`, or `generic`), so mixed stacks work.

## Requirements

- Python 3 with PyYAML (`pip install pyyaml`; add `jsonschema` for `sentinel doctor` schema checks)
- git
- At least one AI agent CLI, if you want stages to run unattended
- `mysql` and `mysqldump`, only if you use the MySQL QA data plugin
- Node, only if your stack or QA driver needs it

## Install

```bash
git clone <your sentinel repo url> ~/sentinel
export SENTINEL_HOME=~/sentinel
export PATH="$SENTINEL_HOME/bin:$PATH"
```

## Quickstart

See [docs/quickstart.md](docs/quickstart.md). In short:

```bash
cd my-workspace
sentinel init
sentinel doctor
sentinel sync-adapters --tool claude
```

Then ask your agent to run Sentinel on a task.

## Documentation

- [Quickstart](docs/quickstart.md)
- [Configuration reference](docs/config.md)
- [Security notes](docs/security.md)
- [Beta testing guide](docs/beta-testing.md)
- [Pipeline contract](core/pipeline.md)

## Status

Internal beta, version 0.1.0-beta. It has run end to end on one project (Tier 2 bug fix on a Spring Boot and Next.js workspace) and passes its own self-test (`python3 scripts/selftest.py`, 28 checks on a throwaway workspace). The specifier, reviewer, hardener, QA, promotion, docs, rollout and retrospective stages have not run for real yet, and the Codex, Gemini and Cursor adapters have not been tried against the real tools. Read [docs/beta-testing.md](docs/beta-testing.md) before testing. The name "Sentinel" has not been checked for availability on package registries.

## License

MIT. See [LICENSE](LICENSE).
