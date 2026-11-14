import json
import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from engine import Engine  # noqa: E402
from errors import SentinelError  # noqa: E402

CONFIG = {"version": 1, "state": {"dir": ".sentinel", "shared_mode": "local"}, "repos": []}


def _triage_worker(args):
    ws, slug, q, barrier = args
    eng = Engine(Path(ws) / ".sentinel", ws, CONFIG)
    try:
        barrier.wait()
        eng.triage(slug, {"files": "2"}, "orchestrator")
        q.put("ok")
    except SentinelError as e:
        q.put(e.code)
    finally:
        eng.close()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.eng = Engine(self.ws / ".sentinel", self.ws, CONFIG)
        self.addCleanup(self.eng.close)

    def make(self, slug="leave-balance", state="CREATED", tier=None):
        """Create a v2 run and force it to a state/tier (test fixture only)."""
        self.eng.create_run(slug, "orchestrator", baseline={"backend": "abc"})
        fields = {"state": state}
        if tier is not None:
            fields.update(tier=tier, initial_tier=tier)
        self.eng.reg.update_run(slug, **fields)
        return slug

    def run_row(self, slug="leave-balance"):
        return self.eng.reg.get_run(slug)

    def events(self, slug="leave-balance", type="run.state_changed"):
        return self.eng.reg.list_events(self.run_row(slug)["id"], type)


