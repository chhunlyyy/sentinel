"""Sentinel 2.1 CLI: `sentinel doctor --fix-routing`, `sentinel resolve --retry-now`, `sentinel next` on a usage limit."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from pb_helpers import PtyProc  # noqa: E402
from pb_helpers import run_plain  # noqa: E402
from pc_helpers import PCX  # noqa: E402


class FixRouting(PCX):
    def setUp(self):
        super().setUp()
        self.d = ["--dir", str(self.ws)]

    def tty(self, typed=None):
        p = PtyProc(self.d + ["doctor", "--fix-routing"])
        if typed is not None and p.wait_for("Type yes", 15):
            p.send(typed + "\n")
        return p.finish()

    def config_file(self):
        return yaml.safe_load((self.ws / "sentinel.config.yaml").read_text())

    def test_without_a_terminal_it_prints_the_suggestion_and_writes_nothing(self):
        before = (self.ws / "sentinel.config.yaml").read_text()
        code, out = run_plain(self.d + ["doctor", "--fix-routing"])
        self.assertNotEqual(code, 0)
        self.assertIn("triage", out)
        self.assertIn("suggested:", out)
        self.assertIn("E_NOT_TTY", out)
        self.assertEqual((self.ws / "sentinel.config.yaml").read_text(), before)

    def test_a_typed_yes_writes_the_routing_with_history(self):
        code, out = self.tty("yes")
        self.assertEqual(code, 0, out)
        cfg = self.config_file()
        self.assertIs(cfg["single_model"], False)
        self.assertTrue(cfg["agents"]["triage"]["runner"])
        import factory
        self.assertEqual(factory.routing_problems(cfg), [])
        self.eng.close()
        from registry import Registry
        reg = Registry.open(self.ws / ".sentinel")
        self.addCleanup(reg.close)
        row = reg._c.execute("SELECT channel, comment FROM config_versions ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual((row[0], row[1]), ("tty", "Fix routing"))

    def test_anything_but_yes_writes_nothing(self):
        before = (self.ws / "sentinel.config.yaml").read_text()
        code, out = self.tty("no")
        self.assertEqual(code, 1, out)
        self.assertIn("nothing written", out)
        self.assertEqual((self.ws / "sentinel.config.yaml").read_text(), before)

    def test_a_routed_project_has_nothing_to_fix(self):
        self.use_config(single_model=False, runners={"claude": {"command": "claude"}},
                        agents={r: {"runner": "claude"} for r in __import__("factory").ENGINE_ROLES})
        code, out = run_plain(self.d + ["doctor", "--fix-routing"])
        self.assertEqual(code, 0, out)
        self.assertIn("nothing to fix", out)


class RetryNow(PCX):
    def test_next_shows_the_wait_and_resolve_retry_now_clears_it(self):
        self.boot({"claude": ("pass\n", {})}, {"docs": "claude"})
        tid = self.docs_task()
        at = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self.eng.reg.transaction():
            self.eng.reg.update_row("tasks", tid, retry_at=at, limit_reason="usage limit reached")
        d = ["--dir", str(self.ws)]
        code, out = run_plain(d + ["next", self.run_row()["slug"]])
        self.assertIn("usage limit until " + at, out)
        self.assertIn("--retry-now", out)
        p = PtyProc(d + ["resolve", self.run_row()["slug"], "--retry-now"])
        code, text = p.finish()
        self.assertEqual(code, 0, text)
        self.assertIn(tid, text)
        self.assertIsNone(self.task(tid)["retry_at"])

    def test_retry_now_needs_a_terminal(self):
        self.boot({"claude": ("pass\n", {})}, {"docs": "claude"})
        code, out = run_plain(["--dir", str(self.ws), "resolve", self.run_row()["slug"], "--retry-now"])
        self.assertNotEqual(code, 0)
        self.assertIn("E_NOT_TTY", out)
