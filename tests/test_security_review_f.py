"""Phase F security-review fixes: audit scrubbing, tier max, migrations, token handoff, symlinks, body limits,
stream bounds, log tail, deny rules, Host, sessions."""
import hashlib
import inspect
import json
import os
import queue
import shutil
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sv_helpers import SV, SLUG, Http, Stream
from test_server_read import ReadBase, SECRET
from test_registry import Base as RegBase, M1
from pc_helpers import PC


class AuditScrub(ReadBase):
    def test_audit_without_project_is_scrubbed_per_project(self):
        self.executing(tier=3)
        c = self.serve()
        r = c.post(f"/api/v1/tasks/{SLUG}/control",
                   {"action": "cancel", "comment": f"leak {SECRET} api_key=abcdef123456"})
        self.assertEqual(r.status, 200, r.text)
        for path in ("/api/v1/audit", "/api/v1/audit?project=digital-hr"):
            with self.subTest(path=path):
                text = c.get(path).text
                self.assertNotIn(SECRET, text)
                self.assertNotIn("abcdef123456", text)
                self.assertIn("[REDACTED", text)


class TierMax(PC):
    def test_triage_override_cannot_lower_dashboard_tier(self):
        self.eng.create_run("dash", "human", type="feature", request="x", requested_tier=4, origin="dashboard")
        self.eng.triage("dash", {}, "orchestrator", requested=1)
        self.assertEqual(self.eng.reg.get_run("dash")["tier"], 4)

    def test_triage_override_can_raise(self):
        self.eng.create_run("dash", "human", type="feature", request="x", requested_tier=2, origin="dashboard")
        self.eng.triage("dash", {}, "orchestrator", requested=4)
        self.assertEqual(self.eng.reg.get_run("dash")["tier"], 4)


