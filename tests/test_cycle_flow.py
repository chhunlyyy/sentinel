"""Phase D part 2b (PD-02): cycle flow, caps, R13, concurrency, invalidation, recovery (cycle_flow.feature)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from errors import SentinelError  # noqa: E402
from pc_helpers import alive, wait_until  # noqa: E402
from pd_helpers import PROD, SLUG, T1, TWO_REPOS, PDX, all_pass, report  # noqa: E402
from tasks import retry_cap  # noqa: E402

FULL = ["PLANNED", "RED_RUNNING", "RED_VERIFIED", "GREEN_RUNNING", "GREEN_VERIFIED", "REFACTOR_RUNNING", "REFACTOR_VERIFIED",
        "CYCLE_ACCEPTED"]
POLICY2 = {"max_parallel_tasks": 2}


class Flow(PDX):
    def test_AC_SM_05d_a_full_cycle_then_the_next_behavior_begins(self):
        self.boot_x()
        steps, outs = self.drive(until=lambda: self.cstate("Remaining") == "CYCLE_ACCEPTED")
        self.assertEqual(self.moves("Remaining"), FULL)
        self.assertNotIn("human", [s["kind"] for s in steps])
        self.assertEqual([o["exit"] for o in outs], [0, 0, 0])
        nxt = self.eng.next_step(SLUG)
        self.assertEqual((nxt["kind"], nxt["role"]), ("task", "tdd_red"))
        self.assertEqual(nxt["task"], self.tdd_tasks("tdd_red", "Carry")[0]["id"])

    def test_AC_ORC_05e_green_and_refactor_caps_reject_the_cycle_and_ask_a_human(self):
        rows = [("green", "green_retries", 3, 4), ("refactor", "refactor_retries", 2, 3)]
        for i, (phase, key, cap, attempts) in enumerate(rows):
            with self.subTest(phase):
                if i:
                    self.reset_ws()
                self.boot_x(tdd={key: cap})
                steps, outs = self.drive(fail_role=f"tdd_{phase}")
                self.assertEqual(len(self.tdd_tasks(f"tdd_{phase}", "Remaining")), attempts)
                cyc = self.cycle("Remaining")
                self.assertEqual((cyc["state"], cyc["reason"]), ("REJECTED", f"{phase} cap reached"))
                self.assertEqual(self.state(), "NEEDS_HUMAN")
                self.assertIn("Remaining", self.last_reason())
                self.assertIn(f"targeted tests fail: {T1}", self.last_reason())
                self.assertEqual(outs[-1]["exit"], 6)
                self.assertEqual(steps[-1]["kind"], "human")

    def test_AC_ORC_05g_a_task_failure_and_a_green_rejection_share_the_phase_cap(self):
        self.to_red_verified(tdd={"green_retries": 1})
        self.agent_exec("tdd_green", "sys.exit(1)")
        self.eng.run_task(self.tid("tdd_green"))
        self.assertEqual(self.task(self.tid("tdd_green"))["state"], "QUEUED")
        self.agent_exec("tdd_green", f"write({PROD!r}, 'class L {{}}\\n')\nwrite_result()\n")
        self.targeted(report("Remaining", "failure"))
        self.eng.run_task(self.tid("tdd_green"))
        self.assertEqual(len(self.tdd_tasks("tdd_green", "Remaining")), 2)
        self.assertEqual(self.cstate("Remaining"), "REJECTED")
        self.assertEqual(self.state(), "NEEDS_HUMAN")

    def test_AC_ORC_05h_after_a_human_resumes_a_rejected_cycle_is_replanned_as_a_new_cycle(self):
        self.boot_x()
        self.prepare()
        old = self.cycle("Remaining")["id"]
        self.set_cycle("Remaining", state="REJECTED", reason="green cap reached")
        with self.eng.reg.transaction():
            self.eng._move(self.eng.reg.get_run(SLUG), "NEEDS_HUMAN", "engine", reason="green cap reached")
        self.eng.request_state(SLUG, "EXECUTING", "human", reason="decision: try again")
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(self.rules()[-1], "R20")
        rows = [c for c in self.cycles() if "Remaining" in c["behavior"]]
        self.assertEqual([(c["state"], c["retry_of"]) for c in rows], [("REJECTED", None), ("PLANNED", old)])
        self.assertEqual(rows[1]["scenarios"], rows[0]["scenarios"])
        self.assertEqual(rows[1]["repo_id"], rows[0]["repo_id"])
        self.assertEqual(len([c for c in self.cycles() if "Carry" in c["behavior"]]), 1)


    def test_a_green_task_that_asks_a_question_gets_a_new_attempt_with_the_answer_on_resume(self):
        """MEF-HR 2026-11-24: Green reported `blocked` with a question, the run parked, a human fixed it and resumed, and
        nothing ever ran again (BLOCKED has no way out). Now R20 closes the blocked task and queues a new attempt whose
        brief carries the question and the human's answer; answering does not use up a retry."""
        self.to_red_verified(tdd={"green_retries": 1})
        self.agent_exec("tdd_green", "write_result('blocked', questions=['Old test X uses the removed method: drop it?'])")
        asked = self.tid("tdd_green")
        self.eng.run_task(asked)
        self.assertEqual((self.task(asked)["state"], self.state()), ("BLOCKED", "NEEDS_HUMAN"))
        self.eng.request_state(SLUG, "EXECUTING", "human", reason="Removed test X myself; keep going.")
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(self.task(asked)["state"], "CANCELLED")
        greens = self.tdd_tasks("tdd_green", "Remaining")
        self.assertEqual([t["state"] for t in greens], ["CANCELLED", "QUEUED"])
        self.assertEqual(self.cycle("Remaining")["green_task"], greens[-1]["id"])
        brief = (self.eng.task_dir(SLUG, greens[-1]["id"]) / "brief.md").read_text()
        self.assertIn("stopped to ask: Old test X uses the removed method: drop it?", brief)
        self.assertIn("A human answered:\nRemoved test X myself; keep going.", brief)


    def test_a_human_sends_a_cycle_back_to_red_with_what_its_tests_must_change(self):
        """MEF-HR 2026-11-24: Green asked about tests that looked wrong; the owner decided the tests must change, which Green
        may not do. back_to_red rejects the cycle with the comment, resumes the run, and the replanned cycle's Red brief
        carries the comment and the paths of the previous tests."""
        self.to_red_verified()
        self.agent_exec("tdd_green", "write_result('blocked', questions=['Test Y expects 503 but cannot reach it'])")
        asked = self.tid("tdd_green")
        self.eng.run_task(asked)
        old = self.cycle("Remaining")
        with self.assertRaises(SentinelError):
            self.eng.back_to_red(SLUG, asked, "  ", user="owner")
        self.eng.back_to_red(SLUG, asked, "Test Y: assert the rollback only, no 503.", user="owner")
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(self.task(asked)["state"], "CANCELLED")
        rows = [c for c in self.cycles() if "Remaining" in c["behavior"]]
        self.assertEqual([(c["state"], c["retry_of"]) for c in rows], [("REJECTED", None), ("PLANNED", old["id"])])
        self.eng.ensure_cycle_tasks(SLUG)
        red = self.tdd_tasks("tdd_red", "Remaining")[-1]
        brief = (self.eng.task_dir(SLUG, red["id"]) / "brief.md").read_text()
        self.assertIn("Change the tests as asked:\nTest Y: assert the rollback only, no 503.", brief)
        self.assertIn(json.loads(old["approved_tests"])[0]["path"], brief)


