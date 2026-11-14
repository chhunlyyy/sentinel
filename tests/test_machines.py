import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sentinel", "scripts"))

import machines as m  # noqa: E402
from errors import SentinelError  # noqa: E402

E, O, H = m.ENGINE, m.ORCHESTRATOR, m.HUMAN


class Base(unittest.TestCase):
    def refused(self, code, fn, *args):
        with self.assertRaises(SentinelError) as cx:
            fn(*args)
        self.assertEqual(cx.exception.code, code)
        return cx.exception


class RunMachine(Base):
    def test_AC_ORC_01a_orchestrator_triages(self):
        self.assertEqual(m.check_run("CREATED", "TRIAGED", O), "R2")

    def test_AC_ORC_01c_jumping_over_gates_is_refused(self):
        rows = [("CREATED", "EXECUTING"), ("TRIAGED", "SPECIFICATION_APPROVED"),
                ("SPECIFICATION_REVIEW", "GHERKIN_REVIEW"), ("SPECIFICATION_APPROVED", "EXECUTING"),
                ("GHERKIN_REVIEW", "EXECUTING")]
        for frm, to in rows:
            with self.subTest(frm=frm, to=to):
                e = self.refused("E_TRANSITION", m.check_run, frm, to, O)
                self.assertEqual(e.details["from"], frm)
                self.assertEqual(e.details["to"], to)

    def test_AC_ORC_01d_finished_run_cannot_move(self):
        for final in ("COMPLETED", "FAILED", "CANCELLED"):
            for actor in (O, E, H):
                with self.subTest(final=final, actor=actor):
                    self.refused("E_TRANSITION", m.check_run, final, "TRIAGED", actor)

    def test_AC_ORC_01d_completed_only_self_loop_for_acceptance(self):
        self.assertEqual(m.check_run("COMPLETED", "COMPLETED", H), "R25")
        self.refused("E_ACTOR", m.check_run, "COMPLETED", "COMPLETED", O)
        for to in m.RUN_STATES:
            if to != "COMPLETED":
                with self.subTest(to=to):
                    self.refused("E_TRANSITION", m.check_run, "COMPLETED", to, H)

    def test_AC_ORC_01e_unknown_state_refused(self):
        self.refused("E_TRANSITION", m.check_run, "CREATED", "DONE", O)
        self.refused("E_TRANSITION", m.check_run, "NOPE", "TRIAGED", O)

    def test_AC_ORC_02a_orchestrator_cannot_approve_spec(self):
        e = self.refused("E_ACTOR", m.check_run, "SPECIFICATION_REVIEW", "SPECIFICATION_APPROVED", O)
        self.assertEqual(e.details["actor"], O)
        self.assertEqual(list(e.details["allowed"]), [H])

    def test_AC_ORC_02b_orchestrator_cannot_cancel(self):
        self.refused("E_ACTOR", m.check_run, "EXECUTING", "CANCELLED", O)

    def test_AC_ORC_02c_human_can_cancel_any_active(self):
        for s in m.RUN_ACTIVE:
            with self.subTest(state=s):
                self.assertIn(m.check_run(s, "CANCELLED", H), ("R7", "R11", "R23"))

    def test_any_active_rows_expand(self):
        for s in m.RUN_ACTIVE:
            with self.subTest(state=s):
                self.assertEqual(m.check_run(s, "FAILED", E), "R24")
                if s != "NEEDS_HUMAN":
                    self.assertEqual(m.check_run(s, "NEEDS_HUMAN", E), "R19")
                if s != "BLOCKED":
                    self.assertEqual(m.check_run(s, "BLOCKED", E), "R21")
        self.refused("E_TRANSITION", m.check_run, "NEEDS_HUMAN", "NEEDS_HUMAN", E)

    def test_previous_state_rows(self):
        for to in m.RUN_ACTIVE - {"NEEDS_HUMAN", "BLOCKED"}:
            with self.subTest(to=to):
                self.assertEqual(m.check_run("NEEDS_HUMAN", to, H), "R20")
                self.assertEqual(m.check_run("BLOCKED", to, H), "R22")
                self.assertIn(m.check_run("BLOCKED", to, E), ("R22", "R17"))
                if to != "SPECIFICATION_REVIEW":  # R17 lets the engine reach it from any active state
                    self.refused("E_ACTOR", m.check_run, "NEEDS_HUMAN", to, E)

    def test_docs_only_R12d(self):
        self.assertEqual(m.check_run("SPECIFICATION_APPROVED", "EXECUTING", E), "R12d")

    def test_every_contract_row_accepted_for_listed_actors(self):
        rows = [
            ("R2", "CREATED", "TRIAGED", (O,)), ("R3", "TRIAGED", "PLANNED", (O, E)),
            ("R4", "PLANNED", "SPECIFICATION_REVIEW", (E,)),
            ("R5", "SPECIFICATION_REVIEW", "SPECIFICATION_APPROVED", (H,)),
            ("R6", "SPECIFICATION_REVIEW", "PLANNED", (H,)),
            ("R7", "SPECIFICATION_REVIEW", "CANCELLED", (H,)),
            ("R8", "SPECIFICATION_APPROVED", "GHERKIN_REVIEW", (E,)),
            ("R9", "GHERKIN_REVIEW", "GHERKIN_APPROVED", (H,)),
            ("R10", "GHERKIN_REVIEW", "SPECIFICATION_APPROVED", (H,)),
            ("R11", "GHERKIN_REVIEW", "CANCELLED", (H,)),
            ("R12", "GHERKIN_APPROVED", "EXECUTING", (E,)),
            ("R13", "EXECUTING", "VERIFYING", (E,)), ("R14", "VERIFYING", "REVIEWING", (E,)),
            ("R15", "REVIEWING", "COMPLETED", (E,)),
            ("R16", "VERIFYING", "EXECUTING", (E,)), ("R16", "REVIEWING", "EXECUTING", (E,)),
            ("R25", "COMPLETED", "COMPLETED", (H,)),
        ]
        for s in ("GHERKIN_APPROVED", "EXECUTING", "VERIFYING", "REVIEWING"):
            rows.append(("R18", s, "GHERKIN_REVIEW", (E,)))
        for s in m.RUN_ACTIVE - {"SPECIFICATION_REVIEW"}:
            rows.append(("R17", s, "SPECIFICATION_REVIEW", (E,)))
        for rid, frm, to, actors in rows:
            for a in actors:
                with self.subTest(rule=rid, frm=frm, to=to, actor=a):
                    got = m.check_run(frm, to, a)
                    self.assertTrue(got == rid or (rid == "R17" and got in ("R4", "R17")) or
                                    (rid == "R18" and got in ("R18", "R17")), got)
            for a in {O, E, H} - set(actors):
                with self.subTest(rule=rid, frm=frm, to=to, refused=a):
                    try:
                        got = m.check_run(frm, to, a)
                    except SentinelError as e:
                        self.assertEqual(e.code, "E_ACTOR")
                    else:  # another rule may allow it (e.g. R3 / R6 overlaps) - must differ from rid
                        self.assertNotEqual(got, rid)


