"""The dispatcher launches the chosen orchestrator for dashboard runs that wait for the AI tool (fake runner)."""
import os
import time
import unittest
from unittest import mock

from sv_helpers import SV, SLUG


class Orchestrator(SV):
    def setUp(self):
        super().setUp()
        self.marker = self.ws / "launches.txt"
        runner = self.script("orch", f"open({str(self.marker)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n")
        self.use_config(single_model=False, runners={"orch": {"command": runner, "prompt_flag": "-p"}})
        self.mk(SLUG, state="CREATED")
        with self.eng.reg.transaction():
            self.eng.reg.update_run(SLUG, origin="dashboard")
        self.serve(dispatch=True, dispatch_interval=3600)

    def launches(self):
        return self.marker.read_text().splitlines() if self.marker.exists() else []

    def pump(self):
        procs = self.srv.dispatch_once()
        for p in procs:
            p.wait(20)
        return procs

    def test_no_orchestrator_launches_nothing(self):
        self.assertEqual(self.pump(), [])
        self.assertFalse(self.marker.exists())

    def test_launches_with_resume_prompt_and_logs(self):
        self.srv.orchestrator = "orch"
        self.assertEqual(len(self.pump()), 1)
        (line,) = self.launches()
        self.assertTrue(line.startswith("-p "))
        self.assertIn(f"/sentinel resume {SLUG}", line)
        log = self.ws / ".sentinel" / "runs" / SLUG / "orchestrator.log"
        self.assertTrue(log.is_file())

    def test_not_for_cli_runs(self):
        with self.eng.reg.transaction():
            self.eng.reg.update_run(SLUG, origin="cli")
        self.srv.orchestrator = "orch"
        self.assertEqual(self.pump(), [])

    def test_at_most_three_launches_per_state_then_waits_for_a_human(self):
        self.srv.orchestrator = "orch"
        d = self.srv.dispatcher
        d.backoff = 0
        for _ in range(6):
            self.pump()
        self.assertEqual(len(self.launches()), 3)
        rows = [r for r in self.audit_rows() if r["action"] == "orchestrator_gave_up"]
        self.assertEqual(len(rows), 1)

    def test_one_live_process_per_run(self):
        slow = self.script("slow", f"open({str(self.marker)!r}, 'a').write('x\\n')\ntime.sleep(3)\n")
        self.use_config(single_model=False, runners={"slow": {"command": slow}})
        self.srv.orchestrator = "slow"
        d = self.srv.dispatcher
        d.backoff = 0
        first = d.once()
        second = d.once()
        self.assertEqual((len(first), len(second)), (1, 0))
        for p in first:
            p.kill()
            p.wait()

    def test_a_task_process_never_launches_it(self):
        self.srv.orchestrator = "orch"
        with mock.patch.dict(os.environ, {"SENTINEL_TASK_ID": "t1"}):
            self.assertEqual(self.srv.dispatch_once(), [])
        self.assertFalse(self.marker.exists())

    def test_an_uninstalled_orchestrator_is_skipped(self):
        self.srv.orchestrator = "claude"
        with mock.patch("runtime.runner_installed", return_value=False):
            self.assertEqual(self.pump(), [])


class Cli(unittest.TestCase):
    """`sentinel dashboard [provider]` argument checks; they fail before anything starts."""

    def run_cli(self, *args, env=None):
        import pty
        import subprocess
        import sys
        from pathlib import Path
        sentinel = Path(__file__).resolve().parents[1] / "sentinel" / "scripts" / "sentinel.py"
        m, s = pty.openpty()
        try:
            r = subprocess.run([sys.executable, str(sentinel), "dashboard", *args], stdin=s, stdout=s, stderr=subprocess.PIPE,
                               env={**os.environ, **(env or {})}, text=True, timeout=30)
        finally:
            os.close(m)
            os.close(s)
        return r.returncode, r.stderr

    def test_unknown_provider_lists_valid_ids(self):
        code, err = self.run_cli("nope")
        self.assertNotEqual(code, 0)
        self.assertIn("unknown provider", err)
        self.assertIn("claude", err)

    def test_not_installed_provider_is_refused(self):
        code, err = self.run_cli("codex", env={"PATH": "/nonexistent"})
        self.assertNotEqual(code, 0)
        self.assertIn("not installed", err)


class Pick(unittest.TestCase):
    def test_pick_by_number_name_or_enter(self):
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))
        import sentinel as cli
        for typed, want in (("2", "gemini"), ("claude", "claude"), ("", None), ("9", None)):
            with mock.patch("builtins.input", return_value=typed), mock.patch("builtins.print"):
                self.assertEqual(cli.pick_orchestrator(["claude", "gemini"]), want)


if __name__ == "__main__":
    unittest.main()
