"""Phase F: mapping engine errors to HTTP answers (error_mapping.feature)."""
import inspect
import unittest
from unittest import mock

from sv_helpers import SV, SLUG, Http
import engine as engine_mod
import errors
from errors import SentinelError
from test_server_read import SECRET

STATUS = {"E_VALIDATION": 400, "E_ACTOR": 403, "E_POLICY": 403, "E_NOT_TTY": 403, "E_NOT_FOUND": 404, "E_TRANSITION": 409,
          "E_APPROVAL_STALE": 409, "E_LOCKED": 409, "E_INTEGRITY": 409, "E_PRECONDITION": 422, "E_APPROVAL_MISSING": 422,
          "E_SCOPE": 422, "E_RESULT_SCHEMA": 422, "E_PROVIDER": 422, "E_EXIT": 500, "E_TIMEOUT": 500, "E_AGENT": 500,
          "E_MIGRATION": 500}


class Mapping(SV):
    def setUp(self):
        super().setUp()
        (self.ws / ".env").write_text(f"DB_PASSWORD={SECRET}\n")
        self.executing(tier=3)
        self.serve()
        self.url = f"/api/v1/tasks/{SLUG}/control"

    def test_AC_API_03c_engine_error_codes_and_their_statuses(self):
        for code, status in STATUS.items():
            with self.subTest(code=code):
                with mock.patch.object(engine_mod.Engine, "cancel_run", side_effect=SentinelError(code, "m", {"k": "v"})):
                    r = self.http.post(self.url, {"action": "cancel"})
                self.assertEqual(r.status, status)
                self.assertEqual(r.json, {"error": {"code": code, "message": "m", "details": {"k": "v"}}})

    def test_AC_API_03d_every_code_in_errors_codes_has_a_status(self):
        from apiserver import status
        self.assertEqual(set(status.ENGINE_STATUS), set(errors.CODES))
        self.assertEqual(status.ENGINE_STATUS, STATUS)
        for code in ("E_AUTH", "E_CSRF", "E_HOST", "E_ORIGIN", "E_METHOD", "E_BODY_TOO_LARGE", "E_MEDIA_TYPE", "E_INTERNAL", "E_UNAVAILABLE"):
            self.assertIn(code, status.HTTP_ONLY_STATUS)
            self.assertNotIn(code, errors.CODES)

    def test_AC_API_03e_server_side_codes(self):
        P = self.srv.port
        anon = Http(P)
        rows = [("no session", lambda: anon.get("/api/v1/projects", cookie=False), 401, "E_AUTH"),
                ("no csrf", lambda: self.http.post(self.url, {"action": "cancel"}, csrf=False), 403, "E_CSRF"),
                ("host", lambda: self.http.get("/api/v1/projects", host=f"attacker.example:{P}"), 403, "E_HOST"),
                ("origin", lambda: self.http.get("/api/v1/projects", origin="http://attacker.example"), 403, "E_ORIGIN"),
                ("unknown", lambda: self.http.get("/api/v1/nothing"), 404, "E_NOT_FOUND"),
                ("method", lambda: self.http.req("DELETE", f"/api/v1/tasks/{SLUG}"), 405, "E_METHOD"),
                ("big", lambda: self.http.req("POST", self.url, raw=b"x" * (2 * 1024 * 1024)), 413, "E_BODY_TOO_LARGE"),
                ("media", lambda: self.http.req("POST", self.url, raw=b"x", ctype="text/plain"), 415, "E_MEDIA_TYPE")]
        for name, call, status, code in rows:
            with self.subTest(case=name):
                r = call()
                self.assertEqual((r.status, r.code), (status, code), r.text)

    def test_AC_API_03f_an_unexpected_exception_becomes_a_500_without_internals(self):
        lines = []
        self.srv.log_sink = lines.append
        with mock.patch.object(engine_mod.Engine, "load_run", side_effect=ZeroDivisionError("boom")):
            r = self.http.get(f"/api/v1/tasks/{SLUG}")
        self.assertEqual((r.status, r.code), (500, "E_INTERNAL"))
        self.assertEqual(r.json["error"]["message"], "internal error; see the server log")
        for leak in ("Traceback", "ZeroDivisionError", ".py", "boom"):
            self.assertNotIn(leak, r.text)
        self.assertEqual(sum("Traceback" in line for line in lines), 1)
        self.assertEqual(self.http.get(f"/api/v1/tasks/{SLUG}").status, 200)

    def test_AC_SEC_06g_error_messages_are_scrubbed(self):
        err = SentinelError("E_PRECONDITION", f"cannot reach postgres://u:{SECRET}@db")
        with mock.patch.object(engine_mod.Engine, "load_run", side_effect=err):
            r = self.http.get(f"/api/v1/tasks/{SLUG}")
        self.assertEqual(r.status, 422)
        self.assertNotIn(SECRET, r.text)

    def test_AC_API_03g_a_successful_mutating_call_returns_the_stored_state(self):
        r = self.http.post(self.url, {"action": "cancel"})
        self.assertEqual(r.status, 200, r.text)
        after = self.http.get(f"/api/v1/tasks/{SLUG}")
        self.assertEqual(r.json, after.json)
        self.assertEqual(r.json["state"], "CANCELLED")
        self.assertEqual(self.state(), "CANCELLED")

    def test_AC_API_03h_mutating_routes_call_the_cli_engine_functions(self):
        from apiserver import routes
        table = {r.name: r for r in routes.ROUTES if r.method == "POST"}
        self.assertEqual(set(table), {"approvals", "acceptance", "control", "create_run", "notification_read",
                                     "create_project", "register_project", "add_repository", "provider_test", "pause", "unpause",
                                     "note", "detect", "shared_test", "config_preview", "config_save", "knowledge_ingest",
                                     "knowledge_snapshot", "knowledge_backfill_estimate", "knowledge_backfill", "factory_pause",
                                     "factory_resume", "retry_now", "pick_folder"})
        self.assertEqual(table["retry_now"].calls, ("Engine.retry_limited_now",))
        for name in ("detect", "shared_test", "config_preview", "knowledge_backfill_estimate", "pick_folder"):
            self.assertEqual(table[name].calls, ())  # 2.0 setup: read or probe only, nothing changes
        self.assertEqual(table["config_save"].calls, ("manage.write_config",))  # the same history-keeping save as the YAML editor
        self.assertEqual((table["knowledge_ingest"].calls, table["knowledge_snapshot"].calls, table["knowledge_backfill"].calls),
                         (("kb_worker.enqueue_ingest",), ("kb_worker.enqueue_snapshot",), ("kb_worker.enqueue_ingest",)))
        for name in ("create_project", "register_project", "add_repository", "provider_test"):
            self.assertEqual(table[name].calls, ())  # dashboard management: files and projects.json, not engine transitions
        self.assertEqual(table["notification_read"].calls, ())  # Phase H: writes only ~/.config/sentinel/user.db
        self.assertEqual((table["factory_pause"].calls, table["factory_resume"].calls),
                         (("factory.set_paused",), ("factory.set_paused",)))   # a switch file in the config dir, audited per project
        self.assertEqual(table["approvals"].calls, ("Engine.decide",))
        self.assertEqual(table["acceptance"].calls, ("Engine.accept",))
        self.assertEqual(set(table["control"].calls),
                         {"Engine.cancel_run", "Engine.resume_run", "Engine.cancel_task_control", "Engine.retry_task",
                          "Engine.back_to_red", "Engine.already_implemented"})
        self.assertEqual(table["create_run"].calls, ("Engine.create_run",))
        self.assertEqual((table["pause"].calls, table["unpause"].calls, table["note"].calls),
                         (("Engine.pause_run",), ("Engine.unpause_run",), ("Engine.add_note",)))
        for r in table.values():
            src = inspect.getsource(r.handler)
            for banned in (".reg.insert", ".reg.update", ".reg.add_", "write_text", "write_bytes", "open(", "os.remove", "unlink"):
                self.assertNotIn(banned, src, (r.name, banned))
        calls = {}
        real_decide = engine_mod.Engine.decide

        def spy(self_, *a, **kw):
            calls["decide"] = (a, kw)
            return real_decide(self_, *a, **kw)
        h = self.spec_review("review-run", 3)
        with mock.patch.object(engine_mod.Engine, "decide", spy):
            r = self.http.post("/api/v1/tasks/review-run/approvals", self.body(h))
        self.assertEqual(r.status, 200, r.text)
        a, kw = calls["decide"]
        self.assertEqual(a[3], "human")
        self.assertEqual((kw["channel"], kw["approver"]), ("dashboard", "dev"))
        real_create = engine_mod.Engine.create_run
        seen = {}

        def spy_create(self_, slug, actor, *a, **k):
            seen.update(actor=actor, channel=self_.channel, name=self_.actor_name)
            return real_create(self_, slug, actor, *a, **k)
        with mock.patch.object(engine_mod.Engine, "create_run", spy_create):
            r = self.http.post("/api/v1/projects/digital-hr/tasks", {"slug": "via-api", "request": "x", "type": "feature"})
        self.assertEqual(r.status, 201, r.text)
        self.assertEqual(seen, {"actor": "human", "channel": "dashboard", "name": "dev"})


if __name__ == "__main__":
    unittest.main()
