"""Claude adapter deny rules for the human-only commands (AC-SEC-04a): merge, idempotency, bad shapes."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "sentinel" / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("sentinel_cli", SCRIPTS / "sentinel.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class DenyRules(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.path = self.ws / ".claude" / "settings.json"

    def put(self, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text)

    def test_creates_file_with_all_rules(self):
        cli.deny_human_commands(self.ws)
        deny = json.loads(self.path.read_text())["permissions"]["deny"]
        self.assertEqual(deny, cli.HUMAN_ONLY_COMMANDS)
        self.assertIn("Bash(sentinel approve:*)", deny)
        self.assertIn("Bash(sentinel --dir * approve *)", deny)

    def test_merge_keeps_other_settings_and_is_idempotent(self):
        self.put(json.dumps({"model": "x", "permissions": {"allow": ["Bash(ls:*)"], "deny": ["Bash(rm:*)"]}}))
        cli.deny_human_commands(self.ws)
        first = self.path.read_text()
        cli.deny_human_commands(self.ws)
        self.assertEqual(self.path.read_text(), first)
        data = json.loads(first)
        self.assertEqual(data["model"], "x")
        self.assertEqual(data["permissions"]["allow"], ["Bash(ls:*)"])
        self.assertEqual(data["permissions"]["deny"], ["Bash(rm:*)"] + cli.HUMAN_ONLY_COMMANDS)

    def test_bad_shapes_exit_non_zero_and_leave_the_file_alone(self):
        for text in ('{"permissions": null}', '{"permissions": {"deny": "x"}}', "[]", '{"permissions": []}',
                     "not json", "null"):
            with self.subTest(text=text):
                self.put(text)
                with self.assertRaises(SystemExit) as c:
                    cli.deny_human_commands(self.ws)
                self.assertNotEqual(c.exception.code, 0)
                self.assertIn("settings.json", str(c.exception.code))
                self.assertEqual(self.path.read_text(), text)


if __name__ == "__main__":
    unittest.main()
