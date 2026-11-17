"""Phase J (TDD-09): Green against the same scenarios, evidence, the recorded exception, acceptance (qa_red_green_exception.feature)."""
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import machines  # noqa: E402
from apiserver import views  # noqa: E402
from engine import Engine  # noqa: E402
from errors import SentinelError  # noqa: E402
from pb_helpers import SLUG  # noqa: E402
from pc_helpers import git  # noqa: E402
from pd_helpers import AGENT, feature  # noqa: E402
from pe_helpers import PE  # noqa: E402
from pj_helpers import delete_events, IDS, LISTENER, PJ, ROLES, RULE, features  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = str(ROOT / "sentinel" / "scripts")
EXC = {"rule": RULE, "replaced": "test_file", "by": "qa_scenario", "repo": "frontend"}


class Green(PJ):
    def rows(self, kind):
        return self.evidence(kind, label=self.FORM)

    def test_AC_TDD_09s_green_makes_the_failing_scenarios_pass_and_the_cycle_is_accepted(self):
        self.to_qa_red_verified()
        self.plan(default={"*": "pass"})
        self.run_qa("tdd_green")
        self.run_qa("tdd_refactor")
        self.assertEqual(self.moves(self.FORM), ["PLANNED", "RED_RUNNING", "RED_VERIFIED", "GREEN_RUNNING", "GREEN_VERIFIED",
                                                 "REFACTOR_RUNNING", "REFACTOR_VERIFIED", "CYCLE_ACCEPTED"])
        g = self.rows("green")[-1]
        self.assertEqual((g["kind"], g["method"], g["classification"]), ("green", "qa_scenario", "pass"))
        self.assertEqual(sorted(r["id"] for r in json.loads(g["scenarios"]) if r["status"] == "pass"), sorted(IDS))
        names = [p.name for p in (self.ws / "frontend").rglob("*") if p.is_file() and ".git" not in p.parts]
        self.assertFalse([n for n in names if ".test." in n or ".spec" in n or n.startswith("playwright.config")], names)

    def test_AC_TDD_09t_green_gets_the_approved_scripts_read_only_and_no_test_glob(self):
        self.to_qa_red_verified()
        doc = self.task_json(self.qid("tdd_green"))
        self.assertEqual(doc["permissions"]["write"], ["frontend/src/main/**"])
        ro = doc["permissions"]["readonly_approved"]
        for sid in IDS:
            self.assertIn(self.script_rel(sid), ro)
        self.assertIn(f".sentinel/cache/qa/tests/current/{SLUG}/{self.form()['id']}/", ro)

    def test_AC_TDD_09u_green_is_rejected_for_a_result_that_is_not_a_clean_pass(self):
        rows = [({"default": {"*": "pass", "AC-5": "fail_then"}}, "assertion", "AC-5"),
                ({"default": {"*": "pass", "AC-5": "missing"}}, "unbound_scenario", "AC-5"),
                ({"default": {"*": "skip"}}, "unbound_scenario", "AC-4")]
        for i, (plan, klass, what) in enumerate(rows):
            with self.subTest(klass=klass, what=what):
                if i:
                    self.reset_ws()
                self.to_qa_red_verified()
                self.plan(**plan)
                self.run_qa("tdd_green")
                e = self.rows("green")[-1]
                self.assertEqual((e["verdict"], e["classification"]), ("rejected", klass))
                tasks = self.qa_tasks("tdd_green")
                self.assertEqual(len(tasks), 2)
                self.assertIn(what, (self.tdir(tasks[-1]["id"]) / "brief.md").read_text())

    def test_AC_TDD_09v_a_driver_error_during_green_is_not_an_agent_failure(self):
        self.to_qa_red_verified()
        self.plan(all="app_down")
        self.run_qa("tdd_green")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertIn("app not running", self.last_reason())
        self.assertEqual(self.form()["state"], "GREEN_RUNNING")
        self.assertEqual(len(self.qa_tasks("tdd_green")), 1)

    def test_AC_TDD_09w_a_changed_script_after_qa_red_stops_the_cycle(self):
        for i, change in enumerate(["edited by the Green agent", "deleted", "replaced"]):
            with self.subTest(change):
                if i:
                    self.reset_ws()
                self.to_qa_red_verified()
                self.plan(default={"*": "pass"})
                path = self.ws / self.script_rel("AC-4")
                if change.startswith("edited"):
                    self.agent_exec("tdd_green", f"write({self.script_rel('AC-4')!r}, 'tampered\\n')\nwrite_result()")
                    self.run_qa("tdd_green")
                else:
                    path.unlink() if change == "deleted" else path.write_text("another script\n")
                    out = self.run_qa("tdd_green")
                    self.assertEqual(out["error_code"] if "error_code" in out and out["error_code"] else out.get("error"), "E_INTEGRITY")
                self.assertEqual(self.state(), "NEEDS_HUMAN")
                self.assertTrue([a for a in self.eng.reg.audit_rows() if a["action"] == "integrity_failed"])

    def test_AC_TDD_09x_refactor_runs_the_scripts_again_and_must_keep_them_green(self):
        self.to_qa_red_verified()
        self.plan(default={"*": "pass"})
        self.run_qa("tdd_green")
        self.plan(default={"*": "pass", "AC-4": "fail_then"})
        self.run_qa("tdd_refactor")
        self.assertEqual(self.rows("refactor")[-1]["verdict"], "rejected")
        self.assertEqual(len(self.qa_tasks("tdd_refactor")), 2)