class MigrationsLate(RegBase):
    M2 = (2, "two", "CREATE TABLE t2 (a TEXT);")
    M3 = (3, "three", "CREATE TABLE t3 (a TEXT);")
    M4 = (4, "four", "CREATE TABLE t4 (a TEXT);")
    M7 = (7, "seven", "CREATE TABLE t7 (a TEXT);")

    def tables(self):
        return {x[0] for x in self.raw().execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_lower_numbered_migration_added_later_is_applied(self):
        self.reg([M1, self.M2, self.M3, self.M7]).close()
        r = self.reg([M1, self.M2, self.M3, self.M4, self.M7])
        self.assertIn("t4", self.tables())
        self.assertEqual(r.schema_version(), 7)
        self.assertTrue(list(self.state_dir.glob("sentinel.db.bak-*")))
        r.close()
        self.reg([M1, self.M2, self.M3, self.M4, self.M7])  # idempotent

    def test_old_database_without_record_is_backfilled_once(self):
        self.reg([M1, self.M7]).close()
        c = self.raw()
        c.execute("DELETE FROM meta WHERE key='applied_migrations'")
        self.reg([M1, self.M3, self.M7]).close()  # <= 7 that exist are treated as applied
        self.assertNotIn("t3", self.tables())
        self.reg([M1, self.M3, self.M4, self.M7])  # the backfill was recorded: 4 is new, 3 is not
        self.assertIn("t4", self.tables())
        self.assertNotIn("t3", self.tables())

    def test_failing_late_migration_rolls_back(self):
        self.reg([M1, self.M7]).close()
        bad = (4, "bad", "CREATE TABLE half (a TEXT);\nINSERT INTO nope VALUES (1);")
        from errors import SentinelError
        with self.assertRaises(SentinelError) as cm:
            from registry import Registry
            Registry.open(self.state_dir, [M1, bad, self.M7])
        self.assertEqual(cm.exception.code, "E_MIGRATION")
        self.assertNotIn("half", self.tables())


class BrowserHandoff(SV):
    def test_opener_gets_a_file_url_without_the_token(self):
        from apiserver import lifecycle, userdir
        userdir.ensure_dir(self.cfgdir)
        token = "ab" * 32
        with mock.patch("webbrowser.open") as op:
            path = lifecycle.open_browser(self.cfgdir, 4321, token)
        url = op.call_args[0][0]
        self.assertNotIn(token, url)
        self.assertTrue(url.startswith("file://"))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(path.parent.resolve(), self.cfgdir.resolve())
        self.assertIn(f"http://127.0.0.1:4321/auth?t={token}", path.read_text())
        lifecycle.remove_redirect(self.cfgdir)
        self.assertFalse(path.exists())


class Symlinks(ReadBase):
    def setUp(self):
        super().setUp()
        self.executing(tier=3)
        self.rd = self.ws / ".sentinel" / "runs" / SLUG
        self.outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.outside, ignore_errors=True))
        (self.outside / "secret.txt").write_text("OUTSIDE-DATA")

    def test_log_that_is_a_symlink_is_refused(self):
        tid = self.make("docs", queue=False)
        self.set_task(tid, state="RUNNING")
        d = self.tdir(tid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "output.log").symlink_to(self.outside / "secret.txt")
        c = self.serve()
        r = c.get(f"/api/v1/tasks/{SLUG}/logs/{tid}")
        self.assertNotIn("OUTSIDE-DATA", r.text)

    def test_report_that_is_a_symlink_is_refused(self):
        (self.rd / "report.md").symlink_to(self.outside / "secret.txt")
        c = self.serve()
        r = c.get(f"/api/v1/tasks/{SLUG}/report?format=md")
        self.assertNotIn("OUTSIDE-DATA", r.text)

    def test_artifact_symlink_file_and_dir_entries_are_refused(self):
        art = self.artifacts("gherkin")[0]
        gdir = Path(art["path"]) if Path(art["path"]).is_absolute() else self.ws / ".sentinel" / art["path"]
        c = self.serve()
        ok = c.get(f"/api/v1/tasks/{SLUG}/artifacts/{art['id']}")
        self.assertEqual(ok.status, 200, ok.text)
        (gdir / "features" / "evil.feature").symlink_to(self.outside / "secret.txt")
        r = c.get(f"/api/v1/tasks/{SLUG}/artifacts/{art['id']}")
        self.assertNotIn("OUTSIDE-DATA", r.text)
        self.assertNotEqual(r.status, 200)

    def test_gherkin_dir_serves_only_hashed_files(self):
        art = self.artifacts("gherkin")[0]
        gdir = Path(art["path"]) if Path(art["path"]).is_absolute() else self.ws / ".sentinel" / art["path"]
        (gdir / "notes.txt").write_text("UNLISTED-FILE")
        c = self.serve()
        r = c.get(f"/api/v1/tasks/{SLUG}/artifacts/{art['id']}")
        self.assertEqual(r.status, 200, r.text)
        self.assertNotIn("UNLISTED-FILE", r.text)

    def test_single_file_artifact_symlink_is_refused(self):
        p = self.rd / "evidence" / "a.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.symlink_to(self.outside / "secret.txt")
        sha = hashlib.sha256(b"OUTSIDE-DATA").hexdigest()
        with self.eng.reg.transaction():
            self.eng.reg.insert_row("artifacts", {"id": "a-link", "run_id": self.run_row()["id"], "kind": "x", "version": 1,
                                                  "path": str(p.relative_to(self.ws / ".sentinel")), "sha256": sha})
        c = self.serve()
        r = c.get(f"/api/v1/tasks/{SLUG}/artifacts/a-link")
        self.assertNotIn("OUTSIDE-DATA", r.text)
        self.assertNotEqual(r.status, 200)

    def test_symlinked_run_subfolder_is_refused(self):
        tid = self.make("docs", queue=False)
        self.set_task(tid, state="RUNNING")
        d = self.tdir(tid)
        shutil.rmtree(d, ignore_errors=True)
        d.parent.mkdir(parents=True, exist_ok=True)
        (self.outside / "output.log").write_text("OUTSIDE-DATA\n")
        d.symlink_to(self.outside)
        c = self.serve()
        r = c.get(f"/api/v1/tasks/{SLUG}/logs/{tid}")
        self.assertNotIn("OUTSIDE-DATA", r.text)


