"""Phase F: Host and Origin checks, session token, CSRF and the allow-list (http_security.feature)."""
import json
import os
import unittest
from unittest import mock

from sv_helpers import SV, SLUG, Http


class Sec(SV):
    def setUp(self):
        super().setUp()
        self.executing(tier=3)
        self.serve()
        self.P = self.srv.port
        self.T = self.srv.token

    def control(self, body=None, **kw):
        return self.http.post(f"/api/v1/tasks/{SLUG}/control", body if body is not None else {"action": "cancel"}, **kw)

    # ---- Host and Origin
    def test_AC_SEC_01l_host_header_is_checked_on_every_request(self):
        P = self.P
        rows = [(f"127.0.0.1:{P}", 200), (f"localhost:{P}", 200), (f"LOCALHOST:{P}", 200), ("127.0.0.1", 403),
                ("127.0.0.1:8", 403), (f"attacker.example:{P}", 403), (f"[::1]:{P}", 403),
                (f"127.0.0.1.nip.io:{P}", 403), (None, 403)]
        for host, status in rows:
            with self.subTest(host=host):
                r = self.http.get("/api/v1/projects", host=host)
                self.assertEqual(r.status, status, r.text)
                if status == 403:
                    self.assertEqual(r.code, "E_HOST")
                    self.assertNotIn("digital-hr", r.text)

    def test_AC_SEC_01m_origin_header_when_present_must_match(self):
        P = self.P
        rows = [(None, 200), (f"http://127.0.0.1:{P}", 200), (f"http://localhost:{P}", 200),
                ("http://attacker.example", 403), ("null", 403), (f"https://127.0.0.1:{P}", 403),
                ("http://127.0.0.1:8", 403)]
        for origin, status in rows:
            with self.subTest(origin=origin):
                r = self.control({"action": "resume", "comment": "x"} if status == 200 else {"action": "cancel"}, origin=origin)
                if status == 200:
                    self.assertIn(r.status, (200, 409), r.text)
                    self.assertNotEqual(r.code, "E_ORIGIN")
                else:
                    self.assertEqual((r.status, r.code), (403, "E_ORIGIN"))

    def test_AC_SEC_01n_host_checks_guard_auth_and_event_routes(self):
        bad = f"attacker.example:{self.P}"
        for path in (f"/auth?t={self.T}", "/api/v1/events", "/"):
            with self.subTest(path=path):
                r = Http(self.P).req("GET", path, host=bad, cookie=f"sentinel_session={self.http.cookie}")
                self.assertEqual((r.status, r.code), (403, "E_HOST"))
                self.assertNotIn("set-cookie", r.headers)
                self.assertNotIn("text/event-stream", r.headers.get("content-type", ""))

    def test_AC_SEC_01o_a_rebinding_page_cannot_read_the_api(self):
        r = self.http.get("/api/v1/projects", host=f"attacker.example:{self.P}")
        self.assertEqual((r.status, r.code), (403, "E_HOST"))
        auth = Http(self.P).get(f"/auth?t={self.T}", cookie=False)
        self.assertNotIn("domain", auth.headers["set-cookie"].lower())

    # ---- token exchange
    def test_AC_SEC_01p_exchanging_the_token_sets_a_strict_cookie(self):
        r = Http(self.P).get(f"/auth?t={self.T}", cookie=False)
        self.assertEqual((r.status, r.headers["location"]), (302, "/"))
        sc = r.headers["set-cookie"]
        self.assertTrue(sc.startswith("sentinel_session="))
        low = sc.lower()
        for attr in ("httponly", "samesite=strict", "path=/"):
            self.assertIn(attr, low)
        self.assertNotIn("domain", low)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(r.headers["referrer-policy"], "no-referrer")
        self.assertNotIn(self.T, r.headers["location"])

    def test_AC_SEC_01q_a_wrong_token_gives_no_session(self):
        T = self.T
        flip = ("1" if T[-1] != "1" else "2")
        rows = ["?t=", "", "?t=" + "0" * 64, "?t=" + T[:-1] + flip, "?t=" + T + "x", "?token=" + T]
        for q in rows:
            with self.subTest(query=q[:12]):
                r = Http(self.P).get("/auth" + q, cookie=False)
                self.assertEqual((r.status, r.code), (401, "E_AUTH"))
                self.assertNotIn("set-cookie", r.headers)

    def test_AC_SEC_01r_comparisons_use_constant_time_compare(self):
        import inspect
        from apiserver import auth
        src = inspect.getsource(auth)
        self.assertIn("hmac.compare_digest", src)

    def test_AC_SEC_01s_every_api_route_needs_the_session_cookie(self):
        T, P = self.T, self.P
        rows = [("GET", "/api/v1/projects", {}), ("GET", "/api/v1/projects", {"cookie": "sentinel_session=wrong"}),
                ("GET", "/api/v1/projects", {"headers": {"Authorization": f"Bearer {T}"}}),
                ("GET", f"/api/v1/projects?t={T}", {}), ("GET", "/api/v1/events", {}), ("GET", "/api/v1/session", {}),
                ("POST", f"/api/v1/tasks/{SLUG}/control", {"csrf": self.http.csrf, "body": {"action": "cancel"}})]
        for method, path, kw in rows:
            with self.subTest(method=method, path=path.split("?")[0], kw=sorted(kw)):
                kw = dict(kw)
                kw.setdefault("cookie", False)
                r = Http(P).req(method, path, **kw)
                self.assertEqual((r.status, r.code), (401, "E_AUTH"))
                self.assertNotIn("items", r.text)
                self.assertNotIn(SLUG, r.text)

    def test_AC_SEC_01t_401_before_revealing_whether_a_route_exists(self):
        r = Http(self.P).get("/api/v1/no-such-route", cookie=False)
        self.assertEqual((r.status, r.code), (401, "E_AUTH"))

    # ---- CSRF
    def test_AC_SEC_01u_a_post_without_the_right_csrf_value_is_refused(self):
        before = (self.state(), len(self.events_rows()), len(self.audit_rows()))
        rows = [("no header", None), ("empty", ""), ("wrong", "wrong"), ("token", self.T)]
        for name, value in rows:
            with self.subTest(csrf=name):
                if value in (None, ""):
                    r = self.http.req("POST", f"/api/v1/tasks/{SLUG}/control", {"action": "cancel"}, csrf=False,
                                      headers={"X-Sentinel-CSRF": ""} if value == "" else None)
                else:
                    r = self.http.req("POST", f"/api/v1/tasks/{SLUG}/control", {"action": "cancel"}, csrf=value)
                self.assertEqual((r.status, r.code), (403, "E_CSRF"), r.text)
        with self.subTest(csrf="form field"):
            r = self.http.req("POST", f"/api/v1/tasks/{SLUG}/control", raw=f"csrf={self.http.csrf}&action=cancel".encode(),
                              ctype="application/x-www-form-urlencoded", csrf=False)
            self.assertEqual((r.status, r.code), (403, "E_CSRF"))
        self.assertEqual(before, (self.state(), len(self.events_rows()), len(self.audit_rows())))

    def test_AC_SEC_01v_read_calls_do_not_need_the_csrf_header(self):
        self.assertEqual(self.http.get(f"/api/v1/tasks/{SLUG}", csrf=False).status, 200)

    def test_AC_SEC_01w_the_csrf_value_is_only_served_to_an_authenticated_client(self):
        r = self.http.get("/api/v1/session")
        self.assertEqual(r.status, 200)
        self.assertRegex(r.json["csrf"], r"^[0-9a-f]{64}$")
        self.assertNotEqual(r.json["csrf"], self.T)
        self.assertNotIn(self.T, r.text)

    # ---- allow-list
    def test_AC_API_01h_unknown_operations_are_refused(self):
        rows = [("GET", "/api/v1/shell", 404, "E_NOT_FOUND", None), ("POST", "/api/v1/exec", 404, "E_NOT_FOUND", {"cmd": "ls"}),
                ("GET", "/api/v2/projects", 404, "E_NOT_FOUND", None),
                ("GET", "/api/v1/fs/dirs?path=/", 404, "E_NOT_FOUND", None),
                ("POST", "/api/v1/projects", 404, "E_NOT_FOUND", {"name": "x"}),
                ("PUT", "/api/v1/projects/digital-hr/configuration", 404, "E_NOT_FOUND", {}),
                ("POST", f"/api/v1/tasks/{SLUG}/publish", 404, "E_NOT_FOUND", {}),
                ("DELETE", f"/api/v1/tasks/{SLUG}", 405, "E_METHOD", None),
                ("PUT", f"/api/v1/tasks/{SLUG}/approvals", 405, "E_METHOD", {}),
                ("POST", "/api/v1/projects/digital-hr/tasks/x/../../config", 404, "E_NOT_FOUND", {})]
        for method, path, status, code, body in rows:
            with self.subTest(method=method, path=path):
                before = len(self.events_rows())
                r = self.http.req(method, path, body=body)
                self.assertEqual((r.status, r.code), (status, code), r.text)
                self.assertEqual(before, len(self.events_rows()))

    def test_AC_API_01i_a_405_answer_lists_the_allowed_methods(self):
        r = self.http.req("DELETE", f"/api/v1/tasks/{SLUG}")
        self.assertEqual((r.status, r.headers["allow"]), (405, "GET"))

    def test_AC_API_01j_bodies_with_extra_fields_are_refused(self):
        for field, value in (("command", "rm -rf /"), ("shell", "true"), ("path", "/etc/passwd"), ("env", {"A": "1"})):
            with self.subTest(field=field):
                with mock.patch("engine.Engine.cancel_run", side_effect=AssertionError("engine called"), create=True):
                    r = self.control({"action": "cancel", field: value})
                self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)
                self.assertIn(field, r.text)
                self.assertEqual(self.state(), "EXECUTING")

    def test_AC_API_01k_other_methods_and_cors_preflight_are_refused(self):
        for method in ("OPTIONS", "TRACE", "CONNECT"):
            with self.subTest(method=method):
                r = self.http.req(method, "/api/v1/projects", origin="http://attacker.example")
                self.assertIn(r.status, (403, 405))
                for h in ("access-control-allow-origin", "access-control-allow-credentials", "access-control-allow-methods"):
                    self.assertNotIn(h, r.headers)

    # ---- bodies
    def test_AC_API_01l_body_size_limit(self):
        base = json.dumps({"action": "cancel", "comment": ""})
        for size, status in ((1048576, 400), (1048577, 413)):
            with self.subTest(size=size):
                pad = size - len(base) + 2
                raw = ('{"action": "cancel", "pad": "' + "x" * (size - len('{"action": "cancel", "pad": ""}'))  + '"}').encode()
                self.assertEqual(len(raw), size)
                r = self.http.req("POST", f"/api/v1/tasks/{SLUG}/control", raw=raw)
                self.assertEqual(r.status, status, r.text[:200])
        self.assertEqual(self.state(), "EXECUTING")

    def test_AC_API_01m_only_json_bodies_are_read(self):
        rows = [("text/plain", b'{"action": "cancel"}', 415, "E_MEDIA_TYPE"),
                ("application/x-www-form-urlencoded", b"action=cancel", 415, "E_MEDIA_TYPE"),
                ("application/json", b'{"action": "cancel"', 400, "E_VALIDATION"),
                ("application/json", b'["cancel"]', 400, "E_VALIDATION"),
                ("application/json", b"", 400, "E_VALIDATION"),
                ("application/json; charset=utf-8", b'{"action": "frob"}', 400, "E_VALIDATION")]
        for ctype, raw, status, code in rows:
            with self.subTest(ctype=ctype, raw=raw[:12]):
                r = self.http.req("POST", f"/api/v1/tasks/{SLUG}/control", raw=raw, ctype=ctype)
                self.assertEqual((r.status, r.code), (status, code), r.text)

    def test_AC_API_01n_a_body_without_content_length_is_refused(self):
        r = self.http.req("POST", f"/api/v1/tasks/{SLUG}/control", raw=b'{"action": "cancel"}', content_length=False,
                          headers={"Transfer-Encoding": "chunked"})
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))
        self.assertIn("Content-Length required", r.json["error"]["message"])

    # ---- headers and token exposure
    def test_AC_SEC_01x_security_headers_on_every_response(self):
        csp = "default-src 'self'; frame-ancestors 'none'"
        for name, r in (("page", self.http.get("/")), ("api", self.http.get("/api/v1/projects")),
                        ("anon", Http(self.P).get("/api/v1/projects", cookie=False))):
            with self.subTest(r=name):
                self.assertEqual(r.headers["content-security-policy"], csp)
                self.assertEqual(r.headers["x-content-type-options"], "nosniff")
                self.assertNotIn("access-control-allow-origin", r.headers)
                if name != "page":
                    self.assertEqual(r.headers["cache-control"], "no-store")
                    self.assertEqual(r.headers["content-type"], "application/json; charset=utf-8")

    def test_AC_SEC_02h_no_answer_holds_the_token(self):
        paths = ["/", "/api/v1/session", "/api/v1/installation", "/api/v1/runtime", "/api/v1/projects",
                 "/api/v1/projects/digital-hr", "/api/v1/projects/nope", "/api/v1/projects/digital-hr/tasks",
                 f"/api/v1/tasks/{SLUG}", f"/api/v1/tasks/{SLUG}/next", f"/api/v1/tasks/{SLUG}/workflow",
                 f"/api/v1/tasks/{SLUG}/tdd", f"/api/v1/tasks/{SLUG}/verification", f"/api/v1/tasks/{SLUG}/trace",
                 f"/api/v1/tasks/{SLUG}/specification", f"/api/v1/tasks/{SLUG}/gherkin", f"/api/v1/tasks/{SLUG}/report",
                 "/api/v1/tasks/unknown", f"/api/v1/tasks/{SLUG}/artifacts/zzz", f"/api/v1/tasks/{SLUG}/logs/t-1",
                 "/api/v1/approvals", "/api/v1/audit"]
        for p in paths:
            with self.subTest(path=p):
                r = self.http.get(p)
                blob = r.text + json.dumps(r.headers)
                self.assertNotIn(self.T, blob)
                self.assertNotIn(self.http.csrf if p != "/api/v1/session" else "\0", blob)

    def test_AC_SEC_02i_path_traversal_cannot_reach_other_files(self):
        secret = self.cfgdir / "server.json"
        secret.write_text(json.dumps({"token": self.T}))
        for path in (f"/api/v1/tasks/{SLUG}/artifacts/..%2F..%2F..%2F.config%2Fsentinel%2Fserver.json",
                     "/api/v1/tasks/..%2F..%2Fetc/report", f"/api/v1/tasks/{SLUG}/logs/..%2Fsentinel.db",
                     "/..%2F..%2F.config/sentinel/server.json", "/static/../../.config/sentinel/server.json"):
            with self.subTest(path=path):
                r = self.http.get(path)
                self.assertIn(r.status, (400, 404))
                self.assertNotIn(self.T, r.text)

    def test_AC_SEC_02j_the_server_log_holds_no_token_or_cookie_value(self):
        lines = []
        self.srv.log_sink = lines.append
        c = self.client()
        for _ in range(20):
            c.get("/api/v1/projects")
        c.post(f"/api/v1/tasks/{SLUG}/control", {"action": "resume", "comment": "x"})
        Http(self.P).get(f"/auth?t={self.T}", cookie=False)
        blob = "\n".join(lines)
        self.assertIn("/api/v1/projects", blob)
        for secret in (self.T, c.cookie, c.csrf):
            self.assertNotIn(secret, blob)
        self.assertIn("t=REDACTED", blob)


if __name__ == "__main__":
    unittest.main()