class TestRunMachine(Base):
    def test_AC_ORC_01a_orchestrator_triages_created_run(self):
        self.make()
        self.eng.triage("leave-balance", {"files": "2"}, "orchestrator")
        self.assertEqual(self.run_row()["state"], "TRIAGED")
        evs = self.events()
        self.assertEqual(len(evs), 1)
        self.assertEqual((evs[0]["payload"]["from"], evs[0]["payload"]["to"]), ("CREATED", "TRIAGED"))
        self.assertEqual(evs[0]["actor"], "orchestrator")

    def test_AC_ORC_01b_event_failure_leaves_state_unchanged(self):
        self.make()
        before = len(self.eng.reg.list_events())

        def boom(*a, **k):
            raise RuntimeError("event store down")
        self.eng.reg.add_event = boom
        with self.assertRaises(RuntimeError):
            self.eng.triage("leave-balance", {"files": "2"}, "orchestrator")
        del self.eng.reg.add_event
        self.assertEqual(self.run_row()["state"], "CREATED")
        self.assertIsNone(self.run_row()["tier"])
        self.assertEqual(len(self.eng.reg.list_events()), before)

    def test_AC_ORC_02a_orchestrator_cannot_approve_spec(self):
        self.make(state="SPECIFICATION_REVIEW")
        with self.assertRaises(SentinelError) as cm:
            self.eng.request_state("leave-balance", "SPECIFICATION_APPROVED", "orchestrator")
        self.assertEqual(cm.exception.code, "E_ACTOR")
        self.assertEqual(self.run_row()["state"], "SPECIFICATION_REVIEW")

    def test_AC_ORC_02c_human_cancels_and_lock_released(self):
        released = []
        self.eng._release_lock = released.append
        self.make(state="EXECUTING")
        self.eng.request_state("leave-balance", "CANCELLED", "human")
        row = self.run_row()
        self.assertEqual((row["state"], row["execution_status"]), ("CANCELLED", "cancelled"))
        self.assertEqual(released, ["leave-balance"])

    def test_AC_ORC_03a_tier3_planning_needs_decisions(self):
        self.make(state="TRIAGED", tier=3)
        with self.assertRaises(SentinelError) as cm:
            self.eng.request_state("leave-balance", "PLANNED", "orchestrator")
        self.assertEqual(cm.exception.code, "E_PRECONDITION")
        self.assertIn("decisions.md", json.dumps(cm.exception.details))
        self.assertEqual(self.run_row()["state"], "TRIAGED")
        (self.eng.run_dir("leave-balance") / "decisions.md").write_text("# decisions\n")
        self.eng.request_state("leave-balance", "PLANNED", "orchestrator")
        self.assertEqual(self.run_row()["state"], "PLANNED")

    def test_AC_ORC_03b_tier1_plans_without_decisions(self):
        self.make("fix-typo", state="TRIAGED", tier=1)
        self.eng.request_state("fix-typo", "PLANNED", "orchestrator")
        self.assertEqual(self.run_row("fix-typo")["state"], "PLANNED")

    def test_AC_ORC_04b_lowering_tier_is_refused(self):
        self.make(state="TRIAGED", tier=3)
        with self.assertRaises(SentinelError) as cm:
            self.eng.set_tier("leave-balance", 2, "orchestrator")
        self.assertEqual(cm.exception.code, "E_POLICY")
        self.assertEqual(self.run_row()["tier"], 3)
        self.eng.set_tier("leave-balance", 4, "orchestrator")
        self.assertEqual(self.run_row()["tier"], 4)

    def test_triage_stores_tier_and_initial_tier(self):
        self.make()
        self.eng.triage("leave-balance", {"repos": "1", "files": "2", "auth": "new_rules"}, "orchestrator", requested=2)
        row = self.run_row()
        self.assertEqual((row["tier"], row["initial_tier"]), (4, 4))

    def test_undefined_transition_is_refused_and_state_kept(self):
        self.make()
        with self.assertRaises(SentinelError) as cm:
            self.eng.request_state("leave-balance", "EXECUTING", "orchestrator")
        self.assertEqual(cm.exception.code, "E_TRANSITION")
        self.assertEqual(self.run_row()["state"], "CREATED")

    def test_AC_C_36a_two_processes_triage_one_wins(self):
        self.make()
        ctx = multiprocessing.get_context("spawn")
        mgr = ctx.Manager()
        q, barrier = mgr.Queue(), mgr.Barrier(2)
        with ctx.Pool(2) as pool:
            pool.map(_triage_worker, [(str(self.ws), "leave-balance", q, barrier)] * 2)
        results = sorted([q.get(), q.get()])
        self.assertEqual(results, ["E_TRANSITION", "ok"])
        self.assertEqual(len(self.events()), 1)

    def test_R20_requires_previous_state(self):
        self.make(state="VERIFYING")
        self.eng.request_state("leave-balance", "NEEDS_HUMAN", "engine")
        self.assertEqual(self.run_row()["previous_state"], "VERIFYING")
        with self.assertRaises(SentinelError) as cm:
            self.eng.request_state("leave-balance", "EXECUTING", "human")
        self.assertEqual(cm.exception.code, "E_PRECONDITION")
        self.assertEqual(self.run_row()["state"], "NEEDS_HUMAN")
        self.eng.request_state("leave-balance", "VERIFYING", "human")
        row = self.run_row()
        self.assertEqual((row["state"], row["previous_state"]), ("VERIFYING", None))

    def test_R22_requires_previous_state(self):
        self.make(state="EXECUTING")
        self.eng.request_state("leave-balance", "BLOCKED", "engine")
        with self.assertRaises(SentinelError) as cm:
            self.eng.request_state("leave-balance", "GHERKIN_APPROVED", "engine")
        self.assertEqual(cm.exception.code, "E_PRECONDITION")
        self.assertEqual(self.run_row()["state"], "BLOCKED")
        self.eng.request_state("leave-balance", "EXECUTING", "engine")
        self.assertEqual(self.run_row()["state"], "EXECUTING")

    def test_triage_emits_run_triaged_with_factors(self):
        self.make()
        self.eng.triage("leave-balance", {"files": "2"}, "orchestrator", requested=2)
        evs = self.events(type="run.triaged")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"], {"factors": {"files": "2"}, "computed_tier": 2, "requested_tier": 2})
        self.assertEqual(self.events(type="run.tier_raised"), [])

    def test_set_tier_refuses_final_run_and_unknown_actor(self):
        self.make(state="COMPLETED", tier=2)
        with self.assertRaises(SentinelError) as cm:
            self.eng.set_tier("leave-balance", 3, "orchestrator")
        self.assertEqual(cm.exception.code, "E_TRANSITION")
        self.assertEqual(self.run_row()["tier"], 2)
        self.make("other", state="TRIAGED", tier=2)
        with self.assertRaises(SentinelError) as cm:
            self.eng.set_tier("other", 3, "robot")
        self.assertEqual(cm.exception.code, "E_ACTOR")

    def test_failed_emits_status_changed(self):
        self.make(state="EXECUTING")
        self.eng.request_state("leave-balance", "FAILED", "engine")
        evs = self.events(type="run.status_changed")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["payload"]["execution_status"], "failed")

    def test_finish_stopped_releases_lock_once(self):
        released = []
        self.eng._release_lock = released.append
        self.make(state="EXECUTING")
        self.eng.finish("leave-balance", "stopped", "human")
        self.assertEqual(released, ["leave-balance"])
        self.assertEqual(len(self.events(type="run.status_changed")), 1)


