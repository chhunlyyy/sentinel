"""Q2 dispatch: while the server runs, ready CLI tasks of runs created through the API are started with
`sentinel task run`, the same path as the CLI. Native tasks and every orchestrator step wait for the AI tool.
The engine's own start checks decide, so a race with an orchestrator has one winner.
"""
import subprocess
import sys
import threading
import time

import adapters
from paths import ROOT

SENTINEL = str(ROOT / "scripts" / "sentinel.py")
FINAL = ("COMPLETED", "FAILED", "CANCELLED")

CANDIDATES = ("SELECT t.id FROM tasks t JOIN runs r ON r.id = t.run_id WHERE r.origin = 'dashboard' "
              "AND r.workflow_version = '2' AND r.state NOT IN ('COMPLETED','FAILED','CANCELLED') "
              "AND t.state = 'QUEUED' AND t.adapter = 'cli' ORDER BY t.created_at, t.id")


def _wait_quietly(proc):
    try:
        proc.wait()
    except Exception:
        pass


class Dispatcher:
    def __init__(self, projects, interval=0.5, log=None):
        self.projects = projects
        self.interval = interval
        self.backoff = max(interval * 5, 1.0)
        self.log = log or (lambda msg: None)
        self.children = {}   # task id -> Popen
        self.last = {}       # task id -> time of the last start
        self._stop = threading.Event()
        self._thread = None
        self._once = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="sentinel-dispatch", daemon=True)
        self._thread.start()

    def stop(self):
        """Stop dispatching. Running task processes keep running (they have their own process group); a thread
        waits for each so no zombie is left behind."""
        self._stop.set()
        if self._thread:
            self._thread.join(5)
        for proc in self.children.values():
            if proc.poll() is None:
                threading.Thread(target=_wait_quietly, args=(proc,), daemon=True).start()
        self.children.clear()

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.once()
            except Exception as e:
                self.log(f"dispatch: {type(e).__name__}: {e}")

    def once(self):
        """One pass over every available project. Returns the Popen objects started."""
        started = []
        with self._once:
            for tid in [t for t, p in self.children.items() if p.poll() is not None]:
                self.children.pop(tid)
            for project in self.projects.list():
                if self.projects.probe(project)[0] != "available":
                    continue
                for tid in self._candidates(project):
                    proc = self._spawn(project, tid)
                    if proc:
                        started.append(proc)
        return started

    def _candidates(self, project):
        try:
            with self.projects.reader(project) as conn:
                if conn is None:
                    return []
                return [r[0] for r in conn.execute(CANDIDATES)]
        except Exception as e:
            self.log(f"dispatch: {project.id}: {type(e).__name__}: {e}")
            return []

    def _spawn(self, project, tid):
        if tid in self.children or time.time() - self.last.get(tid, 0) < self.backoff:
            return None
        with self.projects.engine(project) as eng:
            if not eng.check_start(tid)["ok"]:
                return None
            config = eng.config
        self.last[tid] = time.time()
        proc = subprocess.Popen([sys.executable, SENTINEL, "--dir", str(project.path), "task", "run", tid],
                                cwd=str(project.path), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True,
                                env=adapters.child_env(config))
        self.children[tid] = proc
        return proc
