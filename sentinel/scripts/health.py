"""Installation health checks. `sentinel doctor` and GET /api/v1/installation/health both call `doctor_problems`."""
import json
import os
import re
import shutil
import sys
from pathlib import Path

from paths import ROOT

NAMES = ("installation", "version", "git", "python", "pyyaml", "jsonschema", "registry_writable", "provider",
         "storage", "repo_access")
REQUIRED = {"installation", "version", "git", "python", "pyyaml", "registry_writable", "provider", "storage",
            "repo_access"}


def doctor_problems(config_path, config, state_dir, check_models=False, model_check=None):
    """(problems, notes) for one workspace. problems is a list of (check, text); `sentinel doctor` prints the texts."""
    workspace = Path(config_path).parent
    problems, notes = [], []
    try:
        import jsonschema
        schema = json.loads((ROOT / "core" / "schema" / "config.schema.json").read_text())
        import scopes
        for error in jsonschema.Draft202012Validator(schema).iter_errors(config):
            if re.match(r"repos/\d+/(test|production)_globs", "/".join(map(str, error.path))):
                continue
            problems.append(("storage", f"schema: {'/'.join(map(str, error.path))}: {error.message}"))
        problems.extend(("storage", f"schema: {text}") for _, text in scopes.config_problems(config))
        import verify
        problems = [x for x in problems if not x[1].startswith("schema: verification")]
        problems.extend(("storage", f"schema: {text}") for _, text in verify.config_problems(config))
    except ImportError:
        notes.append("note: jsonschema not installed, schema check skipped")
    for tool in ("git", "python3"):
        if not shutil.which(tool):
            problems.append(("git" if tool == "git" else "python", f"missing tool: {tool}"))
    for repo in config["repos"]:
        path = workspace / repo["path"]
        if not path.exists():
            problems.append(("repo_access", f"repo path missing: {repo['id']} -> {path}"))
        elif not (path / ".git").exists():
            problems.append(("repo_access", f"not a git repo: {repo['id']}"))
        profile_file = ROOT / "profiles" / f"{repo['profile']}.json"
        profile = json.loads(profile_file.read_text()) if profile_file.exists() else None
        if profile is None:
            problems.append(("repo_access", f"unknown profile for {repo['id']}: {repo['profile']}"))
            continue
        commands = {**profile["commands"], **(repo.get("commands") or {})}
        for key, command in commands.items():
            if command and not shutil.which(command.split()[0]) and not command.startswith("./") and not command.startswith("npm") and not command.startswith("npx"):
                problems.append(("repo_access", f"{repo['id']}: {key} command not found: {command.split()[0]}"))
    from run_stage import all_runners, single_model
    for stage, route in ({} if single_model(config) else config.get("routing") or {}).items():
        runner = all_runners(config).get(route["runner"])
        if not runner:
            problems.append(("provider", f"routing {stage}: runner not defined: {route['runner']}"))
            continue
        if not shutil.which(runner["command"].split()[0]):
            problems.append(("provider", f"runner CLI not installed: {runner['command'].split()[0]} (routing {stage})"))
        if route.get("model") and not single_model(config) and not runner.get("model_flag"):
            problems.append(("provider", f"routing {stage}: runner {route['runner']} has no model_flag, so model {route['model']} cannot be set"))
        if model_check:
            problems.extend(("provider", text) for text in model_check(config, stage, route, runner, check_models))
    shared_url = (config.get("state") or {}).get("shared_repo")
    if (config.get("state") or {}).get("shared_mode") == "local":
        if not (state_dir / "shared" / "invariants.md").exists():
            problems.append(("storage", "local-only shared folder is not set up: run `sentinel sync pull`"))
    elif not shared_url:
        problems.append(("storage", "state.shared_repo is required: ask your team for the URL of its private shared repo and run `sentinel shared set <url>`"))
    elif not (state_dir / "shared" / ".git").exists():
        problems.append(("storage", f"the shared repo ({shared_url}) is not cloned: run `sentinel sync pull`"))
    notes.extend(optional_setting_notes(config))
    if (config.get("state") or {}).get("auto_sync_push"):
        notes.append("note: state.auto_sync_push is on, so finished runs publish to the shared repo without asking; set it to false to publish only on request")
    return problems, notes


OPTIONAL_SETTINGS = (
    ("policies", "task limits and the steps that need a human (parallel tasks, task timeout, retries); built-in defaults apply"),
    ("providers", "fallback and disabled runners; none are disabled and there is no fallback"),
    ("agents", "per-role runner and write scope; the roles use the routing defaults"),
    ("tdd", "retry limits of the Red, Green and Refactor phases; the defaults apply"),
    ("verification", "mutation, migration check, disabled and extra checks; the defaults apply"),
    ("notifications", "desktop notifications in the dashboard (desktop: true is the default)"),
)


