"""Phase I: --bind and --public-host of `sentinel dashboard` (dashboard_server_flags.feature)."""
import re
import signal
import tempfile
import time
import unittest
from pathlib import Path

import yaml

from sv_helpers import CONFIG, Dash, Http, free_port

URL = re.compile(r"http://([^/\s]+)/auth\?t=([0-9a-f]{64})")


class Flags(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.home = root / "home"
        self.home.mkdir()
        self.cfg = self.home / ".config" / "sentinel"
        self.ws = root / "ws" / "digital-hr"
        self.ws.mkdir(parents=True)
        (self.ws / "sentinel.config.yaml").write_text(yaml.safe_dump(CONFIG, sort_keys=False))

    def container(self, evidence=True, env="1"):
        """The environment of a simulated container: SENTINEL_CONTAINER plus (test mode only) a marker file standing for /.dockerenv."""
        marker = Path(self._tmp.name) / ".dockerenv"
        if evidence:
            marker.write_text("")
        return {"SENTINEL_CONTAINER": env, "SENTINEL_TEST_MODE": "1", "SENTINEL_TEST_CONTAINER_MARKERS": str(marker)}

    def start(self, *args, env=None, wait=True):
        e = {"HOME": str(self.home), "USER": "dev", "LOGNAME": "dev", **(env or {})}
        d = Dash(self, args=args, cwd=self.ws, env=e)
        if wait:
            end = time.time() + 15
            while not URL.search(d.text()) and time.time() < end:
                d.pump(0.1)
            m = URL.search(d.text())
            self.assertTrue(m, d.text())
            d.host, d.token = m.group(1), m.group(2)
            d.port = int(d.host.rsplit(":", 1)[1])
        self.addCleanup(lambda: d.exited() or d.signal(signal.SIGTERM))
        return d

    def listening(self, pid):
        inodes = set()
        for fd in Path(f"/proc/{pid}/fd").iterdir():
            try:
                t = __import__("os").readlink(fd)
            except OSError:
                continue
            m = re.fullmatch(r"socket:\[(\d+)\]", t)
            if m:
                inodes.add(m.group(1))
        out = []
        for name in ("tcp", "tcp6"):
            for line in Path(f"/proc/net/{name}").read_text().splitlines()[1:]:
                f = line.split()
                if f[3] == "0A" and f[9] in inodes:
                    addr, port = f[1].split(":")
                    out.append((addr, int(port, 16)))
        return out

    def refused(self, args, env=None):
        d = self.start(*args, env=env, wait=False)
        code, out = d.finish(10)
        self.assertEqual(code, 2, out)
        self.assertIn("usage", out.lower())
        self.assertFalse((self.cfg / "server.json").exists())
        return out

    def test_AC_SEC_10a_bind_is_refused_outside_a_container(self):
        out = self.refused(("--no-open", "--bind", "0.0.0.0"))
        self.assertRegex(re.sub(r"\x1b\[[0-9;]*m", "", out).lower().replace("\n", " "), r"only .*inside the sentinel container")

    def test_AC_SEC_10b_only_0_0_0_0_and_only_in_a_container(self):
        rows = [("1", "192.168.1.20"), ("1", "::"), ("1", "localhost"), ("0", "0.0.0.0"), ("yes", "0.0.0.0"), ("", "0.0.0.0"), (None, "0.0.0.0")]
        for env, address in rows:
            with self.subTest(env=env, address=address):
                self.refused(("--no-open", "--bind", address), env=self.container(env=env))

    def test_AC_SEC_10l_the_environment_alone_is_not_container_evidence(self):
        out = self.refused(("--no-open", "--bind", "0.0.0.0"), env=self.container(evidence=False))
        self.assertIn("container", out.lower())

    def test_AC_SEC_10m_a_published_port_may_differ_from_the_server_port_in_a_container(self):
        port, published = free_port(), free_port()
        d = self.start("--no-open", "--bind", "0.0.0.0", "--port", str(port), "--public-host", f"localhost:{published}", env=self.container())
        self.assertEqual(d.host, f"localhost:{published}")
        self.assertIn(f"-p 127.0.0.1:{port}:{port}", d.text())
        self.assertIn("refused", d.text())
        for host, ok in ((f"localhost:{published}", True), (f"localhost:{port}", True), ("localhost:9", False)):
            with self.subTest(host=host):
                r = Http(port).req("GET", "/api/v1/session", host=host)
                self.assertEqual(r.code == "E_HOST", not ok, r.text)

    def test_AC_SEC_10n_outside_a_container_the_public_port_must_be_the_server_port(self):
        port, other = free_port(), free_port()
        self.refused(("--no-open", "--port", str(port), "--public-host", f"localhost:{other}"))
        self.refused(("--no-open", "--public-host", f"localhost:{other}"))

    def test_AC_SEC_10c_the_environment_variable_alone_does_not_widen_the_bind(self):
        d = self.start("--no-open", env={"SENTINEL_CONTAINER": "1"})
        self.assertEqual(self.listening(d.pid), [("0100007F", d.port)])

    def test_AC_SEC_10d_in_a_container_the_flag_binds_all_interfaces(self):
        port = free_port()
        d = self.start("--no-open", "--bind", "0.0.0.0", "--port", str(port), "--public-host", f"localhost:{port}", env=self.container())
        self.assertEqual(self.listening(d.pid), [("00000000", port)])
        self.assertEqual(d.host, f"localhost:{port}")

    def test_AC_SEC_10e_host_and_origin_accept_the_loopback_names_and_the_public_host_only(self):
        port = free_port()
        d = self.start("--no-open", "--port", str(port), "--public-host", f"localhost:{port}")
        rows = [(f"localhost:{port}", f"http://localhost:{port}", None), (f"127.0.0.1:{port}", f"http://127.0.0.1:{port}", None),
                ("evil.example:%d" % port, None, "E_HOST"), ("localhost:9999", None, "E_HOST"), ("172.17.0.2:%d" % port, None, "E_HOST"),
                ("0.0.0.0:%d" % port, None, "E_HOST"), (f"localhost:{port}", "http://evil.example:%d" % port, "E_ORIGIN"),
                (f"localhost:{port}", "http://localhost:9999", "E_ORIGIN"), ("localhost", None, "E_HOST")]
        for host, origin, code in rows:
            with self.subTest(host=host, origin=origin):
                r = Http(port).req("GET", "/api/v1/session", host=host, origin=origin)
                if code:
                    self.assertEqual((r.status, r.code), (403, code), r.text)
                else:
                    self.assertEqual(r.status, 401, r.text)
                    self.assertNotIn(r.code, ("E_HOST", "E_ORIGIN"))

    def test_AC_SEC_10f_public_host_takes_only_a_loopback_name_with_a_valid_port(self):
        for value in ("example.com:8765", "192.168.1.20:8765", "localhost", "localhost:80", "localhost:abc", "0.0.0.0:8765", "localhost:8765/x"):
            with self.subTest(value=value):
                self.refused(("--no-open", "--public-host", value))

    def test_AC_SEC_10g_token_csrf_and_cookie_rules_are_unchanged(self):
        port = free_port()
        args = ("--no-open", "--bind", "0.0.0.0", "--port", str(port), "--public-host", f"localhost:{port}")
        d = self.start(*args, env=self.container())
        h = Http(port, d.token)
        r = h.req("GET", f"/auth?t={d.token}", cookie=False, host=f"localhost:{port}")
        self.assertEqual(r.status, 302)
        cookie = r.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertEqual(h.req("GET", "/api/v1/runtime", cookie=False, host=f"localhost:{port}").status, 401)
        h.login()
        self.assertEqual(h.post("/api/v1/projects/digital-hr/tasks", {}, csrf="x" * 8).status, 403)
        self.assertEqual(oct(self.cfg.joinpath("server.json").stat().st_mode & 0o777), "0o600")
        first = d.token
        d.signal(signal.SIGTERM)
        d.finish(10)
        d2 = self.start(*args, env=self.container())
        self.assertNotEqual(d2.token, first)

    def test_AC_SEC_10h_without_the_options_nothing_changes(self):
        d = self.start("--no-open")
        self.assertEqual(d.host, f"127.0.0.1:{d.port}")
        for host, ok in ((f"127.0.0.1:{d.port}", True), (f"localhost:{d.port}", True), (f"localhost:{d.port + 1}", False)):
            with self.subTest(host=host):
                r = Http(d.port).req("GET", "/api/v1/session", host=host)
                self.assertEqual(r.code == "E_HOST", not ok)


if __name__ == "__main__":
    unittest.main()
