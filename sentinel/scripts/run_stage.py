#!/usr/bin/env python3
import argparse
import json
import shlex
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


def changed_count(workdir):
    result = subprocess.run(["git", "-C", str(workdir), "status", "--porcelain"], capture_output=True, text=True)
    return len(result.stdout.splitlines()) if result.returncode == 0 else None


def run_live(command, stdin, workdir, timeout, log, err_log, name):
    process = subprocess.Popen(command, cwd=workdir, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    collected = {"out": [], "err": []}

    def pump(stream, key, path):
        with open(path, "w") as handle:
            for line in stream:
                collected[key].append(line)
                handle.write(line)
                handle.flush()

    threads = [threading.Thread(target=pump, args=(process.stdout, "out", log), daemon=True), threading.Thread(target=pump, args=(process.stderr, "err", err_log), daemon=True)]
    for thread in threads:
        thread.start()
    if stdin is not None:
        try:
            process.stdin.write(stdin)
            process.stdin.close()
        except BrokenPipeError:
            pass
    started = time.time()
    timed_out = False
    while process.poll() is None:
        try:
            process.wait(timeout=HEARTBEAT_SECONDS)
        except subprocess.TimeoutExpired:
            elapsed = int(time.time() - started)
            if elapsed >= timeout:
                process.kill()
                timed_out = True
                break
            changed = changed_count(workdir)
            note = f", {changed} changed files in {workdir.name}" if changed is not None else ""
            size = sum(len(line) for line in collected["out"])
            print(f"[{name}] running {elapsed // 60}m{elapsed % 60:02d}s, {size} bytes of output{note}", file=sys.stderr, flush=True)
    for thread in threads:
        thread.join(timeout=5)
    stderr = "".join(collected["err"])
    if timed_out:
        stderr += "\ntimeout"
    return (124 if timed_out else process.returncode), "".join(collected["out"]), stderr


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
