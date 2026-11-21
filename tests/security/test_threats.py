"""Phase H part B: end-to-end checks of the threat model (security_suite.feature).

Browser-only checks (a real browser resolving a rebinding name, a form post from a second page, window.history)
need Playwright, which is not available offline; the same server behaviour is checked here with raw HTTP requests
that carry the headers a browser would send. The dashboard XSS screens are covered by dashboard/e2e/accessibility_xss.spec.ts
(run by the dashboard npm scripts) plus the source scan below.
"""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sv_helpers import SV, SLUG, Http, SENTINEL  # noqa: E402
from pc_helpers import wait_until  # noqa: E402
from pb_helpers import PtyProc, CLI, CLI_ENV  # noqa: E402
from adapters import child_env  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CANARIES = {"CANARY_DB_PASSWORD": "cn-7f3a9e1b2c", "API_TOKEN": "cn-tok-55aa66bb77cc"}
AWS = "cn-aws-0123456789abcdef"


class Requests(SV):
    def setUp(self):
        super().setUp()
        self.executing(tier=3)
        self.serve()
        self.P, self.T = self.srv.port, self.srv.token

    def counts(self):
        return (self.state(), len(self.events_rows()), len(self.audit_rows()))

    def test_AC_TST_05c_dns_rebinding_gets_nothing(self):
        for path in ("/api/v1/projects", "/api/v1/session", f"/api/v1/tasks/{SLUG}/report"):
            with self.subTest(path=path):
                r = self.http.get(path, host=f"rebind.example:{self.P}", origin=f"http://rebind.example:{self.P}")
                self.assertEqual((r.status, r.code), (403, "E_HOST"))
                self.assertNotIn("digital-hr", r.text)

    def test_AC_TST_05d_cross_site_requests_change_nothing(self):
        before = self.counts()
        foreign = "http://127.0.0.1:9"  # a second local origin: another port
        rows = [("form post text/plain", f"/api/v1/tasks/{SLUG}/approvals", dict(raw=b"gate=specification", ctype="text/plain")),
                ("no-cors fetch", f"/api/v1/tasks/{SLUG}/control", dict(body={"action": "cancel"}, ctype="text/plain")),
                ("credentialed json", f"/api/v1/tasks/{SLUG}/control", dict(body={"action": "cancel"}))]
        for name, path, kw in rows:
            with self.subTest(name):
                r = self.http.req("POST", path, origin=foreign, **kw)
                self.assertEqual((r.status, r.code), (403, "E_ORIGIN"), r.text)
        with self.subTest("preflight"):
            r = self.http.req("OPTIONS", f"/api/v1/tasks/{SLUG}/control", origin=foreign,
                              headers={"Access-Control-Request-Method": "POST"})
            self.assertGreaterEqual(r.status, 400)
            self.assertNotIn("access-control-allow-origin", r.headers)
        with self.subTest("image GET without the cookie"):
            self.assertEqual(self.http.get("/api/v1/projects", cookie=False).status, 401)
            sc = Http(self.P).get(f"/auth?t={self.T}", cookie=False).headers["set-cookie"].lower()
            self.assertIn("samesite=strict", sc)
        self.assertEqual(before, self.counts())

    def test_AC_TST_05e_path_traversal_in_every_path_like_argument(self):
        (self.cfgdir / "server.json").write_text(json.dumps({"token": self.T}))
        for path, code in ((f"/api/v1/tasks/{SLUG}/artifacts/..%2F..%2F..%2F..%2F.config%2Fsentinel%2Fserver.json", "E_NOT_FOUND"),
                           (f"/api/v1/tasks/{SLUG}/logs/..%2F..%2Fsentinel.db", "E_NOT_FOUND"),
                           ("/assets/%2e%2e/%2e%2e/VERSION", None)):
            with self.subTest(path=path):
                r = self.http.get(path)
                self.assertEqual(r.status, 404, r.text)  # security_suite.feature AC-TST-05e: 404 for each of the three
                if code:
                    self.assertEqual(r.code, code)
                self.assertNotIn(self.T, r.text)
        with self.subTest("notification id"):
            r = self.http.post("/api/v1/notifications/..%2F..%2Fuser.db:1/read", {})
            self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)  # security_suite.feature AC-TST-05e
            self.assertFalse((self.cfgdir / "user.db").exists() and (self.cfgdir / "user.db").stat().st_size == 0)
        with self.subTest("task id"):
            code, out, err = self.cli("task", "complete", "t-1/../../../x")
            self.assertEqual(code, 5, out + err)  # refused like every unknown id (AC-ARC-03h), nothing read outside
        with self.subTest("backup restore"):
            p = PtyProc(["--dir", str(self.ws), "backup", "restore", "../../etc/passwd"], {**CLI_ENV, "HOME": str(self.home)})
            code, out = p.finish()
            self.assertEqual(code, 1, out)
            self.assertIn("not a backup", out)

    def test_AC_TST_05f_the_token_never_stays_in_the_url(self):
        r = Http(self.P).get(f"/auth?t={self.T}", cookie=False)
        self.assertEqual((r.status, r.headers["location"]), (302, "/"))
        self.assertEqual(r.headers["referrer-policy"], "no-referrer")
        self.assertNotIn("t=", r.headers["location"])
        self.assertNotIn(self.T, json.dumps(r.headers))


