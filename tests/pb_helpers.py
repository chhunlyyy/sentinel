"""Shared fixtures for Phase B part 2 tests (engine level and CLI level)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from engine import Engine  # noqa: E402
from test_artifacts import DOCS, FULL, LITE, feat, make_spec  # noqa: E402

CONFIG = {"version": 1, "state": {"dir": ".sentinel", "shared_mode": "local"}, "repos": []}
SLUG = "leave-balance"
GOOD = {"balance.feature": feat([("@AC-1 @unit @P1", "a")]),
        "request_form.feature": feat([("@AC-2 @integration @P1", "b")], feature_tags="@REQ-2")}


def spec_text(slug=SLUG, tier=1, version=1, typ="feature", **kw):
    if typ == "docs":
        return make_spec(DOCS, slug=slug, tier=tier, version=version, **kw)
    return make_spec(LITE if tier <= 2 else FULL, slug=slug, tier=tier, version=version, **kw)


class PB(unittest.TestCase):
    config = CONFIG

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.released = []
        self.eng = Engine(self.ws / ".sentinel", self.ws, self.config, release_lock=self.released.append)
        self.addCleanup(self.eng.close)

    # ---- paths and files
    def sdir(self, slug=SLUG):
        return self.ws / ".sentinel" / "shared" / "specs" / slug

    def write_spec(self, text=None, slug=SLUG, **kw):
        p = self.sdir(slug) / "spec.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text if text is not None else spec_text(slug, **kw))
        return p

    def write_features(self, files=None, slug=SLUG):
        for name, text in (files or GOOD).items():
            p = self.sdir(slug) / "features" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    # ---- run fixtures
    def mk(self, slug=SLUG, state="PLANNED", tier=1, typ="feature"):
        self.eng.create_run(slug, "orchestrator", type=typ, baseline={"backend": "abc"})
        self.eng.reg.update_run(slug, state=state, tier=tier, initial_tier=tier)
        return slug

    def run_row(self, slug=SLUG):
        return self.eng.reg.get_run(slug)

    def state(self, slug=SLUG):
        return self.run_row(slug)["state"]

    def events(self, type, slug=SLUG):
        return self.eng.reg.list_events(self.run_row(slug)["id"], type)

    def rules(self, slug=SLUG):
        return [e["payload"]["transition"] for e in self.events("run.state_changed", slug)]

    def approvals(self, gate=None, slug=SLUG):
        rid = self.run_row(slug)["id"]
        rows = self.eng.reg.rows("approvals", run_id=rid)
        return [r for r in rows if gate in (None, r["gate"])]

    def artifacts(self, kind=None, slug=SLUG):
        rid = self.run_row(slug)["id"]
        return [r for r in self.eng.reg.rows("artifacts", run_id=rid) if kind in (None, r["kind"])]

    def audit(self, action=None):
        return [r for r in self.eng.reg.audit_rows() if action in (None, r["action"])]

    def hash_prefix(self, gate, slug=SLUG):
        return self.eng.pending_approval(slug, gate)["sha256"][:8]

    def approve(self, gate, slug=SLUG, decision="approve", comment=None):
        info = self.eng.pending_approval(slug, gate)
        return self.eng.decide(slug, gate, decision, "human", prefix=info["sha256"][:8], comment=comment,
                               approver="dev", approver_name="Dev User")

    # ---- flow helpers
    def to_spec_review(self, slug=SLUG, tier=1, typ="feature", text=None):
        self.mk(slug, "PLANNED", tier, typ)
        self.write_spec(text, slug=slug, tier=tier, typ=typ)
        res = self.eng.task_completed(slug, "specifier")
        assert res["accepted"], res
        return slug

    def to_spec_approved(self, slug=SLUG, tier=1, typ="feature"):
        self.to_spec_review(slug, tier, typ)
        self.approve("spec", slug)
        return slug

    def to_gherkin_review(self, slug=SLUG, tier=1, files=None):
        self.to_spec_approved(slug, tier)
        self.write_features(files, slug=slug)
        res = self.eng.task_completed(slug, "test_designer")
        assert res["accepted"], res
        return slug

    def to_gherkin_approved(self, slug=SLUG, tier=1):
        self.to_gherkin_review(slug, tier)
        self.approve("gherkin", slug)
        return slug


# ---------------------------------------------------------------- CLI drivers
import pty  # noqa: E402
import select  # noqa: E402
import subprocess  # noqa: E402

CLI = [sys.executable, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts" / "sentinel.py")]
PROMPT = "first 8 characters"
CLI_ENV = {**os.environ, "GIT_AUTHOR_NAME": "Dev User", "GIT_AUTHOR_EMAIL": "d@example.com",
           "GIT_COMMITTER_NAME": "Dev User", "GIT_COMMITTER_EMAIL": "d@example.com"}


class PtyProc:
    """A sentinel command attached to a pseudo-terminal (stdin and stdout are a tty)."""

    def __init__(self, args, env=None):
        self.out = b""
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe(CLI[0], CLI + list(args), env or CLI_ENV)
        self.code = None

    def _pump(self, timeout):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if r:
            try:
                data = os.read(self.fd, 4096)
            except OSError:
                data = b""
            if not data:
                return False
            self.out += data
        return True

    def wait_for(self, text, timeout=15):
        end = time.time() + timeout
        while text.encode() not in self.out and time.time() < end:
            if not self._pump(0.1):
                break
        return text.encode() in self.out

    def send(self, text):
        os.write(self.fd, text.encode())

    def eof(self):
        os.write(self.fd, b"\x04")

    def finish(self, timeout=15):
        end = time.time() + timeout
        while time.time() < end and self._pump(0.1):
            pass
        _, status = os.waitpid(self.pid, 0)
        self.code = os.waitstatus_to_exitcode(status)
        try:
            os.close(self.fd)
        except OSError:
            pass
        return self.code, self.out.decode(errors="replace").replace("\r\n", "\n")


import time  # noqa: E402


def run_tty(args, typed=(), on_prompt=None, eof=False):
    """Run a command on a pty, answer the hash prompt with `typed` lines."""
    p = PtyProc(args)
    if p.wait_for(PROMPT, 10):
        if on_prompt:
            on_prompt()
        if eof:
            p.eof()
        else:
            for t in typed:
                p.send(t + "\n")
    return p.finish()


def run_plain(args, stdin=subprocess.DEVNULL):
    r = subprocess.run(CLI + list(args), stdin=stdin, capture_output=True, text=True, env=CLI_ENV)
    return r.returncode, r.stdout + r.stderr


class CLIBase(PB):
    def setUp(self):
        super().setUp()
        (self.ws / "sentinel.config.yaml").write_text("version: 1\nstate:\n  dir: .sentinel\n  shared_mode: local\nrepos: []\n")
        self.d = ["--dir", str(self.ws)]

    def cli(self, *args):
        return run_plain(self.d + list(args))

    def tty(self, *args, typed=(), **kw):
        return run_tty(self.d + list(args), typed, **kw)
