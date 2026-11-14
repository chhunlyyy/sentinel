#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import boundary  # noqa: E402
import render_stage  # noqa: E402

CONFIG_NAME = "sentinel.config.yaml"


def find_config(start):
    current = Path(start).resolve()
    for folder in [current, *current.parents]:
        if (folder / CONFIG_NAME).exists():
            return folder / CONFIG_NAME
    sys.exit(f"{CONFIG_NAME} not found")


def stage_group(stage):
    return {"cleaner": "cleaner", "hardener": "hardener", "coder": "coder", "repro": "coder"}.get(stage, stage)


DEFAULT_RUNNERS = {
    "claude": {"command": "claude", "prompt_flag": "-p", "model_flag": "--model", "add_dir_flag": "--add-dir", "args": ["--permission-mode", "acceptEdits"]},
    "codex": {"command": "codex exec", "model_flag": "-m"},
    "gemini": {"command": "gemini", "prompt_flag": "-p", "model_flag": "-m"},
    "agy": {"command": "agy", "prompt_flag": "-p", "model_flag": "--model", "resume_flag": "--conversation", "add_dir_flag": "--add-dir", "output": "json_response", "args": ["--output-format", "json", "--mode", "accept-edits"], "unsafe_args": ["--dangerously-skip-permissions"]},
}


def all_runners(config):
    merged = {key: dict(value) for key, value in DEFAULT_RUNNERS.items()}
    for key, value in (config.get("runners") or {}).items():
        merged[key] = {**merged.get(key, {}), **value}
    return merged


def find_route(config, stage, repo=None):
    if single_model(config):
        return None
    routing = config.get("routing") or {}
    group = stage_group(stage)
    keys = ([f"{repo}-{group}", f"{repo}-{stage}"] if repo else []) + [group, stage]
    for key in keys:
        if key in routing:
            return routing[key]
    return None


def single_model(config):
    return config.get("single_model", True) is not False


def pick_runner(config, stage, override, repo=None, model_override=None):
    route = find_route(config, stage, repo) or {}
    runner_id = override or route.get("runner", "claude")
    runner = all_runners(config).get(runner_id)
    if not runner:
        sys.exit(f"runner not defined in config: {runner_id}")
    configured = route.get("model") if not single_model(config) and (not override or override == route.get("runner")) else None
    model = model_override or configured
    if model and not runner.get("model_flag"):
        sys.exit(f"runner {runner_id} has no model_flag, so model {model} cannot be set; add model_flag to runners.{runner_id}")
    return runner_id, runner, model


def build_command(runner, prompt, model, resume, extra_dirs):
    command = shlex.split(runner["command"]) + list(runner.get("args") or [])
    if model and runner.get("model_flag"):
        command += [runner["model_flag"], model]
    if resume and runner.get("resume_flag"):
        command += [runner["resume_flag"], resume]
    if runner.get("add_dir_flag"):
        for directory in extra_dirs:
            command += [runner["add_dir_flag"], str(directory)]
    if runner.get("unsafe_skip_permissions"):
        command += list(runner.get("unsafe_args") or [])
        sys.stderr.write("warning: this runner skips permission prompts\n")
    stdin = None
    if runner.get("input") == "stdin":
        stdin = prompt
    else:
        if runner.get("prompt_flag"):
            command.append(runner["prompt_flag"])
        command.append(prompt)
    return command, stdin


def parse_output(runner, text):
    if runner.get("output") != "json_response":
        return text.strip(), None, "SUCCESS"
    try:
        data = json.loads(text)
    except ValueError:
        return text[-4000:], None, "UNPARSEABLE"
    return (data.get("response") or "").strip(), data.get(runner.get("session_field", "conversation_id")), data.get("status", "UNKNOWN")


HEARTBEAT_SECONDS = 30
PUMP_JOIN_SECONDS = 5


def pump_join_seconds():
    """Seconds to wait for the log pumps after the process ended. SENTINEL_PUMP_JOIN_SECONDS is an engine setting for tests."""
    try:
        value = float(os.environ.get("SENTINEL_PUMP_JOIN_SECONDS") or 0)
    except ValueError:
        value = 0
    return value if value > 0 else PUMP_JOIN_SECONDS


def heartbeat_seconds():
    """Seconds between progress lines. SENTINEL_HEARTBEAT_SECONDS is an engine setting for tests, not a config key."""
    try:
        value = float(os.environ.get("SENTINEL_HEARTBEAT_SECONDS") or 0)
    except ValueError:
        value = 0
    return value if value > 0 else HEARTBEAT_SECONDS


