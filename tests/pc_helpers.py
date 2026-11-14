"""Shared fixtures for Phase C tests (engine level): git repos, an EXECUTING run, task helpers."""
import json
import os
import re
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from engine import Engine  # noqa: E402
from pb_helpers import PB, SLUG  # noqa: E402

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "d@example.com",
           "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "d@example.com"}
REPOS = [{"id": "backend", "path": "backend", "role": "backend", "profile": "generic"},
         {"id": "frontend", "path": "frontend", "role": "frontend", "profile": "generic"}]
BASE_CONFIG = {"version": 1, "state": {"dir": ".sentinel", "shared_mode": "local"}, "repos": REPOS}


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, env=GIT_ENV, check=True).stdout


class PC(PB):
    config = BASE_CONFIG

    def setUp(self):
        super().setUp()
        self.write_config_file()
        for repo in REPOS:
            path = self.ws / repo["path"]
            path.mkdir()
            git(path, "init", "-q")
            (path / "README.md").write_text("hello\n")
            git(path, "add", "-A")
            git(path, "commit", "-q", "-m", "init")

    def use_config(self, **extra):
        """Replace the engine with one that has `extra` merged into the config. Call before the run exists."""
        self.eng.close()
        self.config = {**BASE_CONFIG, **extra}
        self.eng = Engine(self.ws / ".sentinel", self.ws, self.config, release_lock=self.released.append)
        self.addCleanup(self.eng.close)
        self.write_config_file()
        return self.eng

    def write_config_file(self):
        """The CLI reads sentinel.config.yaml; the engine of the test uses the same content."""
        (self.ws / "sentinel.config.yaml").write_text(yaml.safe_dump(self.config, sort_keys=False))

    def executing(self, slug=SLUG, tier=3):
        self.to_gherkin_approved(slug, tier)
        self.eng.advance(slug)
        assert self.state(slug) == "EXECUTING", self.state(slug)
        return slug

    # ---- task helpers
    def tdir(self, tid, slug=SLUG):
        return self.ws / ".sentinel" / "runs" / slug / "tasks" / tid

    def task(self, tid):
        return self.eng.reg.get_row("tasks", tid)

    def make(self, role="docs", repos=("backend",), write=None, slug=SLUG, **kw):
        kw.setdefault("objective", f"{role} work")
        row = self.eng.create_task(slug, role, repos=list(repos), write=write, **kw)
        return row["id"]

    def running(self, role="docs", repos=("backend",), write=None, slug=SLUG, **kw):
        tid = self.make(role, repos, write, slug, **kw)
        self.eng.queue_task(tid)
        self.eng.start_task(tid)
        return tid

    def write_result(self, tid, content=None, slug=SLUG, **over):
        """content: None -> valid result with `over` merged; str -> raw text; other -> JSON value."""
        path = self.tdir(tid, slug) / "result.json"
        if content is None:
            content = {"schema": "agent-result-v1", "task_id": tid, "status": "completed", "summary": "done", **over}
        path.write_text(content if isinstance(content, str) else json.dumps(content))

    def task_events(self, tid, slug=SLUG):
        return [e for e in self.eng.reg.list_events(self.run_row(slug)["id"]) if e["task_id"] == tid]

    def ev(self, tid, type):
        return [e for e in self.task_events(tid) if e["type"] == type]


# ---------------------------------------------------------------- PC-02: fake runners and CLI drivers
SENTINEL = str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts" / "sentinel.py")
PREAMBLE = """#!{py}
import json, os, re, subprocess, sys, time, signal, pathlib
argv = sys.argv[1:]
stdin_text = sys.stdin.read() if {stdin} else ""
prompt = stdin_text or (argv[-1] if argv else "")
m = re.search(r"Result file \\(absolute path\\): (\\S+)", prompt)
result_path = m.group(1) if m else None
task_id = os.environ.get("SENTINEL_TASK_ID")
def write_result(status="completed", **kw):
    doc = {{"schema": "agent-result-v1", "task_id": task_id, "status": status, "summary": "done"}}
    doc.update(kw)
    pathlib.Path(result_path).write_text(json.dumps(doc))
ws = os.path.dirname(os.getcwd())
def write(path, text="x\\n"):
    p = pathlib.Path(ws) / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
def say(text):
    print(text, flush=True)
"""
STARTED_KEYS = {"role", "repo", "provider", "model", "adapter"}
FINISHED_KEYS = {"state", "error_code", "seconds", "tokens", "reason", "details", "exit_code"}


