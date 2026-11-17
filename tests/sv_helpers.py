"""Shared fixtures for Phase F tests: an in-process API server, an HTTP client with full header control,
an SSE reader, and a pty driver for `sentinel dashboard`."""
import http.client
import json
import os
import pty
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "sentinel" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pc_helpers import BASE_CONFIG, GIT_ENV, PCX, REPOS, git, wait_until  # noqa: E402
from pb_helpers import GOOD, SLUG, spec_text  # noqa: E402
from engine import Engine  # noqa: E402

CONFIG = {**BASE_CONFIG, "shape": "custom"}
SENTINEL = str(SCRIPTS / "sentinel.py")
H2_FAIL = "0" * 64


class Resp:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    @property
    def json(self):
        return json.loads(self.body.decode("utf-8"))

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")

    @property
    def code(self):
        try:
            return self.json["error"]["code"]
        except (ValueError, KeyError, TypeError):
            return None


class Http:
    """One client: holds the session cookie and CSRF value; every request is a new connection."""

    def __init__(self, port, token=None):
        self.port, self.token = port, token
        self.cookie = None
        self.csrf = None

    def req(self, method, path, body=None, headers=None, host=True, cookie=True, csrf=None, ctype="application/json",
            raw=None, origin=None, content_length=True, timeout=20):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            if host is True:
                conn.putheader("Host", f"127.0.0.1:{self.port}")
            elif host:
                conn.putheader("Host", host)
            data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
            if cookie is True and self.cookie:
                conn.putheader("Cookie", f"sentinel_session={self.cookie}")
            elif isinstance(cookie, str):
                conn.putheader("Cookie", cookie)
            if csrf is None and method not in ("GET", "HEAD"):
                csrf = self.csrf
            if csrf:
                conn.putheader("X-Sentinel-CSRF", csrf)
            if origin:
                conn.putheader("Origin", origin)
            if data is not None:
                if ctype:
                    conn.putheader("Content-Type", ctype)
                if content_length:
                    conn.putheader("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                conn.putheader(k, v)
            conn.endheaders()
            if data is not None:
                try:
                    conn.send(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            try:
                r = conn.getresponse()
                return Resp(r.status, {k.lower(): v for k, v in r.getheaders()}, r.read())
            except (ConnectionResetError, BrokenPipeError) as e:
                raise AssertionError(f"connection reset: {e}")
        finally:
            conn.close()

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.req("POST", path, body=body, **kw)

    def login(self, token=None):
        r = self.req("GET", f"/auth?t={token or self.token}", cookie=False)
        assert r.status == 302, (r.status, r.text)
        set_cookie = r.headers["set-cookie"]
        self.cookie = set_cookie.split(";", 1)[0].split("=", 1)[1]
        s = self.req("GET", "/api/v1/session")
        assert s.status == 200, (s.status, s.text)
        self.csrf = s.json["csrf"]
        return self


class Stream:
    """A raw text/event-stream reader on a plain socket (a timed-out read never corrupts it)."""

    def __init__(self, http_client, path="/api/v1/events", last_event_id=None, cookie=True, timeout=10, rcvbuf=None):
        import socket
        self.sock = socket.socket()
        if rcvbuf:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        self.sock.settimeout(timeout)
        self.sock.connect(("127.0.0.1", http_client.port))
        lines = [f"GET {path} HTTP/1.1", f"Host: 127.0.0.1:{http_client.port}"]
        if cookie and http_client.cookie:
            lines.append(f"Cookie: sentinel_session={http_client.cookie}")
        if last_event_id:
            lines.append(f"Last-Event-ID: {last_event_id}")
        self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        self.buf = b""
        head = self._read_until(b"\r\n\r\n", timeout)
        first, _, rest = head.partition(b"\r\n")
        self.status = int(first.split()[1])
        self.headers = {}
        for line in rest.decode("latin-1").split("\r\n"):
            k, _, v = line.partition(":")
            self.headers[k.strip().lower()] = v.strip()
        self.body = b""
        if self.status != 200:
            self.body = self._drain()

    def _read_until(self, marker, timeout):
        """Bytes before `marker` (the marker is consumed), or None when it did not arrive in time."""
        end = time.time() + timeout
        while marker not in self.buf:
            left = end - time.time()
            if left <= 0:
                return None
            self.sock.settimeout(max(0.02, min(0.2, left)))
            try:
                data = self.sock.recv(65536)
            except TimeoutError:
                continue
            except OSError:
                return None
            if not data:
                self.eof = True
                return None
            self.buf += data
        head, _, self.buf = self.buf.partition(marker)
        return head

    def _drain(self):
        out = self.buf
        self.buf = b""
        try:
            while True:
                data = self.sock.recv(65536)
                if not data:
                    break
                out += data
        except OSError:
            pass
        return out

    eof = False

    def messages(self, count, timeout=10, comments=False):
        """Read until `count` event messages (or comments when `comments`) arrived or `timeout` passed."""
        out = []
        end = time.time() + timeout
        while len(out) < count and time.time() < end and not self.eof:
            block = self._read_until(b"\n\n", min(0.3, max(0.02, end - time.time())))
            if block is None:
                continue
            msg = self._parse(block, comments)
            if msg:
                out.append(msg)
        return out

    def _parse(self, block, comments):
        cur = {}
        for line in block.decode("utf-8").split("\n"):
            if not line:
                continue
            if line.startswith(":"):
                if comments:
                    return {"comment": line}
                continue
            key, _, value = line.partition(":")
            cur[key] = value.lstrip(" ")
        return cur

    def closed(self, timeout=5):
        end = time.time() + timeout
        while time.time() < end:
            self.sock.settimeout(0.2)
            try:
                if not self.sock.recv(65536):
                    return True
            except TimeoutError:
                continue
            except OSError:
                return True
        return False

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def ids(messages):
    return [m["id"] for m in messages if "id" in m]


class SV(PCX):
    """Base for server tests: workspace "digital-hr" with a git repo pair, an in-process server."""
    config = CONFIG
    POLL = 0.05

    def setUp(self):
        super().setUp()
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        self.home = Path(self._home.name)
        self.cfgdir = self.home / ".config" / "sentinel"
        patch = mock.patch.dict(os.environ, {**GIT_ENV, "HOME": str(self.home), "USER": "dev", "LOGNAME": "dev",
                                             "SENTINEL_TEST_MODE": "1"})
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("XDG_CONFIG_HOME", None)
        os.environ.pop("SENTINEL_TASK_ID", None)
        self.srv = None
        self.http = None
        self._streams = []
        self._engines = []

    def use_config(self, **extra):
        """PC.use_config with the shape key the server's schema check needs."""
        self.eng.close()
        self.config = {**CONFIG, **extra}
        self.eng = Engine(self.ws / ".sentinel", self.ws, self.config, release_lock=self.released.append)
        self.addCleanup(self.eng.close)
        self.write_config_file()
        return self.eng

    # ---- projects and servers
    def add_project(self, pid="digital-hr", ws=None, name=None):
        from apiserver import userdir
        userdir.ensure_dir(self.cfgdir)
        data = userdir.load_projects(self.cfgdir)
        data["projects"].append({"id": pid, "name": name or pid, "path": str(Path(ws or self.ws).resolve()),
                                 "added_at": "2026-11-14T00:00:00Z"})
        userdir.save_projects(self.cfgdir, data)

    def registered(self):
        from apiserver import userdir
        return userdir.load_projects(self.cfgdir)["projects"] if (self.cfgdir / "projects.json").exists() else []

    def extra_workspace(self, name="payroll", register=True):
        d = Path(tempfile.mkdtemp(prefix=f"{name}-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        (d / "sentinel.config.yaml").write_text(__import__("yaml").safe_dump(self.config, sort_keys=False))
        eng = Engine(d / ".sentinel", d, self.config, release_lock=lambda s: None)
        self.addCleanup(eng.close)
        if register:
            self.add_project(name, d)
        return d, eng

    def tty(self, *args, typed=None):
        """A sentinel command on a pseudo-terminal in this workspace, as the human `dev`."""
        return TtyProc(self, [sys.executable, SENTINEL, "--dir", str(self.ws), *args], env=tty_env(self.home))

    def run_tty(self, args, typed=()):
        p = self.tty(*args)
        if typed and p.wait_for("first 8 characters", 15):
            for t in typed:
                p.send(t + "\n")
        return p.finish(30)

    def serve(self, register=True, **kw):
        from apiserver.server import ApiServer
        if register and not any(p["id"] == "digital-hr" for p in self.registered()):
            self.add_project()
        opts = {"user": "dev", "git_name": "Dev User", "poll_interval": self.POLL, "dispatch": False}
        opts.update(kw)
        self.srv = ApiServer(self.cfgdir, port=0, **opts)
        self.srv.start()
        self.addCleanup(self.srv.stop)
        self.http = Http(self.srv.port, self.srv.token).login()
        return self.http

    def client(self):
        return Http(self.srv.port, self.srv.token).login()

    def stream(self, path="/api/v1/events", client=None, **kw):
        s = Stream(client or self.http, path, **kw)
        self._streams.append(s)
        self.addCleanup(s.close)
        return s

    # ---- run fixtures
    def spec_review(self, slug=SLUG, tier=3):
        self.to_spec_review(slug, tier)
        return self.eng.pending_approval(slug, "spec")["sha256"]

    def body(self, sha, gate="specification", decision="approve", comment=None, confirmation=None, **over):
        b = {"gate": gate, "sha256": sha, "confirmation": confirmation if confirmation is not None else sha[:8],
             "decision": decision}
        if comment is not None:
            b["comment"] = comment
        b.update(over)
        return b

    def db(self, ws=None):
        conn = sqlite3.connect((ws or self.ws) / ".sentinel" / "sentinel.db")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        return conn

    def audit_rows(self, ws=None):
        c = sqlite3.connect((ws or self.ws) / ".sentinel" / "sentinel.db")
        c.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in c.execute("SELECT * FROM audit ORDER BY id")]
        finally:
            c.close()

    def events_rows(self, ws=None, type=None):
        c = sqlite3.connect((ws or self.ws) / ".sentinel" / "sentinel.db")
        c.row_factory = sqlite3.Row
        try:
            sql = "SELECT * FROM events" + (" WHERE type=?" if type else "") + " ORDER BY id"
            return [dict(r) for r in c.execute(sql, [type] if type else [])]
        finally:
            c.close()

    def add_event(self, run_slug, type="task.progress", ws=None, eng=None, payload=None):
        eng = eng or self.eng
        run = eng.reg.get_run(run_slug)
        with eng.reg.transaction():
            return eng.reg.add_event(run["id"], type, "engine", payload or {"elapsed_seconds": 1})


class TtyProc:
    """A command attached to a pseudo-terminal (stdin and stdout are a tty), started without fork() in a threaded process."""

    def __init__(self, test, cmd, env=None, cwd=None):
        self.out = b""
        self.code = None
        master, slave = pty.openpty()
        try:
            self.proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=cwd,
                                         start_new_session=True, close_fds=True)
        finally:
            os.close(slave)
        self.fd = master
        self.pid = self.proc.pid
        test.addCleanup(self.cleanup)

    def pump(self, timeout=0.1):
        if self.fd is None:
            return False
        r, _, _ = select.select([self.fd], [], [], timeout)
        if r:
            try:
                data = os.read(self.fd, 4096)
            except OSError:
                return False
            if not data:
                return False
            self.out += data
        return True

    def exited(self):
        return self.proc.poll() is not None

    def wait_for(self, text, timeout=15):
        end = time.time() + timeout
        while text.encode() not in self.out and time.time() < end:
            if not self.pump(0.1) and self.exited():
                break
        return text.encode() in self.out

    def send(self, text):
        os.write(self.fd, text.encode())

    def eof(self):
        os.write(self.fd, b"\x04")

    def signal(self, sig):
        os.kill(self.pid, sig)

    def text(self):
        return self.out.decode(errors="replace").replace("\r\n", "\n")

    def finish(self, timeout=15):
        """Collect output until exit; (code, text)."""
        end = time.time() + timeout
        while not self.exited() and time.time() < end:
            self.pump(0.05)
        for _ in range(20):
            if not self.pump(0.02):
                break
        if not self.exited():
            raise AssertionError("did not exit: " + self.text())
        self.code = self.proc.returncode
        self._close()
        return self.code, self.text()

    def _close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def cleanup(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self._close()


class Dash(TtyProc):
    """`sentinel dashboard` under a pseudo-terminal (or, with tty=False, with stdin from a pipe)."""

    def __init__(self, test, args=("--no-open",), cwd=None, env=None, tty=True, workspace=None):
        e = {k: v for k, v in os.environ.items() if k not in ("XDG_CONFIG_HOME", "SENTINEL_TASK_ID", "SENTINEL_HOST", "HOST")}
        e.update({"PYTHONDONTWRITEBYTECODE": "1", **(env or {})})
        e = {k: v for k, v in e.items() if v is not None}  # a None value in `env` unsets the variable
        cmd = [sys.executable, SENTINEL, *(["--dir", str(workspace)] if workspace else []), "dashboard", *args]
        if tty:
            super().__init__(test, cmd, env=e, cwd=cwd)
        else:
            self.out, self.code, self.fd = b"", None, None
            self.proc = subprocess.Popen(cmd, cwd=cwd, env=e, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT)
            self.pid = self.proc.pid
            test.addCleanup(self.cleanup)
            test.addCleanup(self.proc.stdin.close)

    def finish(self, timeout=15):
        if self.fd is None and self.proc.stdout is not None:
            try:
                out, _ = self.proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                out, _ = self.proc.communicate()
            self.code = self.proc.returncode
            self.out += out
            return self.code, self.text()
        return super().finish(timeout)

    def _exited(self):
        return self.exited()

    def url(self, timeout=15):
        """(port, token) from the printed auth URL."""
        import re
        end = time.time() + timeout
        while time.time() < end:
            m = re.search(r"http://127\.0\.0\.1:(\d+)/auth\?t=([0-9a-f]{64})", self.text())
            if m:
                return int(m.group(1)), m.group(2)
            if not self.pump(0.1) and self.exited():
                break
        raise AssertionError("no auth URL in output: " + self.text())


def tty_env(home):
    return {**os.environ, **GIT_ENV, "HOME": str(home), "USER": "dev", "LOGNAME": "dev", "PYTHONDONTWRITEBYTECODE": "1"}


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@contextmanager
def fail_next_write():
    """The next registry write transaction of any engine in this process raises a database error."""
    import registry
    orig = registry.Registry.transaction
    state = {"n": 1}

    @contextmanager
    def tx(self):
        if state["n"] > 0:
            state["n"] -= 1
            raise sqlite3.OperationalError("disk I/O error")
        with orig(self):
            yield
    with mock.patch.object(registry.Registry, "transaction", tx):
        yield state
