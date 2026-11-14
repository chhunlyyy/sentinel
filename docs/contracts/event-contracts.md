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
| `task.created` / `task.queued` / `task.started` | role, repo, provider, model, adapter |
| `task.progress` | elapsed_seconds, output_bytes, changed_files (from the heartbeat) |
| `task.waiting` | waiting_on (orchestrator, human), question |
| `task.finished` | state, error_code, seconds, tokens |
| `task.scope_violation` | paths, kind |
| `cycle.state_changed` | cycle, behavior, from, to, classification |
| `evidence.recorded` | kind, exit_code, passed, failed, classification |
| `finding.created` / `finding.routed` / `finding.resolved` | severity, location, routed_to |
| `config.saved` | scope, version, sha256 |
| `project.created` / `project.updated` / `repository.added` / `repository.removed` | ids |
| `publish.requested` / `publish.done` | target, commit |
| `notification.created` | level, text, link |

## 3. SSE

- `GET /api/v1/events?project=<pid>&run=<slug>` (both optional filters).
- Reconnect with `Last-Event-ID`; the server replays newer rows from the database.
- Heartbeat comment every 15 s.
- After reconnect the client also re-fetches the resource it shows (state refresh), so a missed event can never leave the UI wrong.
- The server polls each registered workspace database for new event ids (every 500 ms) because CLI and AI-tool processes write events too.

## 4. Notification rules

| Event | Notification |
|---|---|
| `approval.requested` | "Specification (or Gherkin) ready for review" |
| `approval.decided` with changes requested | "Changes requested" |
| `run.state_changed` to NEEDS_HUMAN or BLOCKED | reason |
| `task.finished` FAILED | role, error |
| `evidence.recorded` failed (verification) | kind |
| `run.status_changed` COMPLETED | acceptance result |
| provider unavailable (task.finished with E_PROVIDER) | provider name |
