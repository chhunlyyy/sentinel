"""Phase H part A: fixes for the Opus review (scrub before clip, user.db concurrency, URI paths, analytics definitions, CLI guards)."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import test_analytics as TA
import test_notifications as TN
from sv_helpers import SENTINEL

WEIRD = "we#ird?x%y"


class ScrubBeforeClip(TN.NT):
    def test_a_secret_that_the_clip_would_cut_is_still_scrubbed(self):
        rows = [("x" * 185 + " password=qzvhunter2hunter2 tail", "password=qz"),
                ("y" * 172 + " ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8 tail", "ghp_A1b2")]
        for reason, secret in rows:
            with self.subTest(secret=secret):
                self.ev("run.state_changed", {"to": "NEEDS_HUMAN", "reason": reason})
                for n in self.notes(limit=200)["items"]:
                    self.assertNotIn(secret, n["text"])
                self.assertLessEqual(max(len(n["text"]) for n in self.notes(limit=200)["items"]), 200)


class UserDbConcurrency(TN.NT):
    def test_AC_NOT_01m_first_creation_races_20_times(self):
        import notifications
        ids = [self.ev("run.created", {"tier": 1}) for _ in range(8)]
        for round_no in range(20):
            for f in self.cfgdir.glob("user.db*"):
                f.unlink()
            barrier, errors = threading.Barrier(8), []

            def mark(i):
                try:
                    barrier.wait(10)
                    notifications.mark_read(self.sources(), notifications.user_db_path(), f"digital-hr:{ids[i]}")
                except Exception as e:  # noqa: BLE001
                    errors.append(repr(e))
            threads = [threading.Thread(target=mark, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
            self.assertEqual(errors, [], f"round {round_no}")
            self.assertEqual(len(self.user_rows()), 8, f"round {round_no}")


class WeirdPath(TN.NT):
    def setUp(self):
        super().setUp()
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.weird = self.base / WEIRD
        self.weird.mkdir()
        shutil.copytree(self.ws / ".sentinel", self.weird / ".sentinel")
        shutil.copy(self.ws / "sentinel.config.yaml", self.weird / "sentinel.config.yaml")
        self.wdb = self.weird / ".sentinel" / "sentinel.db"
        self.add_project("weird", self.weird)

    def entries(self):
        return sorted(p.name for p in self.base.iterdir()) + sorted(p.name for p in self.weird.iterdir())

    def test_every_read_only_open_keeps_the_path_literal(self):
        import analytics
        from apiserver.projects import ProjectSet
        from apiserver.stream import Hub
        eid = self.ev("run.created", {"tier": 1}, dbp=self.wdb)
        before = self.entries()
        got = self.notes(project="weird")
        self.assertEqual([n["id"] for n in got["items"]], [f"weird:{eid}"])
        self.assertEqual(got["unavailable"], [])
        self.assertEqual(analytics.compute(self.wdb)["runs"]["total"], 1)
        projects = ProjectSet(self.cfgdir)
        with projects.ro(projects.get("weird")) as conn:
            self.assertIsNotNone(conn)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
        conn = Hub(projects)._open(projects.get("weird"))
        self.assertIsNotNone(conn)
        conn.close()
        self.assertEqual(self.entries(), before)


class AnalyticsDefinitions(TA.AN):
    def evidence(self, run, rnd, kind, verdict, i):
        self.sql("INSERT INTO evidence(id, run_id, kind, round, verdict) VALUES (?,?,?,?,?)", (f"x{i}", run, kind, rnd, verdict))

    def test_AC_ANL_01e_unfinished_runs_have_no_part_in_verification_rates(self):
        before = self.full()["verification"]
        self.evidence("r-fou", 1, "lint", "fail", 1)
        self.evidence("r-fou", 1, "test", "fail", 2)
        self.assertEqual(self.full()["verification"], before)

    def test_lead_time_counts_completed_and_failed_runs_but_not_cancelled_ones(self):
        self.sql("INSERT INTO runs(id, slug, type, state, execution_status, acceptance_status, workflow_version, created_at, updated_at, finished_at) "
                 "VALUES ('r-can','r-can','feature','CANCELLED','cancelled','pending','2',"
                 "'2026-11-05T09:00:00.000000Z','2026-11-05T09:00:00.000000Z','2026-11-05T19:00:00.000000Z')")
        a = self.full()
        self.assertEqual(a["runs"]["by_state"]["CANCELLED"], 1)
        self.assertEqual(a["lead_time_seconds"], {"count": 3, "median": 7200, "p90": 14400})

    def test_N8_a_cancelled_rejected_run_is_not_decided(self):
        self.sql("INSERT INTO runs(id, slug, type, state, execution_status, acceptance_status, workflow_version, created_at, updated_at, finished_at) "
                 "VALUES ('r-can','r-can','feature','CANCELLED','cancelled','rejected','2',"
                 "'2026-11-05T09:00:00.000000Z','2026-11-05T09:00:00.000000Z','2026-11-05T19:00:00.000000Z')")
        self.assertEqual(self.full()["acceptance_rate"], {"value": 0.5, "accepted": 1, "decided": 2})

    def test_M9_only_E_PROVIDER_counts_as_a_provider_failure(self):
        self.sql("INSERT INTO tasks(id, run_id, role, provider, state, error_code, seconds, created_at) "
                 "VALUES ('t9','r-one','tdd_green','codex','FAILED','E_EXIT',5,'2026-11-01T09:00:00.000000Z')")
        self.assertEqual(self.full()["provider_failure_rate"]["codex"], {"value": 0.2, "failures": 1, "tasks": 5})

    def test_M15_evidence_without_a_round_is_not_verification(self):
        before = self.full()["verification"]
        self.evidence("r-one", None, "lint", "fail", 1)
        self.assertEqual(self.full()["verification"], before)

    def fresh_approvals(self, rows):
        """rows: (id, run, gate, version, requested or None, decided). Replaces the fixture approvals."""
        self.sql("DROP TRIGGER events_no_delete")
        self.sql("DELETE FROM approvals")
        self.sql("DELETE FROM events WHERE type = 'approval.requested'")
        for aid, run, gate, ver, req, dec in rows:
            self.sql("INSERT INTO approvals(id, run_id, gate, version, state, decision, decided_at) VALUES (?,?,?,?,?,?,?)",
                     (aid, run, gate, ver, "APPROVED", "approve", dec))
            if req:
                self.sql("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)",
                         (run, "approval.requested", "engine", json.dumps({"gate": gate, "version": ver}), req))

    def test_N13_the_wait_of_each_approval_uses_its_own_request_event(self):
        self.fresh_approvals([("a1", "r-two", "specification", 1, TA.at("02", "09:00"), TA.at("02", "09:10")),
                              ("a2", "r-two", "specification", 2, TA.at("02", "10:00"), TA.at("02", "10:50"))])
        self.assertEqual(self.full()["approval_wait_seconds"]["specification"], {"count": 2, "median": 1800, "p90": 3000})

    def test_a_wait_is_never_negative_and_an_unmatched_gate_says_so(self):
        self.fresh_approvals([("a1", "r-one", "specification", 1, TA.at("01", "10:00"), TA.at("01", "09:00")),
                              ("a2", "r-one", "gherkin", 1, None, TA.at("01", "09:30"))])
        w = self.full()["approval_wait_seconds"]
        self.assertEqual(w["specification"], {"value": None, "reason": "no request event"})
        self.assertEqual(w["gherkin"], {"value": None, "reason": "no request event"})

    def test_the_latest_request_before_the_decision_is_used(self):
        self.fresh_approvals([("a1", "r-one", "specification", 1, TA.at("01", "09:00"), TA.at("01", "09:50"))])
        self.sql("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)",
                 ("r-one", "approval.requested", "engine", json.dumps({"gate": "specification", "version": 1}), TA.at("01", "09:30")))
        self.assertEqual(self.full()["approval_wait_seconds"]["specification"], {"count": 1, "median": 1200, "p90": 1200})

    def test_runner_ids_survives_a_broken_runners_section(self):
        import analytics
        self.assertEqual(analytics.runner_ids({"runners": {"x": 5}}), [])
        self.assertIn("codex", analytics.runner_ids({}))


class RuleTable(TN.NT):
    def test_M2_failing_cycle_evidence_is_not_a_verification_notification(self):
        self.ev("evidence.recorded", {"kind": "test", "passed": False, "verdict": "fail", "cycle": "c-1", "round": None})
        self.assertEqual(self.notes()["items"], [])


class CliGuards(TN.NT):
    def test_limit_must_be_in_range(self):
        for value in ("0", "-3", "201", "abc"):
            with self.subTest(limit=value):
                c, out, err = self.cli_n("--limit", value)
                self.assertEqual(c, 2, (out, err))
                self.assertIn("limit", err)

    def test_a_task_process_may_not_mark_notifications_read(self):
        eid = self.ev("run.created", {"tier": 1})
        for args in (("read", f"digital-hr:{eid}"), ("read", "--all")):
            with self.subTest(args=args):
                p = subprocess.run([sys.executable, SENTINEL, "notifications", *args], capture_output=True, text=True,
                                   env=self.env(**self.home_env(), SENTINEL_TASK_ID="t-1"))
                self.assertNotEqual(p.returncode, 0)
                self.assertIn("E_ACTOR", p.stderr + p.stdout)
        self.assertEqual(self.user_rows(), [])

    def test_the_agent_deny_list_names_notifications_read(self):
        import sentinel
        rules = sentinel.HUMAN_ONLY_COMMANDS
        self.assertIn("Bash(sentinel notifications read:*)", rules)
        self.assertIn("Bash(sentinel --dir * notifications read *)", rules)


class Registries(TN.NT):
    def test_M5_two_registries_with_the_same_event_numbers_keep_separate_read_states(self):
        import notifications
        self.ev("run.created", {"tier": 1})
        eid = self.ev("run.created", {"tier": 2})
        notifications.mark_read(self.sources(), notifications.user_db_path(), f"digital-hr:{eid}")
        self.assertEqual(self.notes()["unread"], 1)
        c = sqlite3.connect(self.dbp)
        c.execute("DROP TRIGGER events_no_update")
        c.execute("INSERT INTO runs(id, slug, type, state, execution_status, acceptance_status, workflow_version, created_at, updated_at) "
                  "VALUES ('r2','other','feature','EXECUTING','running','pending','2','2026-11-14T08:00:00.000000Z','2026-11-14T08:00:00.000000Z')")
        c.execute("UPDATE events SET run_id = 'r2' WHERE id = (SELECT MIN(id) FROM events)")  # another registry: same ids, same times
        c.commit()
        c.close()
        a = self.notes()
        self.assertEqual(a["unread"], 2)


class Ids(TN.NT):
    def test_ids_with_control_characters_or_traversal_are_validation_errors(self):
        self.ev("run.created", {"tier": 1})
        self.serve()
        for nid in ("digital-hr%00:1", "a%00b:1", "..%2F..%2Fuser.db:1", "%2e%2e%2fuser.db:1"):
            with self.subTest(id=nid):
                r = self.http.post(f"/api/v1/notifications/{nid}/read", {})
                self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)
        self.assertFalse(self.user_db().exists())


if __name__ == "__main__":
    unittest.main()
