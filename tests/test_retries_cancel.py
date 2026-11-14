"""Phase C part 2 (PC-02): retries with a cap, cancel, recovery from persisted state."""
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import adapters  # noqa: E402
from errors import SentinelError  # noqa: E402
from pc_helpers import PCX, SLUG, alive, git, wait_until  # noqa: E402


def retries(tests, slug=SLUG):
    return [t for t in tests.eng.reg.rows("tasks", run_id=tests.run_row(slug)["id"]) if t["retry_of"]]


class Retry(PCX):
    def fail_with(self, body, **kw):
        self.boot({"fake": (body, {})}, {"docs": "fake"})
        return self.docs_task(**kw)

    def test_AC_AGT_05k_failed_task_gets_a_retry_with_the_reason_in_its_brief(self):
        tid = self.fail_with('print("error: cannot write docs/leave.md", file=sys.stderr)\nsys.exit(1)\n', max_retries=2)
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 1, out + err)
        self.assertEqual((self.task(tid)["state"], self.task(tid)["error_code"]), ("FAILED", "E_EXIT"))
        (retry,) = retries(self)
        self.assertEqual((retry["state"], retry["retry_of"], retry["attempt"], retry["role"]), ("QUEUED", tid, 2, "docs"))
        brief = (self.tdir(retry["id"]) / "brief.md").read_text()
        self.assertIn("E_EXIT", brief)
        self.assertIn("error: cannot write docs/leave.md", brief)
        old, new = self.task_json(tid), self.task_json(retry["id"])
        for key in ("role", "repos", "permissions", "constraints"):
            self.assertEqual(old[key], new[key], key)
        self.assertIn(retry["id"], out + err)

    def test_AC_ORC_05a_retry_cap_sends_the_run_to_a_human(self):
        for cap, attempts in ((0, 1), (1, 2), (2, 3)):
            with self.subTest(cap=cap):
                self.eng.close()
                slug = f"cap-{cap}"
                self.use_config(single_model=False, runners={"fake": {"command": self.script("fake", "sys.exit(1)\n")}},
                                agents={"docs": {"runner": "fake"}})
                self.executing(slug)
                tid = self.make("docs", ["backend"], ["backend/docs/**"], slug=slug, max_retries=cap)
                self.eng.queue_task(tid)
                ran, last = 0, None
                while True:
                    queued = [t for t, s in self.states(slug=slug) if s == "QUEUED"]
                    if not queued:
                        break
                    last = self.cli("task", "run", queued[0])
                    ran += 1
                self.assertEqual(ran, attempts)
                self.assertEqual(last[0], 6, last)
                self.assertEqual(self.state(slug), "NEEDS_HUMAN")
                ev = self.events("run.state_changed", slug)[-1]["payload"]
                self.assertEqual((ev["transition"], ev["reason"]), ("R19", f"docs task failed after {cap} retries"))
                self.assertEqual(len(self.states('docs', slug)), attempts)

    def test_AC_ORC_05b_a_retry_that_succeeds_ends_the_chain(self):
        flag = self.ws / "first.txt"
        body = f"""
        if not os.path.exists({str(flag)!r}):
            open({str(flag)!r}, "w").write("1")
            sys.exit(1)
        write_result()
        """
        tid = self.fail_with(body, max_retries=2)
        self.assertEqual(self.run_json(tid)[0], 1)
        (retry,) = retries(self)
        self.assertEqual(self.run_json(retry["id"])[0], 0)
        self.assertEqual((self.task(tid)["state"], self.task(retry["id"])["state"]), ("FAILED", "COMPLETED"))
        self.assertEqual(self.state(), "EXECUTING")

    def test_AC_ORC_05c_which_failures_are_retried(self):
        self.executing()
        rows = [("E_EXIT", True), ("E_TIMEOUT", True), ("E_RESULT_SCHEMA", True), ("E_AGENT", True),
                ("E_SCOPE", False), ("E_INTEGRITY", False)]
        for code, retried in rows:
            with self.subTest(code):
                self.eng.close()
                self.use_config()
                slug = f"which-{code.lower().replace('_', '-')}"
                self.executing(slug)
                tid = self.running(write=["backend/docs/**"], slug=slug, max_retries=2)
                kw = {"exit_code": 0}
                if code == "E_EXIT":
                    kw["exit_code"] = 1
                elif code == "E_TIMEOUT":
                    kw["timed_out"] = True
                elif code == "E_RESULT_SCHEMA":
                    pass
                elif code == "E_AGENT":
                    self.write_result(tid, slug=slug, status="failed")
                elif code == "E_SCOPE":
                    (self.ws / "frontend/x.txt").write_text(code)
                    self.write_result(tid, slug=slug)
                elif code == "E_INTEGRITY":
                    p = self.tdir(tid, slug) / "task.json"
                    p.write_text(p.read_text() + " ")
                    self.write_result(tid, slug=slug)
                row = self.eng.finish_task(tid, **kw)
                self.assertEqual(row["error_code"], code)
                self.assertEqual(bool(retries(self, slug)), retried)
                self.assertEqual(self.state(slug), "EXECUTING" if retried else "NEEDS_HUMAN")
                (self.ws / "frontend/x.txt").unlink(missing_ok=True)

    def test_AC_ORC_05d_agent_that_reports_blocked_asks_a_human(self):
        self.executing()
        tid = self.running()
        self.write_result(tid, status="blocked", questions=["Which date format?"])
        row = self.eng.finish_task(tid, exit_code=0)
        self.assertEqual(row["state"], "BLOCKED")
        self.assertEqual(retries(self), [])
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        reason = self.events("run.state_changed")[-1]["payload"]["reason"]
        self.assertEqual(reason, f"docs task blocked: Which date format?")


