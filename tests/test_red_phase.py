"""Phase D part 2a (PD-02): Red phase, binding, failure classifier (red_phase.feature)."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import classifier  # noqa: E402
from pd_helpers import CARRY, REMAINING, RED_OK, SLUG, T1, T2, TEST_FILE, PD  # noqa: E402

BASE_FULL = {"exit": 1, "extra_passed": 3, "report": [["LegacyTest", "flaky", "failure"]]}
NEW_FAIL = [["RemainingBalanceTest", "employeeSeesRemainingDays", "failure"], ["RemainingBalanceTest", "balanceNeverBelowZero", "failure"]]
NEW_PASS = [[c, n, "pass"] for c, n, _ in NEW_FAIL]
LEGACY = ["LegacyTest", "flaky", "failure"]
PATTERNS = {"compile": ["error: cannot find symbol"], "environment": ["Connection refused"], "missing_dependency": ["Could not resolve"]}


def refs_agent(refs):
    """Fake agent writing a Java test file with one method per reference."""
    names = ["employeeSeesRemainingDays", "balanceNeverBelowZero", "extraOne", "extraTwo"]
    body = "".join(f'  @Scenario("{r}")\n  void {names[i]}() {{}}\n' for i, r in enumerate(refs))
    return f"write({TEST_FILE!r}, 'class RemainingBalanceTest {{\\n' + {body!r} + '}}\\n')\nwrite_result()\n"


class RedBase(PD):
    def red(self, targeted, full=BASE_FULL, body=RED_OK, **kw):
        self.boot_exec(agent_body=body, tdd=kw.pop("tdd", {"red_retries": 2}), tool={"full": full, "targeted": targeted}, **kw)
        self.prepare()
        return self.next_red("Remaining")

    def reds(self):
        return self.tdd_tasks("tdd_red", "Remaining")


class Classifier(unittest.TestCase):
    CASES = [(T1, "failure"), (T2, "failure")]

    def cl(self, exit_code, output, report, new=(T1, T2), base=("LegacyTest.flaky",)):
        return classifier.classify(exit_code, output, report, PATTERNS, new_tests=new, baseline_failing=base)

    def test_AC_TDD_03e_classification_precedence_when_several_signals_appear(self):
        rows = [("compile + environment", self.cl(1, "error: cannot find symbol\nConnection refused", None), "compile"),
                ("missing + environment", self.cl(1, "Could not resolve x\nConnection refused", None), "missing_dependency"),
                ("environment + assertion", self.cl(1, "Connection refused", self.CASES), "environment"),
                ("assertion + legacy", self.cl(1, "", self.CASES + [("LegacyTest.flaky", "failure")]), "assertion")]
        for name, got, want in rows:
            with self.subTest(name):
                self.assertEqual(got["classification"], want)

    def test_unknown_preexisting_and_pass(self):
        self.assertEqual(self.cl(139, "Segmentation fault", None)["classification"], "unknown")
        self.assertEqual(self.cl(1, "", [(T1, "error"), (T2, "error")])["classification"], "unknown")
        self.assertEqual(self.cl(1, "", [("LegacyTest.flaky", "failure")])["classification"], "preexisting_failure")
        self.assertEqual(self.cl(0, "", [(T1, "pass"), (T2, "pass")])["classification"], "pass")
        got = self.cl(1, "", [(T1, "failure"), (T2, "pass")])
        self.assertEqual((got["classification"], got["new_passing"], got["new_failing"]), ("assertion", [T2], [T1]))

    def test_profile_assertion_patterns_turn_errors_into_assertions(self):
        pats = {**PATTERNS, "assertion": ["AttributeError"]}
        got = classifier.classify(1, "AttributeError: no attr", [(T1, "error"), (T2, "error")], pats, new_tests=(T1, T2))
        self.assertEqual(got["classification"], "assertion")

    def test_junit_report_parsing_and_counts(self):
        xml = ('<testsuites><testsuite><testcase classname="a.b.FooTest" name="x"/><testcase classname="FooTest" name="y"><failure/></testcase>'
               '<testcase classname="FooTest" name="z"><error/></testcase><testcase classname="FooTest" name="s"><skipped/></testcase></testsuite></testsuites>')
        self.assertEqual(classifier.parse_junit(xml), [("FooTest.x", "pass"), ("FooTest.y", "failure"), ("FooTest.z", "error"), ("FooTest.s", "skipped")])
        self.assertIsNone(classifier.parse_junit("<not xml"))

    def test_baseline_mode_classes(self):
        got = classifier.classify(1, "", [("A.t", "failure"), ("A.u", "pass")], PATTERNS)
        self.assertEqual((got["classification"], got["passed"], got["failed"], got["failing"]), ("assertion", 1, 1, ["A.t"]))
        self.assertEqual(classifier.classify(0, "", [], PATTERNS)["classification"], "pass")
        self.assertEqual(classifier.classify(0, "", None, PATTERNS)["classification"], "pass")
        self.assertEqual(classifier.classify(1, "", None, PATTERNS)["classification"], "unknown")

    def test_output_line_picks_the_matching_line(self):
        out = "ok\nRemainingBalanceTest.java:12: error: cannot find symbol\nmore"
        self.assertEqual(classifier.output_line("compile", out, PATTERNS), "RemainingBalanceTest.java:12: error: cannot find symbol")


class RedVerification(RedBase):
    def test_AC_TDD_03c_red_produces_the_expected_assertion_failures(self):
        tid = self.red({"exit": 1, "report": NEW_FAIL + [LEGACY]})
        out = self.eng.run_task(tid)
        self.assertEqual(out["exit"], 0, out)
        self.assertEqual(self.task(tid)["state"], "COMPLETED")
        self.assertEqual(self.moves("Remaining"), ["PLANNED", "RED_RUNNING", "RED_VERIFIED"])
        e = self.evidence("red")[0]
        self.assertIn(" targeted ", e["command"])
        self.assertNotEqual(e["exit_code"], 0)
        self.assertEqual((e["classification"], e["failed"], e["verdict"]), ("assertion", 2, "accepted"))
        self.assertEqual(sorted(json.loads(e["failing"])), sorted([T1, T2]))
        self.assertEqual((e["task_id"], e["provider"]), (tid, "fake"))
        self.assertEqual(len(e["repo_sha"]), 40)
        self.assertLessEqual(e["started_at"], e["finished_at"])
        cyc = self.cycle("Remaining")
        approved = json.loads(cyc["approved_tests"])
        data = (self.ws / TEST_FILE).read_bytes()
        self.assertEqual(approved, [{"path": TEST_FILE, "sha256": hashlib.sha256(data).hexdigest()}])
        self.assertEqual(sorted(json.loads(cyc["tests"])), sorted([T1, T2]))
        self.assertEqual(cyc["red_task"], tid)
        green = self.tdd_tasks("tdd_green", "Remaining")
        self.assertEqual([g["state"] for g in green], ["QUEUED"])
        self.assertEqual(self.tool_log()[-1]["args"], [T1, T2])

    def test_AC_TDD_03d_classification_and_routing_of_a_red_run(self):
        rows = [("compile", {"exit": 1, "stdout": "error: cannot find symbol"}, "PLANNED", True, "EXECUTING", 1),
                ("missing_dependency", {"exit": 1, "stdout": "Could not resolve com.acme:leave-core:1.0"}, "PLANNED", True, "EXECUTING", 1),
                ("environment", {"exit": 1, "stdout": "Connection refused", "report": NEW_FAIL}, "PLANNED", True, "EXECUTING", 1),
                ("preexisting_failure", {"exit": 1, "report": [LEGACY]}, "PLANNED", True, "EXECUTING", 1),
                ("unknown", {"exit": 139, "stderr": "Segmentation fault"}, "RED_RUNNING", False, "NEEDS_HUMAN", 6),
                ("unknown", {"exit": 1, "report": [[c, n, "error"] for c, n, _ in NEW_FAIL]}, "RED_RUNNING", False, "NEEDS_HUMAN", 6)]
        for i, (klass, outcome, cstate, retry, rstate, code) in enumerate(rows):
            with self.subTest(i=i, klass=klass):
                if i:
                    self.reset_ws()
                tid = self.red(outcome)
                out = self.eng.run_task(tid)
                self.assertEqual(self.evidence("red")[-1]["classification"], klass)
                self.assertEqual(self.cstate("Remaining"), cstate)
                self.assertEqual(len(self.reds()) == 2, retry)
                self.assertEqual(self.state(), rstate)
                self.assertEqual(out["exit"], code)

    def test_a_test_runner_crash_without_a_report_is_run_again_once(self):
        """Gradle died before writing its report (exit 1, no report, no compile/dependency/environment pattern): the engine
        runs the tests once more and the Red is verified from the second run; the evidence output says so."""
        crash = {"exit": 1, "stderr": "Execution failed for task ':test'. > java.io.EOFException"}
        tid = self.red({"once": crash, "exit": 1, "report": NEW_FAIL + [LEGACY]})
        self.eng.run_task(tid)
        self.assertEqual(self.cstate("Remaining"), "RED_VERIFIED")
        e = self.evidence("red")[-1]
        self.assertEqual((e["classification"], e["verdict"]), ("assertion", "accepted"))
        self.assertEqual([x["mode"] for x in self.tool_log()].count("targeted"), 2)

    def test_a_report_with_only_other_tests_counts_as_a_runner_crash(self):
        """Another Gradle run in the same build folder left a report of other tests: the run is repeated once."""
        other = {"exit": 1, "report": [["OtherTest", "unrelated", "pass"]]}
        tid = self.red({"once": other, "exit": 1, "report": NEW_FAIL + [LEGACY]})
        self.eng.run_task(tid)
        self.assertEqual(self.cstate("Remaining"), "RED_VERIFIED")
        self.assertEqual([x["mode"] for x in self.tool_log()].count("targeted"), 2)

    def test_the_engine_waits_while_another_test_run_uses_the_build_folder(self):
        import threading
        import time as _time
        import cycles
        tid = self.red({"exit": 1, "report": NEW_FAIL + [LEGACY]})
        cfg = self.eng._run_config(self.eng._get_v2(SLUG))
        repo = self.eng._repo_path(cfg, "backend")
        marker = repo / "build" / "busy.bin"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("x")
        threading.Timer(1.5, marker.unlink).start()
        orig = cycles.scopes.test_tools
        try:
            cycles.scopes.test_tools = lambda c, r: {**orig(c, r), "busy_paths": ["build/busy.bin"]}
            began = _time.time()
            self.eng.run_task(tid)
        finally:
            cycles.scopes.test_tools = orig
        self.assertGreaterEqual(_time.time() - began, 1.4)
        self.assertEqual(self.cstate("Remaining"), "RED_VERIFIED")

    def test_bookkeeping_does_not_verify_a_task_its_own_process_is_verifying(self):
        """The task's process verifies it as it finishes while the service's bookkeeping sees a COMPLETED task with no
        evidence yet. Both ran the tests at once in one build folder and Gradle crashed (EOFException, MEF-HR 2026-11-24):
        only the first verifies, the other finds the task locked and leaves it alone."""
        tid = self.red({"exit": 1, "report": NEW_FAIL + [LEGACY]})
        real = self.eng._run_tests
        seen = []

        def tests_running(cfg, repo, command, tools, tests=(), info=None):
            if tests and not seen:
                seen.append(self.eng.resume_verification(SLUG))  # bookkeeping ticks while the tests run
            return real(cfg, repo, command, tools, tests, info)
        self.eng._run_tests = tests_running
        try:
            self.eng.run_task(tid)
        finally:
            self.eng._run_tests = real
        self.assertEqual(seen, [[]])
        self.assertEqual(self.cstate("Remaining"), "RED_VERIFIED")
        self.assertEqual([x["mode"] for x in self.tool_log()].count("targeted"), 1)
        self.assertEqual([e["verdict"] for e in self.evidence("red")], ["accepted"])

    def test_a_compile_error_is_not_run_again(self):
        tid = self.red({"exit": 1, "stdout": "error: cannot find symbol"})
        self.eng.run_task(tid)
        self.assertEqual([x["mode"] for x in self.tool_log()].count("targeted"), 1)

    def test_a_resumed_run_verifies_an_unclassified_red_again(self):
        """The test runner crashed while writing its report (no report, exit 1): the run parks; once a human resumes it,
        the completed Red task is verified again instead of leaving the cycle in RED_RUNNING."""
        import machines
        tid = self.red({"exit": 1, "stderr": "Execution failed for task ':test'. > java.io.EOFException"})
        self.eng.run_task(tid)
        self.assertEqual((self.state(), self.cstate("Remaining")), ("NEEDS_HUMAN", "RED_RUNNING"))
        self.assertEqual(self.evidence("red")[-1]["verdict"], "needs_human")
        self.tool_modes(full=BASE_FULL, targeted={"exit": 1, "report": NEW_FAIL + [LEGACY]})
        self.eng.request_state(SLUG, "EXECUTING", machines.HUMAN, reason="resume")
        self.eng.resume_verification(SLUG)
        self.assertEqual(self.cstate("Remaining"), "RED_VERIFIED")
        self.assertEqual([e["verdict"] for e in self.evidence("red")], ["needs_human", "accepted"])
        self.assertEqual(self.eng.resume_verification(SLUG), [])  # accepted evidence: nothing is verified twice

    def test_AC_TDD_03f_the_retry_brief_carries_the_classified_output(self):
        tid = self.red({"exit": 1, "stdout": "RemainingBalanceTest.java:12: error: cannot find symbol"})
        self.eng.run_task(tid)
        retry = self.reds()[1]
        brief = (self.tdir(retry["id"]) / "brief.md").read_text()
        self.assertIn("compile", brief)
        self.assertIn("RemainingBalanceTest.java:12: error: cannot find symbol", brief)
        self.assertIn("attempt 2 of 3", brief)
        self.assertEqual(retry["retry_of"], tid)
        self.assertEqual(retry["attempt"], 2)
        self.assertEqual(self.task_json(retry["id"])["constraints"]["max_retries"], 2)

    def test_AC_TDD_03g_a_new_failure_outside_the_new_tests_rejects_red(self):
        tid = self.red({"exit": 1, "report": NEW_FAIL + [["BalanceServiceTest", "total", "failure"]]})
        out = self.eng.run_task(tid)
        self.assertEqual(self.cstate("Remaining"), "PLANNED")
        e = self.evidence("red")[0]
        self.assertEqual((e["verdict"], e["reason"]), ("rejected", "new failure outside the new tests: BalanceServiceTest.total"))
        self.assertEqual(len(self.reds()), 2)
        self.assertEqual(out["exit"], 1)

    def test_AC_TDD_03h_a_baseline_failure_that_now_passes_does_not_block_red(self):
        tid = self.red({"exit": 1, "report": NEW_FAIL + [["LegacyTest", "flaky", "pass"]]})
        self.eng.run_task(tid)
        self.assertEqual(self.cstate("Remaining"), "RED_VERIFIED")

    def test_AC_TDD_03i_new_tests_that_already_pass_are_refused(self):
        tid = self.red({"exit": 0, "report": NEW_PASS})
        out = self.eng.run_task(tid)
        self.assertEqual(out["exit"], 1)
        cyc = self.cycle("Remaining")
        reason = f"new tests pass before Green: {T1}, {T2}"
        self.assertEqual((cyc["state"], cyc["reason"]), ("PLANNED", reason))
        self.assertEqual(self.tdd_tasks("tdd_green", "Remaining"), [])
        self.assertIn(reason, (self.tdir(self.reds()[1]["id"]) / "brief.md").read_text())

    def test_AC_TDD_03j_one_passing_new_test_refuses_red_even_if_the_other_fails(self):
        tid = self.red({"exit": 1, "report": [NEW_FAIL[0], NEW_PASS[1]]})
        self.eng.run_task(tid)
        cyc = self.cycle("Remaining")
        self.assertEqual(cyc["state"], "PLANNED")
        self.assertIn(T2, cyc["reason"])
        self.assertNotIn(T1, cyc["reason"])

    def test_AC_TDD_03k_a_red_task_that_changes_no_test_file_is_refused(self):
        tid = self.red({"exit": 1, "report": NEW_FAIL}, body='write_result(summary="tests written")\n')
        self.eng.run_task(tid)
        cyc = self.cycle("Remaining")
        self.assertEqual((cyc["state"], cyc["reason"]), ("PLANNED", "no test file changed"))
        self.assertEqual([x["mode"] for x in self.tool_log()], ["full"])
        report = json.loads((self.tdir(tid) / "report.json").read_text())
        self.assertTrue(any("no test file changed" in json.dumps(f) for f in report["claim_flags"]), report)
        self.assertEqual(json.loads((self.tdir(tid) / "result.json").read_text())["summary"], "tests written")

    def test_AC_TDD_02a_tests_reference_their_scenarios_by_feature_path_and_name(self):
        tid = self.red({"exit": 1, "report": NEW_FAIL})
        self.eng.run_task(tid)
        cid = self.cycle("Remaining")["id"]
        pairs = sorted((r["from_id"], r["to_id"]) for r in self.links("scenario", "test"))
        self.assertEqual(pairs, sorted([(REMAINING[0], T1), (REMAINING[1], T2)]))
        self.assertEqual([(r["from_id"], r["to_id"]) for r in self.links("cycle", "test_file")], [(cid, TEST_FILE)])

    def test_AC_TDD_02b_a_binding_problem_refuses_red(self):
        rows = [([REMAINING[0]], f"scenario without test: {REMAINING[1]}"),
                (REMAINING + ["features/balance.feature :: Employee sees all days"], "unknown scenario: features/balance.feature :: Employee sees all days"),
                (REMAINING + [CARRY], f"scenario of another cycle: {CARRY}"),
                (["features/balance.feature :: employee sees remaining days", REMAINING[1]],
                 "unknown scenario: features/balance.feature :: employee sees remaining days"),
                ([], "no scenario reference found")]
        for i, (refs, reason) in enumerate(rows):
            with self.subTest(i=i):
                if i:
                    self.reset_ws()
                tid = self.red({"exit": 1, "report": NEW_FAIL}, body=refs_agent(refs))
                self.eng.run_task(tid)
                cyc = self.cycle("Remaining")
                self.assertEqual((cyc["state"], cyc["reason"]), ("PLANNED", reason))
                self.assertEqual(len(self.reds()), 2)

    def test_AC_TRC_01c_a_retried_red_replaces_its_test_links(self):
        old = ["features/balance.feature :: Employee sees remaining days", "features/balance.feature :: Balance never goes below zero"]
        tid = self.red({"exit": 1, "report": NEW_FAIL}, body=RED_OK)
        cid = self.cycle("Remaining")["id"]
        self.eng.reg.add_trace_link(self.run_row()["id"], "scenario", old[0], "test", "RemainingBalanceTest.old")
        self.eng.run_task(tid)
        got = sorted(r["to_id"] for r in self.links("scenario", "test"))
        self.assertEqual(got, sorted([T1, T2]))

    def test_AC_TDD_02c_red_cannot_edit_an_approved_scenario(self):
        body = ("p = pathlib.Path(ws, '.sentinel/shared/specs/leave-balance/features/balance.feature')\n"
                "p.write_text(p.read_text().replace('Given x', 'Given z', 1))\nwrite_result()\n")
        tid = self.red({"exit": 1, "report": NEW_FAIL}, body=body)
        out = self.eng.run_task(tid)
        self.assertEqual(out["exit"], 3)
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
        self.assertIn(".sentinel/shared/specs/leave-balance/features/balance.feature", row["reason"])
        self.assertEqual([a["state"] for a in self.approvals("gherkin")][:2], ["INVALIDATED", "IN_REVIEW"])
        self.assertEqual(self.state(), "GHERKIN_REVIEW")
        self.assertEqual(self.rules()[-1], "R18")
        cyc = self.cycle("Remaining")
        self.assertEqual((cyc["state"], cyc["reason"]), ("REJECTED", "approval invalidated"))

    def test_AC_TDD_02d_red_writes_outside_the_test_globs(self):
        rows = [("write('backend/src/main/java/leave/LeaveBalance.java', 'class X {}')", "backend/src/main/java/leave/LeaveBalance.java"),
                ("write('backend/build.gradle', 'x')", "backend/build.gradle"),
                ("subprocess.run(['git', '-C', os.path.join(ws, 'backend'), '-c', 'user.name=a', '-c', 'user.email=a@example.com', 'commit', '-qam', 'x'], check=True)"
                 if False else
                 "subprocess.run('git add -A && git -c user.name=a -c user.email=a@example.com commit -qm x', shell=True, cwd=os.path.join(ws, 'backend'), check=True)",
                 "backend: HEAD moved")]
        for i, (action, listed) in enumerate(rows):
            with self.subTest(listed=listed):
                if i:
                    self.reset_ws()
                body = RED_OK.replace("write_result()", action + "\nwrite_result()")
                tid = self.red({"exit": 1, "report": NEW_FAIL}, body=body)
                out = self.eng.run_task(tid)
                self.assertEqual(out["exit"], 3)
                row = self.task(tid)
                self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
                self.assertIn(listed, row["reason"])
                self.assertEqual([x["mode"] for x in self.tool_log()], ["full"])
                self.assertEqual(len(self.reds()), 1)
                self.assertEqual(self.cstate("Remaining"), "RED_RUNNING")
                self.assertEqual(self.state(), "NEEDS_HUMAN")

    def test_AC_TDD_06d_captured_test_output_is_scrubbed_before_it_is_stored(self):
        tid = self.red({"exit": 1, "stdout": "password=hunter2 AKIAABCDEFGHIJKLMNOP", "report": NEW_FAIL})
        self.eng.run_task(tid)
        e = self.evidence("red")[0]
        art = self.eng.reg.get_row("artifacts", e["output_artifact_id"])
        data = (self.ws / ".sentinel" / art["path"]).read_bytes()
        self.assertNotIn(b"hunter2", data)
        self.assertNotIn(b"AKIAABCDEFGHIJKLMNOP", data)
        self.assertEqual(e["output_sha256"], hashlib.sha256(data).hexdigest())
        for p in (self.ws / ".sentinel").rglob("*"):
            if p.is_file() and p.suffix in (".log", ".md", ".json"):
                self.assertNotIn(b"hunter2", p.read_bytes(), p)


class Caps(RedBase):
    def test_AC_ORC_05e_red_cap_rejects_the_cycle_and_asks_a_human(self):
        for cap, attempts in ((2, 3), (0, 1)):
            with self.subTest(cap=cap):
                if cap == 0:
                    self.reset_ws()
                tid = self.red({"exit": 0, "report": NEW_PASS}, tdd={"red_retries": cap})
                last = None
                for _ in range(attempts):
                    last = self.eng.run_task(self.next_red("Remaining"))
                self.assertEqual(len(self.reds()), attempts)
                cyc = self.cycle("Remaining")
                self.assertEqual((cyc["state"], cyc["reason"]), ("REJECTED", "red cap reached"))
                self.assertEqual(self.state(), "NEEDS_HUMAN")
                self.assertIn("Remaining", self.last_reason())
                self.assertIn("new tests pass before Green", self.last_reason())
                self.assertEqual(last["exit"], 6)

    def test_AC_ORC_05f_where_the_cap_comes_from(self):
        from tasks import retry_cap
        rows = [({"tdd": {"red_retries": 1}, "limits": {"red_retries": 4}}, 1), ({"limits": {"red_retries": 4}}, 4), ({}, 2)]
        for cfg, cap in rows:
            with self.subTest(cfg=cfg):
                self.assertEqual(retry_cap(cfg, "tdd_red"), cap)
        self.assertEqual((retry_cap({}, "tdd_green"), retry_cap({}, "tdd_refactor")), (3, 2))
        self.assertEqual(retry_cap({"tdd": {"green_retries": 0}}, "tdd_green"), 0)

    def test_AC_ORC_05g_task_failures_and_engine_rejections_share_the_phase_cap(self):
        body = "sys.exit(1)\n"
        tid = self.red({"exit": 0, "report": NEW_PASS}, body=body, tdd={"red_retries": 1})
        self.eng.run_task(tid)  # E_EXIT, retry 2
        self.assertEqual(self.cstate("Remaining"), "PLANNED")
        self.assertEqual(len(self.reds()), 2)
        self.eng.run_task(self.next_red("Remaining"))
        self.assertEqual(len(self.reds()), 2)
        self.assertEqual(self.cstate("Remaining"), "REJECTED")
        self.assertEqual(self.state(), "NEEDS_HUMAN")


if __name__ == "__main__":
    unittest.main()