class TestStatuses(Base):
    def test_AC_SM_02c_orchestrator_cannot_set_acceptance(self):
        self.make(state="REVIEWING")
        self.eng.complete("leave-balance")
        with self.assertRaises(SentinelError) as cm:
            self.eng.set_acceptance("leave-balance", "accepted", "orchestrator")
        self.assertEqual(cm.exception.code, "E_ACTOR")
        self.assertEqual(self.run_row()["acceptance_status"], "rejected")

    def test_AC_SM_02d_human_cannot_accept_rejected_run(self):
        self.make(state="REVIEWING")
        self.eng.complete("leave-balance")
        finished = self.run_row()["finished_at"]
        self.eng.reg.insert_row("evidence", {"run_id": self.run_row()["id"], "kind": "test", "passed": 3, "failed": 0})
        for call in (lambda: self.eng.request_state("leave-balance", "COMPLETED", "human"),
                     lambda: self.eng.set_acceptance("leave-balance", "accepted", "human")):
            with self.assertRaises(SentinelError) as cm:
                call()
            self.assertEqual(cm.exception.code, "E_PRECONDITION")
            row = self.run_row()
            self.assertEqual((row["acceptance_status"], row["finished_at"]), ("rejected", finished))

    def test_self_transition_does_not_recompute(self):
        self.make(state="REVIEWING")
        self.eng.reg.insert_row("evidence", {"run_id": self.run_row()["id"], "kind": "test", "passed": 3, "failed": 0})
        self.eng.complete("leave-balance")
        before = self.run_row()
        self.eng.request_state("leave-balance", "COMPLETED", "human")
        self.assertEqual(self.run_row()["finished_at"], before["finished_at"])
        self.assertEqual(self.run_row()["acceptance_status"], "accepted")

    def test_AC_SM_02a_new_run_running_and_pending(self):
        self.eng.create_run("leave-balance", "orchestrator", baseline={"backend": "abc"})
        row = self.run_row()
        self.assertEqual((row["state"], row["execution_status"], row["acceptance_status"], row["workflow_version"]),
                         ("CREATED", "running", "pending", "2"))
        self.assertEqual(self.eng.reg.run_repos(row["id"])[0]["baseline_sha"], "abc")
        self.assertEqual(len(self.events(type="run.created")), 1)

    def test_AC_SM_02b_completion_without_evidence_is_rejected(self):
        self.make(state="REVIEWING")
        self.eng.complete("leave-balance")
        row = self.run_row()
        self.assertEqual((row["state"], row["execution_status"], row["acceptance_status"]),
                         ("COMPLETED", "completed", "rejected"))
        ev = self.events(type="run.status_changed")[-1]
        self.assertIn("verification evidence missing", ev["payload"]["reasons"])
        view = json.loads((self.eng.run_dir("leave-balance") / "state.json").read_text())
        self.assertIn("verification evidence missing", view["acceptance_reasons"])

    def test_completion_with_passing_test_evidence_is_accepted(self):
        self.make(state="REVIEWING")
        self.eng.reg.insert_row("evidence", {"run_id": self.run_row()["id"], "kind": "test", "passed": 3, "failed": 0})
        self.eng.complete("leave-balance")
        self.assertEqual(self.run_row()["acceptance_status"], "accepted")

    def test_orchestrator_cannot_complete_or_accept(self):
        self.make(state="REVIEWING")
        with self.assertRaises(SentinelError) as cm:
            self.eng.request_state("leave-balance", "COMPLETED", "orchestrator")
        self.assertEqual(cm.exception.code, "E_ACTOR")
        self.eng.complete("leave-balance")
        with self.assertRaises(SentinelError) as cm:
            self.eng.set_acceptance("leave-balance", "accepted", "orchestrator")
        self.assertEqual(cm.exception.code, "E_ACTOR")

    def test_finish_stopped_cancels_and_passed_needs_completed(self):
        self.make(state="EXECUTING")
        with self.assertRaises(SentinelError) as cm:
            self.eng.finish("leave-balance", "passed", "human")
        self.assertEqual(cm.exception.code, "E_PRECONDITION")
        self.eng.finish("leave-balance", "stopped", "human")
        row = self.run_row()
        self.assertEqual((row["execution_status"], row["acceptance_status"]), ("cancelled", "rejected"))


if __name__ == "__main__":
    unittest.main()
