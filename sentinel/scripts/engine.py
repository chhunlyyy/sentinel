"""Run engine: the only place that changes version 2 run state.

Every change runs in one registry transaction: re-read the run, check the table
(machines.py), check preconditions, write the row and the event. The state.json
view is rewritten after the commit. Source: docs/contracts/state-transitions.md.
"""
import difflib
import hashlib
import json
import os
import shutil
from pathlib import Path

import artifacts as A
import machines
from errors import SentinelError
from registry import Registry, _now
from runtime import RuntimeOps
from tasks import TaskOps, retry_cap

WORKFLOW_VERSION = "2"
TIER_STAGES = {
    1: ["coder"],
    2: ["repro", "coder", "release_check", "metrics", "changelog"],
    3: ["specifier", "retriage", "coder", "cleaner", "reviewer", "qa", "promotion", "release_check", "docs", "metrics"],
    4: ["specifier", "retriage", "coder", "cleaner", "hardener", "reviewer", "qa", "promotion", "release_check", "docs", "rollout", "retrospective", "metrics"],
}
MISSING_EVIDENCE = "verification evidence missing"

# Phase B approval gates. Gate names are stored in approvals.gate.
GATES = {"spec": "specification", "specification": "specification", "gherkin": "gherkin"}
GATE_KIND = {"specification": "spec", "gherkin": "gherkin"}
GATE_STATE = {"specification": "SPECIFICATION_REVIEW", "gherkin": "GHERKIN_REVIEW"}
GATE_TITLE = {"specification": "Specification", "gherkin": "Gherkin"}
ROLES = {"specifier": "specification", "test_designer": "gherkin"}
DECISIONS = {"approve": ("APPROVED", "approve"), "changes": ("CHANGES_REQUESTED", "request_changes"),
             "reject": ("REJECTED", "reject")}
DECISION_TARGET = {("specification", "approve"): "SPECIFICATION_APPROVED", ("specification", "changes"): "PLANNED",
                   ("specification", "reject"): "CANCELLED", ("gherkin", "approve"): "GHERKIN_APPROVED",
                   ("gherkin", "changes"): "SPECIFICATION_APPROVED", ("gherkin", "reject"): "CANCELLED"}
R18_SOURCES = ("GHERKIN_APPROVED", "EXECUTING", "VERIFYING", "REVIEWING")
UPSTREAM = "upstream specification approval invalidated"


