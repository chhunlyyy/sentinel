"""Phase F: starting, attaching to and stopping the dashboard server (server_lifecycle.feature).

`sentinel dashboard` runs in a child process under a pseudo-terminal, as a human would start it."""
import json
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import yaml

from sv_helpers import CONFIG, Dash, Http, SENTINEL, Stream, free_port, wait_until


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.cfg = self.home / ".config" / "sentinel"
        self.ws = self.workspace("digital-hr")
        self.env = {"HOME": str(self.home), "USER": "dev", "LOGNAME": "dev"}
        self._dashes = []

    def workspace(self, name, parent=None):
        d = (parent or self.root / "ws") / name
        d.mkdir(parents=True)
        (d / "sentinel.config.yaml").write_text(yaml.safe_dump(CONFIG, sort_keys=False))
        return d

    def start(self, *args, cwd=None, env=None, tty=True, wait_url=True):
        dash = Dash(self, args=args or ("--no-open",), cwd=cwd or self.ws, env={**self.env, **(env or {})}, tty=tty)
        self._dashes.append(dash)
        if wait_url:
            dash.port, dash.token = dash.url()
        return dash

    def server_json(self):
        return json.loads((self.cfg / "server.json").read_text())

    def client(self, dash):
        return Http(dash.port, dash.token).login()

    def stop(self, dash, sig=signal.SIGTERM):
        dash.signal(sig)
        return dash.finish(10)

    # ---- AC-SEC-01 loopback bind
    def test_AC_SEC_01a_REQ_INS_01_REQ_ARC_02_starting_the_server_at_a_terminal(self):
        d = self.start()
        self.assertIn(f"http://127.0.0.1:{d.port}/auth?t={d.token}", d.text())
        self.assertEqual(self.server_json()["token"], d.token)
        c = self.client(d)
        r = c.get("/api/v1/runtime")
        self.assertEqual(r.status, 200, r.text)
        j = r.json
        self.assertEqual((j["pid"], j["port"]), (d.pid, d.port))
        self.assertTrue(j["started_at"])
        self.assertEqual([p["id"] for p in j["projects"]], ["digital-hr"])
        self.assertFalse(d._exited())

    def _listening(self, pid):
        """(address, port) of every listening TCP socket of pid, from /proc/net/tcp and tcp6."""
        inodes = set()
        for fd in Path(f"/proc/{pid}/fd").iterdir():
            try:
                t = os.readlink(fd)
            except OSError:
                continue
            m = re.fullmatch(r"socket:\[(\d+)\]", t)
            if m:
                inodes.add(m.group(1))
        out = []
        for name, v6 in (("tcp", False), ("tcp6", True)):
            for line in Path(f"/proc/net/{name}").read_text().splitlines()[1:]:
                f = line.split()
                if f[3] == "0A" and f[9] in inodes:
                    addr, port = f[1].split(":")
                    out.append((addr, int(port, 16), v6))
        return out

    def test_AC_SEC_01b_listening_socket_is_loopback_only(self):
        d = self.start()
        socks = self._listening(d.pid)
        self.assertEqual(socks, [("0100007F", d.port, False)])
        for ip in self.non_loopback_addresses():
            s = socket.socket()
            s.settimeout(2)
            self.assertNotEqual(s.connect_ex((ip, d.port)), 0, ip)
            s.close()

    def non_loopback_addresses(self):
        found = []
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                found.append(ip)
        except OSError:
            pass
        return found

    def test_AC_SEC_01c_no_option_chooses_another_address(self):
        for args in (("--host", "0.0.0.0"), ("--bind", "192.168.1.20"), ("--listen", "::", "--no-open")):
            with self.subTest(args=args):
                d = self.start(*args, wait_url=False)
                code, out = d.finish(10)
                self.assertEqual(code, 2, out)
                self.assertIn("usage", out.lower())
                self.assertFalse((self.cfg / "server.json").exists())

    def test_AC_SEC_01d_environment_and_config_cannot_widen_the_bind(self):
        rows = [({"SENTINEL_HOST": "0.0.0.0"}, None), ({"HOST": "0.0.0.0"}, None), ({}, {"dashboard": {"host": "::"}})]
        for env, extra in rows:
            with self.subTest(env=env, extra=extra):
                ws = self.workspace("hr-" + str(abs(hash(str(env) + str(extra))))[:6])
                if extra:
                    (ws / "sentinel.config.yaml").write_text(yaml.safe_dump({**CONFIG, **extra}, sort_keys=False))
                d = self.start(env=env, cwd=ws)
                self.assertEqual(self._listening(d.pid), [("0100007F", d.port, False)])
                self.stop(d)

    def test_AC_API_01a_choosing_the_port(self):
        ok = free_port()
        for port, good in ((ok, True), ("1023", False), ("65536", False), ("0", False), ("abc", False)):
            with self.subTest(port=port):
                d = self.start("--no-open", "--port", str(port), wait_url=good)
                if good:
                    self.assertEqual(d.port, ok)
                    self.stop(d)
                else:
                    code, out = d.finish(10)
                    self.assertEqual(code, 2, out)
                    self.assertIn("1024 to 65535", out)

    def test_AC_API_01a_range_limits_1024_and_65535(self):
        for port in (1024, 65535):
            with self.subTest(port=port):
                busy = socket.socket()
                try:
                    busy.bind(("127.0.0.1", port))
                except OSError:
                    busy.close()
                    self.skipTest(f"port {port} is not free here")
                busy.close()
                d = self.start("--no-open", "--port", str(port))
                self.assertEqual(d.port, port)
                self.stop(d)

    def test_AC_API_01b_the_requested_port_is_taken(self):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        self.addCleanup(s.close)
        port = s.getsockname()[1]
        d = self.start("--no-open", "--port", str(port), wait_url=False)
        code, out = d.finish(10)
        self.assertEqual(code, 1, out)
        self.assertIn(f"port {port} is in use", out)
        self.assertFalse((self.cfg / "server.json").exists())
        self.assertTrue(self.lock_free())

    def lock_free(self):
        import fcntl
        p = self.cfg / "server.lock"
        if not p.exists():
            return True
        with open(p, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False
            fcntl.flock(f, fcntl.LOCK_UN)
        return True

    # ---- who may start it
    def test_AC_SEC_02b_a_task_process_cannot_start_or_attach(self):
        d = self.start(env={"SENTINEL_TASK_ID": "t-abc123"}, wait_url=False)
        code, out = d.finish(10)
        self.assertEqual(code, 5, out)
        self.assertIn("E_ACTOR", out)
        self.assertNotIn("auth?t=", out)
        self.assertFalse((self.cfg / "server.json").exists())

    def test_AC_SEC_02c_without_a_terminal_the_command_is_refused(self):
        for running in (False, True):
            with self.subTest(running=running):
                if running:
                    live = self.start()
                d = self.start(tty=False, wait_url=False)
                code, out = d.finish(10)
                self.assertEqual(code, 5, out)
                self.assertIn("E_NOT_TTY", out)
                self.assertNotIn("auth?t=", out)
                if running:
                    self.assertNotIn(live.token, out)
                    self.stop(live)

    def test_AC_SEC_02d_the_token_never_enters_an_environment(self):
        d = self.start()
        env = Path(f"/proc/{d.pid}/environ").read_bytes().decode(errors="replace")
        cmdline = Path(f"/proc/{d.pid}/cmdline").read_bytes().decode(errors="replace")
        self.assertNotIn("SENTINEL_DASHBOARD_TOKEN", env)
        self.assertNotIn(d.token, env)
        self.assertNotIn(d.token, cmdline)

    # ---- private files
    def test_AC_SEC_02e_token_file_is_0600_in_a_0700_folder(self):
        d = self.start()
        self.assertEqual(stat.S_IMODE(self.cfg.stat().st_mode), 0o700)
        sj = self.cfg / "server.json"
        self.assertEqual(stat.S_IMODE(sj.stat().st_mode), 0o600)
        data = json.loads(sj.read_text())
        self.assertEqual(set(data), {"pid", "port", "token", "started_at", "version", "orchestrator"})
        self.assertRegex(data["token"], r"^[0-9a-f]{64}$")

    def test_AC_SEC_02f_a_folder_with_wider_permissions_is_tightened(self):
        self.cfg.mkdir(parents=True)
        os.chmod(self.cfg, 0o755)
        pj = self.cfg / "projects.json"
        pj.write_text(json.dumps({"version": 1, "projects": []}))
        os.chmod(pj, 0o644)
        d = self.start()
        self.assertEqual(stat.S_IMODE(self.cfg.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(pj.stat().st_mode), 0o600)
        self.assertIn("tightened", d.text())

    def test_AC_SEC_02g_xdg_config_home_moves_the_registry(self):
        x = self.root / "xdg"
        x.mkdir()
        d = self.start(env={"XDG_CONFIG_HOME": str(x)})
        self.assertTrue((x / "sentinel" / "server.json").is_file())
        self.assertTrue((x / "sentinel" / "projects.json").is_file())
        self.assertFalse((self.home / ".config" / "sentinel").exists())

    # ---- projects.json
    def test_AC_API_01c_starting_in_a_workspace_registers_it(self):
        d = self.start()
        data = json.loads((self.cfg / "projects.json").read_text())
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["projects"]), 1)
        p = data["projects"][0]
        self.assertEqual((p["id"], p["name"], p["path"]), ("digital-hr", "digital-hr", str(self.ws.resolve())))
        self.assertTrue(p["added_at"])
        self.assertEqual(stat.S_IMODE((self.cfg / "projects.json").stat().st_mode), 0o600)
        r = self.client(d).get("/api/v1/projects")
        self.assertEqual([i["id"] for i in r.json["items"]], ["digital-hr"])

    def test_AC_API_01d_the_same_workspace_is_registered_once(self):
        link = self.root / "link"
        link.symlink_to(self.ws)
        d1 = self.start()
        self.stop(d1)
        d2 = self.start(cwd=link)
        data = json.loads((self.cfg / "projects.json").read_text())
        self.assertEqual(len(data["projects"]), 1)
        self.assertEqual(data["projects"][0]["path"], str(self.ws.resolve()))

    def test_AC_API_01e_same_name_gets_a_distinct_id(self):
        d1 = self.start()
        self.stop(d1)
        other = self.workspace("digital-hr", parent=self.root / "elsewhere")
        d2 = self.start(cwd=other)
        ids = [p["id"] for p in json.loads((self.cfg / "projects.json").read_text())["projects"]]
        self.assertEqual(ids, ["digital-hr", "digital-hr-2"])

    def test_AC_API_01f_starting_outside_a_workspace_serves_registered_projects(self):
        d1 = self.start()
        self.stop(d1)
        before = (self.cfg / "projects.json").read_text()
        empty = self.root / "empty"
        empty.mkdir()
        d2 = self.start(cwd=empty)
        r = self.client(d2).get("/api/v1/projects")
        self.assertEqual([i["id"] for i in r.json["items"]], ["digital-hr"])
        self.assertEqual((self.cfg / "projects.json").read_text(), before)

    def test_AC_API_01g_a_broken_projects_json_is_never_overwritten(self):
        self.cfg.mkdir(parents=True)
        (self.cfg / "projects.json").write_text("{not json")
        d = self.start(wait_url=False)
        code, out = d.finish(10)
        self.assertEqual(code, 1, out)
        self.assertIn("projects.json", out)
        self.assertEqual((self.cfg / "projects.json").read_text(), "{not json")
        self.assertFalse((self.cfg / "server.json").exists())

    # ---- one server per user
    def test_AC_SEC_01e_a_second_call_attaches_to_the_live_server(self):
        d1 = self.start()
        before = (self.cfg / "server.json").read_text()
        d2 = self.start(wait_url=False)
        code, out = d2.finish(10)
        self.assertEqual(code, 0, out)
        self.assertIn(f"http://127.0.0.1:{d1.port}/auth?t={d1.token}", out)
        self.assertEqual((self.cfg / "server.json").read_text(), before)
        self.assertFalse(d1._exited())

    def test_AC_SEC_01f_attaching_from_a_new_workspace_registers_it(self):
        d1 = self.start()
        c = self.client(d1)
        pay = self.workspace("payroll")
        d2 = self.start(cwd=pay, wait_url=False)
        code, out = d2.finish(10)
        self.assertEqual(code, 0, out)
        ids = [p["id"] for p in json.loads((self.cfg / "projects.json").read_text())["projects"]]
        self.assertIn("payroll", ids)
        self.assertTrue(wait_until(lambda: "payroll" in [i["id"] for i in c.get("/api/v1/projects").json["items"]], 2))

    def test_AC_SEC_01g_two_starts_at_the_same_time_give_one_server(self):
        a = self.start(wait_url=False)
        b = self.start(wait_url=False)
        deadline = time.time() + 15
        while time.time() < deadline and not (a._exited() or b._exited()):
            a.pump(0.05)
            b.pump(0.05)
        done = a if a._exited() else b
        server = b if done is a else a
        code, out = done.finish(10)
        self.assertEqual(code, 0, out)
        sj = self.server_json()
        self.assertIn(f"http://127.0.0.1:{sj['port']}/auth?t={sj['token']}", out)
        self.assertEqual(sj["pid"], server.pid)
        self.assertFalse(self.lock_free())
        self.stop(server)

    def test_AC_SEC_01h_a_stale_server_json_is_replaced(self):
        sleeper = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))
        for pid in (99999, sleeper.pid):
            with self.subTest(pid=pid):
                self.cfg.mkdir(parents=True, exist_ok=True)
                os.chmod(self.cfg, 0o700)
                (self.cfg / "server.json").write_text(json.dumps(
                    {"pid": pid, "port": 9999, "token": "a" * 64, "started_at": "2026-01-01T00:00:00Z", "version": "1"}))
                d = self.start()
                self.assertEqual(self.server_json()["pid"], d.pid)
                self.assertNotEqual(d.token, "a" * 64)
                self.assertIn("stale server.json", d.text())
                self.stop(d)

    # ---- stopping
    def test_AC_SEC_01i_stopping_removes_server_json_and_releases_the_lock(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(sig=sig):
                d = self.start()
                c = self.client(d)
                s = Stream(c, "/api/v1/events")
                self.addCleanup(s.close)
                self.assertEqual(s.status, 200)
                t0 = time.time()
                d.signal(sig)
                self.assertTrue(s.closed(5))
                code, out = d.finish(5)
                self.assertEqual(code, 0, out)
                self.assertLess(time.time() - t0, 5.5)
                self.assertFalse((self.cfg / "server.json").exists())
                self.assertTrue(self.lock_free())

    def test_AC_SEC_01j_stopping_never_removes_another_servers_file(self):
        d = self.start()
        data = self.server_json()
        data["pid"] = 1
        (self.cfg / "server.json").write_text(json.dumps(data))
        os.chmod(self.cfg / "server.json", 0o600)
        self.stop(d)
        self.assertTrue((self.cfg / "server.json").exists())
        self.assertEqual(self.server_json()["pid"], 1)

    def test_AC_SEC_01k_every_start_rotates_the_token_and_csrf_value(self):
        d1 = self.start()
        c1 = self.client(d1)
        t1, csrf1 = d1.token, c1.csrf
        self.stop(d1)
        d2 = self.start()
        self.assertNotEqual(d2.token, t1)
        self.assertEqual(self.server_json()["token"], d2.token)
        c1.port = d2.port
        self.assertEqual(c1.get("/api/v1/runtime").status, 401)
        self.assertEqual(c1.get("/api/v1/runtime").code, "E_AUTH")
        c = Http(d2.port, t1)
        r = c.get(f"/auth?t={t1}", cookie=False)
        self.assertEqual(r.status, 401)
        self.assertNotIn("set-cookie", r.headers)
        c2 = self.client(d2)
        r = c2.post("/api/v1/tasks/no-run/control", {"action": "cancel"}, csrf=csrf1)
        self.assertEqual((r.status, r.code), (403, "E_CSRF"))

    def test_AC_SEC_05a_the_local_user_is_the_only_user_and_is_admin(self):
        d = self.start()
        c = self.client(d)
        r = c.get("/api/v1/runtime")
        self.assertEqual(r.json["user"], {"name": "dev", "role": "admin"})
        for path in ("/api/v1/users", "/api/v1/user"):
            self.assertEqual(c.get(path).status, 404)


if __name__ == "__main__":
    unittest.main()