def changed_count(workdir):
    result = subprocess.run(["git", "-C", str(workdir), "status", "--porcelain"], capture_output=True, text=True)
    return len(result.stdout.splitlines()) if result.returncode == 0 else None


class LiveProcess:
    """A runner process with its output streamed live to two log files.

    With `new_session` the process leads its own process group, so signals reach its children too."""

    def __init__(self, command, stdin, workdir, log, err_log, env=None, new_session=False):
        self.process = subprocess.Popen(command, cwd=workdir, env=env, start_new_session=new_session,
                                        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.pid = self.process.pid
        self.new_session = new_session
        self.err_log = err_log
        self.collected = {"out": [], "err": []}
        self.threads = [threading.Thread(target=self._pump, args=(self.process.stdout, "out", log), daemon=True),
                        threading.Thread(target=self._pump, args=(self.process.stderr, "err", err_log), daemon=True)]
        for thread in self.threads:
            thread.start()
        if stdin is not None:
            try:
                self.process.stdin.write(stdin)
                self.process.stdin.close()
            except BrokenPipeError:
                pass

    def _pump(self, stream, key, path):
        try:
            with open(path, "w") as handle:
                for line in stream:
                    self.collected[key].append(line)
                    handle.write(line)
                    handle.flush()
        finally:
            stream.close()  # only this thread reads the stream, so only it may close it

    def poll(self):
        return self.process.poll()

    def wait(self, timeout):
        try:
            self.process.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            return False

    def output_bytes(self):
        return sum(len(line) for line in self.collected["out"])

    def kill(self):
        if self.new_session:
            try:
                os.killpg(self.pid, signal.SIGKILL)
                return
            except (ProcessLookupError, PermissionError):
                pass
        self.process.kill()

    def reap(self):
        """Wait for the process. A task process (own session) takes its whole group with it, so no background child
        keeps the pipes or outlives the task."""
        self.process.wait()
        if self.new_session:
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        return self.process.returncode

    def finish(self, timed_out=False):
        """Wait for the process and, for a bounded time, the log pumps. Returns (exit code, stdout, stderr); a timeout
        reads as 124. A pump still blocked on a pipe that a background child holds is left to end by itself."""
        self.reap()
        deadline = time.time() + pump_join_seconds()
        for thread in self.threads:
            thread.join(timeout=max(0.0, deadline - time.time()))
        stderr = "".join(self.collected["err"])
        if timed_out:
            stderr += "\ntimeout"
            with open(self.err_log, "a") as handle:
                handle.write("\ntimeout\n")
        return (124 if timed_out else self.process.returncode), "".join(self.collected["out"]), stderr


def run_live(command, stdin, workdir, timeout, log, err_log, name):
    live = LiveProcess(command, stdin, workdir, log, err_log)
    started = time.time()
    timed_out = False
    beat = heartbeat_seconds()
    while live.poll() is None:
        if not live.wait(beat):
            elapsed = int(time.time() - started)
            if elapsed >= timeout:
                live.kill()
                timed_out = True
                break
            changed = changed_count(workdir)
            note = f", {changed} changed files in {workdir.name}" if changed is not None else ""
            print(f"[{name}] running {elapsed // 60}m{elapsed % 60:02d}s, {live.output_bytes()} bytes of output{note}", file=sys.stderr, flush=True)
    return live.finish(timed_out)


def refuse_if_v2(state_dir, slug):
    """`stage run` must not bypass the engine: a version 2 run is driven by `sentinel task run` (exit 5)."""
    db = Path(state_dir) / "sentinel.db"
    if not db.exists():
        return
    import sqlite3
    try:
        conn = sqlite3.connect(db, timeout=10)
        try:
            row = conn.execute("SELECT workflow_version FROM runs WHERE slug=?", (slug,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return
    if row and row[0] == "2":
        print(f"E_TRANSITION: run {slug} is a version 2 run; `stage run` would bypass the engine, use `sentinel task run <task-id>`", file=sys.stderr)
        sys.exit(5)


def main():
    parser = argparse.ArgumentParser(prog="run-stage")
    parser.add_argument("--config")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--repo")
    parser.add_argument("--runner")
    parser.add_argument("--model")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--brief")
    parser.add_argument("--resume")
    parser.add_argument("--concurrent", action="append", default=[], help="repo id another stage is editing at the same time")
    parser.add_argument("--timeout", type=int, default=5400)
    args = parser.parse_args()

    config_path = Path(args.config).resolve() if args.config else find_config(".")
    config = yaml.safe_load(config_path.read_text())
    workspace = config_path.parent
    state_dir = workspace / (config.get("state") or {}).get("dir", ".sentinel")
    from paths import valid_slug
    valid_slug(args.slug)
    refuse_if_v2(state_dir, args.slug)
    run_directory = state_dir / "runs" / args.slug
    run_directory.mkdir(parents=True, exist_ok=True)
    cache = state_dir / "cache" / "runs" / args.slug
    cache.mkdir(parents=True, exist_ok=True)

    runner_id, runner, model = pick_runner(config, args.stage, args.runner, args.repo, args.model)
    template = (HERE.parent / "core" / "stages" / f"{args.stage}.md").read_text()
    front = yaml.safe_load(render_stage.FRONT.match(template).group(1))
    repo = None
    if front.get("per_repo"):
        matches = [r for r in config["repos"] if r["id"] == args.repo]
        if not matches:
            sys.exit(f"stage {args.stage} is per-repo; pass --repo <id> (known: {', '.join(r['id'] for r in config['repos'])})")
        repo = matches[0]
    context = render_stage.build_context(config, repo, workspace, args.stage)
    context["state_dir"] = str(state_dir)
    context["run_dir"] = str(run_directory)
    context["shared_dir"] = str(state_dir / "shared")
    prompt = render_stage.render(template, context)
    prompt += f"\n## Runtime notes\n\n- Workspace root: {workspace}. Every path above is absolute; never create the sentinel state folder inside a repo.\n- You run headless inside an automated pipeline. No human will answer questions; if blocked, stop and state exactly what blocks you in your report.\n- Your write boundary is checked after you finish. Writing outside it, or committing, fails the stage.\n- Finish with the report your instructions ask for.\n"
    if args.brief:
        prompt += "\n## Brief\n\n" + Path(args.brief).read_text()

    name = f"{args.repo + '-' if args.repo else ''}{args.stage}"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (cache / f"{stamp}-{name}.prompt.md").write_text(prompt)

    repos = {r["id"]: (workspace / r["path"]).resolve() for r in config["repos"] if (workspace / r["path"] / ".git").exists()}
    watched = [workspace / "sentinel.config.yaml", workspace / ".claude" / "agents", workspace / ".claude" / "skills", workspace / "AGENTS.md"]
    snapshot = boundary.Snapshot(repos, watched)
    state_name = state_dir.name
    had_state = {rid: (path / state_name).exists() for rid, path in repos.items()}
    workdir = repos[repo["id"]] if repo and repo["id"] in repos else workspace
    allowed = repo["id"] if front.get("writes") == "repo" and repo else None

    command, stdin = build_command(runner, prompt, model, args.resume, [state_dir])
    print(f"running {name} on {runner_id} in {workdir}", file=sys.stderr)
    log = cache / f"{stamp}-{name}.output.txt"
    err_log = cache / f"{stamp}-{name}.stderr.txt"
    print(f"live log: {log}", file=sys.stderr)
    exit_code, stdout, stderr = run_live(command, stdin, workdir, args.timeout, log, err_log, name)
    report, session, status = parse_output(runner, stdout)
    if exit_code != 0 and status in ("SUCCESS", "UNKNOWN"):
        status = "FAILED"
    violations = snapshot.violations(allowed, args.concurrent)
    for rid, path in repos.items():
        if (path / state_name).exists() and not had_state[rid]:
            violations.append(f"{rid}: sentinel state folder ({state_name}) was created inside the repo; run files belong under {state_dir}")

    print("===== RESULT")
    print(f"stage: {name}")
    print(f"runner: {runner_id}" + (f" ({model})" if model else ""))
    print(f"status: {status} (exit {exit_code})")
    if session:
        print(f"session_id: {session}")
    print(f"log: {log}")
    if violations:
        print("BOUNDARY VIOLATIONS:")
        for item in violations:
            print(f"  - {item}")
    print("----- final report")
    print(report)
    if stderr.strip():
        print("----- runner stderr (tail)")
        print("\n".join(stderr.strip().splitlines()[-20:]))
    if violations:
        sys.exit(3)
    if exit_code != 0 or status not in ("SUCCESS", "UNKNOWN"):
        sys.exit(1)


if __name__ == "__main__":
    main()
