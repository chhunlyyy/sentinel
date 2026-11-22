"""Sentinel 2.1: a provider usage limit parks the task (QUEUED + retry_at), it does not fail it."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from pc_helpers import PCX  # noqa: E402

LIMIT = "print('Claude AI usage limit reached|%d')\nsys.exit(1)\n"
GOOD = "write('backend/docs/leave.md')\nwrite_result()\n"


def epoch_in(minutes):
    return int((datetime.now(timezone.utc) + timedelta(minutes=minutes)).timestamp())


class LimitFlow(PCX):
    def boot_claude(self, body, **cfg):
        self.boot({"claude": (body, {})}, {"docs": "claude"}, **cfg)

    def test_limit_hit_queues_the_task_with_retry_at(self):
        self.boot_claude(LIMIT % epoch_in(90))
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 0, out + err)
        row = self.task(tid)
        self.assertEqual(row["state"], "QUEUED")
        self.assertTrue(row["retry_at"] > datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
        self.assertIn("usage limit", row["limit_reason"])
        self.assertEqual(row["limit_hits"], 1)
        self.assertEqual(self.eng.reg.rows("tasks", retry_of=tid), [])   # no retry task: not a failure
        self.assertNotEqual(self.state(), "NEEDS_HUMAN")
        event = self.ev(tid, "task.limit_reached")[0]["payload"]
        self.assertEqual((event["runner"], event["fallback"]), ("claude", None))
        self.assertEqual(event["retry_at"], row["retry_at"])
        self.assertFalse((self.tdir(tid) / "exit.json").exists())

    def test_the_task_does_not_start_before_retry_at_and_next_says_so(self):
        self.boot_claude(LIMIT % epoch_in(90))
        tid = self.docs_task()
        self.run_json(tid)
        check = self.eng.check_start(tid)
        self.assertFalse(check["ok"])
        self.assertIn("usage limit", check["message"])
        step = self.eng.next_step(self.run_row()["slug"])
        self.assertEqual(step["kind"], "wait")
        self.assertEqual(step["retry_at"], self.task(tid)["retry_at"])
        self.assertIn("--retry-now", step["command"])

    def test_retry_now_and_a_past_retry_at_let_it_start(self):
        self.boot_claude(LIMIT % epoch_in(90))
        tid = self.docs_task()
        self.run_json(tid)
        self.assertEqual(self.eng.retry_limited_now(self.run_row()["slug"]), [tid])
        self.assertIsNone(self.task(tid)["retry_at"])
        self.assertTrue(self.eng.check_start(tid)["ok"])
        self.script("claude", GOOD)
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.task(tid)["state"], "COMPLETED")

    def test_a_message_without_a_time_waits_the_configured_backoff(self):
        self.boot_claude("print('API Error: 429 Too Many Requests', file=sys.stderr)\nsys.exit(1)\n",
                         routing={"limit_backoff": 5})
        tid = self.docs_task()
        self.run_json(tid)
        row = self.task(tid)
        wait = datetime.strptime(row["retry_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        self.assertTrue(timedelta(minutes=4) < wait <= timedelta(minutes=5), wait)

    def test_an_ordinary_failure_still_fails(self):
        self.boot_claude("print('boom', file=sys.stderr)\nsys.exit(7)\n")
        tid = self.docs_task()
        self.run_json(tid)
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_EXIT"))
        self.assertIsNone(row["retry_at"])

    def test_fallback_runs_the_task_on_the_other_runner_at_once(self):
        self.boot({"claude": (LIMIT % epoch_in(90), {}), "agy": (GOOD, {})}, {"docs": "claude"},
                  routing={"fallback": {"claude": "agy"}})
        tid = self.docs_task()
        self.run_json(tid)
        row = self.task(tid)
        self.assertEqual((row["state"], row["provider"], row["retry_at"]), ("QUEUED", "agy", None))
        self.assertEqual(self.ev(tid, "task.limit_reached")[0]["payload"]["fallback"], {"from": "claude", "to": "agy"})
        self.assertTrue(self.eng.check_start(tid)["ok"])
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 0, out + err)
        self.assertEqual((self.task(tid)["state"], self.task(tid)["provider"]), ("COMPLETED", "agy"))

    def test_a_second_limit_on_the_fallback_waits(self):
        self.boot({"claude": (LIMIT % epoch_in(90), {}), "agy": ("print('Error: quota exceeded. Resets in 1h.')\nsys.exit(1)\n", {})}, {"docs": "claude"},
                  routing={"fallback": {"claude": "agy", "agy": "claude"}})
        tid = self.docs_task()
        self.run_json(tid)
        self.run_json(tid)
        row = self.task(tid)
        self.assertEqual((row["state"], row["provider"], row["limit_hits"]), ("QUEUED", "agy", 2))
        self.assertIsNotNone(row["retry_at"])

    def test_the_notification_rule_names_the_limit(self):
        import notifications
        level, text, link, command = notifications.rule(
            "task.limit_reached", {"role": "tdd_green", "runner": "claude", "retry_at": "2026-11-21T14:05:00.000000Z"}, "leave-balance")
        self.assertEqual(level, "warning")
        self.assertIn("claude", text)
        self.assertIn("14:05", text)
        self.assertEqual(command, "sentinel resolve leave-balance --retry-now")
        json.dumps(text)
