"""TDD cycles (PD-02): planning at R12, cycle tasks, the baseline, Red verification, evidence, retries and caps.

CycleOps is mixed into Engine. The engine alone moves cycles (`machines.check_cycle`, actor engine); agents and their
result files never do (VER-02). A phase works the same way for Red, Green and Refactor:

  1. `_phase_task` creates the phase's task (write scope from the permission matrix, read-only approved tests).
  2. `start_task` moves the cycle to its running state; the agent runs; `finish_task` judges scope and result.
  3. `verify_phase(task_id)` runs after a COMPLETED task: the engine runs the tests itself, classifies the run,
     writes an evidence row (`_store_evidence`) and either moves the cycle forward and creates the next phase's
     task, or rejects (`_reject_phase`: retry task or, at the cap, REJECTED and NEEDS_HUMAN), or parks the run.
  `_verify_<phase>(run, task, cycle)` is looked up by phase name; Red is here, Green and Refactor plug in the same way.

Source: plan/v1.1/phaseD/README.md, docs/contracts/state-transitions.md section 4.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

import adapters
import artifacts as A
import binding
import boundary
import classifier
import machines
import qa_scenarios as Q
import scopes
import testsel
from errors import SentinelError
from registry import _new_id, _now
from tasks import CYCLE_ROLES, OPEN_STATES, retry_cap, _int

TDD_ROLES = CYCLE_ROLES
PHASE = {"tdd_red": "red", "qa_red": "red", "tdd_green": "green", "tdd_refactor": "refactor"}
ROLE = {"red": "tdd_red", "green": "tdd_green", "refactor": "tdd_refactor"}


def role_for(cycle, phase):
    """The task role of a phase: Red of a QA-scenario cycle is qa_red, everything else follows the phase name."""
    return "qa_red" if phase == "red" and cycle.get("red_method") == Q.QA else ROLE[phase]
# phase -> (cycle state before the task starts, cycle state while it runs)
STATES = {"red": ("PLANNED", "RED_RUNNING"), "green": ("RED_VERIFIED", "GREEN_RUNNING"),
          "refactor": ("GREEN_VERIFIED", "REFACTOR_RUNNING")}
OPEN_CYCLE = ("PLANNED", "RED_RUNNING", "RED_VERIFIED", "GREEN_RUNNING", "GREEN_VERIFIED", "REFACTOR_RUNNING",
              "REFACTOR_VERIFIED")
BASELINE_OK = ("pass", "assertion")
TEST_TIMEOUT = 1800
INVALIDATED = "approval invalidated"
LINE_CAP = 500


def scenario_rows(cycle):
    return json.loads(cycle["scenarios"] or "[]")


def json_list(value):
    try:
        out = json.loads(value) if value else []
    except ValueError:
        return []
    return out if isinstance(out, list) else []


class CycleOps:
    # ---- lookups
    def cycle_rows(self, run):
        return self.reg.rows("cycles", run_id=run["id"])

    def live_cycles(self, run):
        """The newest row of every current behavior (older rows of a replanned behavior, and rows of a Rule that is gone,
        are history), in file order."""
        by_behavior = {}
        for c in self.cycle_rows(run):
            if not c["superseded"]:  # rows of a Rule that was renamed or removed are history
                by_behavior[c["behavior"]] = c
        return sorted(by_behavior.values(), key=lambda c: (c["ordinal"] if c["ordinal"] is not None else 0))

    def _cycle(self, cycle_id):
        row = self.reg.get_row("cycles", cycle_id) if isinstance(cycle_id, str) else None
        if not row:
            raise SentinelError("E_NOT_FOUND", f"no cycle {cycle_id}", {"cycle": cycle_id})
        return row

    def _repo_path(self, cfg, repo_id):
        repo = next((r for r in cfg.get("repos") or [] if isinstance(r, dict) and r.get("id") == repo_id), {})
        return self.workspace / repo.get("path", repo_id)

    # ---- planning (R12)
    def _gherkin_groups(self, run):
        ap = self._latest_approval(run, "gherkin", "APPROVED")
        if not ap:
            return []
        base = self.run_dir(run["slug"]) / "artifacts" / A._stored_name("gherkin", ap["version"]) / "features"
        return A.behavior_groups(base)

    def _assignments(self, run):
        """([(group, repo id)], problem text or None). The repo comes from the Rule's @repo-<id> tag, else the Feature's;
        a run with one repo needs no tag (Phase D point 1)."""
        cfg = self._run_config(run)
        known = [r["id"] for r in cfg.get("repos") or [] if isinstance(r, dict) and r.get("id")]
        in_run = [r["repo_id"] for r in self.reg.run_repos(run["id"])]
        repos = in_run or known
        out = []
        for g in self._gherkin_groups(run):
            tag = g["repo_tags"][0] if g["repo_tags"] else None
            label = f"Rule {g['rule']}" if g["rule"] and g["rule"] != "(no rule)" else g["label"]
            if len(g["repo_tags"]) > 1:
                return out, f"{label} has several repo tags: " + ", ".join(g["repo_tags"]) + "; a behavior belongs to one repo"
            if tag is not None:
                if tag not in repos:
                    return out, f"unknown repo {tag}"
                repo = tag
            elif len(repos) == 1:
                repo = repos[0]
            else:
                return out, f"{label} names no repo"
            out.append((g, repo))
        return out, None

    def _planning_problem(self, run):
        _, problem = self._assignments(run)
        return ("E_PRECONDITION", problem) if problem else None

    def _insert_cycle(self, run, group, repo, ordinal, retry_of=None):
        scenarios = json.dumps([{"key": s["key"], "sha256": s["sha256"]} for s in group["scenarios"]])
        method = Q.method_for(self._run_config(run), repo)
        cid = self.reg.insert_row("cycles", {"run_id": run["id"], "behavior": group["label"], "state": "PLANNED",
                                             "repo_id": repo, "ordinal": ordinal, "scenarios": scenarios,
                                             "retry_of": retry_of, "red_method": method})
        if method == Q.QA:
            self._event(run, "tdd.exception_planned", machines.ENGINE,
                        {"cycle": cid, "repo": repo, "rule": Q.RULE, "method": method,
                         "scenarios": [Q.scenario_id(s["key"], s["text"]) for s in group["scenarios"]]})
        for s in group["scenarios"]:
            self.reg.remove_trace_links(run["id"], from_kind="scenario", from_id=s["key"], to_kind="cycle")
            self.reg.add_trace_link(run["id"], "scenario", s["key"], "cycle", cid)
        self._event(run, "cycle.planned", machines.ENGINE, {"cycle": cid, "behavior": group["label"], "repo": repo,
                                                           "scenarios": len(group["scenarios"]), "retry_of": retry_of})
        return cid

    def _plan_cycles(self, run):
        """Inside a transaction (R12): one cycle per behavior group. On a replan an accepted cycle is kept when every
        scenario of its group is byte-identical; any other group gets a new cycle and the old row stays as history. Rows of a
        Rule that was renamed or removed become history too (no orphan stays live to block R13 or a later Red)."""
        assigned, problem = self._assignments(run)
        if problem:
            raise SentinelError("E_PRECONDITION", problem, {"state": "NEEDS_HUMAN"})
        live = {c["behavior"]: c for c in self.live_cycles(run)}
        for ordinal, (group, repo) in enumerate(assigned):
            prev = live.get(group["label"])
            same = prev and json.loads(prev["scenarios"] or "[]") == [{"key": s["key"], "sha256": s["sha256"]} for s in group["scenarios"]]
            if prev and prev["repo_id"] == repo and (prev["state"] in OPEN_CYCLE or (prev["state"] == "CYCLE_ACCEPTED" and same)):
                self.reg.update_row("cycles", prev["id"], ordinal=ordinal)
                continue
            self._insert_cycle(run, group, repo, ordinal)
        current = {g["label"] for g, _ in assigned}
        for c in self.cycle_rows(run):
            if c["behavior"] not in current and not c["superseded"]:
                if c["state"] in OPEN_CYCLE:
                    c = self._move_cycle(run, c, "REJECTED", reason="behavior no longer in the approved Gherkin")
                self.reg.update_row("cycles", c["id"], superseded=1)

    def _replan_rejected(self, run):
        """Inside a transaction (R20 on a cap): a cycle rejected by a cap gets a new PLANNED cycle with retry_of."""
        groups = {g["label"]: g for g in self._gherkin_groups(run)}
        rows = self.cycle_rows(run)
        for c in self.live_cycles(run):
            if c["state"] == "REJECTED" and c["reason"] != INVALIDATED and c["behavior"] in groups \
                    and not any(r["retry_of"] == c["id"] for r in rows):
                self._insert_cycle(run, groups[c["behavior"]], c["repo_id"], c["ordinal"] or 0, retry_of=c["id"])

    # ---- moves
    def _move_cycle(self, run, cycle, to, reason=None, classification=None, **fields):
        """Inside a transaction: validate with the cycle table (actor engine), write the row and the event."""
        machines.check_cycle(cycle["state"], to, machines.ENGINE)
        self.reg.update_row("cycles", cycle["id"], state=to, reason=reason, **fields)
        payload = {"cycle": cycle["id"], "behavior": cycle["behavior"], "from": cycle["state"], "to": to,
                   "classification": classification, "reason": reason}
        if to == "CYCLE_ACCEPTED" and cycle.get("red_method") == Q.QA:
            payload["red_method"] = Q.QA
        self._event(run, "cycle.state_changed", machines.ENGINE, payload)
        return self._cycle(cycle["id"])

    def request_cycle_state(self, cycle_id, to, actor):
        """The only door for "move this cycle": the table says who may; the engine moves cycles from evidence only."""
        cycle = self._cycle(cycle_id)
        machines.check_cycle(cycle["state"], to, actor)
        raise SentinelError("E_PRECONDITION", f"{to} is decided by the engine from evidence, not requested", {"to": to})

    def _reject_open_cycles(self, run, reason):
        """Inside a transaction (R17, R18): every open cycle becomes REJECTED."""
        for c in self.cycle_rows(run):
            if c["state"] in OPEN_CYCLE:
                self._move_cycle(run, c, "REJECTED", reason=reason)

    # ---- profile values
    def _tdd_precheck(self, slug, role, repos):
        """Before a TDD task is created: the repo needs its test tooling. A gap parks the run and refuses (E_PRECONDITION)."""
        if role != "tdd_red" or not repos:
            return
        run = self._get_v2(slug)
        cfg = self._run_config(run)
        tools = scopes.test_tools(cfg, repos[0])
        for key in ("targeted_test", "test_report", "scenario_ref"):
            if not tools.get(key):
                break
        else:
            return
        msg = f"repo {repos[0]} has no {key} in its profile or repos[] entry"
        with self.reg.transaction():
            run = self._get_v2(slug)
            if run["state"] not in machines.RUN_FINAL and run["state"] != "NEEDS_HUMAN":
                self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=msg)
        self._finish_up(slug, run)
        raise SentinelError("E_PRECONDITION", msg, {"field": key, "repo": repos[0]})

    def _tdd_allowed(self, cfg, role, repo_id):
        return scopes.scope_globs(cfg, repo_id, "tests" if role == "tdd_red" else "production")

    def approved_files(self, run, repo_id):
        """Workspace-relative approved test files of a repo across the cycles of the run (Phase D point 11)."""
        out = []
        for c in self.cycle_rows(run):
            if c["repo_id"] == repo_id and c["state"] != "REJECTED" and not c["superseded"]:
                for item in json_list(c["approved_tests"]):
                    if item["path"] not in out:
                        out.append(item["path"])
        return out

    def _tdd_permissions(self, run, cfg, role, repo_id, write, readonly):
        allowed = self._tdd_allowed(cfg, role, repo_id)
        if write is None:
            write = allowed
        else:
            scopes.check_widening(role, write, allowed)
        if readonly is None and role != "tdd_red":
            readonly = self.approved_files(run, repo_id) + self.approved_script_paths(run, repo_id)
        return write, readonly

    # ---- cycle tasks
    def _cycle_blockers(self, run, task):
        """["cycle <id>"] for every earlier cycle of the same repo that is not accepted: a Red waits for it."""
        if task["role"] not in ("tdd_red", "qa_red") or not task["cycle_id"]:
            return []
        cyc = self.reg.get_row("cycles", task["cycle_id"])
        if not cyc:
            return []
        mine = cyc["ordinal"] or 0
        return [f"cycle {c['id']}" for c in self.live_cycles(run)
                if c["repo_id"] == cyc["repo_id"] and (c["ordinal"] or 0) < mine and c["state"] != "CYCLE_ACCEPTED"
                and c["id"] != cyc["id"]]

    def _objective(self, run, cycle, phase):
        what = {"red": "Write failing QA scenario scripts for" if cycle.get("red_method") == Q.QA else "Write failing tests for", "green": "Make the failing tests pass for",
                "refactor": "Refactor without changing behavior, for"}[phase]
        first = (self.live_cycles(run) or [{}])[0].get("id")
        if phase == "red" and run["type"] == "bug" and cycle["id"] == first:
            what = "Reproduce the reported bug: write a failing " + ("QA scenario script" if cycle.get("red_method") == Q.QA else "test") + " for"
        return f"{what} {cycle['behavior']} ({run['slug']})"

    def _phase_task(self, run, cycle, phase, retry_of=None, brief=None, attempt=1):
        """Inside a transaction: the task of a cycle phase; queued unless an earlier cycle of the repo is open."""
        role = role_for(cycle, phase)
        cfg = self._run_config(run)
        probe = {"role": role, "cycle_id": cycle["id"]}
        queue = not self._cycle_blockers(run, probe)
        row = self._make_task(run, role, self._objective(run, cycle, phase), [cycle["repo_id"]], cycle_id=cycle["id"],
                              retry_of=retry_of, attempt=attempt, brief=brief, must_follow_tdd=True,
                              max_retries=retry_cap(cfg, role), queue=queue)
        self.reg.update_row("cycles", cycle["id"], **{f"{phase}_task": row["id"]})
        return row

    def ensure_cycle_tasks(self, slug):
        """Create the tdd_red task of every PLANNED cycle that has none (what `sentinel next` does before it answers)."""
        run = self._get_v2(slug)
        if run["state"] != "EXECUTING":
            return []
        todo = [c for c in self.live_cycles(run) if c["state"] == "PLANNED" and not c["red_task"]]
        if not todo:
            return []
        for repo in dict.fromkeys(c["repo_id"] for c in todo if c["red_method"] != Q.QA):
            self._tdd_precheck(slug, "tdd_red", [repo])
        made = []
        with self.reg.transaction():
            run = self._get_v2(slug)
            for c in todo:
                cyc = self._cycle(c["id"])
                made.append(self._phase_task(run, cyc, "red", brief=self.cycle_finding_brief(run, cyc))["id"])
        self._finish_up(slug, run)
        return made

    def _cycle_task_started(self, run, task):
        """Inside start_task's transaction: the cycle enters its running state when its phase task starts."""
        if task["role"] not in TDD_ROLES or not task["cycle_id"]:
            return
        before, running = STATES[PHASE[task["role"]]]
        cyc = self.reg.get_row("cycles", task["cycle_id"])
        if cyc and cyc["state"] == before:
            self._move_cycle(run, cyc, running)

    # ---- baseline (TDD-03)
    def _run_tests(self, cfg, repo_id, command, tools, tests=(), info=None):
        """Run a test command in the repo and return what the classifier and the evidence row need. The command is
        rendered by testsel (selectors per test id); the JUnit report goes to a fresh engine-owned directory when the
        profile says `{report_dir}` (an agent cannot pre-write it), else a repo-relative report is cleared first and only a
        file written during the run counts. ValueError: a test name that a selector cannot carry."""
        path = self._repo_path(cfg, repo_id)
        tmp = self.state_dir / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        report_dir = tempfile.mkdtemp(prefix="report-", dir=str(tmp))
        try:
            cmd = testsel.render({**tools, "targeted_test": command}, tests, info or {}, report_dir)
            classifier.clear_report(path, tools.get("test_report"), report_dir)
            timeout = (cfg.get("policies") or {}).get("test_timeout_seconds")
            timeout = timeout if _int(timeout) and timeout > 0 else TEST_TIMEOUT
            started, began = _now(), time.time()
            code, text, _ = Q.run_command(cmd, path, adapters.child_env(cfg), timeout)
            return {"command": cmd, "exit_code": code, "output": text, "started_at": started, "finished_at": _now(),
                    "report": classifier.read_report(path, tools.get("test_report"), report_dir, began - 2), "cwd": repo_id,
                    "repo_sha": boundary.git(path, "rev-parse", "HEAD").strip()}
        finally:
            shutil.rmtree(report_dir, ignore_errors=True)

    def _scrubber(self):
        import scrub
        return scrub.Scrubber(self.workspace, scrub.env_values(self.workspace))

    def _store_evidence(self, run, kind, repo_id, *, task=None, cycle=None, ran=None, cl=None, verdict=None, reason=None,
                        failing=None, counts=None, tests=None, extra=None):
        """Inside a transaction: an evidence row written by the engine from its own test run, with the scrubbed output
        stored as a file (SEC-06). `ran` is _run_tests output (None when no test command ran)."""
        eid = _new_id("evidence")
        row = {"id": eid, "run_id": run["id"], "task_id": task["id"] if task else None, "cycle_id": cycle["id"] if cycle else None,
               "kind": kind, "repo_id": repo_id, "classification": (cl or {}).get("classification"), "verdict": verdict,
               "reason": reason, "provider": task["provider"] if task else None, "model": task["model"] if task else None,
               "failing": json.dumps(failing if failing is not None else (cl or {}).get("failing", [])),
               "tests": json.dumps(tests) if tests is not None else None,
               "method": cycle["red_method"] if cycle and kind in ("red", "green", "refactor") else None}
        if extra:
            row.update(extra)
        if counts is None and cl:
            counts = (cl["passed"], cl["failed"], cl["skipped"])
        if counts:
            row.update(passed=counts[0], failed=counts[1], skipped=counts[2])
        if ran:
            clean = self._scrubber().scrub_text(ran["output"])
            data = clean.encode("utf-8")
            dest = self.run_dir(run["slug"]) / "artifacts" / f"evidence-{eid}.log"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            art = self.reg.insert_row("artifacts", {"run_id": run["id"], "kind": "test_output", "version": 1,
                                                    "path": dest.relative_to(self.state_dir).as_posix(),
                                                    "sha256": hashlib.sha256(data).hexdigest(), "created_at": _now()})
            row.update(command=ran["command"], cwd=ran["cwd"], exit_code=ran["exit_code"], started_at=ran["started_at"],
                       finished_at=ran["finished_at"], repo_sha=ran["repo_sha"], output_artifact_id=art,
                       output_sha256=hashlib.sha256(data).hexdigest(),
                       env=json.dumps({"platform": sys.platform, "python": sys.version.split()[0]}))
        self.reg.insert_row("evidence", row)
        self._event(run, "evidence.recorded", machines.ENGINE,
                    {"kind": kind, "exit_code": row.get("exit_code"), "passed": row.get("passed"),
                     "failed": row.get("failed"), "classification": row["classification"], "evidence": eid,
                     "cycle": row["cycle_id"], "verdict": verdict})
        return eid

    def baseline(self, run, repo_id):
        """The latest usable baseline evidence row of a repo, or None."""
        rows = [e for e in self.reg.rows("evidence", run_id=run["id"], kind="baseline", repo_id=repo_id)
                if e["classification"] in BASELINE_OK]
        return rows[-1] if rows else None

    def ensure_baseline(self, run, repo_id):
        """Run the repo's full test command once, before its first Red, and store the evidence row. Returns the
        classification; a class that is not pass or assertion parks the run (NEEDS_HUMAN)."""
        if self.baseline(run, repo_id):
            return "pass"
        cfg = self._run_config(run)
        tools = scopes.test_tools(cfg, repo_id)
        if not tools["test"]:
            return self._park_baseline(run, repo_id, "unknown", f"repo {repo_id} has no test command")
        ran = self._run_tests(cfg, repo_id, tools["test"], tools)
        cl = classifier.classify(ran["exit_code"], ran["output"], ran["report"], tools["failure_patterns"])
        with self.reg.transaction():
            run = self.reg.get_run_by_id(run["id"])
            self._store_evidence(run, "baseline", repo_id, ran=ran, cl=cl, verdict="recorded")
            if cl["classification"] not in BASELINE_OK and run["state"] != "NEEDS_HUMAN":
                self._move(run, "NEEDS_HUMAN", machines.ENGINE,
                           reason=f"baseline for {repo_id} failed: {cl['classification']}")
        self._finish_up(run["slug"], run)
        return cl["classification"]

    def _park_baseline(self, run, repo_id, klass, why):
        with self.reg.transaction():
            run = self.reg.get_run_by_id(run["id"])
            if run["state"] != "NEEDS_HUMAN":
                self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=f"baseline for {repo_id} failed: {klass} ({why})")
        self._finish_up(run["slug"], run)
        return klass

    def _before_dispatch(self, run, task):
        """Before `task run` starts a TDD task: the baseline of its repo. Returns the refused outcome, or None."""
        if task["role"] in ("tdd_green", "tdd_refactor"):
            return self._check_approved_tests(run, task)
        if task["role"] == "qa":
            return self.qa_gate(run, task)
        if task["role"] == "qa_red":
            return self.qa_gate(run, task) or self._check_qa_files(run, task)
        if task["role"] != "tdd_red":
            return None
        klass = self.ensure_baseline(run, task["repo_id"])
        if klass not in BASELINE_OK:
            return self._outcome(task["id"], blocked=True, reason=self._state_reason(self.reg.get_run_by_id(run["id"]), "NEEDS_HUMAN"))
        return None

    # ---- verification
    def verify_phase(self, task_id):
        """After a COMPLETED tdd task: verify its phase. None when nothing is to verify (already done, no verifier)."""
        task = self._task_row(task_id)
        if task["role"] not in TDD_ROLES or task["state"] != "COMPLETED" or not task["cycle_id"]:
            return None
        run = self.reg.get_run_by_id(task["run_id"])
        cycle = self._cycle(task["cycle_id"])
        phase = PHASE[task["role"]]
        verify = getattr(self, f"_verify_{phase}", None)
        if verify is None or cycle["state"] != STATES[phase][1] or run["state"] != "EXECUTING":
            return None
        if cycle["red_method"] == Q.QA:
            return self._verify_qa_locked(task_id, verify)
        if self.reg.rows("evidence", task_id=task_id):
            return None
        return verify(run, task, cycle)

    def resume_verification(self, slug):
        """A COMPLETED phase task whose cycle is still running and that has no evidence row (the process died between
        task and verification) is verified now."""
        run = self._get_v2(slug)
        if run["state"] != "EXECUTING":
            return []
        out = []
        for c in self.live_cycles(run):
            for phase, (_, running) in STATES.items():
                task_id = c[f"{phase}_task"]
                if c["state"] == running and task_id and self._task_row(task_id)["state"] == "COMPLETED":
                    got = self.verify_phase(task_id)
                    if got:
                        out.append(got)
        return out

    def _approved_changed(self, run, repo_id):
        """Workspace-relative approved test files of the repo whose bytes differ from what Red approved."""
        changed = []
        for c in self.cycle_rows(run):
            if c["repo_id"] != repo_id or c["state"] == "REJECTED" or c["superseded"]:
                continue
            for item in json_list(c["approved_tests"]):
                try:
                    now = hashlib.sha256((self.workspace / item["path"]).read_bytes()).hexdigest()
                except OSError:
                    now = None
                if now != item["sha256"] and item["path"] not in changed:
                    changed.append(item["path"])
        return changed

    def _integrity_stop(self, run, ref, changed, what="test file", msg=None):
        """The run goes to NEEDS_HUMAN: a human edit of an approved test file or QA script (E_INTEGRITY). Returns the message."""
        msg = msg or f"approved {what} changed since Red: " + ", ".join(changed)
        with self.reg.transaction():
            run = self.reg.get_run_by_id(run["id"])
            self.reg.add_audit("engine", "engine", "integrity_failed", f"{run['slug']}/{ref}", reason=msg)
            self._park_run(run, msg)
        self._finish_up(run["slug"], run)
        return msg

    def _check_approved_tests(self, run, task):
        """Before Green or Refactor starts: every approved test file of the repo must still have the bytes Red approved
        (Phase D point 11). A human edit is E_INTEGRITY: the run goes to NEEDS_HUMAN and the task does not start."""
        cycle = self.reg.get_row("cycles", task["cycle_id"]) if task["cycle_id"] else None
        if cycle and cycle["red_method"] == Q.QA:
            return self._check_qa_files(run, task)
        changed = self._approved_changed(run, task["repo_id"])
        if not changed:
            return None
        msg = self._integrity_stop(run, task["id"], changed)
        return self._outcome(task["id"], blocked=True, error="E_INTEGRITY", reason=msg, files=changed)

    def _check_qa_files(self, run, task):
        """Before a QA task starts: the scripts of the repo's accepted QA cycles and the runner files are as Red approved them."""
        gone = self.qa_changed(run, task["repo_id"])
        if not gone:
            return None
        msg = self._integrity_stop(run, task["id"], gone, "QA script or runner file")
        return self._outcome(task["id"], blocked=True, error="E_INTEGRITY", reason=msg, files=gone)

    def accepted_tests(self, run, cycle):
        """Test ids of every CYCLE_ACCEPTED cycle of the same repo, apart from `cycle`: the tests that must stay green."""
        out = []
        for c in self.live_cycles(run):
            if c["id"] != cycle["id"] and c["repo_id"] == cycle["repo_id"] and c["state"] == "CYCLE_ACCEPTED":
                out += [t for t in json_list(c["tests"]) if t not in out]
        return out

    def test_info(self, run, cycle, extra=None):
        """{test id: {"file", "class", "method"}} of the cycle's tests and the accepted ones, for the selector templates."""
        info = {}
        for c in [cycle] + [c for c in self.live_cycles(run) if c["id"] != cycle["id"] and c["repo_id"] == cycle["repo_id"]
                            and c["state"] == "CYCLE_ACCEPTED"]:
            try:
                got = json.loads(c["test_info"] or "{}")
            except ValueError:
                got = {}
            info.update(got if isinstance(got, dict) else {})
        info.update(extra or {})
        return info

    def related_tests(self, run, cycle):
        """Test ids a Green or Refactor of `cycle` runs: its own, then those of every CYCLE_ACCEPTED cycle of the same repo."""
        out = list(json_list(cycle["tests"]))
        return out + [t for t in self.accepted_tests(run, cycle) if t not in out]

    def _flag(self, run, task, text=None, command=None):
        """Keep what the agent claimed in the task report and flag it: only the engine's own run is evidence. With
        `command`, every claimed command that differs from the one the engine ran; with `text`, the result summary."""
        tdir = self.task_dir(run["slug"], task["id"])
        try:
            report = json.loads((tdir / "report.json").read_text(encoding="utf-8"))
            result = json.loads((tdir / "result.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        flags = report.setdefault("claim_flags", [])
        if text is not None:
            flags.append({"claim": result.get("summary"), "flag": f"differs from the evidence: {text}"})
        for claim in result.get("claimed_commands") or [] if command is not None else []:
            if isinstance(claim, dict) and claim.get("command") != command:
                flags.append({"claim": claim.get("command"), "flag": f"differs from the evidence: the engine ran {command}"})
        (tdir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    def _verify_green(self, run, task, cycle):
        return self._verify_run(run, task, cycle, "green")

    def _verify_refactor(self, run, task, cycle):
        return self._verify_run(run, task, cycle, "refactor")

    def _verify_run(self, run, task, cycle, phase):
        """Green and Refactor: the engine runs the cycle's tests and those of the accepted cycles and judges them itself;
        every one must be present and pass ("rest unchanged")."""
        if cycle["red_method"] == Q.QA:
            return self._verify_qa(run, task, cycle, phase)
        cfg = self._run_config(run)
        repo = cycle["repo_id"]
        tools = scopes.test_tools(cfg, repo)
        changed = self._approved_changed(run, repo)  # a human edit since the dispatch check is an integrity failure
        if changed:
            msg = self._integrity_stop(run, task["id"], changed)
            return {"verdict": "needs_human", "reason": msg, "classification": None, "cycle": cycle["id"], "evidence": None,
                    "retry": None}
        own = json_list(cycle["tests"])
        related = self.accepted_tests(run, cycle)
        every = own + [t for t in related if t not in own]
        base_row = self.baseline(run, repo)
        try:
            ran = self._run_tests(cfg, repo, tools["targeted_test"], tools, every, self.test_info(run, cycle))
        except ValueError as err:
            self._park_run_tx(run, f"cycle {cycle['behavior']}: {phase} cannot select its tests: {err}")
            return {"verdict": "needs_human", "reason": str(err), "classification": None, "cycle": cycle["id"],
                    "evidence": None, "retry": None}
        cl = classifier.classify(ran["exit_code"], ran["output"], ran["report"], tools["failure_patterns"], new_tests=own,
                                 baseline_failing=json_list(base_row["failing"]) if base_row else [], related_tests=related,
                                 summary_patterns=tools.get("summary_patterns"))
        verdict, reason = classifier.verify_green(cl, own)
        if verdict == "rejected" and cl["classification"] in classifier.RETRY_CLASSES:
            line = classifier.output_line(cl["classification"], ran["output"], tools["failure_patterns"])
            reason = f"{cl['classification'].replace('_', ' ')}: {line}" if line else reason
        self._flag(run, task, command=ran["command"])
        failing = [t for t in every if t in cl["failing"]] if verdict == "rejected" else []
        with self.reg.transaction():
            run = self.reg.get_run_by_id(run["id"])
            cycle = self._cycle(cycle["id"])
            if cycle["state"] != STATES[phase][1] or run["state"] != "EXECUTING":
                return None
            eid = self._store_evidence(run, phase, repo, task=task, cycle=cycle, ran=ran, cl=cl, verdict=verdict,
                                       reason=reason, failing=failing, tests=every)
            result = {"verdict": verdict, "reason": reason, "classification": cl["classification"], "cycle": cycle["id"],
                      "evidence": eid, "retry": None}
            if verdict == "accepted":
                self._accept_phase(run, task, cycle, phase)
            elif verdict == "needs_human":
                line = classifier.output_line("unknown", ran["output"], {})
                self._park_run(run, f"cycle {cycle['behavior']}: {phase} run could not be classified: {self._clean(line)}")
            else:
                self._event(run, f"{phase}.rejected", machines.ENGINE,
                            {"cycle": cycle["id"], "evidence": eid, "reason": reason, "failing": failing})
                lines = [classifier.output_line(cl["classification"], ran["output"], tools["failure_patterns"])] \
                    if cl["classification"] in classifier.RETRY_CLASSES else []
                result["retry"] = self._reject_phase(run, task, cycle, phase, reason, cl["classification"], lines)
        self._finish_up(run["slug"], run)
        if verdict == "accepted" and phase == "refactor":
            self.check_r13(run["slug"])
        return result

    def _accept_phase(self, run, task, cycle, phase):
        """Inside a transaction: the phase passed. Green plans the Refactor task; Refactor tries to accept the cycle."""
        if phase == "green":
            moved = self._move_cycle(run, cycle, "GREEN_VERIFIED", classification="pass", green_task=task["id"])
            self._link_files(run, moved)
            self._phase_task(run, moved, "refactor")
            return
        moved = self._move_cycle(run, cycle, "REFACTOR_VERIFIED", classification="pass", refactor_task=task["id"])
        self._link_files(run, moved)
        self._try_accept(run, moved)
        self._queue_ready(run)

    def _link_files(self, run, cycle):
        """cycle -> file links: production files the Green and Refactor attempts changed and left in place."""
        cfg = self._run_config(run)
        self.reg.remove_trace_links(run["id"], from_kind="cycle", from_id=cycle["id"], to_kind="file")
        seen = []
        for rec in self.reg.rows("changed_files", cycle_id=cycle["id"]):
            if rec["phase"] not in ("tdd_green", "tdd_refactor") or not rec["repo_id"]:
                continue
            full = f"{rec['repo_id']}/{rec['path']}"
            if scopes.classify(cfg, rec["repo_id"], rec["path"]) != "test" and full not in seen \
                    and (self.workspace / full).exists():
                seen.append(full)
        for full in seen:
            self.reg.add_trace_link(run["id"], "cycle", cycle["id"], "file", full)

    # ---- acceptance and evidence completeness (TDD-06)
    def _accepted_evidence(self, cycle, phase):
        rows = [e for e in self.reg.rows("evidence", cycle_id=cycle["id"], kind=phase) if e["verdict"] == "accepted"]
        return rows[-1] if rows else None

    def _evidence_gaps(self, cycle):
        """Items an accepted cycle still lacks (README point 16), and the ones whose stored output no longer matches."""
        gaps, tampered = [], []
        for phase, klass in (("red", "assertion"), ("green", "pass"), ("refactor", "pass")):
            e = self._accepted_evidence(cycle, phase)
            if e is None:
                gaps.append(f"{phase} evidence")
                continue
            if not e["output_artifact_id"] or not e["output_sha256"]:
                gaps.append(f"{phase} output")
            if not e["repo_sha"]:
                gaps.append(f"{phase} repo_sha")
            for col in ("command", "cwd", "exit_code", "started_at", "finished_at", "env", "task_id"):
                if e[col] is None:
                    gaps.append(f"{phase} {col}")
            if e["classification"] != klass:
                gaps.append(f"{phase} classification")
            if cycle["red_method"] == Q.QA:
                gaps += self._qa_gaps(cycle, phase, e)
            elif phase != "refactor" and not [r for r in self.reg.rows("changed_files", cycle_id=cycle["id"])
                                              if r["phase"] == f"tdd_{phase}"]:
                gaps.append(f"{phase} changed files")
            art = self.reg.get_row("artifacts", e["output_artifact_id"]) if e["output_artifact_id"] else None
            if art and e["output_sha256"]:
                try:
                    now = hashlib.sha256((self.state_dir / art["path"]).read_bytes()).hexdigest()
                except OSError:
                    now = None
                if now != e["output_sha256"] or art["sha256"] != e["output_sha256"]:
                    tampered.append(f"{phase} output")
        return gaps, tampered

    def _try_accept(self, run, cycle):
        """Inside a transaction: REFACTOR_VERIFIED -> CYCLE_ACCEPTED when the evidence is complete and intact. Otherwise
        the cycle stays and the run goes to NEEDS_HUMAN. Returns (code, message, details) of a refusal, else None."""
        changed = self._approved_changed(run, cycle["repo_id"])
        if changed:
            msg = "approved test file changed since Red: " + ", ".join(changed)
            self.reg.add_audit("engine", "engine", "integrity_failed", f"{run['slug']}/{cycle['id']}", reason=msg)
            self._park_run(run, msg)
            return "E_INTEGRITY", msg, {"changed": changed}
        if cycle["red_method"] == Q.QA:
            gone = self.qa_changed(run, cycle["repo_id"])
            if gone:
                msg = "approved QA script or runner file changed since Red: " + ", ".join(gone)
                self.reg.add_audit("engine", "engine", "integrity_failed", f"{run['slug']}/{cycle['id']}", reason=msg)
                self._park_run(run, msg)
                return "E_INTEGRITY", msg, {"changed": gone}
        gaps, tampered = self._evidence_gaps(cycle)
        if gaps:
            msg = f"evidence incomplete for cycle {cycle['behavior']}"
            self._park_run(run, msg)
            return "E_PRECONDITION", f"{msg}: " + ", ".join(gaps), {"missing": gaps}
        if tampered:
            msg = f"evidence changed for cycle {cycle['behavior']}: " + ", ".join(tampered)
            self.reg.add_audit("engine", "engine", "integrity_failed", f"{run['slug']}/{cycle['id']}", reason=msg)
            self._park_run(run, msg)
            return "E_INTEGRITY", msg, {"changed": tampered}
        moved = self._move_cycle(run, cycle, "CYCLE_ACCEPTED", accepted_at=_now())
        self.reg.remove_trace_links(run["id"], from_kind="cycle", from_id=moved["id"], to_kind="evidence")
        for phase in ("red", "green", "refactor"):
            self.reg.add_trace_link(run["id"], "cycle", moved["id"], "evidence", self._accepted_evidence(moved, phase)["id"])
        return None

    def accept_cycle(self, cycle_id):
        """The engine's move REFACTOR_VERIFIED -> CYCLE_ACCEPTED (also what `sentinel next` does for a verified cycle)."""
        cycle = self._cycle(cycle_id)
        machines.check_cycle(cycle["state"], "CYCLE_ACCEPTED", machines.ENGINE)
        with self.reg.transaction():
            run = self.reg.get_run_by_id(cycle["run_id"])
            problem = self._try_accept(run, self._cycle(cycle_id))
        self._finish_up(run["slug"], run)
        if problem:
            raise SentinelError(problem[0], problem[1], problem[2])
        self.check_r13(run["slug"])
        return self._cycle(cycle_id)

    # ---- R13 (ORC-01)
    def check_r13(self, slug):
        """EXECUTING -> VERIFYING when every cycle is accepted and the required extra stages are done (point 19). Runs as
        engine bookkeeping; nobody else can request it (E_ACTOR)."""
        run = self._get_v2(slug)
        if run["state"] != "EXECUTING":
            return False
        for c in self.live_cycles(run):
            if c["state"] == "REFACTOR_VERIFIED":
                try:
                    self.accept_cycle(c["id"])
                except SentinelError:
                    return False
        run = self._get_v2(slug)
        if run["state"] != "EXECUTING":
            return False
        tasks = self.reg.rows("tasks", run_id=run["id"])
        if run["type"] == "docs":
            docs = [t for t in tasks if t["role"] == "docs"]
            ready = bool(docs) and all(self._satisfied(t["id"]) or t["state"] == "CANCELLED" for t in docs) \
                and any(self._satisfied(t["id"]) for t in docs)
        else:
            live = self.live_cycles(run)
            ready = bool(live) and all(c["state"] == "CYCLE_ACCEPTED" for c in live)
            if ready and (run["tier"] or 0) >= 4:
                hard = [t for t in tasks if t["role"] == "hardener"]
                ready = any(t["state"] == "COMPLETED" for t in hard) and not any(
                    t["state"] in ("CREATED", "QUEUED", "RUNNING", "WAITING_FOR_INPUT") for t in hard)
        if not ready:
            return False
        with self.reg.transaction():
            run = self._get_v2(slug)
            if run["state"] != "EXECUTING":
                return False
            self._move(run, "VERIFYING", machines.ENGINE, reason="all cycles accepted" if run["type"] != "docs" else "docs task completed")
        self._finish_up(slug, run)
        return True

    # ---- trace report (TRC-02)
    def trace_report(self, slug):
        """{"gaps": [...], "failures": [...]}: missing links apart from cycles that failed (no item is in both)."""
        run = self._get_v2(slug)
        links = self.reg.rows("trace_links", run_id=run["id"])
        tested = {r["from_id"] for r in links if r["from_kind"] == "scenario" and r["to_kind"] in ("test", "qa_script")}
        with_evidence = {r["from_id"] for r in links if r["from_kind"] == "cycle" and r["to_kind"] == "evidence"}
        gaps, failures = [], []
        for c in self.live_cycles(run):
            if c["state"] == "REJECTED":
                why = c["reason"] or "rejected"
                failures.append({"kind": "cycle", "id": c["id"], "reason": "rejected: " + why[:1].upper() + why[1:]})
                continue
            gaps += [{"kind": "scenario", "id": k, "gap": "no qa script" if c["red_method"] == Q.QA else "no test"}
                     for k in self._scenario_keys(c) if k not in tested]
            if c["state"] != "CYCLE_ACCEPTED" or c["id"] not in with_evidence:
                gaps.append({"kind": "cycle", "id": c["id"], "gap": "no evidence"})
        return {"gaps": gaps, "failures": failures}

    def _changed_test_files(self, run, task, cycle):
        """[(repo-relative path, sha256 now)] of the test files the Red attempts of this cycle changed and left in
        place. A retry sees the files an earlier attempt wrote: they are still in the working tree."""
        cfg = self._run_config(run)
        base = self._repo_path(cfg, cycle["repo_id"])
        attempts = [t["id"] for t in self.reg.rows("tasks", run_id=run["id"], cycle_id=cycle["id"], role="tdd_red")]
        found = {}
        for tid in attempts:
            for rec in self.reg.rows("changed_files", task_id=tid):
                if rec["repo_id"] == cycle["repo_id"] and scopes.classify(cfg, cycle["repo_id"], rec["path"]) == "test":
                    try:
                        found[rec["path"]] = hashlib.sha256((base / rec["path"]).read_bytes()).hexdigest()
                    except OSError:
                        found.pop(rec["path"], None)  # deleted again
        return sorted(found.items())

    @staticmethod
    def _scenario_keys(cycle):
        return [s["key"] for s in scenario_rows(cycle)]

    def _verify_red(self, run, task, cycle):
        if cycle["red_method"] == Q.QA:
            return self._verify_qa(run, task, cycle, "red")
        cfg = self._run_config(run)
        repo = cycle["repo_id"]
        tools = scopes.test_tools(cfg, repo)
        keys = self._scenario_keys(cycle)
        files = self._changed_test_files(run, task, cycle)
        if not files:
            self._flag(run, task, text="no test file changed")
            return self._finish_red(run, task, cycle, None, "rejected", "no test file changed", None, [], files)
        refs, base, info = [], self._repo_path(cfg, repo), {}
        for rel, _ in files:
            try:
                text = (base / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            refs += binding.references(text, tools["scenario_ref"], rel)
            info.update(binding.test_info(text, tools["scenario_ref"], rel))
        live = self.live_cycles(run)
        other = {k for c in live if c["id"] != cycle["id"] for k in self._scenario_keys(c)}
        shared = {k for c in live if c["id"] != cycle["id"] and json_list(c["approved_tests"]) for k in self._scenario_keys(c)}
        problem, pairs = binding.bind(refs, set(keys), other, shared)
        if problem:
            return self._finish_red(run, task, cycle, None, "rejected", problem, None, [], files)
        tests = list(dict.fromkeys(t for _, t in pairs))
        base_row = self.baseline(run, repo)
        failing_base = json_list(base_row["failing"]) if base_row else []
        related = [t for t in self.accepted_tests(run, cycle) if t not in tests]
        try:
            ran = self._run_tests(cfg, repo, tools["targeted_test"], tools, tests + related, self.test_info(run, cycle, info))
        except ValueError as err:
            return self._finish_red(run, task, cycle, None, "rejected", f"a test name cannot be selected: {err}", None, [], files)
        cl = classifier.classify(ran["exit_code"], ran["output"], ran["report"], tools["failure_patterns"],
                                 new_tests=tests, baseline_failing=failing_base, related_tests=related,
                                 summary_patterns=tools.get("summary_patterns"))
        verdict, reason = classifier.verify_red(cl, tests)
        if verdict == "rejected" and cl["classification"] in classifier.RETRY_CLASSES:
            line = classifier.output_line(cl["classification"], ran["output"], tools["failure_patterns"])
            reason = f"{cl['classification'].replace('_', ' ')}: {line}" if line else reason
        return self._finish_red(run, task, cycle, ran, verdict, reason, cl, pairs, files, tools, info)

    def _finish_red(self, run, task, cycle, ran, verdict, reason, cl, pairs, files, tools=None, info=None):
        tests = list(dict.fromkeys(t for _, t in pairs))
        counts = (len(cl["new_passing"]), len(cl["new_failing"]), 0) if cl else None
        failing = list(cl["new_failing"]) if cl else []
        klass = cl["classification"] if cl else None
        with self.reg.transaction():
            run = self.reg.get_run_by_id(run["id"])
            cycle = self._cycle(cycle["id"])
            if cycle["state"] != "RED_RUNNING" or run["state"] != "EXECUTING":
                return None
            eid = self._store_evidence(run, "red", cycle["repo_id"], task=task, cycle=cycle, ran=ran, cl=cl, verdict=verdict,
                                       reason=reason, failing=failing, counts=counts)
            result = {"verdict": verdict, "reason": reason, "classification": klass, "cycle": cycle["id"], "evidence": eid,
                      "retry": None}
            if verdict == "accepted":
                self._accept_red(run, task, cycle, pairs, files, tests, info or {})
            elif verdict == "needs_human":
                line = classifier.output_line("unknown", ran["output"], {}) if ran else ""
                self._park_run(run, f"cycle {cycle['behavior']}: red run could not be classified: {self._clean(line)}")
            else:
                lines = [classifier.output_line(klass, ran["output"], tools["failure_patterns"])] if ran and klass in classifier.RETRY_CLASSES else []
                result["retry"] = self._reject_phase(run, task, cycle, "red", reason, klass, lines)
        self._finish_up(run["slug"], run)
        return result

    def _clean(self, text):
        return self._scrubber().scrub_text(str(text))[:LINE_CAP]

    def _accept_red(self, run, task, cycle, pairs, files, tests, info):
        repo = cycle["repo_id"]
        approved = [{"path": f"{repo}/{rel}", "sha256": sha} for rel, sha in files]
        for other in self.cycle_rows(run):  # tests often share a file: its new bytes are legitimate for every owner
            if other["id"] != cycle["id"] and other["repo_id"] == repo:
                items = json_list(other["approved_tests"])
                fresh = {a["path"]: a["sha256"] for a in approved}
                if any(i["path"] in fresh for i in items):
                    self.reg.update_row("cycles", other["id"], approved_tests=json.dumps(
                        [{"path": i["path"], "sha256": fresh.get(i["path"], i["sha256"])} for i in items]))
        for key in self._scenario_keys(cycle):
            self.reg.remove_trace_links(run["id"], from_kind="scenario", from_id=key, to_kind="test")
        self.reg.remove_trace_links(run["id"], from_kind="cycle", from_id=cycle["id"], to_kind="test_file")
        for key, test in pairs:
            self.reg.add_trace_link(run["id"], "scenario", key, "test", test)
        for item in approved:
            self.reg.add_trace_link(run["id"], "cycle", cycle["id"], "test_file", item["path"])
        moved = self._move_cycle(run, cycle, "RED_VERIFIED", classification="assertion", approved_tests=json.dumps(approved),
                                 tests=json.dumps(tests), red_task=task["id"],
                                 test_info=json.dumps({t: info[t] for t in tests if t in info}))
        self._phase_task(run, moved, "green")

    # ---- rejection, retry and cap
    def _phase_brief(self, run, task, cycle, phase, reason, klass, lines, attempt, cap):
        out = [f"This is attempt {attempt + 1} of {cap + 1} of the {phase} phase of {cycle['behavior']}.",
               f"The previous attempt {task['id']} was rejected by the engine.", f"Classification: {klass or 'none'}",
               f"Reason: {self._clean(reason)}"]
        shown = [self._clean(line) for line in lines if line]
        if shown:
            out += ["", "Output of the engine's test run (secrets removed):"] + [f"    {line}" for line in shown]
        try:
            earlier = (self.task_dir(run["slug"], task["id"]) / "brief.md").read_text(encoding="utf-8").strip()
        except OSError:
            earlier = ""
        if earlier:
            out += ["", "Earlier failures and feedback:", earlier]
        return "\n".join(out) + "\n"

    def _reject_phase(self, run, task, cycle, phase, reason, klass, lines):
        """Inside a transaction: a retry task, or at the cap REJECTED and NEEDS_HUMAN. Returns the retry task id."""
        cfg = self._run_config(run)
        role = role_for(cycle, phase)
        cap = task["max_retries"] if _int(task["max_retries"]) else retry_cap(cfg, role)
        attempt = task["attempt"] or 1
        if attempt > cap:
            self._cap_reached(run, cycle, phase, reason)
            return None
        if phase == "red":
            cycle = self._move_cycle(run, cycle, "PLANNED", reason=reason, classification=klass)
        else:
            self.reg.update_row("cycles", cycle["id"], reason=reason)
        brief = self._phase_brief(run, task, cycle, phase, reason, klass, lines, attempt, cap)
        return self._phase_task(run, cycle, phase, retry_of=task["id"], brief=brief, attempt=attempt + 1)["id"]

    def _cap_reached(self, run, cycle, phase, last):
        cycle = self._cycle(cycle["id"])
        if cycle["state"] in OPEN_CYCLE:
            self._move_cycle(run, cycle, "REJECTED", reason=f"{phase} cap reached")
        if run["state"] not in machines.RUN_FINAL and run["state"] != "NEEDS_HUMAN":
            self._move(run, "NEEDS_HUMAN", machines.ENGINE,
                       reason=f"cycle {cycle['behavior']}: {phase} cap reached; last rejection: {self._clean(last)}")

    def _after_retry_created(self, run, task, retry):
        """Inside finish_task's transaction: a failed (not rejected) TDD task got its retry; Red goes back to PLANNED."""
        if task["role"] not in TDD_ROLES or not task["cycle_id"]:
            return
        phase = PHASE[task["role"]]
        cyc = self._cycle(task["cycle_id"])
        if phase == "red" and cyc["state"] == "RED_RUNNING":
            cyc = self._move_cycle(run, cyc, "PLANNED", reason=f"{task['error_code']}: {self._clean(task['reason'])}")
        self.reg.update_row("cycles", cyc["id"], **{f"{phase}_task": retry["id"]})

    # ---- retry and cancel hooks (called by Phase F's ControlOps and by R20)
    def _unreverted(self, run, task):
        """Paths a failed E_SCOPE task changed against its rules that still differ from its start snapshot: a retry would
        start on top of them, so a human reverts them first."""
        if task["error_code"] != "E_SCOPE":
            return []
        try:
            before = json.loads(task["before_snapshot"])
        except (TypeError, ValueError):
            return []
        cfg = self._run_config(run)
        asked = {}
        for ev in self.reg.list_events(run["id"], "task.scope_violation"):
            if ev["task_id"] == task["id"]:
                for text in ev["payload"].get("paths") or []:
                    asked.setdefault(ev["payload"].get("kind"), []).append(text)
        left = []
        for repo in cfg.get("repos") or []:
            rid = repo.get("id") if isinstance(repo, dict) else None
            path = self.workspace / repo.get("path", rid) if rid else None
            if not rid or not path.is_dir() or rid not in (before.get("repos") or {}):
                continue
            now = boundary.changed_state(path, self._watch_globs(cfg, rid))
            was = before["repos"][rid]
            if now["head"] != was["head"]:
                left.append(f"{rid}: HEAD moved")
            differ = {f"{rid}/{n}" for n in boundary.changed_between(was, now)}
            left += [t for texts in asked.values() for t in texts if t in differ and t not in left]
        now_cfg = self._config_digests()
        left += [t for t in asked.get("config_changed", []) if now_cfg.get(t) != (before.get("config") or {}).get(t)]
        return left

    def retry_cycle_task(self, task_id, actor):
        """A new task for the phase of a failed (E_SCOPE, E_INTEGRITY) or cancelled cycle task: what R20 does for a cycle
        that is still running, and what a human asks for after cancelling a cycle task. Refused (E_PRECONDITION) unless
        the cycle is in that phase's before or running state, the task is the cycle's latest, the cap allows another
        attempt, and the paths of an earlier scope violation are reverted. Returns the new task row."""
        if actor not in (machines.HUMAN, machines.ENGINE):
            raise SentinelError("E_ACTOR", f"{actor} may not retry a cycle task", {"actor": actor})
        task = self._task_row(task_id)
        run0 = self.reg.get_run_by_id(task["run_id"])
        with self.reg.transaction():
            run = self.reg.get_run_by_id(task["run_id"])
            retry = self._retry_cycle_task_in_tx(run, self._task_row(task_id), actor)
        self._finish_up(run0["slug"], run0)
        return self._task_row(retry)

    def _retry_cycle_task_in_tx(self, run, task, actor):
        refuse = lambda msg, **d: SentinelError("E_PRECONDITION", msg, {"task": task["id"], **d})  # noqa: E731
        if task["role"] not in TDD_ROLES or not task["cycle_id"]:
            raise refuse(f"task {task['id']} is not a cycle task")
        if task["state"] not in ("FAILED", "CANCELLED"):
            raise refuse(f"task {task['id']} is {task['state']}; only a failed or cancelled cycle task is retried")
        if run["state"] in machines.RUN_FINAL:
            raise refuse(f"run is {run['state']}")
        phase = PHASE[task["role"]]
        cycle = self._cycle(task["cycle_id"])
        if cycle["state"] not in STATES[phase]:
            raise refuse(f"cycle {cycle['behavior']} is {cycle['state']}, not in the {phase} phase", cycle=cycle["id"])
        if cycle[f"{phase}_task"] != task["id"] or any(
                t["state"] in OPEN_STATES for t in self.reg.rows("tasks", run_id=run["id"], cycle_id=cycle["id"], role=task["role"])):
            raise refuse(f"task {task['id']} is not the latest {phase} task of the cycle")
        cap = task["max_retries"] if _int(task["max_retries"]) else retry_cap(self._run_config(run), task["role"])
        attempt = task["attempt"] or 1
        if attempt > cap:
            raise refuse(f"the {phase} retry cap ({cap}) is used", cap=cap)
        left = self._unreverted(run, task)
        if left:
            raise refuse("revert these paths of the earlier scope violation first: " + ", ".join(left), paths=left)
        v = {"code": task["error_code"] or "E_CANCELLED", "message": task["reason"] or "cancelled", "details": {}}
        retry = self._make_retry(run, task, v, attempt)
        self._after_retry_created(run, task, retry)
        self.reg.add_audit(actor, "engine", "cycle_task_retried", f"{run['slug']}/{task['id']}", reason=f"retry {retry['id']}")
        return retry["id"]

    def _retry_stalled_cycles(self, run):
        """Inside a transaction, on R20: a cycle still in its running state whose newest phase task failed (a scope violation
        parks the run and leaves it so) gets a retry task. A refusal parks the run again with the reason."""
        for c in self.live_cycles(run):
            for phase, (_, running) in STATES.items():
                tid = c[f"{phase}_task"]
                task = self.reg.get_row("tasks", tid) if tid else None
                if c["state"] == running and task and task["state"] == "FAILED":
                    try:
                        self._retry_cycle_task_in_tx(run, task, machines.ENGINE)
                    except SentinelError as err:
                        self._park_run(self.reg.get_run_by_id(run["id"]), f"cycle {c['behavior']}: {err.message}")
                        return

    def on_cycle_task_cancelled(self, run, task):
        """Inside the cancel's transaction: cancelling the running task of a cycle moves the cycle back to the state before
        that phase (Red: PLANNED, Green: RED_VERIFIED, Refactor: GREEN_VERIFIED). A new task is `retry_cycle_task`."""
        if task["role"] not in TDD_ROLES or not task["cycle_id"]:
            return
        phase = PHASE[task["role"]]
        before, running = STATES[phase]
        cyc = self.reg.get_row("cycles", task["cycle_id"])
        if cyc and cyc["state"] == running and cyc[f"{phase}_task"] == task["id"]:
            self._move_cycle(run, cyc, before, reason=f"{task['role']} task cancelled")

    def _park_run_tx(self, run, reason):
        with self.reg.transaction():
            self._park_run(self.reg.get_run_by_id(run["id"]), reason)
        self._finish_up(run["slug"], run)

    def _park_run(self, run, reason):
        if run["state"] not in machines.RUN_FINAL and run["state"] != "NEEDS_HUMAN":
            self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=reason)

    # ---- prompts
    def tdd_prompt_context(self, run, sealed):
        """Placeholders of the TDD stage templates that depend on the task's cycle."""
        cyc_id = (sealed.get("input") or {}).get("cycle_id")
        cycle = self.reg.get_row("cycles", cyc_id) if cyc_id else None
        if not cycle:
            if not sealed["role"].startswith("tdd_"):
                return {}
            perm = sealed["permissions"]  # a verification fix task belongs to no cycle
            bullets = lambda items: "\n".join(f"- `{i}`" for i in items) or "(none)"  # noqa: E731
            return {"cycle_behavior": "verification fix", "scenario_keys": "(none)", "scenario_texts": "(none)",
                    "write_scope": ", ".join(perm["write"]) or "none", "readonly_files": bullets(perm.get("readonly_approved") or []),
                    "failing_tests": "(see the brief below)", "related_tests": "(none)", "task_objective": sealed["objective"]}
        texts = {s["key"]: s["text"] for g in self._gherkin_groups(run) for s in g["scenarios"]}
        keys = self._scenario_keys(cycle)
        scenarios = "\n\n".join(f"### {k}\n\n```gherkin\n{texts.get(k, '')}\n```" for k in keys)
        perm = sealed["permissions"]
        red = [e for e in self.reg.rows("evidence", cycle_id=cycle["id"], kind="red") if e["verdict"] == "accepted"]
        related = self.related_tests(run, cycle)
        bullets = lambda items: "\n".join(f"- `{i}`" for i in items) or "(none)"  # noqa: E731
        qa_scripts = "(none)"
        if cycle["red_method"] == Q.QA:
            folder = self._scripts_rel(run, cycle["id"])
            qa_scripts = "\n".join(f"- `{Q.scenario_id(k, texts.get(k, ''))}` -> `{folder}/{Q.scenario_id(k, texts.get(k, ''))}.spec`"
                                  for k in keys)
        return {"qa_scripts": qa_scripts, "cycle_behavior": cycle["behavior"], "scenario_keys": bullets(keys), "scenario_texts": scenarios,
                "write_scope": ", ".join(perm["write"]) or "none", "readonly_files": bullets(perm.get("readonly_approved") or []),
                "failing_tests": bullets(json_list(red[-1]["failing"]) if red else []), "related_tests": bullets(related),
                "task_objective": sealed["objective"]}
