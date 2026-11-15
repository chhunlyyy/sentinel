"""Token, session cookie and CSRF value. Every comparison is hmac.compare_digest on bytes."""
import hmac
import secrets
import threading
import time

COOKIE = "sentinel_session"
CSRF_HEADER = "X-Sentinel-CSRF"
MAX_SESSIONS = 32
IDLE_SECONDS = 12 * 3600


def new_token():
    return secrets.token_hex(32)


def same(supplied, expected):
    """Constant-time equality of two strings (compared as UTF-8 bytes)."""
    if not isinstance(supplied, str) or not isinstance(expected, str):
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def parse_cookie(header):
    """The value of the session cookie in a Cookie header, or None."""
    for part in (header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name == COOKIE:
            return value
    return None


class Sessions:
    """The start token and the sessions made from it. Everything lives in memory: a restart ends every session."""

    def __init__(self, token):
        self.token = token
        self._sessions = {}
        self._lock = threading.Lock()

    def check_token(self, supplied):
        return same(supplied, self.token)

    def _expire(self, now):
        for session in [k for k, (_, seen) in self._sessions.items() if now - seen > IDLE_SECONDS]:
            del self._sessions[session]

    def create(self):
        session, csrf = secrets.token_hex(32), secrets.token_hex(32)
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            while len(self._sessions) >= MAX_SESSIONS:
                del self._sessions[next(iter(self._sessions))]  # the oldest (dicts keep insertion order)
            self._sessions[session] = (csrf, now)
        return session, csrf

    def lookup(self, cookie_value):
        """The CSRF value of a valid session cookie, else None. A session unused for 12 hours has ended."""
        found = None
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            for session, (csrf, _) in self._sessions.items():
                if same(cookie_value, session):
                    found = (session, csrf)
            if found:
                self._sessions[found[0]] = (found[1], now)
        return found[1] if found else None

    def check_csrf(self, session_csrf, supplied):
        return same(supplied, session_csrf)

    def clear(self):
        with self._lock:
            self._sessions.clear()
