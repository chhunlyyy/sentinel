"""Phase D review fixes (Opus review of 1.1.0 Phase D): regression tests, one class per review item."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import binding  # noqa: E402
import boundary  # noqa: E402
import classifier  # noqa: E402
import render_stage  # noqa: E402
import scopes  # noqa: E402
from errors import SentinelError  # noqa: E402
from pc_helpers import git  # noqa: E402
from pd_helpers import (CARRY_TEST, PROD, REPORT, SLUG, T1, T2, TEST_FILE, PD, PDX, all_pass, report)  # noqa: E402
from tasks import retry_cap  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXTRA_TEST = "backend/src/test/java/leave/ExtraTest.java"


def green_body(extra):
    return f"write({PROD!r}, 'class LeaveBalance {{}}\\n')\n{extra}\nwrite_result()\n"


def violations(test, tid):
    return {e["payload"]["kind"]: e["payload"]["paths"] for e in test.events("task.scope_violation") if e["task_id"] == tid}


# ---------------------------------------------------------------- 1: test files and test infrastructure are not production
class Item1TestFilesAreNotProduction(PDX):
    def test_green_cannot_write_a_test_file_when_the_globs_overlap(self):
        self.to_red_verified(repo_over={"production_globs": ["src/**"]})
        gid = self.tid("tdd_green")
        self.agent_exec("tdd_green", green_body(f"write({EXTRA_TEST!r}, 'class ExtraTest {{}}')"))
        out = self.eng.run_task(gid)
        self.assertEqual(out["exit"], 3, out)
        self.assertEqual(self.task(gid)["error_code"], "E_SCOPE")
        self.assertIn(EXTRA_TEST, violations(self, gid).get("outside_write_scope", []))

    def test_refactor_cannot_write_a_test_file_when_the_globs_overlap(self):
        self.to_green_verified(repo_over={"production_globs": ["src/**"]})
        rid = self.tid("tdd_refactor")
        self.agent_exec("tdd_refactor", f"write({EXTRA_TEST!r}, 'class ExtraTest {{}}')\nwrite_result()\n")
        self.targeted(all_pass())
        out = self.eng.run_task(rid)
        self.assertEqual(out["exit"], 3, out)
        self.assertIn(EXTRA_TEST, violations(self, rid).get("outside_write_scope", []))

    def test_root_conftest_and_runner_config_are_refused_for_green(self):
        over = {"production_globs": ["**"], "test_infra_globs": ["conftest.py", "**/conftest.py", "pytest.ini"]}
        for i, path in enumerate(["backend/conftest.py", "backend/src/main/conftest.py", "backend/pytest.ini"]):
            with self.subTest(path):
                if i:
                    self.reset_ws()
                self.to_red_verified(repo_over=over)
                gid = self.tid("tdd_green")
                self.agent_exec("tdd_green", green_body(f"write({path!r}, 'x')"))
                out = self.eng.run_task(gid)
                self.assertEqual(out["exit"], 3, out)
                self.assertIn(path, violations(self, gid).get("outside_write_scope", []))

    def test_shipped_profiles_name_test_infrastructure(self):
        want = {"python": ["conftest.py", "**/conftest.py", "pytest.ini", "tox.ini", "setup.cfg"],
                "node": ["jest.config.*", "vitest.config.*"], "nextjs": ["jest.config.*", "vitest.config.*"],
                "spring-gradle": ["build.gradle*", "settings.gradle*"], "flutter": ["dart_test.yaml"]}
        for name, globs in want.items():
            with self.subTest(name):
                got = render_stage.load_profile(name).get("test_infra_globs") or []
                for g in globs:
                    self.assertIn(g, got)

    def test_infra_classification_function(self):
        cfg = {"repos": [{"id": "r", "profile": "python"}]}
        self.assertTrue(scopes.is_test_infra(cfg, "r", "conftest.py"))
        self.assertTrue(scopes.is_test_infra(cfg, "r", "pkg/sub/conftest.py"))
        self.assertFalse(scopes.is_test_infra(cfg, "r", "pkg/app.py"))


# ---------------------------------------------------------------- 2 and 3: skipped tests, related tests, gutting
class Item23RelatedAndSkipped(PDX):
    def test_green_with_a_skipped_own_test_is_rejected_and_retried(self):
        gid = self.to_red_verified()
        cases = report("Remaining", "pass")
        cases[1][2] = "skipped"
        self.targeted(cases, exit_code=0)
        self.eng.run_task(gid)
        e = self.evidence("green")[-1]
        self.assertEqual(e["verdict"], "rejected")
        self.assertIn("skipped", e["reason"])
        self.assertEqual(self.cstate("Remaining"), "GREEN_RUNNING")
        self.assertEqual(self.tdd_tasks("tdd_green", "Remaining")[-1]["retry_of"], gid)

    def test_refactor_with_a_skipped_related_test_is_rejected(self):
        rid = self.to_green_verified()
        self.accepted_carry_over()
        self.targeted(all_pass()[:2] + [["CarryOverTest", "unusedDaysCarryOver", "skipped"]], exit_code=0)
        self.eng.run_task(rid)
        e = self.evidence("refactor")[-1]
        self.assertEqual(e["verdict"], "rejected")
        self.assertIn(CARRY_TEST, e["reason"])

    def test_refactor_with_an_absent_related_test_is_rejected(self):
        rid = self.to_green_verified()
        self.accepted_carry_over()
        self.targeted(report("Remaining", "pass"), exit_code=0)
        self.eng.run_task(rid)
        e = self.evidence("refactor")[-1]
        self.assertEqual(e["verdict"], "rejected")
        self.assertIn(CARRY_TEST, e["reason"])

    def test_green_runs_the_related_tests_too(self):
        gid = self.to_red_verified()
        self.accepted_carry_over()
        self.targeted(all_pass(), exit_code=0)
        self.eng.run_task(gid)
        self.assertEqual(self.tool_log()[-1]["args"], [T1, T2, CARRY_TEST])
        self.assertEqual(self.cstate("Remaining"), "GREEN_VERIFIED")

    def test_a_later_red_that_guts_an_earlier_accepted_test_is_rejected(self):
        self.to_accepted("Remaining")
        carry = self.tid("tdd_red", "Carry")
        carry_fail = [["CarryOverTest", "unusedDaysCarryOver", "failure"]]
        self.targeted(carry_fail)  # the earlier tests are absent from the run: gutted
        self.eng.run_task(carry)
        e = self.evidence("red", label="Carry")[-1]
        self.assertEqual(e["verdict"], "rejected", e["reason"])
        self.assertIn(T1, e["reason"])
        self.assertEqual(self.cstate("Carry"), "PLANNED")
        self.targeted(carry_fail + report("Remaining", "pass"))  # the retry keeps them
        self.eng.run_task(self.tid("tdd_red", "Carry"))
        self.assertEqual(self.cstate("Carry"), "RED_VERIFIED")
        self.assertEqual(self.tool_log()[-1]["args"], [CARRY_TEST, T1, T2])

    def test_a_later_red_whose_earlier_test_is_skipped_or_failing_is_rejected(self):
        self.to_accepted("Remaining")
        carry_fail = [["CarryOverTest", "unusedDaysCarryOver", "failure"]]
        for i, status in enumerate(("skipped", "failure")):
            with self.subTest(status):
                earlier = report("Remaining", "pass")
                earlier[0][2] = status
                self.targeted(carry_fail + earlier)
                self.eng.run_task(self.tid("tdd_red", "Carry"))
                e = self.evidence("red", label="Carry")[-1]
                self.assertEqual(e["verdict"], "rejected")
                self.assertIn(T1, e["reason"])

    def test_classifier_related_tests(self):
        cl = classifier.classify(1, "", [("A.new", "failure"), ("A.old", "skipped")], {}, new_tests=["A.new"],
                                 related_tests=["A.old", "A.gone"])
        self.assertEqual((cl["related_skipped"], cl["related_absent"]), (["A.old"], ["A.gone"]))
        verdict, reason = classifier.verify_red(cl, ["A.new"])
        self.assertEqual(verdict, "rejected")
        self.assertIn("A.gone", reason)


# ---------------------------------------------------------------- 4: selectors per profile
class Item4Selectors(unittest.TestCase):
    INFO = {"a.TestOne.t_one": {"file": "tests/test_a.py", "class": "TestOne", "method": "t_one"},
            "b.t_two": {"file": "tests/test_b.py", "class": None, "method": "t_two"},
            "c.t_three": {"file": "tests/test_c.py", "class": None, "method": "t_three"}}

    def render(self, profile, ids, info=None):
        import testsel
        tools = {k: render_stage.load_profile(profile).get(k) for k in ("targeted_test", "selector", "selector_join", "test_report")}
        return testsel.render(tools, ids, info or self.INFO, "/tmp/rd")

    def test_python_pytest_node_ids(self):
        one = self.render("python", ["b.t_two"])
        self.assertIn("pytest", one)
        self.assertIn("tests/test_b.py::t_two", one)
        self.assertIn("--junitxml=/tmp/rd/junit.xml", one)
        three = self.render("python", ["a.TestOne.t_one", "b.t_two", "c.t_three"])
        for node in ("tests/test_a.py::TestOne::t_one", "tests/test_b.py::t_two", "tests/test_c.py::t_three"):
            self.assertIn(node, three)

    def test_spring_gradle_repeats_tests_per_id(self):
        info = {"RemainingBalanceTest.one": {"file": "x", "class": "RemainingBalanceTest", "method": "one"},
                "RemainingBalanceTest.two": {"file": "x", "class": "RemainingBalanceTest", "method": "two"},
                "CarryTest.three": {"file": "y", "class": "CarryTest", "method": "three"}}
        one = self.render("spring-gradle", ["CarryTest.three"], info)
        self.assertEqual(one.count("--tests"), 1)
        three = self.render("spring-gradle", list(info), info)
        self.assertEqual(three.count("--tests"), 3)
        self.assertIn("RemainingBalanceTest.two", three)

    def test_jest_profiles_use_a_name_pattern_and_the_junit_dir(self):
        for profile in ("node", "nextjs"):
            with self.subTest(profile):
                one = self.render(profile, ["b.t_two"])
                self.assertIn("-t", one)
                self.assertIn("t_two", one)
                self.assertIn("tests/test_b.py", one)
                three = self.render(profile, list(self.INFO))
                self.assertIn("t_one|t_two|t_three", three)
                self.assertIn("JEST_JUNIT_OUTPUT_DIR=/tmp/rd", three)

    def test_flutter_uses_name_pattern_and_converts_to_junit(self):
        one = self.render("flutter", ["b.t_two"])
        self.assertIn("--name", one)
        self.assertIn("t_two", one)
        self.assertIn("tojunit", one)
        three = self.render("flutter", list(self.INFO))
        self.assertIn("t_one|t_two|t_three", three)
        self.assertIn("/tmp/rd/junit.xml", three)

    def test_profile_report_paths_are_usable(self):
        self.assertTrue(render_stage.load_profile("python")["test_report"]["path"].startswith("{report_dir}"))
        self.assertTrue(render_stage.load_profile("spring-gradle")["test_report"]["path"].startswith("build/test-results/test/"))

    def test_unsafe_name_is_refused(self):
        import testsel
        with self.assertRaises(ValueError):
            testsel.render({"targeted_test": "x {selectors}", "selector": "'{test}'"}, ["a.b'; rm -rf x"],
                           {"a.b'; rm -rf x": {"file": "f", "class": None, "method": "b'; rm -rf x"}}, "/tmp")

    def test_binding_records_file_class_and_method(self):
        text = '# @Scenario("f :: s")\ndef test_one():\n  pass\nclass TestA:\n  # @Scenario("f :: t")\n  def test_two(self):\n    pass\n'
        info = binding.test_info(text, '@Scenario\\("([^"]+)"\\)', "tests/test_x.py")
        self.assertEqual(info["test_x.test_one"], {"file": "tests/test_x.py", "class": None, "method": "test_one"})
        self.assertEqual(info["TestA.test_two"], {"file": "tests/test_x.py", "class": "TestA", "method": "test_two"})


@unittest.skipUnless(__import__("importlib").util.find_spec("pytest"), "pytest is not installed")
class Item4RealPytest(PD):
    TEST_BODY = f'''
write("backend/tests/test_balance.py", """# @Scenario("{'features/balance.feature :: Employee sees remaining days'}")
def test_employee_sees_remaining_days():
    assert 1 == 2


