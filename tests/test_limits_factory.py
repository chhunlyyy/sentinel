"""Sentinel 2.1: usage limits and routing problems in the factory snapshot, and the routing fix route."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import factory  # noqa: E402
import test_factory as tf  # noqa: E402
from pc_helpers import git  # noqa: E402
from sv_helpers import SV  # noqa: E402


class Served(SV):
    """The served project of test_factory.Served (its tests are not repeated here)."""

    def setUp(self):
        super().setUp()
        script = self.script("fake", tf.fake_body())
        self.use_config(single_model=False, runners={"fake": {"command": script}}, agents=tf.agents())

    def make_run(self, slug=tf.SLUG, driver="engine"):
        sha = git(self.ws / "backend", "rev-parse", "HEAD").strip()
        self.eng.create_run(slug, "human", type="feature", request=tf.REQUEST, baseline={"backend": sha}, driver=driver)
        return slug


class Snapshot(Served):
    def queue_limited(self, minutes_from_now=60):
        self.make_run()
        self.serve()
        self.eng.reg.update_run(tf.SLUG, state="TRIAGED", tier=3)
        tid = self.eng.create_task(tf.SLUG, "planner", repos=["backend"], objective="plan", queue=True)["id"]
        from datetime import datetime, timedelta, timezone
        at = (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self.eng.reg.transaction():
            self.eng.reg.update_row("tasks", tid, retry_at=at, limit_reason="usage limit reached", provider="fake")
        return tid, at

    def snap(self):
        return self.http.get("/api/v1/projects/digital-hr/factory").json

    def test_a_task_waiting_for_a_limit_shows_the_limit_station_state(self):
        tid, at = self.queue_limited()
        run = self.snap()["runs"][0]
        self.assertEqual(run["stations"]["triage"], "limit")
        self.assertEqual(run["limit"], {"station": "triage", "task": tid, "role": "planner", "runner": "fake", "retry_at": at,
                                        "reason": "usage limit reached"})
        self.assertNotIn("limit", [a["text"] for a in self.snap()["activity"]])

    def test_a_past_retry_at_is_only_queued(self):
        self.queue_limited(minutes_from_now=-5)
        run = self.snap()["runs"][0]
        self.assertEqual(run["stations"]["triage"], "queued")
        self.assertIsNone(run["limit"])

    def test_a_paused_run_looks_paused(self):
        self.queue_limited()
        self.eng.reg.update_run(tf.SLUG, paused=1)
        run = self.snap()["runs"][0]
        self.assertEqual(run["stations"]["triage"], "paused")
        self.assertIsNone(run["limit"])

    def test_the_activity_names_the_limit_event(self):
        tid, _ = self.queue_limited()
        run = self.eng.reg.get_run(tf.SLUG)
        self.eng.reg.add_event(run["id"], "task.limit_reached", "engine",
                               {"role": "planner", "runner": "claude", "fallback": None}, task_id=tid)
        texts = [a["text"] for a in self.snap()["activity"]]
        self.assertIn("Triage agent waits for the claude usage limit", texts)

    def test_routing_problems_in_the_snapshot_only_for_the_engine_driver(self):
        self.use_config()   # no routing: every role is native
        self.make_run()
        self.serve()
        problems = self.snap()["routing"]["problems"]
        self.assertTrue(any(p.startswith("triage routes to the native adapter") for p in problems), problems)
        self.use_config(factory={"driver": "ai-tool"})
        self.assertEqual(self.snap()["routing"]["problems"], [])

    def test_a_routed_project_has_no_routing_problems(self):
        self.make_run()
        self.serve()
        self.assertEqual(self.snap()["routing"], {"problems": []})


class Fix(Served):
    def test_the_fix_route_suggests_a_runner_per_blocked_role(self):
        self.use_config()
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/routing/fix")
        self.assertEqual(r.status, 200, r.text)
        body = r.json
        self.assertTrue(body["applies"])
        roles = [p["role"] for p in body["problems"]]
        self.assertEqual(roles, list(factory.ENGINE_ROLES))
        first = body["problems"][0]
        self.assertEqual(set(first), {"role", "text", "current", "suggested"})
        self.assertTrue(first["suggested"]["runner"])
        self.assertEqual(body["changes"][0], {"path": "single_model", "value": False})
        self.assertIn({"path": "agents.triage.runner", "value": first["suggested"]["runner"]}, body["changes"])

    def test_the_suggested_changes_clear_the_problems_and_save_with_history(self):
        self.use_config()
        self.serve()
        body = self.http.get("/api/v1/projects/digital-hr/routing/fix").json
        prev = self.http.post("/api/v1/projects/digital-hr/config/preview", {"changes": body["changes"]})
        self.assertEqual(prev.status, 200, prev.text)
        self.assertIn("+  triage:", prev.json["diff"])
        saved = self.http.post("/api/v1/projects/digital-hr/config/save", {"changes": body["changes"], "comment": "Fix routing"})
        self.assertEqual(saved.status, 200, saved.text)
        self.assertEqual(self.http.get("/api/v1/projects/digital-hr/routing/fix").json["problems"], [])
        self.assertEqual(self.snap_problems(), [])
        history = self.http.get("/api/v1/projects/digital-hr/configuration/history").json
        self.assertTrue(any(v.get("comment") == "Fix routing" for v in history.get("items", history.get("versions", []))), history)

    def snap_problems(self):
        return self.http.get("/api/v1/projects/digital-hr/factory").json["routing"]["problems"]

    def test_ai_tool_projects_have_nothing_to_fix(self):
        self.use_config(factory={"driver": "ai-tool"})
        self.serve()
        body = self.http.get("/api/v1/projects/digital-hr/routing/fix").json
        self.assertEqual((body["applies"], body["problems"], body["changes"]), (False, [], []))

    def test_an_unknown_query_is_refused(self):
        self.serve()
        self.assertEqual(self.http.get("/api/v1/projects/digital-hr/routing/fix?x=1").status, 400)
