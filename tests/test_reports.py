"""Phase E: `sentinel report` (reports.feature)."""
import hashlib
import json
import unittest

from pe_helpers import PE, SLUG

SECTIONS = ["execution", "specification", "gherkin", "agents", "cycles", "verification", "regression", "findings", "changed_files",
            "acceptance", "trace", "cost"]


class Reports(PE):
    def rpath(self, name="report.json"):
        return self.ws / ".sentinel/runs" / SLUG / name

    def reported(self):
        """Two tasks report tokens and cost, the others none; provider and model are set."""
        done = [t for t in self.new_tasks()]
        for i, t in enumerate(done):
            fields = {"provider": "fake", "model": "fake-model"}
            if i < 2:
                fields.update(tokens=100 * (i + 1), cost=0.5 * (i + 1))
            self.eng.reg.update_row("tasks", t["id"], **fields)

    def test_AC_ART_01e_report_json_holds_every_section(self):
        self.to_completed()
        code, out, err = self.cli("report", SLUG, "--json")
        self.assertEqual(code, 0, out + err)
        rep = json.loads(self.rpath().read_text())
        self.assertEqual(list(rep), SECTIONS)
        self.assertEqual(json.loads(out[:out.rindex("}") + 1]), rep)
        for key in ("specification", "gherkin"):
            self.assertEqual(sorted(rep[key]), ["approver", "decided_at", "decision", "sha256", "version"])
        self.assertEqual(rep["acceptance"]["human"]["status"], "pending")
        self.assertEqual(rep["acceptance"]["computed"], "accepted")
        for a in rep["agents"]:
            for k in ("role", "adapter", "provider", "model", "attempt", "state", "error_code", "started_at", "finished_at"):
                self.assertIn(k, a)
        self.assertEqual(len(rep["agents"]), len(self.tasks_of()))

    def test_AC_ART_01f_report_md_is_rendered_from_report_json(self):
        self.to_completed()
        code, out, err = self.cli("report", SLUG)
        self.assertEqual(code, 0, out + err)
        md = self.rpath("report.md").read_text()
        heads = [l[3:] for l in md.splitlines() if l.startswith("## ")]
        self.assertEqual(heads, SECTIONS)
        raw = self.rpath().read_text()
        import re
        for sha in re.findall(r"\b[0-9a-f]{64}\b", md):
            self.assertIn(sha, raw)
        self.assertEqual(out.strip().splitlines()[-2:], [str(self.rpath()), str(self.rpath("report.md"))])

    def test_AC_ART_01g_the_report_is_reproducible(self):
        self.to_completed()
        self.cli("report", SLUG)
        first = hashlib.sha256(self.rpath().read_bytes()).hexdigest()
        self.cli("report", SLUG)
        self.assertEqual(hashlib.sha256(self.rpath().read_bytes()).hexdigest(), first)
        rep = json.loads(self.rpath().read_text())
        self.assertIsInstance(rep["execution"]["last_event_id"], int)
        self.assertNotIn("generated_at", self.rpath().read_text())

    def test_AC_ART_01h_the_report_is_registered_as_an_artifact(self):
        self.to_completed()
        before = (self.run_row()["state"], self.run_row()["acceptance_status"], [t["state"] for t in self.tasks_of()])
        self.cli("report", SLUG)
        arts = self.artifacts("report")
        self.assertEqual(arts[-1]["sha256"], hashlib.sha256(self.rpath().read_bytes()).hexdigest())
        self.assertEqual(before, (self.run_row()["state"], self.run_row()["acceptance_status"], [t["state"] for t in self.tasks_of()]))

    def test_AC_ANL_02a_unreported_cost_is_null_with_a_reason(self):
        self.to_completed()
        self.reported()
        rep = self.eng.build_report(SLUG)
        by = rep["agents"]
        new = [a for a in by if a["id"] in {t["id"] for t in self.new_tasks()}]
        self.assertEqual([a["cost"] for a in new[:2]], [0.5, 1.0])
        for a in new[2:]:
            self.assertEqual((a["tokens"], a["cost"], a["cost_reason"]), (None, None, "not reported by provider"))
        self.assertEqual(rep["cost"]["cost"], 1.5)
        self.assertTrue(rep["cost"]["partial"])
        self.assertGreater(rep["cost"]["unreported_tasks"], 0)
        self.eng.write_report(SLUG)
        self.assertIn("not reported", self.rpath("report.md").read_text())

    def test_AC_ANL_02b_an_unfinished_run_marks_later_sections_not_reached(self):
        self.boot_ver()
        self.set_state("EXECUTING")
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("DELETE FROM verification_rounds")
        code, out, err = self.cli("report", SLUG, "--json")
        self.assertEqual(code, 0, out + err)
        rep = json.loads(self.rpath().read_text())
        for k in ("verification", "findings", "acceptance"):
            self.assertEqual(rep[k]["status"], "not reached")
        self.assertEqual(rep["acceptance"]["acceptance_status"], "pending")
        self.assertEqual(len(rep["cycles"]), 3)

    def test_AC_VER_02d_claims_that_disagree_with_evidence_are_flagged(self):
        self.to_completed()
        task = self.tasks_of()[0]
        self.eng.reg.update_row("tasks", task["id"], changed_files=json.dumps(["backend/src/main/java/leave/Balance.java"]))
        self.tdir(task["id"]).mkdir(parents=True, exist_ok=True)
        self.write_result(task["id"], claimed_changed_files=["backend/src/main/java/leave/Balance.java", "backend/src/main/java/leave/Policy.java"])
        rep = self.eng.build_report(SLUG)
        agent = [a for a in rep["agents"] if a["id"] == task["id"]][0]
        self.assertEqual(agent["claim_flags"], [{"path": "backend/src/main/java/leave/Policy.java", "flag": "not in evidence"}])
        self.assertEqual([c["files"] for c in rep["changed_files"] if c["task"] == task["id"]], [["backend/src/main/java/leave/Balance.java"]])

    def test_AC_VER_02e_regression_compares_the_full_suite_with_the_baseline(self):
        self.to_ready()
        run = self.run_row()
        with self.eng.reg.transaction():
            self.eng.reg.insert_row("evidence", {"run_id": run["id"], "kind": "baseline", "repo_id": "backend", "classification": "assertion",
                                                 "failing": json.dumps(["LegacyTest.flaky", "OldTest.broken"])})
            self.eng.reg._c.execute("UPDATE evidence SET failing=? WHERE kind='test' AND repo_id='backend'", (json.dumps(["LegacyTest.flaky"]),))
        reg = self.eng.build_report(SLUG)["regression"]["backend"]
        self.assertEqual(reg, {"new_failures": [], "still_failing": ["LegacyTest.flaky"], "now_passing": ["OldTest.broken"]})

    def test_AC_TRC_02c_trace_gaps_and_failing_checks_are_in_different_lists(self):
        self.to_ready()
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("UPDATE evidence SET verdict='fail' WHERE kind='lint' AND repo_id='frontend'")
        rep = self.eng.build_report(SLUG)
        self.assertEqual(rep["verification"]["failures"], ["frontend lint"])
        self.assertTrue(all(g.startswith(("scenario ", "cycle ")) for g in rep["trace"]["gaps"]))
        self.assertIn("scenario Unused days carry over has no test link", rep["trace"]["gaps"])
        self.assertFalse([g for g in rep["trace"]["gaps"] if "lint" in g])

    def test_AC_SEC_06b_report_files_are_scrubbed(self):
        self.to_completed()
        task = self.tasks_of()[0]
        self.tdir(task["id"]).mkdir(parents=True, exist_ok=True)
        self.write_result(task["id"], summary="token=ghp_abcdef123456 in /home/alice/work/leave")
        self.cli("report", SLUG)
        text = self.rpath().read_text() + self.rpath("report.md").read_text()
        for bad in ("ghp_abcdef123456", "/home/alice"):
            self.assertNotIn(bad, text)
        self.assertIn("[REDACTED:secret]", text)
        self.assertIn("$HOME", text)

    def test_AC_ART_01i_report_requests_that_are_refused(self):
        self.use_config()
        self.cli("run", "new", "old-fix", "--tier", "2")
        for slug, code, err in [("no-such-run", 5, "E_NOT_FOUND"), ("../x", 5, "E_VALIDATION"), ("old-fix", 5, "E_TRANSITION")]:
            with self.subTest(slug=slug):
                got, out, e = self.cli("report", slug)
                self.assertEqual((got, err in e), (code, True), e)


if __name__ == "__main__":
    unittest.main()