class TierRules(Base):
    def test_AC_ORC_04a_highest_factor_wins(self):
        rows = [({"repos": 1, "files": 1}, 1, 1), ({"repos": 1, "files": 2}, 1, 2),
                ({"repos": 1, "files": 2, "auth": "new_rules"}, 2, 4), ({"repos": 2, "files": 1}, 4, 4)]
        for factors, req, tier in rows:
            with self.subTest(factors=factors, req=req):
                self.assertEqual(m.compute_tier(factors, req), tier)

    def test_matrix_bands_and_string_values(self):
        self.assertEqual(m.compute_tier({"files": "9"}), 4)
        self.assertEqual(m.compute_tier({"files": "5"}), 3)
        self.assertEqual(m.compute_tier({"repos": "2"}), 4)
        self.assertEqual(m.compute_tier({"migration": "additive"}), 3)
        self.assertEqual(m.compute_tier({"security": "high"}), 4)
        self.assertEqual(m.compute_tier({"regression": "low"}), 2)
        self.assertEqual(m.compute_tier({"logic": "complex"}), 4)
        self.assertEqual(m.compute_tier({}), 1)
        self.assertEqual(m.compute_tier({}, 3), 3)

    def test_unknown_factor_rejected(self):
        self.refused("E_VALIDATION", m.compute_tier, {"colour": "red"})
        self.refused("E_VALIDATION", m.compute_tier, {"auth": "sometimes"})
        self.refused("E_VALIDATION", m.compute_tier, {"files": "many"})
        self.refused("E_VALIDATION", m.compute_tier, {"files": 1}, 7)

    def test_AC_ORC_04b_lowering_refused(self):
        self.refused("E_POLICY", m.check_tier_change, 3, 2)
        self.assertEqual(m.check_tier_change(3, 3), 3)
        self.assertEqual(m.check_tier_change(3, 4), 4)
        self.assertEqual(m.check_tier_change(None, 2), 2)


class TaskMachine(Base):
    def test_AC_SM_03a_allowed(self):
        rows = [("CREATED", "QUEUED", E), ("QUEUED", "RUNNING", E), ("RUNNING", "WAITING_FOR_INPUT", E),
                ("WAITING_FOR_INPUT", "RUNNING", O), ("WAITING_FOR_INPUT", "RUNNING", H),
                ("RUNNING", "COMPLETED", E), ("RUNNING", "FAILED", E), ("QUEUED", "CANCELLED", H),
                ("WAITING_FOR_INPUT", "COMPLETED", E), ("WAITING_FOR_INPUT", "FAILED", E),
                ("RUNNING", "BLOCKED", E), ("BLOCKED", "CANCELLED", E)]
        for frm, to, a in rows:
            with self.subTest(frm=frm, to=to, actor=a):
                self.assertIsNone(m.check_task(frm, to, a))

    def test_AC_SM_03b_orchestrator_cannot_complete(self):
        self.refused("E_ACTOR", m.check_task, "RUNNING", "COMPLETED", O)

    def test_AC_SM_03c_completed_cannot_restart(self):
        self.refused("E_TRANSITION", m.check_task, "COMPLETED", "RUNNING", E)
        self.refused("E_TRANSITION", m.check_task, "COMPLETED", "CANCELLED", H)
        self.refused("E_TRANSITION", m.check_task, "CREATED", "NOPE", E)


