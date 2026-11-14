"""Agent adapters: one interface for every provider (docs/architecture/agent-runtime.md section 3).

PC-01 defines the interface, the capability rules and the registry. PC-02 adds CliAdapter.submit/status/
result/cancel (a LiveProcess from run_stage in its own process group) and NativeAdapter.submit/cancel
(cooperative: the engine marks the task, the orchestrator stops the subagent).
"""
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from errors import SentinelError

CANCEL_SIGNAL, CANCEL_COOPERATIVE = "signal", "cooperative"
CANCEL_GRACE = 10.0  # seconds between SIGTERM and SIGKILL
TASK_ENV = "SENTINEL_TASK_ID"
DASHBOARD_TOKEN_ENV = "SENTINEL_DASHBOARD_TOKEN"


@dataclass(frozen=True)
class Capabilities:
    model_select: bool
    resume: bool
    cancel: str
    json_output: bool
    streaming: bool = False
    native: bool = False


@dataclass
class Handle:
    """What an adapter needs to find a submitted task again. Mirrors the task row."""
    task_id: str
    pid: int = None
    pid_started_at: str = None
    session_id: str = None
    workdir: str = None
    model: str = None
    task_dir: str = None


@dataclass
class Job:
    """Everything an adapter needs to start one task."""
    task_id: str
    task_dir: str
    workdir: str
    prompt: str
    model: str = None
    session_id: str = None
    extra_dirs: list = field(default_factory=list)


def _proc_stat(pid):
    """(state letter, start time ticks) from /proc, None when the process is gone or unreadable."""
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[0], fields[19]
    except (OSError, ValueError, IndexError, TypeError):
        return None


def process_start_time(pid):
    """Start time ticks of a process from /proc (Linux), None when unknown or gone."""
    stat = _proc_stat(pid)
    return stat[1] if stat else None


def process_alive(pid, started=None):
    """True when `pid` is a live (not zombie) process; with `started`, only when its start time matches."""
    stat = _proc_stat(pid)
    if not stat or stat[0] == "Z":
        return False
    return started is None or str(started) == stat[1]


def signal_group(pid, sig):
    try:
        os.killpg(int(pid), sig)
        return True
    except (ProcessLookupError, PermissionError, ValueError, TypeError):
        return False


def group_alive(pgid):
    """True while any process is left in the process group `pgid` (the leader may be gone)."""
    return signal_group(pgid, 0)


def cancel_grace():
    """Seconds between SIGTERM and SIGKILL. SENTINEL_CANCEL_GRACE_SECONDS is an engine setting for tests."""
    try:
        value = float(os.environ.get("SENTINEL_CANCEL_GRACE_SECONDS") or 0)
    except ValueError:
        value = 0
    return value if value > 0 else CANCEL_GRACE


def _ours(pid, started):
    """The process group of (pid, start time) is the one a task started: while the leader lives its start time must
    match; once it is gone the group (kept alive by its members, so the pid cannot be reused) is still ours."""
    stat = _proc_stat(pid)
    if stat and stat[0] != "Z" and started is not None and str(started) != stat[1]:
        return False
    return group_alive(pid)


def terminate_groups(targets, grace=None, poll=0.1):
    """SIGTERM the process group of every (pid, start time) that still has members, SIGKILL every group that still
    has members after `grace` seconds, also when its leader is already gone."""
    grace = cancel_grace() if grace is None else grace
    live = [(pid, started) for pid, started in targets if pid and _ours(pid, started)]
    live = [t for t in live if signal_group(t[0], signal.SIGTERM)]
    deadline = time.time() + grace
    while live and time.time() < deadline:
        live = [t for t in live if group_alive(t[0])]
        if live:
            time.sleep(poll)
    for pid, _ in live:
        signal_group(pid, signal.SIGKILL)
    return bool(targets)


def child_env(config, task_id=None, base=None):
    """Environment for a child process: inherited minus the dashboard token and policies.redact_env."""
    env = dict(os.environ if base is None else base)
    env.pop(DASHBOARD_TOKEN_ENV, None)
    for name in (config.get("policies") or {}).get("redact_env") or []:
        env.pop(name, None)
    if task_id:
        env[TASK_ENV] = task_id
    return env


def redact_text(config, text, base=None):
    """`text` without the values of the policies.redact_env variables and the dashboard token (read from the
    environment of this process), for text that reaches another provider or a log."""
    env = os.environ if base is None else base
    names = list((config.get("policies") or {}).get("redact_env") or []) + [DASHBOARD_TOKEN_ENV]
    for name in names:
        value = env.get(name)
        if value:
            text = text.replace(value, "[redacted]")
    return text


class Adapter:
    """Base interface. Subclasses set `name` and implement the methods they support."""
    name = ""

    def capabilities(self):
        raise NotImplementedError

    def submit(self, task):
        raise NotImplementedError

    def status(self, handle):
        raise NotImplementedError

    def result(self, handle):
        raise NotImplementedError

    def cancel(self, handle):
        raise NotImplementedError

    def resume(self, handle, message):
        raise SentinelError("E_PRECONDITION", f"resume not supported by the {self.name} adapter",
                            {"adapter": self.name})


