"""Workstream E tests: usage per task, budget limits, notifications, and retry-now route.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "sentinel" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import analytics
import factory
import limits
from apiserver import ops, routes
from engine import Engine
from errors import SentinelError
from registry import Registry, _load_file_migrations
from runtime import parse_usage


class TestMigration0015(unittest.TestCase):
    def test_0015_migration_file_exists_and_has_rollback_note(self):
        migs = _load_file_migrations()
        v15 = [m for m in migs if m[0] == 15]
        self.assertEqual(len(v15), 1, "0015 migration should exist")
        version, name, sql = v15[0]
        self.assertIn("input_tokens", sql)
        self.assertIn("output_tokens", sql)
        self.assertIn("Rollback:", sql)

    def test_tasks_table_has_input_and_output_tokens_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            reg = Registry.open(state_dir)
            cols = reg._columns("tasks")
            self.assertIn("input_tokens", cols)
            self.assertIn("output_tokens", cols)
            self.assertIn("tokens", cols)
            self.assertIn("cost", cols)
            self.assertIn("seconds", cols)
            reg.close()


class TestUsageParsing(unittest.TestCase):
    def test_claude_cli_output_format_json(self):
        raw = json.dumps({
            "type": "result",
            "subtype": "success",
            "total_cost_usd": 0.0421,
            "usage": {
                "input_tokens": 1520,
                "output_tokens": 340,
            }
        })
        u = parse_usage(raw)
        self.assertEqual(u["tokens"], 1860)
        self.assertEqual(u["input_tokens"], 1520)
        self.assertEqual(u["output_tokens"], 340)
        self.assertAlmostEqual(u["cost"], 0.0421)

    def test_claude_cli_output_with_preceding_text(self):
        body = (
            "Claude Code started\n"
            + json.dumps({
                "usage": {"input_tokens": 500, "output_tokens": 200},
                "total_cost_usd": 0.015,
            })
            + "\nDone.\n"
        )
        u = parse_usage(body)
        self.assertEqual(u["tokens"], 700)
        self.assertEqual(u["input_tokens"], 500)
        self.assertEqual(u["output_tokens"], 200)
        self.assertAlmostEqual(u["cost"], 0.015)

    def test_other_runners_report_nothing_store_null_never_guess(self):
        # Plain text output
        u = parse_usage("Some non-JSON output from codex or gemini")
        self.assertIsNone(u["tokens"])
        self.assertIsNone(u["cost"])
        self.assertIsNone(u["input_tokens"])
        self.assertIsNone(u["output_tokens"])

        # Empty output
        u = parse_usage("")
        self.assertIsNone(u["tokens"])
        self.assertIsNone(u["cost"])

        # JSON output without usage or total_cost_usd
        u = parse_usage(json.dumps({"response": "ok", "status": "SUCCESS"}))
        self.assertIsNone(u["tokens"])
        self.assertIsNone(u["cost"])


class TestTaskUsageStorage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "ws"
        self.ws.mkdir()
        (self.ws / ".git").mkdir()
        self.config = {
            "version": 1,
            "shape": "single",
            "repos": [{"id": "repo1", "path": ".", "role": "backend", "profile": "python"}],
            "runners": {
                "claude": {
                    "command": "claude",
                    "args": ["--output-format", "json"],
                }
            }
        }
        import yaml
        (self.ws / "sentinel.config.yaml").write_text(yaml.dump(self.config))
        self.eng = Engine(self.ws / ".sentinel", self.ws, self.config)
        self.eng.create_run("run-1", "human", baseline={"repo1": "a" * 40}, driver="engine")
        self.eng.reg.update_run("run-1", state="EXECUTING")

    def tearDown(self):
        self.eng.close()
        self._tmp.cleanup()

    def test_finish_task_stores_usage_and_emits_event(self):
        t = self.eng.create_task("run-1", "tdd_green", "Implement feature", repos=["repo1"])
        self.eng.queue_task(t["id"])
        self.eng.start_task(t["id"])

        tdir = self.eng.task_dir("run-1", t["id"])
        (tdir / "result.json").write_text(json.dumps({
            "schema": "agent-result-v1",
            "task_id": t["id"],
            "status": "completed",
            "summary": "done",
        }))

        row = self.eng.finish_task(
            t["id"],
            exit_code=0,
            seconds=12.5,
            tokens=450,
            cost=0.012,
            input_tokens=350,
            output_tokens=100,
        )

        # Stored in task row
        self.assertEqual(row["tokens"], 450)
        self.assertEqual(row["input_tokens"], 350)
        self.assertEqual(row["output_tokens"], 100)
        self.assertAlmostEqual(row["cost"], 0.012)
        self.assertEqual(row["seconds"], 12.5)

        # Stored in registry
        db_row = self.eng.reg.get_row("tasks", t["id"])
        self.assertEqual(db_row["tokens"], 450)
        self.assertEqual(db_row["input_tokens"], 350)
        self.assertEqual(db_row["output_tokens"], 100)
        self.assertAlmostEqual(db_row["cost"], 0.012)

        # Stored in task.finished event payload
        events = self.eng.reg.list_events(self.eng._get("run-1")["id"], "task.finished")
        self.assertTrue(events)
        payload = events[-1]["payload"]
        self.assertEqual(payload["tokens"], 450)
        self.assertEqual(payload["input_tokens"], 350)
        self.assertEqual(payload["output_tokens"], 100)
        self.assertAlmostEqual(payload["cost"], 0.012)


class TestBudgetAndFactory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "ws"
        self.ws.mkdir()
        (self.ws / ".git").mkdir()
        self.config = {
            "version": 1,
            "shape": "single",
            "repos": [{"id": "repo1", "path": ".", "role": "backend", "profile": "python"}],
            "factory": {
                "budget": {
                    "tokens_per_day": 1000,
                    "usd_per_day": 0.50,
                }
            }
        }
        import yaml
        (self.ws / "sentinel.config.yaml").write_text(yaml.dump(self.config))
        self.eng = Engine(self.ws / ".sentinel", self.ws, self.config)
        self.eng.create_run("run-budget", "human", baseline={"repo1": "a" * 40}, driver="engine")
        self.eng.reg.update_run("run-budget", state="EXECUTING")

    def tearDown(self):
        self.eng.close()
        self._tmp.cleanup()

    def test_budget_config_parsed(self):
        fc = factory.factory_config(self.config)
        self.assertIn("budget", fc)
        self.assertEqual(fc["budget"]["tokens_per_day"], 1000)
        self.assertAlmostEqual(fc["budget"]["usd_per_day"], 0.50)

    def test_budget_status_and_snapshot(self):
        # Under budget initially
        status = factory.budget_status(self.eng)
        self.assertFalse(status["reached"])
        self.assertEqual(status["tokens_today"], 0)
        self.assertEqual(status["cost_today"], 0.0)

        # Complete a task that exceeds token budget
        t = self.eng.create_task("run-budget", "tdd_green", "Implement feature", repos=["repo1"])
        self.eng.queue_task(t["id"])
        self.eng.start_task(t["id"])
        tdir = self.eng.task_dir("run-budget", t["id"])
        (tdir / "result.json").write_text(json.dumps({
            "schema": "agent-result-v1",
            "task_id": t["id"],
            "status": "completed",
            "summary": "done",
        }))
        self.eng.finish_task(t["id"], tokens=1200, cost=0.10, input_tokens=1000, output_tokens=200)

        status_after = factory.budget_status(self.eng)
        self.assertTrue(status_after["reached"])
        self.assertEqual(status_after["tokens_today"], 1200)

        snap = factory.snapshot(self.eng, "project-1")
        self.assertIn("budget", snap)
        self.assertTrue(snap["budget"]["reached"])
        self.assertEqual(snap["budget"]["tokens_today"], 1200)


class TestRetryNowRoute(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "ws"
        self.ws.mkdir()
        (self.ws / ".git").mkdir()
        self.config = {
            "version": 1,
            "shape": "single",
            "repos": [{"id": "repo1", "path": ".", "role": "backend", "profile": "python"}],
        }
        import yaml
        (self.ws / "sentinel.config.yaml").write_text(yaml.dump(self.config))
        self.eng = Engine(self.ws / ".sentinel", self.ws, self.config)
        self.eng.create_run("run-limit", "human", baseline={"repo1": "a" * 40}, driver="engine")

    def tearDown(self):
        self.eng.close()
        self._tmp.cleanup()

    def test_ops_retry_now_clears_retry_at_and_audits(self):
        t = self.eng.create_task("run-limit", "tdd_green", "Implement feature", repos=["repo1"])
        self.eng.queue_task(t["id"])
        # Set task in limit wait
        with self.eng.reg.transaction():
            self.eng.reg.update_row("tasks", t["id"], retry_at="2099-01-01T00:00:00.000000Z")

        res = ops.retry_now(self.eng, "run-limit", "dev")
        self.assertEqual(res["resumed_tasks"], [t["id"]])

        # retry_at should now be cleared
        row = self.eng.reg.get_row("tasks", t["id"])
        self.assertIsNone(row["retry_at"])

        # Audited
        audit = self.eng.reg._c.execute("SELECT * FROM audit WHERE action='retry_limit_now'").fetchall()
        self.assertTrue(audit)
        self.assertEqual(audit[-1]["target"], "run-limit")


class TestDispatcherAndNotificationsBudget(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "ws"
        self.ws.mkdir()
        (self.ws / ".git").mkdir()
        self.config = {
            "version": 1,
            "shape": "single",
            "project": {"name": "test-project"},
            "repos": [{"id": "repo1", "path": ".", "role": "backend", "profile": "python"}],
            "factory": {
                "budget": {
                    "tokens_per_day": 500,
                    "usd_per_day": 0.10,
                }
            }
        }
        import yaml
        (self.ws / "sentinel.config.yaml").write_text(yaml.dump(self.config))
        self.eng = Engine(self.ws / ".sentinel", self.ws, self.config)
        self.eng.create_run("run-budget-dispatch", "human", baseline={"repo1": "a" * 40}, driver="engine")
        self.eng.reg.update_run("run-budget-dispatch", state="EXECUTING")

    def tearDown(self):
        self.eng.close()
        self._tmp.cleanup()

    def test_budget_notification_rule(self):
        import notifications as N
        hit = N.rule("budget.reached", {"reason": "daily limit exceeded"}, "run-1")
        self.assertIsNotNone(hit)
        level, text, link, cmd = hit
        self.assertEqual(level, "warning")
        self.assertEqual(text, "daily limit exceeded")
        self.assertIsNone(cmd)

    def test_dispatcher_stops_tasks_and_emits_budget_reached_event(self):
        from apiserver.dispatch import Dispatcher
        from apiserver.projects import Project

        # Consume budget
        t = self.eng.create_task("run-budget-dispatch", "tdd_green", "Implement feature", repos=["repo1"])
        self.eng.queue_task(t["id"])
        self.eng.start_task(t["id"])
        tdir = self.eng.task_dir("run-budget-dispatch", t["id"])
        (tdir / "result.json").write_text(json.dumps({
            "schema": "agent-result-v1",
            "task_id": t["id"],
            "status": "completed",
            "summary": "done",
        }))
        self.eng.finish_task(t["id"], tokens=600, cost=0.15, input_tokens=500, output_tokens=100)

        # Create another queued task that should NOT be started
        t2 = self.eng.create_task("run-budget-dispatch", "tdd_green", "Implement feature 2", repos=["repo1"])
        self.eng.queue_task(t2["id"])

        # Mock projects set
        proj = Project({"id": "test-project", "name": "test-project", "path": str(self.ws)})
        mock_projects = mock.MagicMock()
        mock_projects.cfgdir = self.root / "cfg"
        mock_projects.list.return_value = [proj]
        mock_projects.probe.return_value = ("available", None)
        mock_projects.require.return_value = self.config
        @contextmanager
        def eng_ctx(*a, **kw):
            yield self.eng
        mock_projects.engine.side_effect = eng_ctx
        @contextmanager
        def reader_ctx(*a, **kw):
            yield self.eng.reg._c
        mock_projects.reader.side_effect = reader_ctx

        dispatcher = Dispatcher(mock_projects)
        # Check _budget_reached emits event and returns True
        reached = dispatcher._budget_reached(proj)
        self.assertTrue(reached)

        # Verify event was recorded
        rows = self.eng.reg._c.execute("SELECT type, payload FROM events WHERE type = 'budget.reached'").fetchall()
        self.assertEqual(len(rows), 1)
        p = json.loads(rows[0][1])
        self.assertIn("tokens_today", p)
        self.assertIn("resets_at", p)

        # Calling again today is idempotent (no duplicate event)
        reached2 = dispatcher._budget_reached(proj)
        self.assertTrue(reached2)
        rows2 = self.eng.reg._c.execute("SELECT type FROM events WHERE type = 'budget.reached'").fetchall()
        self.assertEqual(len(rows2), 1)

        # Check once() returns nothing started
        started = dispatcher.once()
        self.assertEqual(started, [])


class TestAnalyticsUsageMetricsAndCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "ws"
        self.ws.mkdir()
        (self.ws / ".git").mkdir()
        self.config = {
            "version": 1,
            "shape": "single",
            "project": {"name": "usage-proj"},
            "repos": [{"id": "repo1", "path": ".", "role": "backend", "profile": "python"}],
        }
        import yaml
        (self.ws / "sentinel.config.yaml").write_text(yaml.dump(self.config))
        self.eng = Engine(self.ws / ".sentinel", self.ws, self.config)
        self.eng.create_run("run-u", "human", baseline={"repo1": "a" * 40}, driver="engine")
        self.eng.reg.update_run("run-u", state="EXECUTING")

    def tearDown(self):
        self.eng.close()
        self._tmp.cleanup()

    def test_analytics_usage_breakdown(self):
        t1 = self.eng.create_task("run-u", "tdd_green", "Implement feature", repos=["repo1"])
        self.eng.queue_task(t1["id"])
        self.eng.start_task(t1["id"])
        with self.eng.reg.transaction():
            self.eng.reg.update_row("tasks", t1["id"], provider="claude", model="sonnet-4.6")
        tdir = self.eng.task_dir("run-u", t1["id"])
        (tdir / "result.json").write_text(json.dumps({"schema": "agent-result-v1", "task_id": t1["id"], "status": "completed"}))
        self.eng.finish_task(t1["id"], tokens=800, cost=0.03, input_tokens=600, output_tokens=200, seconds=10.0)

        # Compute analytics
        res = analytics.compute(self.ws / ".sentinel" / "sentinel.db")
        self.assertIn("usage", res)
        u = res["usage"]
        self.assertFalse(analytics.is_null(u["total"]))
        self.assertEqual(u["total"]["tokens"], 800)
        self.assertEqual(u["total"]["input_tokens"], 600)
        self.assertEqual(u["total"]["output_tokens"], 200)
        self.assertEqual(u["total"]["reported_tasks"], 1)

        # compute_usage
        sources = [("usage-proj", self.ws / ".sentinel" / "sentinel.db")]
        multi = analytics.compute_usage(sources)
        self.assertEqual(multi["totals"]["tokens"], 800)
        self.assertIn("usage-proj", multi["by_project"])
        self.assertEqual(multi["by_project"]["usage-proj"]["tokens"], 800)
        self.assertIn("sonnet-4.6", multi["by_model"])

        # Markdown formatting
        md = analytics.markdown_usage(multi)
        self.assertIn("# Usage Report", md)
        self.assertIn("800", md)
        self.assertIn("usage-proj", md)
        self.assertIn("sonnet-4.6", md)

    def test_cli_stats_usage(self):
        import io
        from contextlib import redirect_stdout
        import sentinel
        from argparse import Namespace

        t1 = self.eng.create_task("run-u", "tdd_green", "Implement feature", repos=["repo1"])
        self.eng.queue_task(t1["id"])
        self.eng.start_task(t1["id"])
        with self.eng.reg.transaction():
            self.eng.reg.update_row("tasks", t1["id"], provider="claude", model="sonnet-4.6")
        tdir = self.eng.task_dir("run-u", t1["id"])
        (tdir / "result.json").write_text(json.dumps({"schema": "agent-result-v1", "task_id": t1["id"], "status": "completed"}))
        self.eng.finish_task(t1["id"], tokens=500, cost=0.02, input_tokens=400, output_tokens=100)

        buf = io.StringIO()
        args = Namespace(
            usage=True,
            project="usage-proj",
            since=None,
            from_day=None,
            to_day=None,
            format="json",
            dir=self.ws,
        )
        with redirect_stdout(buf):
            sentinel.cmd_stats(args)
        out = json.loads(buf.getvalue())
        self.assertIn("totals", out)
        self.assertEqual(out["totals"]["tokens"], 500)
        self.assertIn("usage-proj", out["by_project"])

        # Format md
        buf_md = io.StringIO()
        args.format = "md"
        with redirect_stdout(buf_md):
            sentinel.cmd_stats(args)
        self.assertIn("# Usage Report", buf_md.getvalue())
        self.assertIn("usage-proj", buf_md.getvalue())


if __name__ == "__main__":
    unittest.main()
