"""`sentinel dashboard`: start the one server of this user, or attach to the one that runs (README point 7, 8)."""
import errno
import os
import signal
import sys
import threading
import time

from paths import ROOT

from . import userdir
from .server import ApiServer

ATTACH_WAIT = 10.0


def _say(text, err=False):
    print(text, file=sys.stderr if err else sys.stdout, flush=True)


def _url(port, token):
    return f"http://127.0.0.1:{port}/auth?t={token}"


def _version():
    return (ROOT / "VERSION").read_text().strip()


def run_dashboard(workspace, port=None, no_open=False):
    """Returns the exit code: 0 after attaching or a clean stop, 1 for a start failure."""
    cfgdir = userdir.config_dir()
    for notice in userdir.ensure_dir(cfgdir):
        _say(notice)
    try:
        userdir.load_projects(cfgdir)
    except userdir.ProjectsFileError as e:
        _say(str(e), err=True)
        return 1
    lock = userdir.ServerLock(cfgdir)
    deadline = time.time() + ATTACH_WAIT
    while True:
        if lock.acquire():
            try:
                return _serve(cfgdir, lock, workspace, port, no_open)
            finally:
                lock.release()
        info = userdir.read_server_json(cfgdir)
        if info:
            return _attach(cfgdir, info, workspace)
        if time.time() > deadline:
            _say("another Sentinel server holds the lock but has not published server.json; try again", err=True)
            return 1
        time.sleep(0.1)


def _register(cfgdir, workspace):
    if workspace is not None:
        entry, created = userdir.register_workspace(cfgdir, workspace)
        _say(f"project {entry['id']} {'registered' if created else 'already registered'} ({entry['path']})")


def _attach(cfgdir, info, workspace):
    _register(cfgdir, workspace)
    _say(f"Sentinel dashboard is running (pid {info['pid']}): {_url(info['port'], info['token'])}")
    return 0


def _serve(cfgdir, lock, workspace, port, no_open):
    path = cfgdir / userdir.SERVER
    if path.exists():
        path.unlink()
        _say("a stale server.json was replaced")
    _register(cfgdir, workspace)
    server = ApiServer(cfgdir, port=port or 0, dispatch=True, log_sink=lambda line: _say(line, err=True))
    try:
        server.start()
    except OSError as e:
        if e.errno == errno.EADDRINUSE and port:
            _say(f"port {port} is in use", err=True)
        else:
            _say(f"cannot start the server: {e}", err=True)
        return 1
    userdir.write_server_json(cfgdir, {"pid": os.getpid(), "port": server.port, "token": server.token,
                                       "started_at": server.started_at, "version": _version()})
    url = _url(server.port, server.token)
    _say(f"Sentinel dashboard: {url}")
    _say("Running in the foreground. Press Ctrl-C to stop.")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    if not no_open:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        while not stop.wait(0.2):
            pass
    finally:
        server.stop()
        userdir.remove_server_json(cfgdir, os.getpid())
    return 0
