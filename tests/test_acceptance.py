"""Phase E: R15, computed acceptance and `sentinel accept` (acceptance.feature)."""
import json
import subprocess
import threading
import unittest

from pe_helpers import PE, SLUG
from pb_helpers import PtyProc, run_tty, run_plain, CLI, CLI_ENV
from errors import SentinelError


class Accept(PE):
    d = property(lambda self: ["--dir", str(self.ws)])

    def accept_tty(self, *flags, typed=None):
        typed = self.prefix() if typed is None else typed
        return run_tty(self.d + ["accept", SLUG, *flags], [typed])

    def human_rows(self):
        return self.approvals("acceptance")

    def test_AC_VER_03a_a_clean_run_completes_accepted(self):
        self.to_ready()
        code, step, err = self.next_json()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.state(), "COMPLETED")
        ev = [e for e in self.events("run.state_changed") if e["payload"]["to"] == "COMPLETED"][-1]
        self.assertEqual((ev["payload"]["transition"], ev["actor"]), ("R15", "engine"))
        run = self.run_row()
        self.assertEqual((run["execution_status"], run["acceptance_status"]), ("completed", "accepted"))
        self.assertEqual((step["kind"], step["human_acceptance"], step["command"]), ("done", "pending", f"sentinel accept {SLUG}"))

    def test_AC_VER_03b_completion_records_final_shas_writes_the_report_and_releases_the_lock(self):
        self.to_ready()
        self.eng.next_step(SLUG)
        shas = {r["repo_id"]: r["final_sha"] for r in self.eng.reg.run_repos(self.run_row()["id"])}
        self.assertTrue(all(shas.values()), shas)
        self.assertTrue((self.ws / ".sentinel/runs" / SLUG / "report.json").is_file())
        self.assertTrue((self.ws / ".sentinel/runs" / SLUG / "report.md").is_file())
        self.assertEqual(self.released, [SLUG])
        ev = self.events("run.status_changed")[-1]["payload"]
        self.assertEqual((ev["execution_status"], ev["acceptance_status"], ev["reasons"]), ("completed", "accepted", []))

    def test_AC_VER_03c_each_rule_gives_its_reason(self):
        rows = [("spec invalidated", "specification approval missing or invalid"), ("gherkin missing", "gherkin approval missing or invalid"),
                ("spec edited", "specification approval missing or invalid"), ("cycle open", "cycles incomplete: request-form"),
                ("test failed", "required tests fail: backend test"), ("no scope row", "verification evidence missing: frontend scope"),
                ("unfinished round", "verification evidence missing"), ("scope failed", "scope exceeded: backend"),
                ("waived", "required reviews open: 1 waived major finding"), ("qa cancelled", "required reviews open: qa"),
                ("no security", "required human approval missing: security"),
                ("migration", "required human approval missing: migration")]
        for gap, reason in rows:
            with self.subTest(gap=gap):
                tier = 4 if gap in ("no security", "migration") else 3
                self.to_ready(tier)
                if gap == "migration":
                    self.approve_security()
                self.tweak(gap)
                res = self.eng.compute_acceptance(SLUG)
                self.assertEqual(res["status"], "rejected")
                self.assertIn(reason, res["reasons"], res)
                self.reset_ws()

    def tweak(self, gap):
        run = self.run_row()
        with self.eng.reg.transaction():
            c = self.eng.reg._c
            if gap == "spec invalidated":
                c.execute("UPDATE approvals SET state='INVALIDATED' WHERE gate='specification'")
            elif gap == "gherkin missing":
                c.execute("DELETE FROM approvals WHERE gate='gherkin'")
            elif gap == "cycle open":
                c.execute("UPDATE cycles SET state='REFACTOR_VERIFIED' WHERE behavior LIKE '%request_form%'")
            elif gap == "test failed":
                c.execute("UPDATE evidence SET verdict='fail' WHERE kind='test' AND repo_id='backend'")
            elif gap == "no scope row":
                c.execute("DELETE FROM evidence WHERE kind='scope' AND repo_id='frontend'")
            elif gap == "unfinished round":
                c.execute("UPDATE verification_rounds SET finished_at=NULL")
            elif gap == "scope failed":
                c.execute("UPDATE evidence SET verdict='fail' WHERE kind='scope' AND repo_id='backend'")
            elif gap == "waived":
                c.execute("INSERT INTO findings(id, run_id, source, severity, text, state) VALUES ('f-w', ?, 'reviewer', 'major', 'x', 'waived')", (run["id"],))
            elif gap == "qa cancelled":
                c.execute("UPDATE tasks SET state='CANCELLED' WHERE role='qa'")
            elif gap == "migration":
                eid = [e for e in c.execute("SELECT id FROM evidence WHERE kind='scope' AND repo_id='backend'")][0][0]
                c.execute("INSERT INTO evidence(id, run_id, kind, repo_id, round, verdict, classification, detail, failing) "
                          "VALUES ('e-m', ?, 'migration', 'backend', 1, 'pass', 'destructive_approved', ?, '[]')",
                          (run["id"], json.dumps({"approved": ["db/migration/V8.sql"], "destructive": []})))
        if gap == "spec edited":
            p = self.sdir() / "spec.md"
            p.write_text(p.read_text() + "\nedited\n")

    def test_AC_VER_03d_all_reasons_are_reported_in_order(self):
        self.to_ready()
        with self.eng.reg.transaction():
            c = self.eng.reg._c
            c.execute("DELETE FROM approvals WHERE gate='gherkin'")
            c.execute("UPDATE cycles SET state='GREEN_VERIFIED' WHERE behavior LIKE '%request_form%'")
            c.execute("UPDATE evidence SET verdict='fail' WHERE kind='lint' AND repo_id='frontend'")
        self.assertEqual(self.eng.compute_acceptance(SLUG)["reasons"], [
            "gherkin approval missing or invalid", "cycles incomplete: request-form", "required tests fail: frontend lint"])

    def test_AC_VER_03g_a_planned_check_without_an_evidence_row_is_missing(self):
        self.to_ready()
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("DELETE FROM evidence WHERE kind='lint' AND repo_id='frontend'")
            self.eng.reg._c.execute("DELETE FROM evidence WHERE kind='test' AND repo_id='backend'")
        res = self.eng.compute_acceptance(SLUG)
        self.assertEqual(res["status"], "rejected")
        self.assertIn("verification evidence missing: backend test, frontend lint", res["reasons"])

    def test_AC_VER_03e_checks_that_were_not_run_do_not_count_as_missing(self):
        for repo, kind, verdict in [("frontend", "lint", "not_configured"), ("backend", "typecheck", "disabled")]:
            with self.subTest(kind=kind):
                self.to_ready()
                with self.eng.reg.transaction():
                    self.eng.reg._c.execute("UPDATE evidence SET verdict=?, classification=? WHERE kind=? AND repo_id=?",
                                            (verdict, verdict, kind, repo))
                self.assertEqual(self.eng.compute_acceptance(SLUG)["status"], "accepted")
                self.eng.next_step(SLUG)
                rep = json.loads((self.ws / ".sentinel/runs" / SLUG / "report.json").read_text())
                self.assertIn(f"{repo} {kind}: {verdict}", rep["verification"]["not_run"])
                self.reset_ws()

    def test_AC_VER_03f_acceptance_ignores_agent_claims(self):
        self.to_ready()
        for t in self.new_tasks() + self.tasks_of():
            self.tdir(t["id"]).mkdir(parents=True, exist_ok=True)
            self.write_result(t["id"], claimed_commands=[{"command": "test", "exit_code": 0}])
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("UPDATE evidence SET verdict='fail' WHERE kind='test' AND repo_id='backend'")
        res = self.eng.compute_acceptance(SLUG)
        self.assertEqual((res["status"], res["reasons"][0]), ("rejected", "required tests fail: backend test"))

    def test_AC_SM_02g_R15_waits_while_review_work_is_open(self):
        self.to_ready()
        qa = [t for t in self.new_tasks("qa")][0]
        self.eng.reg.update_row("tasks", qa["id"], state="RUNNING")
        self.assertFalse(self.eng.check_r15(SLUG))
        self.assertEqual(self.state(), "REVIEWING")
        self.assertFalse([e for e in self.events("run.state_changed") if e["payload"]["to"] == "COMPLETED"])

    def test_AC_TRC_01d_the_trace_chain_reaches_the_acceptance(self):
        self.to_completed()
        run = self.run_row()
        links = self.eng.reg.rows("trace_links", run_id=run["id"])
        kinds = {(l["from_kind"], l["to_kind"]) for l in links}
        self.assertTrue({("req", "ac"), ("ac", "scenario"), ("scenario", "cycle"), ("cycle", "file"), ("run", "acceptance")} <= kinds, kinds)
        acc = [l for l in links if l["from_kind"] == "run"][0]
        self.assertEqual(self.eng.reg.get_row("artifacts", acc["to_id"])["kind"], "acceptance")

    def test_AC_TRC_02b_a_missing_trace_link_is_a_gap_not_a_failure(self):
        self.to_completed()
        cyc = [c for c in self.cycles() if "request_form" in c["behavior"]][0]
        rep = self.eng.trace_summary(SLUG)
        self.assertIn("cycle request-form has no evidence link", rep["gaps"])
        self.assertEqual(rep["failures"], [])
        self.assertEqual(self.run_row()["acceptance_status"], "accepted")

    def test_AC_VER_04a_a_human_confirms_an_accepted_run(self):
        self.to_completed()
        code, out = self.accept_tty("-m", "pilot ok")
        self.assertEqual(code, 0, out)
        ap = self.human_rows()[-1]
        self.assertEqual((ap["decision"], ap["sha256"], ap["channel"], ap["comment"]),
                         ("accept", self.eng.report_info(SLUG)["sha256"], "tty", "pilot ok"))
        run = self.run_row()
        self.assertEqual((run["state"], run["acceptance_status"]), ("COMPLETED", "accepted"))
        # wording per Phase F AC-VER-04k; Phase E AC-VER-04a wording pending human confirmation
        self.assertEqual([a["action"] for a in self.audit() if a["action"] in ("accepted", "rejected", "acceptance")], ["accepted"])
        self.assertEqual(self.eng.human_acceptance(run), "confirmed")

    def test_AC_VER_04b_a_human_rejects_an_accepted_run(self):
        self.to_completed()
        code, out = self.accept_tty("--reject", "-m", "wrong rounding")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.run_row()["acceptance_status"], "rejected")
        self.assertEqual(self.events("run.state_changed")[-1]["payload"]["transition"], "R25")
        self.assertEqual(self.events("run.status_changed")[-1]["payload"]["reasons"], ["rejected by human: wrong rounding"])
        self.assertEqual([a["action"] for a in self.audit() if a["action"] in ("accepted", "rejected", "acceptance")], ["rejected"])

    def test_AC_VER_04c_a_rejected_run_never_becomes_accepted(self):
        for cause in ("engine", "human"):
            with self.subTest(cause=cause):
                self.to_completed()
                if cause == "engine":
                    with self.eng.reg.transaction():
                        self.eng.reg._c.execute("UPDATE runs SET acceptance_status='rejected'")
                        self.eng.reg.add_event(self.run_row()["id"], "run.status_changed", "engine",
                                               {"execution_status": "completed", "acceptance_status": "rejected",
                                                "reasons": ["required tests fail: backend test"]})
                else:
                    self.accept_tty("--reject", "-m", "no")
                code, out = self.accept_tty()
                self.assertEqual(code, 5, out)
                self.assertIn("E_PRECONDITION", out)
                self.assertIn("a rejected run never becomes accepted", out)
                self.assertIn("required tests fail: backend test" if cause == "engine" else "rejected by human: no", out)
                self.assertEqual(self.run_row()["acceptance_status"], "rejected")
                self.assertTrue([a for a in self.audit() if a["action"] == "acceptance_refused"])
                self.reset_ws()

    def test_AC_VER_04d_acceptance_outside_a_human_terminal_is_refused(self):
        self.to_completed()
        code, out = run_plain(self.d + ["accept", SLUG])
        self.assertEqual(code, 5)
        self.assertIn("E_NOT_TTY", out)
        import os
        env = {**CLI_ENV, "SENTINEL_TASK_ID": "t-000000000000"}
        p = PtyProc(self.d + ["accept", SLUG], env)
        code, text = p.finish()
        self.assertEqual(code, 5, text)
        self.assertIn("E_ACTOR", text)
        self.assertEqual(self.human_rows(), [])
        self.assertEqual(self.eng.human_acceptance(self.run_row()), "pending")
        refused = [a for a in self.audit() if a["action"] == "acceptance_refused"]
        self.assertEqual([a["reason"] for a in refused], ["E_NOT_TTY", "E_ACTOR"])

    def test_AC_VER_04e_the_orchestrator_cannot_record_acceptance(self):
        self.to_completed()
        with self.assertRaises(SentinelError) as c:
            self.eng.accept(SLUG, "accept", "orchestrator", prefix=self.prefix())
        self.assertEqual(c.exception.code, "E_ACTOR")
        self.assertEqual(self.human_rows(), [])

    def test_AC_SEC_03e_a_wrong_prefix_or_a_changed_report_is_refused(self):
        self.to_completed()
        old = self.prefix()
        for typed, err in [("00000000", "E_VALIDATION"), ("", "E_VALIDATION")]:
            code, out = self.accept_tty(typed=typed)
            self.assertEqual(code, 5, out)
            self.assertIn(err, out)
        self.eng.reg.add_event(self.run_row()["id"], "task.progress", "engine", {})
        self.eng.write_report(SLUG)
        self.assertNotEqual(old, self.prefix())
        code, out = self.accept_tty(typed=old)
        self.assertEqual(code, 5, out)
        self.assertIn("E_APPROVAL_STALE", out)
        self.assertEqual(self.human_rows(), [])

    def test_AC_VER_04f_acceptance_is_only_for_completed_runs(self):
        for state in ("REVIEWING", "NEEDS_HUMAN", "CANCELLED"):
            with self.subTest(state=state):
                self.to_ready()
                self.set_state(state)
                code, out = run_tty(self.d + ["accept", SLUG])
                self.assertEqual(code, 5, out)
                self.assertIn("E_TRANSITION", out)
                self.reset_ws()

    def test_AC_VER_04g_integrity_is_checked_again_before_a_human_confirms(self):
        for change, err in [("spec", "E_APPROVAL_STALE"), ("evidence", "E_INTEGRITY")]:
            with self.subTest(change=change):
                self.to_completed()
                prefix = self.prefix()
                if change == "spec":
                    p = self.sdir() / "spec.md"
                    p.write_text(p.read_text() + "\nedited\n")
                else:
                    e = self.vrows("test", "backend")[0]
                    art = self.eng.reg.get_row("artifacts", e["output_artifact_id"])
                    (self.ws / ".sentinel" / art["path"]).write_text("edited\n")
                code, out = run_tty(self.d + ["accept", SLUG], [prefix])
                self.assertEqual(code, 5, out)
                self.assertIn(err, out)
                run = self.run_row()
                self.assertEqual((run["acceptance_status"], self.eng.human_acceptance(run)), ("accepted", "pending"))
                self.reset_ws()

    def test_AC_VER_01l_an_edited_evidence_output_is_an_integrity_failure(self):
        self.to_ready()
        e = self.vrows("test", "backend")[0]
        art = self.eng.reg.get_row("artifacts", e["output_artifact_id"])
        (self.ws / ".sentinel" / art["path"]).write_text("edited\n")
        with self.assertRaises(SentinelError) as c:
            self.eng.compute_acceptance(SLUG)
        self.assertEqual(c.exception.code, "E_INTEGRITY")
        self.assertIn("backend-test.log", c.exception.message)
        self.assertTrue([a for a in self.audit() if a["action"] == "integrity_failed"])
        self.assertEqual(self.state(), "NEEDS_HUMAN")

    def test_AC_VER_04h_a_human_can_still_reject_a_run_whose_artifacts_changed(self):
        self.to_completed()
        prefix = self.prefix()
        p = self.sdir() / "spec.md"
        p.write_text(p.read_text() + "\nedited\n")
        code, out = run_tty(self.d + ["accept", SLUG, "--reject", "-m", "spec drifted"], [prefix])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.run_row()["acceptance_status"], "rejected")

    def test_AC_VER_04i_a_second_human_decision(self):
        for flags, code, status in [([], 5, "accepted"), (["--reject", "-m", "regression"], 0, "rejected")]:
            with self.subTest(flags=flags):
                self.to_completed()
                self.assertEqual(self.accept_tty()[0], 0)
                got, out = self.accept_tty(*flags)
                self.assertEqual(got, code, out)
                self.assertEqual(self.run_row()["acceptance_status"], status)
                self.reset_ws()

    def test_AC_VER_04j_two_terminals_decide_at_the_same_moment(self):
        self.to_completed()
        prefix = self.prefix()
        a = PtyProc(self.d + ["accept", SLUG])
        b = PtyProc(self.d + ["accept", SLUG, "--reject", "-m", "no"])
        self.assertTrue(a.wait_for("first 8 characters", 15) and b.wait_for("first 8 characters", 15))
        barrier = threading.Barrier(2)

        def go(p):
            barrier.wait()
            p.send(prefix + "\n")
        ts = [threading.Thread(target=go, args=(p,)) for p in (a, b)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        ca, _ = a.finish()
        cb, _ = b.finish()
        self.assertEqual(cb, 0)
        self.assertEqual(self.run_row()["acceptance_status"], "rejected")
        rows = self.human_rows()
        self.assertEqual(rows[-1]["decision"], "reject")
        self.assertEqual(ca, 0 if len(rows) == 2 else 5)

    def test_AC_SEC_04b_generated_agent_configs_still_deny_accept(self):
        self.use_config(runners={"claude": {"command": "claude", "prompt_flag": "-p"}}, agents={})
        code, out, err = self.cli("sync-adapters")
        self.assertEqual(code, 0, out + err)
        deny = json.loads((self.ws / ".claude" / "settings.json").read_text())["permissions"]["deny"]
        self.assertIn("Bash(sentinel accept:*)", deny)
        self.assertIn("Bash(sentinel --dir * accept *)", deny)
        for rule in ("Bash(sentinel run export:*)", "Bash(sentinel run import:*)", "Bash(sentinel --dir * run export *)",
                     "Bash(sentinel --dir * run import *)"):
            self.assertIn(rule, deny)
        for f in (self.ws / ".claude" / "agents").glob("*.md"):
            self.assertIn("sentinel accept", f.read_text())


if __name__ == "__main__":
    unittest.main()
