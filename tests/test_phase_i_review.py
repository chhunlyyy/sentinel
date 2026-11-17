"""Phase I security review fixes: identity fallbacks, container evidence, peer filter, public host, attach URL."""
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sv_helpers import SCRIPTS, SENTINEL, SV, Http

sys.path.insert(0, str(SCRIPTS))

ROUTE = ("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
         "eth0\t00000000\t0100A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
         "eth0\t0000A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n")  # default via 192.168.0.1


def cli(*args, env=None):
    e = {**os.environ, **(env or {})}
    return subprocess.run([sys.executable, SENTINEL, *args], capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL)


class Identity(unittest.TestCase):
    def test_getuser_failure_falls_back_to_uid(self):
        import getpass
        import sentinel
        from apiserver import server
        for exc in (KeyError("getpwuid(): uid not found: 4321"), OSError("no passwd")):
            with self.subTest(exc=type(exc).__name__), mock.patch.object(getpass, "getuser", side_effect=exc), \
                    mock.patch("os.getuid", return_value=4321):
                self.assertEqual(server.identity()[0], "uid4321")
                self.assertEqual(sentinel.human_identity()[0], "uid4321")

    def test_approver_name_is_honoured_only_in_the_container(self):
        import sentinel
        from apiserver import server
        base = {"GIT_AUTHOR_NAME": "Other", "GIT_AUTHOR_EMAIL": "o@example.com"}
        with mock.patch.dict(os.environ, {**base, "SENTINEL_CONTAINER": "1", "SENTINEL_APPROVER_NAME": "  Ada\x07 Lovelace "}):
            self.assertEqual(server.identity()[1], "Ada Lovelace")
            self.assertEqual(sentinel.human_identity()[1], "Ada Lovelace")
        with mock.patch.dict(os.environ, {**base, "SENTINEL_APPROVER_NAME": "Ada Lovelace"}):
            os.environ.pop("SENTINEL_CONTAINER", None)
            self.assertEqual(server.identity()[1], "Other")
            self.assertEqual(sentinel.human_identity()[1], "Other")

    def test_the_container_user_env_is_set_in_the_image(self):
        text = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text()
        self.assertIn("USER=sentinel LOGNAME=sentinel HOME=/home/sentinel", text)


