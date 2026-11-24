import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import engine  # noqa: E402
import sentinel  # noqa: E402
from shared import Shared  # noqa: E402

CONFIG = {"version": 1, "state": {"dir": ".sentinel", "shared_mode": "local"}, "repos": []}


class TestLocks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        (self.ws / "sentinel.config.yaml").write_text("version: 1\n")

    def test_local_lock_acquire_is_exclusive_even_if_exists_check_races(self):
        sh = Shared(self.ws, CONFIG)
        sh.acquire("lb", "me")
        orig = Path.exists
        Path.exists = lambda self: False  # simulate the loser's check-then-create window
        self.addCleanup(setattr, Path, "exists", orig)
        with self.assertRaises(SystemExit) as cm:
            sh.acquire("lb", "you")
        self.assertIn("locked by another run", str(cm.exception))
        Path.exists = orig
        self.assertTrue((sh.dir / "locks" / "lb").read_text().startswith("me "))

    def test_new_v2_run_keeps_lock_after_commit_failure(self):
        cfg = self.ws / "sentinel.config.yaml"
        args = argparse.Namespace(slug="lb", repos="", type=None)
        orig = engine.Engine.write_view

        def boom(self, slug):
            raise RuntimeError("view write failed")
        engine.Engine.write_view = boom
        self.addCleanup(setattr, engine.Engine, "write_view", orig)
        with self.assertRaises(RuntimeError):
            sentinel.new_v2_run(args, cfg, CONFIG)
        self.assertTrue((self.ws / ".sentinel" / "shared" / "locks" / "lb").exists())

    def test_new_v2_run_releases_lock_when_row_not_committed(self):
        cfg = self.ws / "sentinel.config.yaml"
        args = argparse.Namespace(slug="lb", repos="", type=None)
        orig = engine.Engine.create_run

        def boom(self, *a, **k):
            raise RuntimeError("db down")
        engine.Engine.create_run = boom
        self.addCleanup(setattr, engine.Engine, "create_run", orig)
        with self.assertRaises(RuntimeError):
            sentinel.new_v2_run(args, cfg, CONFIG)
        self.assertFalse((self.ws / ".sentinel" / "shared" / "locks" / "lb").exists())


class TestAttach(unittest.TestCase):
    def setUp(self):
        import io
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        (self.ws / "sentinel.config.yaml").write_text("version: 1\nshape: single\nrepos:\n  - id: app\n    path: .\n    role: app\n    profile: generic\n")
        (self.ws / ".git").mkdir()

    def test_attach_print_outputs_context_block(self):
        import contextlib
        import io
        from engine import Engine
        eng = Engine(self.ws / ".sentinel", self.ws, CONFIG)
        try:
            eng.create_run("tax-calc", "test-user", request="Fix tax calculation edge case", type="feature", baseline={})
            eng.request_state("tax-calc", "NEEDS_HUMAN", "engine", reason="Which rounding method to use?")
        finally:
            eng.close()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sentinel.cmd_attach(argparse.Namespace(dir=str(self.ws), slug="tax-calc", print_only=True))

        out = buf.getvalue()
        self.assertIn("Run: tax-calc", out)
        self.assertIn("Request: Fix tax calculation edge case", out)
        self.assertIn("State: NEEDS_HUMAN", out)
        self.assertIn("Park reason: Which rounding method to use?", out)
        self.assertIn("Open questions: Which rounding method to use?", out)
        self.assertIn("Run folder:", out)
        self.assertIn("Spec path:", out)
        self.assertIn("Scenario path:", out)


if __name__ == "__main__":
    unittest.main()