class NativeAdapter(Adapter):
    """Tasks run as a subagent inside the user's AI tool. Submit hands the prompt to the orchestrator."""
    name = "native"

    def capabilities(self):
        return Capabilities(model_select=False, resume=False, cancel=CANCEL_COOPERATIVE,
                            json_output=True, streaming=False, native=True)

    def submit(self, job):
        """No process: the task waits for the orchestrator, which launches the subagent from prompt.md."""
        return Handle(job.task_id, workdir=job.workdir, task_dir=job.task_dir)

    def status(self, handle):
        return {"done": False, "waiting_on": "orchestrator"}

    def result(self, handle):
        return {"done": False}

    def cancel(self, handle):
        """Cooperative: the engine marks the task CANCELLED; `sentinel next` tells the orchestrator to stop it."""
        return False


class CliAdapter(Adapter):
    """Tasks run as a child process built from the runner table, in its own process group."""
    name = "cli"

    def __init__(self, runner_id, runner, config=None):
        self.runner_id = runner_id
        self.runner = dict(runner)
        self.config = config or {}
        self._live = {}

    def capabilities(self):
        r = self.runner
        return Capabilities(model_select=bool(r.get("model_flag")), resume=bool(r.get("resume_flag")),
                            cancel=CANCEL_SIGNAL, json_output=bool(r.get("output")), streaming=True, native=False)

    def submit(self, job):
        from run_stage import LiveProcess, build_command
        command, stdin = build_command(self.runner, job.prompt, job.model, job.session_id, job.extra_dirs)
        tdir = Path(job.task_dir)
        try:
            live = LiveProcess(command, stdin, job.workdir, tdir / "output.log", tdir / "stderr.log",
                               env=child_env(self.config, job.task_id), new_session=True)
        except OSError as e:
            raise SentinelError("E_PROVIDER", f"cannot start runner {self.runner_id}: {e}",
                                {"runner": self.runner_id}) from e
        self._live[job.task_id] = live
        return Handle(job.task_id, pid=live.pid, pid_started_at=process_start_time(live.pid),
                      session_id=job.session_id, workdir=job.workdir, model=job.model, task_dir=job.task_dir)

    def wait(self, handle, timeout):
        """Block up to `timeout` seconds; True when the process has exited."""
        return self._live[handle.task_id].wait(timeout)

    def status(self, handle):
        live = self._live.get(handle.task_id)
        if live is None:
            return {"done": not process_alive(handle.pid, handle.pid_started_at), "exit_code": None}
        code = live.poll()
        return {"done": code is not None, "exit_code": code, "output_bytes": live.output_bytes()}

    def reap(self, handle):
        """Collect the exit code of an ended process and stop what its group left behind; does not wait for the logs."""
        return self._live[handle.task_id].reap()

    def result(self, handle, timed_out=False):
        """(exit code, stdout text, stderr text) once the process has ended; joins the log pumps (bounded)."""
        live = self._live.pop(handle.task_id)
        return live.finish(timed_out)

    def cancel(self, handle, grace=None):
        """SIGTERM to the process group, SIGKILL after `grace` seconds (default 10)."""
        return terminate_groups([(handle.pid, handle.pid_started_at)], grace=grace)

    def resume(self, handle, message):
        if not self.capabilities().resume:
            raise SentinelError("E_PRECONDITION", f"resume not supported: runners.{self.runner_id} has no resume_flag",
                                {"runner": self.runner_id})
        if not handle.session_id:
            raise SentinelError("E_PRECONDITION", f"no session id stored for task {handle.task_id}",
                                {"task": handle.task_id})
        from run_stage import build_command
        command, stdin = build_command(self.runner, message, handle.model, handle.session_id, [])
        out = None
        if handle.task_dir:
            out = open(Path(handle.task_dir) / "output.log", "ab")
        try:
            proc = subprocess.Popen(command, cwd=handle.workdir, env=child_env(self.config, handle.task_id),
                                    stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                    stdout=out or subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                    start_new_session=True, text=True)
        except OSError as e:
            raise SentinelError("E_PROVIDER", f"cannot start runner {self.runner_id}: {e}",
                                {"runner": self.runner_id}) from e
        finally:
            if out:
                out.close()
        if stdin is not None:
            try:
                proc.stdin.write(stdin)
                proc.stdin.close()
            except BrokenPipeError:
                pass
        threading.Thread(target=proc.wait, daemon=True).start()  # reap the child when it exits
        return Handle(handle.task_id, pid=proc.pid, pid_started_at=process_start_time(proc.pid),
                      session_id=handle.session_id, workdir=handle.workdir, model=handle.model,
                      task_dir=handle.task_dir)


ADAPTERS = {"cli": CliAdapter, "native": NativeAdapter}


def get_adapter(kind, config, runner_id=None):
    """The adapter of `kind` ("cli" or "native"); a cli adapter needs the runner id defined in the config."""
    from run_stage import all_runners
    if kind == "native" or runner_id == "native":
        return ADAPTERS["native"]()
    if kind not in ADAPTERS:
        raise SentinelError("E_VALIDATION", f"unknown adapter {kind!r}", {"allowed": sorted(ADAPTERS)})
    runner = all_runners(config).get(runner_id)
    if not runner:
        raise SentinelError("E_VALIDATION", f"runner not defined in config: {runner_id}", {"runner": runner_id})
    return ADAPTERS[kind](runner_id, runner, config)