def optional_setting_notes(config):
    """One note listing the 1.1.0 settings the config does not have, or none. A config from 0.1 stays valid; see docs/config.md."""
    missing = [(key, text) for key, text in OPTIONAL_SETTINGS if key not in config]
    if not missing:
        return []
    return ["note: optional settings not set, built-in defaults apply: " + "; ".join(f"`{key}` ({text})" for key, text in missing)]


FIXES = {
    "installation": "reinstall sentinel (`uv tool install --force sentinel`)",
    "version": "reinstall sentinel; the VERSION file is missing or unreadable",
    "git": "install git and make sure it is on the PATH of the server process",
    "python": "install python3 and make sure it is on the PATH of the server process",
    "pyyaml": "install the pyyaml package for the python that runs sentinel",
    "jsonschema": "install the jsonschema package to enable schema checks",
    "registry_writable": "make the sentinel user folder writable by the user that runs the server (chmod u+w)",
    "provider": "install the runner command named in sentinel.config.yaml, or fix its runners entry",
    "storage": "run `sentinel doctor` in the workspace and fix the first problem it names",
    "repo_access": "run `sentinel doctor` in the workspace and fix the repo problem it names",
}


def _importable(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _installed_runner_status(config):
    from run_stage import single_model
    runners = dict(config.get("runners") or {})
    if not single_model(config):
        for route in (config.get("routing") or {}).values():
            runners.setdefault(route.get("runner"), None)
    if not runners:
        return "not_configured", "no runner is configured"
    from run_stage import all_runners
    merged = all_runners(config)
    cmds = {k: (merged.get(k) or {}).get("command", "") for k in runners}
    missing = [k for k, c in cmds.items() if not c.strip() or not shutil.which(c.split()[0])]
    if len(missing) == len(cmds):
        return "failed", "no runner command is installed: " + ", ".join(sorted(cmds[k].split()[0] if cmds[k].strip() else k for k in missing))
    if missing:
        return "warning", "runner command not installed: " + ", ".join(sorted(missing))
    return "passed", "runner commands are installed"


def checks(cfgdir, workspaces):
    """The health items of this installation. `workspaces` is a list of (id, config_path, config, state_dir) tuples;
    a workspace whose config cannot be read is (id, None, reason, None)."""
    items = {}

    rank = {"not_configured": 0, "passed": 1, "warning": 2, "failed": 3}

    def put(name, status, message, fix=""):
        old = items.get(name)
        if old and rank[old["status"]] >= rank[status] and old["status"] != "not_configured":
            return
        items[name] = {"name": name, "required": name in REQUIRED, "status": status, "message": message,
                       "fix": fix if status in ("failed", "warning") else ""}

    version_file = ROOT / "VERSION"
    put("installation", "passed" if (ROOT / "core" / "schema" / "config.schema.json").is_file() else "failed",
        f"installed at {ROOT}", FIXES["installation"])
    try:
        put("version", "passed", version_file.read_text().strip() or "unknown")
        if not version_file.read_text().strip():
            put("version", "failed", "VERSION file is empty", FIXES["version"])
    except OSError:
        put("version", "failed", "VERSION file is missing", FIXES["version"])
    put("git", "passed" if shutil.which("git") else "failed",
        "git found" if shutil.which("git") else "git is not on PATH", FIXES["git"])
    put("python", "passed" if sys.version_info >= (3, 10) and shutil.which("python3") else "failed",
        f"python {sys.version.split()[0]}" if shutil.which("python3") else "python3 is not on PATH", FIXES["python"])
    put("pyyaml", "passed" if _importable("yaml") else "failed",
        "pyyaml is installed" if _importable("yaml") else "pyyaml is not installed", FIXES["pyyaml"])
    put("jsonschema", "passed" if _importable("jsonschema") else "warning",
        "jsonschema is installed" if _importable("jsonschema") else "jsonschema is not installed", FIXES["jsonschema"])
    cfgdir = Path(cfgdir)
    writable = cfgdir.is_dir() and os.access(cfgdir, os.W_OK | os.X_OK)
    put("registry_writable", "passed" if writable else "failed",
        f"{cfgdir} is writable" if writable else f"{cfgdir} is not writable", FIXES["registry_writable"])
    for name in ("provider", "storage", "repo_access"):
        items[name] = {"name": name, "required": True, "status": "not_configured",
                       "message": "no project is registered", "fix": ""}
    for pid, config_path, config, state_dir in workspaces:
        if config_path is None:
            put("storage", "failed", f"project {pid}: {config}", FIXES["storage"])
            continue
        problems, _ = doctor_problems(config_path, config, state_dir)
        by = {}
        for check, text in problems:
            by.setdefault(check, []).append(text)
        for name in ("provider", "storage", "repo_access"):
            if name in by:
                put(name, "failed", f"project {pid}: {by[name][0]}", FIXES[name])
        status, message = _installed_runner_status(config)
        put("provider", status, f"project {pid}: {message}", FIXES["provider"])
        for name in ("storage", "repo_access"):
            put(name, "passed", f"project {pid}: no problem found")
    return list(items[n] for n in NAMES)


def ready(items):
    return not any(i["required"] and i["status"] == "failed" for i in items)
