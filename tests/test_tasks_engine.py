"""Phase C part 1 (PC-01): engine task lifecycle, events, R3/R5 task creation, spec hook."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from errors import SentinelError  # noqa: E402
from pc_helpers import PC, SLUG  # noqa: E402
from pb_helpers import spec_text  # noqa: E402


class Lifecycle(PC):
    def setUp(self):
        super().setUp()
        self.executing()

    def test_transitions_and_events_in_order(self):
        tid = self.make()
        self.eng.queue_task(tid)
        self.eng.start_task(tid, pid=None)
        self.write_result(tid)
        self.eng.finish_task(tid, exit_code=0)
        self.assertEqual([e["type"] for e in self.task_events(tid)],
                         ["task.created", "task.queued", "task.started", "task.finished"])
        started = self.ev(tid, "task.started")[0]["payload"]
        self.assertEqual((started["provider"], started["adapter"]), ("native", "native"))

    def test_illegal_transition_is_E_TRANSITION(self):
        tid = self.make()
        with self.assertRaises(SentinelError) as c:
            self.eng.start_task(tid)
        self.assertEqual(c.exception.code, "E_TRANSITION")
        self.assertEqual(self.task(tid)["state"], "CREATED")

    def test_second_finish_is_refused(self):
        tid = self.running()
        self.write_result(tid)
        self.eng.finish_task(tid, exit_code=0)
        with self.assertRaises(SentinelError) as c:
            self.eng.finish_task(tid, exit_code=0)
        self.assertEqual(c.exception.code, "E_TRANSITION")

    def test_wait_and_cancel(self):
        tid = self.running()
        self.eng.wait_task(tid, "orchestrator")
        row = self.task(tid)
        self.assertEqual((row["state"], row["waiting_on"]), ("WAITING_FOR_INPUT", "orchestrator"))
        self.eng.cancel_task(tid, "human", reason="stop")
        self.assertEqual(self.task(tid)["state"], "CANCELLED")
        self.assertEqual(self.ev(tid, "task.finished")[0]["payload"]["state"], "CANCELLED")

    def test_unknown_task_is_E_NOT_FOUND(self):
        with self.assertRaises(SentinelError) as c:
            self.eng.finish_task("t-nope", exit_code=0)
        self.assertEqual(c.exception.code, "E_NOT_FOUND")

    def test_dependencies_are_stored(self):
        a = self.make()
        b = self.make(depends_on=[a])
        self.assertEqual(self.eng.reg.task_deps(b), [a])

    def test_start_task_stores_process_fields_and_before_snapshot(self):
        tid = self.make()
        self.eng.queue_task(tid)
        self.eng.start_task(tid, pid=4242, pid_started_at="123")
        row = self.task(tid)
        self.assertEqual((row["pid"], row["pid_started_at"]), (4242, "123"))
        self.assertTrue((self.tdir(tid) / "before.json").is_file())


class AutoTasks(PC):
    def test_R3_creates_specifier_task_and_R5_test_designer_task(self):
        self.eng.create_run(SLUG, "orchestrator", type="feature", baseline={"backend": "abc"})
        self.eng.triage(SLUG, {"files": "1"}, "orchestrator")
        self.eng.request_state(SLUG, "PLANNED", "engine")
        rows = self.eng.reg.rows("tasks", run_id=self.run_row()["id"])
        self.assertEqual([(r["role"], r["state"]) for r in rows], [("specifier", "QUEUED")])
        self.write_spec(spec_text(tier=1))
        self.submit("specifier")  # the open task goes through start_task and finish_task
        self.assertEqual(self.task(rows[0]["id"])["state"], "COMPLETED")
        self.approve("spec")
        rows = self.eng.reg.rows("tasks", run_id=self.run_row()["id"])
        self.assertEqual([(r["role"], r["state"]) for r in rows],
                         [("specifier", "COMPLETED"), ("test_designer", "QUEUED")])

    def test_finishing_specifier_task_runs_spec_completion(self):
        self.mk(SLUG, "TRIAGED", 1)
        self.eng.request_state(SLUG, "PLANNED", "engine")
        tid = self.eng.reg.rows("tasks", run_id=self.run_row()["id"])[0]["id"]
        self.eng.start_task(tid)
        self.write_spec(spec_text(tier=1))
        self.write_result(tid)
        row = self.eng.finish_task(tid, exit_code=0)
        self.assertEqual(row["state"], "COMPLETED")
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")

    def test_invalid_spec_queues_retry_task_with_brief(self):
        self.mk(SLUG, "TRIAGED", 1)
        self.eng.request_state(SLUG, "PLANNED", "engine")
        tid = self.eng.reg.rows("tasks", run_id=self.run_row()["id"])[0]["id"]
        self.eng.start_task(tid)
        self.write_spec("not a spec")
        self.write_result(tid)
        self.eng.finish_task(tid, exit_code=0)
        rows = self.eng.reg.rows("tasks", run_id=self.run_row()["id"])
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[1]["retry_of"], rows[1]["attempt"], rows[1]["state"]), (tid, 2, "QUEUED"))
        self.assertTrue((self.tdir(rows[1]["id"]) / "brief.md").read_text().strip())


if __name__ == "__main__":
    unittest.main()