class StaticDist(SV):
    def setUp(self):
        super().setUp()
        self.dist = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dist, ignore_errors=True))
        (self.dist / "index.html").write_text("<html>INDEX</html>")
        (self.dist / "assets").mkdir()
        (self.dist / "assets" / "app.js").write_text("console.log(1)")
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.out, ignore_errors=True))
        (self.out / "secret.js").write_text("OUTSIDE-DATA")
        (self.dist / "assets" / "link.js").symlink_to(self.out / "secret.js")
        (self.dist / "linkdir").symlink_to(self.out)
        self.executing(tier=3)
        self.serve(dist_dir=self.dist)

    def test_real_dist_serves_and_traversal_fails(self):
        self.assertIn("INDEX", self.http.get("/").text)
        self.assertIn("console.log", self.http.get("/assets/app.js").text)
        for path in ("/..%2Fsecret.js", "/assets/..%2F..%2Fsecret.js", "/%2e%2e/secret.js", "/assets/%2e%2e/%2e%2e/x",
                     "/assets//app.js", "/assets/%00app.js", "/assets\\app.js"):
            with self.subTest(path=path):
                r = self.http.get(path)
                self.assertNotIn("OUTSIDE-DATA", r.text)
                self.assertNotIn("console.log", r.text)

    def test_symlinks_in_dist_are_not_followed(self):
        for path in ("/assets/link.js", "/linkdir/secret.js"):
            with self.subTest(path=path):
                r = self.http.get(path)
                self.assertNotIn("OUTSIDE-DATA", r.text)


class AuthEqualLength(SV):
    def test_wrong_equal_length_token_fails_and_right_passes(self):
        self.executing(tier=3)
        self.serve()
        tok = self.srv.token
        wrong = ("0" if tok[0] != "0" else "1") + tok[1:]
        self.assertEqual(len(wrong), len(tok))
        self.assertEqual(Http(self.srv.port).req("GET", f"/auth?t={wrong}", cookie=False).status, 401)
        last = tok[:-1] + ("0" if tok[-1] != "0" else "1")
        self.assertEqual(Http(self.srv.port).req("GET", f"/auth?t={last}", cookie=False).status, 401)
        self.assertEqual(Http(self.srv.port).req("GET", f"/auth?t={tok}", cookie=False).status, 302)
        from apiserver import auth
        self.assertIn("hmac.compare_digest", inspect.getsource(auth))


class BodyParsing(SV):
    def setUp(self):
        super().setUp()
        self.executing(tier=3)
        self.serve()

    def post(self, raw):
        return self.http.post(f"/api/v1/tasks/{SLUG}/control", raw=raw)

    def test_deeply_nested_json_is_400(self):
        r = self.post(b"[" * 100000 + b"]" * 100000)
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))
        r = self.post(b'{"a":' * 5000 + b"1" + b"}" * 5000)
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))

    def test_nan_and_infinity_are_rejected(self):
        for lit in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(lit=lit):
                r = self.post(b'{"action":"cancel","x":' + lit + b"}")
                self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))


class StreamBounds(SV):
    def test_full_queue_collapses_to_resync(self):
        from apiserver.stream import Hub
        self.executing(tier=3)
        hub = Hub(self.serve() and self.srv.projects, 0.5, queue_max=5)
        sub = hub.subscribe(None, None)
        with hub.lock:
            for i in range(50):
                hub._broadcast("digital-hr", SLUG, f"id: {i}\n\n")
        self.assertLessEqual(sub.q.qsize(), 5)
        items = []
        while True:
            try:
                items.append(sub.q.get_nowait())
            except queue.Empty:
                break
        self.assertTrue(any("event: resync" in m for m in items if m), items)

    def test_stream_cap_per_session(self):
        self.executing(tier=3)
        c = self.serve()
        streams = [self.stream() for _ in range(32)]
        self.assertTrue(all(s.status == 200 for s in streams))
        extra = Stream(c, "/api/v1/events")
        self.addCleanup(extra.close)
        self.assertEqual(extra.status, 429)
        other = self.client()
        ok = Stream(other, "/api/v1/events")
        self.addCleanup(ok.close)
        self.assertEqual(ok.status, 200)


