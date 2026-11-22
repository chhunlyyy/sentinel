# Event Contracts (1.1.0, draft for G1)

Events are rows in the append-only `events` table (`docs/architecture/data-architecture.md`). The same rows feed the SSE stream, notifications and reports.

## 1. Envelope

```json
{
  "id": 1842,
  "type": "run.state_changed",
  "at": "2026-11-14T09:12:03Z",
  "project": "digital-hr",
  "run": "leave-balance",
  "task": null,
  "actor": {"kind": "engine|orchestrator|human", "name": "chhunly", "channel": "tty|dashboard|cli|engine"},
  "payload": {}
}
```

`id` is monotonic per workspace database. The SSE `id:` field is `<project>:<id>`.

## 2. Types

| Type | Payload |
|---|---|
| `run.created` | tier, type, repos |
| `run.triaged` | factors, computed_tier, requested_tier |
| `run.state_changed` | from, to, transition (R#), reason |
| `run.tier_raised` | from, to, reason |
| `run.status_changed` | execution_status, acceptance_status, reasons |
| `artifact.version_created` | kind, version, sha256, path |
| `approval.requested` | gate, version, sha256 |
| `approval.decided` | gate, version, sha256, decision, comment |
| `approval.invalidated` | gate, version, reason |
| `task.created` / `task.queued` / `task.started` | role, repo, provider, model, adapter (`task.started` adds `fallback` {from, to} when a fallback provider took over) |
| `task.limit_reached` | role, repo, provider, model, adapter, runner, retry_at (null when a fallback took over), reason, parsed (false when `retry_at` is the backoff), fallback ({from, to} or null). The task went RUNNING to QUEUED |
| `task.progress` | elapsed_seconds, output_bytes, changed_files (from the heartbeat) |
| `task.waiting` | waiting_on (orchestrator, human), question |
| `task.finished` | state, error_code, seconds, tokens, reason, details, exit_code |
| `task.scope_violation` | paths, kind (`repo_not_allowed`, `outside_write_scope`, `approved_test_changed`, `ignore_rules_changed`, `head_moved`, `config_changed`, `state_in_repo`) |
| `task.stop_requested` | (empty) `sentinel next` told the orchestrator once to stop the subagent of a cancelled or timed-out native task |
| `cycle.planned` | cycle, behavior, repo, scenarios (count), retry_of |
| `cycle.state_changed` | cycle, behavior, from, to, classification, reason |
| `tdd.exception_planned` | cycle, repo, rule, method (`qa_scenario`), scenarios (ids); R12, one per QA-Red cycle |
| `tdd.exception_recorded` | cycle, evidence (the accepted red row), rule, repo, scenarios; once per cycle, actor engine |
| `run.config_refreshed` | from, to (config snapshot ids), sha256, old_sha256, changed_keys (dotted config keys that differ); `sentinel resolve --refresh-config` |
| `green.rejected`, `refactor.rejected` | cycle, evidence, reason, failing |
| `evidence.recorded` | kind, exit_code, passed, failed, classification, evidence, cycle, verdict |
| `finding.created` / `finding.routed` / `finding.resolved` | severity, location, routed_to |
| `config.saved` | scope, version, sha256 |
| `project.created` / `project.updated` / `repository.added` / `repository.removed` | ids |
| `publish.requested` / `publish.done` | target, commit |
| `knowledge.failed` | job, error |
| `budget.reached` | project, date, tokens, tokens_limit, cost, cost_limit |

## 3. SSE

- `GET /api/v1/events?project=<pid>&run=<slug>` (both optional filters).
- Reconnect with `Last-Event-ID`; the server replays newer rows from the database.
- Heartbeat comment every 15 s.
- `Last-Event-ID` is `<project>:<id>`. An id that cannot be resumed exactly (unknown, malformed, unknown project), a restored database, and a project that becomes unavailable or available again produce a `resync` message `{project, reason}` (a stream control message, not a stored event): the client re-fetches the named project.
- The actor `name` and `channel` of the envelope are stored with the event (`events.actor_name`, `events.channel`); older rows are served with name null and the channel derived from the kind.
- After reconnect the client also re-fetches the resource it shows (state refresh), so a missed event can never leave the UI wrong.
- The server polls each registered workspace database for new event ids (every 500 ms) because CLI and AI-tool processes write events too.

## 4. Notification rules

Notifications are not stored. `sentinel notifications` and `GET /api/v1/notifications` apply this table to the `events` table of each registered workspace (version 2 runs only) when asked; the notification id is `<project>:<event id>`. Only the read state is stored, in `~/.config/sentinel/user.db` (project, workspace registry id, event id, event time, read time). Marking a notification read is not audited and decides nothing.

| Event | Level | Notification (text; link) |
|---|---|---|
| `approval.requested` | action | "Specification ready for review" or "Gherkin ready for review"; `/tasks/<slug>/specification` or `/gherkin` |
| `approval.decided` with changes requested | info | "Changes requested"; the gate page |
| `run.created` | info | "Run started"; `/tasks/<slug>` |
| `run.state_changed` to NEEDS_HUMAN | action | the reason; `/tasks/<slug>` |
| `run.state_changed` to BLOCKED | warning | the reason; `/tasks/<slug>` |
| `task.finished` FAILED | warning | "<role> failed: <error code>"; `/tasks/<slug>/workflow` |
| `task.finished` FAILED with E_PROVIDER (provider unavailable) | warning | "Provider <name> unavailable"; `/tasks/<slug>/workflow` |
| `evidence.recorded` failed (verification) | warning | "Verification failed: <kind>"; `/tasks/<slug>/verification` |
| `knowledge.failed` | warning | "Knowledge harvest failed"; `/tasks/<slug>` |
| `budget.reached` | warning | "Daily budget reached: <project>"; `/projects/<pid>/floor` |
| `run.status_changed` completed, acceptance pending | action | "Run completed, waiting for acceptance"; `/tasks/<slug>/verification` |
| `run.status_changed` completed, accepted | info | "Run accepted"; `/tasks/<slug>` |
| `run.status_changed` completed, rejected | warning | "Run rejected"; `/tasks/<slug>` |
| `run.status_changed` failed | warning | "Run failed"; `/tasks/<slug>` |

Every other event, including `approval.decided` with approve, `task.finished` COMPLETED and passing evidence, gives no notification. The text is scrubbed like every other API text. The dashboard translates `/tasks/<slug>...` into the screen of the run in the notification's project.