class R13(PDX):
    def setup_cycles(self, states, tier=3):
        self.boot_x(repos=TWO_REPOS, tier=tier)
        self.prepare()
        for label, state in states.items():
            self.set_cycle(label, state=state)

    def test_AC_ORC_01f_when_r13_applies(self):
        acc = {"Remaining": "CYCLE_ACCEPTED", "Carry": "CYCLE_ACCEPTED"}
        rows = [("all three accepted", dict(acc, request_form="CYCLE_ACCEPTED"), 3, None, "VERIFYING"),
                ("form refactor verified with evidence", dict(acc, request_form="RFV"), 3, None, "VERIFYING"),
                ("form green running", dict(acc, request_form="GREEN_RUNNING"), 3, None, "EXECUTING"),
                ("tier 4 hardener running", dict(acc, request_form="CYCLE_ACCEPTED"), 4, "RUNNING", "EXECUTING"),
                ("tier 4 hardener completed", dict(acc, request_form="CYCLE_ACCEPTED"), 4, "COMPLETED", "VERIFYING")]
        for i, (name, states, tier, hardener, want) in enumerate(rows):
            with self.subTest(name):
                if i:
                    self.reset_ws()
                if states["request_form"] == "RFV":
                    self.boot_x(repos=TWO_REPOS, policies=POLICY2)
                    self.prepare()
                    self.targeted(report("request_form", "failure"), repo="frontend")
                    self.eng.run_task(self.tid("tdd_red", "request_form"))
                    self.targeted(all_pass(), repo="frontend")
                    self.eng.run_task(self.tid("tdd_green", "request_form"))
                    self.eng.run_task(self.tid("tdd_refactor", "request_form"))
                    cid = self.cycle("request_form")["id"]
                    self.sql("UPDATE cycles SET state='REFACTOR_VERIFIED', accepted_at=NULL WHERE id=?", (cid,))
                    self.sql("DELETE FROM trace_links WHERE from_id=? AND to_kind='evidence'", (cid,))
                    self.set_cycle("Remaining", state="CYCLE_ACCEPTED")
                    self.set_cycle("Carry", state="CYCLE_ACCEPTED")
                else:
                    self.setup_cycles(states, tier)
                if hardener:
                    tid = self.make("hardener", ["backend"], ["backend/**"])
                    (self.mark_running(tid) if hardener == "RUNNING" else self.sql("UPDATE tasks SET state='COMPLETED' WHERE id=?", (tid,)))
                self.eng.next_step(SLUG)
                self.assertEqual(self.state(), want)
                if want == "VERIFYING":
                    self.assertEqual(self.rules()[-1], "R13")
                    self.assertEqual(self.cstate("request_form"), "CYCLE_ACCEPTED")

    def test_AC_ORC_01g_nobody_but_the_engine_can_request_verification(self):
        self.setup_cycles({"Remaining": "CYCLE_ACCEPTED", "Carry": "CYCLE_ACCEPTED", "request_form": "GREEN_RUNNING"})
        for actor in ("orchestrator", "human", "agent"):
            with self.subTest(actor):
                with self.assertRaises(SentinelError) as cm:
                    self.eng.request_state(SLUG, "VERIFYING", actor)
                self.assertEqual(cm.exception.code, "E_ACTOR")
                self.assertEqual(self.state(), "EXECUTING")

    def test_AC_ORC_01h_a_docs_only_run_reaches_verification_without_cycles(self):
        slug = "leave-docs"
        self.to_spec_approved(slug, 2, "docs")
        self.eng.advance(slug)
        self.assertEqual(self.state(slug), "EXECUTING")
        self.eng.check_r13(slug)
        self.assertEqual(self.state(slug), "EXECUTING")
        tid = self.make("docs", ["backend"], ["backend/docs/**"], slug=slug)
        self.eng.check_r13(slug)
        self.assertEqual(self.state(slug), "EXECUTING")
        self.sql("UPDATE tasks SET state='COMPLETED' WHERE id=?", (tid,))
        self.eng.check_r13(slug)
        self.assertEqual(self.state(slug), "VERIFYING")
        self.assertEqual(self.cycles(slug), [])

    def test_AC_ORC_01i_a_gherkin_edit_at_the_last_moment_wins_over_r13(self):
        self.setup_cycles({"Remaining": "CYCLE_ACCEPTED", "Carry": "CYCLE_ACCEPTED", "request_form": "CYCLE_ACCEPTED"})
        p = self.sdir() / "features" / "balance.feature"
        p.write_text(p.read_text().replace("Given x", "Given y", 1))
        self.eng.next_step(SLUG)
        self.assertEqual(self.state(), "GHERKIN_REVIEW")
        self.assertEqual(self.rules()[-1], "R18")
        self.assertNotIn("VERIFYING", [e["payload"]["to"] for e in self.events("run.state_changed")])


