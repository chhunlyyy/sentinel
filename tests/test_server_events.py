"""Phase F: server-sent event stream with resume (event_stream.feature)."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from sv_helpers import SV, SLUG, Http, SENTINEL, Stream, ids, wait_until
from test_server_read import SECRET

ENVELOPE = {"id", "type", "at", "project", "run", "task", "actor", "payload"}


def data(msg):
    return json.loads(msg["data"])


class Events(SV):
    def setUp(self):
        super().setUp()
        self.mk("leave-balance", "CREATED", 1)
        self.mk("leave-form", "CREATED", 1)

    def head(self, ws=None):
        c = sqlite3.connect((ws or self.ws) / ".sentinel" / "sentinel.db")
        try:
            return c.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
        finally:
            c.close()

    def settle(self, extra=()):
        """Wait until the event poller has seen everything committed so far."""
        def caught_up():
            pairs = [("digital-hr", self.head()), *extra]
            return all(self.srv.hub.cursors.get(pid) == head for pid, head in pairs)
        self.assertTrue(wait_until(caught_up, 5), self.srv.hub.cursors)

    def write(self, n, slug="leave-balance", eng=None):
        out = []
        for _ in range(n):
            out.append(self.add_event(slug, eng=eng))
        return out

    def test_AC_API_02a_a_stream_delivers_new_events_in_order(self):
        self.serve()
        s = self.stream("/api/v1/events?project=digital-hr")
        self.assertEqual(s.status, 200)
        self.assertTrue(s.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(s.headers["cache-control"], "no-store")
        t0 = time.time()
        written = self.write(3)
        msgs = s.messages(3)
        self.assertEqual(ids(msgs), [f"digital-hr:{i}" for i in written])
        self.assertLess(time.time() - t0, 1.5)
        for m, i in zip(msgs, written):
            self.assertEqual(m["event"], "task.progress")
            d = data(m)
            self.assertTrue(ENVELOPE <= set(d), d)
            self.assertEqual((d["id"], d["project"], d["run"], d["type"]), (i, "digital-hr", "leave-balance", "task.progress"))

    def test_AC_API_02b_a_dashboard_decision_shows_its_channel_in_the_stream(self):
        h = self.spec_review("review-run", 3)
        self.serve()
        s = self.stream("/api/v1/events?project=digital-hr")
        r = self.http.post("/api/v1/tasks/review-run/approvals", self.body(h))
        self.assertEqual(r.status, 200, r.text)
        msgs = s.messages(8, timeout=5)
        types = [m["event"] for m in msgs]
        self.assertIn("approval.decided", types)
        dec = data(msgs[types.index("approval.decided")])
        self.assertEqual(dec["actor"], {"kind": "human", "name": "dev", "channel": "dashboard"})
        later = [data(m) for m in msgs[types.index("approval.decided") + 1:] if m["event"] == "run.state_changed"]
        self.assertEqual(later[0]["payload"]["transition"], "R5")

    def test_AC_API_02c_filters(self):
        d, eng = self.extra_workspace("payroll")
        with eng.reg.transaction():
            pass
        eng.create_run("tax-form", "orchestrator", type="feature", baseline={})
        self.serve()
        rows = [("?project=digital-hr", {"leave-balance", "leave-form"}), ("?project=digital-hr&run=leave-balance", {"leave-balance"}),
                ("?project=payroll", {"tax-form"}), ("", {"leave-balance", "leave-form", "tax-form"})]
        for query, runs in rows:
            with self.subTest(query=query):
                s = self.stream("/api/v1/events" + query)
                self.assertEqual(s.status, 200)
                self.write(1, "leave-balance")
                self.write(1, "leave-form")
                self.add_event("tax-form", eng=eng)
                msgs = s.messages(len(runs) + 1, timeout=2)
                self.assertEqual({data(m)["run"] for m in msgs}, runs)
                s.close()

    def test_AC_API_02d_bad_filters(self):
        self.serve()
        for query, status, code in (("?project=nope", 404, "E_NOT_FOUND"), ("?project=digital-hr&run=no-such-run", 404, "E_NOT_FOUND"),
                                    ("?project=digital-hr&run=Bad..Slug", 400, "E_VALIDATION")):
            with self.subTest(query=query):
                r = self.http.get("/api/v1/events" + query)
                self.assertEqual((r.status, r.code), (status, code), r.text)

    def test_AC_API_02e_only_committed_events_are_streamed(self):
        self.serve()
        s = self.stream("/api/v1/events?project=digital-hr")
        run = self.eng.reg.get_run("leave-balance")
        with self.assertRaises(RuntimeError):
            with self.eng.reg.transaction():
                self.eng.reg.add_event(run["id"], "task.progress", "engine", {"rolled": "back"})
                raise RuntimeError("rollback")
        n = self.add_event("leave-balance", payload={"kept": True})
        msgs = s.messages(2, timeout=2)
        self.assertEqual(ids(msgs), [f"digital-hr:{n}"])
        self.assertEqual(data(msgs[0])["payload"], {"kept": True})

    def test_AC_API_02f_a_new_stream_starts_at_the_current_head(self):
        self.write(40)
        self.serve()
        self.settle()
        s = self.stream("/api/v1/events?project=digital-hr")
        self.assertEqual(s.messages(1, timeout=0.6), [])
        n = self.write(1)[0]
        self.assertEqual(ids(s.messages(1, timeout=3)), [f"digital-hr:{n}"])

    def test_AC_API_02g_heartbeats_keep_an_idle_stream_open(self):
        self.serve(heartbeat=0.2)
        s = self.stream("/api/v1/events?project=digital-hr")
        msgs = s.messages(10, timeout=1.1, comments=True)
        comments = [m for m in msgs if "comment" in m]
        self.assertGreaterEqual(len(comments), 4)
        self.assertEqual([m for m in msgs if "id" in m], [])

    # ---- resume
    def test_AC_DSH_05a_a_reconnecting_client_gets_every_missed_event(self):
        self.serve()
        s = self.stream("/api/v1/events?project=digital-hr")
        first = self.write(1)[0]
        self.assertEqual(ids(s.messages(1)), [f"digital-hr:{first}"])
        s.close()
        missed = self.write(5)
        self.settle()
        s2 = self.stream("/api/v1/events?project=digital-hr", last_event_id=f"digital-hr:{first}")
        msgs = s2.messages(5, timeout=5)
        self.assertEqual(ids(msgs), [f"digital-hr:{i}" for i in missed])
        live = self.write(1)[0]
        self.assertEqual(ids(s2.messages(1, timeout=3)), [f"digital-hr:{live}"])

    def test_AC_DSH_05b_a_last_event_id_that_cannot_be_resumed_asks_for_a_refresh(self):
        self.write(50)
        self.serve()
        rows = [("digital-hr:900", "unknown event id"), ("digital-hr:abc", "malformed id"), ("garbage", "malformed id"),
                ("unknown-project:12", "unknown project")]
        for lei, reason in rows:
            with self.subTest(lei=lei):
                s = self.stream("/api/v1/events?project=digital-hr", last_event_id=lei)
                self.assertEqual(s.status, 200)
                m = s.messages(1, timeout=3)[0]
                self.assertEqual(m["event"], "resync")
                d = data(m)
                self.assertEqual((d["project"], d["reason"]), ("digital-hr", reason))
                n = self.write(1)[0]
                self.assertEqual(ids(s.messages(1, timeout=3)), [f"digital-hr:{n}"])
                s.close()

    def test_AC_DSH_05c_resume_of_a_stream_without_a_project_filter(self):
        d, eng = self.extra_workspace("payroll")
        eng.create_run("tax-form", "orchestrator", type="feature", baseline={})
        self.serve()
        s = self.stream("/api/v1/events")
        first = self.write(1)[0]
        self.assertEqual(ids(s.messages(1)), [f"digital-hr:{first}"])
        s.close()
        away = self.write(2)
        self.write(2, "tax-form", eng=eng)
        self.settle([("payroll", self.head(d))])
        s2 = self.stream("/api/v1/events", last_event_id=f"digital-hr:{first}")
        msgs = s2.messages(4, timeout=5)
        self.assertEqual(ids(msgs), [f"digital-hr:{i}" for i in away])
        resync = [data(m) for m in msgs if m.get("event") == "resync"]
        self.assertEqual([r["project"] for r in resync], ["payroll"])
        a = self.write(1)[0]
        b = self.write(1, "tax-form", eng=eng)[0]
        got = ids(s2.messages(2, timeout=5))
        self.assertEqual(sorted(got), sorted([f"digital-hr:{a}", f"payroll:{b}"]))

    def test_AC_DSH_05d_the_database_is_replaced_by_an_older_backup(self):
        self.write(5)
        backup = self.ws / "backup.db"
        src = sqlite3.connect(self.ws / ".sentinel" / "sentinel.db")
        dst = sqlite3.connect(backup)
        src.backup(dst)
        dst.close()
        src.close()
        self.write(10)
        self.serve()
        s = self.stream("/api/v1/events?project=digital-hr")
        self.eng.close()
        db = self.ws / ".sentinel" / "sentinel.db"
        for suffix in ("-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
        shutil.copy(backup, db)
        msgs = s.messages(1, timeout=3)
        self.assertEqual(msgs[0]["event"], "resync")
        self.assertEqual(data(msgs[0])["project"], "digital-hr")
        from engine import Engine
        eng = Engine(self.ws / ".sentinel", self.ws, self.config, release_lock=lambda s: None)
        self.addCleanup(eng.close)
        run = eng.reg.get_run("leave-balance")
        with eng.reg.transaction():
            n = eng.reg.add_event(run["id"], "task.progress", "engine", {})
        self.assertEqual(ids(s.messages(1, timeout=3)), [f"digital-hr:{n}"])

    # ---- writers and scrubbing
    def test_AC_API_02h_events_written_by_other_processes_reach_the_stream(self):
        self.serve()
        s = self.stream("/api/v1/events")
        before = self.head()
        code, out, err = self.cli("triage", "leave-balance", "--factors", "files=1")
        self.assertEqual(code, 0, out + err)
        code, out, err = self.cli("next", "leave-balance")
        tid = self.eng.reg.rows("tasks")[0]["id"] if self.eng.reg.rows("tasks") else None
        self.assertTrue(tid, "next planned a specifier task")
        code, out, err = self.cli("task", "run", tid)
        self.assertEqual(code, 0, out + err)
        self.write_spec(spec_text_for("leave-balance"), slug="leave-balance")
        self.write_result(tid, slug="leave-balance")
        code, out, err = self.cli("task", "complete", tid)
        self.assertEqual(code, 0, out + err)
        total = self.head() - before
        msgs = s.messages(total, timeout=5)
        self.assertEqual(len(msgs), total)
        types = {m["event"] for m in msgs}
        self.assertTrue({"run.triaged", "task.started", "task.finished"} <= types, types)

    def test_AC_SEC_06f_event_payloads_are_scrubbed_when_served(self):
        (self.ws / ".env").write_text(f"DB_PASSWORD={SECRET}\n")
        self.to_spec_review("review-run", 3)
        self.serve()
        s = self.stream("/api/v1/events?project=digital-hr")
        code, out = self.run_tty(["approve", "review-run", "spec", "--request-changes", "-m",
                             f"use password {SECRET}"], typed=[self.eng.pending_approval("review-run", "spec")["sha256"][:8]])
        self.assertEqual(code, 0, out)
        msgs = s.messages(6, timeout=3)
        dec = [m for m in msgs if m["event"] == "approval.decided"]
        self.assertEqual(len(dec), 1)
        self.assertNotIn(SECRET, dec[0]["data"])
        stored = self.events_rows(type="approval.decided")[-1]
        self.assertIn(SECRET, stored["payload"])
        self.assertEqual(json.loads(stored["payload"])["comment"], f"use password {SECRET}")
        self.assertEqual(stored["channel"], "tty")

    def test_AC_API_02i_one_unreadable_workspace_does_not_stop_the_others(self):
        if os.geteuid() == 0:
            self.skipTest("root can read a mode 000 file")
        d, eng = self.extra_workspace("payroll")
        eng.create_run("tax-form", "orchestrator", type="feature", baseline={})
        self.serve()
        s = self.stream("/api/v1/events")
        db = d / ".sentinel" / "sentinel.db"
        for p in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
            if p.exists():
                os.chmod(p, 0)
        msgs = s.messages(1, timeout=4)
        self.assertEqual((msgs[0]["event"], data(msgs[0])["project"], data(msgs[0])["reason"]),
                         ("resync", "payroll", "project unavailable"))
        n = self.write(1)[0]
        self.assertEqual(ids(s.messages(1, timeout=3)), [f"digital-hr:{n}"])
        for p in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
            if p.exists():
                os.chmod(p, 0o644)
        msgs = s.messages(1, timeout=4)
        self.assertEqual((msgs[0]["event"], data(msgs[0])["project"]), ("resync", "payroll"))
        m = self.add_event("tax-form", eng=eng)
        self.assertEqual(ids(s.messages(1, timeout=3)), [f"payroll:{m}"])

    def test_AC_API_02j_a_project_added_while_streaming_is_included(self):
        self.serve()
        s = self.stream("/api/v1/events")
        d, eng = self.extra_workspace("hr-docs", register=True)
        eng.create_run("docs-run", "orchestrator", type="docs", baseline={})
        msgs = s.messages(1, timeout=3)
        self.assertEqual(ids(msgs), ["hr-docs:1"])

    # ---- many and slow clients
    def test_AC_API_02k_several_clients_receive_the_same_events(self):
        self.serve()
        streams = [self.stream("/api/v1/events?project=digital-hr") for _ in range(20)]
        script = ("import sys; sys.path.insert(0, %r)\nfrom registry import Registry\nreg = Registry.open(%r)\n"
                  "run = reg.get_run('leave-balance')\nfor i in range(100):\n    with reg.transaction():\n"
                  "        reg.add_event(run['id'], 'task.progress', 'engine', {'i': i})\n" % (str(Path(SENTINEL).parent), str(self.ws / ".sentinel")))
        before = self.head()
        subprocess.run([sys.executable, "-c", script], check=True)
        t0 = time.time()
        want = [f"digital-hr:{i}" for i in range(before + 1, before + 101)]
        for s in streams:
            self.assertEqual(ids(s.messages(100, timeout=5)), want)
        self.assertLess(time.time() - t0, 3)

    def test_AC_API_02l_a_client_that_stops_reading_does_not_block_the_others(self):
        self.serve(slow_timeout=1.0)
        before = self.head()
        a = self.stream("/api/v1/events?project=digital-hr", rcvbuf=1024)
        b = self.stream("/api/v1/events?project=digital-hr")
        run = self.eng.reg.get_run("leave-balance")
        conn = sqlite3.connect(self.ws / ".sentinel" / "sentinel.db")
        pad = "p" * 600
        conn.executemany("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)",
                         [(run["id"], "task.progress", "engine", json.dumps({"i": i, "pad": pad}), "2026-01-01T00:00:00Z")
                          for i in range(5000)])
        conn.commit()
        conn.close()
        t0 = time.time()
        got = ids(b.messages(5000, timeout=20))
        self.assertEqual(got, [f"digital-hr:{i}" for i in range(before + 1, before + 5001)])
        self.assertTrue(wait_until(lambda: self.srv.stream_count() == 1, 8), self.srv.stream_count())
        c = self.stream("/api/v1/events?project=digital-hr", last_event_id=f"digital-hr:{before}")
        self.assertEqual(len(ids(c.messages(5000, timeout=20))), 5000)

    def test_AC_API_02m_a_closed_client_frees_its_thread(self):
        lines = []
        self.serve()
        self.srv.log_sink = lines.append
        streams = [self.stream("/api/v1/events") for _ in range(10)]
        self.assertTrue(wait_until(lambda: self.srv.stream_count() == 10, 3))
        for s in streams:
            s.close()
        self.assertTrue(wait_until(lambda: self.srv.stream_count() == 0, 3), self.srv.stream_count())
        self.assertFalse([l for l in lines if "Traceback" in l])

    def test_AC_API_02n_the_stream_ends_when_the_session_is_no_longer_valid(self):
        self.serve()
        s = self.stream("/api/v1/events?project=digital-hr")
        old = (self.http.cookie, self.http.csrf)
        self.srv.stop()
        self.assertTrue(s.closed(5))
        from apiserver.server import ApiServer
        srv2 = ApiServer(self.cfgdir, port=0, user="dev", git_name="Dev User", poll_interval=self.POLL, dispatch=False)
        srv2.start()
        self.addCleanup(srv2.stop)
        c = Http(srv2.port)
        c.cookie = old[0]
        r = c.req("GET", "/api/v1/events", headers={"Last-Event-ID": "digital-hr:1"})
        self.assertEqual((r.status, r.code), (401, "E_AUTH"))


def spec_text_for(slug):
    from pb_helpers import spec_text
    return spec_text(slug, tier=1)


if __name__ == "__main__":
    unittest.main()
