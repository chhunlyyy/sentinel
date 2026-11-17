"""Phase H part C: the release gate tools/release_gate.py (release.feature, Rule "Release gate").

These tests run the gate's functions on fixtures. They never run the gate itself (it runs this suite).
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import release_gate as gate  # noqa: E402

PHASES = ["phaseA", "phaseB", "phaseC", "phaseD", "phaseE", "phaseF", "phaseG", "phaseH", "phaseI", "phaseJ"]


def feature(ids):
    lines = ["Feature: f", ""]
    for i in ids:
        lines += [f"  @{i} @unit @P1 @cov-happy-path", f"  Scenario: s {i}", "    Then ok", ""]
    return "\n".join(lines)


class Names(unittest.TestCase):
    def test_AC_TST_01m_ids_are_read_from_test_names_of_every_suite(self):
        cases = {
            "test_AC_SEC_01l_host_header_is_checked": {"AC-SEC-01l"},
            "AC-DSH-01e no serious or critical axe violation: Overview (light)": {"AC-DSH-01e"},
            "AC-C-35a init --local-only writes auto_sync_push false": {"AC-C-35a"},
            "test_AC_TST_01a_01b_selftest": {"AC-TST-01a"},
            "test_AC_NOT_01q_and_AC_ANL_01p": {"AC-NOT-01q", "AC-ANL-01p"},
            "test_something_without_an_id": set(),
            "test_AC_SEC_01": set(),
        }
        for name, ids in cases.items():
            with self.subTest(name=name):
                self.assertEqual(gate.ids_in_name(name), ids)

    def test_AC_TST_01m_the_ids_of_the_approved_features_are_collected(self):
        with tempfile.TemporaryDirectory() as d:
            for phase, ids in {"phaseA": ["AC-ORC-01a", "AC-ORC-01b"], "phaseB": ["AC-SPA-01a"]}.items():
                (Path(d) / "plan" / "v1.1" / phase / "features").mkdir(parents=True)
                (Path(d) / "plan" / "v1.1" / phase / "features" / "x.feature").write_text(feature(ids))
            self.assertEqual(sorted(gate.approved_ac_ids(Path(d))), ["AC-ORC-01a", "AC-ORC-01b", "AC-SPA-01a"])
        real = gate.approved_ac_ids(ROOT)
        self.assertGreater(len(real), 850)
        self.assertIn("AC-TST-01m", real)

    def test_AC_TST_01m_every_ac_needs_a_passing_test(self):
        ids = ["AC-A-01a", "AC-A-01b", "AC-A-01c", "AC-A-01d", "AC-A-01e"]
        results = [
            {"suite": "unittest", "name": "test_AC_A_01a_one", "status": "passed"},
            {"suite": "unittest", "name": "test_AC_A_01b_two", "status": "failed"},
            {"suite": "unittest", "name": "test_AC_A_01b_two_again", "status": "passed"},
            {"suite": "vitest", "name": "AC-A-01d something", "status": "passed"},
        ]
        problems, covered = gate.ac_problems(ids, results, {})
        self.assertEqual(sorted(p["id"] for p in problems), ["AC-A-01b", "AC-A-01c", "AC-A-01e"])
        by = {p["id"]: p["reason"] for p in problems}
        self.assertIn("failed", by["AC-A-01b"])
        self.assertIn("no test", by["AC-A-01c"])
        self.assertEqual(sorted(covered), ["AC-A-01a", "AC-A-01d"])

    def test_AC_TST_01m_a_manual_ac_is_listed_with_its_evidence(self):
        results = [{"suite": "playwright", "name": "AC-A-01a x", "status": "skipped", "reason": "no user namespaces"}]
        problems, covered = gate.ac_problems(["AC-A-01a"], results, {"AC-A-01a": "run in CI, see IMPLEMENTATION_STATUS.md"})
        self.assertEqual(problems, [])
        self.assertEqual(covered["AC-A-01a"]["manual"], "run in CI, see IMPLEMENTATION_STATUS.md")

    def test_AC_TST_01m_a_manual_entry_without_evidence_is_refused(self):
        problems, _ = gate.ac_problems(["AC-A-01a"], [], {"AC-A-01a": ""})
        self.assertEqual([p["id"] for p in problems], ["AC-A-01a"])


class Honest(unittest.TestCase):
    """Results that prove nothing do not count for an AC."""

    def test_AC_TST_04b_an_expected_failure_counts_as_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "test_expfail.py").write_text(textwrap.dedent("""
                import unittest
                class T(unittest.TestCase):
                    @unittest.expectedFailure
                    def test_AC_X_01a_expected(self): self.fail("known")
                    @unittest.expectedFailure
                    def test_AC_X_01b_unexpected(self): pass
            """))
            r = gate.collect_unittest(Path(d), Path(d))
        by = {x["name"].split(".")[-1]: x["status"] for x in r["results"]}
        self.assertEqual(by, {"test_AC_X_01a_expected": "skipped", "test_AC_X_01b_unexpected": "failed"})
        problems, _ = gate.ac_problems(["AC-X-01a"], [{"name": "test_AC_X_01a_expected", "status": "skipped"}], {})
        self.assertEqual([p["id"] for p in problems], ["AC-X-01a"])

    def test_AC_TST_04b_a_failed_test_is_reported_with_its_reason(self):
        """On a remote runner the log is all there is: a failure must say why, not only which test."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "test_why.py").write_text(textwrap.dedent("""
                import unittest
                class T(unittest.TestCase):
                    def test_AC_X_02a_needs_a_tool(self):
                        self.assertIsNotNone(None, "uv is not installed (install it with pip install uv)")
            """))
            r = gate.collect_unittest(Path(d), Path(d))
        failed = [x for x in r["results"] if x["status"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("uv is not installed", failed[0]["reason"])
        problems, _ = gate.ac_problems(["AC-X-02a"], failed, {})
        self.assertIn("uv is not installed", problems[0]["reason"])

    def test_AC_TST_04b_playwright_test_fail_and_empty_specs_are_not_passes(self):
        report = {"suites": [{"title": "f", "specs": [
            {"title": "AC-A-01a annotated", "tests": [{"status": "expected", "expectedStatus": "failed", "annotations": [{"type": "fail"}], "results": [{"status": "failed"}]}]},
            {"title": "AC-A-01b annotated only", "tests": [{"status": "expected", "annotations": [{"type": "fail"}], "results": [{"status": "failed"}]}]},
            {"title": "AC-A-01c empty", "tests": []},
            {"title": "AC-A-01d real", "tests": [{"status": "expected", "expectedStatus": "passed", "annotations": [], "results": [{"status": "passed"}]}]},
        ]}]}
        self.assertEqual([(x["name"][:8], x["status"]) for x in gate.read_playwright(report)],
                         [("AC-A-01a", "skipped"), ("AC-A-01b", "skipped"), ("AC-A-01c", "skipped"), ("AC-A-01d", "passed")])


class Requirements(unittest.TestCase):
    def test_AC_OPS_04l_requirement_ids_in_names_match_family_and_number_exactly(self):
        self.assertEqual(gate.req_ids_in_name("test_AC_SEC_01a_REQ_INS_01_REQ_ARC_02_x"), {"INS-01", "ARC-02"})
        self.assertEqual(gate.req_ids_in_name("AC-PRJ-02a REQ-PRJ-01 the project list"), {"PRJ-01"})
        self.assertEqual(gate.req_ids_in_name("test_REQ_ARC_010_x"), {"ARC-010"})
        self.assertNotIn("ARC-01", gate.req_ids_in_name("test_REQ_ARC_010_x"))
        self.assertEqual(gate.req_ids_in_name("test_AC_X_01a_requirement_text"), set())

    def test_AC_OPS_04l_a_must_row_needs_a_passing_test_with_its_id(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "SPEC.md").write_text("## Arc\n\n| ARC-01 | MUST: a | x |\n| ARC-02 | MUST: b | x |\n| ARC-03 | MUST: c LATER G-1 | x |\n| ARC-04 | MUST: d | x |\n| ARC-05 | SHOULD: e | x |\n")
            results = [{"name": "test_REQ_ARC_01_a", "status": "passed"}, {"name": "test_REQ_ARC_02_b", "status": "failed"},
                       {"name": "test_REQ_ARC_040_d", "status": "passed"}]
            problems, used = gate.req_problems(d, results)
        self.assertEqual([p["id"] for p in problems], ["ARC-02", "ARC-04"])
        self.assertEqual(used, ["ARC-01 tested", "ARC-03 LATER"])


class Stop(unittest.TestCase):
    def test_AC_TST_04b_a_skipped_ac_test_stops_the_gate_naming_the_id(self):
        results = [
            {"suite": "unittest", "name": "test_AC_A_01a_one", "status": "passed"},
            {"suite": "unittest", "name": "test_AC_A_01b_two", "status": "skipped", "reason": "not today"},
        ]
        problems, _ = gate.ac_problems(["AC-A-01a", "AC-A-01b"], results, {})
        self.assertEqual([p["id"] for p in problems], ["AC-A-01b"])
        self.assertIn("skipped", problems[0]["reason"])
        ok, lines = gate.decide({"ac": problems})
        self.assertFalse(ok)
        self.assertTrue(any("AC-A-01b" in l for l in lines))

    def test_AC_TST_04b_the_evidence_says_release_ready_only_when_the_gate_passed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "evidence.json"
            gate.write_evidence(p, {"commit": "abc"}, False)
            self.assertNotIn("release ready", p.read_text())
            self.assertFalse(json.loads(p.read_text())["release_ready"])
            gate.write_evidence(p, {"commit": "abc"}, True)
            self.assertTrue(json.loads(p.read_text())["release_ready"])
            self.assertIn("release ready", p.read_text())

    def test_AC_TST_04b_the_exit_code_is_1_for_a_failed_gate(self):
        self.assertEqual(gate.exit_code(False), 1)
        self.assertEqual(gate.exit_code(True), 0)


class Manual(unittest.TestCase):
    def test_AC_TST_04b_manual_items_are_pending_owner_unless_done_with_a_date_and_a_machine(self):
        manual = {"A": {"evidence": "e", "status": "done", "date": "2026-11-16", "machine": "m1"},
                  "B": {"evidence": "e", "status": "done"},
                  "C": {"evidence": "e", "status": "pending"},
                  "D": "text only"}
        self.assertEqual([p["id"] for p in gate.pending_manual(manual)], ["B", "C", "D"])
        norm = gate.normalize_manual(manual)
        self.assertEqual((norm["A"]["status"], norm["B"]["status"], norm["D"]["status"]), ("done", "pending", "pending"))

    def test_AC_TST_04b_release_ready_only_when_nothing_is_pending_and_the_tree_is_clean(self):
        pending = [{"id": "X", "evidence": "e"}, {"id": "Y", "evidence": "e"}]
        self.assertEqual(gate.final_status(True, [], False), ("release ready", True))
        self.assertEqual(gate.final_status(True, pending, False), ("release candidate: 2 manual checks pending owner", False))
        self.assertEqual(gate.final_status(True, [], True), ("not releasable: dirty tree", False))
        self.assertEqual(gate.final_status(True, pending, True), ("not releasable: dirty tree", False))
        self.assertEqual(gate.final_status(False, [], False), ("not ready", False))

    def test_AC_TST_04b_the_evidence_file_never_says_release_ready_for_a_candidate_or_a_dirty_tree(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "e.json"
            gate.write_evidence(p, {"commit": "abc", "dirty": False}, True, pending=[{"id": "X", "evidence": "e"}])
            data = json.loads(p.read_text())
            self.assertEqual((data["status"], data["release_ready"]), ("release candidate: 1 manual checks pending owner", False))
            self.assertNotIn("release ready", p.read_text())
            gate.write_evidence(p, {"commit": "abc", "dirty": True}, True, allow_dirty=True)
            data = json.loads(p.read_text())
            self.assertEqual((data["status"], data["release_ready"]), ("not releasable: dirty tree", False))
            self.assertNotIn("release ready", p.read_text())

    def test_AC_TST_04b_a_dirty_tree_is_refused_and_allow_dirty_only_lets_the_gate_run(self):
        self.assertEqual(gate.tree_check(False, False), (True, None))
        proceed, msg = gate.tree_check(True, False)
        self.assertFalse(proceed)
        self.assertIn("dirty tree", msg)
        proceed, msg = gate.tree_check(True, True)
        self.assertTrue(proceed)
        self.assertIn("never releasable", msg)

    def test_AC_TST_04b_the_gate_refuses_a_dirty_tree_before_running_any_stage(self):
        real = gate.new_evidence
        gate.new_evidence = lambda: {**real(), "dirty": True}
        try:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(gate.main(["--skip-dashboard", "--skip-wheel"]), 1)
            self.assertIn("dirty tree", err.getvalue())
        finally:
            gate.new_evidence = real

    def test_AC_TST_04b_a_pending_ac_item_is_satisfied_only_by_a_passing_test(self):
        manual = {"AC-A-01a": {"evidence": "e", "status": "pending"}}
        skipped = [{"suite": "playwright", "name": "AC-A-01a x", "status": "skipped"}]
        passed = [{"suite": "playwright", "name": "AC-A-01a x", "status": "passed"}]
        self.assertEqual([p["id"] for p in gate.pending_manual(manual, skipped)], ["AC-A-01a"])
        self.assertEqual(gate.pending_manual(manual, passed), [])

    def test_AC_TST_04b_the_recorded_manual_items(self):
        data = json.loads((ROOT / "tests" / "release" / "manual.json").read_text())
        for key in ("AC-DSH-06g", "AC-OPS-01i", "G9-screen-reader"):
            self.assertIn(key, data)
        for key, v in data.items():
            with self.subTest(item=key):
                self.assertTrue(v["evidence"])
                self.assertIn(v["status"], ("pending", "done"))
                if v["status"] == "done":
                    self.assertTrue(v["date"] and v["machine"])
        # a pending item keeps its "pending owner" wording; a done item carries a date, a machine and what was run
        wording = {"AC-DSH-06g": "pending owner run on a machine that allows user namespaces (no CI exists)",
                   "AC-OPS-01i": "owner/CI to run in a loopback-only network namespace",
                   "G9-screen-reader": "screen-reader"}
        for key, text in wording.items():
            with self.subTest(wording=key):
                if data[key]["status"] == "pending":
                    self.assertIn(text, data[key]["evidence"])
                else:
                    self.assertTrue(data[key]["date"] and data[key]["machine"])
        self.assertIn("screen-reader", data["G9-screen-reader"]["evidence"])


class Hashes(unittest.TestCase):
    def test_AC_TST_01l_each_phase_still_has_its_approved_set_hash(self):
        self.assertEqual(gate.phase_hash_problems(ROOT), [])
        recorded = gate.recorded_hashes((ROOT / "IMPLEMENTATION_STATUS.md").read_text())
        self.assertEqual(sorted(recorded), PHASES)
        for phase in PHASES:
            with self.subTest(phase=phase):
                self.assertEqual(gate.set_hash(ROOT / "plan" / "v1.1" / phase / "features"), recorded[phase])

    def test_AC_TST_01l_a_changed_feature_file_is_found(self):
        with tempfile.TemporaryDirectory() as d:
            dst = Path(d)
            (dst / "plan" / "v1.1").mkdir(parents=True)
            shutil.copytree(ROOT / "plan" / "v1.1" / "phaseH", dst / "plan" / "v1.1" / "phaseH")
            (dst / "IMPLEMENTATION_STATUS.md").write_text((ROOT / "IMPLEMENTATION_STATUS.md").read_text())
            (dst / "tests" / "release").mkdir(parents=True)
            shutil.copy2(ROOT / "tests" / "release" / "phase_hashes.json", dst / "tests" / "release" / "phase_hashes.json")
            f = dst / "plan" / "v1.1" / "phaseH" / "features" / "backup.feature"
            f.write_text(f.read_text() + "\n# changed\n")
            problems = gate.phase_hash_problems(dst, phases=["phaseH"])
            self.assertEqual(len(problems), 1)
            self.assertIn("phaseH", problems[0])
            self.assertIn("Gherkin set hash", problems[0])

    def test_AC_TST_01l_the_two_recorded_hash_sources_must_agree(self):
        pinned = json.loads((ROOT / "tests" / "release" / "phase_hashes.json").read_text())
        self.assertEqual(sorted(pinned), PHASES)
        self.assertEqual(pinned, gate.recorded_hashes((ROOT / "IMPLEMENTATION_STATUS.md").read_text()))
        with tempfile.TemporaryDirectory() as d:
            dst = Path(d)
            (dst / "tests" / "release").mkdir(parents=True)
            (dst / "IMPLEMENTATION_STATUS.md").write_text((ROOT / "IMPLEMENTATION_STATUS.md").read_text())
            (dst / "tests" / "release" / "phase_hashes.json").write_text(json.dumps({**pinned, "phaseH": "0" * 64}))
            problems = gate.phase_hash_problems(dst, phases=["phaseH"])
            self.assertEqual(len(problems), 1)
            self.assertIn("must agree", problems[0])

    def test_AC_TST_01l_the_set_hash_follows_the_documented_command(self):
        f = ROOT / "plan" / "v1.1" / "phaseH"
        cmd = "find features -name '*.feature' | LC_ALL=C sort | while read f; do printf '%s\\0' \"$f\"; cat \"$f\"; printf '\\0'; done | sha256sum"
        out = subprocess.run(["bash", "-c", cmd], cwd=f, capture_output=True, text=True).stdout.split()[0]
        self.assertEqual(gate.set_hash(f / "features"), out)


class Scenarios(unittest.TestCase):
    def test_AC_TST_03a_the_core_scenarios_map_to_passing_acs(self):
        core = json.loads((ROOT / "tests" / "release" / "core14.json").read_text())
        expected = [
            "User submits a feature request", "Specification has not been approved", "Human requests specification changes",
            "Approved specification changes", "Gherkin has not been approved", "Human finds missing edge cases",
            "Approved Gherkin changes", "Both approvals are valid", "Red produces expected assertion failure",
            "Red fails due to environment", "Green modifies approved tests", "Green passes", "Refactor breaks tests",
            "More behaviors remain", "All cycles pass", "Provider is unavailable", "Agent exceeds write scope",
            "Agent claims tests passed without evidence", "Process is interrupted", "Two tasks modify overlapping files",
            "Security gate requires human approval", "Agent attempts to approve its own work",
            "Publishing is attempted without authorization",
        ]
        self.assertEqual(list(core["scenarios"]), expected)
        approved = gate.approved_ac_ids(ROOT)
        for name, ids in core["scenarios"].items():
            with self.subTest(scenario=name):
                self.assertTrue(ids)
                for i in ids:
                    self.assertIn(i, approved)

    def test_AC_TST_03a_a_scenario_with_a_failing_ac_stops_the_gate(self):
        core = {"scenarios": {"S1": ["AC-A-01a"], "S2": ["AC-A-01b", "AC-A-01c"]}}
        results = [{"suite": "unittest", "name": "test_AC_A_01a_x", "status": "passed"},
                   {"suite": "unittest", "name": "test_AC_A_01b_x", "status": "failed"}]
        problems = gate.core_problems(core, results)
        self.assertEqual([p["id"] for p in problems], ["S2"])

    def test_AC_TST_04a_the_twenty_dashboard_criteria_are_each_accounted_for(self):
        data = json.loads((ROOT / "tests" / "release" / "dashboard22.json").read_text())
        crit = data["criteria"]
        self.assertEqual(len(crit), 20)
        self.assertEqual([c["n"] for c in crit], list(range(1, 21)))
        approved = gate.approved_ac_ids(ROOT)
        for c in crit:
            with self.subTest(n=c["n"]):
                self.assertIn(c["status"], ("automated", "manual", "LATER"))
                self.assertTrue(c["text"])
                if c["status"] == "automated":
                    self.assertTrue(c["acs"])
                    for i in c["acs"]:
                        self.assertIn(i, approved)
                elif c["status"] == "manual":
                    self.assertTrue(c["evidence"])
                else:
                    self.assertIn("G-1", c["reference"])

    def test_AC_TST_04a_the_gate_copies_the_list_into_the_evidence(self):
        crit = [{"n": 1, "text": "t", "status": "automated", "acs": ["AC-A-01a"]},
                {"n": 2, "text": "u", "status": "LATER", "reference": "G-1"}]
        results = [{"suite": "unittest", "name": "test_AC_A_01a_x", "status": "passed"}]
        problems, listing = gate.dashboard_problems({"criteria": crit}, results)
        self.assertEqual(problems, [])
        self.assertEqual([c["n"] for c in listing], [1, 2])
        self.assertEqual(listing[0]["passed"], True)
        bad, _ = gate.dashboard_problems({"criteria": crit}, [])
        self.assertEqual([p["id"] for p in bad], ["criterion 1"])


class Results(unittest.TestCase):
    def test_AC_TST_01k_selftest_output_is_parsed(self):
        text = "x\n  PASS  one\n  FAIL  two  (why)\n  PASS  three\n\n2 passed, 1 failed\n"
        p = gate.parse_selftest(text)
        self.assertEqual((p["passed"], p["failed"]), (2, 1))
        self.assertEqual(p["names"], {"one": True, "two": False, "three": True})
        self.assertEqual(gate.selftest_problems(p, ["one", "missing"])[0], "selftest failed: two")

    def test_AC_TST_01k_a_missing_baseline_check_is_a_problem(self):
        p = gate.parse_selftest("  PASS  one\n\n1 passed, 0 failed\n")
        problems = gate.selftest_problems(p, ["one", "gone"])
        self.assertEqual(problems, ["selftest baseline check missing: gone"])

    def test_AC_TST_01k_unittest_results_carry_pass_skip_fail_and_subtests(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "test_x.py").write_text(textwrap.dedent("""
                import unittest
                class T(unittest.TestCase):
                    def test_AC_X_01a_pass(self): pass
                    def test_AC_X_01b_fail(self): self.fail("no")
                    @unittest.skip("because")
                    def test_AC_X_01c_skip(self): pass
                    def test_AC_X_01d_sub(self):
                        for i in range(2):
                            with self.subTest(i=i):
                                self.assertEqual(i, 0)
                    def test_AC_X_01e_error(self): raise RuntimeError("x")
            """))
            r = gate.collect_unittest(Path(d), Path(d))
        by = {x["name"].split(".")[-1]: x for x in r["results"]}
        self.assertEqual(by["test_AC_X_01a_pass"]["status"], "passed")
        self.assertEqual(by["test_AC_X_01b_fail"]["status"], "failed")
        self.assertEqual(by["test_AC_X_01c_skip"]["status"], "skipped")
        self.assertEqual(by["test_AC_X_01c_skip"]["reason"], "because")
        self.assertEqual(by["test_AC_X_01d_sub"]["status"], "failed")
        self.assertEqual(by["test_AC_X_01e_error"]["status"], "failed")
        self.assertEqual(r["ran"], 5)

    def test_AC_TST_01k_the_evidence_holds_counts_durations_and_the_commit(self):
        ev = gate.new_evidence()
        self.assertRegex(ev["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(ev["version"], "1.1.0")
        gate.record_stage(ev, "unittest", ok=True, seconds=1.5, counts={"passed": 3, "failed": 0, "skipped": 0})
        self.assertEqual(ev["stages"]["unittest"]["counts"]["passed"], 3)
        self.assertEqual(ev["stages"]["unittest"]["seconds"], 1.5)

    def test_AC_TST_01k_vitest_and_playwright_json_reports_are_read(self):
        vitest = {"testResults": [{"assertionResults": [
            {"fullName": "AC-A-01a one", "status": "passed"}, {"fullName": "AC-A-01b two", "status": "failed"}]}]}
        playwright = {"suites": [{"title": "f.spec.ts", "specs": [], "suites": [{"title": "g", "specs": [
            {"title": "AC-A-01c three", "tests": [{"status": "expected", "results": [{"status": "passed"}]}]},
            {"title": "AC-A-01d four", "tests": [{"status": "skipped", "results": [{"status": "skipped"}]}]},
            {"title": "AC-A-01e five", "tests": [{"status": "unexpected", "results": [{"status": "failed"}]}]},
            {"title": "AC-A-01f six", "tests": [{"status": "flaky", "results": [{"status": "failed"}, {"status": "passed"}]}]},
        ]}]}]}
        v = gate.read_vitest(vitest)
        self.assertEqual([(x["name"], x["status"]) for x in v], [("AC-A-01a one", "passed"), ("AC-A-01b two", "failed")])
        p = gate.read_playwright(playwright)
        self.assertEqual([(x["name"], x["status"]) for x in p],
                         [("AC-A-01c three", "passed"), ("AC-A-01d four", "skipped"), ("AC-A-01e five", "failed"), ("AC-A-01f six", "failed")])


class Suites(unittest.TestCase):
    def test_AC_TST_01i_the_package_declares_no_new_runtime_dependency(self):
        text = (ROOT / "pyproject.toml").read_text()
        self.assertIn('dependencies = ["pyyaml>=6", "jsonschema>=4"]', text)
        self.assertIn('requires-python = ">=3.10"', text)

    def test_AC_OPS_01e_the_build_is_pinned_and_the_source_hash_covers_the_build_inputs(self):
        self.assertIn('requires = ["hatchling>=1.25"]', (ROOT / "pyproject.toml").read_text())
        import importlib.util
        import types
        from unittest import mock
        stub = types.ModuleType("hatchling.builders.hooks.plugin.interface")
        stub.BuildHookInterface = object  # hatchling is a build tool, not installed for the tests
        names = ["hatchling", "hatchling.builders", "hatchling.builders.hooks", "hatchling.builders.hooks.plugin"]
        with mock.patch.dict(sys.modules, {**{n: types.ModuleType(n) for n in names}, "hatchling.builders.hooks.plugin.interface": stub}):
            spec = importlib.util.spec_from_file_location("hatch_build_under_test", ROOT / "hatch_build.py")
            hatch_build = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hatch_build)
        for name in ("package.json", "package-lock.json", "vite.config.ts", "vitest.config.ts", "eslint.config.js", "tsconfig.json", "index.html"):
            self.assertIn(name, hatch_build.SOURCE_FILES)
            self.assertIn(name, (ROOT / "dashboard" / "vite.config.ts").read_text())
            self.assertTrue((ROOT / "dashboard" / name).exists(), name)
        manifest = json.loads((ROOT / "sentinel" / "dashboard_dist" / "manifest.json").read_text())
        self.assertEqual(manifest["source_sha256"], hatch_build.source_hash(ROOT / "dashboard"))

    def test_AC_TST_01a_AC_TST_01b_AC_TST_01c_AC_TST_01d_selftest_passes_with_every_baseline_check(self):
        """The 0.1.0b7 baseline (tests/release/selftest_baseline.json) is present and the whole selftest passes."""
        r = subprocess.run([sys.executable, str(ROOT / "sentinel" / "scripts" / "selftest.py")], capture_output=True, text=True, timeout=600)
        parsed = gate.parse_selftest(r.stdout + r.stderr)
        baseline = json.loads((ROOT / "tests" / "release" / "selftest_baseline.json").read_text())
        self.assertGreaterEqual(len(baseline["checks"]), 80)
        self.assertEqual(gate.selftest_problems(parsed, baseline["checks"], baseline.get("superseded", {})), [])
        self.assertEqual(parsed["failed"], 0)
        self.assertEqual(r.returncode, 0)

    def test_AC_TST_01j_the_cli_needs_no_dashboard_assets(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = Path(d) / "pkg"
            shutil.copytree(ROOT / "sentinel", pkg / "sentinel", ignore=shutil.ignore_patterns("dashboard_dist", "__pycache__"))
            self.assertFalse((pkg / "sentinel" / "dashboard_dist").exists())
            ws = Path(d) / "ws"
            ws.mkdir()
            env = {**os.environ, "HOME": d, "PYTHONDONTWRITEBYTECODE": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
            cli = [sys.executable, str(pkg / "sentinel" / "scripts" / "sentinel.py"), "--dir", str(ws)]
            r = subprocess.run(cli[:1] + cli[1:2] + ["--version"], capture_output=True, text=True, env=env)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, (ROOT / "sentinel" / "VERSION").read_text().strip()), r.stderr)
            r = subprocess.run(cli + ["init", "--non-interactive", "--local-only", "--shape", "single"], capture_output=True, text=True, env=env, cwd=ws)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            for args, codes in ((["run", "new", "no-ui", "--type", "feature"], (0,)), (["next", "no-ui", "--json"], (0,)),
                                (["review", "no-ui", "spec"], (5,)), (["approve", "no-ui", "spec"], (5,))):
                with self.subTest(args=args):
                    r = subprocess.run(cli + args, capture_output=True, text=True, env=env, cwd=ws, stdin=subprocess.DEVNULL)
                    self.assertIn(r.returncode, codes, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
