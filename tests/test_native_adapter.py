"""Phase C part 2 (PC-02): native adapter, task complete, cooperative cancel, dispatch without a session."""
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from errors import SentinelError  # noqa: E402
from pc_helpers import PCX, SLUG  # noqa: E402


class Native(PCX):
    def setUp(self):
        super().setUp()
        self.use_config(single_model=True)
        self.executing()

    def waiting(self, **kw):
        tid = self.docs_task(**kw)
        code, out, err = self.run_json(tid)
        assert code == 0, out + err
        return tid

    def subagent(self, tid, path="backend/docs/leave.md", result=True, **over):
        if path:
            f = self.ws / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x\n")
        if result:
            self.write_result(tid, **over)

    def test_AC_AGT_04d_native_task_run_waits_for_the_orchestrator(self):
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 0, out + err)
        row = self.task(tid)
        self.assertEqual((row["state"], row["waiting_on"]), ("WAITING_FOR_INPUT", "orchestrator"))
        d = self.tdir(tid)
        for name in ("task.json", "prompt.md", "before.json"):
            self.assertTrue((d / name).is_file(), name)
        self.assertIn("backend", json.loads((d / "before.json").read_text())["repos"])
        self.assertIsNone(row["pid"])
        doc = json.loads(out)
        self.assertEqual((doc["prompt"], doc["result"], doc["next"]),
                         (str(d / "prompt.md"), str(d / "result.json"), f"sentinel task complete {tid}"))
        types = [e["type"] for e in self.task_events(tid) if e["type"] != "task.created"]
        self.assertEqual(types, ["task.queued", "task.started", "task.waiting"])
        self.assertEqual(self.ev(tid, "task.waiting")[0]["payload"]["waiting_on"], "orchestrator")

    def test_AC_AGT_04e_task_complete_with_a_valid_result_completes_the_task(self):
        tid = self.waiting()
        self.subagent(tid)
        code, out, err = self.cli("task", "complete", tid)
        self.assertEqual(code, 0, out + err)
        row = self.task(tid)
        self.assertEqual(row["state"], "COMPLETED")
        self.assertEqual(json.loads(row["changed_files"]), ["backend/docs/leave.md"])
        self.assertEqual(self.ev(tid, "task.finished")[0]["actor"], "engine")
        rows = self.audit("task_complete")
        self.assertEqual([(r["actor"], r["target"]) for r in rows], [("orchestrator", tid)])

    def test_AC_ORC_02d_bad_outcomes_fail_the_task(self):
        rows = {
            "no_result": (dict(result=False, path=None), 1, "E_RESULT_SCHEMA", None),
            "bad_status": (dict(path=None, status="ok"), 1, "E_RESULT_SCHEMA", None),
            "agent_failed": (dict(path=None, status="failed"), 1, "E_AGENT", None),
            "stray": (dict(path="frontend/stray.txt"), 3, "E_SCOPE", None),
            "commit": (dict(path=None, commit=True), 3, "E_SCOPE", None),
        }
        for name, (spec, code, error, _) in rows.items():
            with self.subTest(name):
                self.eng.close()
                self.use_config(single_model=True)
                slug = f"nat-{name.replace('_', '-')}"
                self.executing(slug)
                tid = self.make("docs", ["backend"], ["backend/docs/**"], slug=slug)
                self.eng.queue_task(tid)
                c, out, err = self.cli("task", "run", tid)
                self.assertEqual(c, 0, out + err)
                if spec.pop("commit", False):
                    git(self.ws / "backend", "commit", "--allow-empty", "-q", "-m", "x")
                path = spec.pop("path", None)
                if path:
                    (self.ws / path).write_text("x")
                if spec.pop("result", True):
                    self.write_result(tid, slug=slug, **spec)
                c, out, err = self.cli("task", "complete", tid)
                self.assertEqual(c, code, out + err)
                row = self.task(tid)
                self.assertEqual((row["state"], row["error_code"]), ("FAILED", error))

    def test_AC_ORC_02e_task_complete_has_no_way_to_choose_the_state(self):
        tid = self.waiting()
        code, out, err = self.cli("task", "complete", tid, "--state", "COMPLETED")
        self.assertEqual(code, 2, out + err)
        self.assertEqual(self.task(tid)["state"], "WAITING_FOR_INPUT")

    def test_AC_ORC_02f_orchestrator_cannot_move_a_task_through_the_engine(self):
        tid = self.waiting()
        for to in ("COMPLETED", "FAILED", "CANCELLED"):
            with self.subTest(to):
                with self.assertRaises(SentinelError) as c:
                    self.eng.request_task_state(tid, to, "orchestrator")
                self.assertEqual(c.exception.code, "E_ACTOR")
                self.assertEqual(self.task(tid)["state"], "WAITING_FOR_INPUT")

    def test_AC_ORC_02g_task_complete_needs_a_waiting_native_task(self):
        rows = [("QUEUED", "native", "E_TRANSITION"), ("CREATED", "native", "E_TRANSITION"),
                ("RUNNING", "cli", "E_PRECONDITION"), ("COMPLETED", "native", "E_TRANSITION"),
                ("FAILED", "native", "E_TRANSITION"), ("CANCELLED", "native", "E_TRANSITION")]
        for state, adapter, error in rows:
            with self.subTest(state=state, adapter=adapter):
                tid = self.make("docs", ["backend"], [f"backend/docs/{state}/**"])
                self.eng.reg.update_row("tasks", tid, state=state, adapter=adapter)
                code, out, err = self.cli("task", "complete", tid)
                self.assertEqual(code, 5, out + err)
                self.assertIn(error, err)
                self.assertEqual(self.task(tid)["state"], state)

    def test_AC_ORC_02h_second_task_complete_changes_nothing(self):
        tid = self.waiting()
        self.subagent(tid)
        self.assertEqual(self.cli("task", "complete", tid)[0], 0)
        code, out, err = self.cli("task", "complete", tid)
        self.assertEqual(code, 5, out + err)
        self.assertIn("E_TRANSITION", err)
        self.assertEqual(len(self.ev(tid, "task.finished")), 1)

    def test_AC_ORC_02i_two_task_complete_calls_finish_the_task_once(self):
        tid = self.waiting()
        self.subagent(tid)
        procs = [self.popen("task", "complete", tid) for _ in range(2)]
        results = [self.finish(p) for p in procs]
        self.assertEqual(sorted(r[0] for r in results), [0, 5], results)
        self.assertIn("E_TRANSITION", "".join(r[2] for r in results if r[0] == 5))
        self.assertEqual(len(self.ev(tid, "task.finished")), 1)

    def test_AC_AGT_05i_native_task_past_its_timeout_fails_at_the_next_engine_call(self):
        tid = self.waiting(timeout_seconds=2)
        time.sleep(3)
        code, step, err = self.next_json()
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_TIMEOUT"), err)
        self.assertIn(tid, json.dumps(step))
        self.assertIn("stop the subagent", json.dumps(step))

    def test_AC_AGT_05j_cancelling_a_native_task_is_cooperative(self):
        tid = self.waiting()
        self.eng.cancel_task(tid, "human", reason="stop")
        self.assertEqual(self.task(tid)["state"], "CANCELLED")
        code, step, err = self.next_json()
        self.assertIn("stop the subagent", json.dumps(step))
        self.assertIn(tid, json.dumps(step))
        self.write_result(tid)
        code, out, err = self.cli("task", "complete", tid)
        self.assertEqual(code, 5, out + err)
        self.assertIn("E_TRANSITION", err)
        self.assertIsNone(self.task(tid)["result_artifact_id"])


class Dispatch(PCX):
    def test_AC_TSK_03a_dispatch_without_a_session_runs_only_cli_tasks(self):
        slug = "leave-form"
        body = 'write("backend/docs/leave.md")\nwrite_result()\n'
        self.use_config(single_model=False, runners={"fake": {"command": self.script("fake", body)}},
                        agents={"docs": {"runner": "fake"}})
        self.executing(slug)
        docs = self.make("docs", ["backend"], ["backend/docs/**"], slug=slug)
        qa = self.make("qa", ["frontend"], [], slug=slug)
        for t in (docs, qa):
            self.eng.queue_task(t)
        done = self.eng.dispatch_ready(slug)
        self.assertEqual(done, [docs])
        self.assertEqual((self.task(docs)["state"], self.task(docs)["adapter"]), ("COMPLETED", "cli"))
        self.assertEqual((self.task(qa)["state"], self.task(qa)["adapter"]), ("QUEUED", "native"))
        code, step, err = self.next_json(slug)
        self.assertEqual((step["kind"], step["task"], step["label"]), ("task", qa, "waiting for orchestrator"))


from pc_helpers import git  # noqa: E402

if __name__ == "__main__":
    unittest.main()