class Evidence(PJ):
    def test_AC_TRC_03a_a_qa_red_cycle_has_the_full_chain_from_scenario_to_evidence(self):
        self.to_qa_accepted()
        links = self.links()
        keys = [s["key"] for s in json.loads(self.form()["scenarios"])]
        for sid, key in zip(IDS, keys):
            mine = [(l["to_kind"], l["to_id"]) for l in links if l["from_kind"] == "scenario" and l["from_id"] == key]
            self.assertIn(("cycle", self.form()["id"]), mine)
            self.assertIn(("qa_script", self.script_rel(sid)), mine)
        ev = {l["to_id"] for l in links if l["from_kind"] == "cycle" and l["from_id"] == self.form()["id"] and l["to_kind"] == "evidence"}
        self.assertEqual(ev, {self.evidence(k, label=self.FORM)[-1]["id"] for k in ("red", "green", "refactor")})
        self.assertEqual([l for l in links if l["to_kind"] == "test_file" and l["from_id"] == self.form()["id"]], [])
        self.assertEqual([l for l in links if l["to_kind"] == "test" and l["from_id"] in keys], [])
        gaps = self.eng.trace_summary(SLUG)["gaps"]
        self.assertFalse([g for g in gaps if "Form shows" in g or "Form rejects" in g], gaps)

    def test_AC_TRC_03b_a_missing_qa_script_link_is_a_trace_gap_not_a_failure(self):
        self.to_qa_accepted()
        key = json.loads(self.form()["scenarios"])[1]["key"]
        self.eng.reg.remove_trace_links(self.run_row()["id"], from_kind="scenario", from_id=key, to_kind="qa_script")
        rep = self.eng.trace_summary(SLUG)
        self.assertIn(f"scenario {key.split(' :: ')[-1]} has no QA script link", rep["gaps"])
        self.assertFalse([f for f in rep["failures"] if "request" in f])

    def test_AC_TDD_09y_the_red_evidence_row_of_a_qa_red_cycle_carries_the_exception(self):
        self.to_qa_accepted()
        for kind in ("red", "green", "refactor"):
            e = self.evidence(kind, label=self.FORM)[-1]
            self.assertEqual(e["method"], "qa_scenario")
            self.assertEqual(json.loads(e["exception"]), EXC)
        ev = self.exc_events("recorded")
        self.assertEqual(len(ev), 1)
        p = ev[0]["payload"]
        self.assertEqual((p["cycle"], p["evidence"], p["rule"], sorted(p["scenarios"])), (
            self.form()["id"], self.evidence("red", label=self.FORM)[-1]["id"], RULE, sorted(IDS)))
        self.assertEqual(ev[0]["actor"], "engine")

    def test_AC_TDD_09z_the_exception_is_recorded_once_per_cycle_not_once_per_retry(self):
        self.boot_qa()
        self.plan(runs={"1": {"*": "pass"}, "2": {"*": "pass"}})
        for _ in range(3):
            self.run_qa()
        self.assertEqual(self.form()["state"], "RED_VERIFIED")
        self.assertEqual(len(self.qa_tasks()), 3)
        ev = self.exc_events("recorded")
        self.assertEqual(len(ev), 1)
        accepted = [e for e in self.evidence("red", label=self.FORM) if e["verdict"] == "accepted"]
        self.assertEqual(ev[0]["payload"]["evidence"], accepted[0]["id"])

    def test_AC_VER_05a_the_cycle_is_not_accepted_with_incomplete_qa_red_evidence(self):
        sql = {"the red row has no method": ("UPDATE evidence SET method=NULL WHERE cycle_id=? AND kind='red'", "E_PRECONDITION", "red method"),
               "no script manifest": ("UPDATE evidence SET scripts=NULL WHERE cycle_id=? AND kind='red'", "E_PRECONDITION", "red scripts"),
               "no exception field": ("UPDATE evidence SET exception=NULL WHERE cycle_id=? AND kind='red'", "E_PRECONDITION", "red exception"),
               "no exception event": ("EVENT", "E_PRECONDITION", "red exception event"),
               "green lists fewer scenarios": ("UPDATE evidence SET scenarios='[]' WHERE cycle_id=? AND kind='green'", "E_PRECONDITION", "green scenarios"),
               "red output edited": (None, "E_INTEGRITY", "red output"),
               "red classification pass": ("UPDATE evidence SET classification='pass' WHERE cycle_id=? AND kind='red'", "E_PRECONDITION", "red classification")}
        for i, (name, (stmt, code, missing)) in enumerate(sql.items()):
            with self.subTest(name):
                if i:
                    self.reset_ws()
                self.to_qa_accepted()
                cid = self.form()["id"]
                self.eng.reg.update_row("cycles", cid, state="REFACTOR_VERIFIED")
                if stmt is None:
                    red = self.evidence("red", label=self.FORM)[-1]
                    art = self.eng.reg.get_row("artifacts", red["output_artifact_id"])
                    with open(self.ws / ".sentinel" / art["path"], "ab") as f:
                        f.write(b"edited\n")
                elif stmt == "EVENT":
                    delete_events(self, "tdd.exception_recorded")
                else:
                    self.sql(stmt, (cid,))
                with self.assertRaises(SentinelError) as cm:
                    self.eng.accept_cycle(cid)
                self.assertEqual(cm.exception.code, code)
                self.assertIn(missing, cm.exception.message)
                self.assertEqual(self.form()["state"], "REFACTOR_VERIFIED")
                self.assertEqual(self.state(), "NEEDS_HUMAN")

    def test_AC_VER_05b_the_accepted_cycle_holds_all_three_rows_and_the_links(self):
        self.to_qa_accepted()
        self.assertEqual(self.form()["state"], "CYCLE_ACCEPTED")
        ev = [e for e in self.cycle_events(self.FORM) if e["payload"]["to"] == "CYCLE_ACCEPTED"]
        self.assertEqual(ev[0]["payload"]["red_method"], "qa_scenario")
        ids = {l["to_id"] for l in self.links("cycle", "evidence") if l["from_id"] == self.form()["id"]}
        self.assertEqual(len(ids), 3)


