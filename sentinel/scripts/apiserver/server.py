"""The HTTP layer: checks in a fixed order (Host, Origin, session cookie, route, CSRF, body), then the route handler.

Standard library only. The server binds 127.0.0.1 and nothing else; there is no option, environment variable or
configuration key that changes that.
"""
import getpass
import json
import mimetypes
import os
import queue
import re
import select
import socket
import socketserver
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote

from errors import SentinelError
from paths import ROOT

from . import auth, routes
from .dispatch import Dispatcher
from .projects import ProjectSet, scrub_obj
from .status import HttpError, INTERNAL_MESSAGE, envelope, status_for
from .stream import Hub, resync

BIND = "127.0.0.1"
MAX_BODY = 1024 * 1024
DRAIN_LIMIT = 16 * 1024 * 1024
CSP = "default-src 'self'; frame-ancestors 'none'"
LAST_EVENT = re.compile(r"([^:\s]+):(\d+)")
SECRET_QUERY = re.compile(r"(?i)([?&](?:t|token)=)[^&\s]*")

PLACEHOLDER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Sentinel</title></head>
<body><h1>Sentinel local API</h1>
<p>The dashboard UI is not installed in this build (UI not installed).</p>
<p>The API is served under <code>/api/v1</code>.</p></body></html>
"""


def setting(value, env_name, default):
    """A tuning value: the argument, else (only with SENTINEL_TEST_MODE=1) the environment in milliseconds, else the default."""
    if value is not None:
        return value
    if os.environ.get("SENTINEL_TEST_MODE") == "1" and os.environ.get(env_name):
        try:
            return float(os.environ[env_name]) / 1000.0
        except ValueError:
            pass
    return default


def identity():
    """(OS user, git user.name or None) of the process running the server."""
    name = None
    try:
        out = subprocess.run(["git", "var", "GIT_AUTHOR_IDENT"], capture_output=True, text=True, timeout=10).stdout
        name = out.rsplit(" <", 1)[0].strip() or None if " <" in out else None
    except (OSError, subprocess.SubprocessError):
        pass
    return getpass.getuser(), name


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)  # no getfqdn(): the server makes no name lookups
        host, port = self.server_address[:2]
        self.server_name, self.server_port = host, port

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError, socket.timeout)):
            return
        self.api.log("server error:\n" + traceback.format_exc())


class ApiServer:
    def __init__(self, cfgdir, port=0, user=None, git_name=None, poll_interval=None, heartbeat=None,
                 slow_timeout=None, dispatch=False, dispatch_interval=None, dist_dir=None, token=None, log_sink=None):
        self.cfgdir = Path(cfgdir)
        self.requested_port = port
        self.user, self.git_name = (user, git_name) if user else identity()
        if user and git_name is None:
            self.git_name = identity()[1]
        self.poll_interval = setting(poll_interval, "SENTINEL_TEST_POLL_MS", 0.5)
        self.heartbeat = setting(heartbeat, "SENTINEL_TEST_HEARTBEAT_MS", 15.0)
        self.slow_timeout = setting(slow_timeout, "SENTINEL_TEST_SLOW_CLIENT_MS", 10.0)
        self.dispatch_enabled = dispatch
        self.dispatch_interval = setting(dispatch_interval, "SENTINEL_TEST_DISPATCH_MS", 0.5)
        dist = Path(dist_dir) if dist_dir else ROOT / "dashboard_dist"
        self.dist = dist if (dist / "index.html").is_file() else None
        self.token = token or auth.new_token()
        self.log_sink = log_sink
        self.pid = os.getpid()
        self.started_at = None
        self.port = None
        self.stopping = threading.Event()
        self.httpd = self.thread = self.hub = self.dispatcher = None
        self.sessions = auth.Sessions(self.token)
        self.projects = ProjectSet(self.cfgdir)

    # ---- lifecycle
    def log(self, message):
        sink = self.log_sink
        if sink:
            sink(message)

    def start(self):
        self.httpd = _HTTPServer((BIND, self.requested_port), Handler)
        self.httpd.api = self
        self.port = self.httpd.server_address[1]
        self.started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.hub = Hub(self.projects, self.poll_interval, self.log)
        self.hub.start()
        if self.dispatch_enabled:
            self.dispatcher = Dispatcher(self.projects, self.dispatch_interval, self.log)
            self.dispatcher.start()
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.1},
                                       name="sentinel-http", daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.httpd is None:
            return
        self.stopping.set()
        if self.hub:
            self.hub.stop()
        deadline = time.time() + 3
        while self.hub and self.hub.count() and time.time() < deadline:
            time.sleep(0.02)
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread:
            self.thread.join(5)
        if self.dispatcher:
            self.dispatcher.stop()
        self.sessions.clear()
        self.httpd = None

    def stream_count(self):
        return self.hub.count() if self.hub else 0

    def dispatch_once(self):
        return (self.dispatcher or Dispatcher(self.projects, self.dispatch_interval, self.log)).once()

    # ---- checks
    def host_ok(self, host):
        return bool(host) and host.lower() in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def origin_ok(self, origin):
        return origin.lower() in (f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "sentinel"
    sys_version = ""
    timeout = 30

    @property
    def api(self):
        return self.server.api

    # ---- logging (paths and statuses only; secrets in a query are hidden)
    def log_message(self, format, *args):
        pass

    def log_request(self, code="-", size="-"):
        shown = SECRET_QUERY.sub(lambda m: m.group(1) + "REDACTED", self.path)
        self.api.log(f"{self.command} {shown} {code}")

    def log_error(self, format, *args):
        self.api.log("request error: " + (format % args))

    # ---- responses
    def _headers(self, status, ctype, length, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _json(self, status, obj, extra=None):
        body = json.dumps(obj).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body), {"Cache-Control": "no-store", **(extra or {})})
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, status, code, message, details=None, extra=None):
        self._json(status, envelope(code, message, details), extra)

    def _page(self, status, body, ctype):
        self._headers(status, ctype, len(body))
        self.wfile.write(body)

    # ---- dispatch
    def _dispatch(self):
        self.ctx = None
        self.close_connection = True
        try:
            self._handle()
        except HttpError as e:
            self._error(e.status, e.code, e.message, e.details, e.headers)
        except SentinelError as e:
            scrubber = self._scrubber()
            self._error(status_for(e.code), e.code, scrubber.scrub_text(e.message), scrub_obj(scrubber, e.details))
        except (BrokenPipeError, ConnectionResetError, TimeoutError, socket.timeout):
            pass
        except Exception:
            self.api.log("unexpected error:\n" + traceback.format_exc())
            try:
                self._error(500, "E_INTERNAL", INTERNAL_MESSAGE)
            except OSError:
                pass

    def _scrubber(self):
        ctx = self.ctx
        if ctx is not None and ctx.project is not None:
            return self.api.projects.scrubber(ctx.project)
        return self.api.projects.plain_scrubber()

    def _handle(self):
        api = self.api
        if not api.host_ok(self.headers.get("Host")):
            raise HttpError("E_HOST", "the Host header must be 127.0.0.1 or localhost with this server's port")
        origin = self.headers.get("Origin")
        if origin is not None and not api.origin_ok(origin):
            raise HttpError("E_ORIGIN", "the Origin header does not match this server")
        method = self.command
        if method in ("OPTIONS", "TRACE", "CONNECT", "HEAD"):
            raise HttpError("E_METHOD", f"{method} is not supported", headers={"Allow": "GET, POST"})
        path, _, query_text = self.path.partition("?")
        query_text = query_text.partition("#")[0]
        if path == "/auth":
            return self._auth(query_text)
        csrf = api.sessions.lookup(auth.parse_cookie(self.headers.get("Cookie")))
        if csrf is None:
            raise HttpError("E_AUTH", "a session cookie is needed; open the URL printed by `sentinel dashboard`")
        query = {k: v[0] for k, v in parse_qs(query_text, keep_blank_values=True).items()}
        if not path.startswith("/api/"):
            return self._static(path)
        route, params = routes.match(method, path)
        body = None
        if method == "POST":
            if not api.sessions.check_csrf(csrf, self.headers.get(auth.CSRF_HEADER)):
                raise HttpError("E_CSRF", "the X-Sentinel-CSRF header is missing or wrong")
            body = self._body()
        self.ctx = routes.Ctx(api, query, body, csrf, self.headers)
        status, result = route.handler(self.ctx, **params)
        if isinstance(result, routes.StreamRequest):
            return self._stream(result)
        self._json(status, result)

    # ---- auth
    def _auth(self, query_text):
        if self.command != "GET":
            raise HttpError("E_METHOD", "use GET", headers={"Allow": "GET"})
        supplied = parse_qs(query_text, keep_blank_values=True).get("t", [""])[0]
        if not supplied or not self.api.sessions.check_token(supplied):
            raise HttpError("E_AUTH", "the token is wrong; use the URL printed by `sentinel dashboard`")
        session, _ = self.api.sessions.create()
        self._headers(302, "text/plain; charset=utf-8", 0, {
            "Location": "/", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "Set-Cookie": f"{auth.COOKIE}={session}; HttpOnly; SameSite=Strict; Path=/"})

    # ---- body
    def _body(self):
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            raise HttpError("E_VALIDATION", "Content-Length required")
        try:
            length = int(raw_len)
            if length < 0:
                raise ValueError
        except ValueError:
            raise HttpError("E_VALIDATION", "Content-Length is not a number")
        if length > MAX_BODY:
            left = min(length, DRAIN_LIMIT)
            while left > 0:
                chunk = self.rfile.read(min(65536, left))
                if not chunk:
                    break
                left -= len(chunk)
            raise HttpError("E_BODY_TOO_LARGE", f"the body is larger than {MAX_BODY} bytes")
        raw = self.rfile.read(length) if length else b""
        media = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if media != "application/json":
            raise HttpError("E_MEDIA_TYPE", "the body must be application/json")
        try:
            doc = json.loads(raw.decode("utf-8")) if raw.strip() else None
        except (ValueError, UnicodeDecodeError):
            doc = None
        if not isinstance(doc, dict):
            raise HttpError("E_VALIDATION", "the body must be a JSON object")
        return doc

    # ---- static page
    def _static(self, path):
        if self.command != "GET":
            raise HttpError("E_METHOD", "use GET", headers={"Allow": "GET"})
        dist = self.api.dist
        if dist is None:
            if path == "/":
                return self._page(200, PLACEHOLDER.encode("utf-8"), "text/html; charset=utf-8")
            raise HttpError("E_NOT_FOUND", "no such route")
        rel = unquote(path).lstrip("/")
        parts = rel.split("/") if rel else []
        if any(p in ("..", ".") or "\0" in p or "\\" in p for p in parts) or any(p == "" for p in parts):
            raise HttpError("E_NOT_FOUND", "no such file")
        target = (dist / rel) if rel else dist / "index.html"
        try:
            target.resolve().relative_to(dist.resolve())
        except ValueError:
            raise HttpError("E_NOT_FOUND", "no such file")
        if not target.is_file():
            if rel and "." in parts[-1]:
                raise HttpError("E_NOT_FOUND", "no such file")
            target = dist / "index.html"  # single-page app route
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._page(200, target.read_bytes(), ctype)

    # ---- event stream
    def _resume(self, req, sub):
        """Wire messages that come before live events: replay for a Last-Event-ID, or resync messages."""
        api, hub = self.api, self.api.hub
        scope = [p for p in api.projects.list() if req.project in (None, p.id)]
        lei = self.headers.get("Last-Event-ID")
        if not lei:
            return []
        known = {p.id: p for p in api.projects.list()}

        def all_resync(reason, named=None):
            return [resync(p.id, reason if named in (None, p.id) else "reconnected") for p in scope]
        m = LAST_EVENT.fullmatch(lei.strip())
        if not m:
            return all_resync("malformed id")
        pid, n = m.group(1), int(m.group(2))
        if pid not in known or (req.project and pid != req.project):
            return all_resync("unknown project")
        project = known[pid]
        upto = sub.snapshot.get(pid)
        try:
            if upto is None or n > upto or not hub.has_event(project, n):
                return all_resync("unknown event id", pid)
            out = hub.replay(project, n, upto, req.run)
        except (OSError, Exception) as e:
            if isinstance(e, SentinelError):
                raise
            return all_resync("project unavailable", pid)
        out += [resync(p.id, "reconnected") for p in scope if p.id != pid]
        return out

    def _peer_closed(self):
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _write(self, text):
        """Send in chunks: the slow-client timeout then limits each chunk, not a whole replay."""
        data = text.encode("utf-8")
        for i in range(0, len(data), 65536):
            self.wfile.write(data[i:i + 65536])

    def _stream(self, req):
        api = self.api
        sub = api.hub.subscribe(req.project, req.run)
        try:
            initial = self._resume(req, sub)
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 32768)
            self._headers(200, "text/event-stream; charset=utf-8", None,
                          {"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
            self.connection.settimeout(api.slow_timeout)
            if initial:
                self._write("".join(initial))
            last = time.monotonic()
            tick = max(0.02, min(0.2, api.heartbeat / 4))
            while not api.stopping.is_set():
                try:
                    msg = sub.q.get(timeout=tick)
                except queue.Empty:
                    if self._peer_closed():
                        break
                    if time.monotonic() - last >= api.heartbeat:
                        self.wfile.write(b": heartbeat\n\n")
                        last = time.monotonic()
                    continue
                if msg is None:
                    break
                batch = [msg]
                while len(batch) < 200:
                    try:
                        more = sub.q.get_nowait()
                    except queue.Empty:
                        break
                    if more is None:
                        break
                    batch.append(more)
                self._write("".join(batch))
                last = time.monotonic()
        finally:
            api.hub.unsubscribe(sub)


for _method in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "CONNECT"):
    setattr(Handler, f"do_{_method}", lambda self: self._dispatch())
