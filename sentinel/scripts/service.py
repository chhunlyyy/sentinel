"""Background service management for Sentinel 2.0 (plan/v2-factory.md Decision 2, W2)."""
import errno
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import adapters
import factory
from errors import SentinelError
from paths import ROOT
from apiserver import lifecycle, userdir

SENTINEL_PY = (Path(__file__).resolve().parent / "sentinel.py").resolve()
WAIT_START = 15.0
WAIT_STOP = 10.0


def _say(text, err=False):
    print(text, file=sys.stderr if err else sys.stdout, flush=True)


def _port_answers(port, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _is_sentinel_process(pid):
    cmd_path = Path(f"/proc/{pid}/cmdline")
    if not cmd_path.exists():
        return True
    try:
        raw = cmd_path.read_bytes()
        args = [a.decode(errors="replace") for a in raw.split(b"\0") if a]
        has_sentinel = any(
            a.endswith("sentinel") or a.endswith("sentinel.py") or "sentinel" in Path(a).name
            for a in args
        )
        has_server_cmd = any(c in args for c in ("dashboard", "run", "service"))
        return has_sentinel and has_server_cmd
    except OSError:
        return False


def recover_lost_tasks(cfgdir):
    """Restart safety: recover tasks left RUNNING by a previous server whose process is gone."""
    from apiserver.projects import ProjectSet
    from apiserver.manage import live_runs
    projects = ProjectSet(cfgdir)
    for project in projects.list():
        try:
            status, _ = projects.probe(project)
            if status != "available":
                continue
            with projects.engine(project) as eng:
                slugs = set(live_runs(eng))
                for t in eng.reg.rows("tasks", state="RUNNING"):
                    r = eng.reg.get_run_by_id(t["run_id"])
                    if r:
                        slugs.add(r["slug"])
                for slug in slugs:
                    try:
                        eng._recover(slug)
                    except SentinelError as err:
                        if err.code != "E_TRANSITION":  # E_TRANSITION: another process finished it first
                            _say(f"recovery of {project.id}/{slug} failed: {err}", err=True)
        except Exception as e:  # noqa: BLE001 - start-up must not fail because one project cannot be recovered
            _say(f"recovery of project {getattr(project, 'id', '?')} failed: {type(e).__name__}: {e}", err=True)


def service_run(workspace=None, port=None, bind=None, public_host=None, allow_peers=(), orchestrator=None):
    """Run the foreground server (what run_dashboard does today, minus opening a browser)."""
    return lifecycle.run_dashboard(
        workspace,
        port=port,
        no_open=True,
        bind=bind,
        public_host=public_host,
        allow_peers=allow_peers,
        orchestrator=orchestrator,
    )


def service_start(workspace=None, port=None, bind=None, public_host=None, allow_peers=(), orchestrator=None, quiet=False):
    """Start service run detached. Waits until server.json shows new pid and port answers."""
    cfgdir = userdir.config_dir()
    for notice in userdir.ensure_dir(cfgdir):
        if not quiet:
            _say(notice)
    try:
        userdir.load_projects(cfgdir)
    except userdir.ProjectsFileError as e:
        _say(str(e), err=True)
        return 1

    info = userdir.read_server_json(cfgdir)
    if info:
        pid = info["pid"]
        started = info.get("pid_started_at")
        if adapters.process_alive(pid, started) and _port_answers(info["port"]):
            if not quiet:
                _say(f"Sentinel service is already running (pid {pid}, port {info['port']})")
            return 0
        else:
            userdir.remove_server_json(cfgdir, pid)

    log_path = cfgdir / "service.log"
    fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with open(fd, "a", encoding="utf-8") as log_f:
        cmd = [sys.executable, str(SENTINEL_PY)]
        if workspace:
            cmd.extend(["--dir", str(workspace)])
        cmd.extend(["service", "run"])
        if port:
            cmd.extend(["--port", str(port)])
        if bind:
            cmd.extend(["--bind", str(bind)])
        if public_host:
            cmd.extend(["--public-host", str(public_host)])
        for peer in allow_peers:
            cmd.extend(["--allow-peer", str(peer)])
        if orchestrator:
            cmd.append(orchestrator)

        proc = subprocess.Popen(
            cmd,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
        )

    deadline = time.time() + WAIT_START
    started_info = None
    while time.time() < deadline:
        if proc.poll() is not None:
            _say(f"Sentinel service failed to start (exit code {proc.returncode})", err=True)
            _say(f"See log: {log_path}", err=True)
            return 1
        info = userdir.read_server_json(cfgdir)
        if info and info.get("pid") == proc.pid:
            if _port_answers(info["port"]):
                started_info = info
                break
        time.sleep(0.05)

    if not started_info:
        _say("Timed out waiting for Sentinel service to start", err=True)
        return 1

    if not quiet:
        _say(f"Sentinel service started (pid {started_info['pid']}, port {started_info['port']})")
        _say(f"Log: {log_path}")
    return 0


def service_stop(cfgdir=None):
    """Stop the running service via SIGTERM, then SIGKILL. Removes stale server.json."""
    cfgdir = Path(cfgdir) if cfgdir else userdir.config_dir()
    server_json = cfgdir / userdir.SERVER
    if not server_json.exists():
        _say("Sentinel service is not running")
        return 0

    info = userdir.read_server_json(cfgdir)
    if not info:
        server_json.unlink(missing_ok=True)
        _say("Removed stale server.json")
        return 0

    pid = info["pid"]
    started = info.get("pid_started_at")

    if not adapters.process_alive(pid, started):
        server_json.unlink(missing_ok=True)
        _say(f"Removed stale server.json (process {pid} is not running)")
        return 0

    if not _is_sentinel_process(pid):
        _say(f"Refusing to stop pid {pid}: process is not a Sentinel server", err=True)
        return 1

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        server_json.unlink(missing_ok=True)
        _say(f"Removed stale server.json (process {pid} is not running)")
        return 0
    except PermissionError:
        _say(f"Permission denied stopping process {pid}", err=True)
        return 1

    deadline = time.time() + WAIT_STOP
    while time.time() < deadline:
        if not adapters.process_alive(pid):
            break
        time.sleep(0.05)

    if adapters.process_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        time.sleep(0.1)

    server_json.unlink(missing_ok=True)
    lifecycle.remove_redirect(cfgdir)
    _say(f"Sentinel service stopped (pid {pid})")
    return 0


def service_status(as_json=False, cfgdir=None):
    """Print service status (running or not, pid, port, uptime, registered projects count, log path)."""
    cfgdir = Path(cfgdir) if cfgdir else userdir.config_dir()
    log_path = cfgdir / "service.log"
    info = userdir.read_server_json(cfgdir)
    running = False
    pid = None
    port = None
    uptime = None

    if info:
        pid_cand = info["pid"]
        started = info.get("pid_started_at")
        if adapters.process_alive(pid_cand, started) and _port_answers(info["port"]):
            running = True
            pid = pid_cand
            port = info["port"]
            started_iso = info.get("started_at")
            if started_iso:
                try:
                    t0 = datetime.fromisoformat(started_iso.replace("Z", "+00:00")).timestamp()
                    uptime = max(0.0, time.time() - t0)
                except Exception:
                    pass

    projects_data = userdir.load_projects(cfgdir)
    projects_count = len(projects_data.get("projects", []))
    paused = factory.pause_state(cfgdir)["paused"]

    if as_json:
        data = {
            "running": running,
            "pid": pid,
            "port": port,
            "uptime": round(uptime, 1) if uptime is not None else None,
            "projects_count": projects_count,
            "factory_paused": paused,
            "log_path": str(log_path),
        }
        print(json.dumps(data, indent=2))
    else:
        if running:
            uptime_str = f"{int(uptime)}s" if uptime is not None else "unknown"
            _say("Sentinel service: running")
            _say(f"  PID: {pid}")
            _say(f"  Port: {port}")
            _say(f"  Uptime: {uptime_str}")
            _say(f"  Registered projects: {projects_count}")
            _say(f"  Log: {log_path}")
        else:
            _say("Sentinel service: not running")
            _say(f"  Registered projects: {projects_count}")
            _say(f"  Log: {log_path}")
        _say(f"  Factory: {'paused (nothing new starts)' if paused else 'running'}")
    return 0


def factory_pause(paused, user, comment=None, cfgdir=None):
    """`sentinel service pause|resume`: the same whole-factory switch as the dashboard button."""
    cfgdir = Path(cfgdir) if cfgdir else userdir.config_dir()
    state = factory.pause_state(cfgdir)["paused"]
    factory.set_paused(cfgdir, paused, user, "cli", (comment or "").strip() or None)
    word = "paused" if paused else "running"
    _say(f"factory already {word}" if state == paused else
         f"factory {word}: " + ("nothing new starts; running tasks finish" if paused else "agents start again"))
    return 0


def service_autostart(action):
    """Manage autostart: systemd user unit on Linux; Linux-only in 2.0 for other OS."""
    if not sys.platform.startswith("linux"):
        _say("Autostart is Linux-only in Sentinel 2.0")
        return 0

    env = os.environ
    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path(env.get("HOME") or Path.home()) / ".config"
    systemd_dir = base / "systemd" / "user"
    unit_path = systemd_dir / "sentinel.service"
    systemctl_bin = shutil.which("systemctl")

    if action == "on":
        systemd_dir.mkdir(parents=True, exist_ok=True)
        exec_cmd = f"{sys.executable} {SENTINEL_PY} service run"
        unit_content = (
            "[Unit]\n"
            "Description=Sentinel Factory Service\n"
            "After=network.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={exec_cmd}\n"
            "Restart=on-failure\n"
            "RestartSec=5\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )
        unit_path.write_text(unit_content, encoding="utf-8")
        if systemctl_bin:
            try:
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
                subprocess.run(["systemctl", "--user", "enable", "--now", "sentinel.service"], check=True)
                _say(f"Autostart enabled: {unit_path}")
            except subprocess.CalledProcessError as e:
                _say(f"Failed to enable service with systemctl: {e}", err=True)
                return 1
        else:
            _say("systemctl not found; unit written. Run these commands manually:")
            _say("  systemctl --user daemon-reload")
            _say("  systemctl --user enable --now sentinel.service")
        return 0

    elif action == "off":
        if systemctl_bin:
            try:
                subprocess.run(["systemctl", "--user", "disable", "--now", "sentinel.service"], check=False)
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
            except Exception:
                pass
        else:
            _say("systemctl not found; run these commands manually if needed:")
            _say("  systemctl --user disable --now sentinel.service")
            _say("  systemctl --user daemon-reload")

        if unit_path.exists():
            unit_path.unlink()
            _say(f"Autostart disabled: removed {unit_path}")
        else:
            _say("Autostart is already disabled")
        return 0

    elif action == "status":
        if not unit_path.exists():
            _say("Autostart: disabled")
            return 0
        if systemctl_bin:
            res = subprocess.run(["systemctl", "--user", "is-enabled", "sentinel.service"], capture_output=True, text=True)
            state = res.stdout.strip() or "unknown"
            _say(f"Autostart: {state} ({unit_path})")
        else:
            _say(f"Autostart: enabled ({unit_path})")
        return 0


def dashboard_ensure_and_open(workspace, port=None, no_open=False, bind=None, public_host=None, allow_peers=(), orchestrator=None):
    """Ensure Sentinel service is running, print session URL, open browser."""
    cfgdir = userdir.config_dir()
    for notice in userdir.ensure_dir(cfgdir):
        _say(notice)
    try:
        userdir.load_projects(cfgdir)
    except userdir.ProjectsFileError as e:
        _say(str(e), err=True)
        return 1

    if workspace is not None:
        entry, created = userdir.register_workspace(cfgdir, workspace)
        _say(f"project {entry['id']} {'registered' if created else 'already registered'} ({entry['path']})")

    info = userdir.read_server_json(cfgdir)
    running = False
    if info:
        pid = info["pid"]
        started = info.get("pid_started_at")
        if adapters.process_alive(pid, started) and _port_answers(info["port"]):
            running = True
        else:
            userdir.remove_server_json(cfgdir, pid)
            info = None

    if not running:
        res = service_start(
            workspace=workspace,
            port=port,
            bind=bind,
            public_host=public_host,
            allow_peers=allow_peers,
            orchestrator=orchestrator,
            quiet=True,
        )
        if res != 0:
            return res
        info = userdir.read_server_json(cfgdir)
        if not info:
            _say("service started but server.json not found", err=True)
            return 1
    elif orchestrator:
        _say("the orchestrator is changed in the running dashboard (Settings > Providers)")

    url = lifecycle._url(info["port"], info["token"], public_host)
    _say(f"Sentinel dashboard: {url}")

    if not no_open:
        try:
            lifecycle.open_browser(cfgdir, info["port"], info["token"])
        except Exception:
            pass

    return 0