class Api(PJ):
    def test_AC_TDD_09aa_the_existing_tdd_and_verification_answers_expose_the_method(self):
        self.to_qa_accepted()
        run = self.run_row()
        tdd = views.tdd(self.eng.reg, run)
        cyc = next(c for c in tdd["cycles"] if c["id"] == self.form()["id"])
        self.assertEqual((cyc["red_method"], cyc["exception"]), ("qa_scenario", EXC))
        other = next(c for c in tdd["cycles"] if c["repo"] == "backend")
        self.assertEqual((other["red_method"], other["exception"]), ("test_file", None))
        ver = views.verification(self.eng, run)
        vc = next(c for c in ver["cycles"] if c["id"] == self.form()["id"])
        self.assertEqual((vc["red_method"], vc["exception"]), ("qa_scenario", EXC))
        text = json.dumps([tdd, ver])
        self.assertNotIn("scenario AC-4", text)


class Machines(unittest.TestCase):
    def test_AC_SM_06a_cycle_and_run_state_machines_are_unchanged(self):
        # the run and cycle tables hold the same states and moves as before Phase J: pinned by a hash of their content (no .git needed)
        table = json.dumps([machines.RUN_STATES, machines.CYCLE_STATES, machines.RUN_ROWS, machines.CYCLE_ROWS], default=list, sort_keys=True)
        self.assertEqual(hashlib.sha256(table.encode()).hexdigest(), "7edec110d84657abeafc5cbb8d17a5158d9fb3f17684d00ab756a3539d87029d")
        states = {"PLANNED", "RED_RUNNING", "RED_VERIFIED", "GREEN_RUNNING", "GREEN_VERIFIED", "REFACTOR_RUNNING", "REFACTOR_VERIFIED",
                  "CYCLE_ACCEPTED", "REJECTED"}
        self.assertEqual(set(machines.CYCLE_STATES), states)


