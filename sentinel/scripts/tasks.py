"""Task contracts and task lifecycle (PC-01): task-v1, agent-result-v1, result ingestion.

TaskOps is mixed into Engine. Every state change runs in one registry transaction through
machines.check_task and stores its event. The engine decides COMPLETED or FAILED; the agent's
result file and its claims never decide anything (VER-02).
Source: docs/architecture/agent-runtime.md, plan/v1.1/phaseC/README.md.
"""
import collections
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone

import yaml

import adapters
import boundary
import machines
import scopes
from errors import SentinelError
from paths import ROOT
from registry import _new_id, _now
from util import sha_bytes

DEFAULT_TIMEOUT = 5400
DEFAULT_RETRIES = 2
READ_ONLY_ROLES = {"specifier", "test_designer", "reviewer", "qa", "retrospective"}
OPEN_STATES = ("CREATED", "QUEUED", "RUNNING", "WAITING_FOR_INPUT")
RETRY_CODES = ("E_EXIT", "E_TIMEOUT", "E_RESULT_SCHEMA", "E_AGENT")
STDERR_LINES, STDERR_LINE_CAP = 20, 500  # what a retry brief may carry of the last attempt
WATCHED = ("sentinel.config.yaml", ".claude/agents", ".claude/skills", "AGENTS.md")
_schemas = {}
IGNORE_RULES = re.compile(r"(^|/)\.gitignore$|^\.git/(info/exclude|config)$")  # rules that decide which files git shows


def load_schema(name):
    """task-v1 or agent-result-v1, from sentinel/core/schema/<name>.schema.json."""
    if name not in _schemas:
        _schemas[name] = json.loads((ROOT / "core" / "schema" / f"{name}.schema.json").read_text(encoding="utf-8"))
    return _schemas[name]


def _path(parts, indexes):
    out = ""
    for p in parts:
        if isinstance(p, int):
            out += f"[{p}]" if indexes else ""
        else:
            out += ("." if out else "") + str(p)
    return out


def schema_problems(name, doc, indexes=False):
    """[(field, text)] for every schema violation of `doc`, sorted by field."""
    import jsonschema
    found = []
    for err in jsonschema.Draft202012Validator(load_schema(name)).iter_errors(doc):
        base = _path(err.absolute_path, indexes)
        if err.validator == "required":
            for missing in err.validator_value:
                if missing not in err.instance:
                    found.append((f"{base}.{missing}" if base else missing, f"{missing}: required property missing"))
            continue
        found.append((base, f"{base}: {err.message}" if base else err.message))
    return sorted(found)


def select_adapter(config, role, repo=None):
    """(adapter, provider, model) for a role from a config snapshot. Workflows never name a provider (PRV-05)."""
    from run_stage import find_route, single_model
    native = ("native", "native", None)
    if single_model(config):
        return native
    agent = (config.get("agents") or {}).get(role) or {}
    route = agent if agent.get("runner") else (find_route(config, role, repo) or {})
    runner = route.get("runner")
    if not runner or runner == "native":
        return native
    return "cli", runner, route.get("model")


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


TDD_DEFAULT_RETRIES = {"red": 2, "green": 3, "refactor": 2}


def retry_cap(config, role, task_cap=None):
    """Retries after the first attempt: task, agents.<role>.max_retries, limits.<role>_retries, then 2. A TDD role
    (tdd_red, ...) reads tdd.<phase>_retries, then limits.<phase>_retries, then 2, 3 or 2 (Phase D point 8); agents.<role>
    does not apply to it."""
    if _int(task_cap) and task_cap >= 0:
        return task_cap
    if role.startswith("tdd_"):
        phase = role[4:]
        for value in ((config.get("tdd") or {}).get(f"{phase}_retries"), (config.get("limits") or {}).get(f"{phase}_retries")):
            if _int(value) and value >= 0:
                return value
        return TDD_DEFAULT_RETRIES.get(phase, DEFAULT_RETRIES)
    for value in (((config.get("agents") or {}).get(role) or {}).get("max_retries"),
                  (config.get("limits") or {}).get(f"{role}_retries")):
        if _int(value) and value >= 0:
            return value
    return DEFAULT_RETRIES


def _seconds_since(iso):
    try:
        then = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return round((datetime.now(timezone.utc) - then).total_seconds(), 3)


