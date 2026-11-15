"""Phase E: verification evidence and the verify command (verification_evidence.feature)."""
import hashlib
import json
import sqlite3
import time
import unittest
from unittest import mock

from pe_helpers import PE, SLUG
from pc_helpers import wait_until
from errors import SentinelError


class Evidence(PE):
    def boot1(self, **kw):
        self.boot_ver(tier=3, repos=("backend",), **kw)
        self.change(("backend",))

    def test_AC_VER_01j_evidence_row_holds_the_full_record(self):
        self.boot1()
        self.verify()
        rows = self.vrows(round=1)
        self.assertTrue(rows)
        for e in rows:
            if e["kind"] in ("scope", "deps", "hygiene", "secret"):
                continue
            for col in ("kind", "repo_id", "command", "cwd", "exit_code", "classification", "started_at", "finished_at",
                        "env", "repo_sha", "output_sha256", "output_artifact_id"):
                self.assertIsNotNone(e[col], (e["kind"], col))
            self.assertLessEqual(e["started_at"], e["finished_at"])
            art = self.eng.reg.get_row("artifacts", e["output_artifact_id"])
            self.assertTrue(art["path"].startswith("runs/leave-balance/verification/round-1/"))
            data = (self.ws / ".sentinel" / art["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), e["output_sha256"])
            self.assertIsNone(e["task_id"])
            self.assertIn("python", json.loads(e["env"]))
            self.assertIn("os", json.loads(e["env"]))
        for ev in self.events("evidence.recorded"):
            self.assertEqual(ev["actor"], "engine")

    def test_AC_VER_02b_agent_claims_do_not_count(self):
        self.boot1()
        tid = self.tasks_of()[0]["id"]
        (self.tdir(tid)).mkdir(parents=True, exist_ok=True)
        self.write_result(tid, claimed_commands=[{"command": "./gradlew test", "exit_code": 0}])
        self.mode("test", "backend", exit=1, report=[["LeaveFormTest", "submit", "failure"]], extra_passed=1)
        res = self.verify()
        self.assertEqual(self.vrows("test")[0]["verdict"], "fail")
        self.assertEqual(self.state(), "VERIFYING")
        self.assertEqual(res["summary"]["claims"][0]["flag"], "contradicted by evidence")

    def test_AC_VER_02c_a_check_an_agent_ran_is_not_skipped(self):
        self.boot1()
        for t in self.tasks_of():
            self.tdir(t["id"]).mkdir(parents=True, exist_ok=True)
            self.write_result(t["id"], claimed_commands=[{"command": c, "exit_code": 0} for c in ("build", "lint", "typecheck", "test")])
        self.verify()
        modes = {c["mode"] for c in self.tool_calls()}
        self.assertTrue({"build", "lint", "typecheck", "targeted", "test"} <= modes, modes)

    def test_AC_SEC_06a_secrets_never_reach_stored_output(self):
        rows = [("password=hunter2x9", "hunter2x9", "[REDACTED:secret]"),
                ("key AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP", "[REDACTED:aws key]"),
                ("jdbc://app:s3cretpw@db.internal/leave", "s3cretpw", "[REDACTED:credentials]"),
                ("mail sent to jane.doe@corp-mail.com", "jane.doe@corp-mail.com", "[REDACTED:email]"),
                ("value Pw-9f3kq2zz", "Pw-9f3kq2zz", "[REDACTED:env]")]
        for text, secret, marker in rows:
            with self.subTest(text=text):
                self.boot1()
                (self.ws / "backend" / ".env").write_text("DB_PASSWORD=Pw-9f3kq2zz\n")
                self.mode("test", "backend", exit=0, report=[], extra_passed=1, stdout=text)
                self.verify()
                e = self.vrows("test")[0]
                art = self.eng.reg.get_row("artifacts", e["output_artifact_id"])
                data = (self.ws / ".sentinel" / art["path"]).read_text()
                self.assertNotIn(secret, data)
                self.assertIn(marker, data)
                self.assertEqual(hashlib.sha256(data.encode()).hexdigest(), e["output_sha256"])
                self.reset_ws()

    def test_AC_VER_01k_second_round_keeps_the_first(self):
        self.boot1()
        self.mode("lint", "backend", exit=1, stdout="Balance.java:12 unused")
        self.assertEqual(self.verify()["exit"], 1)
        first = [dict(e) for e in self.vrows(round=1)]
        fix = self.tasks_of("tdd_green")[0]
        self.eng.reg.update_row("tasks", fix["id"], state="COMPLETED")
        self.mode("lint", "backend", exit=0)
        self.assertEqual(self.verify()["exit"], 0)
        self.assertEqual([dict(e) for e in self.vrows(round=1)], first)
        self.assertTrue(self.vrows(round=2))
        self.assertEqual(self.eng.finished_round(self.run_row())["round"], 2)

    def test_AC_VER_01m_verify_in_other_states_is_refused(self):
        for state in ("EXECUTING", "GHERKIN_REVIEW", "REVIEWING", "COMPLETED", "NEEDS_HUMAN"):
            with self.subTest(state=state):
                self.boot1()
                self.set_state(state)
                with self.assertRaises(SentinelError) as c:
                    self.verify()
                self.assertEqual(c.exception.code, "E_TRANSITION")
                self.assertFalse(self.vrows())
                self.reset_ws()

    def test_AC_VER_01n_verify_on_a_0_1_run_points_to_release_check(self):
        self.use_config()
        code, out, err = self.cli("run", "new", "old-fix", "--tier", "2")
        self.assertEqual(code, 0, out + err)
        code, out, err = self.cli("verify", "old-fix")
        self.assertEqual(code, 5)
        self.assertIn("E_TRANSITION", err)
        self.assertIn("release-check", err)

    def test_AC_ARC_03j_next_says_to_run_verification(self):
        self.boot1()
        step = self.eng.next_step(SLUG)
        self.assertEqual((step["kind"], step["command"]), ("orchestrator", f"sentinel verify {SLUG}"))
        self.assertFalse(self.vrows())

    def test_AC_ARC_03k_verify_prints_one_line_per_check(self):
        self.boot1()
        code, out, err = self.cli("verify", SLUG)
        self.assertEqual(code, 0, out + err)
        lines = out.strip().splitlines()
        self.assertEqual(lines[-1], "VERIFICATION PASSED (round 1)")
        self.assertEqual(len(lines) - 1, len(self.vrows()))
        self.assertIn("backend test: pass", lines)

    def test_AC_AGT_07t_two_verify_calls_run_once(self):
        self.boot1()
        self.mode("test", "backend", exit=0, report=[], extra_passed=1, sleep=3)
        a = self.popen("verify", SLUG)
        self.assertTrue(wait_until(lambda: self.rounds(), 10))
        b = self.popen("verify", SLUG)
        codes = sorted([self.finish(a)[0], self.finish(b)[0]])
        self.assertEqual(codes, [0, 5])
        self.assertEqual(len(self.rounds()), 1)

    def test_AC_AGT_07u_verify_waits_while_a_task_runs(self):
        self.boot1()
        t = self.tasks_of()[0]
        self.eng.reg.update_row("tasks", t["id"], state="RUNNING")
        with self.assertRaises(SentinelError) as c:
            self.verify()
        self.assertEqual(c.exception.code, "E_PRECONDITION")
        self.assertIn(t["id"], c.exception.message)
        self.assertFalse(self.vrows())

    def test_AC_ORC_07e_interrupted_verification_starts_again(self):
        self.boot1()
        run = self.run_row()
        with self.eng.reg.transaction():
            self.eng.reg.insert_row("verification_rounds", {"run_id": run["id"], "round": 1, "started_at": "2026-01-01T00:00:00.000000Z",
                                                            "interrupted": 0, "owner_pid": 999999, "owner_started_at": "1"})
            self.eng.reg.insert_row("evidence", {"run_id": run["id"], "kind": "build", "repo_id": "backend", "round": 1, "verdict": "pass"})
        res = self.verify()
        self.assertEqual(res["exit"], 0)
        r1 = [r for r in self.rounds() if r["round"] == 1][0]
        self.assertEqual((r1["interrupted"], r1["finished_at"]), (1, None))
        self.assertEqual(self.eng.finished_round(self.run_row())["round"], 2)

    def test_AC_ORC_07f_failed_registry_write_leaves_an_open_round(self):
        self.boot1()
        real = self.eng.reg.insert_row
        count = {"n": 0}

        def flaky(table, row):
            if table == "evidence":
                count["n"] += 1
                if count["n"] > 3:
                    raise sqlite3.OperationalError("disk I/O error")
            return real(table, row)
        with mock.patch.object(self.eng.reg, "insert_row", flaky):
            with self.assertRaises(SentinelError) as c:
                self.verify()
        self.assertEqual(c.exception.exit_code, 1)
        r1 = self.rounds()[0]
        self.assertIsNone(r1["finished_at"])
        self.assertEqual(self.state(), "VERIFYING")
        res = self.verify()
        self.assertEqual(res["exit"], 0)
        self.assertEqual([r["interrupted"] for r in self.rounds()], [1, 0])


if __name__ == "__main__":
    unittest.main()
