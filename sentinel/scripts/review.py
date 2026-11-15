"""Review and QA stages (PE-01): the chain created at R14, findings, R16, R15 and the R20 `resolve` decisions.

ReviewOps is mixed into Engine. Source: plan/v1.1/phaseE/README.md points 10 to 14.
"""
import hashlib
import json
import re
from pathlib import Path

import machines
import scopes
from errors import SentinelError
from registry import _now

CHAIN = ["reviewer", "qa", "promotion", "docs"]
CHAIN_T4 = CHAIN + ["rollout", "retrospective"]
OPEN = ("CREATED", "QUEUED", "RUNNING", "WAITING_FOR_INPUT")
ROUTED = ("blocker", "major")


def cycle_name(cycle):
    """Short name of a cycle in messages: the Rule name or the feature file stem, lowercase with dashes."""
    label = cycle["behavior"] or ""
    text = label.split(":: Rule ", 1)[1] if ":: Rule " in label else Path(label.split(" :: ")[0]).stem
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class ReviewOps:
    # ---- the chain (R14)
    def review_chain_roles(self, run):
        tier = run["tier"] or 1
        return CHAIN_T4 if tier >= 4 else CHAIN if tier == 3 else []

    def chain_tasks(self, run):
        """The latest task of each chain role (a retry or a new chain replaces the older rows)."""
        latest = {}
        for t in self.reg.rows("tasks", run_id=run["id"]):
            if t["role"] in CHAIN_T4 and t["cycle_id"] is None:
                latest[t["role"]] = t
        return latest

    def _create_review_chain(self, run):
        """Inside a transaction: reviewer, qa, promotion, docs (and rollout, retrospective at tier 4), each after the one before."""
        roles = self.review_chain_roles(run)
        if not roles:
            return []
        cfg = self._run_config(run)
        repos = [r["repo_id"] for r in self.reg.run_repos(run["id"])] or [r["id"] for r in cfg.get("repos") or []]
        sname = self.state_dir.name
        rnd = self.finished_round(run)
        extra = {"baseline": {r["repo_id"]: r["baseline_sha"] for r in self.reg.run_repos(run["id"])},
                 "verification_round": rnd["round"] if rnd else None}
        resolved = [f for f in self.reg.rows("findings", run_id=run["id"]) if f["state"] == "resolved"]
        rechecked = {e["payload"]["finding"] for e in self.reg.list_events(run["id"], "finding.rechecked")}
        resolved = [f for f in resolved if f["id"] not in rechecked]
        writes = {"promotion": [f"{sname}/shared/regression/**"], "retrospective": [f"{sname}/shared/proposals/**"],
                  "docs": [g for r in repos for g in (f"{r}/docs/**", f"{r}/CHANGELOG.md")]}
        prev, made = None, []
        for role in roles:
            brief = None
            if role == "reviewer" and resolved:
                brief = "Re-check these resolved findings, and report any new ones:\n" + "\n".join(
                    f"- {f['id']} [{f['severity']}] {f['location'] or ''}: {f['text']}" for f in resolved) + "\n"
            if role == "qa":
                mode = "targeted" if (run["tier"] or 3) == 3 else "full"
                brief = f"QA mode: {mode}\n"
            row = self._make_task(run, role, f"{role} for {run['slug']}", repos, write=writes.get(role, []), brief=brief,
                                  depends_on=[prev] if prev else (), queue=prev is None, extra_input=extra)
            prev = row["id"]
            made.append(row["id"])
        for f in resolved:
            self._event(run, "finding.rechecked", machines.ENGINE, {"finding": f["id"]})
        return made

    # ---- findings
    def _resolve_findings(self, run):
        """Inside a transaction (R14): routed findings whose cycle is CYCLE_ACCEPTED are resolved."""
        for f in self.reg.rows("findings", run_id=run["id"]):
            if f["state"] == "routed" and f["cycle_id"]:
                c = self.reg.get_row("cycles", f["cycle_id"])
                if c and c["state"] == "CYCLE_ACCEPTED":
                    self.reg.update_row("findings", f["id"], state="resolved")
                    self._event(run, "finding.resolved", machines.ENGINE, {"finding": f["id"], "cycle": c["id"]})

    def open_findings(self, run, severities=ROUTED):
        return [f for f in self.reg.rows("findings", run_id=run["id"]) if f["state"] == "open" and f["severity"] in severities]

    def _result_findings(self, task):
        try:
            data = json.loads((self.task_dir(self.reg.get_run_by_id(task["run_id"])["slug"], task["id"]) / "result.json").read_text())
        except (OSError, ValueError):
            return []
        return [f for f in data.get("findings") or [] if isinstance(f, dict)]

    def _owner_cycles(self, run, path):
        """Live cycles whose accepted work changed `path` (workspace-relative)."""
        out = []
        links = self.reg.rows("trace_links", run_id=run["id"])
        for c in self.live_cycles(run):
            if any(l["from_kind"] == "cycle" and l["from_id"] == c["id"] and l["to_kind"] == "file" and l["to_id"] == path for l in links):
                out.append(c)
                continue
            if any(f"{r['repo_id']}/{r['path']}" == path for r in self.reg.rows("changed_files", cycle_id=c["id"])):
                out.append(c)
        return out

    def after_review_task(self, task_id):
        """After a COMPLETED reviewer or qa task: store its findings and route blockers and majors (R16)."""
        t = self._task_row(task_id)
        if t["role"] not in ("reviewer", "qa") or t["state"] != "COMPLETED" or t["cycle_id"]:
            return None
        run0 = self.reg.get_run_by_id(t["run_id"])
        if run0["state"] != "REVIEWING":
            return None
        found = self._result_findings(t)
        slug = run0["slug"]
        out = {"findings": [], "routed": []}
        with self.reg.transaction():
            run = self._get_v2(slug)
            if run["state"] != "REVIEWING" or self.reg.rows("findings", task_id=task_id):
                return None
            rows = []
            for f in found:
                if f.get("severity") not in ("blocker", "major", "minor") or not isinstance(f.get("text"), str):
                    continue
                fid = self.reg.insert_row("findings", {
                    "run_id": run["id"], "task_id": task_id, "source": t["role"], "severity": f["severity"],
                    "location": f.get("location"), "text": f["text"], "state": "open",
                    "category": f.get("category") or ("code_bug" if t["role"] == "qa" else None), "round": None})
                self._event(run, "finding.created", machines.ENGINE, {"finding": fid, "source": t["role"], "severity": f["severity"],
                                                                      "location": f.get("location")})
                rows.append(self.reg.get_row("findings", fid))
            out["findings"] = [r["id"] for r in rows]
            todo = [r for r in rows if r["severity"] in ROUTED]
            if todo:
                out["routed"] = self._route_findings(run, t, todo)
        self._finish_up(slug, run0)
        return out

    def _route_findings(self, run, task, todo):
        """Inside a transaction: R16 with a new cycle per owning behavior, or NEEDS_HUMAN."""
        cfg = self._run_config(run)
        source = task["role"]
        cap_key = "review_rounds" if source == "reviewer" else "qa_rounds"
        cap = (cfg.get("limits") or {}).get(cap_key)
        cap = cap if isinstance(cap, int) and not isinstance(cap, bool) and cap >= 1 else (2 if source == "reviewer" else 3)
        used = len([e for e in self.reg.list_events(run["id"], "review.routed") if e["payload"]["source"] == source])
        listing = "; ".join(f"[{f['severity']}] {f['text']}" for f in todo)
        if source == "reviewer" and (run["tier"] or 0) == 3 and any(f["severity"] == "blocker" for f in todo):
            self.reg.update_run(run["slug"], tier=4)  # the 0.1 rule: a blocker raises the tier, so the security gate applies
            self._event(run, "run.tier_raised", machines.ENGINE, {"from": 3, "to": 4, "reason": "review blocker"})
            self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason="security gate (tier 4) needs human approval before execution resumes")
            return []
        gaps = [f for f in todo if f["category"] == "spec_gap"]
        if gaps:
            self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=f"QA spec gap: {'; '.join(f['text'] for f in gaps)}")
            return []
        owners = {}
        for f in todo:
            path = (f["location"] or "").rsplit(":", 1)[0] if re.search(r":\d+$", f["location"] or "") else (f["location"] or "")
            cycles = self._owner_cycles(run, path)
            if not cycles:
                self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=f"finding has no owning cycle: {f['text']}")
                return []
            owners.setdefault(cycles[0]["id"], []).append(f)
        if used >= cap:
            self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=f"{source} round cap reached: {listing}")
            return []
        groups = {g["label"]: g for g in self._gherkin_groups(run)}
        made = []
        for cid, fs in owners.items():
            old = self.reg.get_row("cycles", cid)
            group = groups.get(old["behavior"])
            if group is None:
                self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=f"finding has no owning cycle: {fs[0]['text']}")
                return []
            new = self._insert_cycle(run, group, old["repo_id"], old["ordinal"] or 0, retry_of=old["id"])
            made.append(new)
            for f in fs:
                self.reg.update_row("findings", f["id"], state="routed", routed_to=new, cycle_id=new)
                self.reg.add_trace_link(run["id"], "finding", f["id"], "cycle", new)
        for other in self.reg.rows("tasks", run_id=run["id"]):
            if other["role"] in CHAIN_T4 and other["cycle_id"] is None and other["state"] in ("CREATED", "QUEUED"):
                self._cancel_in_tx(run, other, machines.ENGINE, "review finding routed", cascade=False)
        self._event(run, "review.routed", machines.ENGINE, {"source": source, "findings": [f["id"] for f in todo], "cycles": made})
        self._move(run, "EXECUTING", machines.ENGINE, reason=f"{source} finding routed")
        return made

    def cycle_finding_brief(self, run, cycle):
        fs = [f for f in self.reg.rows("findings", run_id=run["id"]) if f["cycle_id"] == cycle["id"]]
        if not fs:
            return None
        return ("A review finding was routed to this behavior. Write a test that reproduces it:\n"
                + "\n".join(f"- [{f['severity']}] {f['location'] or ''}: {f['text']}" for f in fs) + "\n")

    # ---- R15
    def check_r15(self, slug):
        """REVIEWING -> COMPLETED when no review task is open: acceptance computed, final SHAs, report, lock released."""
        run = self._get_v2(slug)
        if run["state"] != "REVIEWING":
            return False
        tasks = self.reg.rows("tasks", run_id=run["id"])
        if any(t["state"] in OPEN for t in tasks if t["role"] in CHAIN_T4 and t["cycle_id"] is None):
            return False
        if self.review_chain_roles(run) and not self.chain_tasks(run):
            return False
        self.complete_run(slug)
        return True

    # ---- R20 decisions
    def resolve(self, slug, *, user, channel="tty", comment=None, waive=None, approve_file=None, approve_clone=False,
                approve_security=False, resume=True):
        """A human's recorded decision on a parked run (R20): waive an open finding, approve a destructive migration file by
        its sha256, approve a real-data QA clone, approve the tier 4 security gate, then send the run back to where it was."""
        self._as_human(user, channel)
        self._sync(slug)
        done = []
        with self.reg.transaction():
            run = self._get_v2(slug)
            if run["state"] in machines.RUN_FINAL:
                raise SentinelError("E_TRANSITION", f"run is {run['state']}", {"state": run["state"]})
            if waive:
                f = self.reg.get_row("findings", waive)
                if not f or f["run_id"] != run["id"]:
                    raise SentinelError("E_NOT_FOUND", f"no finding {waive} in run {slug}", {"finding": waive})
                if f["state"] != "open":
                    raise SentinelError("E_PRECONDITION", f"finding {waive} is {f['state']}, not open", {"finding": waive})
                if not (comment or "").strip():
                    raise SentinelError("E_VALIDATION", "waiving a finding needs a comment")
                self.reg.update_row("findings", waive, state="waived", decided_by=user, comment=comment)
                self._event(run, "finding.waived", machines.HUMAN, {"finding": waive, "comment": comment})
                self.reg.add_audit(user, channel, "resolve", f"{slug}/{waive}", reason=f"waive: {comment}")
                done.append("waive")
            if approve_file:
                path = (self.workspace / approve_file)
                try:
                    path.resolve().relative_to(self.workspace.resolve())
                except ValueError:
                    raise SentinelError("E_VALIDATION", f"{approve_file} is outside the workspace")
                if not path.is_file():
                    raise SentinelError("E_NOT_FOUND", f"no file {approve_file}", {"path": approve_file})
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                self._approval(run, "migration", sha, user, channel, comment, approve_file)
                self.reg.add_audit(user, channel, "resolve", f"{slug}/{approve_file}", after_sha=sha, reason="approve migration")
                done.append("migration")
            if approve_clone:
                self._approval(run, "real_data_clone", None, user, channel, comment, "qa clone")
                self.reg.add_audit(user, channel, "resolve", f"{slug}/qa", reason="approve real-data clone")
                done.append("clone")
            if approve_security:
                ap = self._latest_approval(run, "specification", "APPROVED")
                self._approval(run, "security", ap["sha256"] if ap else None, user, channel, comment, "security gate")
                self.reg.add_audit(user, channel, "resolve", f"{slug}/security", reason="approve security gate")
                done.append("security")
        if resume and self._get_v2(slug)["state"] == "NEEDS_HUMAN":
            if not done and not (comment or "").strip():
                raise SentinelError("E_VALIDATION", "resuming needs a comment")
            self.resume_run(slug, comment or ", ".join(done), user=user, channel=channel)
            done.append("resume")
        return self._get_v2(slug)

    def _approval(self, run, gate, sha, user, channel, comment, what):
        self.reg.insert_row("approvals", {"run_id": run["id"], "gate": gate, "sha256": sha, "state": "APPROVED", "decision": "approve",
                                          "approver": user, "channel": channel, "comment": comment or what, "decided_at": _now(),
                                          "version": 1})
        self._event(run, "approval.decided", machines.HUMAN, {"gate": gate, "sha256": sha, "decision": "approve", "what": what,
                                                             "comment": comment})

    def qa_gate(self, run, task):
        """Before a qa task starts: a clone of real data needs a human when the policy says so. Returns the outcome or None."""
        cfg = self._run_config(run)
        clone = (cfg.get("qa") or {}).get("db_clone")
        if clone in (None, "none") or "real_data_clone" not in ((cfg.get("policies") or {}).get("human_required") or []):
            return None
        if any(a["state"] == "APPROVED" for a in self.reg.rows("approvals", run_id=run["id"], gate="real_data_clone")):
            return None
        why = "QA needs a clone of real data (policy real_data_clone)"
        with self.reg.transaction():
            run = self.reg.get_run_by_id(run["id"])
            self._park_run(run, why)
        self._finish_up(run["slug"], run)
        return self._outcome(task["id"], blocked=True, reason=why)