class TaskOps:
    # ---- lookups
    def _task_row(self, task_id):
        row = self.reg.get_row("tasks", task_id) if isinstance(task_id, str) else None
        if not row:
            raise SentinelError("E_NOT_FOUND", f"no task {task_id}", {"task": task_id})
        return row

    def get_task(self, task_id):
        return self._task_row(task_id)

    def task_dir(self, slug, task_id):
        return self.run_dir(slug) / "tasks" / task_id

    def _run_config(self, run):
        """The config the run started with (CFG-08)."""
        row = self.reg.get_config_version(run["config_snapshot_id"]) if run.get("config_snapshot_id") else None
        if row:
            try:
                cfg = yaml.safe_load(row["content"])
            except yaml.YAMLError:
                cfg = None
            if isinstance(cfg, dict):
                return cfg
        return self.config

    def adapter_for(self, runner, slug=None):
        """The adapter object for a runner name ("native" or a runner of the config)."""
        run = self.reg.get_run(slug) if slug else None
        cfg = self._run_config(run) if run else self.config
        return adapters.get_adapter("native" if runner == "native" else "cli", cfg, runner)

    def workflow_graph(self, tier):
        """The planned stages of a tier as provider-free nodes (VIS-03a). Sequential; Phase D plans the real graph."""
        import engine
        stages = engine.TIER_STAGES[tier]
        return [{"stage": s, "depends_on": [stages[i - 1]] if i else []} for i, s in enumerate(stages)]

    # ---- creation
    def create_task(self, slug, role, objective=None, repos=None, **kw):
        """Create a CREATED task and its task-v1 file. Keywords: write, read, timeout_seconds, max_retries,
        depends_on, cycle_id, retry_of, brief, must_follow_tdd, readonly_approved."""
        self._tdd_precheck(slug, role, repos if isinstance(repos, list) else [])
        with self.reg.transaction():
            run = self._get_v2(slug)
            row = self._make_task(run, role, objective, repos, **kw)
        return row

    def _spec_inputs(self, run):
        inp = {}
        for gate, kind in (("specification", "spec"), ("gherkin", "gherkin")):
            ap = self._latest_approval(run, gate, "APPROVED")
            art = self.reg.get_row("artifacts", ap["artifact_id"]) if ap else None
            if not art:
                continue
            if kind == "spec":
                inp["specification"] = {"path": art["path"], "sha256": ap["sha256"]}
            else:
                base = self.state_dir / art["path"]
                files = sorted(p.relative_to(self.state_dir).as_posix() for p in base.rglob("*.feature")) if base.is_dir() else []
                inp["gherkin"] = {"paths": files, "sha256": ap["sha256"]}
        return inp

    def _known_repos(self, run, cfg):
        ids = {r.get("id") for r in cfg.get("repos") or [] if isinstance(r, dict)}
        return ids | {r["repo_id"] for r in self.reg.run_repos(run["id"])}

    def _make_task(self, run, role, objective=None, repos=None, *, write=None, read=None, timeout_seconds=None,
                   max_retries=None, depends_on=(), cycle_id=None, retry_of=None, brief=None,
                   must_follow_tdd=None, readonly_approved=None, attempt=1, queue=False, extra_input=None):
        """Inside a transaction: validate, write task.json, insert the row and the task.created event."""
        if run["state"] in machines.RUN_FINAL:
            raise SentinelError("E_TRANSITION", f"run is {run['state']}; it takes no new tasks", {"state": run["state"]})
        cfg = self._run_config(run)
        names = [r for r in repos if isinstance(r, str)] if isinstance(repos, list) else []
        if role in ("tdd_red", "tdd_green", "tdd_refactor") and names:
            write, readonly_approved = self._tdd_permissions(run, cfg, role, names[0], write, readonly_approved)
        adapter, provider, model = select_adapter(cfg, role, names[0] if names else None)
        if timeout_seconds is None:
            policy = (cfg.get("policies") or {}).get("task_timeout_seconds")
            timeout_seconds = policy if _int(policy) and policy > 0 else DEFAULT_TIMEOUT
        if max_retries is None:
            max_retries = retry_cap(cfg, role)
        constraints = {"timeout_seconds": timeout_seconds, "max_retries": max_retries}
        if must_follow_tdd is not None:
            constraints["must_follow_tdd"] = bool(must_follow_tdd)
        shared = {"specifier": [f"specs/{run['slug']}/spec.md"], "test_designer": [f"specs/{run['slug']}/features/**"]}
        if write is None:
            write = shared.get(role, [] if role in READ_ONLY_ROLES else [f"{r}/**" for r in names])
        permissions = {"read": read if read is not None else [f"{r}/**" for r in names], "write": write}
        if readonly_approved:
            permissions["readonly_approved"] = list(readonly_approved)
        inp = self._spec_inputs(run)
        inp["cycle_id"] = cycle_id
        inp.update(extra_input or {})
        if retry_of:
            inp["previous_results"] = [retry_of]
        if brief:
            inp["brief"] = "brief.md"
        task_id = _new_id("tasks")
        doc = {"schema": "task-v1", "id": task_id, "run_id": run["slug"], "role": role, "objective": objective,
               "provider": {"name": provider, "model": model, "adapter": adapter}, "input": inp, "repos": repos,
               "permissions": permissions, "constraints": constraints,
               "expected_output": {"schema": "agent-result-v1", "path": "result.json"}}
        if attempt and attempt > 1:
            doc["attempt"] = attempt
        if retry_of:
            doc["retry_of"] = retry_of
        problems = schema_problems("task-v1", doc)
        if not problems:
            unknown = sorted(set(repos) - self._known_repos(run, cfg))
            if unknown:
                problems = [("repos", f"repos: not in the config: {', '.join(unknown)}")]
        deps = list(depends_on or ())
        if not problems:
            for dep in deps:
                row = self.reg.get_row("tasks", dep)
                if not row or row["run_id"] != run["id"]:
                    problems = [("depends_on", f"depends_on: no task {dep} in this run")]
                    break
        if problems:
            field = problems[0][0]
            raise SentinelError("E_VALIDATION", f"task is not valid, field {field!r}: " + "; ".join(t for _, t in problems),
                                {"field": field, "problems": [t for _, t in problems]})
        if deps:
            doc["depends_on"] = deps
        tdir = self.task_dir(run["slug"], task_id)
        tdir.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
        (tdir / "task.json").write_bytes(data)
        (tdir / "task.sealed.json").write_bytes(data)
        if brief:
            (tdir / "brief.md").write_text(brief, encoding="utf-8")
        self.reg.insert_row("tasks", {
            "id": task_id, "run_id": run["id"], "role": role, "repo_id": repos[0], "cycle_id": cycle_id,
            "state": "CREATED", "provider": provider, "model": model, "adapter": adapter, "retry_of": retry_of,
            "task_path": f"runs/{run['slug']}/tasks/{task_id}/task.json", "created_at": _now(),
            "attempt": attempt, "task_sha256": hashlib.sha256(data).hexdigest(),
            "timeout_seconds": timeout_seconds, "max_retries": max_retries})
        for dep in deps:
            self.reg.add_task_dep(task_id, dep)
        self._task_event(run, task_id, "task.created", machines.ENGINE, self._started_payload(self._task_row(task_id)))
        if queue:
            self._set_state(run, self._task_row(task_id), "QUEUED", machines.ENGINE, "task.queued")
        return self._task_row(task_id)

    @staticmethod
    def _started_payload(task):
        return {"role": task["role"], "repo": task["repo_id"], "provider": task["provider"],
                "model": task["model"], "adapter": task["adapter"]}

    def _task_event(self, run, task_id, type, actor, payload):
        self.reg.add_event(run["id"], type, actor, payload, task_id=task_id, **self._actor_ctx(actor))

    def _auto_task(self, run, role):
        """R3 and R5: the engine creates the specifier or test_designer task and queues it."""
        cfg = self._run_config(run)
        repos = [r["repo_id"] for r in self.reg.run_repos(run["id"])] or \
            [r["id"] for r in cfg.get("repos") or [] if isinstance(r, dict) and r.get("id")]
        if not repos:
            return None
        what = "specification" if role == "specifier" else "Gherkin scenarios"
        brief = "\n".join(f"- {line}" for line in self.brief_feedback(run["slug"], role)) or None
        write = [f"specs/{run['slug']}/features/**"] if role == "test_designer" else None
        return self._make_task(run, role, f"Write the {what} for {run['slug']}", repos, brief=brief, queue=True,
                               write=write)

    # ---- transitions
    def _set_state(self, run, task, to, actor, event, extra=None, payload=None):
        machines.check_task(task["state"], to, actor)
        self.reg.update_row("tasks", task["id"], state=to, **(extra or {}))
        body = self._started_payload(task)
        body.update(payload or {})
        self._task_event(run, task["id"], event, actor, body)

    def _in_task_tx(self, task_id, fn):
        task = self._task_row(task_id)
        run_before = self.reg.get_run_by_id(task["run_id"])
        with self.reg.transaction():
            run = self.reg.get_run_by_id(task["run_id"])
            fn(run, self._task_row(task_id))
        self._finish_up(run_before["slug"], run_before)
        return self._task_row(task_id)

    def queue_task(self, task_id):
        return self._in_task_tx(task_id, lambda run, t: self._set_state(run, t, "QUEUED", machines.ENGINE, "task.queued"))

    def _before_snapshot(self, run, tdir):
        """(text, sha256) of the start snapshot: every repo's changed paths, the watched config files and the repos'
        state folders. The text is written to before.json for people and stored in the registry, which is what is
        compared at the end; the file is only checked against the stored hash."""
        cfg = self._run_config(run)
        snap, had_state = {}, {}
        for repo in cfg.get("repos") or []:
            if isinstance(repo, dict) and repo.get("id"):
                path = self.workspace / repo.get("path", repo["id"])
                if path.is_dir():
                    snap[repo["id"]] = boundary.changed_state(path, self._watch_globs(cfg, repo["id"]))
                    had_state[repo["id"]] = (path / self.state_dir.name).exists()
        text = json.dumps({"repos": snap, "config": self._config_digests(), "had_state": had_state,
                           "shared": self._shared_state(run["slug"])}, indent=2)
        (tdir / "before.json").write_text(text, encoding="utf-8")
        return text, hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _shared_state(self, slug):
        """{path relative to the shared specs folder of the run: sha256} of the files the spec authors write."""
        base = self.state_dir / "shared" / "specs" / slug
        out = {}
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file():
                    try:
                        out[f"specs/{slug}/{p.relative_to(base).as_posix()}"] = hashlib.sha256(p.read_bytes()).hexdigest()
                    except OSError:
                        out[f"specs/{slug}/{p.relative_to(base).as_posix()}"] = None
        return out

    @staticmethod
    def _watch_globs(cfg, repo_id):
        """Predicate over repo-relative paths: true for a path that a glob of the repo (test, production, test
        infrastructure) decides, so an ignored file matching one is still checked."""
        globs = scopes.effective_globs(cfg, repo_id)
        every = [g for key in globs for g in globs[key]]
        return lambda path: any(scopes.glob_match(g, path) for g in every)

    def repo_globs(self, run, repo_id):
        """Effective test_globs and production_globs of a repo from the run's config snapshot (CFG-10, CFG-08)."""
        if isinstance(run, str):
            run = self.reg.get_run(run)
        return scopes.effective_globs(self._run_config(run), repo_id)

    def watched_files(self):
        """{workspace-relative path: sha256} of the agent, skill and AGENTS.md files (the config file is checked against the
        run's config snapshot). Taken when a run is created; verification compares against it."""
        out = {}
        for name in WATCHED[1:]:
            base = self.workspace / name
            files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file()) if base.is_dir() else []
            for f in files:
                try:
                    out[f.relative_to(self.workspace).as_posix()] = sha_bytes(f.read_bytes())
                except OSError:
                    out[f.relative_to(self.workspace).as_posix()] = None
        return out

    def _config_digests(self):
        return {name: boundary.config_state([self.workspace / name]) for name in WATCHED}

    def start_task(self, task_id, pid=None, pid_started_at=None, provider=None, schedule=True, owner=False):
        """QUEUED to RUNNING. The scheduler checks (dependencies, run state, write-scope overlap, parallel limit) run in
        the same transaction, so two processes cannot both start. `provider` is a fallback runner replacing the task's.
        `owner` records this process as the one running the task (recovery waits for it before declaring the runner lost)."""
        def go(run, t):
            machines.check_task(t["state"], "RUNNING", machines.ENGINE)
            if schedule:
                problem = self._task_start_problem(run, t)
                if problem:
                    raise problem
            text, digest = self._before_snapshot(run, self.task_dir(run["slug"], task_id))
            extra = {"started_at": _now(), "pid": pid, "pid_started_at": pid_started_at, "waiting_on": None,
                     "before_snapshot": text, "before_sha256": digest}
            if owner:
                extra.update(owner_pid=os.getpid(), owner_started_at=adapters.process_start_time(os.getpid()))
            payload = None
            if provider and provider != t["provider"]:
                extra.update(provider=provider, model=None)
                payload = {"provider": provider, "model": None, "fallback": {"from": t["provider"], "to": provider}}
            self._set_state(run, t, "RUNNING", machines.ENGINE, "task.started", extra, payload)
            self._cycle_task_started(run, t)
        return self._in_task_tx(task_id, go)

    def set_process(self, task_id, pid, pid_started_at):
        """Record the runner process of a RUNNING task (the row is RUNNING before the process exists)."""
        with self.reg.transaction():
            self.reg.update_row("tasks", task_id, pid=pid, pid_started_at=pid_started_at)

    def wait_task(self, task_id, waiting_on, question=None):
        return self._in_task_tx(task_id, lambda run, t: self._set_state(
            run, t, "WAITING_FOR_INPUT", machines.ENGINE, "task.waiting", {"waiting_on": waiting_on},
            {"waiting_on": waiting_on, "question": question}))

    def _cancel_in_tx(self, run, t, actor, reason, cascade=True, root=None):
        """Inside a transaction: CANCELLED, queue the process kill for after the commit, cancel dependents."""
        self._set_state(run, t, "CANCELLED", actor, "task.finished",
                        {"finished_at": _now(), "reason": reason, "waiting_on": None},
                        {"state": "CANCELLED", "error_code": None, "seconds": _seconds_since(t["started_at"]),
                         "tokens": None, "reason": reason, "exit_code": None})
        if t["cycle_id"] and t["state"] in ("RUNNING", "WAITING_FOR_INPUT"):
            self.on_cycle_task_cancelled(run, t)
        if t["adapter"] == "cli" and t["pid"] and t["state"] in ("RUNNING", "WAITING_FOR_INPUT"):
            self._kills.append((t["pid"], t["pid_started_at"]))
        if cascade:
            chain, row = {t["id"]}, t
            while row["retry_of"] and row["retry_of"] not in chain:  # a dependent waits on the root of the retry chain
                chain.add(row["retry_of"])
                row = self.reg.get_row("tasks", row["retry_of"]) or {"retry_of": None}
            for other in self.reg.rows("tasks", run_id=t["run_id"]):
                if chain & set(self.reg.task_deps(other["id"])) and other["state"] in ("CREATED", "QUEUED"):
                    self._cancel_in_tx(run, other, machines.ENGINE, f"dependency {root or t['id']} cancelled",
                                       root=root or t["id"])

    def cancel_task(self, task_id, actor, reason=None):
        """A human or the engine cancels a task (anyone else gets E_ACTOR). A CLI process group gets SIGTERM, then
        SIGKILL after 10 seconds, once the cancel is committed; dependents are cancelled with it."""
        return self._in_task_tx(task_id, lambda run, t: self._cancel_in_tx(run, t, actor, reason))

    def cancel_open_tasks(self, run, reason):
        """Inside a transaction: cancel every open task of a run (R17, R18, run cancelled or failed)."""
        for t in self.reg.rows("tasks", run_id=run["id"]):
            if t["state"] in OPEN_STATES:
                self._cancel_in_tx(run, t, machines.ENGINE, reason, cascade=False)

    def _flush_kills(self):
        kills, self._kills = self._kills, []
        if kills:
            adapters.terminate_groups(kills)

    def request_task_state(self, task_id, to, actor):
        """The only door for "move this task": the table decides who may. Results are ingested by finish_task."""
        t = self._task_row(task_id)
        machines.check_task(t["state"], to, actor)
        if to == "CANCELLED":
            return self.cancel_task(task_id, actor)
        raise SentinelError("E_PRECONDITION", f"{to} is decided by the engine from the task result, not requested",
                            {"to": to})

    def resume_task(self, task_id, message, actor=machines.ORCHESTRATOR):
        """Answer a WAITING_FOR_INPUT task through its adapter; refused when the adapter cannot resume."""
        t = self._task_row(task_id)
        run = self.reg.get_run_by_id(t["run_id"])
        if t["state"] != "WAITING_FOR_INPUT":
            raise SentinelError("E_TRANSITION", f"task is {t['state']}, only a WAITING_FOR_INPUT task resumes",
                                {"state": t["state"]})
        adapter = self.adapter_for(t["provider"] if t["adapter"] == "cli" else "native", run["slug"])
        cfg = self._run_config(run)
        repo = next((r for r in cfg.get("repos") or [] if isinstance(r, dict) and r.get("id") == t["repo_id"]), {})
        handle = adapters.Handle(task_id, pid=t["pid"], pid_started_at=t["pid_started_at"], session_id=t["session_id"],
                                 workdir=str(self.workspace / repo.get("path", t["repo_id"])), model=t["model"],
                                 task_dir=str(self.task_dir(run["slug"], task_id)))
        new = adapter.resume(handle, message)

        def go(run, t):
            self._set_state(run, t, "RUNNING", actor, "task.started",
                            {"pid": new.pid, "pid_started_at": new.pid_started_at, "waiting_on": None},
                            {"resumed": True})
        return self._in_task_tx(task_id, go)

    # ---- result ingestion
    def _sealed_doc(self, task, strict=False):
        """The sealed task-v1 copy, only when its bytes still match tasks.task_sha256 (a task process can edit
        files in its own folder). Untrusted: None, or E_INTEGRITY when `strict`."""
        run = self.reg.get_run_by_id(task["run_id"])
        try:
            raw = (self.task_dir(run["slug"], task["id"]) / "task.sealed.json").read_bytes()
            if hashlib.sha256(raw).hexdigest() == task["task_sha256"]:
                return json.loads(raw)
        except (OSError, ValueError):
            pass
        if strict:
            raise SentinelError("E_INTEGRITY", f"task.sealed.json of task {task['id']} is missing or was changed",
                                {"task": task["id"]})
        return None

    def task_scope(self, task_id):
        """Write globs of a task from the sealed copy, verified against its stored hash; [] when it cannot be trusted."""
        doc = self._sealed_doc(self._task_row(task_id))
        try:
            return doc["permissions"]["write"] if doc else []
        except (KeyError, TypeError):
            return []

    def overlap_scope(self, task_id):
        """The scope the scheduler compares: an untrusted sealed copy counts as the whole workspace (safe side)."""
        doc = self._sealed_doc(self._task_row(task_id))
        return self.task_scope(task_id) if doc else ["**"]

    def _read_result(self, task_id, tdir):
        """(data, raw bytes, problems). Problems name the field or the reason."""
        path = tdir / "result.json"
        try:
            raw = path.read_bytes()
        except OSError:
            return None, None, ["result.json missing"]
        if not raw.strip():
            return None, raw, ["result.json is empty"]
        try:
            data = json.loads(raw)
        except ValueError:
            return None, raw, ["result.json is not valid JSON"]
        if not isinstance(data, dict):
            return None, raw, ["result.json must be an object"]
        problems = [t for _, t in schema_problems("agent-result-v1", data, indexes=True)]
        if "task_id" in data and data["task_id"] != task_id and (
                isinstance(data["task_id"], str) or not any(p.startswith("task_id") for p in problems)):
            problems.append(f"task_id: {data['task_id']!r} is not this task ({task_id})")
        return (None if problems else data), raw, problems

    def _owned_elsewhere(self, task, rid, name, cache):
        """True when another task of the same run that ran at the same time in this repo has `name` in its write scope
        (README point 15). The candidates are listed once per call and indexed by repo."""
        if "others" not in cache:
            by_repo = {}
            for other in self.reg.rows("tasks", run_id=task["run_id"]):
                if other["id"] == task["id"] or not other["started_at"] or other["state"] in ("CANCELLED", "CREATED", "QUEUED"):
                    continue
                if other["finished_at"] and task["started_at"] and other["finished_at"] < task["started_at"]:
                    continue
                scope = self.task_scope(other["id"])
                for repo in self._task_repos(other, None):
                    by_repo.setdefault(repo, []).append(scope)
            cache["others"] = by_repo
        return any(scopes.path_allowed(scope, rid, name) for scope in cache["others"].get(rid, ()))

    def _changed_files(self, run, task, tdir):
        """(changed paths prefixed by repo id, violations [(kind, text)], change records) from git and content hashes,
        compared with the snapshot stored at start. Kinds: repo_not_allowed, outside_write_scope, approved_test_changed,
        ignore_rules_changed, head_moved, config_changed, state_in_repo."""
        cfg = self._run_config(run)
        try:
            doc = json.loads(task["before_snapshot"])
            before = doc["repos"]
        except (TypeError, ValueError, KeyError):
            doc, before = {}, None
        scope = self.task_scope(task["id"])
        sealed = self._sealed_doc(task) or {}
        approved = (sealed.get("permissions") or {}).get("readonly_approved") or []
        task_repos = set(self._task_repos(task, tdir))
        changed, violations, records, cache = [], [], [], {}
        state_name = self.state_dir.name
        for repo in cfg.get("repos") or []:
            if not (isinstance(repo, dict) and repo.get("id")):
                continue
            path = self.workspace / repo.get("path", repo["id"])
            if not path.is_dir():
                continue
            rid = repo["id"]
            now = boundary.changed_state(path, self._watch_globs(cfg, rid))
            was = (before or {}).get(rid) or {"head": now["head"], "paths": {}}
            names = boundary.changed_between(was, now)
            changed += [f"{rid}/{n}" for n in names]
            records += [{"repo_id": rid, "path": n, "before_sha256": was["paths"].get(n), "after_sha256": now["paths"].get(n)}
                        for n in names]
            if before is None:
                continue
            if now["head"] != was["head"]:
                violations.append(("head_moved", f"{rid}: HEAD moved"))
            for n in names:
                if n == state_name or n.startswith(state_name + "/"):
                    continue
                full = f"{rid}/{n}"
                if rid not in task_repos:
                    if not self._owned_elsewhere(task, rid, n, cache):
                        violations.append(("repo_not_allowed", full))
                elif IGNORE_RULES.search(n):
                    violations.append(("ignore_rules_changed", full))
                elif any(scopes.glob_match(g, full) for g in approved):
                    violations.append(("approved_test_changed", full))
                elif task["role"] in ("tdd_green", "tdd_refactor") and (
                        scopes.classify(cfg, rid, n) == "test" or scopes.is_test_infra(cfg, rid, n)):
                    violations.append(("outside_write_scope", full))  # tests and test setup are Red's, even inside a scope glob
                elif not scopes.path_allowed(scope, rid, n) and not self._owned_elsewhere(task, rid, n, cache):
                    violations.append(("outside_write_scope", full))
            if (path / state_name).exists() and not (doc.get("had_state") or {}).get(rid, False):
                violations.append(("state_in_repo", f"{rid}/{state_name}"))
        if before is not None:
            now_cfg = self._config_digests()
            violations += [("config_changed", name) for name, digest in (doc.get("config") or {}).items()
                           if now_cfg.get(name) != digest]
            if doc.get("shared") is not None:
                was_shared, now_shared = doc["shared"], self._shared_state(run["slug"])
                for n in sorted(k for k in set(was_shared) | set(now_shared) if was_shared.get(k) != now_shared.get(k)):
                    changed.append(n)
                    records.append({"repo_id": None, "path": n, "before_sha256": was_shared.get(n),
                                    "after_sha256": now_shared.get(n)})
                    if not any(scopes.glob_match(g, n) for g in scope):
                        violations.append(("outside_write_scope", f"{state_name}/shared/{n}"))
        return sorted(changed), violations, records

    def _task_repos(self, task, tdir):
        doc = self._sealed_doc(task)
        return (doc or {}).get("repos") or [task["repo_id"]]

    def _integrity_problems(self, task, tdir):
        """Files of the task folder that no longer match what the engine stored (task.json, task.sealed.json, before.json)."""
        problems = []
        try:
            current = hashlib.sha256((tdir / "task.json").read_bytes()).hexdigest()
        except OSError:
            current = None
        if current != task["task_sha256"]:
            problems.append(f"task file changed during task {task['id']}")
        if self._sealed_doc(task) is None:
            problems.append(f"task.sealed.json of task {task['id']} is missing or was changed")
        try:
            before = (tdir / "before.json").read_bytes()
        except OSError:
            before = None
        if not task["before_sha256"] or hashlib.sha256(before or b"").hexdigest() != task["before_sha256"]:
            problems.append(f"before.json of task {task['id']} is missing or was changed")
        return problems

    def _judge(self, run, task, exit_code, timed_out=False, lost=False):
        """Decide the task outcome. Order: integrity, scope, timeout, exit code, result schema, agent status."""
        tdir = self.task_dir(run["slug"], task["id"])
        role = task["role"]
        v = {"state": "COMPLETED", "code": None, "message": None, "details": None, "art": None,
             "changed": [], "flags": [], "park": None, "audit": None, "data": None, "violations": []}
        changed, violations, records = self._changed_files(run, task, tdir)
        integrity = self._integrity_problems(task, tdir)
        v["changed"] = changed
        v["records"] = records
        v["violations"] = violations
        data, raw, problems = self._read_result(task["id"], tdir)
        v["data"] = data
        if integrity:
            msg = "; ".join(integrity)
            v.update(state="FAILED", code="E_INTEGRITY", message=msg, details={"problems": integrity}, park=msg,
                     audit=("integrity_failed", task["id"], "E_INTEGRITY"))
        elif violations:
            listed = [text for _, text in violations]
            v.update(state="FAILED", code="E_SCOPE", message="; ".join(listed),
                     details={"violations": listed, "kinds": sorted({k for k, _ in violations})},
                     park=f"scope violation in {role} task {task['id']}: " + "; ".join(listed))
        elif timed_out:
            msg = f"timed out after {task['timeout_seconds']} seconds"
            v.update(state="FAILED", code="E_TIMEOUT", message=msg, details={"timeout_seconds": task["timeout_seconds"]})
        elif lost:
            v.update(state="FAILED", code="E_EXIT", message="process lost", details={"exit_code": None, "problems": []})
        elif exit_code != 0:
            msg = f"exit code {exit_code}"
            v.update(state="FAILED", code="E_EXIT", message=msg, details={"exit_code": exit_code, "problems": []})
        elif problems:
            msg = "result.json is not valid: " + "; ".join(problems)
            v.update(state="FAILED", code="E_RESULT_SCHEMA", message=msg, details={"problems": problems})
        elif data["status"] == "failed":
            v.update(state="FAILED", code="E_AGENT", message=data["summary"], details={"summary": data["summary"]})
        elif data["status"] == "blocked":
            why = "; ".join(str(q) for q in data.get("questions") or []) or data["summary"]
            v.update(state="BLOCKED", message=why, park=f"{role} task blocked: {why}")
        if data is not None:
            v["raw"] = raw
            claimed = data.get("claimed_changed_files") or []
            v["flags"] = [{"path": p, "flag": "claimed but not changed"} for p in claimed if p not in changed]
        return v

    def _store_result(self, run, task, raw):
        slug = run["slug"]
        dest = self.run_dir(slug) / "artifacts" / f"result-{task['id']}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return self.reg.insert_row("artifacts", {
            "run_id": run["id"], "kind": "result", "version": 1,
            "path": dest.relative_to(self.state_dir).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(), "created_at": _now()})

    def _log_scrubber(self, run=None):
        """The scrubber for task logs, kept for 30 seconds (it reads the .env files of the workspace and its repos)."""
        import scrub
        now = time.monotonic()
        cached = getattr(self, "_log_scrubber_cache", None)
        if cached and now - cached[0] < 30:
            return cached[1]
        cfg = self._run_config(run) if run else self.config
        repos = [r.get("path") for r in (cfg.get("repos") or []) if isinstance(r, dict) and r.get("path")]
        scrubber = scrub.Scrubber("/nonexistent-workspace", scrub.env_values(self.workspace, repos))  # local paths stay readable
        self._log_scrubber_cache = (now, scrubber)
        return scrubber

    def _scrub_task_logs(self, tdir, run=None):
        """Redact secrets from the finished task's stdout and stderr logs on disk (SEC-06): values of the workspace
        .env files, of the redact_env variables of the run's own config snapshot and of the dashboard token, plus the
        scrubber's patterns. The log is read line by line (whatever its size) into a temp file that replaces it."""
        import scrub
        scrubber = self._log_scrubber(run)
        cfg = self._run_config(run) if run else self.config
        for name in ("output.log", "stderr.log"):
            path = tdir / name
            tmp = None
            try:
                if not path.is_file() or path.is_symlink():
                    continue
                fd, tmp = tempfile.mkstemp(dir=tdir, prefix=f".{name}.")
                changed = False
                seen = collections.deque()

                def bodies(src):
                    for raw in src:
                        text = raw.decode("utf-8", errors="replace")
                        body = text.rstrip("\r\n")
                        seen.append((text, text[len(body):]))
                        yield body
                with open(path, "rb") as src, os.fdopen(fd, "wb") as dst:
                    for clean in scrub.clean_lines(scrubber, bodies(src), cfg):
                        text, end = seen.popleft()
                        changed = changed or clean + end != text
                        dst.write((clean + end).encode("utf-8"))
                if changed:
                    os.chmod(tmp, path.stat().st_mode & 0o777)
                    os.replace(tmp, path)
                    tmp = None
            except OSError:
                continue
            finally:
                if tmp:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

    def finish_task(self, task_id, exit_code=0, seconds=None, timed_out=False, lost=False, session_id=None):
        """Ingest the task's result.json and decide its state. `exit_code` is the process exit (0 for a native task).
        FAILED tasks are retried as a new task until their cap; scope and integrity failures go to a human."""
        task0 = self._task_row(task_id)
        run0 = self.reg.get_run_by_id(task0["run_id"])
        retry = None
        with self.reg.transaction():
            run = self.reg.get_run_by_id(task0["run_id"])
            task = self._task_row(task_id)
            machines.check_task(task["state"], "COMPLETED", machines.ENGINE)
            v = self._judge(run, task, exit_code, timed_out, lost)
            tdir = self.task_dir(run["slug"], task_id)
            art = self._store_result(run, task, v["raw"]) if v.get("raw") and v["data"] is not None else None
            secs = seconds if seconds is not None else _seconds_since(task["started_at"])
            extra = {"error_code": v["code"], "reason": v["message"], "finished_at": _now(), "seconds": secs,
                     "result_artifact_id": art, "changed_files": json.dumps(v["changed"]), "waiting_on": None}
            if session_id:
                extra["session_id"] = session_id
            for rec in v["records"]:
                self.reg.insert_row("changed_files", {"run_id": run["id"], "task_id": task_id, "cycle_id": task["cycle_id"],
                                                      "phase": task["role"] if task["role"].startswith("tdd_") else None, **rec})
            for kind in sorted({k for k, _ in v["violations"]} if v["code"] == "E_SCOPE" else ()):
                self._task_event(run, task_id, "task.scope_violation", machines.ENGINE,
                                 {"paths": [t for k, t in v["violations"] if k == kind], "kind": kind})
            self._set_state(run, task, v["state"], machines.ENGINE, "task.finished", extra,
                            {"state": v["state"], "error_code": v["code"], "seconds": secs, "tokens": None,
                             "reason": v["message"], "details": v["details"],
                             "exit_code": None if lost or timed_out else exit_code})
            (tdir / "report.json").write_text(json.dumps({
                "task_id": task_id, "state": v["state"], "error_code": v["code"], "changed_files": v["changed"],
                "claim_flags": v["flags"], "write_scope_checked": self.task_scope(task_id),
                "claimed_commands": (v["data"] or {}).get("claimed_commands", []),
                "out_of_lane": (v["data"] or {}).get("out_of_lane", [])}, indent=2), encoding="utf-8")
            if v["audit"]:
                self.reg.add_audit("engine", "engine", *v["audit"][:2], reason=v["audit"][2])
            state_before = run["state"]
            if v["code"] == "E_SCOPE" and any(t.startswith(f"{self.state_dir.name}/shared/") for _, t in v["violations"]):
                run = self._detect(self.reg.get_run_by_id(run["id"]))  # an edited approved file is R17 or R18 first
            if v["state"] == "FAILED" and v["code"] in RETRY_CODES:
                retry = self._retry_or_park(run, self._task_row(task_id), v)
            elif v["park"] and run["state"] == state_before and run["state"] not in machines.RUN_FINAL \
                    and run["state"] != "NEEDS_HUMAN":
                self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=v["park"])
            if v["state"] == "COMPLETED":
                self._queue_ready(run, dependents_only=True)
        self._scrub_task_logs(self.task_dir(run0["slug"], task_id), run0)
        self._finish_up(run0["slug"], run0)
        row = self._task_row(task_id)
        row["error_details"] = v["details"]
        row["retry"] = retry
        if v["state"] == "COMPLETED":
            self.link_fix_task_files(task_id)
        if v["state"] == "COMPLETED" and task["role"] in ("specifier", "test_designer"):
            row["completion"] = self.task_completed(run0["slug"], task["role"], task_id)
        if v["state"] == "COMPLETED" and task["role"] in ("tdd_red", "tdd_green", "tdd_refactor"):
            row["verification"] = self.verify_phase(task_id)
        if v["state"] == "COMPLETED" and task["role"] in ("reviewer", "qa"):
            row["findings"] = self.after_review_task(task_id)
        return row

    # ---- retries (ORC-05)
    def _retry_or_park(self, run, task, v):
        """Inside a transaction: a new task for a retryable failure, or NEEDS_HUMAN (R19) once the cap is used."""
        cap = task["max_retries"] if _int(task["max_retries"]) else retry_cap(self._run_config(run), task["role"])
        attempt = task["attempt"] or 1
        if run["state"] in machines.RUN_FINAL:
            return None
        tdd = task["role"].startswith("tdd_") and task["cycle_id"]
        if attempt <= cap:
            retry = self._make_retry(run, task, v, attempt)
            if tdd:
                self._after_retry_created(run, self._task_row(task["id"]), retry)
            return retry["id"]
        if tdd:
            self._cap_reached(run, self._cycle(task["cycle_id"]), task["role"][4:], f"{v['code']}: {v['message']}")
        elif run["state"] != "NEEDS_HUMAN":
            why = f"{task['role']} task failed after {cap} retries"
            if task["role"] in ("tdd_green", "hardener"):  # a verification fix task
                why = f"{task['role']} fix task {task['id']} failed after {cap} retries: retry cap reached"
            self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=why)
        return None

    def _make_retry(self, run, task, v, attempt):
        tdir = self.task_dir(run["slug"], task["id"])
        sealed = self._sealed_doc(task, strict=True)
        perm, cons = sealed["permissions"], sealed["constraints"]
        cfg = self._run_config(run)

        def clean(text):
            return adapters.redact_text(cfg, str(text))[:STDERR_LINE_CAP]
        lines = [f"Previous attempt {task['id']} (attempt {attempt}) failed with {v['code']}: {clean(v['message'])}"]
        lines += [f"- {clean(p)}" for p in (v["details"] or {}).get("problems") or []]
        try:
            tail = (tdir / "stderr.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-STDERR_LINES:]
        except OSError:
            tail = []
        if tail:
            lines += ["", "Last lines of its stderr (secrets removed):"] + [f"    {clean(line)}" for line in tail]
        try:
            earlier = (tdir / "brief.md").read_text(encoding="utf-8").strip()
        except OSError:
            earlier = ""
        if earlier:
            lines += ["", "Earlier failures and feedback:", earlier]
        return self._make_task(
            run, task["role"], sealed["objective"], sealed["repos"], write=perm.get("write"), read=perm.get("read"),
            timeout_seconds=cons["timeout_seconds"], max_retries=cons.get("max_retries"),
            cycle_id=(sealed.get("input") or {}).get("cycle_id"), retry_of=task["id"], attempt=attempt + 1,
            brief="\n".join(lines) + "\n", must_follow_tdd=cons.get("must_follow_tdd"),
            readonly_approved=None if task["role"].startswith("tdd_") else perm.get("readonly_approved"), queue=True)

    # ---- specifier / test_designer hook
    def _open_tasks(self, run, role):
        return [t for t in self.reg.rows("tasks", run_id=run["id"], role=role) if t["state"] in OPEN_STATES]

    def _after_role_task(self, slug, role, result, task_id):
        """After task_completed: queue a retry task with the brief when the submission was rejected."""
        with self.reg.transaction():
            run = self._get_v2(slug)
            wanted = "PLANNED" if role == "specifier" else "SPECIFICATION_APPROVED"
            if result["accepted"] or run["state"] != wanted or self._open_tasks(run, role):
                return
            last = self._task_row(task_id)
            brief = "\n".join(f"- {line}" for line in self.brief_feedback(slug, role)) or "the previous attempt was rejected"
            self._make_task(run, role, last_objective(last, self), [last["repo_id"]], retry_of=last["id"],
                            attempt=(last["attempt"] or 1) + 1, brief=brief, queue=True)


def last_objective(task, engine):
    try:
        run = engine.reg.get_run_by_id(task["run_id"])
        return json.loads((engine.task_dir(run["slug"], task["id"]) / "task.json").read_text())["objective"]
    except (OSError, ValueError, KeyError):
        return f"Retry {task['role']} task"