class Bug(PJ):
    def test_AC_TST_06a_a_bug_run_reproduces_the_bug_as_a_qa_scenario(self):
        files = {"request_form.feature": features()["request_form.feature"]}
        self.boot_qa(features=files, typ="bug")
        self.prepare()
        task = self.qa_tasks()[0]
        self.assertTrue(self.task_json(task["id"])["objective"].startswith("Reproduce the reported bug"))
        self.plan(default={"*": "fail_given"})
        self.run_qa()
        self.assertEqual(self.evidence("red", label=self.FORM)[-1]["verdict"], "rejected")
        self.plan()
        self.run_qa()
        self.assertEqual(self.evidence("red", label=self.FORM)[-1]["verdict"], "accepted")


class Concurrency(PJ):
    def two_group_features(self):
        files = features()
        files["balance_card.feature"] = feature("@REQ-1 @repo-frontend", [("", "Balance card", [("AC-6", "Card shows days")])], title="Balance card")
        return files

    def test_AC_ORC_09h_two_groups_of_one_client_repo_wait_for_each_other(self):
        self.boot_qa(features=self.two_group_features())
        self.prepare()
        card = self.cycle("Balance card")
        task = self.tdd_tasks("qa_red", "Request form")[0]
        self.assertNotEqual(task["state"], "QUEUED")
        run = self.run_row()
        self.assertEqual(self.eng._cycle_blockers(run, task), [f"cycle {card['id']}"])
        self.assertEqual(self.tdd_tasks("qa_red", "Balance card")[0]["state"], "QUEUED")
        self.assertEqual(card["red_method"], "qa_scenario")

    def verifier(self, tid):
        code = ("import sys, yaml; sys.path.insert(0, %r)\nfrom engine import Engine\nfrom errors import SentinelError\n"
                "ws = %r\ncfg = yaml.safe_load(open(ws + '/sentinel.config.yaml'))\ne = Engine(ws + '/.sentinel', ws, cfg)\n"
                "try:\n    r = e.verify_phase(%r)\n    print('verdict', r and r['verdict'])\nexcept SentinelError as err:\n    print('error', err.code)\n"
                "e.close()\n") % (SCRIPTS_DIR, str(self.ws), tid)
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self._procs.append(p)
        return p

    def complete_without_verifying(self, tid):
        real = self.eng.verify_phase
        self.eng.verify_phase = lambda _t: None
        try:
            self.eng.run_task(tid)
        finally:
            self.eng.verify_phase = real

    def test_AC_ORC_09i_qa_driver_runs_of_different_cycles_never_overlap(self):
        mobile = self.ws / "mobile"
        mobile.mkdir()
        git(mobile, "init", "-q")
        (mobile / "README.md").write_text("x\n")
        (mobile / ".gitignore").write_text("build/\n")
        git(mobile, "add", "-A")
        git(mobile, "commit", "-q", "-m", "init")
        files = features()
        files["mobile.feature"] = feature("@REQ-1 @repo-mobile", [("", "Mobile card", [("AC-6", "Card shows days")])], title="Mobile")
        self.boot_qa(repos=("backend", "frontend", "mobile"), features=files, repo_over={"role": "frontend"},
                     qa={"start_commands": {"frontend": f'{sys.executable} -c "{LISTENER}"', "backend": "true",
                                            "mobile": f'{sys.executable} -c "{LISTENER}"'}})
        self.prepare()
        tids = [self.tdd_tasks("qa_red", "Request form")[0]["id"], self.tdd_tasks("qa_red", "Mobile card")[0]["id"]]
        self.plan(sleep=0.7)
        self.eng.reg.update_row("cycles", self.cycle("Mobile card")["id"], ordinal=0)  # no waiting behind the other cycle
        self.eng._queue_ready(self.eng.reg.get_run_by_id(self.run_row()["id"]))
        for t in tids:
            self.complete_without_verifying(t)
        procs = [self.verifier(t) for t in tids]
        outs = [p.communicate(timeout=60)[0] for p in procs]
        self.assertTrue(all("verdict accepted" in o for o in outs), outs)
        log = self.driver_log()
        spans = sorted((e["at"], next(x["at"] for x in log if x["event"] == "end" and x["pid"] == e["pid"] and x["run"] == e["run"]))
                       for e in log if e["event"] == "start")
        for a, b in zip(spans, spans[1:]):
            self.assertLessEqual(a[1], b[0] + 0.001, spans)
        for c in ("Request form", "Mobile card"):
            self.assertEqual(self.evidence("red", label=c)[-1]["verdict"], "accepted")

    def test_AC_ORC_09j_two_verify_calls_for_the_same_task_write_one_evidence_row(self):
        self.boot_qa()
        self.prepare()
        tid = self.qid()
        self.plan(sleep=1.5)
        self.complete_without_verifying(tid)
        first = self.verifier(tid)
        time.sleep(0.6)
        second = self.verifier(tid)
        outs = [first.communicate(timeout=60)[0], second.communicate(timeout=60)[0]]
        self.assertIn("error E_LOCKED", outs[1], outs)
        self.assertIn("verdict accepted", outs[0], outs)
        self.assertEqual(len([e for e in self.evidence("red", label=self.FORM) if e["task_id"] == tid]), 1)

    def test_AC_ORC_09k_a_killed_engine_during_the_qa_run_is_recovered(self):
        self.boot_qa()
        self.prepare()
        tid = self.qid()
        self.complete_without_verifying(tid)
        self.addCleanup(subprocess.run, ["pkill", "-f", "s.bind\\(\\('127.0.0.1',4173\\)\\)"])
        self.plan(sleep=30)
        p = self.verifier(tid)
        for _ in range(100):
            if self.driver_runs():
                break
            time.sleep(0.1)
        self.assertTrue(self.driver_runs())
        for e in self.driver_log():
            try:
                os.kill(e["pid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        p.kill()
        p.communicate(timeout=10)
        self.plan()
        self.eng.next_step(SLUG)
        self.assertEqual(self.driver_runs() >= 1, True)
        rows = [e for e in self.evidence("red", label=self.FORM) if e["task_id"] == tid]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], "accepted")

    def setUp(self):
        super().setUp()
        self._procs = getattr(self, "_procs", [])


