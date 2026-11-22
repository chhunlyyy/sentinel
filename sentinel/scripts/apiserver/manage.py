"""Provider, agent, project-creation and repository routes: the dashboard side of `sentinel init` and the config."""
import copy
import difflib
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

import yaml

import initws
import kb_worker
import providers
import run_stage
import shared
import tasks
from errors import SentinelError
from paths import ROOT

from . import userdir
from .ops import bad, check_fields, text_field
from .projects import CONFIG_NAME
from .status import HttpError

DEFAULT_RUNNER = "claude"
ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
ROLE_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
FINAL = ("COMPLETED", "FAILED", "CANCELLED")


def live_runs(eng):
    """Slugs of version 2 runs that are not finished. Imported 0.1 runs (state LEGACY) never count: they are records only."""
    return [r["slug"] for r in eng.reg.list_runs() if r.get("workflow_version") == "2" and r["state"] not in FINAL]
MAX_DIRS = 500
GLOBAL_NAME = "config.yaml"


def conflict(message, **details):
    return HttpError("E_PRECONDITION", message, details, status=409)


def not_found(message, **details):
    return SentinelError("E_NOT_FOUND", message, details)


# ---- files
def sha_of(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write(path, text, mode=None):
    path = Path(path)
    if mode is None:
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def dump(config):
    return yaml.safe_dump(config, sort_keys=False)


def schema_check(projects, config):
    try:
        import jsonschema
    except ImportError:
        return
    err = next(iter(sorted(jsonschema.Draft202012Validator(projects._config_schema()).iter_errors(config),
                           key=lambda e: list(map(str, e.path)))), None)
    if err:
        where = "/".join(map(str, err.path))
        raise bad(f"{where + ': ' if where else ''}{err.message}", where or None)


def global_file(cfgdir):
    return Path(cfgdir) / GLOBAL_NAME


def load_global(cfgdir):
    try:
        data = yaml.safe_load(global_file(cfgdir).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def read_project_config(project):
    f = project.path / CONFIG_NAME
    try:
        text = f.read_text(encoding="utf-8")
        config = yaml.safe_load(text)
    except (OSError, yaml.YAMLError):
        raise SentinelError("E_PRECONDITION", f"{CONFIG_NAME} of {project.id} cannot be read", {"project": project.id})
    if not isinstance(config, dict):
        raise SentinelError("E_PRECONDITION", f"{CONFIG_NAME} of {project.id} is not a mapping", {"project": project.id})
    return text, config


# ---- providers and the orchestrator
def project_config(ctx, pid):
    if not pid:
        return None, {}
    project = ctx.projects.get(pid)
    ctx.project = project
    return project, ctx.projects.require(project)


def providers_view(ctx):
    _, config = project_config(ctx, ctx.query.get("project"))
    return {"items": providers.detect(config), "orchestrator": getattr(ctx.api, "orchestrator", None)}


def probe(ctx, rid):
    _, config = project_config(ctx, ctx.query.get("project"))
    if rid not in run_stage.all_runners(config):
        raise not_found(f"no provider {rid}", provider=rid)
    return providers.probe(rid, config)


def orchestrator_view(ctx):
    return {"id": getattr(ctx.api, "orchestrator", None), "installed_ids": providers.installed_ids(None)}


def set_orchestrator(ctx, body):
    check_fields(body, ("id",))
    rid = body.get("id")
    if rid is not None:
        if not isinstance(rid, str):
            raise bad("id must be a string or null", "id")
        if rid not in run_stage.all_runners({}):
            raise bad(f"unknown provider {rid}", "id", allowed=sorted(run_stage.all_runners({})))
        if rid not in providers.installed_ids(None):
            raise SentinelError("E_PRECONDITION", f"provider {rid} is not installed", {"id": rid})
    api = ctx.api
    api.orchestrator = rid
    if getattr(api, "dispatcher", None) is not None and hasattr(api.dispatcher, "orchestrator"):
        api.dispatcher.orchestrator = rid
    info = userdir.read_server_json(api.cfgdir)
    if info and info.get("pid") == api.pid:
        info["orchestrator"] = rid
        userdir.write_server_json(api.cfgdir, info)
    return orchestrator_view(ctx)


# ---- agents
def _agent_roles(config):
    roles = tasks.agent_roles()
    for r in config.get("repos") or []:
        if isinstance(r, dict) and r.get("role"):
            role = f"{r['role']}-coder"
            if role not in roles:
                roles.append(role)
    for role in (config.get("agents") or {}):
        if role not in roles:
            roles.append(role)
    return roles


def agents_view(project, config, raw, cfgdir):
    glob = load_global(cfgdir)
    own, shared = config.get("agents") or {}, glob.get("agents") or {}
    items = []
    for role in _agent_roles(config):
        item = {"role": role, "runner": None, "model": None, "source": "default"}
        for source, layer in (("global", shared), ("project", own)):
            entry = layer.get(role) if isinstance(layer.get(role), dict) else {}
            if entry.get("runner") or entry.get("model"):
                item["source"] = source
            if entry.get("runner"):
                item["runner"] = entry["runner"]
            if entry.get("model"):
                item["model"] = entry["model"]
        items.append(item)
    prov = {"default": None, "fallback": [], "disabled": []}
    for layer in (glob.get("providers"), config.get("providers")):
        if isinstance(layer, dict):
            for k in prov:
                if layer.get(k) is not None:
                    prov[k] = layer[k]
    for item in items:
        if not item["runner"]:
            item["runner"] = prov["default"] or DEFAULT_RUNNER
    return {"project": project.id if project else None, "roles": [i["role"] for i in items], "items": items,
            "providers": prov, "single_model": run_stage.single_model(config), "sha256": sha_of(raw) if raw is not None else None}


def agents_get(ctx):
    pid = ctx.query.get("project")
    if not pid:
        return agents_view(None, {}, None, ctx.api.cfgdir)
    project = ctx.projects.get(pid)
    ctx.project = project
    ctx.projects.require(project)
    raw, config = read_project_config(project)
    return agents_view(project, config, raw, ctx.api.cfgdir)


def _apply_agents(target, body, runners):
    """Merge the request into `target` (a config or the global mapping). Returns nothing; raises E_VALIDATION."""
    agents = body.get("agents")
    if agents is not None:
        if not isinstance(agents, dict):
            raise bad("agents must be an object", "agents")
        cur = target.setdefault("agents", {})
        for role, spec in agents.items():
            if not ROLE_KEY_RE.match(str(role)):
                raise bad(f"bad role name {role!r}", "agents")
            if not isinstance(spec, dict):
                raise bad(f"agents.{role} must be an object", "agents")
            for k in spec:
                if k not in ("runner", "model"):
                    raise bad(f"unknown field {k} in agents.{role}", "agents")
            entry = dict(cur.get(role) or {})
            for k in ("runner", "model"):
                if k not in spec:
                    continue
                v = spec[k]
                if v is None or v == "":
                    entry.pop(k, None)
                elif not isinstance(v, str) or (k == "model" and (v.startswith("-") or " " in v.strip())):
                    raise bad(f"agents.{role}.{k} must be a name", "agents")
                elif k == "runner" and v not in runners:
                    raise bad(f"unknown runner {v}", "agents", allowed=sorted(runners))
                else:
                    entry[k] = v
            if entry:
                cur[role] = entry
            else:
                cur.pop(role, None)
        if not cur:
            target.pop("agents", None)
    prov = body.get("providers")
    if prov is not None:
        if not isinstance(prov, dict):
            raise bad("providers must be an object", "providers")
        for k in prov:
            if k not in ("default", "fallback", "disabled"):
                raise bad(f"unknown field {k} in providers", "providers")
        cur = dict(target.get("providers") or {})
        for k, v in prov.items():
            if v is None:
                cur.pop(k, None)
                continue
            ids = [v] if k == "default" else v
            if k == "default" and not isinstance(v, str) or k != "default" and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
                raise bad(f"providers.{k} has the wrong type", "providers")
            unknown = [x for x in ids if x not in runners]
            if unknown:
                raise bad(f"unknown runner {unknown[0]}", "providers", allowed=sorted(runners))
            cur[k] = v
        if cur:
            target["providers"] = cur
        else:
            target.pop("providers", None)


def agents_put(ctx, body):
    check_fields(body, ("project", "scope", "sha256", "agents", "providers", "single_model"), ("scope",))
    scope = body["scope"]
    if scope not in ("project", "global"):
        raise bad("scope must be project or global", "scope", allowed=["project", "global"])
    sm = body.get("single_model")
    if sm is not None and not isinstance(sm, bool):
        raise bad("single_model must be true or false", "single_model")
    pid = body.get("project")
    if pid is not None and not isinstance(pid, str):
        raise bad("project must be a string", "project")
    if scope == "project":
        if not pid:
            raise bad("project is required for scope project", "project")
        return _put_project(ctx, pid, body, sm)
    if sm is not None:
        raise bad("single_model is a project setting", "single_model")
    project = config = None
    if pid:
        project, config = project_config(ctx, pid)
    runners = run_stage.all_runners(config or {})
    cfgdir = ctx.api.cfgdir
    userdir.ensure_dir(cfgdir)
    data = load_global(cfgdir)
    glob = {k: data[k] for k in ("agents", "providers") if k in data}
    _apply_agents(glob, body, runners)
    for key in ("agents", "providers"):
        data.pop(key, None)
    data.update(glob)
    import jsonschema
    props = json.loads((ROOT / "core" / "schema" / "config.schema.json").read_text())["properties"]
    err = next(iter(jsonschema.Draft202012Validator({"type": "object", "properties": {k: props[k] for k in ("agents", "providers")}})
                    .iter_errors(glob)), None)
    if err:
        raise bad(err.message, "/".join(map(str, err.path)) or None)
    atomic_write(global_file(cfgdir), dump(data), 0o600)
    if project:
        raw, cfg = read_project_config(project)
        return agents_view(project, cfg, raw, cfgdir)
    return agents_view(None, {}, None, cfgdir)


def _put_project(ctx, pid, body, single_model):
    project = ctx.projects.get(pid)
    ctx.project = project
    with ctx.projects.engine(project, ctx.user, "dashboard") as eng:
        raw, config = read_project_config(project)
        sha = body.get("sha256")
        if sha is not None and sha != sha_of(raw):
            raise conflict("the project configuration changed; reload it", expected=sha_of(raw))
        _apply_agents(config, body, run_stage.all_runners(config))
        if single_model is not None:
            config["single_model"] = single_model
        schema_check(ctx.projects, config)
        text = dump(config)
        write_config(eng, project, text, ctx.user)
    raw, config = read_project_config(project)
    return agents_view(project, config, raw, ctx.api.cfgdir)


def write_config(eng, project, text, user, comment=None):
    """Atomic write of the project config plus a config_versions row and an audit line."""
    atomic_write(project.path / CONFIG_NAME, text)
    with eng.reg.transaction():
        eng.reg.store_config_version("workspace", text, author=user, channel="dashboard", comment=comment)
        eng.reg.add_audit(user, "dashboard", "config_changed", project.id, reason=comment)


# ---- profiles
def profile_items():
    out = []
    for f in sorted((ROOT / "profiles").glob("*.json")):
        try:
            p = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        item = {"id": p.get("id") or f.stem, "detect": list(p.get("detect") or [])}
        if p.get("label") or p.get("name"):
            item["label"] = p.get("label") or p.get("name")
        out.append(item)
    return out


def profiles_view():
    shapes = json.loads((ROOT / "templates" / "shapes.json").read_text())
    roles = sorted({r["role"] for s in shapes.values() for r in s["repos"]} | {"app"})
    return {"items": profile_items(), "roles": roles}


# ---- file system
def fs_dirs(query):
    raw = query.get("path") or str(Path.home())
    if "\0" in raw:
        raise bad("path must not contain NUL", "path")
    if not os.path.isabs(raw):
        raise bad("path must be absolute", "path")
    path = os.path.realpath(raw)
    if not os.path.isdir(path):
        raise not_found("no such directory", path=raw)
    items = []
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir():
                        items.append({"name": e.name, "path": os.path.join(path, e.name),
                                      "is_git": os.path.exists(os.path.join(path, e.name, ".git"))})
                except OSError:
                    continue
    except OSError as e:
        raise SentinelError("E_PRECONDITION", f"cannot list {raw}: {e.strerror}", {"path": raw})
    items.sort(key=lambda i: i["name"].lower())
    parent = os.path.dirname(path)
    return {"path": path, "parent": parent if parent != path else None, "items": items[:MAX_DIRS]}


# ---- repositories
def _abs_path(value, field, base=None):
    if not isinstance(value, str) or not value.strip():
        raise bad(f"{field} must be a path", field)
    if "\0" in value:
        raise bad(f"{field} must not contain NUL", field)
    p = Path(value)
    if not p.is_absolute():
        if base is None:
            raise bad(f"{field} must be absolute", field)
        if ".." in p.parts:
            raise bad(f"{field} must not contain ..", field)
        p = Path(base) / p
    return p


def parse_repo(spec, base, taken, field="repos"):
    if not isinstance(spec, dict):
        raise bad("a repo must be an object", field)
    check_fields(spec, ("id", "path", "role", "profile"), ("path", "role"))
    path = _abs_path(spec["path"], f"{field}.path", base)
    real = Path(os.path.realpath(path))
    if not real.is_dir():
        raise bad(f"repo path is not an existing directory: {spec['path']}", f"{field}.path")
    role = text_field(spec, "role")
    if not ID_RE.match(role):
        raise bad("role must be lowercase letters, digits and dashes", f"{field}.role")
    rid = text_field(spec, "id", required=False) or re.sub(r"[^a-z0-9]+", "-", real.name.lower()).strip("-") or role
    if not ID_RE.match(rid):
        rid = f"r-{rid}".strip("-")
    if not ID_RE.match(rid):
        raise bad("repo id must be lowercase letters, digits and dashes, starting with a letter", f"{field}.id")
    explicit = bool(spec.get("id"))
    if rid in taken:
        if explicit:
            raise conflict(f"repo id {rid} is already used", id=rid)
        n = 2
        while f"{rid}-{n}" in taken:
            n += 1
        rid = f"{rid}-{n}"
    profile = text_field(spec, "profile", required=False) or initws.detect_profile(real)
    known = {p["id"] for p in profile_items()} | {"generic"}
    if profile not in known:
        raise bad(f"unknown profile {profile}", f"{field}.profile", allowed=sorted(known))
    base_real = Path(os.path.realpath(base))
    try:
        stored = "./" + str(real.relative_to(base_real))
    except ValueError:
        stored = str(real)
    if stored == "./.":
        stored = "."
    return {"id": rid, "path": stored, "role": role, "profile": profile}


def add_repository(ctx, pid, body):
    project = ctx.projects.get(pid)
    ctx.project = project
    ctx.projects.require(project)
    with ctx.projects.engine(project, ctx.user, "dashboard") as eng:
        raw, config = read_project_config(project)
        taken = {r.get("id") for r in config.get("repos") or [] if isinstance(r, dict)}
        repo = parse_repo(body, project.path, taken, "path")
        config.setdefault("repos", []).append(repo)
        schema_check(ctx.projects, config)
        write_config(eng, project, dump(config), ctx.user, f"repository {repo['id']} added")
    return repo


def remove_repository(ctx, pid, rid):
    project = ctx.projects.get(pid)
    ctx.project = project
    ctx.projects.require(project)
    with ctx.projects.engine(project, ctx.user, "dashboard") as eng:
        raw, config = read_project_config(project)
        repos = config.get("repos") or []
        if rid not in [r.get("id") for r in repos if isinstance(r, dict)]:
            raise not_found(f"no repository {rid}", repo=rid)
        if len(repos) <= 1:
            raise conflict("a project needs at least one repository")
        live = live_runs(eng)
        if live:
            raise conflict("repositories cannot be removed while a run is active", runs=live[:10])
        config["repos"] = [r for r in repos if r.get("id") != rid]
        write_config(eng, project, dump(config), ctx.user, f"repository {rid} removed")
    return {"removed": rid}


# ---- projects
def delete_project(ctx, pid):
    """Unregister the project. Nothing on disk is deleted: the folder, the configuration and .sentinel stay."""
    project = ctx.projects.get(pid)
    ctx.project = project
    if ctx.projects.probe(project)[0] == "available":
        with ctx.projects.engine(project, ctx.user, "dashboard") as eng:
            live = live_runs(eng)
            if live:
                raise conflict("a project with an active run cannot be deleted", runs=live[:10])
            eng.reg.add_audit(ctx.user, "dashboard", "project_unregistered", project.id,
                              reason="removed from the dashboard; files kept")
    if not userdir.unregister_project(ctx.api.cfgdir, pid):
        raise not_found(f"no project {pid}", project=pid)
    return {"removed": pid}


def create_project(ctx, body):
    from shared import looks_like_git_url
    check_fields(body, ("name", "path", "shared", "repos"), ("name", "path"))
    name = text_field(body, "name").strip()
    if not name:
        raise bad("name must not be empty", "name")
    path = _abs_path(body["path"], "path")
    shared = body.get("shared") or {"mode": "local"}
    if not isinstance(shared, dict):
        raise bad("shared must be an object", "shared")
    check_fields(shared, ("mode", "url"))
    mode = shared.get("mode", "local")
    if mode not in ("local", "git"):
        raise bad("shared.mode must be local or git", "shared.mode", allowed=["local", "git"])
    url = None
    if mode == "git":
        url = (shared.get("url") or "").strip() if isinstance(shared.get("url"), str) else ""
        if not url or not looks_like_git_url(url):
            raise bad("shared.url must be a git URL", "shared.url")
    specs = body.get("repos")
    if not isinstance(specs, list) or not specs:
        raise bad("at least one repo is required (a configuration with no repos is not valid)", "repos")
    ws = Path(os.path.realpath(path))
    if (ws / CONFIG_NAME).exists():
        raise conflict(f"{CONFIG_NAME} already exists in {ws}", path=str(ws))
    if not ws.exists() and not ws.parent.is_dir():
        raise bad("the parent folder of path must exist", "path")
    if ws.exists() and not ws.is_dir():
        raise bad("path is not a directory", "path")
    repos, taken = [], set()
    for spec in specs:
        repo = parse_repo(spec, ws, taken)
        taken.add(repo["id"])
        repos.append(repo)
    seed = {k: v for k, v in load_global(ctx.api.cfgdir).items() if k in ("agents", "providers") and v}
    config = initws.build_config("custom", repos, url, mode == "local", seed)
    schema_check(ctx.projects, config)
    ws.mkdir(exist_ok=True)
    initws.write_workspace(ws, config)
    userdir.ensure_dir(ctx.api.cfgdir)
    entry, _ = userdir.register_workspace(ctx.api.cfgdir, ws, name)
    return ctx.projects.get(entry["id"])


def register_project(ctx, body):
    check_fields(body, ("path",), ("path",))
    ws = Path(os.path.realpath(_abs_path(body["path"], "path")))
    if not ws.is_dir() or not (ws / CONFIG_NAME).is_file():
        raise not_found(f"no {CONFIG_NAME} in {ws}", path=str(ws))
    try:
        config = yaml.safe_load((ws / CONFIG_NAME).read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("not a mapping")
        schema_check(ctx.projects, config)
    except (OSError, ValueError, yaml.YAMLError, SentinelError) as e:
        raise conflict(f"{CONFIG_NAME} in {ws} is not valid: {getattr(e, 'message', e)}", path=str(ws))
    userdir.ensure_dir(ctx.api.cfgdir)
    entry, created = userdir.register_workspace(ctx.api.cfgdir, ws)
    return created, ctx.projects.get(entry["id"])


# ---- W3 Setup and Detection
def _git_run(directory, *args, timeout=10):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    return subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True, timeout=timeout, env=env)


def detect_paths(body):
    if not isinstance(body, dict):
        raise bad("body must be an object", "paths")
    check_fields(body, ("paths",), ("paths",))
    paths = body.get("paths")
    if not isinstance(paths, list):
        raise bad("paths must be a list of directory paths", "paths")
    items = []
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise bad("each path must be a non-empty string", "paths")
        if "\0" in raw:
            raise bad("path must not contain NUL", "paths")
        if not os.path.isabs(raw):
            raise bad(f"path must be absolute: {raw}", "paths")
        real = Path(os.path.realpath(raw))
        if not real.is_dir():
            raise bad(f"path is not an existing directory: {raw}", "paths")

        res = _git_run(real, "rev-parse", "--is-inside-work-tree")
        is_git = (res.returncode == 0) and ((real / ".git").exists() or (real / ".git").is_file() or (real / ".git").is_dir())

        current_branch = None
        default_branch = None
        local_branches = []
        tracked_branches = []

        if is_git:
            res_curr = _git_run(real, "symbolic-ref", "-q", "--short", "HEAD")
            if res_curr.returncode == 0 and res_curr.stdout.strip():
                current_branch = res_curr.stdout.strip()
            else:
                res_det = _git_run(real, "rev-parse", "--abbrev-ref", "HEAD")
                if res_det.returncode == 0 and res_det.stdout.strip() != "HEAD":
                    current_branch = res_det.stdout.strip()

            res_def = _git_run(real, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
            if res_def.returncode == 0 and res_def.stdout.strip():
                orig = res_def.stdout.strip()
                default_branch = orig.split("/", 1)[1] if "/" in orig else orig

            res_branches = _git_run(real, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
            if res_branches.returncode == 0:
                local_branches = [b.strip() for b in res_branches.stdout.splitlines() if b.strip()]

            if not default_branch:
                if "main" in local_branches or _git_run(real, "rev-parse", "--verify", "-q", "refs/heads/main").returncode == 0:
                    default_branch = "main"
                elif "master" in local_branches or _git_run(real, "rev-parse", "--verify", "-q", "refs/heads/master").returncode == 0:
                    default_branch = "master"
                else:
                    default_branch = current_branch

            if "develop" in local_branches or _git_run(real, "rev-parse", "--verify", "-q", "refs/heads/develop").returncode == 0:
                tracked_branches.append("develop")
            if default_branch and default_branch not in tracked_branches:
                tracked_branches.append(default_branch)
            if not tracked_branches and current_branch:
                tracked_branches.append(current_branch)

        profile = initws.detect_profile(real)
        from .readroutes import COMMAND_KEYS, _profile
        commands = dict.fromkeys(COMMAND_KEYS, "")
        p_data = _profile(profile)
        if p_data:
            commands.update({k: v for k, v in (p_data.get("commands") or {}).items() if k in COMMAND_KEYS})

        items.append({
            "path": str(raw),
            "is_git": is_git,
            "current_branch": current_branch,
            "default_branch": default_branch,
            "local_branches": local_branches,
            "profile": profile,
            "commands": commands,
            "tracked_branches": tracked_branches,
        })
    return {"items": items}


def test_shared(body):
    if not isinstance(body, dict):
        raise bad("body must be an object", "url")
    check_fields(body, ("url",), ("url",))
    url = body.get("url")
    if not isinstance(url, str) or not url.strip():
        raise bad("url must be a non-empty string", "url")
    if "\0" in url:
        raise bad("url must not contain NUL", "url")
    url = url.strip()
    # never let a request choose git options (e.g. --upload-pack=<command>): only a git URL or a path
    if url.startswith("-") or not shared.looks_like_git_url(url):
        raise bad("url must be a git URL (https://, ssh://, git://, file://, git@host:...) or a path", "url")

    ok, detail, count = shared.verify_remote(url, timeout=25)
    if not ok:
        return {"ok": False, "read": False, "write": False, "refs": 0, "error": detail}

    write = "unknown"
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        try:
            subprocess.run(["git", "init", str(td_path)], capture_output=True, timeout=5)
            subprocess.run(["git", "-C", str(td_path), "config", "user.name", "sentinel"], capture_output=True, timeout=5)
            subprocess.run(["git", "-C", str(td_path), "config", "user.email", "sentinel@localhost"], capture_output=True, timeout=5)
            subprocess.run(["git", "-C", str(td_path), "commit", "--allow-empty", "-m", "probe"], capture_output=True, timeout=5)
            env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
            res = subprocess.run(["git", "-C", str(td_path), "push", "--dry-run", url, "HEAD:refs/sentinel/test-probe"],
                                 capture_output=True, text=True, timeout=25, env=env)
            if res.returncode == 0:
                write = True
            else:
                err = (res.stderr or "").lower()
                if any(t in err for t in ("permission denied", "access denied", "forbidden", "unauthorized", "auth", "403")):
                    write = False
                else:
                    write = "unknown"
        except Exception:
            write = "unknown"

    return {"ok": True, "read": True, "write": write, "refs": count, "error": ""}


def suggest_routing():
    return providers.suggest_routing()


def config_form(projects, project):
    raw, config = read_project_config(project)
    schema = json.loads((ROOT / "core" / "schema" / "config.schema.json").read_text(encoding="utf-8"))
    props = schema.get("properties") or {}

    sections = []
    flat_fields = []

    section_keys = ("factory", "knowledge", "policies", "limits", "verification", "rules", "qa", "routing", "state")
    for sec_name in section_keys:
        sec_schema = props.get(sec_name)
        if not isinstance(sec_schema, dict):
            continue
        sec_title = sec_schema.get("title") or sec_name.replace("_", " ").title()
        sec_fields = []
        for field_name, field_schema in (sec_schema.get("properties") or {}).items():
            if not isinstance(field_schema, dict):
                continue
            field_path = f"{sec_name}.{field_name}"
            field_type = field_schema.get("type", "string")
            enum_vals = field_schema.get("enum")
            default_val = field_schema.get("default")
            help_text = field_schema.get("description", "")
            current_val = (config.get(sec_name) or {}).get(field_name) if isinstance(config.get(sec_name), dict) else None
            if current_val is None and default_val is not None:
                current_val = default_val
            editable = not (sec_name == "state" and field_name == "shared_repo")
            item = {
                "path": field_path,
                "type": field_type,
                "enum": enum_vals,
                "default": default_val,
                "value": current_val,
                "help": help_text,
                "editable": editable,
            }
            sec_fields.append(item)
            flat_fields.append(item)
        sections.append({"id": sec_name, "title": sec_title, "fields": sec_fields})

    if "single_model" in props:
        field_schema = props["single_model"]
        item = {
            "path": "single_model",
            "type": field_schema.get("type", "boolean"),
            "enum": field_schema.get("enum"),
            "default": field_schema.get("default", True),
            "value": config.get("single_model", True),
            "help": field_schema.get("description", ""),
            "editable": True,
        }
        flat_fields.append(item)
        sections.append({"id": "general", "title": "General", "fields": [item]})

    repos = config.get("repos") or []
    if repos:
        repo_fields = []
        for idx, r in enumerate(repos):
            if not isinstance(r, dict):
                continue
            repo_fields.append({
                "path": f"repos.{idx}.path",
                "type": "string",
                "enum": None,
                "default": None,
                "value": r.get("path"),
                "help": "Repository directory path",
                "editable": False,
            })
            for k, h in (("role", "Repository role"), ("profile", "Repository profile")):
                repo_fields.append({
                    "path": f"repos.{idx}.{k}",
                    "type": "string",
                    "enum": None,
                    "default": None,
                    "value": r.get(k),
                    "help": h,
                    "editable": True,
                })
            for cmd in ("build", "test", "lint", "typecheck", "mutate"):
                repo_fields.append({
                    "path": f"repos.{idx}.commands.{cmd}",
                    "type": "string",
                    "enum": None,
                    "default": "",
                    "value": (r.get("commands") or {}).get(cmd, ""),
                    "help": f"{cmd.title()} command",
                    "editable": True,
                })
        flat_fields.extend(repo_fields)
        sections.append({"id": "repos", "title": "Repositories", "fields": repo_fields})

    return {
        "project": project.id,
        "sha256": sha_of(raw),
        "sections": sections,
        "fields": flat_fields,
    }


def _set_path(target, path, value):
    parts = path.split(".")
    cur = target
    for i, p in enumerate(parts[:-1]):
        nxt = parts[i + 1]
        if isinstance(cur, list):
            idx = int(p)
            cur = cur[idx]
        elif isinstance(cur, dict):
            if nxt.isdigit():
                cur = cur.setdefault(p, [])
            else:
                cur = cur.setdefault(p, {})
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    elif isinstance(cur, dict):
        if value is None:
            cur.pop(last, None)
        else:
            cur[last] = value


def _apply_changes_checked(projects, project, body):
    raw, config = read_project_config(project)
    changes = body if isinstance(body, list) else body.get("changes") if isinstance(body, dict) else None
    if changes is None or not isinstance(changes, list):
        raise bad("changes must be a list of {path, value} objects", "changes")
    new_config = copy.deepcopy(config)
    for ch in changes:
        if not isinstance(ch, dict) or "path" not in ch:
            raise bad("each change must be an object with path and value", "changes")
        p = str(ch["path"])
        if p == "state.shared_repo" or p.startswith("state.shared_repo."):
            raise bad("state.shared_repo cannot be modified via config form", "state.shared_repo")
        if re.search(r"^repos(\.\d+|\[\d+\])?\.path$", p) or (p.startswith("repos") and p.endswith(".path")):
            raise bad("repository path cannot be modified via config form", p)
        _set_path(new_config, p, ch.get("value"))

    schema_check(projects, new_config)
    old_lines = raw.splitlines(keepends=True)
    new_text = dump(new_config)
    new_lines = new_text.splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(old_lines, new_lines, fromfile="sentinel.config.yaml", tofile="sentinel.config.yaml (preview)"))
    return raw, new_config, new_text, diff, changes


def config_preview(ctx, project, body):
    _, _, _, diff, changes = _apply_changes_checked(ctx.projects, project, body)
    return {"project": project.id, "valid": True, "diff": diff, "changes": changes}


def config_save(ctx, project, body):
    with ctx.projects.engine(project, ctx.user, "dashboard") as eng:
        _, _, new_text, diff, _ = _apply_changes_checked(ctx.projects, project, body)
        comment = body.get("comment") if isinstance(body, dict) else None
        write_config(eng, project, new_text, ctx.user, comment=comment or "Config updated via dashboard form")
        return {"ok": True, "project": project.id, "sha256": sha_of(new_text), "diff": diff}


_BACKFILL_TOKENS = {}


def knowledge_ingest(ctx, pid):
    project = ctx.projects.get(pid)
    ctx.project = project
    ctx.projects.require(project)
    with ctx.projects.engine(project, ctx.user, "dashboard") as eng:
        job_id = kb_worker.enqueue_ingest(eng.reg)
        kb_worker.spawn_worker(project.path)
        eng.reg.add_audit(ctx.user, "dashboard", "knowledge_ingest", project.id, reason=f"job={job_id}")
        return {"ok": True, "job": job_id, "state": "queued"}


def knowledge_snapshot(ctx, pid):
    project = ctx.projects.get(pid)
    ctx.project = project
    ctx.projects.require(project)
    with ctx.projects.engine(project, ctx.user, "dashboard") as eng:
        job_id = kb_worker.enqueue_snapshot(eng.reg)
        kb_worker.spawn_worker(project.path)
        eng.reg.add_audit(ctx.user, "dashboard", "knowledge_snapshot", project.id, reason=f"job={job_id}")
        return {"ok": True, "job": job_id, "state": "queued"}


def knowledge_backfill_estimate(ctx, pid, body):
    project = ctx.projects.get(pid)
    ctx.project = project
    config = ctx.projects.require(project)
    import knowledge
    shared_dir = str(shared.Shared(project.path, config).dir)
    since = body.get("since") if isinstance(body, dict) else None
    repo = body.get("repo") if isinstance(body, dict) else None
    estimate = knowledge.estimate_backfill(shared_dir, str(project.path), config, since=since, only_repo=repo)
    total = sum(c for r in estimate.values() for c in r.values())
    token = secrets.token_hex(16)
    _BACKFILL_TOKENS[token] = {"pid": pid, "estimate": estimate, "total": total, "since": since, "repo": repo, "at": time.time()}
    return {"token": token, "estimate": estimate, "total": total, "since": since, "repo": repo}


def knowledge_backfill(ctx, pid, body):
    project = ctx.projects.get(pid)
    ctx.project = project
    config = ctx.projects.require(project)
    token = body.get("token") if isinstance(body, dict) else None
    if not token or not isinstance(token, str):
        raise bad("estimate token is required", "token")
    info = _BACKFILL_TOKENS.get(token)
    if not info or info.get("pid") != pid:
        raise bad("invalid or expired estimate token", "token")
    _BACKFILL_TOKENS.pop(token, None)
    # The backfill is an ingest job for the background worker: it can take many agent calls, so it never runs in
    # the request or under the engine lock.
    with ctx.projects.engine(project, ctx.user, "dashboard") as eng:
        job_id = kb_worker.enqueue_ingest(eng.reg)
        kb_worker.spawn_worker(project.path)
        eng.reg.add_audit(ctx.user, "dashboard", "knowledge_backfill", project.id,
                          reason=f"job={job_id}; estimated={info.get('total')}")
        return {"ok": True, "job": job_id, "state": "queued", "estimated": info.get("total")}