SLEEPER = "child = subprocess.Popen(['sleep', '60'])\nopen({pids!r}, 'w').write(f'{{os.getpid()}} {{child.pid}}')\ntime.sleep(60)\n"


class Cancel(PCX):
    def start_sleeper(self, body=None, role_agents=None, **kw):
        self.pidf = str(self.ws / "pids.txt")
        self.boot({"fake": (body or SLEEPER.format(pids=self.pidf), {})}, {"docs": "fake", **(role_agents or {})})
        tid = self.docs_task(**kw)
        self.runner = self.popen("task", "run", tid)
        self.assertTrue(wait_until(lambda: os.path.exists(self.pidf) and len(Path(self.pidf).read_text().split()) == 2, 10))
        self.assertTrue(wait_until(lambda: self.task(tid)["pid"], 5))
        return tid

    def test_AC_AGT_05l_human_cancels_a_running_cli_task(self):
        tid = self.start_sleeper()
        pids = self.pids(self.pidf)
        self.eng.cancel_task(tid, "human", reason="stop")
        self.assertTrue(wait_until(lambda: not any(alive(p) for p in pids), 15))
        self.assertEqual(self.task(tid)["state"], "CANCELLED")
        code, out, err = self.finish(self.runner)
        self.assertEqual(code, 1, out + err)
        self.assertIn("CANCELLED", out)
        fin = self.ev(tid, "task.finished")
        self.assertEqual([(e["payload"]["state"], e["actor"]) for e in fin], [("CANCELLED", "human")])
        self.assertEqual(retries(self), [])
        self.assertEqual(self.state(), "EXECUTING")

    def test_AC_AGT_05m_runner_that_ignores_sigterm_is_killed_after_10_seconds(self):
        marker = self.ws / "term.txt"
        body = f"""
        signal.signal(signal.SIGTERM, lambda *a: open({str(marker)!r}, "w").write(str(time.time())))
        child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"])
        time.sleep(0.5)
        open({str(self.ws / 'pids.txt')!r}, "w").write(f"{{os.getpid()}} {{child.pid}}")
        while True:
            time.sleep(0.2)
        """
        tid = self.start_sleeper(body)
        pid, child = self.pids(self.pidf)
        started = time.time()
        self.eng.cancel_task(tid, "human", reason="stop")
        self.assertTrue(marker.exists())
        self.assertLess(float(marker.read_text()) - started, 3)
        self.assertTrue(wait_until(lambda: not alive(pid), 6))
        self.assertTrue(wait_until(lambda: not alive(child), 3), "the group's other process survived the SIGKILL")
        elapsed = time.time() - started
        self.assertGreaterEqual(elapsed, 9.5)
        self.assertLess(elapsed, 15)
        self.assertEqual(self.task(tid)["state"], "CANCELLED")
        self.finish(self.runner)

    def test_AC_AGT_05n_finishing_run_does_not_overwrite_a_cancel(self):
        body = 'write_result()\nopen(' + repr(str(self.ws / "pids.txt")) + ', "w").write(f"{os.getpid()} {os.getpid()}")\ntime.sleep(60)\n'
        tid = self.start_sleeper(body)
        self.eng.cancel_task(tid, "human", reason="stop")
        code, out, err = self.finish(self.runner)
        self.assertEqual(code, 1, out + err)
        self.assertEqual(self.task(tid)["state"], "CANCELLED")
        self.assertEqual(len(self.ev(tid, "task.finished")), 1)
        time.sleep(0.5)
        self.assertEqual(self.task(tid)["state"], "CANCELLED")

    def test_AC_AGT_05o_only_a_human_or_the_engine_can_cancel(self):
        self.executing()
        for actor, ok in (("human", True), ("engine", True), ("orchestrator", False)):
            with self.subTest(actor):
                tid = self.running(write=[f"backend/{actor}/**"])
                if ok:
                    self.eng.cancel_task(tid, actor)
                    self.assertEqual(self.task(tid)["state"], "CANCELLED")
                else:
                    with self.assertRaises(SentinelError) as c:
                        self.eng.cancel_task(tid, actor)
                    self.assertEqual(c.exception.code, "E_ACTOR")
                    self.assertEqual(self.task(tid)["state"], "RUNNING")

    def test_AC_AGT_05p_a_finished_task_cannot_be_cancelled(self):
        self.executing()
        for state in ("COMPLETED", "FAILED", "CANCELLED"):
            with self.subTest(state):
                tid = self.make(write=[f"backend/{state}/**"])
                self.eng.reg.update_row("tasks", tid, state=state)
                with self.assertRaises(SentinelError) as c:
                    self.eng.cancel_task(tid, "human")
                self.assertEqual(c.exception.code, "E_TRANSITION")
                self.assertEqual(self.task(tid)["state"], state)

    def test_AC_AGT_05q_cancelling_the_run_cancels_its_tasks(self):
        tid = self.start_sleeper()
        pids = self.pids(self.pidf)
        qa = self.make("qa", ["backend"], [])
        self.eng.queue_task(qa)
        self.eng.finish(SLUG, "stopped", "human")
        self.assertEqual(self.state(), "CANCELLED")
        self.assertEqual(self.events("run.state_changed")[-1]["payload"]["transition"], "R23")
        self.assertEqual((self.task(tid)["state"], self.task(qa)["state"]), ("CANCELLED", "CANCELLED"))
        self.assertTrue(wait_until(lambda: not any(alive(p) for p in pids), 15))
        self.assertEqual(self.released, [SLUG])
        self.finish(self.runner)

    def test_AC_AGT_05r_specification_change_cancels_the_running_tasks(self):
        tid = self.start_sleeper()
        pids = self.pids(self.pidf)
        spec = self.sdir() / "spec.md"
        spec.write_text(spec.read_text() + "\nedit\n")
        self.eng.load_run(SLUG)
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.assertEqual(self.task(tid)["state"], "CANCELLED")
        self.assertEqual(self.ev(tid, "task.finished")[0]["payload"]["reason"], "approval invalidated")
        self.assertEqual(self.ev(tid, "task.finished")[0]["actor"], "engine")
        self.assertTrue(wait_until(lambda: not any(alive(p) for p in pids), 15))
        self.finish(self.runner)


