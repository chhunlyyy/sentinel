"""Phase H part A: local notifications, engine function and CLI (plan/v1.1/phaseH/features/notifications.feature)."""
import json
import os
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from sv_helpers import SV, SENTINEL

RULE_ROWS = [  # event, payload, level, text, link
    ("approval.requested", {"gate": "specification", "version": 1}, "action", "Specification ready for review", "/tasks/leave-balance/specification"),
    ("approval.requested", {"gate": "gherkin", "version": 2}, "action", "Gherkin ready for review", "/tasks/leave-balance/gherkin"),
    ("approval.decided", {"decision": "changes_requested", "gate": "specification"}, "info", "Changes requested", "/tasks/leave-balance/specification"),
    ("approval.decided", {"decision": "changes", "gate": "gherkin"}, "info", "Changes requested", "/tasks/leave-balance/gherkin"),
    ("run.created", {"tier": 2, "type": "feature"}, "info", "Run started", "/tasks/leave-balance"),
    ("run.state_changed", {"to": "NEEDS_HUMAN", "reason": "unknown Red failure"}, "action", "unknown Red failure", "/tasks/leave-balance"),
    ("run.state_changed", {"to": "BLOCKED", "reason": "runner codex not installed"}, "warning", "runner codex not installed", "/tasks/leave-balance"),
    ("task.finished", {"state": "FAILED", "role": "tdd_green", "error_code": "E_EXIT"}, "warning", "tdd_green failed: E_EXIT", "/tasks/leave-balance/workflow"),
    ("task.finished", {"state": "FAILED", "error_code": "E_PROVIDER", "provider": "codex"}, "warning", "Provider codex unavailable", "/tasks/leave-balance/workflow"),
    ("evidence.recorded", {"kind": "lint", "passed": False, "round": 1, "verdict": "fail"}, "warning", "Verification failed: lint", "/tasks/leave-balance/verification"),
    ("run.status_changed", {"execution_status": "completed", "acceptance_status": "pending"}, "action", "Run completed, waiting for acceptance", "/tasks/leave-balance/verification"),
    ("run.status_changed", {"execution_status": "completed", "acceptance_status": "accepted"}, "info", "Run accepted", "/tasks/leave-balance"),
    ("run.status_changed", {"execution_status": "completed", "acceptance_status": "rejected"}, "warning", "Run rejected", "/tasks/leave-balance"),
    ("run.status_changed", {"execution_status": "failed", "acceptance_status": "pending"}, "warning", "Run failed", "/tasks/leave-balance"),
]
NO_RULE_ROWS = [
    ("task.progress", {"elapsed_seconds": 5}), ("task.started", {"role": "tdd_green"}), ("run.state_changed", {"to": "EXECUTING", "reason": None}),
    ("approval.decided", {"decision": "approve", "gate": "specification"}), ("task.finished", {"state": "COMPLETED"}),
    ("evidence.recorded", {"kind": "test", "passed": True, "round": 1, "verdict": "pass"}),
]


