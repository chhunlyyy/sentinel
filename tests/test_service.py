"""Tests for Sentinel 2.0 background service (plan/v2-factory.md Decision 2, W2)."""
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import yaml

from sv_helpers import CONFIG, Dash, Http, SENTINEL, free_port, wait_until


class TestService(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.cfg = self.home / ".config" / "sentinel"
        self.ws = self.root / "ws" / "digital-hr"
        self.ws.mkdir(parents=True)
        (self.ws / "sentinel.config.yaml").write_text(yaml.safe_dump(CONFIG, sort_keys=False))
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.env = {
            "HOME": str(self.home),
            "USER": "dev",
            "LOGNAME": "dev",
            "PATH": f"{self.bin_dir}:{os.environ.get('PATH', '')}",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SENTINEL_ORCHESTRATOR": "none",
        }
        self.addCleanup(self._stop_service)

    def _stop_service(self):
        try:
            self.run_cli("service", "stop")
        except Exception:
            pass

    def run_cli(self, *args, env=None, cwd=None):
        cmd = [sys.executable, SENTINEL, *args]
        e = {**self.env, **(env or {})}
        return subprocess.run(cmd, env=e, cwd=cwd or self.ws, capture_output=True, text=True)

    # ---- 1. start/status/stop with real detached server on free port
    def test_start_status_stop_detached(self):
        port = free_port()
        res = self.run_cli("service", "start", "--port", str(port))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Sentinel service started", res.stdout)
        self.assertIn(str(port), res.stdout)

        # server.json exists with pid, port, token, pid_started_at
        sj_path = self.cfg / "server.json"
        self.assertTrue(sj_path.exists())
        sj = json.loads(sj_path.read_text())
        self.assertEqual(sj["port"], port)
        self.assertIn("pid", sj)
        self.assertIn("token", sj)
        self.assertIn("started_at", sj)

        # service.log exists
        log_path = self.cfg / "service.log"
        self.assertTrue(log_path.exists())

        # service status human output
        res_status = self.run_cli("service", "status")
        self.assertEqual(res_status.returncode, 0, res_status.stderr)
        self.assertIn("Sentinel service: running", res_status.stdout)
        self.assertIn(f"PID: {sj['pid']}", res_status.stdout)
        self.assertIn(f"Port: {port}", res_status.stdout)
        self.assertIn(str(log_path), res_status.stdout)

        # service status --json
        res_json = self.run_cli("service", "status", "--json")
        self.assertEqual(res_json.returncode, 0, res_json.stderr)
        st = json.loads(res_json.stdout)
        self.assertTrue(st["running"])
        self.assertEqual(st["pid"], sj["pid"])
        self.assertEqual(st["port"], port)
        self.assertIsNotNone(st["uptime"])
        self.assertGreaterEqual(st["projects_count"], 1)
        self.assertEqual(st["log_path"], str(log_path))

        # Port answers HTTP
        client = Http(port, sj["token"]).login()
        r = client.get("/api/v1/runtime")
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json["pid"], sj["pid"])

        # Stop via alias: sentinel stop
        res_stop = self.run_cli("stop")
        self.assertEqual(res_stop.returncode, 0, res_stop.stderr)
        self.assertIn(f"Sentinel service stopped (pid {sj['pid']})", res_stop.stdout)
        self.assertFalse(sj_path.exists())

        # Status after stop
        res_post = self.run_cli("service", "status", "--json")
        st_post = json.loads(res_post.stdout)
        self.assertFalse(st_post["running"])
        self.assertIsNone(st_post["pid"])
        self.assertIsNone(st_post["port"])

    # ---- 2. start twice is a no-op
    def test_start_twice_is_noop(self):
        port = free_port()
        res1 = self.run_cli("service", "start", "--port", str(port))
        self.assertEqual(res1.returncode, 0, res1.stderr)

        res2 = self.run_cli("service", "start", "--port", str(port))
        self.assertEqual(res2.returncode, 0, res2.stderr)
        self.assertIn("already running", res2.stdout)

    # ---- 3. stop refuses a pid that is not our server
    def test_stop_refuses_non_sentinel_pid(self):
        dummy = subprocess.Popen(["sleep", "60"])
        def cleanup_dummy():
            try:
                dummy.kill()
                dummy.wait()
            except Exception:
                pass
        self.addCleanup(cleanup_dummy)
        self.cfg.mkdir(parents=True, exist_ok=True)
        sj_path = self.cfg / "server.json"
        sj_path.write_text(json.dumps({
            "pid": dummy.pid,
            "port": 54321,
            "token": "0" * 64,
        }))

        res = self.run_cli("service", "stop")
        self.assertEqual(res.returncode, 1)
        self.assertIn("not a Sentinel server", res.stderr)
        # Process was not killed
        self.assertIsNone(dummy.poll())
        # server.json was not removed
        self.assertTrue(sj_path.exists())
        cleanup_dummy()

    # ---- 4. stale server.json cleaned
    def test_stop_cleans_stale_server_json(self):
        self.cfg.mkdir(parents=True, exist_ok=True)
        sj_path = self.cfg / "server.json"
        sj_path.write_text(json.dumps({
            "pid": 9999999,
            "port": 54321,
            "token": "0" * 64,
        }))

        res = self.run_cli("service", "stop")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse(sj_path.exists())
        self.assertIn("Removed stale server.json", res.stdout)

    # ---- 5. dashboard ensures the service and prints a URL (--no-open)
    def test_dashboard_ensures_service_and_prints_url(self):
        port = free_port()
        dash = Dash(self, args=("--no-open", "--port", str(port)), cwd=self.ws, env=self.env, foreground=False)
        code, out = dash.finish(15)
        self.assertEqual(code, 0, out)
        m = re.search(r"http://127\.0\.0\.1:(\d+)/auth\?t=([0-9a-f]{64})", out)
        self.assertIsNotNone(m, out)
        self.assertEqual(int(m.group(1)), port)

        sj_path = self.cfg / "server.json"
        self.assertTrue(sj_path.exists())
        sj = json.loads(sj_path.read_text())
        self.assertEqual(sj["port"], port)

        # Service is running detached
        res_status = self.run_cli("service", "status", "--json")
        st = json.loads(res_status.stdout)
        self.assertTrue(st["running"])
        self.assertEqual(st["pid"], sj["pid"])

    # ---- 6. autostart writes and removes unit file with systemctl mocked
    def test_autostart_linux_writes_and_removes_unit_file(self):
        calls_log = self.root / "systemctl.log"
        # Mock systemctl script
        mock_systemctl = self.bin_dir / "systemctl"
        mock_systemctl.write_text(
            f"#!/bin/sh\n"
            f"echo \"$*\" >> {calls_log}\n"
            f"if [ \"$1\" = \"--user\" ] && [ \"$2\" = \"is-enabled\" ]; then\n"
            f"    echo \"enabled\"\n"
            f"fi\n"
            f"exit 0\n"
        )
        mock_systemctl.chmod(mock_systemctl.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        unit_path = self.home / ".config" / "systemd" / "user" / "sentinel.service"

        # autostart on
        res_on = self.run_cli("service", "autostart", "on")
        self.assertEqual(res_on.returncode, 0, res_on.stderr)
        self.assertTrue(unit_path.exists())
        unit_text = unit_path.read_text()
        self.assertIn("service run", unit_text)
        self.assertIn("ExecStart=", unit_text)
        self.assertIn("Autostart enabled", res_on.stdout)

        # Check systemctl calls
        log_text = calls_log.read_text()
        self.assertIn("--user daemon-reload", log_text)
        self.assertIn("--user enable --now sentinel.service", log_text)

        # autostart status
        res_status = self.run_cli("service", "autostart", "status")
        self.assertEqual(res_status.returncode, 0, res_status.stderr)
        self.assertIn("Autostart: enabled", res_status.stdout)

        # autostart off
        res_off = self.run_cli("service", "autostart", "off")
        self.assertEqual(res_off.returncode, 0, res_off.stderr)
        self.assertFalse(unit_path.exists())
        self.assertIn("Autostart disabled", res_off.stdout)

        log_text2 = calls_log.read_text()
        self.assertIn("--user disable --now sentinel.service", log_text2)

    # ---- 7. autostart with systemctl missing
    def test_autostart_systemctl_missing(self):
        env_no_systemctl = {**self.env, "PATH": "/usr/bin:/bin"}
        # Ensure systemctl is shadowed or not found
        fake_empty_bin = self.root / "empty_bin"
        fake_empty_bin.mkdir()
        env_no_systemctl["PATH"] = str(fake_empty_bin)

        unit_path = self.home / ".config" / "systemd" / "user" / "sentinel.service"

        res_on = self.run_cli("service", "autostart", "on", env=env_no_systemctl)
        self.assertEqual(res_on.returncode, 0, res_on.stderr)
        self.assertTrue(unit_path.exists())
        self.assertIn("systemctl not found", res_on.stdout)
        self.assertIn("systemctl --user daemon-reload", res_on.stdout)

        res_off = self.run_cli("service", "autostart", "off", env=env_no_systemctl)
        self.assertEqual(res_off.returncode, 0, res_off.stderr)
        self.assertFalse(unit_path.exists())

    # ---- 8. autostart non-Linux
    def test_autostart_non_linux(self):
        import service
        with mock.patch("sys.platform", "darwin"):
            buf = []
            with mock.patch("service._say", buf.append):
                code = service.service_autostart("on")
                self.assertEqual(code, 0)
                self.assertTrue(any("Linux-only in Sentinel 2.0" in s for s in buf))

    # ---- 9. restart safety: lost task handled on startup recovery
    def test_restart_safety_lost_task_handled(self):
        from engine import Engine
        import adapters
        import service

        # Set up workspace with a CLI runner configuration
        cfg_custom = {
            **CONFIG,
            "single_model": False,
            "runners": {"fake": {"command": "echo 1"}},
            "agents": {"docs": {"runner": "fake"}},
        }
        (self.ws / "sentinel.config.yaml").write_text(yaml.safe_dump(cfg_custom, sort_keys=False))

        # Set up a project in projects.json
        from apiserver import userdir
        userdir.ensure_dir(self.cfg)
        userdir.register_workspace(self.cfg, self.ws)

        eng = Engine(self.ws / ".sentinel", self.ws, cfg_custom)
        self.addCleanup(eng.close)

        # Create a run and a CLI task
        slug = "task-left-running"
        eng.create_run(slug, "dev")
        tid = eng.create_task(slug, "docs", objective="write docs", repos=["backend"], write=["backend/**"])["id"]
        eng.queue_task(tid)

        # Start the task with a dead pid
        dead = subprocess.Popen(["sleep", "0"])
        dead.wait()
        eng.start_task(tid, pid=dead.pid, pid_started_at=adapters.process_start_time(dead.pid) or "1", schedule=False)
        self.assertEqual(eng.reg.get_row("tasks", tid)["state"], "RUNNING")

        # Run recovery
        service.recover_lost_tasks(self.cfg)

        # Task should now be FAILED with E_EXIT / process lost
        t_after = eng.reg.get_row("tasks", tid)
        self.assertEqual(t_after["state"], "FAILED")
        self.assertEqual(t_after["error_code"], "E_EXIT")
        self.assertEqual(t_after["reason"], "process lost")