class Invalidation(PJ):
    def start(self, task_role):
        self.eng.start_task(self.qid(task_role), schedule=False)

    def test_AC_ORC_09f_an_invalidated_approval_stops_open_qa_red_cycles(self):
        rows = [("RED_RUNNING", "spec", "R17"), ("RED_RUNNING", "gherkin", "R18"), ("GREEN_RUNNING", "gherkin", "R18")]
        for i, (state, gate, rule) in enumerate(rows):
            with self.subTest(state=state, gate=gate):
                if i:
                    self.reset_ws()
                if state == "RED_RUNNING":
                    self.boot_qa()
                    self.prepare()
                    self.start("qa_red")
                else:
                    self.to_qa_red_verified()
                    self.start("tdd_green")
                self.assertEqual(self.form()["state"], state)
                folder = self.scripts_dir()
                path = self.sdir() / ("spec.md" if gate == "spec" else "features/request_form.feature")
                path.write_text(path.read_text() + "\n# edited\n")
                self.eng.next_step(SLUG)
                self.assertEqual(self.events("run.state_changed")[-1]["payload"]["transition"] if False else
                                 [e["payload"]["transition"] for e in self.events("run.state_changed")][-1], rule)
                c = self.cycle(self.FORM)
                self.assertEqual((c["state"], c["reason"]), ("REJECTED", "approval invalidated"))
                self.assertTrue(self.tdd_tasks("qa_red" if state == "RED_RUNNING" else "tdd_green", self.FORM)[-1]["state"] == "CANCELLED")
                self.assertTrue(list(folder.iterdir()) if state == "GREEN_RUNNING" else True)

    def test_AC_ORC_09g_reapproved_gherkin_replans_qa_red_only_for_changed_groups(self):
        self.to_qa_accepted()
        old = self.form()["id"]
        path = self.sdir() / "features" / "request_form.feature"
        path.write_text(path.read_text().replace("Given x", "Given y", 1))
        self.eng.next_step(SLUG)
        self.approve("gherkin")
        self.eng.advance(SLUG)
        new = self.form()
        self.assertNotEqual(new["id"], old)
        self.assertEqual((new["red_method"], new["state"]), ("qa_scenario", "PLANNED"))
        self.assertIsNotNone(self.eng.reg.get_row("cycles", old))
        planned = [e for e in self.exc_events("planned") if e["payload"]["cycle"] == new["id"]]
        self.assertEqual(len(planned), 1)