class NT(SV):
    def setUp(self):
        super().setUp()
        self.eng.close()
        self.dbp = self.ws / ".sentinel" / "sentinel.db"
        self.seq = 0
        self.add_project()
        self.add_run(self.dbp, "r1", "leave-balance")

    def add_run(self, dbp, rid, slug, wf="2"):
        c = sqlite3.connect(dbp)
        c.execute("INSERT INTO runs(id, slug, type, state, execution_status, acceptance_status, workflow_version, created_at, updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (rid, slug, "feature", "EXECUTING", "running", "pending", wf, "2026-11-14T08:00:00.000000Z", "2026-11-14T08:00:00.000000Z"))
        c.commit()
        c.close()

    def ev(self, type, payload=None, run="r1", dbp=None, at=None, task=None):
        self.seq += 1
        at = at or f"2026-11-14T09:{self.seq // 60:02d}:{self.seq % 60:02d}.000000Z"
        c = sqlite3.connect(dbp or self.dbp)
        try:
            cur = c.execute("INSERT INTO events(run_id, task_id, type, actor, payload, at) VALUES (?,?,?,?,?,?)",
                            (run, task, type, "engine", json.dumps(payload or {}), at))
            c.commit()
            return cur.lastrowid
        finally:
            c.close()

    def sources(self):
        import notifications
        return notifications.sources_from_registry(self.cfgdir)

    def notes(self, **kw):
        import notifications
        return notifications.compute(self.sources(), notifications.user_db_path(), **kw)

    def user_db(self):
        return self.cfgdir / "user.db"

    def home_env(self):
        return {"HOME": str(self.home), "XDG_CONFIG_HOME": ""}

    def cli_n(self, *args):
        return self.cli("notifications", *args, **self.home_env())

    def user_rows(self):
        if not self.user_db().exists():
            return []
        c = sqlite3.connect(self.user_db())
        try:
            return c.execute("SELECT project, event_id, read_at FROM notification_reads ORDER BY event_id").fetchall()
        finally:
            c.close()


class Rules(NT):
    def test_AC_NOT_01a_an_event_that_matches_a_rule_gives_one_notification(self):
        for i, (event, payload, level, text, link) in enumerate(RULE_ROWS):
            with self.subTest(event=event, payload=payload):
                eid = self.ev(event, payload)
                items = self.notes()["items"]
                mine = [n for n in items if n["id"] == f"digital-hr:{eid}"]
                self.assertEqual(len(mine), 1, items)
                self.assertEqual(len(items), i + 1)
                n = mine[0]
                self.assertEqual(n["level"], level)
                self.assertIn(text, n["text"])
                self.assertEqual(n["link"], link)
                self.assertEqual((n["project"], n["run"]), ("digital-hr", "leave-balance"))

    def test_AC_NOT_01a_the_event_contract_lists_the_rules_and_no_stored_notification(self):
        text = (Path(__file__).resolve().parents[1] / "docs" / "contracts" / "event-contracts.md").read_text()
        self.assertNotIn("notification.created", text)
        for word in ("Specification ready for review", "Gherkin ready for review", "Changes requested", "Verification failed", "Run started",
                     "Run completed, waiting for acceptance", "Run accepted", "Run rejected", "Run failed", "unavailable", "user.db", "run.created"):
            self.assertIn(word, text)

    def test_AC_NOT_01b_events_without_a_rule_give_no_notification(self):
        for event, payload in NO_RULE_ROWS:
            with self.subTest(event=event, payload=payload):
                self.ev(event, payload)
                self.assertEqual(self.notes()["items"], [])

    def test_AC_NOT_01d_a_fresh_installation_has_no_notifications(self):
        import shutil
        shutil.rmtree(self.cfgdir)
        self.assertEqual(self.notes(), {"items": [], "next": None, "unread": 0, "unavailable": []})
        c, out, err = self.cli_n("--json")
        self.assertEqual(c, 0, err)
        j = json.loads(out)
        self.assertEqual((j["items"], j["unread"]), ([], 0))
        self.assertFalse(self.user_db().exists())
        self.assertFalse(self.cfgdir.exists())

    def test_AC_NOT_01e_several_projects_newest_first_with_paging(self):
        d, eng = self.extra_workspace("payroll")
        eng.close()
        pdb = d / ".sentinel" / "sentinel.db"
        self.add_run(pdb, "p1", "pay-run")
        c = sqlite3.connect(self.dbp)
        c.executemany("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)",
                      [("r1", "run.created", "engine", "{}", f"2026-11-14T10:{i // 60:02d}:{i % 60:02d}.000000Z") for i in range(120)])
        c.commit()
        c.close()
        c = sqlite3.connect(pdb)
        c.executemany("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)",
                      [("p1", "run.created", "engine", "{}", f"2026-11-14T10:{i // 60:02d}:{i % 60:02d}.500000Z") for i in range(30)])
        c.commit()
        c.close()
        first = self.notes(limit=50)
        self.assertEqual(len(first["items"]), 50)
        self.assertEqual(first["unread"], 150)
        ats = [n["at"] for n in first["items"]]
        self.assertEqual(ats, sorted(ats, reverse=True))
        self.assertTrue(first["next"])
        seen = list(first["items"])
        cursor = first["next"]
        pages = 1
        while cursor:
            page = self.notes(limit=50, cursor=cursor)
            seen += page["items"]
            cursor = page["next"]
            pages += 1
        self.assertEqual((pages, len(seen), len({n["id"] for n in seen})), (3, 150, 150))
        self.assertEqual(len(seen[100:]), 50)
        only = self.notes(project="payroll", limit=200)
        self.assertEqual((len(only["items"]), {n["project"] for n in only["items"]}), (30, {"payroll"}))

    def test_AC_NOT_01f_an_unavailable_project_does_not_hide_the_others(self):
        d, eng = self.extra_workspace("payroll")
        eng.close()
        self.ev("run.created", {"tier": 1})
        (d / ".sentinel" / "sentinel.db").write_bytes(b"garbage" * 200)
        a = self.notes()
        self.assertEqual([n["project"] for n in a["items"]], ["digital-hr"])
        self.assertEqual([u["project"] for u in a["unavailable"]], ["payroll"])
        self.assertTrue(a["unavailable"][0]["reason"])

    def test_AC_NOT_01g_01_runs_give_no_notifications(self):
        self.add_run(self.dbp, "old", "old-fix", wf="0.1")
        self.ev("run.created", {"tier": 1}, run="old")
        self.ev("run.state_changed", {"to": "NEEDS_HUMAN", "reason": "x"}, run="old")
        self.assertEqual(self.notes()["items"], [])

    def test_AC_NOT_01o_user_db_is_created_private_and_holds_no_text(self):
        import notifications
        eid = self.ev("run.created", {"tier": 1})
        self.assertFalse(self.user_db().exists())
        notifications.mark_read(self.sources(), notifications.user_db_path(), f"digital-hr:{eid}")
        db = self.user_db()
        self.assertEqual(stat.S_IMODE(db.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.cfgdir.stat().st_mode), 0o700)
        c = sqlite3.connect(db)
        try:
            self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertEqual(c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "1")
            cols = [r[1] for r in c.execute("PRAGMA table_info(notification_reads)")]
            self.assertEqual(sorted(cols), ["event_at", "event_id", "project", "read_at", "registry_id"])
            blob = json.dumps(c.execute("SELECT * FROM notification_reads").fetchall())
            self.assertNotIn("Run started", blob)
        finally:
            c.close()

    def test_AC_NOT_01p_a_restored_registry_does_not_mark_new_events_read(self):
        import notifications
        base = [("run.created", {"tier": 1}, f"2026-11-14T09:00:{i:02d}.000000Z") for i in range(50)]
        for t, p, at in base:
            self.ev(t, p, at=at)
        notifications.mark_all(self.sources(), notifications.user_db_path())
        self.assertEqual(self.notes()["unread"], 0)
        # a restored registry: events 1..40 as before, then new events 41..45 written later
        self.dbp.unlink()
        for ext in ("-wal", "-shm"):
            Path(str(self.dbp) + ext).unlink(missing_ok=True)
        from engine import Engine
        Engine(self.ws / ".sentinel", self.ws, self.config).close()
        self.add_run(self.dbp, "r1", "leave-balance")
        c = sqlite3.connect(self.dbp)
        for i in range(1, 41):
            c.execute("INSERT INTO events(id, run_id, type, actor, payload, at) VALUES (?,?,?,?,?,?)", (i, "r1", "run.created", "engine", "{}", f"2026-11-14T09:00:{i - 1:02d}.000000Z"))
        for i in range(41, 46):
            c.execute("INSERT INTO events(id, run_id, type, actor, payload, at) VALUES (?,?,?,?,?,?)", (i, "r1", "run.created", "engine", "{}", f"2026-11-15T09:00:{i:02d}.000000Z"))
        c.commit()
        c.close()
        a = self.notes(limit=200)
        self.assertEqual(a["unread"], 5)
        self.assertEqual(sorted(int(n["id"].split(":")[1]) for n in a["items"] if not n["read_at"]), [41, 42, 43, 44, 45])


class Cli(NT):
    def three(self):
        return [self.ev("approval.requested", {"gate": "specification", "version": 1}),
                self.ev("run.state_changed", {"to": "NEEDS_HUMAN", "reason": "unknown Red failure"}),
                self.ev("run.status_changed", {"execution_status": "completed", "acceptance_status": "pending"})]

    def test_AC_NOT_01i_listing_and_marking_read_in_a_terminal(self):
        self.three()
        c, out, err = self.cli_n()
        self.assertEqual(c, 0, err)
        for word in ("digital-hr", "action", "Specification ready for review", "unknown Red failure", "sentinel review leave-balance spec",
                     "sentinel resolve leave-balance", "sentinel accept leave-balance", "2026-11-14"):
            self.assertIn(word, out)
        c, out, err = self.cli_n("--unread")
        self.assertEqual(out.count("digital-hr:"), 3, out)
        self.assertEqual(self.cli_n("read", "--all")[0], 0)
        c, out, err = self.cli_n("--unread")
        self.assertEqual((c, out.strip()), (0, ""))
        self.assertEqual(len(self.user_rows()), 3)

    def test_AC_NOT_01i_read_one_by_id_and_errors(self):
        ids = self.three()
        c, out, err = self.cli_n("read", f"digital-hr:{ids[0]}")
        self.assertEqual(c, 0, err)
        self.assertEqual(len(self.user_rows()), 1)
        c, out, err = self.cli_n("read", "digital-hr:999999")
        self.assertNotEqual(c, 0)
        self.assertIn("E_NOT_FOUND", err)
        c, out, err = self.cli_n("read", "digital-hr:abc")
        self.assertNotEqual(c, 0)
        self.assertIn("E_VALIDATION", err)
        c, out, err = self.cli_n("read")
        self.assertEqual(c, 2)

    def test_AC_NOT_01l_marking_read_twice_keeps_the_first_time(self):
        import notifications
        eid = self.ev("run.created", {"tier": 1})
        n = f"digital-hr:{eid}"
        first = notifications.mark_read(self.sources(), notifications.user_db_path(), n)["read_at"]
        time.sleep(0.05)
        c, out, err = self.cli_n("read", n)
        self.assertEqual(c, 0, err)
        self.assertEqual(self.user_rows()[0][2], first)

    def test_AC_NOT_01m_dashboard_and_terminal_mark_read_at_the_same_time(self):
        import notifications
        ids = [self.ev("run.created", {"tier": 1}) for _ in range(10)]
        self.srv_http = self.serve()
        procs, errors = [], []

        def api(i):
            r = self.client().post(f"/api/v1/notifications/digital-hr:{ids[i % 10]}/read", {})
            if r.status != 200:
                errors.append(r.text)
        threads = [threading.Thread(target=api, args=(i,)) for i in range(20)]
        for i in range(20):
            procs.append(subprocess.Popen([sys.executable, SENTINEL, "notifications", "read", f"digital-hr:{ids[i % 10]}"],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env(**self.home_env())))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for p in procs:
            out, err = p.communicate(timeout=30)
            self.assertEqual(p.returncode, 0, err)
        self.assertEqual(errors, [])
        self.assertEqual(len(self.user_rows()), 10)
        self.assertEqual(notifications.compute(self.sources(), notifications.user_db_path())["unread"], 0)

    def test_AC_NOT_01n_user_db_cannot_be_written(self):
        import notifications
        if os.geteuid() == 0:
            self.skipTest("root ignores file modes")
        a, b = self.ev("run.created", {"tier": 1}), self.ev("run.created", {"tier": 2})
        notifications.mark_read(self.sources(), notifications.user_db_path(), f"digital-hr:{a}")
        os.chmod(self.user_db(), 0o400)
        self.addCleanup(lambda: os.chmod(self.user_db(), 0o600))
        with self.assertRaises(notifications.UserDbError) as cm:
            notifications.mark_read(self.sources(), notifications.user_db_path(), f"digital-hr:{b}")
        self.assertIn(str(self.user_db()), cm.exception.fix)
        self.assertIn("0400", cm.exception.fix)
        c, out, err = self.cli_n("read", f"digital-hr:{b}")
        self.assertEqual(c, 1)
        self.assertIn("user.db", err)
        listing = self.notes()
        self.assertEqual(len(listing["items"]), 2)

    def test_AC_NOT_01n_the_list_loads_when_user_db_is_unreadable(self):
        self.ev("run.created", {"tier": 1})
        self.cfgdir.mkdir(parents=True, exist_ok=True)
        self.user_db().write_bytes(b"not a database" * 50)
        a = self.notes()
        self.assertEqual((len(a["items"]), a["unread"]), (1, 1))


class Security(NT):
    def test_AC_NOT_03b_reading_notifications_leaves_approvals_and_audit_unchanged(self):
        self.use_config()
        self.to_spec_review("leave-balance2", 3)
        self.eng.close()
        c = sqlite3.connect(self.dbp)
        c.row_factory = sqlite3.Row
        before = c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        states = [r[0] for r in c.execute("SELECT state FROM approvals")]
        self.assertIn("IN_REVIEW", states)
        n = self.notes()
        self.assertTrue(any("ready for review" in x["text"] for x in n["items"]))
        self.serve()
        for item in self.http.get("/api/v1/notifications").json["items"]:
            self.assertEqual(self.http.post(f"/api/v1/notifications/{item['id']}/read", {}).status, 200)
        self.assertEqual(self.cli_n("read", "--all")[0], 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM audit").fetchone()[0], before)
        self.assertEqual([r[0] for r in c.execute("SELECT state FROM approvals")], states)
        c.close()

    def test_AC_NOT_03c_a_notification_carries_no_decision_control(self):
        self.ev("approval.requested", {"gate": "specification", "version": 1})
        self.ev("run.state_changed", {"to": "NEEDS_HUMAN", "reason": "x"})
        self.serve()
        items = self.http.get("/api/v1/notifications").json["items"]
        self.assertEqual(len(items), 2)
        for n in items:
            self.assertEqual(set(n), {"id", "project", "run", "level", "text", "link", "at", "read_at"})
            self.assertTrue(n["link"].startswith("/") and not n["link"].startswith("/api"), n)

    def test_AC_SEC_06i_notification_text_is_scrubbed(self):
        rows = [("run.state_changed", {"to": "NEEDS_HUMAN", "reason": "password=hunter2hunter2"}, "hunter2hunter2"),
                ("task.finished", {"state": "FAILED", "role": "Bearer eyJhbGciOiJIUzI1NiJ9.e30.abc123def456", "error_code": "E_EXIT"},
                 "eyJhbGciOiJIUzI1NiJ9.e30.abc123def456"),
                ("run.status_changed", {"execution_status": "completed", "acceptance_status": "rejected",
                                        "reasons": ["the workspace path /home/dev/work/digital-hr is wrong"]}, "/home/dev/work/digital-hr")]
        self.serve()
        for event, payload, secret in rows:
            with self.subTest(event=event):
                self.ev(event, payload)
                api = self.http.get("/api/v1/notifications").text
                c, cli, err = self.cli_n("--json")
                c2, plain, err2 = self.cli_n()
                for where, text in (("api", api), ("cli json", cli), ("cli", plain)):
                    self.assertNotIn(secret, text, where)

    def test_AC_VIS_04a_the_cli_makes_no_network_connection(self):
        self.ev("approval.requested", {"gate": "specification", "version": 1})
        probe = ("import sys, runpy\nseen = []\n"
                 "def hook(event, args):\n    if event.startswith('socket.') and event not in ('socket.__new__', 'socket.close'):\n"
                 "        seen.append(event)\n"
                 "sys.addaudithook(hook)\n"
                 f"sys.argv = ['sentinel', 'notifications', '--json']\n"
                 "import io, contextlib\nbuf = io.StringIO()\n"
                 f"try:\n    with contextlib.redirect_stdout(buf):\n        runpy.run_path({SENTINEL!r}, run_name='__main__')\n"
                 "except SystemExit:\n    pass\n"
                 "print('SOCKET:' + ','.join(seen))\n")
        r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=self.env(**self.home_env()))
        self.assertIn("SOCKET:", r.stdout, r.stderr)
        self.assertEqual(r.stdout.split("SOCKET:")[1].strip(), "")

    def test_AC_VIS_04a_the_dashboard_source_registers_no_service_worker_or_push(self):
        root = Path(__file__).resolve().parents[1] / "dashboard" / "src"
        bad = [p.name for p in root.rglob("*.ts*") if any(w in p.read_text() for w in ("serviceWorker", "PushManager", "pushManager", "notify-send"))]
        self.assertEqual(bad, [])


class Server(NT):
    def test_AC_NOT_01c_events_written_by_the_cli_notify_like_server_events(self):
        self.use_config()
        self.serve()
        stream = self.stream()
        self.to_spec_review("leave-balance2", 3)
        events = []
        end = time.time() + 5
        while time.time() < end and not any(m.get("event") == "approval.requested" for m in events):
            events += stream.messages(1, timeout=1)
        got = [m for m in events if m.get("event") == "approval.requested"]
        self.assertTrue(got, events)
        items = self.http.get("/api/v1/notifications").json["items"]
        mine = [n for n in items if n["text"] == "Specification ready for review"]
        self.assertEqual(len(mine), 1, items)
        self.assertIsNone(mine[0]["read_at"])

    def test_AC_NOT_01h_marking_a_notification_read_in_the_dashboard(self):
        eid = self.ev("run.created", {"tier": 1})
        self.ev("run.created", {"tier": 2})
        self.serve()
        before = self.http.get("/api/v1/notifications").json
        self.assertEqual(before["unread"], 2)
        r = self.http.post(f"/api/v1/notifications/digital-hr:{eid}/read", {})
        self.assertEqual(r.status, 200, r.text)
        self.assertTrue(r.json["read_at"])
        self.assertEqual([(p, e) for p, e, _ in self.user_rows()], [("digital-hr", eid)])
        self.assertEqual(self.http.get("/api/v1/notifications").json["unread"], 1)
        c, out, err = self.cli_n("--unread", "--json")
        self.assertEqual(json.loads(out)["unread"], 1)
        r = self.http.get("/api/v1/notifications?unread=1")
        self.assertEqual(len(r.json["items"]), 1)

    def test_AC_NOT_01j_marking_read_needs_the_session_and_the_csrf_value(self):
        eid = self.ev("run.created", {"tier": 1})
        self.serve()
        r = self.http.req("POST", f"/api/v1/notifications/digital-hr:{eid}/read", body={}, csrf="")
        self.assertEqual((r.status, r.code), (403, "E_CSRF"))
        r = self.http.req("POST", f"/api/v1/notifications/digital-hr:{eid}/read", body={}, csrf="wrong")
        self.assertEqual((r.status, r.code), (403, "E_CSRF"))
        r = self.http.req("POST", f"/api/v1/notifications/digital-hr:{eid}/read", body={}, cookie=False)
        self.assertEqual((r.status, r.code), (401, "E_AUTH"))
        self.assertFalse(self.user_db().exists())

    def test_AC_NOT_01k_unknown_or_malformed_notification_ids(self):
        self.ev("run.created", {"tier": 1})
        self.serve()
        rows = [("digital-hr:999999", 404, "E_NOT_FOUND"), ("nope:1", 404, "E_NOT_FOUND"), ("digital-hr:abc", 400, "E_VALIDATION"),
                ("..%2F..%2Fuser.db:1", 400, "E_VALIDATION")]
        for nid, status, code in rows:
            with self.subTest(id=nid):
                r = self.http.post(f"/api/v1/notifications/{nid}/read", {})
                self.assertEqual((r.status, r.code), (status, code), r.text)
        self.assertFalse(self.user_db().exists())

    def test_AC_NOT_01n_the_dashboard_answers_500_with_a_fix_when_user_db_is_read_only(self):
        import notifications
        if os.geteuid() == 0:
            self.skipTest("root ignores file modes")
        a, b = self.ev("run.created", {"tier": 1}), self.ev("run.created", {"tier": 2})
        notifications.mark_read(self.sources(), notifications.user_db_path(), f"digital-hr:{a}")
        os.chmod(self.user_db(), 0o400)
        self.addCleanup(lambda: os.chmod(self.user_db(), 0o600))
        self.serve()
        r = self.http.post(f"/api/v1/notifications/digital-hr:{b}/read", {})
        self.assertEqual((r.status, r.code), (500, "E_INTERNAL"), r.text)
        fix = r.json["error"]["details"]["fix"]
        self.assertIn("user.db", fix)
        self.assertIn("0400", fix)
        self.assertEqual(self.http.get("/api/v1/notifications").status, 200)

    def test_AC_NOT_01d_the_routes_answer_empty_on_a_fresh_install(self):
        import shutil
        shutil.rmtree(self.cfgdir)
        self.serve(register=False)
        r = self.http.get("/api/v1/notifications")
        self.assertEqual((r.status, r.json), (200, {"items": [], "next": None, "unread": 0, "unavailable": []}))
        self.assertFalse(self.user_db().exists())

    def test_AC_NOT_01e_the_routes_page_and_filter(self):
        c = sqlite3.connect(self.dbp)
        c.executemany("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)",
                      [("r1", "run.created", "engine", "{}", f"2026-11-14T10:{i // 60:02d}:{i % 60:02d}.000000Z") for i in range(120)])
        c.commit()
        c.close()
        self.serve()
        p1 = self.http.get("/api/v1/notifications?limit=50").json
        self.assertEqual(len(p1["items"]), 50)
        p2 = self.http.get(f"/api/v1/notifications?limit=50&cursor={p1['next']}").json
        p3 = self.http.get(f"/api/v1/notifications?limit=50&cursor={p2['next']}").json
        self.assertEqual((len(p2["items"]), len(p3["items"]), p3["next"]), (50, 20, None))
        for q, code in (("limit=0", 400), ("cursor=zzz", 400), ("project=nope", 404)):
            self.assertEqual(self.http.get(f"/api/v1/notifications?{q}").status, code, q)

    def test_AC_NOT_01f_the_route_lists_an_unavailable_project(self):
        d, eng = self.extra_workspace("payroll")
        eng.close()
        self.ev("run.created", {"tier": 1})
        (d / ".sentinel" / "sentinel.db").write_bytes(b"garbage" * 200)
        self.serve()
        j = self.http.get("/api/v1/notifications").json
        self.assertEqual([n["project"] for n in j["items"]], ["digital-hr"])
        self.assertEqual([u["project"] for u in j["unavailable"]], ["payroll"])


if __name__ == "__main__":
    unittest.main()
