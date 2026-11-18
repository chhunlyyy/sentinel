"""Providers are the runners of run_stage.all_runners: which are installed, and a harmless probe."""
import shlex
import shutil
import subprocess

import run_stage
import runtime

LABELS = {"claude": "Claude Code", "codex": "Codex CLI", "gemini": "Gemini CLI", "agy": "Antigravity (agy)"}

# Suggested models per provider. Empty means the provider default only; the dashboard always allows a custom id.
MODELS = {
    "claude": [("claude-fable-5-2", "Fable 5.2"), ("claude-opus-5-5", "Opus 5.5"),
               ("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-haiku-5-5", "Haiku 5.5")],
    "gemini": [("gemini-2.5-pro", "Gemini 2.5 Pro"), ("gemini-2.5-flash", "Gemini 2.5 Flash")],
}


def _runners(config):
    return run_stage.all_runners(config or {})


def _path(runner):
    cmd = runtime.runner_command(runner)
    if not cmd or not runtime.runner_installed(runner):
        return None
    return cmd if "/" in cmd else shutil.which(cmd)


def detect(config=None):
    out = []
    for rid, runner in _runners(config).items():
        path = _path(runner)
        out.append({"id": rid, "label": LABELS.get(rid, rid), "command": runner.get("command", ""),
                    "installed": path is not None, "path": path,
                    "models": models_for(rid, runner),
                    "capabilities": {"model_select": bool(runner.get("model_flag")),
                                     "resume": bool(runner.get("resume_flag")),
                                     "json_output": runner.get("output") == "json_response"}})
    return out


def models_for(rid, runner):
    """Models the config declares (runners.<id>.models) first, then the built-in suggestions. None without a model flag."""
    if not runner.get("model_flag"):
        return []
    out, seen = [], set()
    declared = [(m, m) for m in runner.get("models") or [] if isinstance(m, str)]
    for m, label in declared + MODELS.get(rid, []):
        if m not in seen:
            seen.add(m)
            out.append({"id": m, "label": label})
    return out


def installed_ids(config=None):
    return [p["id"] for p in detect(config) if p["installed"]]


def probe(runner_id, config=None, timeout=5):
    """Run `<command> --version` only. Never raises."""
    try:
        runner = _runners(config).get(runner_id)
        if not runner:
            return {"id": runner_id, "ok": False, "message": "unknown provider"}
        if not _path(runner):
            return {"id": runner_id, "ok": False, "message": "not installed"}
        proc = subprocess.run(shlex.split(runner["command"]) + ["--version"], capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL)
        lines = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
        msg = lines[0][:200] if lines else ""
        if proc.returncode != 0:
            return {"id": runner_id, "ok": False, "message": msg or f"exit {proc.returncode}"}
        return {"id": runner_id, "ok": True, "message": msg}
    except subprocess.TimeoutExpired:
        return {"id": runner_id, "ok": False, "message": f"no answer within {timeout}s"}
    except Exception as e:
        return {"id": runner_id, "ok": False, "message": f"{type(e).__name__}: {e}"[:200]}