class Concurrency(PDX):
    def two_repo_run(self, **kw):
        kw.setdefault("policies", POLICY2)
        return self.boot_x(repos=TWO_REPOS, **kw)

    def test_AC_AGT_07p_two_cycles_in_different_repos_run_in_parallel(self):
        self.two_repo_run()
        self.prepare()
        self.targeted(report("Remaining", "failure"), repo="backend")
        self.eng.run_task(self.tid("tdd_red", "Remaining"))
        self.assertEqual(self.cstate("Remaining"), "RED_VERIFIED")
        self.targeted(all_pass(), repo="backend")
        self.targeted(report("request_form", "failure"), repo="frontend")
        (self.ws / self.BIN / "faketest.log").unlink()
        self.agent(sleep=2, mark=True)
        green, red = self.tid("tdd_green", "Remaining"), self.tid("tdd_red", "request_form")
        procs = [self.popen("task", "run", green), self.popen("task", "run", red)]
        for p in procs:
            self.assertEqual(self.finish(p)[0], 0)
        marks = [json.loads((self.ws / f"mark-{t}.json").read_text()) for t in (green, red)]
        self.assertLess(marks[0][0], marks[1][1])
        self.assertLess(marks[1][0], marks[0][1])
        self.assertEqual(self.cstate("Remaining"), "GREEN_VERIFIED")
        self.assertEqual(self.cstate("request_form"), "RED_VERIFIED")
        by_repo = {}
        for entry in self.tool_log():
            by_repo.setdefault(entry["repo"], []).append(entry["mode"])
        self.assertEqual(by_repo, {"backend": ["targeted"], "frontend": ["full", "targeted"]})

    def test_AC_AGT_07q_a_task_overlapping_a_running_cycle_task_waits(self):
        self.two_repo_run()
        self.prepare()
        self.targeted(report("Remaining", "failure"), repo="backend")
        self.eng.run_task(self.tid("tdd_red", "Remaining"))
        green = self.tid("tdd_green", "Remaining")
        self.mark_running(green)
        hid = self.make("hardener", ["backend"], ["backend/**"])
        self.eng.queue_task(hid)
        with self.assertRaises(SentinelError) as cm:
            self.eng.run_task(hid)
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("E_PRECONDITION", 5))
        self.assertIn(green, cm.exception.message)
        self.assertIn("backend/src/main/**", cm.exception.message)
        self.assertIn("backend/**", cm.exception.message)
        self.assertEqual(self.task(hid)["state"], "QUEUED")

    def test_AC_AGT_07r_two_cycles_in_one_repo_never_run_at_once(self):
        self.two_repo_run(policies={"max_parallel_tasks": 4})
        self.prepare()
        remaining = self.cycle("Remaining")["id"]
        self.sql("UPDATE cycles SET state='GREEN_RUNNING' WHERE id=?", (remaining,))
        carry_red = self.tid("tdd_red", "Carry")
        with self.assertRaises(SentinelError) as cm:
            self.eng.run_task(carry_red)
        self.assertEqual(cm.exception.code, "E_TRANSITION")
        self.assertIn(f"cycle {remaining}", cm.exception.message)
        self.assertEqual(cm.exception.exit_code, 5)

    def test_AC_AGT_07s_the_parallel_limit_still_applies_to_disjoint_cycles(self):
        self.two_repo_run(policies={"max_parallel_tasks": 1})
        self.prepare()
        self.targeted(report("Remaining", "failure"), repo="backend")
        self.eng.run_task(self.tid("tdd_red", "Remaining"))
        green = self.tid("tdd_green", "Remaining")
        self.mark_running(green)
        with self.assertRaises(SentinelError) as cm:
            self.eng.run_task(self.tid("tdd_red", "request_form"))
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("E_PRECONDITION", 5))
        self.assertIn("max_parallel_tasks 1", cm.exception.message)


