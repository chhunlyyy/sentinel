"""providers.detect / installed_ids / probe with fake runner scripts (no real AI CLI)."""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))
import providers  # noqa: E402


def script(directory, name, body):
    p = Path(directory) / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


class Providers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def test_builtins_come_first_in_stable_order_with_labels(self):
        ids = [p["id"] for p in providers.detect()]
        self.assertEqual(ids[:4], ["claude", "codex", "gemini", "agy"])
        labels = {p["id"]: p["label"] for p in providers.detect()}
        self.assertEqual(labels["claude"], "Claude Code")
        self.assertEqual(labels["agy"], "Antigravity (agy)")

    def test_custom_runner_installed_and_capabilities(self):
        fake = script(self.tmp, "fake", "echo fake 1.2")
        cfg = {"runners": {"fake": {"command": fake, "model_flag": "--model"},
                           "ghost": {"command": "/nonexistent/ghost"}}}
        items = {p["id"]: p for p in providers.detect(cfg)}
        self.assertTrue(items["fake"]["installed"])
        self.assertEqual(items["fake"]["path"], fake)
        self.assertEqual(items["fake"]["label"], "fake")
        self.assertEqual(items["fake"]["capabilities"], {"model_select": True, "resume": False, "json_output": False})
        self.assertFalse(items["ghost"]["installed"])
        self.assertIsNone(items["ghost"]["path"])
        self.assertIn("fake", providers.installed_ids(cfg))
        self.assertNotIn("ghost", providers.installed_ids(cfg))

    def test_probe_runs_version_only(self):
        log = Path(self.tmp) / "args"
        fake = script(self.tmp, "fake", f'echo "$@" > {log}\necho fake 1.2')
        r = providers.probe("fake", {"runners": {"fake": {"command": fake}}})
        self.assertEqual(r, {"id": "fake", "ok": True, "message": "fake 1.2"})
        self.assertEqual(log.read_text().strip(), "--version")

    def test_probe_never_raises(self):
        cfg = {"runners": {"bad": {"command": script(self.tmp, "bad", "echo boom >&2\nexit 3")},
                           "slow": {"command": script(self.tmp, "slow", "sleep 5")},
                           "ghost": {"command": "/nonexistent/x"}}}
        self.assertEqual(providers.probe("bad", cfg), {"id": "bad", "ok": False, "message": "boom"})
        r = providers.probe("slow", cfg, timeout=0.3)
        self.assertFalse(r["ok"])
        self.assertIn("0.3", r["message"])
        self.assertEqual(providers.probe("ghost", cfg)["message"], "not installed")
        self.assertEqual(providers.probe("nope", cfg)["message"], "unknown provider")


if __name__ == "__main__":
    unittest.main()


class ModelsAndRoles(unittest.TestCase):
    def test_config_models_come_first_and_extend_the_builtins(self):
        cfg = {"runners": {"claude": {"command": "claude", "models": ["my-tuned", "claude-opus-5-5"]}}}
        ids = [m["id"] for m in next(p for p in providers.detect(cfg) if p["id"] == "claude")["models"]]
        self.assertEqual(ids[0], "my-tuned")
        self.assertEqual(ids.count("claude-opus-5-5"), 1)
        self.assertIn("claude-haiku-5-5", ids)

    def test_a_provider_without_a_model_flag_lists_no_models(self):
        cfg = {"runners": {"plain": {"command": "plain", "models": ["x"]}}}
        self.assertEqual(next(p for p in providers.detect(cfg) if p["id"] == "plain")["models"], [])

    def test_roles_come_from_the_stage_prompts(self):
        import tasks
        roles = tasks.agent_roles()
        self.assertEqual(roles[0], "specifier")
        self.assertEqual(set(roles), {f.stem for f in (tasks.ROOT / "core" / "stages").glob("*.md")})