def alive(pid):
    """True when the process exists and is not a zombie."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def wait_until(fn, timeout=15, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(step)
    return fn()


class PCX(PC):
    """PC with fake CLI runners, a CLI driver and cleanup of every process a test started."""
    BIN = "bin"

    def setUp(self):
        super().setUp()
        (self.ws / self.BIN).mkdir()
        self._procs = []
        self.addCleanup(self._reap)

    # ---- fake runners
    def script(self, name, body, stdin=False):
        """Write a fake runner script; returns its path. `body` sees prompt, result_path, write_result(), write(), say()."""
        path = self.ws / self.BIN / name
        path.write_text(PREAMBLE.format(py=sys.executable, stdin=stdin) + textwrap.dedent(body))
        path.chmod(0o755)
        return str(path)

    def boot(self, runners=None, agents=None, tier=3, policies=None, **cfg):
        """Config with single_model false, fake runners, agents.<role> routes, then an EXECUTING run.
        runners: {name: (body, extra runner fields)}."""
        defs = {}
        for name, (body, fields) in (runners or {}).items():
            defs[name] = {"command": self.script(name, body, stdin=fields.get("input") == "stdin"), **fields}
        extra = {"single_model": False, "runners": defs,
                 "agents": {role: {"runner": r} if isinstance(r, str) else r for role, r in (agents or {}).items()}}
        if policies:
            extra["policies"] = policies
        extra.update(cfg)
        self.use_config(**extra)
        return self.executing(tier=tier)

    def docs_task(self, write=("backend/docs/**",), queue=True, **kw):
        tid = self.make("docs", ["backend"], list(write), **kw)
        if queue:
            self.eng.queue_task(tid)
        return tid

    # ---- CLI
    def env(self, **extra):
        env = {**os.environ, **GIT_ENV, "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("SENTINEL_TASK_ID", None)
        env.update(extra)
        return env

    def popen(self, *args, **env):
        p = subprocess.Popen([sys.executable, SENTINEL, "--dir", str(self.ws), *args], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=self.env(**env))
        self._procs.append(p)
        return p

    def cli(self, *args, timeout=60, **env):
        """(exit code, stdout, stderr)"""
        p = self.popen(*args, **env)
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err

    def finish(self, p, timeout=60):
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err

    def _reap(self):
        for row in self._runner_rows():
            if row["pid"]:
                try:
                    os.killpg(row["pid"], signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        for p in self._procs:
            if p.poll() is None:
                p.kill()
            try:
                p.communicate(timeout=10)
            except Exception:
                pass

    def _runner_rows(self):
        import sqlite3
        db = self.ws / ".sentinel" / "sentinel.db"
        if not db.exists():
            return []
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT pid FROM tasks WHERE pid IS NOT NULL")]
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    # ---- readers
    def row(self, tid):
        return self.task(tid)

    def states(self, role=None, slug=SLUG):
        return [(t["id"], t["state"]) for t in self.eng.reg.rows("tasks", run_id=self.run_row(slug)["id"])
                if role in (None, t["role"])]

    def run_json(self, tid, *extra, **env):
        code, out, err = self.cli("task", "run", tid, *extra, **env)
        return code, out, err

    def next_json(self, slug=SLUG, **env):
        code, out, err = self.cli("next", slug, "--json", **env)
        try:
            return code, json.loads(out), err
        except ValueError:
            return code, None, out + err

    def task_json(self, tid, slug=SLUG):
        return json.loads((self.tdir(tid, slug) / "task.json").read_text())

    def pids(self, path):
        return [int(x) for x in Path(path).read_text().split()]

    def write_pids_script(self, name="fake", pid_file=None, tail="time.sleep(60)", extra=""):
        """A runner that starts a child `sleep 60` and sleeps; both pids go to pid_file."""
        pid_file = pid_file or str(self.ws / "pids.txt")
        return f"""
        child = subprocess.Popen(["sleep", "60"])
        open({pid_file!r}, "w").write(f"{{os.getpid()}} {{child.pid}}")
        {extra}
        {tail}
        """
