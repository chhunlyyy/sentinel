"""Opus review fixes for Phase C: tamper detection, process lifecycle, retries, cascade, redaction, unblock."""
import hashlib
import json
import os
import signal
import sys
import time
import unittest
from pathlib import Path

from pc_helpers import PCX, SLUG, alive, wait_until  # noqa: E402

DELETE_BEFORE = """
d = pathlib.Path(result_path).parent
write("frontend/evil.md")
subprocess.run(["git", "-C", os.path.join(ws, "frontend"), "add", "-A"])
subprocess.run(["git", "-C", os.path.join(ws, "frontend"), "-c", "user.name=a", "-c", "user.email=a@b", "commit", "-qm", "x"])
(d/"before.json").unlink()
write_result()
"""
EDIT_BEFORE = """
d = pathlib.Path(result_path).parent
write("frontend/evil2.md")
b = json.loads((d/"before.json").read_text())
import hashlib
b["repos"]["frontend"]["paths"]["evil2.md"] = hashlib.sha256(b"x\\n").hexdigest()
(d/"before.json").write_text(json.dumps(b))
write_result()
"""
WIDEN_SEALED = """
d = pathlib.Path(result_path).parent
write("frontend/evil.md")
s = json.loads((d/"task.sealed.json").read_text())
s["permissions"]["write"] = ["backend/docs/**", "frontend/**"]
s["repos"] = ["backend", "frontend"]
(d/"task.sealed.json").write_text(json.dumps(s))
write_result()
"""
DELETE_SEALED = """
d = pathlib.Path(result_path).parent
write("backend/docs/ok.md")
(d/"task.sealed.json").unlink()
write_result()
"""


class Tamper(PCX):
    def tampered(self, body):
        self.boot({"fake": (body, {})}, {"docs": "fake"})
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        return tid, code, self.task(tid)

    def assert_integrity(self, tid, row):
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_INTEGRITY"), row["reason"])
        self.assertEqual(self.state(SLUG), "NEEDS_HUMAN")
        self.assertEqual(self.eng.reg.rows("tasks", retry_of=tid), [])

    def test_deleting_before_json_cannot_hide_an_out_of_scope_commit(self):
        tid, code, row = self.tampered(DELETE_BEFORE)
        self.assert_integrity(tid, row)
        self.assertIn("before.json", row["reason"])

    def test_editing_before_json_cannot_absorb_out_of_scope_changes(self):
        tid, code, row = self.tampered(EDIT_BEFORE)
        self.assert_integrity(tid, row)
        self.assertIn("before.json", row["reason"])

    def test_widening_the_sealed_scope_is_an_integrity_failure(self):
        tid, code, row = self.tampered(WIDEN_SEALED)
        self.assert_integrity(tid, row)
        self.assertIn("task.sealed.json", row["reason"])

    def test_deleting_the_sealed_copy_is_an_integrity_failure(self):
        tid, code, row = self.tampered(DELETE_SEALED)
        self.assert_integrity(tid, row)

    def test_untampered_task_still_completes(self):
        tid, code, row = self.tampered('write("backend/docs/a.md")\nwrite_result()\n')
        self.assertEqual((row["state"], code), ("COMPLETED", 0))
        self.assertEqual(json.loads(row["changed_files"]), ["backend/docs/a.md"])


class Cascade(PCX):
    def test_cancelling_a_retry_cancels_dependents_of_the_retry_root(self):
        self.executing()
        a = self.make(write=["backend/a/**"])
        b = self.make(write=["backend/b/**"], depends_on=[a])
        self.eng.queue_task(a)
        self.eng.start_task(a)
        self.write_result(a, status="failed")
        a2 = self.eng.finish_task(a, exit_code=0)["retry"]
        self.assertTrue(a2)
        self.eng.cancel_task(a2, "human", reason="stop")
        self.assertEqual(self.task(b)["state"], "CANCELLED")
        self.assertIn(a2, self.task(b)["reason"])


LEAKY = """
sys.stderr.write("connect failed postgres://u:s3cr3t-value@db token=tok-xyz-123 " + "x" * 3000 + "\\n")
sys.exit(1)
"""


