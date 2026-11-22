"""Sentinel 2.1 usage limits: reset time parsing and the per-runner pattern tables, from sample runner output."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import limits  # noqa: E402

NOW = datetime(2026, 11, 21, 10, 0, 0, tzinfo=timezone.utc)


class Samples(unittest.TestCase):
    def check(self, runner, out="", err="", expect=None, parsed=True):
        res = limits.classify(runner, out, err, now=NOW, local=timezone.utc)
        self.assertIsNotNone(res, (runner, out, err))
        self.assertEqual(res["parsed"], parsed, res)
        if expect:
            self.assertEqual(res["retry_at"], expect, res)
        return res

    def test_claude_epoch(self):
        self.check("claude", out="Claude AI usage limit reached|1795260000", expect="2026-11-21T11:20:00.000000Z")

    def test_claude_clock_with_zone(self):
        # 3pm Europe/Berlin (UTC+1 in November) is 14:00 UTC, later than NOW
        self.check("claude", err="5-hour limit reached ∙ resets 3pm (Europe/Berlin)", expect="2026-11-21T14:00:00.000000Z")

    def test_claude_clock_passed_rolls_to_tomorrow(self):
        self.check("claude", err="You've hit your limit · resets 9am (UTC)", expect="2026-11-22T09:00:00.000000Z")

    def test_claude_dated(self):
        self.check("claude", err="Weekly limit reached ∙ resets Nov 25, 10am (UTC)", expect="2026-11-25T10:00:00.000000Z")

    def test_claude_will_reset_at(self):
        self.check("claude", out="Claude usage limit reached. Your limit will reset at 3:30pm (UTC).", expect="2026-11-21T15:30:00.000000Z")

    def test_gemini_quota_reset_after(self):
        self.check("gemini", err="You have exhausted your capacity on this model. Your quota will reset after 1h2m3s.",
                   expect="2026-11-21T11:02:03.000000Z")

    def test_gemini_resource_exhausted_retry_delay(self):
        self.check("gemini", err='{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [{"retryDelay": "34s"}]}}',
                   expect="2026-11-21T10:00:34.000000Z")

    def test_agy_quota_resets_in(self):
        self.check("agy", out="Error: quota exceeded for this model. Resets in 2h 15m.", expect="2026-11-21T12:15:00.000000Z")

    def test_codex_try_again_at(self):
        self.check("codex", err="You've hit your usage limit. Upgrade to Pro or try again at 3:45 PM.", expect="2026-11-21T15:45:00.000000Z")

    def test_codex_try_again_in(self):
        self.check("codex", err="stream error: rate_limit_exceeded. Please try again in 2 hours 5 minutes.", expect="2026-11-21T12:05:00.000000Z")

    def test_http_429_without_time_uses_the_backoff(self):
        res = self.check("claude", err="API Error: 429 Too Many Requests", parsed=False, expect="2026-11-21T10:30:00.000000Z")
        self.assertIn("429", res["reason"])

    def test_backoff_is_configurable(self):
        res = limits.classify("gemini", "", "RESOURCE_EXHAUSTED", now=NOW, backoff_minutes=5)
        self.assertEqual(res["retry_at"], "2026-11-21T10:05:00.000000Z")

    def test_ordinary_failures_are_not_limits(self):
        for text in ("npm ERR! exit 1", "AssertionError: 4 != 5", "connection refused", "", "limit the scope of the change"):
            self.assertIsNone(limits.classify("claude", text, text, now=NOW), text)

    def test_an_absurd_reset_is_ignored(self):
        res = limits.classify("claude", "", "usage limit reached|4102444800", now=NOW)
        self.assertFalse(res["parsed"])
        self.assertEqual(res["retry_at"], "2026-11-21T10:30:00.000000Z")

    def test_every_runner_table_compiles_and_matches_something(self):
        self.assertEqual(set(limits.TABLES), {"claude", "gemini", "agy", "codex", "generic"})
        for table in limits.TABLES.values():
            self.assertTrue(table)


if __name__ == "__main__":
    unittest.main()


class ConfigSchema(unittest.TestCase):
    def errors(self, routing):
        import json
        import jsonschema
        schema = json.loads((Path(__file__).resolve().parents[1] / "sentinel" / "core" / "schema" / "config.schema.json").read_text())
        sub = {"type": "object", "properties": {"routing": schema["properties"]["routing"]}}
        return [e.message for e in jsonschema.Draft202012Validator(sub).iter_errors({"routing": routing})]

    def test_fallback_and_backoff_validate(self):
        self.assertEqual(self.errors({"fallback": {"claude": "agy", "tdd_green": "codex"}, "limit_backoff": 15,
                                      "triage": {"runner": "claude"}}), [])
        self.assertTrue(self.errors({"fallback": ["agy"]}))
        self.assertTrue(self.errors({"fallback": {"claude": 3}}))
        self.assertTrue(self.errors({"limit_backoff": 0}))
        self.assertTrue(self.errors({"limit_backoff": "soon"}))


class Migration(unittest.TestCase):
    def test_the_task_limit_columns_arrive_with_migration_14(self):
        import tempfile
        import registry
        with tempfile.TemporaryDirectory() as tmp:
            old = registry.Registry.open(Path(tmp) / ".sentinel", [m for m in registry._load_file_migrations() if m[0] < 14])
            self.assertNotIn("retry_at", old._columns("tasks"))
            old.close()
            reg = registry.Registry.open(Path(tmp) / ".sentinel")
            self.addCleanup(reg.close)
            self.assertGreaterEqual(registry.Registry.LATEST, 14)
            self.assertTrue({"retry_at", "limit_reason", "limit_hits"} <= set(reg._columns("tasks")))