class LogTail(ReadBase):
    def setUp(self):
        super().setUp()
        self.executing(tier=3)

    def task(self, state):
        tid = self.make("docs", queue=False)
        self.set_task(tid, state=state)
        return tid, self.tdir(tid) / "output.log"

    def test_final_line_without_newline_shown_when_not_running(self):
        tid, log = self.task("DONE")
        log.write_text("one\ntwo")
        c = self.serve()
        r = c.get(f"/api/v1/tasks/{SLUG}/logs/{tid}")
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json["lines"], ["one", "two"])
        self.assertEqual(r.json["next_offset"], 7)
        r2 = c.get(f"/api/v1/tasks/{SLUG}/logs/{tid}?offset=7")
        self.assertEqual((r2.status, r2.json["lines"]), (200, []))

    def test_running_partial_line_is_held_back(self):
        tid, log = self.task("RUNNING")
        log.write_text("one\ntwo")
        c = self.serve()
        r = c.get(f"/api/v1/tasks/{SLUG}/logs/{tid}")
        self.assertEqual((r.json["lines"], r.json["next_offset"]), (["one"], 4))

    def test_line_longer_than_a_chunk_does_not_stick(self):
        from apiserver import views
        tid, log = self.task("RUNNING")
        log.write_text("x" * (views.LOG_CHUNK + 100) + "\nafter\n")
        c = self.serve()
        r = c.get(f"/api/v1/tasks/{SLUG}/logs/{tid}")
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(len(r.json["lines"]), 1)
        nxt = r.json["next_offset"]
        self.assertGreater(nxt, 0)
        r2 = c.get(f"/api/v1/tasks/{SLUG}/logs/{tid}?offset={nxt}")
        self.assertEqual(r2.json["lines"], ["after"])


class DenyRules(unittest.TestCase):
    def test_resolved_config_dir_is_denied(self):
        import sentinel as S
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d + "/xdg"}):
            ws = Path(d) / "ws"
            ws.mkdir()
            S.deny_human_commands(ws)
            text = (ws / ".claude" / "settings.json").read_text()
        self.assertIn(f"Read({d}/xdg/sentinel/**)", text)
        self.assertIn(f"Bash(cat {d}/xdg/sentinel/*)", text)


class HostAndSessions(SV):
    def test_two_host_headers_are_refused(self):
        self.executing(tier=3)
        self.serve()
        import socket
        s = socket.create_connection(("127.0.0.1", self.srv.port))
        s.sendall((f"GET /api/v1/projects HTTP/1.1\r\nHost: 127.0.0.1:{self.srv.port}\r\nHost: evil.example\r\n"
                   f"Cookie: sentinel_session={self.http.cookie}\r\n\r\n").encode())
        data = s.recv(65536)
        s.close()
        self.assertIn(b" 400 ", data.split(b"\r\n")[0] + b" ")
        self.assertNotIn(b"digital-hr", data)

    def test_sessions_are_capped_and_expire(self):
        from apiserver import auth
        s = auth.Sessions("t" * 64)
        first, _ = s.create()
        for _ in range(auth.MAX_SESSIONS + 5):
            s.create()
        self.assertIsNone(s.lookup(first))
        self.assertLessEqual(len(s._sessions), auth.MAX_SESSIONS)
        keep, csrf = s.create()
        self.assertEqual(s.lookup(keep), csrf)
        with mock.patch("apiserver.auth.time.monotonic", return_value=__import__("time").monotonic() + auth.IDLE_SECONDS + 5):
            self.assertIsNone(s.lookup(keep))


if __name__ == "__main__":
    unittest.main()