class Recovery(PCX):
    def lost(self, **kw):
        self.boot({"fake": ("pass", {})}, {"docs": "fake"})
        tid = self.docs_task(**kw)
        dead = subprocess.Popen(["sleep", "0"])
        dead.wait()
        self.eng.start_task(tid, pid=dead.pid, pid_started_at=adapters.process_start_time(dead.pid) or "1")
        return tid

    def test_AC_ORC_07a_task_whose_sentinel_process_died_is_failed_and_retried(self):
        tid = self.lost(max_retries=2)
        code, step, err = self.next_json()
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"], row["reason"]), ("FAILED", "E_EXIT", "process lost"), err)
        (retry,) = retries(self)
        self.assertEqual(retry["state"], "QUEUED")
        self.assertEqual((step["kind"], step["task"]), ("task", retry["id"]))

    def test_AC_ORC_07b_reused_pid_is_not_mistaken_for_the_runner(self):
        self.boot({"fake": ("pass", {})}, {"docs": "fake"})
        tid = self.docs_task()
        other = subprocess.Popen(["sleep", "30"])
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        self.eng.start_task(tid, pid=other.pid, pid_started_at="1")  # a different start time
        code, step, err = self.next_json()
        self.assertEqual(self.task(tid)["state"], "FAILED", err)
        self.assertEqual(self.task(tid)["reason"], "process lost")
        self.assertIsNone(other.poll())

    def test_AC_ORC_07c_event_write_failure_leaves_the_task_running(self):
        self.executing()
        tid = self.running()
        self.write_result(tid)
        (self.tdir(tid) / "exit.json").write_text(json.dumps({"exit_code": 0, "timed_out": False, "seconds": 1.5}))
        real = self.eng.reg.add_event
        calls = []

        def broken(*a, **kw):
            calls.append(a)
            raise RuntimeError("disk full")
        self.eng.reg.add_event = broken
        with self.assertRaises(RuntimeError):
            self.eng.finish_task(tid, exit_code=0)
        self.eng.reg.add_event = real
        self.assertEqual(self.task(tid)["state"], "RUNNING")
        self.assertEqual(self.ev(tid, "task.finished"), [])
        self.assertTrue((self.tdir(tid) / "result.json").is_file())
        code, step, err = self.next_json()
        self.assertEqual(self.task(tid)["state"], "COMPLETED", err)
        self.assertEqual(len(self.ev(tid, "task.finished")), 1)


if __name__ == "__main__":
    unittest.main()
