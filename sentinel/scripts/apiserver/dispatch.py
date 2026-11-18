"""Q2 dispatch: while the server runs, ready CLI tasks of runs created through the API are started with
`sentinel task run`, the same path as the CLI. Native tasks and every orchestrator step wait for the AI tool.
The engine's own start checks decide, so a race with an orchestrator has one winner.
"""
import os
import subprocess
import sys
import threading
import time

import adapters
import run_stage
import runtime
from paths import ROOT

SENTINEL = str(ROOT / "scripts" / "sentinel.py")
FINAL = ("COMPLETED", "FAILED", "CANCELLED")
MAX_ORCHESTRATOR_LAUNCHES = 3   # per (run, state); after that the run waits for a human

RUNS = ("SELECT slug, state FROM runs WHERE origin = 'dashboard' AND workflow_version = '2' "
        "AND state NOT IN ('COMPLETED','FAILED','CANCELLED') ORDER BY created_at, id")

CANDIDATES = ("SELECT t.id FROM tasks t JOIN runs r ON r.id = t.run_id WHERE r.origin = 'dashboard' "
              "AND r.workflow_version = '2' AND r.state NOT IN ('COMPLETED','FAILED','CANCELLED') "
              "AND t.state = 'QUEUED' AND t.adapter = 'cli' ORDER BY t.created_at, t.id")


def _wait_quietly(proc):
    try:
        proc.wait()
    except Exception:
        pass


class Dispatcher:
    def __init__(self, projects, interval=0.5, log=None, api=None):
        self.projects = projects
        self.api = api   # holds `orchestrator`, read on every pass so a change takes effect at once
        self.orch_children = {}   # (project id, slug) -> Popen
        self.orch_launches = {}   # (project id, slug, state) -> count
        self.orch_last = {}       # (project id, slug) -> time of the last launch
        self.orch_gave_up = set()
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
        for proc in self.orch_children.values():
            if proc.poll() is None:
                threading.Thread(target=_wait_quietly, args=(proc,), daemon=True).start()
        self.children.clear()
        self.orch_children.clear()

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
                started.extend(self._orchestrate(project))
        return started

    # ---- orchestrator auto-drive
    def _orchestrator(self):
        return getattr(self.api, "orchestrator", None) if self.api else None

    def _orchestrate(self, project):
        """Launch the orchestrator AI tool for runs that wait for it. Never when none is set, and never from a task process."""
        runner_id = self._orchestrator()
        if not runner_id or os.environ.get(adapters.TASK_ENV):
            return []
        for key in [k for k, p in self.orch_children.items() if p.poll() is not None]:
            self.orch_children.pop(key)
        try:
            with self.projects.reader(project) as conn:
                if conn is None:
                    return []
                runs = [(r[0], r[1]) for r in conn.execute(RUNS)]
        except Exception as e:
            self.log(f"dispatch: {project.id}: {type(e).__name__}: {e}")
            return []
        started = []
        for slug, state in runs:
            try:
                proc = self._launch_orchestrator(project, runner_id, slug, state)
            except Exception as e:
                self.log(f"dispatch: orchestrator {project.id}/{slug}: {type(e).__name__}: {e}")
                continue
            if proc:
                started.append(proc)
        return started

    def _launch_orchestrator(self, project, runner_id, slug, state):
        rkey, skey = (project.id, slug), (project.id, slug, state)
        if rkey in self.orch_children or time.time() - self.orch_last.get(rkey, 0) < self.backoff:
            return None
        with self.projects.engine(project) as eng:
            run = eng._get(slug)
            if run["state"] != state or run["state"] in FINAL:
                return None
            step = eng._step_for(run, {"run": slug, "state": state})
            if step.get("kind") != "orchestrator":
                return None
            config = eng.config
            logdir = eng.state_dir / "runs" / slug
            if self.orch_launches.get(skey, 0) >= MAX_ORCHESTRATOR_LAUNCHES:
                if skey not in self.orch_gave_up:
                    self.orch_gave_up.add(skey)
                    self.log(f"dispatch: orchestrator {runner_id} gave up on {project.id}/{slug} in {state} after "
                             f"{MAX_ORCHESTRATOR_LAUNCHES} launches; waiting for a human")
                    try:
                        eng.audit("dashboard", "dashboard", "orchestrator_gave_up", f"{slug}/{state}",
                                  reason=f"{MAX_ORCHESTRATOR_LAUNCHES} launches without progress")
                    except Exception:
                        pass
                return None
        runner = run_stage.all_runners(config).get(runner_id)
        if not runner or not runtime.runner_installed(runner):
            self.log(f"dispatch: orchestrator {runner_id} is not available")
            return None
        prompt = (f"Resume the Sentinel run {slug} in this project with the Sentinel skill: /sentinel resume {slug}. "
                  "Follow `sentinel next` and stop at human gates.")
        command, stdin = run_stage.build_command(runner, prompt, None, None, [])
        logdir.mkdir(parents=True, exist_ok=True)
        self.orch_last[rkey] = time.time()
        self.orch_launches[skey] = self.orch_launches.get(skey, 0) + 1
        with open(logdir / "orchestrator.log", "ab") as log:
            log.write(f"--- launch {self.orch_launches[skey]} of {runner_id} for {state} ---\n".encode())
            log.flush()
            proc = subprocess.Popen(command, cwd=str(project.path), stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                    env=adapters.child_env(config))
        if stdin is not None:
            try:
                proc.stdin.write(stdin.encode())
                proc.stdin.close()
            except OSError:
                pass
        self.orch_children[rkey] = proc
        return proc

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
