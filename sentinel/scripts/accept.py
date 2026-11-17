"""Run completion, computed acceptance, final human acceptance and the run report (PE-01).

AcceptOps is mixed into Engine. R15 computes acceptance from evidence alone (VER-03); a human at a terminal or the dashboard
may then confirm or reject it (R25); a rejected run never changes. The report is built from the registry only, scrubbed and
reproducible. Source: plan/v1.1/phaseE/README.md points 14 to 16.
"""
import json
import subprocess
from pathlib import Path

import machines
import qa_scenarios as Q
import scopes
from errors import SentinelError
from registry import _now
from review import cycle_name
from util import sha_bytes

REPORT_SECTIONS = ["execution", "specification", "gherkin", "agents", "cycles", "verification", "regression", "findings",
                   "changed_files", "acceptance", "trace", "cost"]
NOT_REACHED = {"status": "not reached"}
BLOCKING = ("blocker", "major")


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def display_name(cycle):
    """Name of a cycle in people's text: the Rule name, else the feature file stem."""
    label = cycle["behavior"] or ""
    return label.split(":: Rule ", 1)[1] if ":: Rule " in label else Path(label.split(" :: ")[0]).stem


class AcceptOps:
    # ---- human acceptance state
    def acceptance_rows(self, run):
        return [a for a in self.reg.rows("approvals", run_id=run["id"], gate="acceptance")]

    def human_acceptance(self, run):
        rows = self.acceptance_rows(run)
        if not rows:
            return "pending"
        return "confirmed" if rows[-1]["decision"] == "accept" else "rejected"

    # ---- integrity
    def _evidence_problems(self, run, rows):
        bad = []
        for e in rows:
            if not e["output_artifact_id"]:
                continue
            art = self.reg.get_row("artifacts", e["output_artifact_id"])
            path = self.state_dir / art["path"] if art else None
            try:
                now = sha_bytes(path.read_bytes())
            except (OSError, AttributeError):
                now = None
            if now != e["output_sha256"] or (art and art["sha256"] != e["output_sha256"]):
                bad.append(art["path"] if art else e["output_artifact_id"])
        return bad

    def _evidence_stop(self, run, files):
        msg = "evidence output changed: " + ", ".join(files)
        with self.reg.transaction():
            run = self.reg.get_run_by_id(run["id"])
            self.reg.add_audit("engine", "engine", "integrity_failed", f"{run['slug']}/evidence", reason=msg)
            if run["state"] not in machines.RUN_FINAL and run["state"] != "NEEDS_HUMAN":
                self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=msg)
        self._finish_up(run["slug"], run)
        return SentinelError("E_INTEGRITY", msg, {"files": files})

    # ---- computation
    def latest_round(self, run):
        rows = [r for r in self._vrounds(run) if not r["interrupted"]]
        return max(rows, key=lambda r: r["round"]) if rows else None

    def _acceptance(self, run):
        """(status, reasons) from the registry alone; raises E_INTEGRITY (not handled here) for a changed evidence file."""
        slug = run["slug"]
        reasons = []
        for gate, kind in (("specification", "spec"), ("gherkin", "gherkin")):
            if gate == "gherkin" and run["type"] == "docs":
                continue
            ap = self._latest_approval(run, gate)
            ok = bool(ap) and ap["state"] == "APPROVED" and self._current_hash(slug, kind) == ap["sha256"]
            if not ok:
                reasons.append(f"{gate} approval missing or invalid")
        if run["type"] != "docs":
            open_c = [cycle_name(c) for c in self.live_cycles(run) if c["state"] != "CYCLE_ACCEPTED"]
            if open_c:
                reasons.append("cycles incomplete: " + ", ".join(open_c))
        reasons += [f"tdd exception evidence missing: {c['repo_id']} {display_name(c)}" for c in self._exception_gaps(run)]
        latest = self.latest_round(run)
        rows = self.round_rows(run, latest["round"]) if latest and latest["finished_at"] else []
        bad = self._evidence_problems(run, rows)
        if bad:
            raise SentinelError("E_INTEGRITY", "evidence output changed: " + ", ".join(bad), {"files": bad})
        migration_missing = False
        for e in rows:
            if e["kind"] == "migration":
                d = json.loads(e["detail"] or "{}")
                files = d.get("approved", []) + [x["file"] for x in d.get("destructive", [])]
                for f in files:
                    full = self.workspace / run_repo_path(self, run, e["repo_id"], f)
                    sha = sha_bytes(full.read_bytes()) if full.is_file() else None
                    if not any(a["state"] == "APPROVED" and a["sha256"] == sha for a in self.reg.rows("approvals", run_id=run["id"], gate="migration")):
                        migration_missing = True
                if e["classification"] == "destructive":
                    migration_missing = True
        fails = [e for e in rows if e["verdict"] == "fail" and e["kind"] not in ("scope",) and e["classification"] != "destructive"]
        if fails:
            reasons.append("required tests fail: " + ", ".join(f"{e['repo_id']} {e['kind']}" + (f" {e['name']}" if e["name"] else "")
                                                               for e in fails))
        if not latest or not latest["finished_at"]:
            reasons.append("verification evidence missing")
        else:
            miss = self._missing_evidence(run, latest, rows)
            if miss:
                reasons.append("verification evidence missing: " + ", ".join(miss))
            reasons += [f"verification evidence stale: {rid} changed after round {latest['round']}"
                        for rid in self._stale_repos(run, latest)]
        scope_bad = [e["repo_id"] for e in rows if e["kind"] == "scope" and e["verdict"] == "fail"]
        if scope_bad:
            reasons.append("scope exceeded: " + ", ".join(scope_bad))
        findings = [f for f in self.reg.rows("findings", run_id=run["id"]) if f["severity"] in BLOCKING]
        parts = []
        for state in ("open", "waived"):
            for sev in BLOCKING:
                n = len([f for f in findings if f["state"] == state and f["severity"] == sev])
                if n:
                    parts.append(f"{n} {state} {sev} finding" + ("" if n == 1 else "s"))
        if parts:
            reasons.append("required reviews open: " + ", ".join(parts))
        if run["type"] != "docs" and (run["tier"] or 0) >= 3:
            chain = self.chain_tasks(run)
            roles = [r for r in self.review_chain_roles(run) if r not in chain or chain[r]["state"] != "COMPLETED"]
            if roles:
                reasons.append("required reviews open: " + ", ".join(roles))
        missing = []
        if (run["tier"] or 0) >= 4 and not self.security_approved(run):
            missing.append("security")
        if migration_missing:
            missing.append("migration")
        if missing:
            reasons.append("required human approval missing: " + ", ".join(missing))
        return ("rejected" if reasons else "accepted"), reasons

    def _exception_cycles(self, run):
        return [c for c in self.live_cycles(run) if c["red_method"] == Q.QA and c["state"] == "CYCLE_ACCEPTED"]

    def _exception_gaps(self, run):
        """QA-Red cycles whose recorded exception is incomplete: no accepted red row, no exception field, no
        tdd.exception_recorded event for the cycle, or script hashes that no longer match the QA cache (TDD-09)."""
        events = self.reg.list_events(run["id"], "tdd.exception_recorded")
        out = []
        for c in self._exception_cycles(run):
            red = self._accepted_evidence(c, "red")
            ok = bool(red) and bool(red["exception"]) and any(e["payload"].get("cycle") == c["id"] for e in events)
            if ok:
                scripts = json.loads(red["scripts"] or "[]")
                ok = bool(scripts) and not Q.changed_scripts(self.workspace, scripts, self._scripts_rel(run, c["id"])) \
                    and not Q.changed_scripts(self.workspace, json.loads(c["approved_runner"] or "[]"))
            if not ok:
                out.append(c)
        return out

    def _tdd_exceptions(self, run):
        out = []
        for c in self._exception_cycles(run):
            red, green = self._accepted_evidence(c, "red"), self._accepted_evidence(c, "green")
            if not red:
                continue
            out.append({"repo": c["repo_id"], "cycle": c["id"], "name": display_name(c), "rule": Q.RULE, "method": Q.QA,
                        "red_evidence": red["id"], "green_evidence": green["id"] if green else None,
                        "scenarios": len(json.loads(c["scenarios"] or "[]")), "failed_before_green": json.loads(red["failing"] or "[]"),
                        "script_hashes": [{"path": x["path"], "sha256": x["sha256"], "exported": False}
                                          for x in json.loads(red["scripts"] or "[]")]})
        return out

    def _missing_evidence(self, run, latest, rows):
        """The checks the round planned (its summary) that left no evidence row; a round without a plan owes one scope row per repo."""
        plan = json.loads(latest["summary"] or "{}").get("plan")
        if plan is None:
            plan = {r["repo_id"]: [["scope", None]] for r in self.reg.run_repos(run["id"])}
        have = {(e["repo_id"], e["kind"], e["name"]) for e in rows}
        return [f"{rid} {kind}" + (f" {name}" if name else "") for rid, kinds in plan.items() for kind, name in kinds
                if (rid, kind, name) not in have]

    def _stale_repos(self, run, latest):
        """Repos whose tree is no longer the one the latest round verified: HEAD moved or a path changed that no review task
        (docs, promotion) was allowed to write. Rounds from before this check have no stored state and are not compared."""
        state = json.loads(latest["summary"] or "{}").get("repo_state") or {}
        imported = self.reg.list_events(run["id"], "run.imported")
        if imported and latest["finished_at"] <= imported[-1]["payload"]["imported_at"]:
            return []  # verified on the machine the bundle came from: this tree is not the one that was checked
        allowed = [g for t in self.chain_tasks(run).values() for g in self.task_scope(t["id"])]
        cfg = self._run_config(run)
        stale = []
        for rid, was in sorted(state.items()):
            now = self.repo_fingerprint(self._repo_path(cfg, rid))
            changed = [p for p in set(was["paths"]) | set(now["paths"]) if was["paths"].get(p) != now["paths"].get(p)]
            if now["head"] != was["head"] or any(not scopes.path_allowed(allowed, rid, p) for p in changed):
                stale.append(rid)
        return stale

    def security_approved(self, run):
        """A tier 4 run needs a human's approval of the security gate that was given for the specification it now has."""
        spec = self._latest_approval(run, "specification", "APPROVED")
        return any(a["state"] == "APPROVED" and (spec is None or a["sha256"] == spec["sha256"])
                   for a in self.reg.rows("approvals", run_id=run["id"], gate="security"))

    def compute_acceptance(self, slug):
        """The acceptance the engine computes now: {"status", "reasons"}. A changed evidence file is E_INTEGRITY and parks the run."""
        self._sync(slug)
        run = self._get_v2(slug)
        try:
            status, reasons = self._acceptance(run)
        except SentinelError as err:
            if err.code != "E_INTEGRITY":
                raise
            raise self._evidence_stop(run, err.details.get("files", [])) from err
        return {"status": status, "reasons": reasons}

    # ---- R15
    def complete_run(self, slug):
        """REVIEWING -> COMPLETED (R15): acceptance computed, final SHAs recorded, report written, lock released."""
        run0 = self._get_v2(slug)
        try:
            with self.reg.transaction():
                run = self._get_v2(slug)
                if run["state"] != "REVIEWING":
                    raise SentinelError("E_TRANSITION", f"R15 needs a REVIEWING run, run is {run['state']}", {"state": run["state"]})
                status, reasons = self._acceptance(run)
                self._move(run, "COMPLETED", machines.ENGINE, reason="review complete", acceptance=(status, reasons))
                for rr in self.reg.run_repos(run["id"]):
                    path = self._repo_path(self._run_config(run), rr["repo_id"])
                    sha = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
                    self.reg._c.execute("UPDATE run_repos SET final_sha=? WHERE run_id=? AND repo_id=?", (sha or None, run["id"], rr["repo_id"]))
                record = json.dumps({"status": status, "reasons": reasons}, sort_keys=True).encode()
                dest = self.run_dir(slug) / "acceptance.json"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(record)
                art = self.reg.insert_row("artifacts", {"run_id": run["id"], "kind": "acceptance", "version": 1,
                                                        "path": dest.relative_to(self.state_dir).as_posix(),
                                                        "sha256": sha_bytes(record), "created_at": _now()})
                self.reg.add_trace_link(run["id"], "run", slug, "acceptance", art)
        except SentinelError as err:
            if err.code == "E_INTEGRITY":
                raise self._evidence_stop(run0, err.details.get("files", [])) from err
            raise
        self.write_view(slug)
        self.write_report(slug)
        self._release(slug, self._get_v2(slug))
        return self._get_v2(slug)

    # ---- trace
    def trace_summary(self, slug):
        """{"gaps": [text], "failures": [text]}: a missing link is a gap, a rejected cycle a failure (TRC-02)."""
        run = self._get_v2(slug)
        links = self.reg.rows("trace_links", run_id=run["id"])
        tested = {l["from_id"] for l in links if l["from_kind"] == "scenario" and l["to_kind"] in ("test", "qa_script")}
        evid = {l["from_id"] for l in links if l["from_kind"] == "cycle" and l["to_kind"] == "evidence"}
        gaps, failures = [], []
        for c in self.live_cycles(run):
            if c["state"] == "REJECTED":
                failures.append(f"cycle {cycle_name(c)} rejected: {c['reason'] or 'rejected'}")
                continue
            for k in self._scenario_keys(c):
                if k not in tested:
                    gaps.append(f"scenario {k.split(' :: ')[-1]} has no " + ("QA script link" if c["red_method"] == Q.QA else "test link"))
            if c["id"] not in evid:
                gaps.append(f"cycle {cycle_name(c)} has no evidence link")
        return {"gaps": gaps, "failures": failures}

    # ---- report
    def build_report(self, slug):
        run = self._get_v2(slug)
        cfg = self._run_config(run)
        reg = self.reg
        events = reg.list_events(run["id"])
        past_exec = run["state"] in ("VERIFYING", "REVIEWING", "COMPLETED") or bool(self._vrounds(run))
        final = run["state"] == "COMPLETED"
        repos = reg.run_repos(run["id"])
        rep = {}
        rep["execution"] = {"slug": slug, "request": run["request"], "type": run["type"], "tier": run["tier"],
                            "initial_tier": run["initial_tier"], "state": run["state"],
                            "execution_status": run["execution_status"], "workflow_version": run["workflow_version"],
                            "repos": [{"id": r["repo_id"], "baseline_sha": r["baseline_sha"], "final_sha": r["final_sha"]} for r in repos],
                            "last_event_id": events[-1]["id"] if events else None}
        for gate, key in (("specification", "specification"), ("gherkin", "gherkin")):
            ap = self._latest_approval(run, gate, "APPROVED")
            rep[key] = ({"version": ap["version"], "sha256": ap["sha256"], "approver": ap["approver"], "decision": ap["decision"],
                         "decided_at": ap["decided_at"]} if ap else ({"status": "not applicable"} if gate == "gherkin" and run["type"] == "docs" else {"status": "not reached"}))
        tasks = reg.rows("tasks", run_id=run["id"])
        agents, changed, cost_total, unreported, tokens_total = [], [], 0.0, 0, 0
        for t in tasks:
            flags, claimed, summary = [], [], None
            try:
                tdir = self.task_dir(slug, t["id"])
                doc = json.loads((tdir / "result.json").read_text())
                claimed = [p for p in doc.get("claimed_changed_files") or [] if isinstance(p, str)]
                summary = doc.get("summary") if isinstance(doc.get("summary"), str) else None
            except (OSError, ValueError):
                pass
            try:
                actual = json.loads(t["changed_files"] or "[]")
            except ValueError:
                actual = []
            flags = [{"path": p, "flag": "not in evidence"} for p in claimed if p not in actual]
            reported = t["tokens"] is not None or t["cost"] is not None
            if not reported and t["state"] in ("COMPLETED", "FAILED"):
                unreported += 1
            tokens_total += t["tokens"] or 0
            cost_total += t["cost"] or 0.0
            agents.append({"id": t["id"], "role": t["role"], "repo": t["repo_id"], "adapter": t["adapter"], "provider": t["provider"],
                           "model": t["model"], "attempt": t["attempt"], "state": t["state"], "error_code": t["error_code"],
                           "started_at": t["started_at"], "finished_at": t["finished_at"], "claim_flags": flags,
                           "summary": summary, "reason": t["reason"],
                           "tokens": t["tokens"], "cost": t["cost"],
                           "cost_reason": None if reported else "not reported by provider"})
            if actual:
                changed.append({"task": t["id"], "role": t["role"], "files": actual})
        rep["agents"] = agents
        rep["cycles"] = [{"id": c["id"], "name": cycle_name(c), "behavior": c["behavior"], "repo": c["repo_id"], "state": c["state"],
                          "tests": json.loads(c["tests"] or "[]"), "retry_of": c["retry_of"]} for c in self.live_cycles(run)]
        latest = self.latest_round(run)
        if not past_exec or not latest:
            rep["verification"] = dict(NOT_REACHED)
            rep["regression"] = dict(NOT_REACHED)
        else:
            rows = self.round_rows(run, latest["round"])
            failures = [f"{e['repo_id']} {e['kind']}" + (f" {e['name']}" if e["name"] else "") for e in rows if e["verdict"] == "fail"]
            rep["verification"] = {
                "round": latest["round"], "finished": bool(latest["finished_at"]), "rounds": len([r for r in self._vrounds(run) if r["finished_at"]]),
                "rows": [{"repo": e["repo_id"], "kind": e["kind"], "name": e["name"], "verdict": e["verdict"],
                          "classification": e["classification"], "command": e["command"], "exit_code": e["exit_code"],
                          "output_sha256": e["output_sha256"], "repo_sha": e["repo_sha"]} for e in rows],
                "failures": failures, "not_run": [f"{e['repo_id']} {e['kind']}: {e['verdict']}" for e in rows
                                                  if e["verdict"] in ("not_configured", "disabled")],
                "summary": json.loads(latest["summary"] or "{}")}
            regression = {}
            for e in rows:
                if e["kind"] == "test":
                    base = self.baseline(run, e["repo_id"])
                    base_f = json.loads(base["failing"] or "[]") if base else []
                    now = json.loads(e["failing"] or "[]")
                    regression[e["repo_id"]] = {"new_failures": [t for t in now if t not in base_f],
                                                "still_failing": [t for t in now if t in base_f],
                                                "now_passing": [t for t in base_f if t not in now]}
            rep["regression"] = regression
        if run["state"] in ("REVIEWING", "COMPLETED") or reg.rows("findings", run_id=run["id"]):
            rep["findings"] = [{"id": f["id"], "source": f["source"], "severity": f["severity"], "location": f["location"],
                                "text": f["text"], "state": f["state"], "category": f["category"], "routed_to": f["routed_to"],
                                "decided_by": f["decided_by"], "comment": f["comment"]} for f in reg.rows("findings", run_id=run["id"])]
        else:
            rep["findings"] = dict(NOT_REACHED)
        rep["changed_files"] = changed
        reasons = reg.last_status_reasons(run["id"])
        if final:
            human = self.acceptance_rows(run)
            h = human[-1] if human else None
            rep["acceptance"] = {"execution_status": run["execution_status"], "computed": run["acceptance_status"], "reasons": reasons,
                                 "human": {"status": self.human_acceptance(run), "approver": h["approver"] if h else None,
                                           "decided_at": h["decided_at"] if h else None, "comment": h["comment"] if h else None}}
        else:
            rep["acceptance"] = {"status": "not reached", "acceptance_status": run["acceptance_status"]}
        rep["tdd_exceptions"] = self._tdd_exceptions(run)
        rep["trace"] = {**self.trace_summary(slug), "links": len(reg.rows("trace_links", run_id=run["id"]))}
        rep["cost"] = {"tokens": tokens_total if unreported < len(tasks) else None, "cost": cost_total if unreported < len(tasks) else None,
                       "partial": unreported > 0, "unreported_tasks": unreported,
                       "reason": "not reported by provider" if unreported else None}
        return rep

    def render_report_md(self, rep):
        lines = [f"# Run report: {rep['execution']['slug']}", ""]
        for key in REPORT_SECTIONS:
            lines += [f"## {key}", ""]
            sec = rep[key]
            if isinstance(sec, dict) and sec.get("status") == "not reached":
                lines += ["not reached", ""]
                continue
            if key == "agents":
                for a in sec:
                    tok = "not reported" if a["tokens"] is None else a["tokens"]
                    cost = "not reported" if a["cost"] is None else a["cost"]
                    lines.append(f"- {a['id']} {a['role']} ({a['adapter']}/{a['provider']}/{a['model']}) attempt {a['attempt']}: "
                                 f"{a['state']} {a['error_code'] or ''} tokens {tok} cost {cost}")
                    lines += [f"  - claim `{f['path']}`: {f['flag']}" for f in a["claim_flags"]]
            else:
                lines += ["```json", json.dumps(sec, indent=2), "```"]
            lines.append("")
        if rep.get("tdd_exceptions"):
            lines += ["## TDD exceptions", "", "QA scenarios were the Red evidence; no test files were committed.", ""]
            for x in rep["tdd_exceptions"]:
                lines.append(f"- {x['repo']} {x['name']}: {x['rule']}, {x['scenarios']} scenarios, red {x['red_evidence']}, "
                             f"green {x['green_evidence']}, failed before Green: {', '.join(x['failed_before_green'])}")
                lines += [f"  - script {h['path']} sha256 {h['sha256']} (not exported)" for h in x["script_hashes"]]
            lines.append("")
        return "\n".join(lines) + "\n"

    def write_report(self, slug):
        """report.json (scrubbed, reproducible) and report.md; registered as an artifact when its content changed."""
        rep = self.build_report(slug)
        scrub = self._scrubber()
        data = (scrub.scrub_text(json.dumps(rep, indent=2)) + "\n").encode("utf-8")
        md = scrub.scrub_text(self.render_report_md(json.loads(data))).encode("utf-8")
        rdir = self.run_dir(slug)
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "report.json").write_bytes(data)
        (rdir / "report.md").write_bytes(md)
        sha = sha_bytes(data)
        run = self._get_v2(slug)
        with self.reg.transaction():
            arts = self.reg.rows("artifacts", run_id=run["id"], kind="report")
            if not arts or arts[-1]["sha256"] != sha:
                self.reg.insert_row("artifacts", {"run_id": run["id"], "kind": "report", "version": len(arts) + 1,
                                                  "path": (rdir / "report.json").relative_to(self.state_dir).as_posix(),
                                                  "sha256": sha, "created_at": _now()})
        return {"sha256": sha, "json": str(rdir / "report.json"), "md": str(rdir / "report.md"), "report": json.loads(data)}

    def report_info(self, slug):
        """{"sha256", "report"} of the stored report.json (written first when the run has none)."""
        run = self._get_v2(slug)
        path = self.run_dir(slug) / "report.json"
        if not path.is_file():
            return self.write_report(slug)
        data = path.read_bytes()
        sha = sha_bytes(data)
        arts = self.reg.rows("artifacts", run_id=run["id"], kind="report")
        if arts and arts[-1]["sha256"] != sha:
            raise SentinelError("E_INTEGRITY", "report.json does not match the report the engine registered", {"path": "report.json"})
        return {"sha256": sha, "report": json.loads(data)}

    # ---- final human acceptance (R25)
    def pending_acceptance(self, slug):
        """What the accept screen shows: report hash, computed status, reasons, added dependencies, human state."""
        self._sync(slug)
        run = self._get_v2(slug)
        if run["state"] != "COMPLETED":
            raise SentinelError("E_TRANSITION", f"acceptance needs a COMPLETED run, run is {run['state']}", {"state": run["state"]})
        info = self.report_info(slug)
        rep = info["report"]
        deps = []
        latest = self.latest_round(run)
        if latest:
            for e in self.round_rows(run, latest["round"]):
                if e["kind"] == "deps":
                    deps += json.loads(e["detail"] or "{}").get("added", [])
        return {"slug": slug, "state": run["state"], "sha256": info["sha256"], "acceptance": run["acceptance_status"],
                "reasons": (rep.get("acceptance") or {}).get("reasons", []), "human": self.human_acceptance(run),
                "added_dependencies": deps}

    def accept(self, slug, decision, actor, *, sha256=None, prefix=None, comment=None, approver=None, approver_name=None,
               channel="tty"):
        """A human's final decision on a COMPLETED run: "accept" confirms what the engine computed, "reject" rejects it."""
        who = approver or actor
        self.channel, self.actor_name = channel, who
        try:
            return self._accept_decision(slug, decision, actor, sha256, prefix, comment, who, approver_name, channel)
        except SentinelError as err:
            self.audit(who, channel, "acceptance_refused", slug, reason=err.code)
            raise

    def _accept_decision(self, slug, decision, actor, sha256, prefix, comment, who, approver_name, channel):
        if actor != machines.HUMAN:
            raise SentinelError("E_ACTOR", f"{actor} may not decide acceptance", {"actor": actor, "allowed": [machines.HUMAN]})
        if decision not in ("accept", "reject"):
            raise SentinelError("E_VALIDATION", f"unknown decision {decision!r}", {"allowed": ["accept", "reject"]})
        if decision == "reject" and not (comment or "").strip():
            raise SentinelError("E_VALIDATION", "rejecting needs a comment")
        if (sha256 is None) == (prefix is None):
            raise SentinelError("E_VALIDATION", "give exactly one of sha256 or prefix")
        self._sync(slug)
        run = self._get_v2(slug)
        if run["state"] != "COMPLETED":
            raise SentinelError("E_TRANSITION", f"acceptance needs a COMPLETED run, run is {run['state']}", {"state": run["state"]})
        typed = (prefix if prefix is not None else sha256 or "").strip().lower()
        current = self.report_info(slug)["sha256"]
        ok = (len(typed) == 8 and current.startswith(typed)) if prefix is not None else typed == current
        if not ok:
            older = [a["sha256"] for a in self.reg.rows("artifacts", run_id=run["id"], kind="report")]
            known = any(h.startswith(typed) for h in older) if (prefix is not None and len(typed) == 8) else typed in older
            if known:
                raise SentinelError("E_APPROVAL_STALE", f"that hash is from an older report; the current sha256 is {current}",
                                    {"current_sha256": current})
            raise SentinelError("E_VALIDATION", "the typed hash does not match the report", {})
        if decision == "accept":
            for gate, kind in (("specification", "spec"), ("gherkin", "gherkin")):
                if gate == "gherkin" and run["type"] == "docs":
                    continue
                ap = self._latest_approval(run, gate)
                if not ap or ap["state"] != "APPROVED" or self._current_hash(slug, kind) != ap["sha256"]:
                    raise SentinelError("E_APPROVAL_STALE", f"the approved {gate} changed since completion", {"gate": gate})
        deferred = None
        with self.reg.transaction():
            run = self._get_v2(slug)
            if run["state"] != "COMPLETED":
                raise SentinelError("E_TRANSITION", f"acceptance needs a COMPLETED run, run is {run['state']}", {"state": run["state"]})
            human = self.human_acceptance(run)
            reasons = self.reg.last_status_reasons(run["id"])
            if run["acceptance_status"] == "rejected":
                raise SentinelError("E_PRECONDITION", "the run is rejected: " + "; ".join(reasons or ["rejected"]) +
                                    "; a rejected run never becomes accepted",
                                    {"reasons": reasons, "acceptance": "rejected"})
            if decision == "accept":
                if human == "confirmed":
                    raise SentinelError("E_PRECONDITION", "acceptance was already confirmed", {"acceptance": "confirmed"})
                try:
                    now_status, now_reasons = self._acceptance(run)
                except SentinelError as err:
                    if err.code != "E_INTEGRITY":
                        raise
                    deferred = err.details.get("files", [])
                else:
                    if now_status != "accepted":
                        raise SentinelError("E_INTEGRITY", "the evidence no longer supports the recorded acceptance: " + "; ".join(now_reasons),
                                            {"reasons": now_reasons})
            if deferred is None:
                machines.check_acceptance_change(run["acceptance_status"], "accepted" if decision == "accept" else "rejected",
                                                 machines.HUMAN)
                self.reg.insert_row("approvals", {
                    "run_id": run["id"], "gate": "acceptance", "sha256": current, "state": "APPROVED" if decision == "accept" else "REJECTED",
                    "decision": decision, "approver": who, "channel": channel, "comment": comment, "decided_at": _now(), "version": 1})
                payload = {"decision": decision, "sha256": current, "comment": comment, "approver_name": approver_name}
                self._event(run, "acceptance.decided", machines.HUMAN, payload)
                if decision == "reject":
                    why = f"rejected by human: {comment.strip()}"
                    self.reg.update_run(slug, acceptance_status="rejected")
                    self._event(run, "run.state_changed", machines.HUMAN, {"from": "COMPLETED", "to": "COMPLETED", "transition": "R25",
                                                                            "reason": why})
                    self._event(run, "run.status_changed", machines.HUMAN, {"execution_status": "completed", "acceptance_status": "rejected",
                                                                             "reasons": [why]})
                else:
                    self._event(run, "run.status_changed", machines.HUMAN, {"execution_status": "completed", "acceptance_status": "accepted",
                                                                             "reasons": [], "human_acceptance": "confirmed"})
                # wording per Phase F AC-VER-04k, confirmed by the owner 2026-11-17
                self.reg.add_audit(who, channel, "accepted" if decision == "accept" else "rejected", slug, after_sha=current,
                                   reason=decision)
        if deferred is not None:
            raise self._evidence_stop(run, deferred)
        return self._finish_up(slug, run)


def run_repo_path(engine, run, repo_id, rel):
    """Workspace-relative path of a repo-relative file."""
    return Path(engine._repo_path(engine._run_config(run), repo_id).relative_to(engine.workspace)) / rel