class RetryBrief(PCX):
    def test_retry_brief_redacts_secrets_and_caps_stderr_lines(self):
        self.boot({"fake": (LEAKY, {})}, {"docs": "fake"}, policies={"redact_env": ["MY_DB_URL"]})
        tid = self.docs_task()
        self.cli("task", "run", tid, MY_DB_URL="s3cr3t-value", SENTINEL_DASHBOARD_TOKEN="tok-xyz-123")
        retry = self.eng.reg.rows("tasks", retry_of=tid)[0]["id"]
        brief = (self.tdir(retry) / "brief.md").read_text()
        self.assertIn("connect failed", brief)
        self.assertNotIn("s3cr3t-value", brief)
        self.assertNotIn("tok-xyz-123", brief)
        self.assertIn("[redacted]", brief)
        self.assertLess(max(len(line) for line in brief.splitlines()), 700)


STUBBORN_CHILD = """
child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open(%r, 'w').write('x'); time.sleep(40)" % os.path.join(ws, "ready.txt")])
open(os.path.join(ws, "pids.txt"), "w").write(f"{os.getpid()} {child.pid}")
time.sleep(40)
"""
BG_CHILD = """
child = subprocess.Popen(["sleep", "40"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
open(os.path.join(ws, "pids.txt"), "w").write(f"{os.getpid()} {child.pid}")
write("backend/docs/a.md")
write_result()
"""
HOLDS_STDOUT = """
child = subprocess.Popen(["sleep", "4"])
open(os.path.join(ws, "pids.txt"), "w").write(f"{os.getpid()} {child.pid}")
write("backend/docs/a.md")
write_result()
"""
SETSID_HOLDS_STDOUT = """
child = subprocess.Popen(["sleep", "5"], start_new_session=True)
open(os.path.join(ws, "pids.txt"), "w").write(f"{os.getpid()} {child.pid}")
write("backend/docs/a.md")
write_result()
"""
FAST = {"SENTINEL_CANCEL_GRACE_SECONDS": "1", "SENTINEL_PUMP_JOIN_SECONDS": "1"}


