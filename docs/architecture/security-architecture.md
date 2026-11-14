# Security Architecture (1.1.0, draft for G1)

Requirements: `SPEC.md` section 23. Risks: `plan/v1.1/phase0/IMPLEMENTATION_RISKS.md`.

## 1. Trust boundaries

```text
[ Browser ]  --- loopback HTTP, token cookie, Host/Origin checks --->  [ sentinel server ]
[ Terminal user ]  --- TTY ------------------------------------------>  [ sentinel CLI ]
[ AI tool / worker agents ]  --- CLI subprocess, no TTY, no token -->  [ sentinel CLI ]
                                                                            |
                                                                       [ engine ]
                                                                            |
                                                   files, SQLite, git, provider CLIs
```

| Principal | Can | Cannot |
|---|---|---|
| Human in the dashboard | everything the API offers, including approvals and acceptance | run arbitrary commands, read files outside registered projects |
| Human at a TTY | everything in the CLI, including `sentinel approve` | n/a |
| Orchestrator agent | propose transitions, run and complete tasks, read state | approve, accept, change policy, call the API (no token) |
| Worker agent | write inside its task scope, write `result.json` | anything else; violations are detected after the task |

## 2. Local API protection

- Bind `127.0.0.1` on a random free port (or `--port`). Never `0.0.0.0`.
- Token: 32 random bytes per server start, stored at `~/.config/sentinel/server.json` (mode 0600) with port and pid.
- The browser opens `http://127.0.0.1:<port>/auth?t=<token>`; the server sets `sentinel_session` (`HttpOnly`, `SameSite=Strict`, `Path=/`) and redirects to `/`, removing the token from the URL.
- Every `/api` request needs the cookie. Mutating requests also need header `X-Sentinel-CSRF` equal to a value served in the page (double submit).
- `Host` must be `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding defense). `Origin`, when present, must match.
- No CORS headers. `Content-Security-Policy: default-src 'self'`.
- Request body limit 1 MB; JSON only.

## 3. Operation allow-list

The API exposes named operations, never commands or raw paths:

| Operation | Validation |
|---|---|
| Browse directories (picker) | path resolved, must be under `$HOME` or a configured root; lists directories only |
| Register / create project | target directory under allowed roots; no overwrite of an existing config without explicit `force` |
| Add repo by path | resolved path inside the project workspace or an allowed root; must be a git repo |
| Clone remote repo | URL must pass `looks_like_git_url`; `git clone` with argument list (no shell), `--` before URL, target inside workspace |
| Save config | jsonschema valid; YAML written with safe dump |
| Run a check command | only commands already in the validated config (profile or repo commands), executed with the existing release-check code |
| Read artifact or log | id lookup in the registry, path must be under the run directory, sha256 verified, scrubbed on output |

No endpoint takes a shell string. All subprocess calls use argument lists.

## 4. Approvals

- CLI: `sentinel approve` refuses when `sys.stdin.isatty()` is false, shows the artifact hash, and requires typing the first 8 hex characters.
- Dashboard: approval endpoint requires the session cookie and CSRF header, and the request body must include the full hash the reviewer saw. Stale hash: `409 E_APPROVAL_STALE`.
- Records: approver identity (OS user, git `user.name`), channel (`tty` or `dashboard`), time, version, hash, decision, comment.
- Generated agent configs (`sync-adapters`) add a deny rule for `sentinel approve*` and `sentinel accept*` where the tool supports one (Claude Code `permissions.deny`), and an explicit rule in the agent instructions otherwise.

**Residual risk (R1):** an agent running as the same OS user could, in theory, script a pseudo-terminal or read the token file. Sentinel records the channel and identity and documents this. Strong separation needs a different OS user or a sandbox, which is out of scope for 1.1.0.

## 5. Agent execution

- Detective scope enforcement (see `agent-runtime.md` section 6).
- Child environment strips `SENTINEL_DASHBOARD_TOKEN` and `policies.redact_env`.
- Provider permission modes stay the provider's (for example `acceptEdits`). `unsafe_skip_permissions` stays opt-in with a warning.
- **Residual risk (R3):** Sentinel cannot stop a provider CLI from running a command during a task. It detects file and git effects afterwards.

## 6. Data protection

- Scrubber applied to evidence, logs and reports when written and again when served.
- Run exports are scrubbed and need `--yes`.
- Shared-repo publishing: off by default (`auto_sync_push: false` in new configs), human action required, scrub check must pass (existing).
- No secrets stored by Sentinel in 1.1.0.

## 7. Audit

Append-only `audit` table: actor, channel, action, target, before hash, after hash, time. Covers approvals, acceptance, config saves, project and repo changes, publish, cancel, policy overrides. Shown in the dashboard; exported with `sentinel audit export`.

## 8. Security tests (required)

Wrong Host, wrong Origin, missing cookie, missing CSRF, token in URL after redirect, path traversal in picker and artifact routes, clone URL injection (`--upload-pack`, `-` prefixed), oversized body, non-TTY approval, stale-hash approval, agent environment without token.