class Netguard(unittest.TestCase):
    def setUp(self):
        from apiserver import netguard
        self.ng = netguard
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.route = Path(self.tmp.name) / "route"
        self.route.write_text(ROUTE)
        self.marker = Path(self.tmp.name) / ".dockerenv"
        for p in (mock.patch.object(netguard, "ROUTE_FILE", str(self.route)), mock.patch.object(netguard, "MARKERS", (str(self.marker),))):
            p.start()
            self.addCleanup(p.stop)

    def test_container_evidence_needs_the_env_and_a_marker(self):
        with mock.patch.dict(os.environ, {"SENTINEL_CONTAINER": "1"}):
            self.assertFalse(self.ng.container_ok())
            self.marker.write_text("")
            self.assertTrue(self.ng.container_ok())
        with mock.patch.dict(os.environ, {"SENTINEL_CONTAINER": "0"}):
            self.assertFalse(self.ng.container_ok())
        env = {k: v for k, v in os.environ.items() if k != "SENTINEL_CONTAINER"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(self.ng.container_ok())

    def test_the_default_gateway_is_read_from_the_route_table(self):
        self.assertEqual(self.ng.default_gateways(), {"192.168.0.1"})
        self.route.write_text("garbage\n")
        self.assertEqual(self.ng.default_gateways(), set())
        self.route.unlink()
        self.assertEqual(self.ng.default_gateways(), set())

    def test_who_may_connect(self):
        ok = self.ng.peer_allowed
        for ip in ("127.0.0.1", "127.5.5.5", "::1", "::ffff:127.0.0.1", "192.168.0.1"):
            self.assertTrue(ok(ip, ()), ip)
        for ip in ("192.168.0.2", "10.0.0.1", "172.17.0.2", "::2", "not an ip", ""):
            self.assertFalse(ok(ip, ()), ip)
        self.assertTrue(ok("10.0.2.2", ("10.0.2.2",)))
        self.assertFalse(ok("10.0.2.3", ("10.0.2.2",)))

    def test_the_server_asserts_its_bind_address(self):
        from apiserver.server import ApiServer
        cfg = Path(self.tmp.name) / "cfg"
        for bind in ("192.168.1.20", "::", "localhost", "0.0.0.0"):
            with self.subTest(bind=bind), mock.patch.dict(os.environ, {"SENTINEL_CONTAINER": "1"}):
                with self.assertRaises(ValueError):
                    ApiServer(cfg, bind=bind, user="dev", git_name="Dev")  # no container marker
        self.marker.write_text("")
        with mock.patch.dict(os.environ, {"SENTINEL_CONTAINER": "1"}):
            ApiServer(cfg, bind="0.0.0.0", user="dev", git_name="Dev")
            with self.assertRaises(ValueError):
                ApiServer(cfg, bind="192.168.1.20", user="dev", git_name="Dev")
        ApiServer(cfg, user="dev", git_name="Dev")
        ApiServer(cfg, bind="127.0.0.1", user="dev", git_name="Dev")


class Peers(SV):
    """A server bound to all interfaces in a (simulated) container refuses every peer that is not loopback or the gateway."""

    def setUp(self):
        super().setUp()
        from apiserver import netguard
        self.ng = netguard
        self.route = Path(self.home) / "route"
        self.route.write_text(ROUTE)
        marker = Path(self.home) / ".dockerenv"
        marker.write_text("")
        for p in (mock.patch.object(netguard, "ROUTE_FILE", str(self.route)), mock.patch.object(netguard, "MARKERS", (str(marker),)),
                  mock.patch.dict(os.environ, {"SENTINEL_CONTAINER": "1"})):
            p.start()
            self.addCleanup(p.stop)

    def raw_server(self, **kw):
        from apiserver.server import ApiServer
        self.srv = ApiServer(self.cfgdir, port=0, user="dev", git_name="Dev User", poll_interval=self.POLL, bind="0.0.0.0", **kw)
        self.srv.start()
        self.addCleanup(self.srv.stop)

    def test_a_peer_outside_the_allowed_set_gets_403_and_no_body_is_read(self):
        with mock.patch.object(self.ng, "is_loopback", lambda ip: False):
            self.raw_server()
            r = Http(self.srv.port).req("GET", f"/auth?t={self.srv.token}", cookie=False)
            self.assertEqual((r.status, r.code), (403, "E_HOST"), r.text)
            r = Http(self.srv.port).req("POST", "/api/v1/projects/digital-hr/tasks", raw=b"{" * 10, csrf="x" * 8)
            self.assertEqual((r.status, r.code), (403, "E_HOST"), r.text)

    def test_the_gateway_and_allow_peer_pass(self):
        with mock.patch.object(self.ng, "is_loopback", lambda ip: False):
            self.route.write_text(ROUTE.replace("0100A8C0", "0100007F"))  # default gateway 127.0.0.1
            self.raw_server()
            self.assertEqual(Http(self.srv.port).req("GET", "/api/v1/session", cookie=False).status, 401)
        with mock.patch.object(self.ng, "is_loopback", lambda ip: False):
            self.route.write_text(ROUTE)
            self.srv.stop()
            self.raw_server(allow_peers=["127.0.0.1"])
            self.assertEqual(Http(self.srv.port).req("GET", "/api/v1/session", cookie=False).status, 401)

    def test_the_default_bind_has_no_peer_filter(self):
        with mock.patch.object(self.ng, "is_loopback", lambda ip: False):
            self.serve()
            self.assertEqual(Http(self.srv.port).req("GET", "/api/v1/session", cookie=False).status, 401)


class Cli(unittest.TestCase):
    """The parse stage: a request that passes it stops at E_NOT_TTY (exit 5) because these runs have no terminal."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        marker = Path(self.tmp.name) / ".dockerenv"
        marker.write_text("")
        self.container = {"SENTINEL_CONTAINER": "1", "SENTINEL_TEST_MODE": "1", "SENTINEL_TEST_CONTAINER_MARKERS": str(marker)}

    def test_bind_needs_the_container_evidence_not_only_the_env(self):
        r = cli("dashboard", "--bind", "0.0.0.0", env={"SENTINEL_CONTAINER": "1", "SENTINEL_TEST_MODE": "1", "SENTINEL_TEST_CONTAINER_MARKERS": "/nonexistent/.dockerenv"})
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("container", r.stderr)
        r = cli("dashboard", "--bind", "0.0.0.0", env=self.container)
        self.assertEqual(r.returncode, 5, r.stderr)

    def test_the_test_hooks_need_test_mode(self):
        env = {k: v for k, v in self.container.items() if k != "SENTINEL_TEST_MODE"}
        r = cli("dashboard", "--bind", "0.0.0.0", env=env)
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_public_host_port_must_equal_the_server_port_outside_a_container(self):
        env = {k: v for k, v in os.environ.items() if k != "SENTINEL_CONTAINER"}
        for args in (("--public-host", "localhost:9000"), ("--port", "8765", "--public-host", "localhost:9000")):
            with self.subTest(args=args):
                r = cli("dashboard", *args, env={"SENTINEL_CONTAINER": ""})
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("public-host", r.stderr)
        r = cli("dashboard", "--port", "9000", "--public-host", "localhost:9000", env={"SENTINEL_CONTAINER": ""})
        self.assertEqual(r.returncode, 5, r.stderr)

    def test_in_a_container_the_public_port_may_differ(self):
        r = cli("dashboard", "--bind", "0.0.0.0", "--port", "8765", "--public-host", "localhost:9000", env=self.container)
        self.assertEqual(r.returncode, 5, r.stderr)

    def test_allow_peer_takes_an_ip_address_and_repeats(self):
        r = cli("dashboard", "--bind", "0.0.0.0", "--allow-peer", "10.0.2.2", "--allow-peer", "fd00::1", env=self.container)
        self.assertEqual(r.returncode, 5, r.stderr)
        for bad in ("10.0.2.0/24", "host.docker.internal", ""):
            with self.subTest(bad=bad):
                r = cli("dashboard", "--bind", "0.0.0.0", "--allow-peer", bad, env=self.container)
                self.assertEqual(r.returncode, 2, r.stderr)


class Attach(unittest.TestCase):
    def test_attach_prints_the_public_host(self):
        from apiserver import lifecycle
        out = io.StringIO()
        info = {"pid": 7, "port": 8765, "token": "a" * 64}
        with mock.patch.object(lifecycle, "_register"), mock.patch("sys.stdout", out):
            self.assertEqual(lifecycle._attach(Path("/x"), info, None, "localhost:9000"), 0)
            self.assertEqual(lifecycle._attach(Path("/x"), info, None), 0)
        lines = out.getvalue().splitlines()
        self.assertIn("http://localhost:9000/auth?t=" + "a" * 64, lines[0])
        self.assertIn("http://127.0.0.1:8765/auth?t=" + "a" * 64, lines[1])


if __name__ == "__main__":
    unittest.main()
