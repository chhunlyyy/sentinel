"""Phase F: the CLI is unchanged and the server stays offline (regression_offline.feature)."""
import ast
import json
import os
import re
import socket
import subprocess
import sys
import threading
import unittest
from pathlib import Path

from sv_helpers import SV, SLUG, SCRIPTS, SENTINEL, Http, Stream, ids

ROOT = Path(__file__).resolve().parents[1]


class Regression(SV):
    def cfg_absent(self):
        return not (self.home / ".config" / "sentinel").exists()

    def test_AC_TST_01e_earlier_commands_leave_no_user_registry(self):
        self.assertTrue(self.cfg_absent())
        for args in (("run", "new", "x-run", "--type", "feature"), ("next", "x-run", "--json"), ("stats",)):
            self.cli(*args)
        self.assertTrue(self.cfg_absent())

    def test_AC_TST_01f_cli_commands_do_not_need_or_create_server_files(self):
        expected = {("run", "new", "leave-balance", "--type", "feature"): 0, ("next", "leave-balance", "--json"): 0,
                    ("review", "leave-balance", "spec"): 5, ("stats",): 0}
        for args, code in expected.items():
            with self.subTest(args=args):
                c, out, err = self.cli(*args)
                self.assertEqual(c, code, out + err)
                self.assertTrue(self.cfg_absent())
        c, out, err = self.cli("doctor")
        self.assertIn(c, (0, 1))
        self.assertTrue(self.cfg_absent())

    def test_AC_TST_01g_the_cli_does_not_load_the_server_code_unless_asked_for(self):
        self.cli("run", "new", "leave-balance", "--type", "feature")
        probe = ("import runpy, sys\nsys.argv = ['sentinel', '--dir', %r, 'next', 'leave-balance', '--json']\n"
                 "try:\n    runpy.run_path(%r, run_name='__main__')\nexcept SystemExit:\n    pass\n"
                 "print('LOADED:' + ','.join(sorted(m for m in sys.modules if m.split('.')[0] == 'apiserver')))\n"
                 % (str(self.ws), SENTINEL))
        r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env={**os.environ, "HOME": str(self.home)})
        self.assertIn("LOADED:\n", r.stdout + "\n")
        self.assertRegex(r.stdout, r"LOADED:\s*$")

    def test_AC_TST_01h_the_0_1_flow_is_untouched_by_the_server(self):
        c, out, err = self.cli("run", "new", "old-fix", "--tier", "1")
        self.assertEqual(c, 0, out + err)
        self.serve()
        c, out, err = self.cli("run", "update", "old-fix", "--stage", "coder")
        self.assertEqual(c, 0, out + err)
        c, out, err = self.cli("run", "finish", "old-fix", "--outcome", "passed")
        self.assertEqual(c, 0, out + err)
        r = self.http.get("/api/v1/tasks/old-fix")
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json["workflow_version"], "0.1")
        w = self.http.post("/api/v1/tasks/old-fix/control", {"action": "cancel"})
        self.assertEqual(w.status, 409)

    def test_AC_SEC_03v_terminal_approval_with_a_running_server(self):
        h = self.spec_review("review-run", 3)
        self.serve()
        s = self.stream("/api/v1/events?project=digital-hr")
        code, out = self.run_tty(["approve", "review-run", "spec"], typed=[h[:8]])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.approvals("specification", "review-run")[-1]["channel"], "tty")
        msgs = s.messages(6, timeout=3)
        dec = [json.loads(m["data"]) for m in msgs if m["event"] == "approval.decided"]
        self.assertEqual(dec[0]["actor"]["channel"], "tty")
        self.assertEqual(dec[0]["actor"]["kind"], "human")

    def test_AC_SEC_03w_a_running_server_gives_no_new_way_to_approve_without_a_terminal(self):
        self.spec_review("review-run", 3)
        self.serve()
        c, out, err = self.cli("approve", "review-run", "spec")
        self.assertEqual(c, 5, out + err)
        self.assertIn("E_NOT_TTY", out + err)

    # ---- offline and stdlib only
    def test_AC_DSH_06a_no_outbound_network_connection(self):
        from apiserver.server import ApiServer
        self.executing(tier=3)
        self.add_project()
        events = []
        window = {"server_calls": False}
        main = threading.main_thread()
        watched = ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo")

        def hook(name, args):
            if name in watched and (threading.current_thread() is not main or window["server_calls"]):
                events.append((name, args[1] if name == "socket.connect" else args))
        sys.addaudithook(hook)
        srv = ApiServer(self.cfgdir, port=0, user="dev", poll_interval=0.05, dispatch=True, dispatch_interval=0.1)
        window["server_calls"] = True
        srv.start()
        window["server_calls"] = False
        self.srv = srv
        c = Http(srv.port, srv.token).login()
        for p in ("/", "/api/v1/session", "/api/v1/installation", "/api/v1/runtime", "/api/v1/projects",
                  "/api/v1/projects/digital-hr", "/api/v1/projects/digital-hr/tasks", f"/api/v1/tasks/{SLUG}",
                  f"/api/v1/tasks/{SLUG}/next", f"/api/v1/tasks/{SLUG}/workflow", "/api/v1/approvals", "/api/v1/audit"):
            self.assertEqual(c.get(p).status, 200, p)
        s = Stream(c, "/api/v1/events")
        r = c.post("/api/v1/projects/digital-hr/tasks", {"slug": "via-api", "request": "x", "type": "feature"})
        self.assertEqual(r.status, 201, r.text)
        s.messages(1, timeout=2)
        s.close()
        window["server_calls"] = True
        srv.stop()
        window["server_calls"] = False
        self.assertEqual([e for e in events if e[0] != "socket.connect"], [])
        for name, target in events:
            self.assertEqual(target[0], "127.0.0.1", (name, target))

    def test_AC_DSH_06b_the_served_page_loads_nothing_from_the_network(self):
        c = self.serve()
        r = c.get("/")
        self.assertEqual(r.status, 200)
        page = r.text
        refs = re.findall(r"""(?:src|href|action)\s*=\s*["']([^"']+)["']""", page) + re.findall(r"url\(([^)]+)\)", page)
        for ref in refs:
            if ref.startswith(("http:", "https:", "//")):
                self.assertTrue(ref.startswith(f"http://127.0.0.1:{self.srv.port}"), ref)
        self.assertNotRegex(page, r"""(?:src|href)\s*=\s*["'](?:https?:)?//(?!127\.0\.0\.1)""")

    def test_AC_DSH_06c_the_server_uses_the_standard_library_only(self):
        package = SCRIPTS / "apiserver"
        local = {p.stem for p in SCRIPTS.glob("*.py")} | {"apiserver"}
        declared = {"yaml", "jsonschema"}
        std = set(sys.stdlib_module_names)
        found = set()
        for f in package.glob("*.py"):
            for node in ast.walk(ast.parse(f.read_text())):
                if isinstance(node, ast.Import):
                    found |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])
        outside = found - std - local
        self.assertEqual(outside - declared, set())
        self.assertNotIn("http.server" if False else "flask", found)
        text = (ROOT / "pyproject.toml").read_text()
        self.assertIn('dependencies = ["pyyaml>=6", "jsonschema>=4"]', text)

    def test_AC_DSH_06d_the_dashboard_ui_is_not_built_yet(self):
        c = self.serve(dist_dir=self.ws / "no-dist")  # a wheel built without sentinel/dashboard_dist (AC-OPS-01c)
        r = c.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn("UI not installed", r.text)
        self.assertIn("/api/v1", r.text)
        self.assertEqual(r.headers["content-security-policy"], "default-src 'self'; frame-ancestors 'none'")

    def test_AC_DSH_06d_static_assets_come_only_from_the_installed_dist_folder(self):
        dist = self.ws / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html>built ui</html>")
        (dist / "assets" / "app.js").write_text("console.log(1)")
        secret = self.ws / "secret.txt"
        secret.write_text("nope")
        c = self.serve(dist_dir=dist)
        self.assertIn("built ui", c.get("/").text)
        r = c.get("/assets/app.js")
        self.assertEqual(r.status, 200)
        self.assertIn("javascript", r.headers["content-type"])
        for p in ("/assets/../../secret.txt", "/assets/%2e%2e/secret.txt", "/%2e%2e/secret.txt"):
            self.assertIn(c.get(p).status, (400, 404), p)


if __name__ == "__main__":
    unittest.main()
