"""Phase D part 2b (PD-02): cycle evidence and trace links (cycle_evidence_trace.feature)."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from errors import SentinelError  # noqa: E402
from pd_helpers import (PROD, REMAINING, SLUG, T1, T2, TEST_FILE, PDX, all_pass, default_features, report)  # noqa: E402

BAL = {"balance.feature": default_features()["balance.feature"]}


class Evidence(PDX):
    def accepted(self, **kw):
        kw.setdefault("model", "fake-model")
        self.to_accepted(**kw)

    def back_to_refactor_verified(self):
        """A cycle in REFACTOR_VERIFIED with complete evidence, as the state before acceptance."""
        cid = self.cycle("Remaining")["id"]
        self.sql("UPDATE cycles SET state='REFACTOR_VERIFIED', accepted_at=NULL WHERE id=?", (cid,))
        self.sql("DELETE FROM trace_links WHERE from_kind='cycle' AND from_id=? AND to_kind='evidence'", (cid,))
        return cid

    def test_AC_TDD_06a_an_accepted_cycle_holds_full_evidence(self):
        self.accepted()
        cyc = self.cycle("Remaining")
        self.assertEqual(self.moves("Remaining")[-1], "CYCLE_ACCEPTED")
        for kind in ("red", "green", "refactor"):
            with self.subTest(kind):
                rows = self.evidence(kind, label="Remaining")
                self.assertEqual(len(rows), 1)
                e = rows[0]
                for col in ("command", "cwd", "exit_code", "classification", "passed", "failed", "skipped", "started_at",
                            "finished_at", "env", "repo_sha", "output_artifact_id", "output_sha256", "task_id"):
                    self.assertIsNotNone(e[col], col)
                self.assertLessEqual(e["started_at"], e["finished_at"])
                art = self.eng.reg.get_row("artifacts", e["output_artifact_id"])
                data = (self.ws / ".sentinel" / art["path"]).read_bytes()
                self.assertEqual(e["output_sha256"], hashlib.sha256(data).hexdigest())
                self.assertEqual((e["provider"], e["model"], e["verdict"]), ("fake", "fake-model", "accepted"))
                self.assertEqual(e["task_id"], cyc[f"{kind}_task"])
                changed = self.eng.reg.rows("changed_files", task_id=e["task_id"])
                if kind != "refactor":
                    self.assertTrue(changed)
                self.assertTrue(all(c["path"] and "after_sha256" in c for c in changed))
        self.assertTrue(cyc["accepted_at"])

    def test_AC_TDD_06b_incomplete_evidence_blocks_acceptance(self):
        self.accepted()
        cid = self.back_to_refactor_verified()
        snap = self.snapshot()
        behavior = self.cycle("Remaining")["behavior"]
        rows = [("the red evidence row is missing", "DELETE FROM evidence WHERE cycle_id=? AND kind='red'", "red evidence"),
                ("the green evidence row has no output file",
                 "UPDATE evidence SET output_artifact_id=NULL, output_sha256=NULL WHERE cycle_id=? AND kind='green'", "green output"),
                ("the refactor evidence row has no repo_sha", "UPDATE evidence SET repo_sha=NULL WHERE cycle_id=? AND kind='refactor'",
                 "refactor repo_sha"),
                ("the changed-file rows of the green phase are missing",
                 "DELETE FROM changed_files WHERE cycle_id=? AND phase='tdd_green'", "green changed files"),
                ("the red evidence row has classification compile",
                 "UPDATE evidence SET classification='compile' WHERE cycle_id=? AND kind='red'", "red classification")]
        for gap, sql, item in rows:
            with self.subTest(gap):
                self.restore(snap)
                self.sql(sql, (cid,))
                with self.assertRaises(SentinelError) as cm:
                    self.eng.accept_cycle(cid)
                self.assertEqual(cm.exception.code, "E_PRECONDITION")
                self.assertIn(item, cm.exception.message)
                self.assertEqual(self.eng.reg.get_row("cycles", cid)["state"], "REFACTOR_VERIFIED")
                self.assertEqual(self.state(), "NEEDS_HUMAN")
                self.assertEqual(self.last_reason(), f"evidence incomplete for cycle {behavior}")

    def test_AC_TDD_06c_a_changed_evidence_output_file_is_an_integrity_failure(self):
        self.accepted()
        cid = self.back_to_refactor_verified()
        art = self.eng.reg.get_row("artifacts", self.evidence("green")[0]["output_artifact_id"])
        p = self.ws / ".sentinel" / art["path"]
        p.write_text(p.read_text() + "edited\n")
        with self.assertRaises(SentinelError) as cm:
            self.eng.accept_cycle(cid)
        self.assertEqual(cm.exception.code, "E_INTEGRITY")
        self.assertEqual(len(self.audit("integrity_failed")), 1)
        self.assertEqual((self.state(), self.eng.reg.get_row("cycles", cid)["state"]), ("NEEDS_HUMAN", "REFACTOR_VERIFIED"))

    def test_AC_TDD_06e_agent_results_never_create_evidence_rows(self):
        gid = self.to_red_verified()
        self.agent_exec("tdd_green", f"write({PROD!r}, 'class LeaveBalance {{}}\\n')\n"
                                     "write_result(claimed_commands=[{'command': './gradlew test', 'exit_code': 0}],"
                                     " claimed_changed_files=['backend/src/main/java/leave/Other.java'])\n")
        self.targeted(all_pass())
        self.eng.run_task(gid)
        rows = self.evidence(label="Remaining")
        self.assertEqual([e["kind"] for e in rows], ["red", "green"])
        for e in rows:
            self.assertIn("faketest", e["command"])
            self.assertNotIn("gradlew", e["command"])
        flags = json.loads((self.tdir(gid) / "report.json").read_text())["claim_flags"]
        self.assertIn({"path": "backend/src/main/java/leave/Other.java", "flag": "claimed but not changed"}, flags)

    def test_AC_TDD_06f_a_failed_evidence_write_leaves_the_cycle_where_it_was(self):
        gid = self.to_red_verified()
        self.targeted(all_pass())
        real = self.eng.reg.insert_row

        def failing(table, row):
            if table == "evidence":
                raise RuntimeError("database error")
            return real(table, row)
        self.eng.reg.insert_row = failing
        with self.assertRaises(RuntimeError):
            self.eng.run_task(gid)
        self.eng.reg.insert_row = real
        self.assertEqual(self.cstate("Remaining"), "GREEN_RUNNING")
        self.assertNotIn("GREEN_VERIFIED", self.moves("Remaining"))
        self.assertEqual(self.evidence("green"), [])
        step = self.eng.next_step(SLUG)
        self.assertEqual(self.cstate("Remaining"), "GREEN_VERIFIED")
        self.assertEqual(len(self.evidence("green")), 1)
        self.assertEqual(len(self.tdd_tasks("tdd_green", "Remaining")), 1)
        self.assertEqual(step["kind"], "task")


class Trace(PDX):
    def cycle_links(self, cid):
        return sorted({(r["to_kind"]) for r in self.links("cycle") if r["from_id"] == cid})

    def test_AC_TRC_01a_an_accepted_cycle_completes_the_trace_chain(self):
        self.to_accepted()
        cid = self.cycle("Remaining")["id"]
        got = {(r["from_kind"], r["from_id"], r["to_kind"], r["to_id"]) for r in self.links()}
        ev = {e["id"] for e in self.evidence(label="Remaining")}
        want = {("req", "REQ-1", "ac", "AC-1"), ("ac", "AC-1", "scenario", REMAINING[0]), ("scenario", REMAINING[0], "cycle", cid),
                ("scenario", REMAINING[0], "test", T1), ("scenario", REMAINING[1], "test", T2), ("cycle", cid, "test_file", TEST_FILE),
                ("cycle", cid, "file", PROD)} | {("cycle", cid, "evidence", e) for e in ev}
        self.assertEqual(len(ev), 3)
        self.assertLessEqual(want, got)

    def test_AC_TRC_01b_links_are_added_as_the_cycle_moves(self):
        self.boot_x()
        self.prepare()
        cid = self.cycle("Remaining")["id"]
        self.assertEqual(self.cycle_links(cid), [])
        self.assertEqual(len([r for r in self.links("scenario", "cycle") if r["to_id"] == cid]), 2)
        self.targeted(report("Remaining", "failure"))
        self.eng.run_task(self.tid("tdd_red"))
        self.assertEqual(self.cycle_links(cid), ["test_file"])
        self.targeted(all_pass())
        self.eng.run_task(self.tid("tdd_green"))
        self.assertEqual(self.cycle_links(cid), ["file", "test_file"])
        self.eng.run_task(self.tid("tdd_refactor"))
        self.assertEqual(self.cycle_links(cid), ["evidence", "file", "test_file"])

    def test_AC_TRC_02a_the_trace_report_separates_gaps_and_failures(self):
        self.boot_x(features=BAL)
        self.prepare()
        rem, carry = self.cycle("Remaining")["id"], self.cycle("Carry")["id"]
        self.set_cycle("Remaining", state="REJECTED", reason="green cap reached")
        for key, test in zip(REMAINING, (T1, T2)):
            self.eng.reg.add_trace_link(self.run_row()["id"], "scenario", key, "test", test)
        rep = self.eng.trace_report(SLUG)
        carry_key = "features/balance.feature :: Unused days carry over"
        self.assertIn({"kind": "scenario", "id": carry_key, "gap": "no test"}, rep["gaps"])
        self.assertIn({"kind": "cycle", "id": carry, "gap": "no evidence"}, rep["gaps"])
        self.assertEqual(rep["failures"], [{"kind": "cycle", "id": rem, "reason": "rejected: Green cap reached"}])
        ids = lambda items: {(i["kind"], i["id"]) for i in items}  # noqa: E731
        self.assertFalse(ids(rep["gaps"]) & ids(rep["failures"]))
        self.assertNotIn(("cycle", rem), ids(rep["gaps"]))

    def test_the_phase_b_trace_links_use_the_scenario_key_not_the_line_number(self):
        self.boot_x()
        got = {(r["from_id"], r["to_id"]) for r in self.links("ac", "scenario")}
        self.assertIn(("AC-1", REMAINING[0]), got)
        self.assertIn(("AC-2", REMAINING[1]), got)
        self.assertFalse([1 for _, to in got if to.rsplit(":", 1)[-1].isdigit()])


if __name__ == "__main__":
    unittest.main()