class TestBalance:
    # @Scenario("{'features/balance.feature :: Balance never goes below zero'}")
    def test_never_below_zero(self):
        assert False
""")
write_result()
'''

    def test_red_end_to_end_with_real_pytest(self):
        prof = render_stage.load_profile("python")
        py = f"{sys.executable} -m pytest"
        (self.ws / "backend" / "tests").mkdir(exist_ok=True)
        (self.ws / "backend" / "tests" / "test_existing.py").write_text("def test_existing():\n    assert True\n")
        git(self.ws / "backend", "add", "-A")
        git(self.ws / "backend", "commit", "-q", "-m", "existing test")
        over = {"profile": "python", "test_globs": prof["test_globs"], "production_globs": ["src/**"],
                "commands": {"test": f"{py} -p no:cacheprovider --junitxml={{report_dir}}/junit.xml"},
                "targeted_test": prof["targeted_test"].replace("pytest", py, 1), "selector": prof["selector"],
                "test_report": prof["test_report"], "failure_patterns": prof["failure_patterns"],
                "scenario_ref": prof["scenario_ref"]}
        self.boot_exec(agent_body=self.TEST_BODY, repo_over=over, tdd={"red_retries": 1})
        self.prepare()
        out = self.eng.run_task(self.next_red("Remaining"))
        self.assertEqual(self.cstate("Remaining"), "RED_VERIFIED", (out, self.evidence("red")))
        e = self.evidence("red")[-1]
        self.assertEqual((e["verdict"], e["classification"], e["failed"]), ("accepted", "assertion", 2))
        self.assertEqual(sorted(json.loads(self.cycle("Remaining")["tests"])),
                         ["TestBalance.test_never_below_zero", "test_balance.test_employee_sees_remaining_days"])


# ---------------------------------------------------------------- 5: agent-writable ignore rules
class Item5IgnoreRules(PDX):
    def red_body(self, action):
        return f"write({TEST_FILE!r}, 'class RemainingBalanceTest {{}}')\n{action}\nwrite_result()\n"

    def run_red_with(self, action, **kw):
        self.boot_x(**kw)
        self.prepare()
        self.agent_exec("tdd_red", self.red_body(action))
        tid = self.tid("tdd_red")
        out = self.eng.run_task(tid)
        return tid, out

    def test_git_info_exclude_change_is_a_violation(self):
        tid, out = self.run_red_with("open(os.path.join(ws, 'backend/.git/info/exclude'), 'a').write('src/test/java/leave/Hidden*\\n')\n"
                                     "write('backend/src/test/java/leave/HiddenTest.java', 'x')")
        self.assertEqual(out["exit"], 3, out)
        self.assertIn("backend/.git/info/exclude", self.task(tid)["reason"])

    def test_nested_gitignore_change_is_a_violation(self):
        tid, out = self.run_red_with("write('backend/src/test/java/leave/.gitignore', 'Hidden*')\n"
                                     "write('backend/src/test/java/leave/HiddenTest.java', 'x')")
        self.assertEqual(out["exit"], 3, out)
        self.assertIn(".gitignore", self.task(tid)["reason"])

    def test_ignored_file_matching_production_globs_is_checked(self):
        (self.ws / "backend" / ".gitignore").write_text("build/\nsrc/test/gen/\n")
        git(self.ws / "backend", "add", "-A")
        git(self.ws / "backend", "commit", "-q", "-m", "ignore gen")
        self.to_red_verified()
        gid = self.tid("tdd_green")
        self.agent_exec("tdd_green", green_body("write('backend/src/test/gen/HiddenTest.java', 'x')"))
        out = self.eng.run_task(gid)
        self.assertEqual(out["exit"], 3, out)
        self.assertIn("backend/src/test/gen/HiddenTest.java", violations(self, gid).get("outside_write_scope", []))

    def test_heavy_ignored_dir_change_is_noticed(self):
        (self.ws / "backend" / ".gitignore").write_text("build/\nnode_modules/\n")
        git(self.ws / "backend", "add", "-A")
        git(self.ws / "backend", "commit", "-q", "-m", "ignore modules")
        (self.ws / "backend" / "node_modules" / "pkg").mkdir(parents=True)
        (self.ws / "backend" / "node_modules" / "pkg" / "index.js").write_text("1")
        tid, out = self.run_red_with("write('backend/node_modules/pkg/evil.js', 'x')")
        self.assertEqual(out["exit"], 3, out)
        self.assertIn("node_modules", self.task(tid)["reason"])

    def test_changed_state_lists_ignored_files_matching_globs(self):
        repo = self.ws / "backend"
        (repo / ".gitignore").write_text("build/\ngen/\n")
        (repo / "gen").mkdir()
        (repo / "gen" / "A.java").write_text("x")
        (repo / "gen" / "notes.txt").write_text("x")
        state = boundary.changed_state(repo, lambda n: scopes.glob_match("gen/**", n) and n.endswith(".java"))
        self.assertIn("gen/A.java", state["paths"])
        self.assertNotIn("gen/notes.txt", state["paths"])
        self.assertNotIn("gen/A.java", boundary.changed_state(repo)["paths"])


# ---------------------------------------------------------------- 6: renamed or removed Rule
class Item6RenamedRule(PDX):
    def edit_and_reapprove(self, old, new):
        p = self.sdir() / "features" / "balance.feature"
        p.write_text(p.read_text().replace(old, new))
        self.eng.load_run(SLUG)
        self.assertEqual(self.state(), "GHERKIN_REVIEW")
        self.approve("gherkin")
        self.eng.advance(SLUG)
        self.assertEqual(self.state(), "EXECUTING")

    def test_renamed_rule_leaves_no_orphan_cycle(self):
        self.boot_x()
        self.prepare()
        self.edit_and_reapprove("Rule: Carry-over", "Rule: Carried days")
        live = [c["behavior"] for c in self.eng.live_cycles(self.run_row())]
        self.assertTrue(any("Carried days" in b for b in live), live)
        self.assertFalse(any("Carry-over" in b for b in live), live)
        for c in self.eng.live_cycles(self.run_row()):
            self.set_cycle(c["behavior"], state="CYCLE_ACCEPTED", tests=[T1])
        self.assertTrue(self.eng.check_r13(SLUG))
        self.assertEqual(self.state(), "VERIFYING")
        self.assertTrue([c for c in self.cycles() if "Carry-over" in c["behavior"]])  # history stays

    def test_removed_rule_leaves_no_orphan_cycle(self):
        self.boot_x()
        self.prepare()
        self.edit_and_reapprove("  Rule: Carry-over\n\n", "")  # its scenario now belongs to the Rule above
        live = [c["behavior"] for c in self.eng.live_cycles(self.run_row())]
        self.assertFalse(any("Carry-over" in b for b in live), live)
        for c in self.eng.live_cycles(self.run_row()):
            self.set_cycle(c["behavior"], state="CYCLE_ACCEPTED", tests=[T1])
        self.assertTrue(self.eng.check_r13(SLUG))

    def test_an_orphan_does_not_block_a_later_red(self):
        self.boot_x()
        self.prepare()
        self.edit_and_reapprove("Rule: Remaining balance", "Rule: Balance left")
        self.prepare()
        red = [t for t in self.eng.reg.rows("tasks", run_id=self.run_row()["id"], role="tdd_red") if t["state"] == "QUEUED"]
        self.assertTrue(red)


# ---------------------------------------------------------------- 7: E_SCOPE dead end, retry and cancel hooks
class Item7CycleRetry(PDX):
    def scope_fail_green(self, **kw):
        gid = self.to_red_verified(**kw)
        self.agent_exec("tdd_green", green_body(f"write({TEST_FILE!r}, 'changed')\nwrite({EXTRA_TEST!r}, 'x')"))
        out = self.eng.run_task(gid)
        self.assertEqual(out["exit"], 3, out)
        return gid

    def restore_approved(self, text):
        (self.ws / TEST_FILE).write_text(text)
        (self.ws / EXTRA_TEST).unlink(missing_ok=True)

    def test_resume_after_a_scope_violation_retries_the_cycle_task(self):
        gid = self.to_red_verified()
        original = (self.ws / TEST_FILE).read_text()
        self.agent_exec("tdd_green", green_body(f"write({TEST_FILE!r}, 'changed')\nwrite({EXTRA_TEST!r}, 'x')"))
        self.assertEqual(self.eng.run_task(gid)["exit"], 3)
        self.restore_approved(original)
        self.agent_exec("tdd_green", green_body("pass"))
        self.eng.request_state(SLUG, "EXECUTING", "human", reason="reverted")
        self.assertEqual(self.state(), "EXECUTING")
        tasks = self.tdd_tasks("tdd_green", "Remaining")
        self.assertEqual(len(tasks), 2)
        retry = tasks[-1]
        self.assertEqual((retry["retry_of"], retry["state"], retry["attempt"]), (gid, "QUEUED", 2))
        self.assertEqual(self.cycle("Remaining")["green_task"], retry["id"])
        self.assertEqual(self.cstate("Remaining"), "GREEN_RUNNING")
        self.assertIn(TEST_FILE, self.task_json(retry["id"])["permissions"]["readonly_approved"])
        step = self.eng.next_step(SLUG)
        self.assertEqual((step["kind"], step["task"]), ("task", retry["id"]))
        self.targeted(all_pass())
        self.eng.run_task(retry["id"])
        self.assertEqual(self.cstate("Remaining"), "GREEN_VERIFIED")

    def test_unreverted_violation_paths_refuse_the_retry_and_list_them(self):
        gid = self.scope_fail_green()
        with self.assertRaises(SentinelError) as cm:
            self.eng.retry_cycle_task(gid, "human")
        self.assertEqual(cm.exception.code, "E_PRECONDITION")
        self.assertIn(EXTRA_TEST, cm.exception.message)
        self.assertEqual(len(self.tdd_tasks("tdd_green", "Remaining")), 1)
        self.eng.request_state(SLUG, "EXECUTING", "human", reason="again")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertIn(EXTRA_TEST, self.last_reason())

    def test_red_scope_violation_retry_returns_the_cycle_to_planned(self):
        self.boot_x()
        self.prepare()
        self.agent_exec("tdd_red", f"write({PROD!r}, 'x')\nwrite_result()\n")
        rid = self.tid("tdd_red")
        self.assertEqual(self.eng.run_task(rid)["exit"], 3)
        self.assertEqual(self.cstate("Remaining"), "RED_RUNNING")
        (self.ws / PROD).unlink()
        retry = self.eng.retry_cycle_task(rid, "human")
        self.assertEqual(self.cstate("Remaining"), "PLANNED")
        self.assertEqual(self.cycle("Remaining")["red_task"], retry["id"] if isinstance(retry, dict) else retry)

    def test_cap_and_wrong_state_are_refused(self):
        gid = self.to_red_verified(tdd={"green_retries": 0})
        self.agent_exec("tdd_green", green_body(f"write({EXTRA_TEST!r}, 'x')"))
        self.eng.run_task(gid)
        (self.ws / EXTRA_TEST).unlink()
        with self.assertRaises(SentinelError) as cm:
            self.eng.retry_cycle_task(gid, "human")
        self.assertEqual(cm.exception.code, "E_PRECONDITION")
        self.assertIn("cap", cm.exception.message)
        self.set_cycle("Remaining", state="CYCLE_ACCEPTED")
        with self.assertRaises(SentinelError) as cm:
            self.eng.retry_cycle_task(gid, "human")
        self.assertEqual(cm.exception.code, "E_PRECONDITION")

    def test_cancelling_a_running_cycle_task_moves_the_cycle_back(self):
        rows = [("tdd_red", "RED_RUNNING", "PLANNED"), ("tdd_green", "GREEN_RUNNING", "RED_VERIFIED"),
                ("tdd_refactor", "REFACTOR_RUNNING", "GREEN_VERIFIED")]
        for i, (role, running, before) in enumerate(rows):
            with self.subTest(role):
                if i:
                    self.reset_ws()
                self.to_green_verified()
                tid = self.tid(role)
                self.set_cycle("Remaining", state=running)
                self.mark_running(tid)
                self.eng.cancel_task(tid, "human")
                self.assertEqual(self.cstate("Remaining"), before)
                again = self.eng.retry_cycle_task(tid, "human")
                self.assertEqual(self.task(again["id"] if isinstance(again, dict) else again)["attempt"], 2)


# ---------------------------------------------------------------- 8: re-hash approved tests at verification and acceptance
class Item8Rehash(PDX):
    def test_a_human_edit_of_an_approved_test_before_green_verification_is_an_integrity_failure(self):
        gid = self.to_red_verified()
        self.agent_exec("tdd_green", green_body("open('/dev/null')"))
        real = self.eng._check_approved_tests
        self.eng._check_approved_tests = lambda run, task: None  # the edit happens after the dispatch check
        (self.ws / TEST_FILE).write_text("tampered")
        try:
            self.targeted(all_pass())
            self.eng.run_task(gid)
        finally:
            self.eng._check_approved_tests = real
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertIn("approved test file changed", self.last_reason())
        self.assertEqual(self.evidence("green"), [])
        self.assertEqual(self.cstate("Remaining"), "GREEN_RUNNING")


# ---------------------------------------------------------------- 9: report forgery
class Item9Report(PD):
    FORGED = ("write('backend/build/test-results/test/TEST-forged.xml', "
              "'<testsuite><testcase classname=\"leave.RemainingBalanceTest\" name=\"employeeSeesRemainingDays\"/></testsuite>')\n")

    def test_report_is_read_from_the_engine_dir_and_a_forged_repo_file_is_ignored(self):
        body = f"write({TEST_FILE!r}, '''class RemainingBalanceTest {{\n  @Scenario(\"features/balance.feature :: Employee sees remaining days\")\n  void employeeSeesRemainingDays() {{}}\n" \
               f"  @Scenario(\"features/balance.feature :: Balance never goes below zero\")\n  void balanceNeverBelowZero() {{}}\n}}''')\n{self.FORGED}write_result()\n"
        fails = [["RemainingBalanceTest", "employeeSeesRemainingDays", "failure"], ["RemainingBalanceTest", "balanceNeverBelowZero", "failure"]]
        self.boot_exec(agent_body=body, tool={"full": {"exit": 0, "report": [], "extra_passed": 2}, "targeted": {"exit": 1, "report": fails}},
                       repo_over={"test_report": {"kind": "junit-xml", "path": "{report_dir}/*.xml"},
                                  "targeted_test": f"{sys.executable} {self.ws / self.BIN / 'faketest'} targeted --report-dir={{report_dir}} {{tests}}"})
        self.prepare()
        self.eng.run_task(self.next_red("Remaining"))
        self.assertEqual(self.cstate("Remaining"), "RED_VERIFIED", self.evidence("red"))
        e = self.evidence("red")[-1]
        self.assertEqual((e["verdict"], e["failed"]), ("accepted", 2))
        cmd = e["command"]
        self.assertNotIn("{report_dir}", cmd)

    def test_report_path_guard(self):
        base = self.ws / "backend"
        (self.ws / "other").mkdir(exist_ok=True)
        (self.ws / "other" / "x.xml").write_text("<testsuite/>")
        self.assertEqual(classifier.report_files(base, {"path": "../other/*.xml"}), [])
        self.assertEqual(classifier.report_files(base, {"path": str(self.ws / "other" / "*.xml")}), [])
        self.assertIsNone(classifier.read_report(base, {"kind": "junit-xml", "path": "../other/*.xml"}))

    def test_clear_report_only_touches_its_own_tree(self):
        base = self.ws / "backend"
        outside = self.ws / "other" / "x.xml"
        outside.parent.mkdir(exist_ok=True)
        outside.write_text("<testsuite/>")
        classifier.clear_report(base, {"path": "../other/*.xml"})
        self.assertTrue(outside.exists())

    def test_summary_pattern_cross_check(self):
        pats = {}
        summary = ["(?P<passed>\\d+) passed", "(?P<failed>\\d+) failed"]
        ok = classifier.classify(1, "1 failed, 1 passed in 0.1s", [("A.x", "failure"), ("A.y", "pass")], pats, new_tests=["A.x"],
                                 summary_patterns=summary)
        self.assertEqual(ok["classification"], "assertion")
        lie = classifier.classify(0, "1 failed, 1 passed in 0.1s", [("A.x", "pass"), ("A.y", "pass")], pats, new_tests=["A.x"],
                                  summary_patterns=summary)
        self.assertEqual(lie["classification"], "unknown")


# ---------------------------------------------------------------- 10: assertion pattern per test message
class Item10PerTestMessage(unittest.TestCase):
    def test_pattern_is_matched_against_each_errors_message(self):
        pats = {"assertion": ["AttributeError"]}
        cases = [("A.one", "error", "AttributeError: no attribute"), ("A.two", "error", "boom")]
        got = classifier.classify(1, "AttributeError: somewhere in the output", cases, pats, new_tests=["A.one", "A.two"])
        self.assertEqual(got["new_failing"], ["A.one"])
        self.assertEqual(got["classification"], "unknown")

    def test_junit_messages_are_parsed(self):
        xml = '<testsuite><testcase classname="p.A" name="x"><error message="AttributeError: m">tb</error></testcase></testsuite>'
        self.assertEqual(classifier.parse_junit_cases(xml), [("A.x", "error", "AttributeError: m\ntb")])
        self.assertEqual(classifier.parse_junit(xml), [("A.x", "error")])


# ---------------------------------------------------------------- 11: _owned_elsewhere scope
class Item11OwnedElsewhere(PDX):
    def test_another_runs_task_does_not_own_a_path(self):
        gid = self.to_red_verified()
        run2 = "other-run"
        self.mk(run2, "EXECUTING", 3)
        tid = self.eng.create_task(run2, "docs", "docs", repos=["backend"], write=["backend/docs/**"])["id"]
        self.eng.queue_task(tid)
        self.eng.start_task(tid, schedule=False)
        self.agent_exec("tdd_green", green_body("write('backend/docs/x.md', 'x')"))
        out = self.eng.run_task(gid)
        self.assertEqual(out["exit"], 3, out)
        self.assertIn("backend/docs/x.md", violations(self, gid).get("outside_write_scope", []))


# ---------------------------------------------------------------- 12: retry cap order
class Item12RetryCap(unittest.TestCase):
    def test_agent_max_retries_does_not_apply_to_tdd_roles(self):
        cfg = {"agents": {"tdd_red": {"max_retries": 9}, "coder": {"max_retries": 7}}, "tdd": {"red_retries": 1}}
        self.assertEqual(retry_cap(cfg, "tdd_red"), 1)
        self.assertEqual(retry_cap({"agents": {"tdd_red": {"max_retries": 9}}}, "tdd_red"), 2)
        self.assertEqual(retry_cap({"agents": {"tdd_red": {"max_retries": 9}}, "limits": {"red_retries": 4}}, "tdd_red"), 4)
        self.assertEqual(retry_cap(cfg, "coder"), 7)


# ---------------------------------------------------------------- 13: the Green prompt matches the checks
class Item13Prompt(PDX):
    def test_green_prompt_names_related_tests_and_the_skip_rule(self):
        text = (Path(render_stage.__file__).parent.parent / "core" / "stages" / "tdd_green.md").read_text()
        self.assertIn("{{related_tests}}", text)
        self.assertIn("skipped", text)


# ---------------------------------------------------------------- 14: cleanup
class Item14Cleanup(PDX):
    def test_dead_code_is_gone(self):
        self.boot_x()
        self.assertFalse(hasattr(self.eng, "scope_for"))
        self.assertFalse(hasattr(self.eng, "tdd_tools"))
        self.assertFalse(hasattr(self.eng, "_flag_claim"))

    def test_changed_files_has_a_cycle_index(self):
        self.boot_x()
        rows = self.sql("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='changed_files'")
        cols = {r[0] for r in rows}
        self.assertIn("idx_changed_files_cycle", cols)

    def test_several_repo_tags_on_one_rule_is_a_planning_problem(self):
        from pd_helpers import default_features
        files = default_features()
        files["balance.feature"] = files["balance.feature"].replace("Rule: Carry-over", "@repo-backend @repo-frontend\n  Rule: Carry-over")
        self.boot_pd(features=files, repos=("backend", "frontend"))
        with self.assertRaises(SentinelError) as cm:
            self.eng.advance(SLUG)
        self.assertIn("repo tags", str(cm.exception))
        self.assertEqual(self.state(), "NEEDS_HUMAN")


if __name__ == "__main__":
    unittest.main()
