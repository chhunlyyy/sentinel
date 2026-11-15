"""Phase G read routes: health, readiness, repositories, configuration, history, diff, changes (read only)."""
import difflib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml

import engine as engine_mod
import health
import scopes
from errors import SentinelError
from paths import ROOT

from . import userdir
from .projects import CONFIG_NAME
from .views import validation

WORKFLOWS = engine_mod.RUN_TYPES
DIFF_LIMIT = 1024 * 1024
DIFF_READ_CAP = 8 * 1024 * 1024
GIT_TIMEOUT = 30
COMMAND_KEYS = ("build", "test", "lint", "typecheck", "mutate")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(path, *args, limit=DIFF_READ_CAP, ok=(0,)):
    """(stdout bytes, returncode). Never runs configured external diff or text conversion programs, never writes."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat", "LC_ALL": "C"}
    cmd = ["git", "-c", "core.quotepath=off", "-c", "core.fsmonitor=false", "-C", str(path), *args]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, env=env)
    except OSError:
        return b"", 127
    try:
        data = proc.stdout.read(limit)
        if len(data) >= limit:
            proc.kill()
        proc.wait(timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    finally:
        proc.stdout.close()
    return data, proc.returncode


# ---- health
def health_view(projects, cfgdir):
    workspaces = []
    for project in projects.list():
        if not project.path.is_dir():
            workspaces.append((project.id, None, "workspace missing", None))
            continue
        config, reason = projects._load_config(project)
        if reason or not isinstance(config, dict) or not isinstance(config.get("repos"), list):
            workspaces.append((project.id, None, reason or "invalid configuration", None))
            continue
        workspaces.append((project.id, project.path / CONFIG_NAME, config, projects.state_dir(project, config)))
    items = health.checks(cfgdir, workspaces)
    return {"items": items, "ready": health.ready(items), "checked_at": _now()}


# ---- repositories and readiness
def _strip_credentials(url):
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return re.sub(r"//[^/@\s]*@", "//", url)
    if parts.netloc and "@" in parts.netloc:
        return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))
    return url


def _profile(name):
    f = ROOT / "profiles" / f"{name}.json"
    try:
        return json.loads(f.read_text()) if re.fullmatch(r"[A-Za-z0-9._-]+", name or "") and f.is_file() else None
    except (OSError, ValueError):
        return None


def _branches(path):
    out, code = _git(path, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", limit=4096)
    origin_head = out.decode().strip() if code == 0 else ""
    out, code = _git(path, "symbolic-ref", "-q", "--short", "HEAD", limit=4096)
    current = out.decode().strip() if code == 0 and out.strip() else None
    default = origin_head.split("/", 1)[1] if "/" in origin_head else (origin_head or current)
    return default, current


def _branch_exists(path, name):
    for ref in (f"refs/heads/{name}", f"refs/remotes/origin/{name}"):
        if _git(path, "rev-parse", "--verify", "-q", ref, limit=4096)[1] == 0:
            return True
    return False


def _item(name, status, message="", fix=""):
    return {"name": name, "status": status, "message": message, "fix": fix if status in ("failed", "warning") else ""}


def repo_info(workspace, repo):
    path = (workspace / repo["path"])
    exists = path.is_dir()
    commands = dict.fromkeys(COMMAND_KEYS, "")
    profile = _profile(repo.get("profile"))
    commands.update({k: v for k, v in ((profile or {}).get("commands") or {}).items() if k in COMMAND_KEYS})
    commands.update({k: v for k, v in (repo.get("commands") or {}).items() if k in COMMAND_KEYS})
    is_git = exists and (path / ".git").exists()
    default = current = remote = None
    if is_git:
        default, current = _branches(path)
        out, code = _git(path, "remote", "get-url", "origin", limit=8192)
        remote = _strip_credentials(out.decode(errors="replace").strip()) if code == 0 and out.strip() else None
    validation_items = [
        _item("exists", "passed" if exists else "failed", f"{repo['path']} exists" if exists else f"{repo['path']} does not exist",
              f"create the folder or fix repos[].path of {repo['id']} in sentinel.config.yaml"),
        _item("git", "passed" if is_git else "failed", "a git repository" if is_git else "not a git repository",
              f"run `git init` in {repo['path']} or point the repo at a git checkout"),
    ]
    if is_git:
        has_branch = bool(default) and _branch_exists(path, default)
        validation_items.append(_item("branch", "passed" if has_branch else "failed",
                                      f"default branch {default}" if has_branch else f"the default branch {default or '(none)'} does not exist",
                                      "create or check out the default branch (for example `git switch -c main`)"))
    else:
        validation_items.append(_item("branch", "failed", "no git repository to read a branch from", "fix the git check first"))
    writable = exists and os.access(path, os.W_OK | os.X_OK)
    validation_items.append(_item("writable", "passed" if writable else "failed",
                                  "writable" if writable else "not writable by the server user",
                                  f"make {repo['path']} writable by the user that runs the server"))
    validation_items.append(_item("profile", "passed" if profile else "failed",
                                  f"profile {repo['profile']}" if profile else f"profile {repo['profile']} is not installed",
                                  "use one of the profiles that ship with sentinel or fix repos[].profile"))
    return {"id": repo["id"], "path": repo["path"], "remote": remote, "default_branch": default,
            "current_branch": current, "role": repo.get("role"), "profile": repo.get("profile"), "commands": commands,
            "guidelines": repo.get("guidelines"), "validation": validation_items}


def repositories(projects, project):
    config = projects.require(project)
    return {"items": [repo_info(project.path, r) for r in config["repos"]], "next": None}


def _load_unchecked(project):
    """(config, errors, reason). errors is a list of {path, message}; reason is 'workspace missing' or None."""
    if not project.path.is_dir():
        return None, [], "workspace missing"
    f = project.path / CONFIG_NAME
    try:
        config = yaml.safe_load(f.read_text(encoding="utf-8"))
    except OSError:
        return None, [{"path": CONFIG_NAME, "message": f"{CONFIG_NAME} cannot be read"}], None
    except yaml.YAMLError as e:
        return None, [{"path": CONFIG_NAME, "message": f"not valid YAML: {str(e).splitlines()[0] if str(e) else 'syntax error'}"}], None
    if not isinstance(config, dict):
        return None, [{"path": CONFIG_NAME, "message": "the configuration must be a mapping"}], None
    errors = []
    try:
        import jsonschema
        schema = json.loads((ROOT / "core" / "schema" / "config.schema.json").read_text())
        for e in sorted(jsonschema.Draft202012Validator(schema).iter_errors(config), key=lambda e: list(map(str, e.path))):
            errors.append({"path": "/".join(map(str, e.path)) or "(root)", "message": e.message})
    except ImportError:
        pass
    return config, errors, None


def _exe(command):
    if not command or not command.strip():
        return None
    try:
        first = command.split()[0]
    except IndexError:
        return None
    return first


def readiness(projects, project, query):
    workflow = query.get("workflow")
    if workflow is not None and workflow not in WORKFLOWS:
        raise validation(f"workflow must be one of {', '.join(WORKFLOWS)}", "workflow", allowed=list(WORKFLOWS))
    checked = _now()
    items = []

    def add(name, repo, required, status, message, fix=""):
        items.append({"name": name, "repo": repo, "required": required, "status": status, "message": message,
                      "fix": fix if status in ("failed", "warning") else "", "checked_at": checked if status != "not_checked" else checked})

    config, errors, reason = _load_unchecked(project)
    if reason:
        add("workspace", None, True, "failed", f"{reason}: {project.path}", "restore the folder or register the project again")
        return {"project": project.id, "workflow": workflow, "state": "connection_unavailable", "items": items,
                "errors": []}
    if errors:
        add("configuration", None, True, "failed", f"{len(errors)} problem(s) in {CONFIG_NAME}",
            f"fix the listed problems in {CONFIG_NAME}")
        return {"project": project.id, "workflow": workflow, "state": "invalid_configuration", "items": items,
                "errors": errors}
    add("configuration", None, True, "passed", f"{CONFIG_NAME} passes the schema")
    needs_test = workflow != "docs"
    unreachable = False
    for repo in config["repos"]:
        info = repo_info(project.path, repo)
        by = {v["name"]: v for v in info["validation"]}
        for name in ("exists", "git", "branch", "writable", "profile"):
            v = by[name]
            required = name in ("exists", "git")
            add(f"repo_{name}", repo["id"], required, v["status"], v["message"], v["fix"])
        if by["exists"]["status"] == "failed":
            unreachable = True
        for key in COMMAND_KEYS:
            command = info["commands"].get(key, "")
            required = key == "test" and needs_test
            name = f"{key}_command"
            exe = _exe(command)
            if exe is None:
                add(name, repo["id"], required, "failed" if required else "not_configured",
                    f"no {key} command is set", f"set commands.{key} for repo {repo['id']} in {CONFIG_NAME}")
            elif command.startswith(("./", "/")) and (project.path / repo["path"] / exe).exists() or shutil.which(exe):
                add(name, repo["id"], required, "not_checked", f"{exe} found; the command was not run")
            elif command.startswith("./") or command.startswith("npm") or command.startswith("npx"):
                add(name, repo["id"], required, "not_checked", f"{exe} is not checked on PATH; the command was not run")
            else:
                add(name, repo["id"], required, "failed" if required else "warning", f"{exe} is not on PATH",
                    f"install {exe} or fix commands.{key} for repo {repo['id']}")
    status, message = health._installed_runner_status(config)
    add("provider", None, False, status, message, "install a runner command or fix runners in " + CONFIG_NAME)
    if unreachable:
        state = "connection_unavailable"
    elif any(i["required"] and i["status"] == "failed" for i in items):
        state = "needs_configuration"
    elif any(i["status"] in ("warning", "failed") for i in items):
        state = "ready_with_warnings"
    else:
        state = "ready"
    return {"project": project.id, "workflow": workflow, "state": state, "items": items, "errors": []}


# ---- configuration
def _flatten(value, prefix=()):
    if isinstance(value, dict) and value:
        for k, v in value.items():
            yield from _flatten(v, prefix + (str(k),))
    else:
        yield ".".join(prefix), value


def _schema_defaults():
    schema = json.loads((ROOT / "core" / "schema" / "config.schema.json").read_text())
    out = {}

    def walk(node, prefix):
        for key, sub in (node.get("properties") or {}).items():
            if not isinstance(sub, dict):
                continue
            if "default" in sub:
                out[".".join(prefix + (key,))] = sub["default"]
            if sub.get("type") == "object" and "properties" in sub:
                walk(sub, prefix + (key,))
    walk({"properties": {k: v for k, v in schema["properties"].items() if k != "repos"}}, ())
    return out


def _global_values(cfgdir):
    f = Path(cfgdir) / "config.yaml"
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, yaml.YAMLError):
        return {}
    return dict(_flatten(data)) if isinstance(data, dict) else {}


def configuration(projects, project, cfgdir):
    config = projects.require(project)
    raw = (project.path / CONFIG_NAME).read_bytes()
    layers = [("default", _schema_defaults()), ("global", _global_values(cfgdir)),
              ("project", dict(_flatten({k: v for k, v in config.items() if k != "repos"})))]
    for repo in config["repos"]:
        rid = repo["id"]
        layers.append((f"repo:{rid}", {f"repos.{rid}.{k}": v for k, v in
                                       _flatten({k: v for k, v in repo.items() if k != "id"})}))
    by_key = {}
    for source, values in layers:
        for key, value in values.items():
            by_key.setdefault(key, []).append({"source": source, "value": value})
    items = []
    for key in sorted(by_key):
        chain = by_key[key]
        item = {"key": key, "value": chain[-1]["value"], "source": chain[-1]["source"],
                "overridden": chain[:-1]}
        items.append(item)
    return {"project": project.id, "sha256": hashlib.sha256(raw).hexdigest(), "items": items,
            "global_file": str(Path(cfgdir) / "config.yaml") if (Path(cfgdir) / "config.yaml").is_file() else None}


def _rows(projects, project, sql, args=()):
    try:
        with projects.reader(project) as conn:
            return [dict(r) for r in conn.execute(sql, args)] if conn is not None else []
    except sqlite3.Error as e:
        raise SentinelError("E_PRECONDITION", f"the registry of project {project.id} cannot be read", {"project": project.id}) from e


def configuration_history(projects, project):
    rows = _rows(projects, project, "SELECT id, scope, sha256, author, channel, created_at, comment "
                                    "FROM config_versions ORDER BY id DESC")
    return {"items": rows, "next": None}


def _version_text(projects, project, ref):
    if ref == "current":
        projects.require(project)
        try:
            return (project.path / CONFIG_NAME).read_text(encoding="utf-8")
        except OSError as e:
            raise SentinelError("E_PRECONDITION", f"{CONFIG_NAME} cannot be read", {}) from e
    rows = _rows(projects, project, "SELECT content FROM config_versions WHERE id=?", (int(ref),))
    if not rows:
        raise SentinelError("E_NOT_FOUND", f"no configuration version {ref}", {"version": ref})
    return rows[0]["content"] or ""


def configuration_diff(projects, project, query):
    refs = []
    for name in ("a", "b"):
        raw = query.get(name)
        if raw is None or not (raw == "current" or re.fullmatch(r"[0-9]{1,12}", raw)):
            raise validation(f"{name} must be a version id or the word current", name)
        refs.append(raw)
    projects.require(project)
    scrubber = projects.scrubber(project)
    texts = [scrubber.scrub_text(_version_text(projects, project, r)) for r in refs]
    diff = "".join(difflib.unified_diff(texts[0].splitlines(True), texts[1].splitlines(True),
                                        f"configuration@{refs[0]}", f"configuration@{refs[1]}"))
    return {"a": refs[0], "b": refs[1], "identical": texts[0] == texts[1], "diff": diff}


# ---- changes
def _norm(rel):
    return rel


def _tracked(path, base):
    nums, _ = _git(path, "diff", "--numstat", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", base, "--")
    stat, _ = _git(path, "diff", "--name-status", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", base, "--")
    status = {}
    parts = stat.decode("utf-8", "replace").split("\0")
    for i in range(0, len(parts) - 1, 2):
        status[parts[i + 1]] = {"A": "added", "D": "deleted"}.get(parts[i][:1], "modified")
    files = []
    for rec in nums.decode("utf-8", "replace").split("\0"):
        if not rec:
            continue
        a, _, rest = rec.partition("\t")
        d, _, name = rest.partition("\t")
        binary = a == "-" and d == "-"
        files.append({"path": name, "status": status.get(name, "modified"), "additions": 0 if binary else int(a),
                      "deletions": 0 if binary else int(d), "binary": binary})
    return files


def _untracked(path):
    out, _ = _git(path, "ls-files", "--others", "--exclude-standard", "-z", limit=4 * 1024 * 1024)
    files = []
    for name in out.decode("utf-8", "replace").split("\0"):
        if not name:
            continue
        full = path / name
        if full.is_symlink() or not full.is_file():
            continue
        try:
            data = full.read_bytes()[:DIFF_READ_CAP]
        except OSError:
            continue
        binary = b"\0" in data[:8192]
        lines = 0 if binary else len(data.splitlines())
        files.append({"path": name, "status": "added", "additions": lines, "deletions": 0, "binary": binary})
    return files


def _repo_files(workspace, repo, base, state_dir_name=None):
    path = workspace / repo["path"]
    if not path.is_dir() or not (path / ".git").exists() or not base:
        return []
    files = _tracked(path, base) + _untracked(path)
    if state_dir_name:
        files = [f for f in files if f["path"].split("/")[0] != state_dir_name]
    return sorted(files, key=lambda f: f["path"])


def _covering(eng, run, repo_id, path):
    tasks, cycles = [], []
    for t in eng.reg.rows("tasks", run_id=run["id"]):
        try:
            scope = eng.task_scope(t["id"])
        except SentinelError:
            scope = []
        if t["repo_id"] == repo_id and scopes.path_allowed(scope, repo_id, path) or \
                (t["repo_id"] != repo_id and scopes.path_allowed(scope, repo_id, path)):
            tasks.append(t["id"])
            if t.get("cycle_id") and t["cycle_id"] not in cycles:
                cycles.append(t["cycle_id"])
    return tasks, cycles


def _repo_cfg(eng, repo_id):
    for r in eng.config.get("repos") or []:
        if r["id"] == repo_id:
            return r
    return None


def changes(eng, project, slug):
    run = eng._get(slug)
    sd = os.path.relpath(eng.state_dir, project.path) if str(eng.state_dir).startswith(str(project.path)) else None
    out = []
    for rr in eng.reg.run_repos(run["id"]):
        repo = _repo_cfg(eng, rr["repo_id"])
        files = []
        head = rr["final_sha"]
        if repo:
            path = project.path / repo["path"]
            for f in _repo_files(project.path, repo, rr["baseline_sha"], sd):
                f["tasks"], f["cycles"] = _covering(eng, run, rr["repo_id"], f["path"])
                files.append(f)
            if path.is_dir() and not head:
                o, c = _git(path, "rev-parse", "HEAD", limit=256)
                head = o.decode().strip() if c == 0 else None
        out.append({"repo": rr["repo_id"], "base_sha": rr["baseline_sha"], "branch": rr["branch"],
                    "head_sha": head, "files": files})
    return {"slug": slug, "repos": out}


def _parse_hunks(text):
    hunks, cur = [], None
    old = new = 0
    for line in text.split("\n"):
        m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$", line)
        if m:
            cur = {"header": line, "old_start": int(m.group(1)), "new_start": int(m.group(2)), "lines": []}
            hunks.append(cur)
            old, new = cur["old_start"], cur["new_start"]
            continue
        if cur is None or line.startswith("\\"):
            continue
        tag, body = line[:1], line[1:]
        if tag == "+":
            cur["lines"].append({"type": "add", "old": None, "new": new, "text": body})
            new += 1
        elif tag == "-":
            cur["lines"].append({"type": "del", "old": old, "new": None, "text": body})
            old += 1
        elif tag == " ":
            cur["lines"].append({"type": "ctx", "old": old, "new": new, "text": body})
            old += 1
            new += 1
    return hunks


def _split(hunk):
    rows, dels, adds = [], [], []

    def flush():
        for i in range(max(len(dels), len(adds))):
            rows.append({"old": {"n": dels[i]["old"], "text": dels[i]["text"]} if i < len(dels) else None,
                         "new": {"n": adds[i]["new"], "text": adds[i]["text"]} if i < len(adds) else None})
        dels.clear()
        adds.clear()
    for ln in hunk["lines"]:
        if ln["type"] == "del":
            dels.append(ln)
        elif ln["type"] == "add":
            adds.append(ln)
        else:
            flush()
            rows.append({"old": {"n": ln["old"], "text": ln["text"]}, "new": {"n": ln["new"], "text": ln["text"]}})
    flush()
    return {"header": hunk["header"], "old_start": hunk["old_start"], "new_start": hunk["new_start"], "rows": rows}


def _cut(data):
    """The first DIFF_LIMIT bytes of whole lines; (bytes, truncated)."""
    if len(data) <= DIFF_LIMIT:
        return data, False
    head = data[:DIFF_LIMIT]
    return head[:head.rfind(b"\n") + 1], True


def changes_diff(eng, project, slug, query):
    mode = query.get("mode", "inline")
    if mode not in ("inline", "split"):
        raise validation("mode must be inline or split", "mode", allowed=["inline", "split"])
    repo_id, rel = query.get("repo"), query.get("path")
    if not repo_id or not rel:
        raise validation("repo and path are required", "repo" if not repo_id else "path")
    missing = SentinelError("E_NOT_FOUND", "no such changed file", {"repo": repo_id, "path": rel})
    run = eng._get(slug)
    rr = next((r for r in eng.reg.run_repos(run["id"]) if r["repo_id"] == repo_id), None)
    repo = _repo_cfg(eng, repo_id) if rr else None
    if not rr or not repo:
        raise missing
    sd = os.path.relpath(eng.state_dir, project.path) if str(eng.state_dir).startswith(str(project.path)) else None
    entry = next((f for f in _repo_files(project.path, repo, rr["baseline_sha"], sd) if f["path"] == rel), None)
    if entry is None:
        raise missing
    answer = {"repo": repo_id, "path": rel, "mode": mode, "status": entry["status"], "additions": entry["additions"],
              "deletions": entry["deletions"], "binary": entry["binary"], "truncated": False, "hunks": []}
    if entry["binary"]:
        return answer
    repo_dir = project.path / repo["path"]
    if entry["status"] == "added" and _git(repo_dir, "cat-file", "-e", f"{rr['baseline_sha']}:{rel}", limit=64)[1] != 0 \
            and _git(repo_dir, "ls-files", "--error-unmatch", "--", rel, limit=64)[1] != 0:
        full = repo_dir / rel
        if full.is_symlink() or not full.is_file():
            raise missing
        out, _ = _git(repo_dir, "diff", "--no-index", "--no-ext-diff", "--no-textconv", "-U3", "--", "/dev/null", rel)
    else:
        out, _ = _git(repo_dir, "diff", "-U3", "--no-color", "--no-renames", "--no-ext-diff", "--no-textconv",
                      rr["baseline_sha"], "--", rel)
    out, answer["truncated"] = _cut(out)
    hunks = _parse_hunks(out.decode("utf-8", "replace"))
    answer["hunks"] = hunks if mode == "inline" else [_split(h) for h in hunks]
    return answer