class Engine(RuntimeOps, TaskOps):
    def __init__(self, state_dir, workspace, config, release_lock=None):
        self.state_dir = Path(state_dir)
        self.workspace = Path(workspace)
        self.config = config or {}
        self.reg = Registry.open(self.state_dir)
        self._release_lock = release_lock
        self._kills = []

    def close(self):
        self.reg.close()

    # ---- helpers
    def run_dir(self, slug):
        return self.state_dir / "runs" / slug

    def _get(self, slug):
        run = self.reg.get_run(slug)
        if not run:
            raise SentinelError("E_NOT_FOUND", f"no run named {slug}", {"slug": slug})
        return run

    def _get_v2(self, slug):
        run = self._get(slug)
        if run["workflow_version"] != WORKFLOW_VERSION:
            raise SentinelError("E_TRANSITION", f"run {slug} is a 0.1 run; the engine only moves version 2 runs",
                                {"slug": slug, "workflow_version": run["workflow_version"]})
        return run

    def _sync(self, slug):
        """Apply changes to the shared spec and feature files in their own committed transaction.

        Runs before every command's own transaction, so a command that then fails cannot roll the
        detection back. A stored copy that fails its hash check parks the run (R19) instead of failing.
        """
        run = self._get(slug)
        if run["workflow_version"] != WORKFLOW_VERSION or run["state"] in machines.RUN_FINAL:
            return
        try:
            with self.reg.transaction():
                self._detect(self._get(slug))
        except SentinelError as err:
            if err.code != "E_INTEGRITY":
                raise
            with self.reg.transaction():
                run = self._get(slug)
                if run["state"] not in machines.RUN_FINAL and run["state"] != "NEEDS_HUMAN":
                    self.reg.add_audit("engine", "engine", "integrity_failed", f"{slug}/detection", reason=err.code)
                    self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=str(err))
        self.write_view(slug)
        self._flush_kills()

    def is_v2(self, slug):
        run = self.reg.get_run(slug)
        return bool(run) and run["workflow_version"] == WORKFLOW_VERSION

    def _release(self, slug, run):
        if run.get("adhoc"):
            return
        if self._release_lock:
            self._release_lock(slug)
        else:
            from shared import Shared
            Shared(self.workspace, self.config).release(slug)

    def _event(self, run, type, actor, payload):
        self.reg.add_event(run["id"], type, actor, payload)

    def _move(self, run, to, actor, reason=None):
        """Inside a transaction: validate and apply a state change. Returns the rule and extra fields."""
        frm = run["state"]
        rule = machines.check_run(frm, to, actor)
        if frm == to:
            raise SentinelError("E_TRANSITION", f"run is already {frm}", {"from": frm, "to": to})
        if rule == "R12d" and run["type"] != "docs":
            raise SentinelError("E_TRANSITION", f"run transition {frm} -> {to} needs a docs-only run",
                                {"from": frm, "to": to})
        if frm == "TRIAGED" and to == "PLANNED" and (run["tier"] or 0) >= 3:
            if not (self.run_dir(run["slug"]) / "decisions.md").is_file():
                raise SentinelError("E_PRECONDITION", "a tier 3 or 4 run needs decisions.md before planning",
                                    {"missing": ["decisions.md"], "tier": run["tier"]})
        if rule in ("R20", "R22") and to != run["previous_state"]:
            raise SentinelError("E_PRECONDITION", f"run must resume at {run['previous_state']}, not {to}",
                                {"from": frm, "to": to, "previous_state": run["previous_state"]})
        parked = ("NEEDS_HUMAN", "BLOCKED")
        previous = run["previous_state"] if frm in parked and to in parked else frm if to in parked else None
        fields = {"state": to, "execution_status": machines.execution_status_for(to), "previous_state": previous}
        reasons = []
        if to == "COMPLETED":  # only reachable from REVIEWING: self-transitions are refused above
            if not self.reg.has_passing_evidence(run["id"]):
                reasons.append(MISSING_EVIDENCE)
            fields["acceptance_status"] = "rejected" if reasons else "accepted"
        if to == "CANCELLED":
            fields["acceptance_status"] = "rejected"
        if to in machines.RUN_FINAL:
            fields["finished_at"] = _now()
        self.reg.update_run(run["slug"], **fields)
        payload = {"from": frm, "to": to, "transition": rule, "reason": reason}
        self._event(run, "run.state_changed", actor, payload)
        if rule in ("R17", "R18"):
            self.cancel_open_tasks(run, "approval invalidated")
        elif to in ("CANCELLED", "FAILED"):
            self.cancel_open_tasks(run, f"run {to.lower()}")
        if rule == "R3":
            self._auto_task({**run, **fields}, "specifier")
        elif rule == "R5" and run["type"] != "docs":
            self._auto_task({**run, **fields}, "test_designer")
        if to in machines.RUN_FINAL:
            self._event(run, "run.status_changed", actor, {
                "execution_status": fields["execution_status"],
                "acceptance_status": fields.get("acceptance_status", run["acceptance_status"]),
                "reasons": reasons})
        return rule

    def _finish_up(self, slug, run_before):
        """After commit: rewrite the view, release the lock on a final state."""
        self._flush_kills()
        run = self.reg.get_run(slug)
        self.write_view(slug)
        if run["state"] in ("CANCELLED", "FAILED") and run_before["state"] not in machines.RUN_FINAL:
            self._release(slug, run)
        return run

    # ---- commands
    def create_run(self, slug, actor, type=None, baseline=None, request=None, adhoc=False):
        baseline = baseline or {}
        config_text = json.dumps(self.config, sort_keys=True)
        cfg_file = self.workspace / "sentinel.config.yaml"
        if cfg_file.exists():
            config_text = cfg_file.read_text(encoding="utf-8")
        with self.reg.transaction():
            if self.reg.get_run(slug):
                raise SentinelError("E_PRECONDITION", f"run {slug} already exists", {"slug": slug})
            snap = self.reg.store_config_version("workspace", config_text, author=actor)
            self.reg.insert_run({
                "slug": slug, "request": request, "type": type, "tier": None, "initial_tier": None,
                "state": "CREATED", "execution_status": "running", "acceptance_status": "pending",
                "workflow_version": WORKFLOW_VERSION, "config_snapshot_id": snap, "adhoc": int(bool(adhoc)),
            })
            run = self.reg.get_run(slug)
            for repo_id, sha in sorted(baseline.items()):
                self.reg.add_run_repo(run["id"], repo_id, sha)
            self._event(run, "run.created", actor, {
                "tier": None, "type": type, "repos": sorted(baseline),
                "config_sha256": hashlib.sha256(config_text.encode("utf-8")).hexdigest()})
        self.write_view(slug)
        return self.reg.get_run(slug)

    def triage(self, slug, factors, actor, requested=None):
        self._sync(slug)
        with self.reg.transaction():
            run = self._get_v2(slug)
            tier = machines.compute_tier(factors, requested)
            machines.check_tier_change(run["tier"], tier)
            self.reg.update_run(slug, tier=tier, initial_tier=tier)
            run["tier"] = tier
            self._move(run, "TRIAGED", actor, reason=f"tier {tier}")
            self._event(run, "run.triaged", actor, {"factors": factors or {}, "computed_tier": tier,
                                                    "requested_tier": requested})
        return self._finish_up(slug, run)

    def request_state(self, slug, to, actor, reason=None):
        deferred = None
        self._sync(slug)
        with self.reg.transaction():
            run = self._get_v2(slug)
            if machines.check_run(run["state"], to, actor) == "R25":
                self._accept(run, "accepted", actor)  # acceptance only; never recomputed
            elif to == "EXECUTING" and actor == machines.ENGINE and self._starts_execution(run):
                deferred = self._start(run, reason)
            else:
                rule = self._move(run, to, actor, reason)
                if rule in ("R20", "R22"):  # a resumed run re-checks its files and approvals (R18, R17)
                    run = self._detect(self.reg.get_run(slug))
                    if run["state"] in ("GHERKIN_APPROVED", "EXECUTING"):
                        deferred = self._park_if_unapproved(run)
        result = self._finish_up(slug, run)
        if deferred:
            raise deferred
        return result

    def complete(self, slug):
        return self.request_state(slug, "COMPLETED", machines.ENGINE)

    def set_tier(self, slug, tier, actor, reason=None):
        if isinstance(tier, bool) or not isinstance(tier, int) or not 1 <= tier <= 4:
            raise SentinelError("E_VALIDATION", f"tier must be 1-4, got {tier!r}")
        if actor not in machines.ACTORS:
            raise SentinelError("E_ACTOR", f"unknown actor {actor!r}", {"allowed": list(machines.ACTORS)})
        self._sync(slug)
        with self.reg.transaction():
            run = self._get_v2(slug)
            if run["state"] in machines.RUN_FINAL:
                raise SentinelError("E_TRANSITION", f"run is {run['state']}; its tier cannot change",
                                    {"state": run["state"]})
            machines.check_tier_change(run["tier"], tier)
            if tier != run["tier"]:
                self.reg.update_run(slug, tier=tier)
                self._event(run, "run.tier_raised", actor, {"from": run["tier"], "to": tier, "reason": reason})
        return self._finish_up(slug, run)

    def _accept(self, run, value, actor):
        """Inside a transaction: change acceptance on a COMPLETED run."""
        if run["state"] != "COMPLETED":
            raise SentinelError("E_PRECONDITION", f"acceptance can only change on a COMPLETED run, run is {run['state']}",
                                {"state": run["state"]})
        machines.check_acceptance_change(run["acceptance_status"], value, actor)
        self.reg.update_run(run["slug"], acceptance_status=value)
        self._event(run, "run.status_changed", actor, {
            "execution_status": run["execution_status"], "acceptance_status": value, "reasons": []})

    def set_acceptance(self, slug, value, actor):
        self._sync(slug)
        with self.reg.transaction():
            run = self._get_v2(slug)
            self._accept(run, value, actor)
        return self._finish_up(slug, run)

    def finish(self, slug, outcome, actor):
        """Legacy `run finish --outcome` on a version 2 run."""
        self._sync(slug)
        with self.reg.transaction():
            run = self._get_v2(slug)
            target = machines.finish_outcome(run["state"], outcome)[0]
            if target == "CANCELLED":
                self._move(run, "CANCELLED", actor, reason=f"run finish --outcome {outcome}")
        result = self._finish_up(slug, run)  # releases the lock when the run was cancelled
        if target == "COMPLETED":
            self._release(slug, result)
        return result

    # ---- Phase B: artifacts, approvals, hashes (docs/contracts/state-transitions.md R4-R12, R17, R18)
    def spec_path(self, slug):
        return self.state_dir / "shared" / "specs" / slug / "spec.md"

    def features_dir(self, slug):
        return self.state_dir / "shared" / "specs" / slug / "features"

    def _gate(self, gate):
        if gate not in GATES:
            raise SentinelError("E_VALIDATION", f"unknown gate {gate!r}", {"allowed": ["spec", "gherkin"]})
        return GATES[gate]

    def _rows(self, run, table, **where):
        return self.reg.rows(table, run_id=run["id"], **where)

    def _latest_approval(self, run, gate, state=None):
        rows = [a for a in self._rows(run, "approvals", gate=gate) if state in (None, a["state"])]
        return rows[-1] if rows else None

    def _latest_artifact(self, run, kind):
        rows = self._rows(run, "artifacts", kind=kind)
        return max(rows, key=lambda a: a["version"]) if rows else None

    def _current_hash(self, slug, kind):
        """sha256 of the shared file(s) now; None when the spec file is gone."""
        if kind == "spec":
            path = self.spec_path(slug)
            return A.spec_hash(path) if path.is_file() else None
        return A.gherkin_set_hash(self.features_dir(slug))[0]

    def _stored_text(self, slug, version):
        return (self.run_dir(slug) / "artifacts" / f"spec-v{version}.md").read_text(encoding="utf-8", errors="replace")

    def _approved_spec(self, run):
        """(text, version) of the spec a Gherkin set is checked against."""
        ap = self._latest_approval(run, "specification", "APPROVED")
        if not ap:
            raise SentinelError("E_APPROVAL_MISSING", "no approved specification to check the Gherkin against")
        A.verify_stored(self.state_dir, run["slug"], "spec", ap["version"], ap["sha256"])
        return self._stored_text(run["slug"], ap["version"]), ap["version"]

    def _store_version(self, run, kind):
        """Inside a transaction: copy the shared file(s), add the artifact row, an IN_REVIEW approval and the events."""
        slug = run["slug"]
        gate = "specification" if kind == "spec" else "gherkin"
        version = max([a["version"] for a in self._rows(run, "artifacts", kind=kind)], default=0) + 1
        orphan = self.run_dir(slug) / "artifacts" / A._stored_name(kind, version)
        if orphan.is_dir():
            shutil.rmtree(orphan)
        elif orphan.exists():
            orphan.unlink()
        src = self.spec_path(slug) if kind == "spec" else self.features_dir(slug)
        version, sha, dest = A.store_version(self.state_dir, slug, kind, src, version)
        path = str(Path(dest).relative_to(self.state_dir))
        self.reg.insert_row("artifacts", {"run_id": run["id"], "kind": kind, "version": version, "path": path,
                                          "sha256": sha, "created_at": _now()})
        art = self._latest_artifact(run, kind)
        self._event(run, "artifact.version_created", machines.ENGINE,
                    {"kind": kind, "version": version, "sha256": sha, "path": path})
        machines.check_approval("DRAFT", "IN_REVIEW", machines.ENGINE)
        self.reg.insert_row("approvals", {"run_id": run["id"], "gate": gate, "artifact_id": art["id"],
                                          "version": version, "sha256": sha, "state": "IN_REVIEW"})
        self._event(run, "approval.requested", machines.ENGINE, {"gate": gate, "version": version, "sha256": sha})
        return version, sha

    def _invalidate(self, run, approval, reason):
        machines.check_approval(approval["state"], "INVALIDATED", machines.ENGINE)
        self.reg.update_row("approvals", approval["id"], state="INVALIDATED", invalidated_at=_now(),
                            invalidated_reason=reason)
        self._event(run, "approval.invalidated", machines.ENGINE,
                    {"gate": approval["gate"], "version": approval["version"], "reason": reason})

    def _invalidate_open(self, run, gate, reason):
        for ap in self._rows(run, "approvals", gate=gate):
            if ap["state"] in ("IN_REVIEW", "APPROVED"):
                self._invalidate(run, ap, reason)

    def _detect(self, run):
        """Inside a transaction: re-hash the shared files; a changed hash is a new version (R17, R18)."""
        if run["workflow_version"] != WORKFLOW_VERSION or run["state"] in machines.RUN_FINAL:
            return run
        slug = run["slug"]
        spec_ap = self._latest_approval(run, "specification")
        if spec_ap:
            latest = self._latest_artifact(run, "spec")
            cur = self._current_hash(slug, "spec")
            changed = spec_ap["state"] in ("IN_REVIEW", "APPROVED") and cur != latest["sha256"]
            reopened = spec_ap["state"] == "INVALIDATED" and run["state"] == "SPECIFICATION_REVIEW" and cur is not None
            if changed or reopened:
                self._invalidate_open(run, "specification", "spec hash changed")
                self._invalidate_open(run, "gherkin", UPSTREAM)
                if run["state"] != "SPECIFICATION_REVIEW":
                    self._move(run, "SPECIFICATION_REVIEW", machines.ENGINE, reason="spec hash changed")
                if cur is not None and self._spec_valid(run):  # an invalid file is not stored (README point 4)
                    self._store_version(run, "spec")
                    self._set_spec_links(run)
                return self.reg.get_run(slug)
        gh_ap = self._latest_approval(run, "gherkin")
        if (gh_ap and gh_ap["state"] in ("IN_REVIEW", "APPROVED")
                and (run["state"] == "GHERKIN_REVIEW" or run["state"] in R18_SOURCES)):
            latest = self._latest_artifact(run, "gherkin")
            if self._current_hash(slug, "gherkin") != latest["sha256"]:
                self._invalidate_open(run, "gherkin", "Gherkin hash changed")
                if run["state"] != "GHERKIN_REVIEW":
                    self._move(run, "GHERKIN_REVIEW", machines.ENGINE, reason="Gherkin hash changed")
                self._store_version(run, "gherkin")
                self._set_gherkin_data(run)
                return self.reg.get_run(slug)
        return run

    def _spec_valid(self, run):
        path = self.spec_path(run["slug"])
        text = path.read_bytes().decode("utf-8", "replace")
        return A.validate_spec(text, run["slug"], run["tier"], run["type"] or "feature").ok

    def _set_spec_links(self, run):
        text = self.spec_path(run["slug"]).read_text(encoding="utf-8", errors="replace")
        spec = A.parse_spec(text)
        links = [("req", r, "ac", a) for a, reqs in spec["criteria"].items() for r in reqs if r in spec["requirements"]]
        self.reg.replace_trace_links(run["id"], links, from_kind="req")

    def _set_gherkin_data(self, run, report=None):
        """Trace links and the coverage table of the newest Gherkin version."""
        slug = run["slug"]
        if report is None:
            text, version = self._approved_spec(run)
            report = A.validate_gherkin(self.features_dir(slug), text, version)
        links = [tuple(link) for link in report.data.get("trace_links", [])]
        self.reg.replace_trace_links(run["id"], links, to_kind="scenario")
        version = self._latest_artifact(run, "gherkin")["version"]
        out = self.run_dir(slug) / "artifacts" / f"coverage-v{version}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report.data.get("coverage", {}), indent=2))

    def load_run(self, slug):
        """Load a version 2 run; any change to its shared spec or feature files is applied first."""
        self._sync(slug)
        self._sync(slug)
        return self._finish_up(slug, self._get_v2(slug))

    # ---- specifier / test_designer completion (R4, R8)
    def _retry_cap(self, role):
        return retry_cap(self.config, role)

    def _feedback_path(self, slug, role):
        return self.run_dir(slug) / f"feedback-{role}.json"

    def _feedback(self, slug, role):
        try:
            return json.loads(self._feedback_path(slug, role).read_text())
        except (OSError, ValueError):
            return {"errors": [], "failures": 0, "comments": []}

    def _save_feedback(self, slug, role, data):
        path = self._feedback_path(slug, role)
        if not data["errors"] and not data["comments"] and not data["failures"]:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def brief_feedback(self, slug, role):
        """What the next brief for `role` must carry: validation errors and requested changes."""
        data = self._feedback(slug, role)
        return list(data["errors"]) + [f"changes requested: {c}" for c in data["comments"]]

    def task_completed(self, slug, role, task_id):
        """Called by finish_task for a finished specifier or test_designer task `task_id`: validate the shared files and open the review.

        Returns {"accepted", "errors", "warnings", "state"}. Invalid files are not stored; the errors go
        into the next brief, and after `limits.<role>_retries` failures the run goes to NEEDS_HUMAN.
        """
        if role not in ROLES:
            raise SentinelError("E_VALIDATION", f"unknown role {role!r}", {"allowed": sorted(ROLES)})
        gate = ROLES[role]
        feedback = None
        self._sync(slug)
        with self.reg.transaction():
            run = self._get_v2(slug)
            if run["state"] != ("PLANNED" if role == "specifier" else "SPECIFICATION_APPROVED"):
                raise SentinelError("E_TRANSITION", f"the {role} task cannot complete while the run is {run['state']}",
                                    {"state": run["state"], "role": role})
            if role == "test_designer" and run["type"] == "docs":
                raise SentinelError("E_PRECONDITION", "docs-only runs have no Gherkin gate", {"type": "docs"})
            if role == "specifier":
                path = self.spec_path(slug)
                if path.is_file():
                    report = A.validate_spec(path.read_bytes().decode("utf-8", "replace"), slug, run["tier"],
                                             run["type"] or "feature")
                else:
                    report = A.Report(errors=[f"specs/{slug}/spec.md not found"])
            else:
                text, version = self._approved_spec(run)
                report = A.validate_gherkin(self.features_dir(slug), text, version)
            fb = self._feedback(slug, role)
            if not report.ok:
                fb["errors"] = list(report.errors)
                fb["failures"] += 1
                feedback = fb
                cap = self._retry_cap(role)
                if fb["failures"] > cap:
                    what = "specification" if role == "specifier" else "Gherkin"
                    self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=f"{what} invalid after {cap} retries")
            else:
                self._store_version(run, GATE_KIND[gate])
                if role == "specifier":
                    self._set_spec_links(run)
                    self._move(run, "SPECIFICATION_REVIEW", machines.ENGINE, reason="specification submitted")
                else:
                    self._set_gherkin_data(run, report)
                    self._move(run, "GHERKIN_REVIEW", machines.ENGINE, reason="Gherkin submitted")
                feedback = {"errors": [], "failures": 0, "comments": []}
        self._save_feedback(slug, role, feedback)  # after the commit: a rolled-back change leaves no file
        final = self._finish_up(slug, run)
        res = {"accepted": report.ok, "errors": list(report.errors), "warnings": list(report.warnings),
               "state": final["state"]}
        self._after_role_task(slug, role, res, task_id)
        return res

    # ---- approval decisions (R5-R7, R9-R11)
    def _pending(self, run, gate, decision):
        """Inside a transaction: the IN_REVIEW approval a decision applies to, after all gate checks."""
        slug = run["slug"]
        if gate == "gherkin" and run["type"] == "docs":
            raise SentinelError("E_PRECONDITION", "docs-only runs have no Gherkin gate", {"type": "docs"})
        if run["state"] != GATE_STATE[gate]:
            raise SentinelError("E_TRANSITION", f"{gate} can only be decided while the run is {GATE_STATE[gate]}, "
                                f"run is {run['state']}", {"state": run["state"], "gate": gate})
        ap = self._latest_approval(run, gate)
        if not ap or ap["state"] != "IN_REVIEW":
            if gate == "specification":
                path = self.spec_path(slug)
                errors = ([f"specs/{slug}/spec.md not found"] if not path.is_file() else
                          A.validate_spec(path.read_bytes().decode("utf-8", "replace"), slug, run["tier"],
                                          run["type"] or "feature").errors)
                if errors:
                    raise SentinelError("E_VALIDATION", "the specification is not valid: " + "; ".join(errors),
                                        {"errors": errors})
            raise SentinelError("E_APPROVAL_MISSING", f"no {gate} version is in review", {"gate": gate})
        kind = GATE_KIND[gate]
        art = self.reg.get_row("artifacts", ap["artifact_id"])
        if not art or art["sha256"] != ap["sha256"]:
            raise SentinelError("E_INTEGRITY", "approval record does not match artifact", {"gate": gate})
        A.verify_stored(self.state_dir, slug, kind, ap["version"], ap["sha256"])
        if decision == "approve":
            if gate == "specification":
                errors = A.validate_spec(self._stored_text(slug, ap["version"]), slug, run["tier"],
                                         run["type"] or "feature").errors
            else:
                text, version = self._approved_spec(run)
                stored = self.run_dir(slug) / "artifacts" / A._stored_name("gherkin", ap["version"]) / "features"
                errors = A.validate_gherkin(stored, text, version).errors
            if errors:
                raise SentinelError("E_VALIDATION", f"the {gate} is not valid: " + "; ".join(errors),
                                    {"errors": errors})
        return {"approval": ap, "gate": gate, "kind": kind, "version": ap["version"], "sha256": ap["sha256"],
                "state": ap["state"]}

    @staticmethod
    def _need_comment(decision, comment):
        if decision == "changes" and not (comment or "").strip():
            raise SentinelError("E_VALIDATION", "requesting changes needs a comment")

    def pending_approval(self, slug, gate, decision="approve", comment=None):
        """The approval a human is about to decide (runs every gate check). Used before the hash prompt."""
        gate = self._gate(gate)
        self._need_comment(decision, comment)
        self._sync(slug)
        with self.reg.transaction():
            run = self._get_v2(slug)
            info = self._pending(run, gate, decision)
        self._finish_up(slug, run)
        return {k: v for k, v in info.items() if k != "approval"}

    def _is_known_hash(self, run, gate, test):
        return any(test(a["sha256"] or "") for a in self._rows(run, "artifacts", kind=GATE_KIND[gate])) or \
            any(test(a["sha256"] or "") for a in self._rows(run, "approvals", gate=gate))

    def decide(self, slug, gate, decision, actor, *, sha256=None, prefix=None, comment=None,
               approver=None, approver_name=None, channel="tty"):
        """A human decision on the artifact in review. Give the full `sha256` or the typed 8-character `prefix`."""
        gate = self._gate(gate)
        who = approver or actor
        try:
            return self._decide(slug, gate, decision, actor, sha256, prefix, comment, who, approver_name, channel)
        except SentinelError as err:
            self.audit_refused(slug, gate, err.code, who, channel)
            raise

    def audit_refused(self, slug, gate, code, approver, channel):
        """Record a refused approval attempt (README open point 7); integrity failures get their own action."""
        gate = self._gate(gate)
        action = "integrity_failed" if code == "E_INTEGRITY" else "approve_refused"
        self.audit(approver, channel, action, f"{slug}/{gate}", reason=code)

    def audit(self, actor, channel, action, target, reason=None):
        with self.reg.transaction():
            self.reg.add_audit(actor, channel, action, target, reason=reason)

    def _decide(self, slug, gate, decision, actor, sha256, prefix, comment, who, approver_name, channel):
        if actor != machines.HUMAN:
            raise SentinelError("E_ACTOR", f"{actor} may not decide an approval",
                                {"actor": actor, "allowed": [machines.HUMAN]})
        if decision not in DECISIONS:
            raise SentinelError("E_VALIDATION", f"unknown decision {decision!r}", {"allowed": sorted(DECISIONS)})
        if (sha256 is None) == (prefix is None):
            raise SentinelError("E_VALIDATION", "give exactly one of sha256 or prefix")
        self._need_comment(decision, comment)
        deferred = None
        feedback = None
        self._sync(slug)
        with self.reg.transaction():
            run = self._get_v2(slug)
            info = self._pending(run, gate, decision)
            ap = info["approval"]
            typed = (prefix if prefix is not None else sha256).strip().lower()
            current = ap["sha256"]
            if prefix is not None:
                ok = len(typed) == 8 and current.startswith(typed)
                older = len(typed) == 8 and self._is_known_hash(run, gate, lambda h: h.startswith(typed))
            else:
                ok = typed == current
                older = self._is_known_hash(run, gate, lambda h: h == typed)
            if not ok and not older:
                raise SentinelError("E_VALIDATION", "the typed hash does not match the artifact in review",
                                    {"gate": gate})
            if not ok:  # an older version: keep what detection stored, then refuse
                deferred = SentinelError("E_APPROVAL_STALE", f"that hash is from an older {gate} version; "
                                         f"the current sha256 is {current}",
                                         {"gate": gate, "version": ap["version"], "current_sha256": current})
            else:
                new_state, action = DECISIONS[decision]
                machines.check_approval("IN_REVIEW", new_state, machines.HUMAN)
                self.reg.update_row("approvals", ap["id"], state=new_state, decision=decision, approver=who,
                                    channel=channel, comment=comment, decided_at=_now())
                self._event(run, "approval.decided", machines.HUMAN, {
                    "gate": gate, "version": ap["version"], "sha256": current, "decision": decision,
                    "comment": comment, "approver_name": approver_name})
                self._move(run, DECISION_TARGET[(gate, decision)], machines.HUMAN, reason=f"{gate} {decision}")
                self.reg.add_audit(who, channel, action, f"{slug}/{gate}", after_sha=current)
                if decision == "changes":
                    role = "specifier" if gate == "specification" else "test_designer"
                    feedback = (role, {"errors": [], "failures": 0, "comments": [comment.strip()]})
        if feedback:
            self._save_feedback(slug, *feedback)  # after the commit
        result = self._finish_up(slug, run)
        if deferred:
            raise deferred
        return result

    # ---- execution start (R12, R12d)
    def _starts_execution(self, run):
        return run["state"] == "GHERKIN_APPROVED" or (run["state"] == "SPECIFICATION_APPROVED" and run["type"] == "docs")

    def _start_problem(self, run):
        """(error code, reason) when the approvals do not allow execution, else None."""
        slug = run["slug"]
        gates = ["specification"] + ([] if run["type"] == "docs" else ["gherkin"])
        for gate in gates:
            ap = self._latest_approval(run, gate, "APPROVED")
            if not ap:
                return "E_APPROVAL_MISSING", f"{GATE_TITLE[gate]} approval missing"
            art = self.reg.get_row("artifacts", ap["artifact_id"])
            if not art or art["sha256"] != ap["sha256"]:
                return "E_INTEGRITY", "approval record does not match artifact"
            try:
                A.verify_stored(self.state_dir, slug, GATE_KIND[gate], ap["version"], ap["sha256"])
            except SentinelError:
                return "E_INTEGRITY", "stored artifact does not match its hash"
        return None

    def _start(self, run, reason=None):
        """Inside a transaction: start execution, or park the run. Returns the error to raise after commit."""
        problem = self._start_problem(run)
        if problem is None:
            self._move(run, "EXECUTING", machines.ENGINE, reason=reason or "both approvals valid")
            return None
        return self._park(run, problem)

    def _park_if_unapproved(self, run):
        problem = self._start_problem(run)
        return self._park(run, problem) if problem else None

    def _park(self, run, problem):
        code, why = problem
        if code == "E_INTEGRITY":
            self.reg.add_audit("engine", "engine", "integrity_failed", f"{run['slug']}/execution", reason=why)
        self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=why)
        return SentinelError(code, why, {"state": "NEEDS_HUMAN"})

    def advance(self, slug):
        """Take the engine's next approval-gated step: R12 or R12d. Does nothing in any other state."""
        deferred = None
        self._sync(slug)
        with self.reg.transaction():
            run = self._get_v2(slug)
            if self._starts_execution(run):
                deferred = self._start(run)
        result = self._finish_up(slug, run)
        if deferred:
            raise deferred
        return result

    @staticmethod
    def _joined(files):
        return "".join(f"### {f['path']}\n{f['text']}\n" for f in files)

    # ---- review (read side)
    def review(self, slug, gate=None):
        """Everything `sentinel review` shows. Re-hashes the shared files first (open point 2)."""
        run = self.load_run(slug)
        if gate is None:
            gate = "gherkin" if run["state"] in ("GHERKIN_REVIEW", "GHERKIN_APPROVED") else "specification"
        gate = self._gate(gate)
        kind = GATE_KIND[gate]
        art = self._latest_artifact(run, kind)
        if not art:
            raise SentinelError("E_PRECONDITION", f"no {gate} version exists for {slug} yet", {"gate": gate})
        A.verify_stored(self.state_dir, slug, kind, art["version"], art["sha256"])
        ap = self._latest_approval(run, gate)
        before = [a["version"] for a in self._rows(run, "approvals", gate=gate) if a["version"] < art["version"]]
        prev = max(before) if before else None
        adir = self.run_dir(slug) / "artifacts"
        info = {"gate": gate, "kind": kind, "version": art["version"], "sha256": art["sha256"],
                "approval_state": ap["state"] if ap else None, "run_state": run["state"], "diff": None,
                "errors": [], "warnings": []}
        if gate == "specification":
            text = self._stored_text(slug, art["version"])
            rep = A.validate_spec(text, slug, run["tier"], run["type"] or "feature")
            info.update(text=text, errors=list(rep.errors), warnings=list(rep.warnings))
            if not self.spec_path(slug).is_file():
                info["errors"].append(f"specs/{slug}/spec.md not found")
            old = self._stored_text(slug, prev) if prev else None
            new = text
        else:
            base = adir / A._stored_name("gherkin", art["version"])
            spec_text, spec_version = self._approved_spec(run)
            rep = A.validate_gherkin(base / "features", spec_text, spec_version)
            paths = rep.data.get("paths", [])
            files = [{"path": p, "text": (base / p).read_text(encoding="utf-8", errors="replace")} for p in paths]
            info.update(paths=paths, files=files, scenarios=rep.data.get("scenarios", []),
                        coverage=rep.data.get("coverage", {}), errors=list(rep.errors), warnings=list(rep.warnings))
            new = self._joined(files)
            old = None
            if prev:
                pbase = adir / A._stored_name("gherkin", prev)
                pp = A.gherkin_set_hash(pbase / "features")[1]
                old = self._joined([{"path": p, "text": (pbase / p).read_text(encoding="utf-8", errors="replace")}
                                    for p in pp])
        if prev:
            info["diff"] = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                       f"{gate} v{prev}", f"{gate} v{art['version']}"))
            info["previous_version"] = prev
        return info

    # ---- view
    def write_view(self, slug):
        run = self._get(slug)
        reasons = []
        for ev in self.reg.list_events(run["id"], "run.status_changed"):
            reasons = (ev["payload"] or {}).get("reasons", [])
        baseline = {r["repo_id"]: r["baseline_sha"] for r in self.reg.run_repos(run["id"])}
        tier = run["tier"]
        view = {
            "schema_version": 2, "slug": slug, "tier": tier, "initial_tier": run["initial_tier"],
            "adhoc": bool(run["adhoc"]), "stages": TIER_STAGES.get(tier, []), "completed": [], "sessions": {},
            "rounds": {"review": 0, "qa": 0, "release_check": 0}, "baseline": baseline,
            "started": run["created_at"], "state": run["state"],
            "execution_status": run["execution_status"], "acceptance_status": run["acceptance_status"],
            "acceptance_reasons": reasons,
        }
        directory = self.run_dir(slug)
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / f".state.json.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(view, indent=2))
        os.replace(tmp, directory / "state.json")
        return view

