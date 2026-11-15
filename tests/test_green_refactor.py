"""Phase D part 2b (PD-02): Green and Refactor phases (green_refactor.feature)."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import classifier  # noqa: E402
from pd_helpers import (CARRY_TEST, FORM_TEST, PROD, SLUG, T1, T2, TEST_FILE, TWO_REPOS, PDX, all_pass, report)  # noqa: E402

TEST_JAVA = "backend/src/test/java/leave/RemainingBalanceTest.java"
G_STATES = ["PLANNED", "RED_RUNNING", "RED_VERIFIED", "GREEN_RUNNING", "GREEN_VERIFIED"]


def fail_one(name, others="pass"):
    cases = [[c, n, "pass"] for c, n in [("RemainingBalanceTest", "employeeSeesRemainingDays"), ("RemainingBalanceTest", "balanceNeverBelowZero")]]
    for case in cases:
        if f"{case[0]}.{case[1]}" == name:
            case[2] = "failure"
    return cases


class Green(PDX):
    def edit_prod_and(self, action):
        return f"write({PROD!r}, 'class LeaveBalance {{}}\\n')\n{action}\nwrite_result()\n"

    def test_AC_TDD_04a_green_passes_and_refactor_can_begin(self):
        gid = self.to_red_verified()
        self.targeted(report("Remaining", "pass"))
        out = self.eng.run_task(gid)
        self.assertEqual(out["exit"], 0, out)
        self.assertEqual(self.moves("Remaining"), G_STATES)
        rows = self.evidence("green")
        self.assertEqual(len(rows), 1)
        e = rows[0]
        self.assertIn(" targeted ", e["command"])
        self.assertEqual((e["exit_code"], e["passed"], e["failed"], e["verdict"], e["classification"]), (0, 2, 0, "accepted", "pass"))
        changed = self.eng.reg.rows("changed_files", task_id=gid)
        self.assertEqual([(c["repo_id"], c["path"], c["phase"], c["before_sha256"]) for c in changed],
                         [("backend", "src/main/java/leave/LeaveBalance.java", "tdd_green", None)])
        self.assertEqual(changed[0]["after_sha256"], hashlib.sha256((self.ws / PROD).read_bytes()).hexdigest())
        self.assertEqual([t["state"] for t in self.tdd_tasks("tdd_refactor", "Remaining")], ["QUEUED"])
        self.assertEqual(self.cycle("Remaining")["green_task"], gid)

    def test_AC_TDD_04b_green_changing_approved_tests_is_rejected(self):
        rows = [("edits", f"write({TEST_JAVA!r}, 'changed')", "approved_test_changed", TEST_JAVA),
                ("deletes", f"os.remove(os.path.join(ws, {TEST_JAVA!r}))", "approved_test_changed", TEST_JAVA),
                ("renames", f"os.rename(os.path.join(ws, {TEST_JAVA!r}), os.path.join(ws, 'backend/src/test/java/leave/Old.java'))",
                 "approved_test_changed", TEST_JAVA),
                ("creates", "write('backend/src/test/java/leave/ExtraTest.java', 'class E {}')", "outside_write_scope",
                 "backend/src/test/java/leave/ExtraTest.java")]
        for i, (name, action, kind, listed) in enumerate(rows):
            with self.subTest(name):
                if i:
                    self.reset_ws()
                gid = self.to_red_verified()
                self.agent_exec("tdd_green", self.edit_prod_and(action))
                before = len(self.tool_log())
                out = self.eng.run_task(gid)
                self.assertEqual(out["exit"], 3, out)
                row = self.task(gid)
                self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
                self.assertIn(listed, row["reason"])
                kinds = {e["payload"]["kind"] for e in self.events("task.scope_violation") if e["task_id"] == gid}
                self.assertIn(kind, kinds)
                self.assertEqual(len(self.tool_log()), before)
                self.assertEqual(len(self.tdd_tasks("tdd_green", "Remaining")), 1)
                self.assertEqual((self.cstate("Remaining"), self.state()), ("GREEN_RUNNING", "NEEDS_HUMAN"))
                self.assertTrue((self.ws / PROD).exists())
                if name == "edits":
                    self.assertEqual((self.ws / TEST_JAVA).read_text(), "changed")

    def test_AC_TDD_04c_an_approved_test_rewritten_with_the_same_bytes_is_not_a_change(self):
        gid = self.to_red_verified()
        self.agent_exec("tdd_green", self.edit_prod_and(f"p = pathlib.Path(ws, {TEST_JAVA!r}); p.write_bytes(p.read_bytes())"))
        self.targeted(all_pass())
        out = self.eng.run_task(gid)
        self.assertEqual(out["exit"], 0, out)
        self.assertEqual(self.cstate("Remaining"), "GREEN_VERIFIED")

    def test_AC_TDD_04d_failing_targeted_tests_send_the_work_back_to_green(self):
        gid = self.to_red_verified()
        self.targeted(fail_one(T2))
        out = self.eng.run_task(gid)
        self.assertEqual(out["exit"], 1, out)
        self.assertEqual(self.task(gid)["state"], "COMPLETED")
        e = self.evidence("green")[0]
        self.assertEqual((e["verdict"], e["reason"]), ("rejected", f"targeted tests fail: {T2}"))
        self.assertEqual(json.loads(e["failing"]), [T2])
        self.assertEqual(self.cstate("Remaining"), "GREEN_RUNNING")
        greens = self.tdd_tasks("tdd_green", "Remaining")
        self.assertEqual([t["state"] for t in greens], ["COMPLETED", "QUEUED"])
        self.assertEqual((greens[1]["retry_of"], greens[1]["attempt"]), (gid, 2))
        brief = (self.tdir(greens[1]["id"]) / "brief.md").read_text()
        self.assertIn(T2, brief)
        self.assertIn("attempt 2 of 4", brief)
        self.assertEqual(self.task_json(greens[1]["id"])["constraints"]["max_retries"], 3)

    def test_AC_TDD_04e_a_claim_that_the_tests_passed_is_not_evidence(self):
        gid = self.to_red_verified()
        self.agent_exec("tdd_green", f"write({PROD!r}, 'class LeaveBalance {{}}\\n')\n"
                                     "write_result(claimed_commands=[{'command': './gradlew test', 'exit_code': 0}])\n")
        self.targeted(fail_one(T1))
        self.eng.run_task(gid)
        e = self.evidence("green")[0]
        self.assertNotIn("gradlew", e["command"])
        self.assertEqual([x["mode"] for x in self.tool_log()][-1], "targeted")
        self.assertEqual(self.cstate("Remaining"), "GREEN_RUNNING")
        report_ = json.loads((self.tdir(gid) / "report.json").read_text())
        flags = json.dumps(report_["claim_flags"])
        self.assertIn("./gradlew test", flags)
        self.assertIn("differs from the evidence", flags)

    def test_AC_TDD_04f_an_approved_test_changed_between_red_and_green_stops_the_cycle(self):
        gid = self.to_red_verified()
        p = self.ws / TEST_JAVA
        p.write_text(p.read_text() + "// by hand\n")
        out = self.eng.run_task(gid)
        self.assertEqual((out["error"], out["exit"]), ("E_INTEGRITY", 6), out)
        self.assertIn(TEST_JAVA, out["reason"])
        self.assertEqual(len(self.audit("integrity_failed")), 1)
        self.assertEqual(self.task(gid)["state"], "QUEUED")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertIn(TEST_JAVA, self.last_reason())

    def test_green_verdicts_of_the_classifier(self):
        base = dict(passed=2, failed=0, skipped=0, failing=[], new_failing=[], new_passing=[T1, T2], new_absent=[], outside=[])
        tests = [T1, T2]
        rows = [({**base, "classification": "pass"}, "accepted", None),
                ({**base, "classification": "assertion", "failing": [T2], "new_passing": [T1]}, "rejected", f"targeted tests fail: {T2}"),
                ({**base, "classification": "pass", "new_absent": [T2], "new_passing": [T1]}, "rejected", f"targeted tests did not run: {T2}"),
                ({**base, "classification": "compile"}, "rejected", "compile: the tests did not run"),
                ({**base, "classification": "unknown"}, "needs_human", "the result could not be classified")]
        for cl, verdict, reason in rows:
            with self.subTest(cl["classification"], reason=reason):
                self.assertEqual(classifier.verify_green(cl, tests), (verdict, reason))

    def test_green_run_that_cannot_be_classified_goes_to_a_human(self):
        gid = self.to_red_verified()
        self.targeted([], exit_code=139, stderr="Segmentation fault", report=None)
        out = self.eng.run_task(gid)
        self.assertEqual((out["exit"], self.state(), self.cstate("Remaining")), (6, "NEEDS_HUMAN", "GREEN_RUNNING"))
        self.assertEqual(len(self.tdd_tasks("tdd_green", "Remaining")), 1)


class Refactor(PDX):
    def test_AC_TDD_05a_a_refactor_that_keeps_the_tests_green_is_accepted(self):
        rid = self.to_green_verified()
        self.accepted_carry_over()
        self.targeted(all_pass())
        out = self.eng.run_task(rid)
        self.assertEqual(out["exit"], 0, out)
        self.assertEqual(self.moves("Remaining")[-4:], ["GREEN_VERIFIED", "REFACTOR_RUNNING", "REFACTOR_VERIFIED", "CYCLE_ACCEPTED"])
        rows = self.evidence("refactor")
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["tests"]), [T1, T2, CARRY_TEST])
        self.assertEqual(self.tool_log()[-1]["args"], [T1, T2, CARRY_TEST])
        self.assertEqual(rows[0]["verdict"], "accepted")
        cyc = self.cycle("Remaining")
        self.assertEqual((cyc["refactor_task"], bool(cyc["accepted_at"])), (rid, True))

    def test_AC_TDD_05b_a_refactor_that_breaks_a_targeted_test_is_rejected(self):
        rid = self.to_green_verified()
        self.agent_exec("tdd_refactor", f"write({PROD!r}, 'class LeaveBalance {{ /* refactor */ }}\\n')\nwrite_result()\n")
        self.targeted(fail_one(T1))
        out = self.eng.run_task(rid)
        self.assertEqual(out["exit"], 1, out)
        evs = [e for e in self.events("refactor.rejected")]
        self.assertEqual(len(evs), 1)
        self.assertIn(T1, json.dumps(evs[0]["payload"]))
        self.assertEqual(self.cstate("Remaining"), "REFACTOR_RUNNING")
        retry = self.tdd_tasks("tdd_refactor", "Remaining")[-1]
        self.assertEqual((retry["state"], retry["retry_of"]), ("QUEUED", rid))
        self.assertIn(T1, (self.tdir(retry["id"]) / "brief.md").read_text())
        self.assertEqual((self.ws / PROD).read_text(), "class LeaveBalance { /* refactor */ }\n")

    def test_AC_TDD_05c_a_refactor_that_breaks_an_earlier_cycles_test_is_rejected(self):
        rid = self.to_green_verified()
        self.accepted_carry_over()
        self.targeted(all_pass()[:2] + [["CarryOverTest", "unusedDaysCarryOver", "failure"]])
        self.eng.run_task(rid)
        self.assertEqual(self.cstate("Remaining"), "REFACTOR_RUNNING")
        e = self.evidence("refactor")[0]
        self.assertEqual((e["verdict"], e["reason"]), ("rejected", f"related tests fail: {CARRY_TEST}"))

    def test_AC_TDD_05d_which_tests_are_related(self):
        self.boot_x(repos=TWO_REPOS)
        run = self.run_row()
        rows = [("Carry", "backend", "CYCLE_ACCEPTED", True), ("Carry", "backend", "PLANNED", False),
                ("request_form", "frontend", "CYCLE_ACCEPTED", False)]
        self.set_cycle("Remaining", state="GREEN_VERIFIED", tests=[T1, T2])
        for label, repo, state, included in rows:
            with self.subTest(label=label, state=state):
                self.set_cycle("Carry", state="PLANNED")
                self.set_cycle("request_form", state="PLANNED")
                self.set_cycle(label, state=state, tests=[CARRY_TEST if label == "Carry" else FORM_TEST])
                self.assertEqual(self.cycle(label)["repo_id"], repo)
                got = self.eng.related_tests(run, self.cycle("Remaining"))
                self.assertEqual(got[:2], [T1, T2])
                self.assertEqual((CARRY_TEST in got) or (FORM_TEST in got), included)

    def test_AC_TDD_05e_a_refactor_that_changes_nothing_is_still_verified_by_the_engine(self):
        rid = self.to_green_verified()
        self.agent_exec("tdd_refactor", "write_result()")
        self.targeted(all_pass())
        before = len(self.tool_log())
        out = self.eng.run_task(rid)
        self.assertEqual(out["exit"], 0, out)
        self.assertEqual(self.cstate("Remaining"), "CYCLE_ACCEPTED")
        self.assertEqual(len(self.tool_log()), before + 1)
        self.assertEqual(self.eng.reg.rows("changed_files", task_id=rid), [])
        self.assertEqual(json.loads(self.evidence("refactor")[0]["tests"]), [T1, T2])

    def test_AC_TDD_05f_a_refactor_that_touches_a_test_file_is_a_scope_violation(self):
        rid = self.to_green_verified()
        self.agent_exec("tdd_refactor", f"write({TEST_JAVA!r}, 'changed')\nwrite_result()\n")
        out = self.eng.run_task(rid)
        self.assertEqual(out["exit"], 3, out)
        row = self.task(rid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
        kinds = {e["payload"]["kind"] for e in self.events("task.scope_violation") if e["task_id"] == rid}
        self.assertEqual(kinds, {"approved_test_changed"})
        self.assertEqual(self.state(), "NEEDS_HUMAN")


if __name__ == "__main__":
    unittest.main()