class ReportBase(PE, PJ):
    """PE's VERIFYING run with the frontend cycle driven through the real QA-Red flow."""
    FORM = "request_form"

    def to_qa_ready(self, rule=True, run=True):
        self.plan()
        extra = {"qa": self.qa_cfg(), "rules": {RULE: rule}, "policies": {"test_timeout_seconds": 5},
                 "agents": {r: {"runner": "fake"} for r in ROLES}}
        self.boot_ver(tier=3, **extra)
        if rule:
            c = self.form()
            self.eng.reg.update_row("cycles", c["id"], state="PLANNED", tests=None, red_task=None, green_task=None, refactor_task=None)
            self.set_state("EXECUTING")
            self.eng.bookkeep(SLUG)
            self.run_qa()
            self.plan(default={"*": "pass"})
            self.run_qa("tdd_green")
            self.run_qa("tdd_refactor")
            self.assertEqual(self.form()["state"], "CYCLE_ACCEPTED")
            self.assertEqual(self.state(), "VERIFYING")
        self.change()
        for c in self.cycles():
            self.eng.reg.add_trace_link(self.run_row()["id"], "cycle", c["id"], "file", self.BAL)
        if run:
            self.assertEqual(self.verify()["exit"], 0)
            for t in self.new_tasks():
                self.eng.reg.update_row("tasks", t["id"], state="COMPLETED")

    def to_qa_completed(self, rule=True):
        self.to_qa_ready(rule)
        self.eng.next_step(SLUG)
        self.assertEqual(self.state(), "COMPLETED")


class Acceptance(ReportBase):
    def test_AC_VER_05c_a_completed_run_reports_the_exception_and_is_still_accepted(self):
        self.to_qa_ready()
        self.assertEqual(self.state(), "REVIEWING")
        self.eng.next_step(SLUG)
        run = self.run_row()
        self.assertEqual((run["state"], run["acceptance_status"]), ("COMPLETED", "accepted"))
        rep = json.loads((self.ws / ".sentinel/runs" / SLUG / "report.json").read_text())
        self.assertEqual(len(rep["tdd_exceptions"]), 1)
        x = rep["tdd_exceptions"][0]
        for k in ("repo", "cycle", "rule", "method", "red_evidence", "green_evidence", "scenarios", "failed_before_green", "script_hashes"):
            self.assertIn(k, x)
        self.assertEqual((x["repo"], x["rule"], x["method"], x["scenarios"]), ("frontend", RULE, "qa_scenario", 1))
        md = (self.ws / ".sentinel/runs" / SLUG / "report.md").read_text()
        self.assertIn("TDD exceptions", md)
        self.assertIn("QA scenarios were the Red evidence; no test files were committed", md)

    def test_AC_VER_05d_missing_exception_evidence_rejects_the_run_with_its_own_reason(self):
        gaps = ["the tdd.exception_recorded event is missing", "the exception field of the red row was removed", "script hashes no longer match"]
        for i, gap in enumerate(gaps):
            with self.subTest(gap):
                if i:
                    self.reset_ws()
                self.to_qa_ready()
                cid = self.form()["id"]
                if i == 0:
                    delete_events(self, "tdd.exception_recorded")
                elif i == 1:
                    self.sql("UPDATE evidence SET exception=NULL WHERE cycle_id=? AND kind='red'", (cid,))
                else:
                    (self.ws / self.script_rel("AC-4")).write_text("changed after red\n")
                got = self.eng.compute_acceptance(SLUG)
                self.assertEqual(got["status"], "rejected")
                self.assertIn("tdd exception evidence missing: frontend request_form", got["reasons"])

    def test_AC_VER_05e_the_hygiene_rule_applies_to_the_whole_frontend_repo_without_an_exception(self):
        self.to_qa_ready(run=False)
        self.write_file("frontend/src/test/Form.test.ts", "test('x', () => {});\n")
        self.verify()
        row = self.vrows("hygiene", "frontend")[0]
        self.assertEqual(row["verdict"], "fail")
        self.assertIn("test infrastructure left behind: src/test/Form.test.ts", json.loads(row["failing"]))

    def test_AC_VER_05f_the_interim_hygiene_skip_stays_for_test_file_cycles(self):
        self.to_qa_ready(run=False)
        cycle = self.form()
        self.write_file("frontend/src/test/Form.test.ts", "test('x', () => {});\n")
        self.write_file("frontend/src/test/Other.spec.ts", "export default {};\n")
        sha = hashlib.sha256((self.ws / "frontend/src/test/Form.test.ts").read_bytes()).hexdigest()
        self.eng.reg.update_row("cycles", cycle["id"], red_method="test_file",
                                approved_tests=json.dumps([{"path": "frontend/src/test/Form.test.ts", "sha256": sha}]))
        self.verify()
        failing = json.loads(self.vrows("hygiene", "frontend")[0]["failing"])
        self.assertTrue(any("Other.spec.ts" in f for f in failing), failing)
        self.assertFalse(any("Form.test.ts" in f for f in failing), failing)