class Secrets(SV):
    """One canary run: fake runners print every canary; nothing may reach a file, API answer or export."""

    def setUp(self):
        super().setUp()
        (self.ws / ".env").write_text("".join(f"{k}={v}\n" for k, v in CANARIES.items()))
        self.rec = self.ws / "env-record.json"
        body = f"""
            import json
            for v in {list(CANARIES.values()) + [AWS]!r}:
                print(v)
                print(v, file=sys.stderr)
            fds = []
            for n in os.listdir("/proc/self/fd"):
                try:
                    fds.append(os.readlink("/proc/self/fd/" + n))
                except OSError:
                    pass
            open({str(self.rec)!r}, "w").write(json.dumps({{"env": dict(os.environ), "fds": fds}}))
            write_result()
        """
        self.boot({"fake": (body, {})}, {"docs": "fake"}, policies={"redact_env": ["AWS_SECRET_ACCESS_KEY"]})
        self.serve()
        self.tid = self.docs_task()
        self.code, self.out, self.err = self.run_json(self.tid, SENTINEL_DASHBOARD_TOKEN=self.srv.token,
                                                      AWS_SECRET_ACCESS_KEY=AWS, **CANARIES)

    def sweep(self, root, values):
        hits = []
        for p in Path(root).rglob("*"):
            if p.is_file() and not p.is_symlink():
                data = p.read_bytes()
                for v in values:
                    if v.encode() in data:
                        hits.append((str(p.relative_to(root)), v))
        return hits

    def test_AC_SEC_02l_the_agent_environment_is_stripped(self):
        self.assertEqual(self.code, 0, self.out + self.err)
        rec = json.loads(self.rec.read_text())
        text = json.dumps(rec["env"])
        for secret in (self.srv.token, AWS):
            self.assertNotIn(secret, text)
        self.assertNotIn("SENTINEL_DASHBOARD_TOKEN", rec["env"])
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", rec["env"])
        for link in rec["fds"]:
            for name in ("server.json", "server.lock", "user.db"):
                self.assertNotIn(name, link)

    def test_AC_SEC_02l_child_env_drops_token_and_redacted_names(self):
        env = child_env({"policies": {"redact_env": ["AWS_SECRET_ACCESS_KEY"]}}, "t-1",
                        base={"SENTINEL_DASHBOARD_TOKEN": "tok", "AWS_SECRET_ACCESS_KEY": AWS, "HOME": "/h"})
        self.assertEqual(env, {"HOME": "/h", "SENTINEL_TASK_ID": "t-1"})

    def test_AC_SEC_06j_canary_sweep_of_run_files_and_api_answers(self):
        state = self.ws / ".sentinel"
        files = [(rel, v) for rel, v in self.sweep(state, list(CANARIES.values()) + [AWS])
                 if not rel.startswith(("shared/", "workspaces/"))]
        self.assertEqual(files, [], "canary values reached stored run files")
        for path in ("/api/v1/projects", f"/api/v1/tasks/{SLUG}/report"):
            text = self.http.get(path).text
            for v in list(CANARIES.values()) + [AWS]:
                self.assertNotIn(v, text)
        log = self.http.get(f"/api/v1/tasks/{SLUG}/logs/{self.tid}")
        for v in list(CANARIES.values()) + [AWS]:
            self.assertNotIn(v, log.text)

    def test_AC_SEC_06j_canary_in_a_long_needs_human_reason_stays_out_of_notifications(self):
        import notifications
        canary = CANARIES["CANARY_DB_PASSWORD"]
        # the canary starts a few characters before the clip length, so a clip made before the scrub would leave a prefix
        reason = "a" * (notifications.TEXT_MAX - 5) + canary + " tail"
        self.add_event(SLUG, "run.state_changed", payload={"to": "NEEDS_HUMAN", "reason": reason})
        api = self.http.get("/api/v1/notifications")
        self.assertEqual(api.status, 200, api.text)
        self.assertTrue(any(n["text"].startswith("aaaa") for n in api.json["items"]), api.text[:300])
        r = subprocess.run(CLI + ["notifications", "--json"], capture_output=True, text=True,
                           env={**CLI_ENV, "HOME": str(self.home), "XDG_CONFIG_HOME": ""}, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for where, text in (("api", api.text), ("cli", r.stdout)):
            for v in list(CANARIES.values()):
                self.assertNotIn(v, text, where)
                self.assertNotIn(v[:6], text.replace("aaaa", ""), where)  # no leftover prefix of the canary either

    def test_AC_SEC_06k_prompts_and_task_files_hold_no_secret(self):
        values = list(CANARIES.values()) + [AWS, self.srv.token]
        for p in (self.ws / ".sentinel" / "runs").rglob("*"):
            if p.is_file() and (p.name.startswith("prompt") or p.name in ("task.json", "task.sealed.json")):
                data = p.read_text(errors="replace")
                for v in values:
                    self.assertNotIn(v, data, str(p))

    def test_AC_SEC_06l_a_backup_is_as_sensitive_as_the_registry(self):
        r = subprocess.run(CLI + ["--dir", str(self.ws), "backup"], capture_output=True, text=True,
                           env={**CLI_ENV, "HOME": str(self.home)}, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        path = Path(json.loads(r.stdout)["path"])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(path.parent.parent, self.ws / ".sentinel")
        data, reg = path.read_bytes(), (self.ws / ".sentinel" / "sentinel.db").read_bytes()
        for v in list(CANARIES.values()) + [AWS]:
            self.assertEqual(v.encode() in data, v.encode() in reg)


class EnvironmentOtherPaths(SV):
    """security_suite.feature AC-SEC-02l, the two other rows: the server's Q2 dispatch and a native task."""

    def body(self, rec):
        return f"""
            import json
            fds = []
            for n in os.listdir("/proc/self/fd"):
                try:
                    fds.append(os.readlink("/proc/self/fd/" + n))
                except OSError:
                    pass
            open({str(rec)!r}, "w").write(json.dumps({{"env": dict(os.environ), "fds": fds}}))
            write_result()
        """

    def test_AC_SEC_02l_the_servers_q2_dispatch_strips_the_environment(self):
        rec = self.ws / "q2-env.json"
        (self.ws / ".env").write_text("".join(f"{k}={v}\n" for k, v in CANARIES.items()))
        self.boot({"fake": (self.body(rec), {})}, {"docs": "fake"}, policies={"redact_env": ["AWS_SECRET_ACCESS_KEY"]})
        with self.eng.reg.transaction():
            self.eng.reg.update_run(SLUG, origin="dashboard", driver="ai-tool")  # only a dashboard run is started by the server
        patch = mock.patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": AWS, **CANARIES})
        patch.start()
        self.addCleanup(patch.stop)
        tid = self.docs_task(queue=True)
        self.serve(dispatch=True, dispatch_interval=0.1)
        self.assertTrue(wait_until(lambda: rec.exists() and self.task(tid)["state"] in ("COMPLETED", "FAILED"), 30),
                        self.task(tid)["state"])
        data = json.loads(rec.read_text())
        text = json.dumps(data["env"])
        for secret in (self.srv.token, AWS):
            self.assertNotIn(secret, text)
        self.assertNotIn("SENTINEL_DASHBOARD_TOKEN", data["env"])
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", data["env"])
        for link in data["fds"]:
            for name in ("server.json", "server.lock", "user.db"):
                self.assertNotIn(name, link)

    def test_AC_SEC_02l_the_files_a_native_subagent_reads_hold_no_secret(self):
        (self.ws / ".env").write_text("".join(f"{k}={v}\n" for k, v in CANARIES.items()))
        self.executing(tier=3)
        patch = mock.patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": AWS, **CANARIES})
        patch.start()
        self.addCleanup(patch.stop)
        self.serve()
        tid = self.make("docs", ["backend"], ["backend/docs/**"], objective="write the docs")
        self.assertEqual(self.task(tid)["adapter"], "native")
        files = [p for p in (self.ws / ".sentinel" / "runs" / SLUG / "tasks" / tid).rglob("*") if p.is_file()]
        self.assertTrue(files)
        for f in files:
            data = f.read_text(errors="replace")
            for v in [*CANARIES.values(), AWS, self.srv.token]:
                self.assertNotIn(v, data, str(f))


class Residual(SV):
    def setUp(self):
        super().setUp()
        self.h = self.spec_review(SLUG, 3)
        self.env = {**CLI_ENV, "HOME": str(self.home), "USER": "dev", "LOGNAME": "dev"}
        self.env.pop("SENTINEL_TASK_ID", None)

    def agent(self, *args, **extra):
        r = subprocess.run([sys.executable, SENTINEL, "--dir", str(self.ws), *args], capture_output=True, text=True,
                           input="", env={**self.env, "SENTINEL_TASK_ID": "t-agent", **extra})
        return r.returncode, r.stdout + r.stderr

    def spec_state(self):
        return [a["state"] for a in self.approvals("specification")]

    def test_AC_TST_05g_simple_forgery_attempts_by_an_agent_fail(self):
        rows = [(("approve", SLUG, "spec"), "E_NOT_TTY"), (("accept", SLUG), ("E_NOT_TTY", "E_ACTOR")),
                (("dashboard", "--no-open"), "E_ACTOR")]
        for args, want in rows:
            with self.subTest(args=args):
                code, out = self.agent(*args)
                self.assertEqual(code, 5, out)
                self.assertTrue(any(w in out for w in ((want,) if isinstance(want, str) else want)), out)
                self.assertEqual(self.spec_state(), ["IN_REVIEW"])
        self.serve()
        r = Http(self.srv.port).post(f"/api/v1/tasks/{SLUG}/approvals", self.body(self.h), cookie=False)
        self.assertEqual((r.status, r.code), (401, "E_AUTH"))
        self.assertEqual(self.spec_state(), ["IN_REVIEW"])
        self.assertNotIn("SENTINEL_DASHBOARD_TOKEN", child_env({}, "t-agent", base={"SENTINEL_DASHBOARD_TOKEN": "x"}))

    def test_AC_TST_05h_an_agent_driving_a_pseudo_terminal_is_recorded_not_stopped_R1(self):
        # RESIDUAL R1: if this starts failing, the product got safer (update docs/security.md); if the docs
        # lose the paragraph, the product silently got less honest. Either direction fails this test.
        p = PtyProc(["--dir", str(self.ws), "approve", SLUG, "spec"], self.env)
        self.assertTrue(p.wait_for("first 8 characters", 15))
        p.send(self.h[:8] + "\n")
        code, out = p.finish()
        self.assertEqual(code, 0, out)
        ap = self.approvals("specification")[-1]
        self.assertEqual((ap["state"], ap["channel"], ap["approver"]), ("APPROVED", "tty", "dev"))
        doc = (REPO / "docs" / "security.md").read_text()
        r1 = doc[doc.index("residual risk R1"):doc.index("## Dependencies")]
        self.assertIn("pseudo-terminal", r1)

    def test_AC_TST_05i_an_agent_reading_server_json_can_call_the_api_R1(self):
        self.serve()
        from apiserver import userdir  # what `sentinel dashboard` writes after it starts the server
        userdir.write_server_json(self.cfgdir, {"pid": os.getpid(), "port": self.srv.port, "token": self.srv.token})
        info = json.loads((self.cfgdir / "server.json").read_text())
        agent = Http(info["port"], info["token"]).login()
        r = agent.post(f"/api/v1/tasks/{SLUG}/approvals", self.body(self.h))
        self.assertEqual(r.status, 200, r.text)
        ap = self.approvals("specification")[-1]
        self.assertEqual((ap["state"], ap["channel"]), ("APPROVED", "dashboard"))
        doc = (REPO / "docs" / "security.md").read_text()
        r1 = doc[doc.index("residual risk R1"):doc.index("## Dependencies")]
        self.assertIn("server.json", r1)
        self.assertIn("channel `dashboard`", r1)


class DocsAndConfigs(unittest.TestCase):
    def test_AC_TST_05j_R3_is_stated_as_detected_not_prevented(self):
        doc = (REPO / "docs" / "security.md").read_text()
        r3 = doc[doc.index("Residual risk R3"):doc.index("## Audit log and backups")]
        for word in ("E_SCOPE", "git commit", "does not undo"):
            self.assertIn(word, r3)

    def test_AC_SEC_08a_docs_state_that_a_same_user_attacker_can_rewrite_the_chain(self):
        doc = (REPO / "docs" / "security.md").read_text()
        part = doc[doc.index("## Audit log and backups"):]
        self.assertIn("rewrite every row and the whole chain", part)

    def test_AC_TST_05_dashboard_source_builds_no_html_from_content(self):
        bad = re.compile(r"dangerouslySetInnerHTML|\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML|document\.write\(|\beval\(|new Function\(")
        hits = []
        for p in (REPO / "dashboard" / "src").rglob("*"):
            if p.suffix in (".ts", ".tsx", ".js", ".jsx") and bad.search(p.read_text(errors="replace")):
                hits.append(str(p.relative_to(REPO)))
        self.assertEqual(hits, [])
        self.assertTrue((REPO / "dashboard" / "e2e" / "accessibility_xss.spec.ts").is_file())


class SyncDeny(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.ws = Path(cls._tmp.name) / "ws"
        cls.ws.mkdir()
        repo = cls.ws / "backend"
        repo.mkdir()
        (repo / "build.gradle").write_text("")
        for c in (["init", "-q", "-b", "main"], ["add", "."], ["-c", "user.email=a@b", "-c", "user.name=t", "commit", "-q", "-m", "i"]):
            subprocess.run(["git", *c], cwd=repo, check=True, capture_output=True)
        r = subprocess.run(CLI + ["--dir", str(cls.ws), "init", "--shape", "single", "--non-interactive", "--local-only"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr

    def sync(self, tool):
        r = subprocess.run(CLI + ["--dir", str(self.ws), "sync-adapters", "--tool", tool], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_AC_SEC_04d_generated_configs_deny_the_human_commands(self):
        # `agy` (Antigravity) is not a `sync-adapters --tool` value: it reads the AGENTS.md that `--tool agents` writes
        for tool in ("claude", "agents", "codex", "gemini", "cursor"):
            with self.subTest(tool=tool):
                self.sync(tool)
                if tool == "claude":
                    deny = json.loads((self.ws / ".claude" / "settings.json").read_text())["permissions"]["deny"]
                    for rule in ("Bash(sentinel approve:*)", "Bash(sentinel accept:*)", "Bash(sentinel backup restore:*)",
                                 "Bash(sentinel audit export:*)", "Read(//**/.config/sentinel/server.json)"):
                        self.assertIn(rule, deny)
                else:
                    text = (self.ws / "AGENTS.md").read_text()
                    for phrase in ("sentinel approve", "sentinel accept", "sentinel backup restore", "sentinel audit export",
                                   "server.json"):
                        self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