class ApprovalMachine(Base):
    def test_AC_SM_04a_only_human_decides(self):
        self.assertIsNone(m.check_approval("IN_REVIEW", "APPROVED", H))
        for a in (O, E):
            with self.subTest(actor=a):
                self.refused("E_ACTOR", m.check_approval, "IN_REVIEW", "APPROVED", a)
        for to in ("CHANGES_REQUESTED", "REJECTED"):
            self.assertIsNone(m.check_approval("IN_REVIEW", to, H))

    def test_AC_SM_04b_engine_invalidates(self):
        self.assertIsNone(m.check_approval("APPROVED", "INVALIDATED", E))
        self.assertIsNone(m.check_approval("DRAFT", "IN_REVIEW", E))
        self.assertIsNone(m.check_approval("CHANGES_REQUESTED", "DRAFT", E))

    def test_AC_SM_04c_rejected_stays_rejected(self):
        self.refused("E_TRANSITION", m.check_approval, "REJECTED", "APPROVED", H)


class CycleMachine(Base):
    def test_AC_SM_05a_walk(self):
        path = ["PLANNED", "RED_RUNNING", "RED_VERIFIED", "GREEN_RUNNING", "GREEN_VERIFIED",
                "REFACTOR_RUNNING", "REFACTOR_VERIFIED", "CYCLE_ACCEPTED"]
        for a, b in zip(path, path[1:]):
            with self.subTest(frm=a, to=b):
                self.assertIsNone(m.check_cycle(a, b, E))

    def test_AC_SM_05b_no_skipping(self):
        for frm, to in [("PLANNED", "GREEN_RUNNING"), ("RED_RUNNING", "GREEN_RUNNING"),
                        ("RED_VERIFIED", "REFACTOR_RUNNING"), ("GREEN_VERIFIED", "CYCLE_ACCEPTED")]:
            with self.subTest(frm=frm, to=to):
                self.refused("E_TRANSITION", m.check_cycle, frm, to, E)

    def test_AC_SM_05c_only_engine(self):
        for a in (O, H):
            self.refused("E_ACTOR", m.check_cycle, "RED_RUNNING", "RED_VERIFIED", a)

    def test_retry_and_reject(self):
        self.assertIsNone(m.check_cycle("RED_RUNNING", "PLANNED", E))
        for s in ("RED_RUNNING", "GREEN_RUNNING", "REFACTOR_RUNNING"):
            self.assertIsNone(m.check_cycle(s, "REJECTED", E))
        self.refused("E_TRANSITION", m.check_cycle, "RED_VERIFIED", "REJECTED", E)


class Acceptance(Base):
    def test_AC_SM_02_execution_status_for(self):
        self.assertEqual(m.execution_status_for("COMPLETED"), "completed")
        self.assertEqual(m.execution_status_for("FAILED"), "failed")
        self.assertEqual(m.execution_status_for("CANCELLED"), "cancelled")
        self.assertEqual(m.execution_status_for("EXECUTING"), "running")

    def test_AC_SM_02c_orchestrator_cannot_set(self):
        self.refused("E_ACTOR", m.check_acceptance_change, "rejected", "accepted", O)
        self.refused("E_ACTOR", m.check_acceptance_change, "pending", "accepted", E)

    def test_AC_SM_02d_rejected_never_accepted(self):
        self.refused("E_PRECONDITION", m.check_acceptance_change, "rejected", "accepted", H)

    def test_human_allowed_changes(self):
        self.assertIsNone(m.check_acceptance_change("pending", "accepted", H))
        self.assertIsNone(m.check_acceptance_change("pending", "rejected", H))
        self.assertIsNone(m.check_acceptance_change("accepted", "rejected", H))

    def test_unknown_acceptance_value(self):
        self.refused("E_VALIDATION", m.check_acceptance_change, "pending", "maybe", H)

    def test_AC_SM_02e_finish_outcome(self):
        self.assertEqual(m.finish_outcome("EXECUTING", "stopped"), ("CANCELLED", "cancelled", "rejected"))
        self.assertEqual(m.finish_outcome("EXECUTING", "abandoned"), ("CANCELLED", "cancelled", "rejected"))
        self.assertEqual(m.finish_outcome("COMPLETED", "passed"), ("COMPLETED", "completed", None))

    def test_AC_SM_02f_passed_unfinished_refused(self):
        for s in ("EXECUTING", "FAILED", "CANCELLED"):
            with self.subTest(state=s):
                self.refused("E_PRECONDITION", m.finish_outcome, s, "passed")

    def test_finish_outcome_edges(self):
        self.refused("E_PRECONDITION", m.finish_outcome, "COMPLETED", "stopped")
        self.refused("E_VALIDATION", m.finish_outcome, "EXECUTING", "weird")


if __name__ == "__main__":
    unittest.main()
