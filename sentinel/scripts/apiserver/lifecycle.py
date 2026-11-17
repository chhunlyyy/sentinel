"""`sentinel dashboard`: start the one server of this user, or attach to the one that runs (README point 7, 8)."""
import errno
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

from paths import ROOT

from . import userdir
from .server import ApiServer

ATTACH_WAIT = 10.0


def _say(text, err=False):
    print(text, file=sys.stderr if err else sys.stdout, flush=True)


def _url(port, token, host=None):
    return f"http://{host or f'127.0.0.1:{port}'}/auth?t={token}"


REDIRECT = "open.html"


def open_browser(cfgdir, port, token):
    """Open the browser on a private redirect file, so the token never appears in the browser's command line.

    The file lives in the 0700 config folder with mode 0600 and holds the one-time /auth URL. Returns its path.
    """
    path = Path(cfgdir) / REDIRECT
    remove_redirect(cfgdir)
    url = _url(port, token)
    page = ('<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer">'
            f'<meta http-equiv="refresh" content="0;url={url}"><title>Sentinel</title>'
            f'<script>location.replace({json.dumps(url)})</script>')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(page)
    import webbrowser
    webbrowser.open(path.as_uri())
    return path


def remove_redirect(cfgdir):
    path = Path(cfgdir) / REDIRECT
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _version():
    return (ROOT / "VERSION").read_text().strip()


def run_dashboard(workspace, port=None, no_open=False, bind=None, public_host=None, allow_peers=()):
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
                return _serve(cfgdir, lock, workspace, port, no_open, bind, public_host, allow_peers)
            finally:
                lock.release()
        info = userdir.read_server_json(cfgdir)
        if info:
            return _attach(cfgdir, info, workspace, public_host)
        if time.time() > deadline:
            _say("another Sentinel server holds the lock but has not published server.json; try again", err=True)
            return 1
        time.sleep(0.1)


def _register(cfgdir, workspace):
    if workspace is not None:
        entry, created = userdir.register_workspace(cfgdir, workspace)
        _say(f"project {entry['id']} {'registered' if created else 'already registered'} ({entry['path']})")


def _attach(cfgdir, info, workspace, public_host=None):
    _register(cfgdir, workspace)
    _say(f"Sentinel dashboard is running (pid {info['pid']}): {_url(info['port'], info['token'], public_host)}")
    return 0


def _serve(cfgdir, lock, workspace, port, no_open, bind=None, public_host=None, allow_peers=()):
    path = cfgdir / userdir.SERVER
    if path.exists():
        path.unlink()
        _say("a stale server.json was replaced")
    _register(cfgdir, workspace)
    server = ApiServer(cfgdir, port=port or 0, dispatch=True, bind=bind, public_host=public_host, allow_peers=allow_peers, log_sink=lambda line: _say(line, err=True))
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
    url = _url(server.port, server.token, public_host)
    _say(f"Sentinel dashboard: {url}")
    if bind:
        _say(f"publish with -p 127.0.0.1:{server.port}:{server.port}; requests from other addresses are refused")
    _say("Running in the foreground. Press Ctrl-C to stop.")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    if not no_open:
        try:
            open_browser(cfgdir, server.port, server.token)
        except Exception:
            pass
    try:
        while not stop.wait(0.2):
            pass
    finally:
        server.stop()
        remove_redirect(cfgdir)
        userdir.remove_server_json(cfgdir, os.getpid())
    return 0