class Groups(PCX):
    """The runner's whole process group is stopped: on cancel, and when the leader exits."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self.kill_pids)
        old = {k: os.environ.get(k) for k in FAST}
        os.environ.update(FAST)
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in old.items()])

    def kill_pids(self):
        path = self.ws / "pids.txt"
        for pid in (self.pids(path) if path.exists() else []):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def pidfile(self):
        pf = self.ws / "pids.txt"
        self.assertTrue(wait_until(lambda: pf.exists() and len(pf.read_text().split()) == 2, 10))
        return self.pids(pf)

    def test_cancel_kills_a_child_that_ignores_sigterm_after_the_leader_is_gone(self):
        self.boot({"fake": (STUBBORN_CHILD, {})}, {"docs": "fake"})
        tid = self.docs_task()
        p = self.popen("task", "run", tid, **FAST)
        leader, child = self.pidfile()
        self.assertTrue(wait_until(lambda: (self.ws / "ready.txt").exists() and self.task(tid)["pid"], 5))
        self.eng.cancel_task(tid, "human", reason="stop")
        self.assertTrue(wait_until(lambda: not alive(child), 5), "child survived the cancel")
        self.assertFalse(alive(leader))
        self.finish(p)

    def test_normal_exit_does_not_leave_group_children_behind(self):
        self.boot({"fake": (BG_CHILD, {})}, {"docs": "fake"})
        tid = self.docs_task()
        code, out, err = self.run_json(tid, **FAST)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.task(tid)["state"], "COMPLETED")
        leader, child = self.pidfile()
        self.assertTrue(wait_until(lambda: not alive(child), 3), "background child survived task run")

    def test_task_run_returns_when_a_child_keeps_stdout_open(self):
        self.boot({"fake": (HOLDS_STDOUT, {})}, {"docs": "fake"})
        tid = self.docs_task()
        started = time.time()
        code, out, err = self.run_json(tid, **FAST)
        self.assertEqual(code, 0, out + err)
        self.assertLess(time.time() - started, 3.5, "task run waited for the background child")
        self.assertEqual(self.task(tid)["state"], "COMPLETED")

    def test_AC_ORC_07c_exit_json_is_written_before_the_log_pumps_are_joined(self):
        """A setsid child keeps stdout open, so the pumps finish late; meanwhile `next` must find the exit, not a lost task."""
        self.boot({"fake": (SETSID_HOLDS_STDOUT, {})}, {"docs": "fake"})
        tid = self.docs_task()
        p = self.popen("task", "run", tid, **{**FAST, "SENTINEL_PUMP_JOIN_SECONDS": "4"})
        leader, child = self.pidfile()
        self.assertTrue(wait_until(lambda: not alive(leader), 10))
        self.assertTrue(wait_until(lambda: (self.tdir(tid) / "exit.json").exists(), 1), "exit.json not written at exit")
        code, step, err = self.next_json()
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("COMPLETED", None), (row["reason"], err))
        code, out, err = self.finish(p)
        self.assertEqual(self.task(tid)["state"], "COMPLETED")
        self.assertEqual(len(self.ev(tid, "task.finished")), 1)

    def test_AC_ORC_07c_live_owner_keeps_a_task_from_being_declared_lost(self):
        """ORC-07c race: runner gone, no exit.json yet, but the `task run` process that owns it is alive."""
        self.boot({"fake": ("write_result()\n", {})}, {"docs": "fake"})
        tid = self.docs_task()
        me = os.getpid()
        self.eng.start_task(tid, pid=2 ** 22 - 3, pid_started_at="1", owner=True)
        self.assertEqual(self.task(tid)["owner_pid"], me)
        self.eng.set_process(tid, 2 ** 22 - 3, "1")
        code, step, err = self.next_json()
        self.assertEqual(self.task(tid)["state"], "RUNNING", err)
        with self.eng.reg.transaction():
            self.eng.reg.update_row("tasks", tid, owner_pid=2 ** 22 - 4)
        code, step, err = self.next_json()
        self.assertEqual((self.task(tid)["state"], self.task(tid)["reason"]), ("FAILED", "process lost"), err)


class LiveStreams(unittest.TestCase):
    def test_stage_run_style_process_returns_while_a_background_child_holds_the_pipe(self):
        import subprocess
        import tempfile
        import run_stage
        os.environ["SENTINEL_PUMP_JOIN_SECONDS"] = "1"
        self.addCleanup(os.environ.pop, "SENTINEL_PUMP_JOIN_SECONDS", None)
        with tempfile.TemporaryDirectory() as tmp:
            pidf = Path(tmp) / "pid"
            live = run_stage.LiveProcess(["bash", "-c", f"sleep 30 & echo $! > {pidf}; echo hi"], None, tmp,
                                         Path(tmp) / "out.log", Path(tmp) / "err.log")
            started = time.time()
            code, out, err = live.finish()
            elapsed = time.time() - started
            child = int(pidf.read_text())
            try:
                self.assertEqual((code, out.strip()), (0, "hi"))
                self.assertLess(elapsed, 3, "finish waited for the background child")
            finally:
                os.kill(child, signal.SIGKILL)
                for thread in live.threads:
                    thread.join(5)
            self.assertFalse(any(t.is_alive() for t in live.threads))


class Unblock(PCX):
    def test_relative_runner_command_unblocks_once_installed(self):
        self.use_config(single_model=False, runners={"late": {"command": "bin/late-agent"}},
                        agents={"docs": {"runner": "late"}})
        self.executing()
        old = os.getcwd()
        os.chdir(self.ws)
        self.addCleanup(os.chdir, old)
        tid = self.docs_task()
        out = self.eng.run_task(tid)
        self.assertEqual((out["exit"], self.state()), (6, "BLOCKED"), out)
        self.assertEqual(self.task(tid)["blocked_command"], "bin/late-agent")
        self.eng.bookkeep(SLUG)
        self.assertEqual(self.state(), "BLOCKED")
        self.script("late-agent", "write_result()\n")
        self.eng.bookkeep(SLUG)
        self.assertEqual(self.state(), "EXECUTING")


if __name__ == "__main__":
    unittest.main()
