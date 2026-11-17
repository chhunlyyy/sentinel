# Gate G0 Decisions

Recorded 2026-11-14. Approver: project owner (chat approval at gate G0).

| ID | Decision | Effect |
|---|---|---|
| G0 | Phase 0 discovery and the proposed architecture are approved. | Proceed to Phase 1 (unified `SPEC.md` and contracts), stop at G1. |
| B1 | **The dashboard ships in this release.** Everything works locally. Remote data is exchanged only through the shared repo sync. | The release covers core plus dashboard. No remote Sentinel installations, no hosted service, no remote database. The local API and companion run on the user's machine. Project repos given as remote URLs are cloned locally. |
| B2 | SQLite registry plus artifact files (recommended value, not contested). | As proposed. Cross-machine exchange only through scrubbed export bundles or the shared repo. |
| B3 | Human-only approval channel (recommended value). | TTY approval in the CLI plus token-authenticated approval in the local dashboard. |
| B4 | Post-hoc path-level write scopes (recommended value). | As proposed. |
| B5 | **Every tier, tier 1 included, has two separate approvals: specification first, Gherkin second.** Reason given by the owner: Gherkin depends on the spec, so a spec change can change the Gherkin; the spec must be settled first. | Replaces the "one combined approval" proposal. A spec change after Gherkin approval invalidates both approvals. Docs-only tasks: specification approval only. |
| B6 | `auto_sync_push` defaults to off for new configs (recommended value). | As proposed. |
| B7 | **Version `1.1.0`.** | `sentinel/VERSION` becomes `1.1.0` at release. |
| B8 | Canonical lifecycle from SPEC_CORE section 9 with a separate `acceptance_status` (recommended value). | As proposed. |
| B9 | Core engine before dashboard phases (recommended value). | Dashboard phases run after the engine API exists, in the same release. |
| B10 | `no_permanent_frontend_tests` conflict handling (recommended value). | As proposed. |
