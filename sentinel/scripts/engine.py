"""Run engine: the only place that changes version 2 run state.

Every change runs in one registry transaction: re-read the run, check the table
(machines.py), check preconditions, write the row and the event. The state.json
view is rewritten after the commit. Source: docs/contracts/state-transitions.md.
"""
import hashlib
import json
import os
from pathlib import Path

import machines
from errors import SentinelError
from registry import Registry, _now

WORKFLOW_VERSION = "2"
TIER_STAGES = {
    1: ["coder"],
    2: ["repro", "coder", "release_check", "metrics", "changelog"],
    3: ["specifier", "retriage", "coder", "cleaner", "reviewer", "qa", "promotion", "release_check", "docs", "metrics"],
    4: ["specifier", "retriage", "coder", "cleaner", "hardener", "reviewer", "qa", "promotion", "release_check", "docs", "rollout", "retrospective", "metrics"],
}
MISSING_EVIDENCE = "verification evidence missing"


class Engine:
    def __init__(self, state_dir, workspace, config, release_lock=None):
        self.state_dir = Path(state_dir)
        self.workspace = Path(workspace)
        self.config = config or {}
        self.reg = Registry.open(self.state_dir)
        self._release_lock = release_lock

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
        if rule == "R12d":
            raise SentinelError("E_PRECONDITION", "docs-only runs are not supported yet", {"from": frm, "to": to})
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
        if to in machines.RUN_FINAL:
            self._event(run, "run.status_changed", actor, {
                "execution_status": fields["execution_status"],
                "acceptance_status": fields.get("acceptance_status", run["acceptance_status"]),
                "reasons": reasons})
        return rule

    def _finish_up(self, slug, run_before):
        """After commit: rewrite the view, release the lock on a final state."""
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
        with self.reg.transaction():
            run = self._get_v2(slug)
            if machines.check_run(run["state"], to, actor) == "R25":
                self._accept(run, "accepted", actor)  # acceptance only; never recomputed
            else:
                self._move(run, to, actor, reason)
        return self._finish_up(slug, run)

    def complete(self, slug):
        return self.request_state(slug, "COMPLETED", machines.ENGINE)

    def set_tier(self, slug, tier, actor, reason=None):
        if isinstance(tier, bool) or not isinstance(tier, int) or not 1 <= tier <= 4:
            raise SentinelError("E_VALIDATION", f"tier must be 1-4, got {tier!r}")
        if actor not in machines.ACTORS:
            raise SentinelError("E_ACTOR", f"unknown actor {actor!r}", {"allowed": list(machines.ACTORS)})
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
        with self.reg.transaction():
            run = self._get_v2(slug)
            self._accept(run, value, actor)
        return self._finish_up(slug, run)

    def finish(self, slug, outcome, actor):
        """Legacy `run finish --outcome` on a version 2 run."""
        with self.reg.transaction():
            run = self._get_v2(slug)
            target = machines.finish_outcome(run["state"], outcome)[0]
            if target == "CANCELLED":
                self._move(run, "CANCELLED", actor, reason=f"run finish --outcome {outcome}")
        result = self._finish_up(slug, run)  # releases the lock when the run was cancelled
        if target == "COMPLETED":
            self._release(slug, result)
        return result

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

