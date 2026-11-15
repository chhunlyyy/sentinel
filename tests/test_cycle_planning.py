"""Phase D part 2a (PD-02): cycle planning, repo assignment, baseline (cycle_planning.feature)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import machines  # noqa: E402
from errors import SentinelError  # noqa: E402
from pd_helpers import (CARRY, FORM, PD, REMAINING, SLUG, default_features, feature)  # noqa: E402

TWO = ("backend", "frontend")


class Planning(PD):
    def test_AC_TDD_01a_both_approvals_valid_plans_the_cycles(self):
        self.boot_pd(repos=TWO)
        self.assertEqual(self.state(), "GHERKIN_APPROVED")
        self.eng.advance(SLUG)
        self.assertEqual(self.state(), "EXECUTING")
        rows = [(c["behavior"], c["repo_id"], len(json.loads(c["scenarios"])), c["state"]) for c in self.cycles()]
        self.assertEqual(rows, [("features/balance.feature :: Rule Remaining balance", "backend", 2, "PLANNED"),
                                ("features/balance.feature :: Rule Carry-over", "backend", 1, "PLANNED"),
                                ("features/request_form.feature", "frontend", 1, "PLANNED")])
        self.assertEqual(len(self.events("cycle.planned")), 3)
        links = self.links("scenario", "cycle")
        keys = [r["from_id"] for r in links]
        self.assertEqual(sorted(keys), sorted(REMAINING + [CARRY, FORM]))
        self.assertEqual(len(keys), len(set(keys)))
        by_cycle = {r["from_id"]: r["to_id"] for r in links}
        self.assertEqual(by_cycle[CARRY], self.cycle("Carry")["id"])

    def test_AC_TDD_01b_how_scenarios_group_into_behaviors(self):
        rows = [
            ("3 scenarios and no Rule", feature("@REQ-1 @repo-backend", [], [("AC-1", "a"), ("AC-2", "b"), ("AC-3", "c")]),
             [("features/x.feature", 3)]),
            ("rules", feature("@REQ-1 @repo-backend", [("", "A", [("AC-1", "a"), ("AC-2", "b")]), ("", "B", [("AC-3", "c")])]),
             [("features/x.feature :: Rule A", 2), ("features/x.feature :: Rule B", 1)]),
            ("before rule", feature("@REQ-1 @repo-backend", [("", "A", [("AC-2", "b"), ("AC-3", "c")])], [("AC-1", "a")]),
             [("features/x.feature :: (no rule)", 1), ("features/x.feature :: Rule A", 2)]),
        ]
        for i, (name, text, want) in enumerate(rows):
            with self.subTest(name):
                if i:
                    self.reset_ws()
                self.boot_exec(features={"x.feature": text}, repos=TWO)
                got = [(c["behavior"], len(json.loads(c["scenarios"]))) for c in self.cycles()]
                self.assertEqual(got, want)

    def test_AC_TDD_01b_outline_counts_as_one_scenario(self):
        text = ("@REQ-1 @repo-backend\nFeature: F\n\n  Rule: A\n\n    @AC-1 @unit @P1\n    Scenario Outline: o\n      Given <x>\n"
                "      Examples:\n        | x |\n        | 1 |\n        | 2 |\n        | 3 |\n        | 4 |\n\n"
                "    @AC-2 @unit @P1\n    Scenario: b\n      Given x\n      Then z\n"
                "  Rule: B\n\n    @AC-3 @unit @P1\n    Scenario: c\n      Given x\n      Then z\n")
        self.boot_exec(features={"x.feature": text}, repos=TWO)
        self.assertEqual([(c["behavior"], len(json.loads(c["scenarios"]))) for c in self.cycles()],
                         [("features/x.feature :: Rule A", 2), ("features/x.feature :: Rule B", 1)])

    def test_AC_TDD_01c_repo_assignment_of_a_behavior_group(self):
        def feats(feature_tags, rule_tags):
            bal = feature(f"@REQ-1 {feature_tags}".strip(), [("@repo-backend" if len(repos) > 1 else "", "Remaining balance", [("AC-1", "Employee sees remaining days"), ("AC-2", "Balance never goes below zero")]),
                                                      (rule_tags, "Carry-over", [("AC-3", "Unused days carry over"), ("AC-4", "Form shows the balance")])])
            return {"balance.feature": bal}
        rows = [(("backend",), "", "", "backend", None),
                (TWO, "@repo-backend", "", "backend", None),
                (TWO, "@repo-backend", "@repo-frontend", "frontend", None),
                (TWO, "", "", None, "Rule Carry-over names no repo"),
                (TWO, "@repo-mobile", "", None, "unknown repo mobile")]
        for i, (repos, ftags, rtags, repo, problem) in enumerate(rows):
            with self.subTest(i=i):
                if i:
                    self.reset_ws()
                self.boot_pd(features=feats(ftags, rtags), repos=repos)
                if problem:
                    with self.assertRaises(SentinelError):
                        self.eng.advance(SLUG)
                    self.assertEqual(self.state(), "NEEDS_HUMAN")
                    self.assertEqual(self.last_reason(), problem)
                    self.assertEqual(self.cycles(), [])
                    self.assertEqual(self.links("scenario", "cycle"), [])
                else:
                    self.eng.advance(SLUG)
                    self.assertEqual(self.cycle("Carry-over")["repo_id"], repo)

    def test_AC_TDD_01d_planning_stores_all_cycles_or_none(self):
        self.boot_pd(repos=TWO)
        real = self.eng.reg.insert_row
        count = []

        def flaky(table, row):
            if table == "cycles":
                count.append(1)
                if len(count) == 3:
                    raise RuntimeError("database error")
            return real(table, row)
        self.eng.reg.insert_row = flaky
        with self.assertRaises(RuntimeError):
            self.eng.advance(SLUG)
        self.eng.reg.insert_row = real
        self.assertEqual(self.state(), "GHERKIN_APPROVED")
        self.assertEqual(self.cycles(), [])
        self.assertEqual(self.links("scenario", "cycle"), [])
        self.assertEqual(self.eng.reg.rows("tasks", run_id=self.run_row()["id"], role="tdd_red"), [])

    def test_AC_TDD_01e_same_repo_in_file_order_other_repos_do_not_wait(self):
        self.boot_exec(repos=TWO, policies={"max_parallel_tasks": 2})
        code, step, _ = self.next_json()
        self.assertEqual(code, 0)
        red = {c: self.tdd_tasks("tdd_red", c)[0] for c in ("Remaining", "Carry", "request_form")}
        self.assertEqual(red["Remaining"]["state"], "QUEUED")
        self.assertEqual(red["request_form"]["state"], "QUEUED")
        self.assertEqual(red["Carry"]["state"], "CREATED")
        self.assertEqual(step["role"], "tdd_red")
        self.assertIn(f"cycle {self.cycle('Remaining')['id']}", " ".join(self.eng.open_dependencies(red["Carry"]["id"])))

    def test_AC_TDD_01e_next_accepted_cycle_queues_the_following_one(self):
        self.boot_exec(repos=("backend",), features={"balance.feature": default_features()["balance.feature"],
                                                    "other.feature": feature("@REQ-2", [], [("AC-4", "Form shows the balance")], "Other")})
        self.prepare()
        carry = self.tdd_tasks("tdd_red", "Carry")[0]["id"]
        self.assertEqual(self.task(carry)["state"], "CREATED")
        self.eng.reg.update_row("cycles", self.cycle("Remaining")["id"], state="CYCLE_ACCEPTED")
        self.eng.schedule(SLUG)
        self.assertEqual(self.task(carry)["state"], "QUEUED")

    def test_AC_TDD_01f_gherkin_edit_before_red_stops_the_red_phase(self):
        self.boot_exec()
        self.prepare()
        p = self.sdir() / "features" / "balance.feature"
        p.write_text(p.read_text().replace("Given x", "Given y", 1))
        code, step, _ = self.next_json()
        self.assertEqual(self.state(), "GHERKIN_REVIEW")
        self.assertEqual(self.rules()[-1], "R18")
        self.assertNotIn("RED_RUNNING", [e["payload"]["to"] for e in self.cycle_events()])
        self.assertFalse([t for t in self.tdd_tasks("tdd_red") if t["state"] in ("RUNNING", "QUEUED")])
        self.assertTrue(all(c["state"] == "REJECTED" for c in self.cycles()))

    def test_AC_TDD_01g_only_the_engine_moves_a_cycle(self):
        self.boot_exec()
        cid = self.cycle("Remaining")["id"]
        rows = [("orchestrator", "PLANNED", "RED_RUNNING"), ("orchestrator", "RED_RUNNING", "RED_VERIFIED"),
                ("human", "GREEN_RUNNING", "GREEN_VERIFIED"), ("human", "REFACTOR_VERIFIED", "CYCLE_ACCEPTED")]
        for actor, frm, to in rows:
            with self.subTest(actor=actor, frm=frm):
                self.eng.reg.update_row("cycles", cid, state=frm)
                with self.assertRaises(SentinelError) as cm:
                    self.eng.request_cycle_state(cid, to, actor)
                self.assertEqual(cm.exception.code, "E_ACTOR")
                self.assertEqual(self.eng.reg.get_row("cycles", cid)["state"], frm)

    def test_AC_SM_05e_undefined_cycle_moves_are_refused(self):
        self.boot_exec()
        cid = self.cycle("Remaining")["id"]
        for frm, to in [("PLANNED", "GREEN_RUNNING"), ("RED_VERIFIED", "CYCLE_ACCEPTED"), ("CYCLE_ACCEPTED", "RED_RUNNING"),
                        ("REJECTED", "PLANNED")]:
            with self.subTest(frm=frm, to=to):
                self.eng.reg.update_row("cycles", cid, state=frm)
                with self.assertRaises(SentinelError) as cm:
                    self.eng.request_cycle_state(cid, to, "engine")
                self.assertEqual(cm.exception.code, "E_TRANSITION")

    def test_machines_reject_from_any_open_state(self):
        for s in ("PLANNED", "RED_RUNNING", "RED_VERIFIED", "GREEN_RUNNING", "GREEN_VERIFIED", "REFACTOR_RUNNING", "REFACTOR_VERIFIED"):
            self.assertIsNone(machines.check_cycle(s, "REJECTED", "engine"))
        with self.assertRaises(SentinelError):
            machines.check_cycle("CYCLE_ACCEPTED", "REJECTED", "engine")

    def test_AC_TDD_07a_repro_test_is_cycle_1_red_and_stays_a_regression_test(self):
        feats = {"bug.feature": feature("@REQ-1 @repo-backend", [("", "Reproduce negative balance", [("AC-1", "Negative balance is reproduced")]),
                                                              ("", "Clamp at zero", [("AC-2", "Balance clamps at zero")])])}
        spec = dict(acs=("AC-1 (REQ-1): a", "AC-2 (REQ-1): b"))
        self.boot_pd(features=feats, tier=2, typ="bug")
        self.eng.advance(SLUG)
        self.prepare()
        first = self.tdd_tasks("tdd_red", "Reproduce")[0]
        doc = self.task_json(first["id"])
        self.assertIn("reproduce the reported bug", doc["objective"].lower())
        self.assertNotIn("reproduce the reported bug", self.task_json(self.tdd_tasks("tdd_red", "Clamp")[0]["id"])["objective"].lower())
        cyc = self.cycle("Reproduce")
        path = "backend/src/test/java/leave/NegativeBalanceTest.java"
        self.eng.reg.update_row("cycles", cyc["id"], state="CYCLE_ACCEPTED", approved_tests=json.dumps([{"path": path, "sha256": "a" * 64}]))
        later = self.eng.create_task(SLUG, "tdd_green", "g", repos=["backend"], cycle_id=self.cycle("Clamp")["id"])
        self.assertIn(path, self.task_json(later["id"])["permissions"]["readonly_approved"])
        later = self.eng.create_task(SLUG, "tdd_refactor", "r", repos=["backend"], cycle_id=self.cycle("Clamp")["id"])
        self.assertIn(path, self.task_json(later["id"])["permissions"]["readonly_approved"])


class Baseline(PD):
    def booted(self, **modes):
        self.boot_exec(tool=modes or None)
        self.prepare()
        return self.next_red("Remaining")

    def test_AC_TDD_03a_baseline_once_per_repo_before_the_first_red(self):
        full = {"exit": 1, "extra_passed": 40, "report": [["LegacyTest", "flaky", "failure"]]}
        tid = self.booted(full=full, targeted={"exit": 1, "report": [["RemainingBalanceTest", "employeeSeesRemainingDays", "failure"],
                                                                     ["RemainingBalanceTest", "balanceNeverBelowZero", "failure"]]})
        self.eng.run_task(tid)
        rows = self.evidence("baseline")
        self.assertEqual(len(rows), 1)
        e = rows[0]
        self.assertEqual((e["classification"], e["passed"], e["failed"], e["exit_code"]), ("assertion", 40, 1, 1))
        self.assertEqual(json.loads(e["failing"]), ["LegacyTest.flaky"])
        self.assertIn(" full", e["command"])
        self.assertEqual(len(e["repo_sha"]), 40)
        self.assertEqual(e["cwd"], "backend")
        self.assertLess(e["finished_at"], self.task(tid)["started_at"])
        self.assertEqual(self.tool_log()[0]["mode"], "full")
        self.eng.reg.update_row("cycles", self.cycle("Remaining")["id"], state="CYCLE_ACCEPTED")
        self.eng.schedule(SLUG)
        self.eng.run_task(self.next_red("Carry"))
        self.assertEqual(len(self.evidence("baseline")), 1)

    def test_AC_TDD_03b_a_baseline_that_cannot_run_stops_execution_in_that_repo(self):
        rows = [({"exit": 1, "stdout": "error: cannot find symbol"}, "compile"),
                ({"exit": 1, "stdout": "Connection refused"}, "environment"),
                ({"exit": 1, "stdout": "Could not resolve com.acme:leave-core:1.0"}, "missing_dependency"),
                ({"exit": 139, "stderr": "Segmentation fault"}, "unknown")]
        for i, (outcome, klass) in enumerate(rows):
            with self.subTest(klass):
                if i:
                    self.reset_ws()
                tid = self.booted(full=outcome)
                out = self.eng.run_task(tid)
                self.assertEqual(self.evidence("baseline")[0]["classification"], klass)
                self.assertEqual(self.state(), "NEEDS_HUMAN")
                self.assertEqual(self.last_reason(), f"baseline for backend failed: {klass}")
                self.assertEqual(self.task(tid)["state"], "QUEUED")
                self.assertEqual(out["exit"], 6)
                self.assertEqual(self.cstate("Remaining"), "PLANNED")

    def test_AC_TDD_03m_a_repo_with_no_tests_has_an_empty_baseline(self):
        tid = self.booted(full={"exit": 0, "report": []}, targeted={"exit": 1, "report": [["RemainingBalanceTest", "employeeSeesRemainingDays", "failure"],
                                                                                 ["RemainingBalanceTest", "balanceNeverBelowZero", "failure"]]})
        out = self.eng.run_task(tid)
        e = self.evidence("baseline")[0]
        self.assertEqual((e["passed"], e["failed"], json.loads(e["failing"])), (0, 0, []))
        self.assertEqual(self.cstate("Remaining"), "RED_VERIFIED", out)


if __name__ == "__main__":
    unittest.main()
