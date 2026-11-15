"""Phase E: reviewer and QA stages and finding routing (review_qa.feature)."""
import json
import unittest

from pe_helpers import PE, SLUG
from errors import SentinelError

BAL = "backend/src/main/java/leave/Balance.java"
FORM = "frontend/src/LeaveForm.tsx"


def finding(sev, text, loc, **kw):
    return {"severity": sev, "text": text, "location": loc, **kw}


class Review(PE):
    def to_review(self, tier=3, **kw):
        self.boot_ver(tier=tier, **kw)
        self.change()
        for c in self.cycles():
            path = FORM if c["repo_id"] == "frontend" else BAL
            self.eng.reg.add_trace_link(self.run_row()["id"], "cycle", c["id"], "file", path)
        res = self.verify()
        assert res["exit"] == 0 and self.state() == "REVIEWING", res
        return self.chain()

    def chain(self):
        return {t["role"]: t for t in self.new_tasks()}

    def reviewer_says(self, *findings, role="reviewer"):
        self.agent_exec(role, f"write_result(findings={list(findings)!r})")

    def run_role(self, role, **kw):
        tid = self.chain_task(role)["id"]
        return self.eng.run_task(tid)

    def chain_task(self, role):
        return [t for t in self.new_tasks() if t["role"] == role][-1]

    def complete(self, role):
        self.eng.reg.update_row("tasks", self.chain_task(role)["id"], state="COMPLETED")
        self.eng.bookkeep(SLUG)

    def r16(self):
        return [e for e in self.events("run.state_changed") if e["payload"]["transition"] == "R16"]

    def test_AC_AGT_01f_review_tasks_per_tier(self):
        for tier, roles in [(3, ["reviewer", "qa", "promotion", "docs"]),
                            (4, ["reviewer", "qa", "promotion", "docs", "rollout", "retrospective"])]:
            with self.subTest(tier=tier):
                self.to_review(tier)
                tasks = [t for t in self.new_tasks()]
                self.assertEqual([t["role"] for t in tasks], roles)
                for prev, t in zip(tasks, tasks[1:]):
                    self.assertEqual(self.eng.reg.task_deps(t["id"]), [prev["id"]])
                self.reset_ws()

    def test_AC_AGT_01g_low_tiers_complete_without_review_tasks(self):
        for tier in (1, 2):
            with self.subTest(tier=tier):
                self.boot_ver(tier=tier)
                self.change()
                self.verify()
                self.assertEqual(self.state(), "REVIEWING")
                step = self.eng.next_step(SLUG)
                self.assertEqual(step["kind"], "done")
                self.assertFalse(self.new_tasks("reviewer") or self.new_tasks("qa"))
                self.assertEqual(self.state(), "COMPLETED")
                self.assertEqual(self.events("run.state_changed")[-1]["payload"]["transition"], "R15")
                self.reset_ws()

    def test_AC_AGT_01h_review_task_inputs_and_write_scopes(self):
        self.to_review(4)
        want = {"reviewer": [], "qa": [], "promotion": [".sentinel/shared/regression/**"],
                "docs": ["backend/docs/**", "backend/CHANGELOG.md", "frontend/docs/**", "frontend/CHANGELOG.md"],
                "rollout": [], "retrospective": [".sentinel/shared/proposals/**"]}
        for role, write in want.items():
            with self.subTest(role=role):
                doc = self.task_json(self.chain_task(role)["id"])
                self.assertEqual(doc["permissions"]["write"], write)
                inp = doc["input"]
                self.assertIn("sha256", inp["specification"])
                self.assertIn("sha256", inp["gherkin"])
                self.assertEqual(sorted(inp["baseline"]), ["backend", "frontend"])
                self.assertEqual(inp["verification_round"], 1)

    def test_AC_AGT_01i_qa_depth_follows_the_tier(self):
        for tier, mode in [(3, "targeted"), (4, "full")]:
            with self.subTest(tier=tier):
                self.to_review(tier)
                brief = (self.tdir(self.chain_task("qa")["id"]) / "brief.md").read_text()
                self.assertIn(f"QA mode: {mode}", brief)
                self.reset_ws()

    def test_AC_ORC_05o_minor_findings_do_not_stop_the_run(self):
        self.to_review()
        self.reviewer_says(finding("minor", "nit", f"{BAL}:14"))
        self.run_role("reviewer")
        rows = self.eng.reg.rows("findings", run_id=self.run_row()["id"])
        self.assertEqual([(r["source"], r["severity"], r["location"], r["state"]) for r in rows], [("reviewer", "minor", f"{BAL}:14", "open")])
        self.assertTrue(self.events("finding.created"))
        self.assertEqual(self.state(), "REVIEWING")
        self.assertEqual(self.chain_task("qa")["state"], "QUEUED")

    def test_AC_ORC_01m_a_blocker_sends_the_run_back_R16(self):
        self.to_review()
        self.reviewer_says(finding("blocker", "balance can go negative", f"{BAL}:22"))
        self.run_role("reviewer")
        self.assertEqual(self.state(), "NEEDS_HUMAN")  # tier 3 blocker raises the tier (ORC-03c); see that test
        self.assertEqual(self.run_row()["tier"], 4)

    def test_AC_ORC_01m_a_major_finding_sends_the_run_back_R16(self):
        self.to_review()
        self.reviewer_says(finding("major", "balance can go negative", f"{BAL}:22"))
        self.run_role("reviewer")
        self.assertEqual(self.state(), "EXECUTING")
        ev = self.r16()
        self.assertEqual((len(ev), ev[0]["actor"]), (1, "engine"))
        new = [c for c in self.cycles() if c["state"] == "PLANNED"]
        self.assertEqual([c["behavior"] for c in new], ["features/balance.feature :: Rule Remaining balance"])
        f = self.eng.reg.rows("findings", run_id=self.run_row()["id"])[0]
        self.assertEqual((f["state"], f["routed_to"]), ("routed", new[0]["id"]))
        self.assertEqual(self.chain_task("qa")["state"], "CANCELLED")
        self.assertEqual(self.chain_task("qa")["reason"], "review finding routed")
        self.assertEqual(len(self.events("review.routed")), 1)

    def test_AC_ORC_01n_the_finding_is_resolved_and_the_reviewer_checks_again(self):
        self.to_review()
        self.reviewer_says(finding("major", "balance can go negative", f"{BAL}:22"))
        self.run_role("reviewer")
        new = [c for c in self.cycles() if c["state"] == "PLANNED"][0]
        self.eng.reg.update_row("cycles", new["id"], state="CYCLE_ACCEPTED", tests=json.dumps(["RemainingBalanceTest.employeeSeesRemainingDays"]))
        self.eng.bookkeep(SLUG)
        self.assertEqual(self.state(), "VERIFYING")
        self.assertEqual(self.verify()["exit"], 0)
        f = self.eng.reg.rows("findings", run_id=self.run_row()["id"])[0]
        self.assertEqual(f["state"], "resolved")
        self.assertEqual(self.state(), "REVIEWING")
        reviewer = self.chain_task("reviewer")
        self.assertEqual(reviewer["state"], "QUEUED")
        self.assertIn(f["id"], (self.tdir(reviewer["id"]) / "brief.md").read_text())
        self.assertEqual(self.finished_round_no(), 2)

    def finished_round_no(self):
        return self.eng.finished_round(self.run_row())["round"]

    def test_AC_ORC_01o_several_findings_on_one_behavior_give_one_cycle(self):
        self.to_review()
        self.reviewer_says(finding("major", "a", f"{BAL}:1"), finding("major", "b", f"{BAL}:2"), finding("major", "c", f"{FORM}:3"))
        self.run_role("reviewer")
        new = sorted(c["behavior"] for c in self.cycles() if c["state"] == "PLANNED")
        self.assertEqual(new, ["features/balance.feature :: Rule Remaining balance", "features/request_form.feature"])
        self.assertEqual(len(self.r16()), 1)
        rows = self.eng.reg.rows("findings", run_id=self.run_row()["id"])
        self.assertEqual(len({r["cycle_id"] for r in rows[:2]}), 1)

    def test_AC_ORC_01p_a_finding_no_cycle_owns_goes_to_a_human(self):
        self.to_review()
        self.reviewer_says(finding("major", "bad yaml", "backend/src/main/resources/application.yml:3"))
        self.run_role("reviewer")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertIn("finding has no owning cycle", self.last_reason())
        self.assertIn("bad yaml", self.last_reason())
        self.assertFalse([c for c in self.cycles() if c["state"] == "PLANNED"])

    def test_AC_ORC_01q_qa_findings_route_by_category(self):
        rows = [("major", "code_bug", "EXECUTING"), ("major", "spec_gap", "NEEDS_HUMAN"), ("blocker", None, "EXECUTING"),
                ("minor", "code_bug", "REVIEWING")]
        for sev, cat, state in rows:
            with self.subTest(sev=sev, cat=cat):
                self.to_review()
                self.complete("reviewer")
                kw = {"category": cat} if cat else {}
                self.reviewer_says(finding(sev, "form broken", f"{FORM}:40", **kw), role="qa")
                self.run_role("qa")
                self.assertEqual(self.state(), state)
                if state == "EXECUTING":
                    new = [c for c in self.cycles() if c["state"] == "PLANNED"]
                    self.assertEqual([c["behavior"] for c in new], ["features/request_form.feature"])
                    self.eng.bookkeep(SLUG)
                    red = [t for t in self.eng.reg.rows("tasks", cycle_id=new[0]["id"], role="tdd_red")][0]
                    self.assertIn("form broken", (self.tdir(red["id"]) / "brief.md").read_text())
                elif state == "NEEDS_HUMAN":
                    self.assertIn("QA spec gap", self.last_reason())
                    self.assertIn("form broken", self.last_reason())
                    self.assertFalse([c for c in self.cycles() if c["state"] == "PLANNED"])
                else:
                    self.assertEqual(self.chain_task("promotion")["state"], "QUEUED")
                self.reset_ws()

    def test_AC_ORC_01r_nobody_but_the_engine_sends_the_run_back(self):
        self.to_review()
        with self.assertRaises(SentinelError) as c:
            self.eng.request_state(SLUG, "EXECUTING", "orchestrator")
        self.assertEqual(c.exception.code, "E_ACTOR")
        self.assertEqual(self.state(), "REVIEWING")

    def test_AC_ORC_03c_a_review_blocker_at_tier_3_raises_the_tier(self):
        self.to_review()
        self.reviewer_says(finding("blocker", "bad", f"{BAL}:22"))
        self.run_role("reviewer")
        self.assertEqual(self.run_row()["tier"], 4)
        ev = self.events("run.tier_raised")[-1]["payload"]
        self.assertEqual((ev["from"], ev["to"]), (3, 4))
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertEqual(self.last_reason(), "security gate (tier 4) needs human approval before execution resumes")

    def drive_to_cap(self, source):
        """Every pass of `source` reports a major finding; every new cycle and verification round passes."""
        role = "reviewer" if source == "reviewer" else "qa"
        for _ in range(12):
            step = self.eng.next_step(SLUG)
            if step["kind"] == "human":
                return step
            if step["kind"] == "orchestrator":
                self.verify()
            elif step["kind"] == "task":
                t = self.task(step["task"])
                if t["role"] == role:
                    self.reviewer_says(finding("major", "balance can go negative", f"{BAL}:22"), role=role)
                    self.eng.run_task(t["id"])
                elif t["cycle_id"] is None:
                    self.eng.reg.update_row("tasks", t["id"], state="COMPLETED")
                    self.eng.bookkeep(SLUG)
                else:
                    break
            if self.state() == "EXECUTING":
                for c in self.cycles():
                    if c["state"] == "PLANNED":
                        self.eng.reg.update_row("cycles", c["id"], state="CYCLE_ACCEPTED", tests=json.dumps(["RemainingBalanceTest.employeeSeesRemainingDays"]))
                        self.eng.reg.add_trace_link(self.run_row()["id"], "cycle", c["id"], "file", BAL)
                self.eng.bookkeep(SLUG)
            if source == "qa" and self.state() == "REVIEWING":
                done = [t for t in self.new_tasks("reviewer") if t["state"] == "QUEUED"]
                for t in done:
                    self.eng.reg.update_row("tasks", t["id"], state="COMPLETED")
                self.eng.bookkeep(SLUG)
        return None

    def test_AC_ORC_05p_round_caps(self):
        for key, cap, source, routed in [("review_rounds", 1, "reviewer", 1), ("review_rounds", 2, "reviewer", 2), ("qa_rounds", 1, "qa", 1)]:
            with self.subTest(key=key, cap=cap):
                self.to_review(4, limits={key: cap})
                self.approve_security()
                if source == "qa":
                    self.complete("reviewer")
                step = self.drive_to_cap(source)
                self.assertIsNotNone(step)
                self.assertEqual(len([e for e in self.events("review.routed") if e["payload"]["source"] == source]), routed)
                self.assertEqual(self.state(), "NEEDS_HUMAN")
                self.assertIn(f"{source} round cap reached", self.last_reason())
                self.assertIn("balance can go negative", self.last_reason())
                self.reset_ws()

    def approve_security(self):
        self.eng.reg.insert_row("approvals", {"run_id": self.run_row()["id"], "gate": "security", "state": "APPROVED", "version": 1})

    def test_AC_ORC_05q_a_waived_finding_completes_the_run_rejected(self):
        self.to_review()
        self.reviewer_says(finding("major", "balance can go negative", f"{BAL}:22"))
        self.run_role("reviewer")
        f = self.eng.reg.rows("findings", run_id=self.run_row()["id"])[0]
        # the review round cap parks the run with the finding open, back in REVIEWING
        self.eng.reg.update_row("findings", f["id"], state="open", routed_to=None, cycle_id=None)
        self.set_state("NEEDS_HUMAN")
        self.eng.reg.update_run(SLUG, previous_state="REVIEWING")
        for t in self.new_tasks():
            if t["state"] in ("CANCELLED",):
                self.eng.reg.update_row("tasks", t["id"], state="COMPLETED")
        self.eng.resolve(SLUG, user="dev", channel="tty", comment="accepted risk for pilot", waive=f["id"])
        f2 = self.eng.reg.get_row("findings", f["id"])
        self.assertEqual((f2["state"], f2["decided_by"], f2["comment"]), ("waived", "dev", "accepted risk for pilot"))
        self.assertTrue([a for a in self.audit() if a["action"] == "resolve"])
        for t in self.new_tasks():
            if t["state"] not in ("COMPLETED",):
                self.eng.reg.update_row("tasks", t["id"], state="COMPLETED")
        self.eng.next_step(SLUG)
        run = self.run_row()
        self.assertEqual((run["state"], run["acceptance_status"]), ("COMPLETED", "rejected"))
        self.assertIn("required reviews open: 1 waived major finding", self.eng.compute_acceptance(SLUG)["reasons"])

    def test_AC_ORC_06g_qa_on_real_data_waits_for_a_human(self):
        self.to_review(4, qa={"db_clone": {"databases": []}}, policies={"human_required": ["real_data_clone"]})
        self.complete("reviewer")
        out = self.eng.run_task(self.chain_task("qa")["id"])
        self.assertEqual(out["exit"], 6)
        self.assertEqual(self.chain_task("qa")["state"], "QUEUED")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertEqual(self.last_reason(), "QA needs a clone of real data (policy real_data_clone)")
        self.eng.resolve(SLUG, user="dev", channel="tty", comment="ok", approve_clone=True)
        self.assertEqual(self.state(), "REVIEWING")

    def test_AC_ORC_06h_promotion_never_pushes(self):
        self.to_review(3, state={"auto_sync_push": True, "dir": ".sentinel", "shared_mode": "local"})
        self.complete("reviewer")
        self.complete("qa")
        self.agent_exec("promotion", 'write(".sentinel/shared/regression/leave-balance.md", "x\\n")\nwrite_result()')
        self.eng.run_task(self.chain_task("promotion")["id"])
        self.assertEqual(self.chain_task("promotion")["state"], "COMPLETED")
        step = self.eng.next_step(SLUG)
        self.assertNotIn("sync push", json.dumps(step))


if __name__ == "__main__":
    unittest.main()