class Invalidation(PDX):
    def test_AC_SM_05f_r17_and_r18_cancel_running_tdd_tasks(self):
        rows = [("spec.md", "R17", "SPECIFICATION_REVIEW"), ("features/balance.feature", "R18", "GHERKIN_REVIEW")]
        for i, (name, rule, state) in enumerate(rows):
            with self.subTest(rule):
                if i:
                    self.reset_ws()
                self.boot_x(repos=TWO_REPOS, policies=POLICY2)
                self.prepare()
                self.targeted(report("Remaining", "failure"), repo="backend")
                self.eng.run_task(self.tid("tdd_red", "Remaining"))
                self.set_cycle("Carry", state="CYCLE_ACCEPTED")
                self.agent(sleep=60)
                green, red = self.tid("tdd_green", "Remaining"), self.tid("tdd_red", "request_form")
                p = self.popen("task", "run", green)
                self.assertTrue(wait_until(lambda: self.task(green)["state"] == "RUNNING" and self.task(green)["pid"], 15))
                pid = self.task(green)["pid"]
                path = self.sdir() / name
                path.write_text(path.read_text() + "\nedit\n")
                self.eng.load_run(SLUG)
                self.assertEqual(self.state(), state)
                self.assertEqual(self.rules()[-1], rule)
                for tid in (green, red):
                    self.assertEqual(self.task(tid)["state"], "CANCELLED")
                    self.assertEqual(self.task(tid)["reason"], "approval invalidated")
                self.assertTrue(wait_until(lambda: not alive(pid), 15))
                for label in ("Remaining", "request_form"):
                    c = self.cycle(label)
                    self.assertEqual((c["state"], c["reason"]), ("REJECTED", "approval invalidated"))
                self.assertEqual(self.cstate("Carry"), "CYCLE_ACCEPTED")
                self.assertTrue((self.ws / "backend/src/test/java/leave/RemainingBalanceTest.java").exists())
                self.finish(p, 30)

    def test_AC_SM_05g_re_approval_keeps_accepted_cycles_whose_scenarios_did_not_change(self):
        rows = [("Employee sees remaining days", "Given x", "Given w", True),
                ("Unused days carry over", "Given x", "Given w", False)]
        for i, (scenario, old, new, kept) in enumerate(rows):
            with self.subTest(scenario):
                if i:
                    self.reset_ws()
                self.boot_x(repos=TWO_REPOS)
                self.prepare()
                self.set_cycle("Carry", state="CYCLE_ACCEPTED")
                carry = self.cycle("Carry")["id"]
                p = self.sdir() / "features" / "balance.feature"
                text = p.read_text()
                head = f"Scenario: {scenario}\n      {old}"
                self.assertIn(head, text)
                p.write_text(text.replace(head, f"Scenario: {scenario}\n      {new}", 1))
                self.eng.load_run(SLUG)
                self.assertEqual(self.state(), "GHERKIN_REVIEW")
                self.approve("gherkin")
                self.eng.advance(SLUG)
                self.assertEqual(self.state(), "EXECUTING")
                carries = [c for c in self.cycles() if "Carry" in c["behavior"]]
                if kept:
                    self.assertEqual([(c["id"], c["state"]) for c in carries], [(carry, "CYCLE_ACCEPTED")])
                else:
                    self.assertEqual([c["state"] for c in carries], ["CYCLE_ACCEPTED", "PLANNED"])
                self.assertEqual([c["state"] for c in self.cycles() if "Remaining" in c["behavior"]][-1], "PLANNED")