class Report(ReportBase):
    def test_AC_ART_04a_the_report_is_reproducible_and_shows_the_exception_from_the_registry_alone(self):
        self.to_qa_completed()
        a = self.eng.write_report(SLUG)
        first = (Path(a["json"]).read_bytes(), Path(a["md"]).read_bytes())
        b = self.eng.write_report(SLUG)
        self.assertEqual(first, (Path(b["json"]).read_bytes(), Path(b["md"]).read_bytes()))
        x = a["report"]["tdd_exceptions"][0]
        self.assertEqual(x["red_evidence"], self.evidence("red", label=self.FORM)[-1]["id"])
        self.assertEqual(x["green_evidence"], self.evidence("green", label=self.FORM)[-1]["id"])

    def test_AC_ART_04b_a_run_with_no_exception_has_no_empty_section(self):
        self.to_qa_completed(rule=False)
        rep = self.eng.write_report(SLUG)
        self.assertEqual(rep["report"]["tdd_exceptions"], [])
        self.assertNotIn("TDD exceptions", Path(rep["md"]).read_text())

    def test_AC_ART_04c_export_and_import_keep_the_exception(self):
        self.to_qa_completed()
        (self.ws / "out").mkdir()
        res = self.eng.export_run(SLUG, out_dir=str(self.ws / "out"), user="dev")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ws = Path(tmp.name)
        (ws / "sentinel.config.yaml").write_text((self.ws / "sentinel.config.yaml").read_text())
        for rid in ("backend", "frontend"):
            (ws / rid).mkdir()
            git(ws / rid, "init", "-q")
            (ws / rid / "README.md").write_text("hello\n")
            git(ws / rid, "add", "-A")
            git(ws / rid, "commit", "-q", "-m", "init")
        eng = Engine(ws / ".sentinel", ws, yaml.safe_load((ws / "sentinel.config.yaml").read_text()))
        self.addCleanup(eng.close)
        eng.import_run(res["path"])
        run = eng.reg.get_run(SLUG)
        c = next(c for c in eng.reg.rows("cycles", run_id=run["id"]) if c["red_method"] == "qa_scenario")
        red = next(e for e in eng.reg.rows("evidence", run_id=run["id"], cycle_id=c["id"], kind="red"))
        self.assertEqual((red["method"], json.loads(red["exception"])["by"]), ("qa_scenario", "qa_scenario"))
        self.assertTrue(json.loads(red["scripts"])[0]["sha256"])
        self.assertFalse(list((ws / ".sentinel" / "cache").rglob("*.spec")) if (ws / ".sentinel" / "cache").exists() else [])
        x = eng.build_report(SLUG)["tdd_exceptions"][0]
        self.assertTrue(all(h["exported"] is False for h in x["script_hashes"]))


if __name__ == "__main__":
    unittest.main()
