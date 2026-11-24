"""QA scenarios as Red evidence (TDD-09), the engine side: R12 driver check, qa_red scope, the driver run of a phase, its evidence.

QaCycleOps is mixed into Engine next to CycleOps (cycles.py), whose helpers it uses. Pure helpers are in qa_scenarios.py.
Integrity: the scripts of every live QA cycle of a repo and the runner files named in qa.scenario_run are hashed when Red is
accepted and checked again at dispatch, at Green and Refactor verification, at acceptance and in the report.

Source: plan/v1.1/phaseJ/README.md.
"""
import hashlib
import json

import boundary
import machines
import qa_scenarios as Q
from cycles import PHASE, STATES, TEST_TIMEOUT, json_list, scenario_rows
from errors import SentinelError
from registry import _now
from tasks import _int

NO_RESULT = {"results": [], "failing": [], "passing": [], "missing": [], "extra": [], "skipped": [], "line": ""}


class QaCycleOps:
    # ---- paths and scope
    def _state_rel(self):
        """The state folder relative to the workspace (a nested `state.dir` keeps its parents)."""
        try:
            return self.state_dir.resolve().relative_to(self.workspace.resolve()).as_posix()
        except ValueError:
            return self.state_dir.name

    def _scripts_rel(self, run, cycle_id=None):
        return Q.scripts_rel(self._state_rel(), run["slug"], cycle_id)

    def _qa_driver_problem(self, run):
        """R12: a QA-Red cycle needs a usable QA driver; there is no silent fall back to test files (TDD-09)."""
        cfg = self._run_config(run)
        assigned, _ = self._assignments(run)
        for _, repo in assigned:
            if Q.method_for(cfg, repo) == Q.QA:
                why = Q.driver_problem(cfg, self.workspace, repo)
                if why:
                    return ("E_PRECONDITION", f"repo {repo} cannot use QA scenarios as Red evidence: {why}; configure the QA driver "
                            f"(qa.driver, qa.scenario_run, qa.scenario_report, qa.start_commands) and run `sentinel resolve "
                            f"{run['slug']} --refresh-config`, or turn rules.{Q.RULE} off", "tdd_exception_refused")
        return None

    def qa_cycles(self, run, repo_id):
        """Live QA cycles of a repo whose Red was accepted (their scripts are approved files for every later task)."""
        return [c for c in self.live_cycles(run) if c["repo_id"] == repo_id and c["red_method"] == Q.QA and c["state"] != "REJECTED"
                and c.get("approved_scripts")]

    def approved_script_paths(self, run, repo_id):
        """Workspace-relative approved QA scripts of a repo's live cycles and their folders (read-only for Green and Refactor)."""
        out = []
        for c in self.qa_cycles(run, repo_id):
            out += [i["path"] for i in json_list(c["approved_scripts"])]
            out.append(self._scripts_rel(run, c["id"]) + "/")
        return out

    def qa_runner_paths(self, run):
        """Workspace-relative runner files (named in qa.scenario_run) hashed at Red: test infrastructure for Green and Refactor."""
        out = set()
        for c in self.live_cycles(run):
            if c["red_method"] == Q.QA:
                out.update(i["path"] for i in json_list(c.get("approved_runner")))
        return out

    def _qa_red_scope(self, run, write):
        """Write scope of a qa_red task: the QA script folder of the run only; the repo is read-only. Anything wider is E_SCOPE."""
        allowed = [self._scripts_rel(run) + "/**"]
        if write is None:
            return allowed
        for glob in write:
            if glob not in allowed:
                raise SentinelError("E_SCOPE", f"qa_red task may not write {glob}", {"role": "qa_red", "glob": glob})
        return write

    def _qa_tree_state(self, slug):
        """{path under the slug's QA script folder: sha256 or "symlink"}: the start snapshot of a task (lstat, no following)."""
        return Q.tree_state(self.workspace, Q.scripts_rel(self._state_rel(), slug))

    def _qa_tree_violations(self, run, task, was, now):
        """[(kind, path)] for what a task changed in the QA script tree. A qa_red task may write only its own cycle's folder; a file
        of an accepted cycle is approved_test_changed. Green and Refactor write nothing there: a change in an accepted cycle's
        folder is left to their verification (E_INTEGRITY, AC-TDD-09w), a change elsewhere is outside_write_scope."""
        base = self._scripts_rel(run)
        approved = {c["id"] for c in self.live_cycles(run) if c["red_method"] == Q.QA and c.get("approved_scripts")}
        out = []
        for n in sorted(k for k in set(was) | set(now) if was.get(k) != now.get(k)):
            top = n.split("/", 1)[0]
            full = f"{base}/{n}"
            if top in approved:
                if task["role"] == "qa_red":
                    out.append(("approved_test_changed", full))
            elif task["role"] != "qa_red" or top != task["cycle_id"]:
                out.append(("outside_write_scope", full))
        return out

    def _refuse_tdd_red_for_qa(self, role, cycle_id):
        cyc = self.reg.get_row("cycles", cycle_id) if isinstance(cycle_id, str) else None
        if role == "tdd_red" and cyc and cyc["red_method"] == Q.QA:
            raise SentinelError("E_PRECONDITION", "this cycle uses QA scenarios as Red evidence (qa_red); a tdd_red task is refused",
                                {"cycle": cycle_id, "red_method": Q.QA})

    # ---- integrity
    def _runner_now(self, cfg, repo_id):
        out = []
        for path in Q.runner_files(cfg, self.workspace, repo_id):
            try:
                sha = hashlib.sha256((self.workspace / path).read_bytes()).hexdigest()
            except OSError:
                continue
            out.append({"path": path, "sha256": sha})
        return out

    def qa_changed(self, run, repo_id):
        """Workspace-relative scripts and runner files of the repo's accepted QA cycles whose bytes differ from what Red approved,
        files added to a script folder since, and symlinks (E_INTEGRITY material)."""
        out = []
        for c in self.qa_cycles(run, repo_id):
            for path in Q.changed_scripts(self.workspace, json_list(c["approved_scripts"]), self._scripts_rel(run, c["id"])) + \
                    Q.changed_scripts(self.workspace, json_list(c.get("approved_runner"))):
                if path not in out:
                    out.append(path)
        return out

    def _qa_integrity_outcome(self, run, task, changed):
        msg = self._integrity_stop(run, task["id"], changed, "QA script or runner file")
        return {"verdict": "needs_human", "reason": msg, "classification": None, "cycle": task["cycle_id"], "evidence": None, "retry": None}

    # ---- verification
    # ---- QA scenarios as Red evidence (TDD-09)
    def _qa_gaps(self, cycle, phase, e):
        gaps = []
        if not e["method"]:
            gaps.append(f"{phase} method")
        if not json_list(e["scripts"]):
            gaps.append(f"{phase} scripts")
        if not e["exception"]:
            gaps.append(f"{phase} exception")
        if phase == "red" and not any(ev["payload"].get("cycle") == cycle["id"]
                                      for ev in self.reg.list_events(cycle["run_id"], "tdd.exception_recorded")):
            gaps.append("red exception event")
        if phase == "green" and len([r for r in json_list(e["scenarios"]) if r.get("status") == "pass"]) < len(scenario_rows(cycle)):
            gaps.append("green scenarios")
        return gaps

    def _qa_ids(self, run, cycle):
        texts = {s["key"]: s["text"] for g in self._gherkin_groups(run) for s in g["scenarios"]}
        return [(Q.scenario_id(r["key"], texts.get(r["key"], "")), r["key"]) for r in scenario_rows(cycle)]

    def _qa_steps(self, run, cycle):
        """{scenario id: steps} of the cycle, so a failure at an And or But step gets the keyword it inherits."""
        texts = {s["key"]: s["text"] for g in self._gherkin_groups(run) for s in g["scenarios"]}
        return {Q.scenario_id(r["key"], texts.get(r["key"], "")): Q.steps_of(texts.get(r["key"], "")) for r in scenario_rows(cycle)}

    def _qa_execute(self, cfg, run, cycle, ids, phase, steps=None):
        """The driver run of a phase: [(ran, judged)] and the final class. An environment class is rerun once; a Red that
        failed as wanted is run once more to catch a flaky scenario."""
        repo = cycle["repo_id"]
        path = self._repo_path(cfg, repo)
        folder = self.workspace / self._scripts_rel(run, cycle["id"])
        timeout = (cfg.get("policies") or {}).get("test_timeout_seconds")
        timeout = timeout if _int(timeout) and timeout > 0 else TEST_TIMEOUT

        def once():
            ran = Q.run_driver(cfg, path, repo, folder, cycle["id"], self.state_dir / "cache" / "qa", timeout, _now)
            ran["repo_sha"] = boundary.git(path, "rev-parse", "HEAD").strip()
            return ran, Q.judge(ran, ids, steps)
        runs = [once()]
        first = runs[0][1]["class"]
        final = first
        if first in Q.ENV_CLASSES:
            runs.append(once())
            final = runs[1][1]["class"]
        elif phase == "red" and first == "assertion":
            runs.append(once())
            final = "flaky" if runs[1][1]["passing"] else runs[1][1]["class"]
        return runs, final

    def _qa_reason(self, phase, final, j, last_line):
        ids = lambda xs: ", ".join(xs)  # noqa: E731
        if final == "partial_pass":
            final = "unexpected_pass" if phase == "red" else "assertion"
        if final == "pass" and phase == "red":
            final = "unexpected_pass"
        lines = []
        if final == "unexpected_pass":
            reason = "red passed unexpectedly" + (f": {ids(j['passing'])}" if j["failing"] else "")
            lines.append(f"These scenarios passed before any production change: {ids(j['passing'])}")
        elif final == "flaky":
            reason = f"flaky: scenario {ids(j['passing'])} passed on the engine's rerun"
        elif final == "setup_failure":
            reason = "setup failure: " + (last_line or "a Given or When step failed")
        elif final == "script_error":
            reason = "script error: " + (last_line or "the script could not run")
        elif final == "unbound_scenario":
            parts = []
            if j["missing"]:
                parts.append("scenario without result: " + ids(j["missing"]))
            if j["extra"]:
                parts.append("result for unknown scenario: " + ids(j["extra"]))
            if j["skipped"]:
                parts.append("scenario skipped: " + ids(j["skipped"]))
            reason = "; ".join(parts)
        elif final == "assertion":
            reason = "scenarios still fail: " + ids(j["failing"])
        else:
            reason = final
        if last_line and final in ("setup_failure", "script_error", "assertion"):
            lines.append(last_line)
        return final, reason, lines

    def _qa_busy(self, run, cycle, err):
        """The QA driver could not run (busy past the wait, or a bad report path): the run waits for a human, with the reason."""
        why = f"cycle {cycle['behavior']}: the QA driver could not run ({err.code}: {err.message}); resume when it is free"
        self._park_run_tx(run, why)
        return {"verdict": "needs_human", "reason": why, "classification": None, "cycle": cycle["id"], "evidence": None, "retry": None}

    def _verify_qa(self, run, task, cycle, phase):
        cfg = self._run_config(run)
        repo = cycle["repo_id"]
        pairs = self._qa_ids(run, cycle)
        ids = [i for i, _ in pairs]
        steps = self._qa_steps(run, cycle)
        folder_rel = self._scripts_rel(run, cycle["id"])
        runner = None
        if phase == "red":
            others = self.qa_changed(run, repo)  # an earlier accepted cycle must be as Red approved it
            if others:
                return self._qa_integrity_outcome(run, task, others)
            try:
                scripts = Q.manifest(self.workspace, folder_rel)
            except SentinelError as err:
                if err.code != "E_INTEGRITY":
                    raise
                msg = self._integrity_stop(run, task["id"], [err.details.get("path", folder_rel)], "QA script", err.message)
                return {"verdict": "needs_human", "reason": msg, "classification": None, "cycle": cycle["id"], "evidence": None, "retry": None}
            if not [x for x in scripts if x["scenario"] in ids]:
                return self._finish_qa(run, task, cycle, phase, [], "unbound_scenario", dict(NO_RESULT, missing=ids), scripts,
                                       "no QA script written for: " + ", ".join(ids), [], None)
            runner = self._runner_now(cfg, repo)
        else:
            scripts = json_list(cycle["approved_scripts"])
            changed = self.qa_changed(run, repo)  # this cycle, every other live QA cycle of the repo, the runner files
            if changed:
                return self._qa_integrity_outcome(run, task, changed)
        try:
            runs, final = self._qa_execute(cfg, run, cycle, ids, phase, steps)
        except SentinelError as err:
            if err.code not in ("E_LOCKED", "E_VALIDATION"):
                raise
            return self._qa_busy(run, cycle, err)
        j = runs[-1][1]
        forced = None
        if phase == "red":
            moved = Q.changed_scripts(self.workspace, scripts, folder_rel) + Q.changed_scripts(self.workspace, runner or [])
            if moved:
                return self._qa_integrity_outcome(run, task, moved)
        elif final == "pass":
            final, j, forced = self._qa_peers(cfg, run, cycle, runs)
        return self._finish_qa(run, task, cycle, phase, runs, final, j, scripts, forced, [] if forced else None, runner)

    def _qa_peers(self, cfg, run, cycle, runs):
        """Green and Refactor: the accepted QA cycles of the repo run through the driver too ("rest unchanged"). Appends their
        runs to `runs`; returns (class, judged, forced reason): the first failure decides, else the own pass."""
        own = runs[-1][1]
        for peer in self.live_cycles(run):
            if peer["id"] == cycle["id"] or peer["repo_id"] != cycle["repo_id"] or peer["red_method"] != Q.QA \
                    or peer["state"] != "CYCLE_ACCEPTED":
                continue
            ids = [i for i, _ in self._qa_ids(run, peer)]
            try:
                more, final = self._qa_execute(cfg, run, peer, ids, "green", self._qa_steps(run, peer))
            except SentinelError as err:
                if err.code not in ("E_LOCKED", "E_VALIDATION"):
                    raise
                more, final = [({"command": "", "exit_code": None, "output": err.message + "\n", "started_at": _now(), "finished_at": _now(),
                                 "repo_sha": "", "artifacts": [], "app_started": False}, dict(NO_RESULT, **{"class": "driver_error", "line": err.message}))], \
                    "driver_error"
            runs.extend(more)
            if final != "pass":
                j = more[-1][1]
                if final in Q.HUMAN_CLASSES:
                    return final, j, None
                bad = ", ".join(j["failing"] + j["missing"]) or final
                return "assertion", j, f"regression: scenarios of the earlier cycle {peer['behavior']} fail: {bad}"
        return "pass", own, None

    def _finish_qa(self, run, task, cycle, phase, runs, final, j, scripts, forced, forced_lines, runner):
        repo = cycle["repo_id"]
        if forced is None:
            last_line = self._clean(j["line"])
            klass, reason, lines = self._qa_reason(phase, final, j, last_line)
        else:
            klass, reason, lines = final, forced, forced_lines
        if klass in Q.HUMAN_CLASSES:
            verdict = "needs_human"
        elif klass == "assertion" and phase == "red" or klass == "pass" and phase != "red":
            verdict = "accepted"
        else:
            verdict = "rejected"
        if verdict == "needs_human":
            label = {"driver_error": "QA driver error", "app_not_running": "QA app not running",
                     "unknown": "QA run could not be classified"}[klass]
            reason = f"{label}: {self._clean(j['line'])}"
        ran = None
        if runs:
            combined = "".join(f"== run {n} ==\n{r['output']}\n" for n, (r, _) in enumerate(runs, 1))
            first, last = runs[0][0], runs[-1][0]
            ran = {"command": last["command"], "exit_code": last["exit_code"], "output": combined, "started_at": first["started_at"],
                   "finished_at": last["finished_at"], "cwd": repo, "repo_sha": last["repo_sha"]}
            self._flag(run, task, command=last["command"])  # a command the agent claimed is not evidence (VER-02)
        results = [{**r, "message": self._clean(r["message"]), "step": self._clean(r["step"])} for r in j.get("results", [])]
        extra = {"exception": json.dumps(Q.exception_doc(repo)), "scripts": json.dumps(scripts), "scenarios": json.dumps(results),
                 "runs": json.dumps([{"class": jj["class"], "exit_code": r["exit_code"], "started_at": r["started_at"],
                                      "finished_at": r["finished_at"], "artifacts": r["artifacts"],
                                      "app_started": r.get("app_started", False)} for r, jj in runs or []])}
        counts = (len(j.get("passing", [])), len(j.get("failing", [])), len(j.get("skipped", [])))
        failing = list(j.get("failing", []))
        ids = [i for i, _ in self._qa_ids(run, cycle)]
        cl = {"classification": klass, "failing": failing}
        running = STATES[phase][1]
        with self.reg.transaction():
            run = self.reg.get_run_by_id(run["id"])
            cycle = self._cycle(cycle["id"])
            if cycle["state"] != running or run["state"] != "EXECUTING":
                return None
            eid = self._store_evidence(run, phase, repo, task=task, cycle=cycle, ran=ran, cl=cl, verdict=verdict, reason=reason,
                                       failing=failing, counts=counts, tests=ids, extra=extra)
            result = {"verdict": verdict, "reason": reason, "classification": klass, "cycle": cycle["id"], "evidence": eid, "retry": None}
            if verdict == "accepted":
                if phase == "red":
                    self._accept_qa_red(run, task, cycle, scripts, eid, runner)
                else:
                    self._accept_phase(run, task, cycle, phase)
            elif verdict == "needs_human":
                self._park_run(run, f"cycle {cycle['behavior']}: {reason}")
            else:
                self._event(run, f"{phase}.rejected", machines.ENGINE, {"cycle": cycle["id"], "evidence": eid, "reason": reason, "failing": failing})
                result["retry"] = self._reject_phase(run, task, cycle, phase, reason, klass, lines)
        self._finish_up(run["slug"], run)
        if verdict == "accepted" and phase == "refactor":
            self.check_r13(run["slug"])
        return result

    def _accept_qa_red(self, run, task, cycle, scripts, eid, runner):
        pairs = self._qa_ids(run, cycle)
        by_id = {x["scenario"]: x["path"] for x in scripts if x["scenario"]}
        for _, key in pairs:
            self.reg.remove_trace_links(run["id"], from_kind="scenario", from_id=key, to_kind="qa_script")
            self.reg.remove_trace_links(run["id"], from_kind="scenario", from_id=key, to_kind="test")
        for sid, key in pairs:
            if sid in by_id:
                self.reg.add_trace_link(run["id"], "scenario", key, "qa_script", by_id[sid])
        moved = self._move_cycle(run, cycle, "RED_VERIFIED", classification="assertion", approved_scripts=json.dumps(scripts),
                                 approved_runner=json.dumps(runner or []), red_task=task["id"])
        self._event(run, "tdd.exception_recorded", machines.ENGINE,
                    {"cycle": cycle["id"], "evidence": eid, "rule": Q.RULE, "repo": cycle["repo_id"], "scenarios": [i for i, _ in pairs]})
        self._phase_task(run, moved, "green")