class Recovery(PDX):
    def test_AC_ORC_07d_sentinel_dies_after_a_task_but_before_verification(self):
        gid = self.to_red_verified()
        self.targeted(all_pass())
        real = self.eng.verify_phase
        self.eng.verify_phase = lambda task_id: None  # the process died right after the task was finished
        self.eng.run_task(gid)
        self.eng.verify_phase = real
        self.assertEqual((self.task(gid)["state"], self.cstate("Remaining")), ("COMPLETED", "GREEN_RUNNING"))
        self.assertEqual(self.evidence("green"), [])
        self.eng.next_step(SLUG)
        self.assertEqual(len(self.evidence("green")), 1)
        self.assertEqual(self.cstate("Remaining"), "GREEN_VERIFIED")
        self.assertEqual(len(self.tdd_tasks("tdd_green", "Remaining")), 1)
        self.assertEqual([t["state"] for t in self.tdd_tasks("tdd_refactor", "Remaining")], ["QUEUED"])


class Config(PDX):
    def test_AC_CFG_11a_a_config_without_tdd_keys_or_glob_overrides_stays_valid(self):
        import jsonschema
        schema = json.loads((Path(__file__).resolve().parents[1] / "sentinel/core/schema/config.schema.json").read_text())
        cfg = {"version": 1, "shape": "single", "repos": [{"id": "backend", "path": "backend", "role": "backend", "profile": "spring-gradle"}],
               "limits": {"review_rounds": 2}}
        jsonschema.validate(cfg, schema)
        self.assertNotIn("tdd", cfg)
        self.assertEqual([retry_cap(cfg, r) for r in ("tdd_red", "tdd_green", "tdd_refactor")], [2, 3, 2])


if __name__ == "__main__":
    unittest.main()
