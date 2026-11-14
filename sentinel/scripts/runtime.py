"""Task runtime (PC-02): the scheduler, `task run`, `task complete`, `next`, recovery.

RuntimeOps is mixed into Engine next to TaskOps. The engine decides every task state; adapters only start and
stop work. Source: docs/architecture/agent-runtime.md, plan/v1.1/phaseC/README.md.
"""
import json
import os
import re
import shlex
import shutil
import time
from pathlib import Path

import yaml

import adapters
import machines
import render_stage
import scheduler
from errors import SentinelError
from paths import ROOT
from tasks import DEFAULT_TIMEOUT, OPEN_STATES, _int, _seconds_since

TASK_ID = re.compile(r"t-[0-9a-f]{12}")
ACTIVE = ("RUNNING", "WAITING_FOR_INPUT")
EXEC_STATES = ("EXECUTING", "VERIFYING", "REVIEWING")
ROLE_RUN_STATES = {"specifier": ("PLANNED",), "test_designer": ("SPECIFICATION_APPROVED",)}
PROCESS_GRACE = 30.0  # seconds a RUNNING CLI task may have no pid yet, and slack before recovery enforces a timeout
TICK = 0.2
STAGES = ROOT / "core" / "stages"


def check_task_id(task_id):
    if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
        raise SentinelError("E_VALIDATION", f"not a task id: {task_id!r} (expected t- and 12 hex digits)",
                            {"task": task_id})
    return task_id


def runner_command(runner):
    parts = shlex.split(runner.get("command") or "")
    return parts[0] if parts else ""


def runner_installed(runner):
    cmd = runner_command(runner)
    if not cmd:
        return False
    if "/" in cmd:
        return os.path.isfile(cmd) and os.access(cmd, os.X_OK)
    return shutil.which(cmd) is not None


class RuntimeOps:
    _kills = ()

    # ---- guards
    def _refuse_agent(self, target, command, caller_task):
        """A task process (SENTINEL_TASK_ID set) may not drive tasks (AGT-06e). Audited, then E_ACTOR."""
        if not caller_task:
            return
        self.audit("agent", "cli", "task_refused", str(target),
                   reason=f"`sentinel {command}` called from task {caller_task}")
        raise SentinelError("E_ACTOR", f"a task process may not run `sentinel {command}` (called from task {caller_task})",
                            {"task": caller_task, "command": command})

    # ---- scheduler
    def _satisfied(self, task_id):
        """A dependency is satisfied when it completed or one of its retries did."""
        row = self.reg.get_row("tasks", task_id)
        if not row:
            return False
        if row["state"] == "COMPLETED":
            return True
        return any(self._satisfied(r["id"]) for r in self.reg.rows("tasks", retry_of=task_id))

    def open_dependencies(self, task_id):
        return [d for d in self.reg.task_deps(task_id) if not self._satisfied(d)]

    def _queue_ready(self, run, dependents_only=False):
        """Inside a transaction: CREATED tasks whose dependencies are all satisfied become QUEUED."""
        queued = []
        for t in self.reg.rows("tasks", run_id=run["id"]):
            if t["state"] != "CREATED":
                continue
            deps = self.reg.task_deps(t["id"])
            if (dependents_only and not deps) or any(not self._satisfied(d) for d in deps):
                continue
            self._set_state(run, t, "QUEUED", machines.ENGINE, "task.queued")
            queued.append(t["id"])
        return queued

    def schedule(self, slug):
        """Queue every CREATED task whose dependencies are complete. Returns the queued task ids."""
        with self.reg.transaction():
            run = self._get_v2(slug)
            queued = [] if run["state"] in machines.RUN_FINAL else self._queue_ready(run)
        self._finish_up(slug, run)
        return queued

    def _parallel_limit(self, run):
        value = (self._run_config(run).get("policies") or {}).get("max_parallel_tasks")
        return value if _int(value) and value >= 1 else 1

    def _task_start_problem(self, run, t):
        """None when the task may start now, else the SentinelError that says why not."""
        open_deps = self.open_dependencies(t["id"])
        if open_deps:
            return SentinelError("E_TRANSITION", f"task {t['id']} has open dependencies: {', '.join(open_deps)}",
                                 {"open_dependencies": open_deps})
        allowed = ROLE_RUN_STATES.get(t["role"], EXEC_STATES)
        if run["state"] not in allowed:
            return SentinelError("E_PRECONDITION", f"a {t['role']} task does not start while the run is {run['state']} "
                                 f"(allowed: {', '.join(allowed)})", {"run_state": run["state"], "allowed": list(allowed)})
        mine = self.overlap_scope(t["id"])
        active = [x for x in self.reg.rows("tasks", run_id=run["id"]) if x["state"] in ACTIVE and x["id"] != t["id"]]
        overlaps = []
        for other in active:
            pair = scheduler.scopes_overlap(mine, self.overlap_scope(other["id"]))
            if pair:
                overlaps.append({"task": other["id"], "globs": list(pair)})
        if overlaps:
            first = overlaps[0]
            return SentinelError("E_PRECONDITION", f"write scope of task {t['id']} overlaps running task {first['task']}: "
                                 f"{first['globs'][0]} and {first['globs'][1]}", {"overlaps": overlaps})
        limit = self._parallel_limit(run)
        if len(active) >= limit:
            return SentinelError("E_PRECONDITION", f"max_parallel_tasks {limit} reached by running tasks: "
                                 f"{', '.join(x['id'] for x in active)}",
                                 {"max_parallel_tasks": limit, "running": [x["id"] for x in active]})
        return None

    def check_start(self, task_id):
        """May the task start now? {"ok": bool, "code", "message", "details"}."""
        t = self._task_row(task_id)
        run = self.reg.get_run_by_id(t["run_id"])
        problem = self._task_start_problem(run, t)
        if problem is None:
            return {"ok": True, "code": None, "message": None, "details": {}}
        return {"ok": False, "code": problem.code, "message": problem.message, "details": problem.details}

    def create_task_graph(self, slug, nodes):
        """Store several tasks and their dependencies atomically. Each node is create_task keywords plus `key`;
        `depends_on` holds keys of this graph or ids of tasks of the same run. Invalid graphs store nothing."""
        keys = [n.get("key") for n in nodes]
        if len(set(keys)) != len(keys) or any(not isinstance(k, str) for k in keys):
            raise SentinelError("E_VALIDATION", "task graph keys must be unique strings")
        by_key = {n["key"]: n for n in nodes}
        graph = {}
        for n in nodes:
            graph[n["key"]] = list(n.get("depends_on") or [])
        for key, deps in graph.items():
            for dep in deps:
                if dep not in by_key:
                    row = self.reg.get_row("tasks", dep) if isinstance(dep, str) else None
                    run = self._get_v2(slug)
                    if not row or row["run_id"] != run["id"]:
                        raise SentinelError("E_VALIDATION", f"task {key} depends on {dep!r}, which is not in this graph or run",
                                            {"field": "depends_on"})
        order, state = [], {}

        def visit(key, trail):
            if state.get(key) == 2:
                return
            if state.get(key) == 1:
                raise SentinelError("E_VALIDATION", f"dependency cycle: {' -> '.join(trail + [key])}", {"field": "depends_on"})
            state[key] = 1
            for dep in graph[key]:
                if dep in by_key:
                    visit(dep, trail + [key])
            state[key] = 2
            order.append(key)
        for key in keys:
            visit(key, [])
        ids, made = {}, []
        try:
            with self.reg.transaction():
                run = self._get_v2(slug)
                for key in order:
                    n = dict(by_key[key])
                    role, objective, repos = n.pop("role"), n.pop("objective", None), n.pop("repos", None)
                    n.pop("key")
                    n["depends_on"] = [ids.get(d, d) for d in graph[key]]
                    row = self._make_task(run, role, objective or f"{role} work", repos, **n)
                    ids[key] = row["id"]
                    made.append(row["id"])
        except BaseException:
            for tid in made:
                shutil.rmtree(self.task_dir(slug, tid), ignore_errors=True)
            raise
        return ids

    # ---- bookkeeping shared by next, task run, dispatch
    def bookkeep(self, slug):
        """Engine housekeeping before any answer: shared-file changes, finished or lost processes, native timeouts,
        R22 once a missing runner is installed, R3 and R12 when nothing else is needed, queue ready tasks."""
        self._sync(slug)
        run = self._get_v2(slug)
        if run["state"] in machines.RUN_FINAL:
            return run
        self._unblock(slug)
        self._recover(slug)
        run = self._get_v2(slug)
        if run["state"] == "TRIAGED" and ((run["tier"] or 0) < 3 or (self.run_dir(slug) / "decisions.md").is_file()):
            self.request_state(slug, "PLANNED", machines.ENGINE, reason="triage done")
        elif self._starts_execution(run):
            try:
                self.advance(slug)
            except SentinelError:
                pass  # the run is parked with the reason; `next` reports it
        if self._get_v2(slug)["state"] not in machines.RUN_FINAL:
            self.schedule(slug)
        return self._get_v2(slug)

    def _unblock(self, slug):
        """R22: a run blocked on a missing runner resumes once the command stored with the blocked task is installed."""
        run = self._get(slug)
        if run["state"] != "BLOCKED":
            return
        waiting = [t for t in self.reg.rows("tasks", run_id=run["id"], state="QUEUED") if t["blocked_command"]]
        if waiting and runner_installed({"command": waiting[-1]["blocked_command"]}):
            self.request_state(slug, run["previous_state"], machines.ENGINE,
                               reason=f"{runner_command({'command': waiting[-1]['blocked_command']})} is installed")

    def _recover(self, slug):
        run = self._get(slug)
        for t in self.reg.rows("tasks", run_id=run["id"]):
            try:
                self._recover_task(t)
            except SentinelError as err:
                if err.code != "E_TRANSITION":  # another process finished it first
                    raise

    def _recover_task(self, t):
        if t["state"] not in ACTIVE:
            return
        run = self.reg.get_run_by_id(t["run_id"])
        tdir = self.task_dir(run["slug"], t["id"])
        exit_file = tdir / "exit.json"
        if t["state"] == "RUNNING" and exit_file.is_file():
            try:
                info = json.loads(exit_file.read_text(encoding="utf-8"))
            except ValueError:
                info = {}
            self.finish_task(t["id"], exit_code=info.get("exit_code", 0), seconds=info.get("seconds"),
                             timed_out=bool(info.get("timed_out")), session_id=info.get("session_id"))
            return
        age = _seconds_since(t["started_at"])
        timeout = t["timeout_seconds"] or DEFAULT_TIMEOUT
        if t["adapter"] == "cli" and t["state"] == "RUNNING":
            if t["pid"]:
                alive = adapters.process_alive(t["pid"], t["pid_started_at"])
            else:
                alive = age is not None and age < PROCESS_GRACE
            owner = bool(t["owner_pid"]) and adapters.process_alive(t["owner_pid"], t["owner_started_at"])
            if not alive and not owner:  # the runner is gone and so is the `task run` that was about to record its exit
                self.finish_task(t["id"], exit_code=1, lost=True)
            elif alive and age is not None and age > timeout + PROCESS_GRACE:
                adapters.terminate_groups([(t["pid"], t["pid_started_at"])], grace=2)
                self.finish_task(t["id"], timed_out=True)
        elif t["adapter"] == "native" and age is not None and age > timeout:
            self.finish_task(t["id"], exit_code=0, timed_out=True)

    # ---- prompts
    def _render_prompt(self, run, t, tdir, require_template=False):
        slug = run["slug"]
        cfg = self._run_config(run)
        sealed = self._sealed_doc(t, strict=True)
        role = sealed["role"]
        template_path = STAGES / f"{role}.md"
        parts = []
        if template_path.is_file():
            template = template_path.read_text(encoding="utf-8")
            front_match = render_stage.FRONT.match(template)
            front = (yaml.safe_load(front_match.group(1)) if front_match else {}) or {}
            repo = None
            if front.get("per_repo"):
                repo = next((r for r in cfg.get("repos") or [] if r.get("id") == sealed["repos"][0]), None)
            try:
                ctx = render_stage.build_context(cfg, repo, self.workspace, role)
                ctx.update(state_dir=str(self.state_dir), run_dir=str(self.run_dir(slug)),
                           shared_dir=str(self.state_dir / "shared"))
                parts.append(render_stage.render(template, ctx).replace("<slug>", slug))
            except KeyError as missing:
                raise SentinelError("E_PRECONDITION", f"stage template {role}.md has an unresolved placeholder: {missing}",
                                    {"role": role}) from missing
        elif require_template:
            raise SentinelError("E_PRECONDITION", f"no stage template for role {role} yet; a CLI runner cannot take it "
                                "(route it to the native adapter)", {"role": role})
        else:
            parts.append(f"You are the {role} for run {slug}.")
        scope = sealed["permissions"]["write"]
        inp = sealed.get("input") or {}
        lines = ["## Task", "", f"- Task id: {t['id']}", f"- Role: {role}", f"- Objective: {sealed['objective']}",
                 f"- Repos: {', '.join(sealed['repos'])}",
                 f"- Write scope: {', '.join(scope) if scope else 'none (read-only task)'}",
                 f"- Run folder: {self.run_dir(slug)}", f"- Shared specs: {self.state_dir / 'shared' / 'specs' / slug}"]
        if inp.get("specification"):
            lines.append(f"- Approved specification: {inp['specification']['path']} (sha256 {inp['specification']['sha256']})")
        lines += [f"- Result file (absolute path): {tdir / 'result.json'}", "",
                  "When you finish, write the result file as JSON: "
                  '{"schema": "agent-result-v1", "task_id": "<task id>", "status": "completed|blocked|failed", '
                  '"summary": "<text>"}. Questions go in "questions", findings in "findings".']
        parts.append("\n".join(lines))
        parts.append("## Runtime notes\n\n"
                     f"- Workspace root: {self.workspace}. Every path above is absolute; never create the sentinel state folder inside a repo.\n"
                     "- You run headless inside an automated pipeline. No human will answer questions; if blocked, set status \"blocked\" and list your questions.\n"
                     "- Your write boundary is checked after you finish. Writing outside it, or committing, fails the task.\n"
                     "- Never run `sentinel task run`, `sentinel task complete` or approve anything.")
        brief = tdir / "brief.md"
        if brief.is_file():
            parts.append("## Brief\n\n" + brief.read_text(encoding="utf-8"))
        text = "\n\n".join(p.strip() for p in parts) + "\n"
        (tdir / "prompt.md").write_text(text, encoding="utf-8")
        return text

    # ---- task run
    def _outcome(self, task_id, **extra):
        row = self._task_row(task_id)
        run = self.reg.get_run_by_id(row["run_id"])
        if row["error_code"] == "E_SCOPE":
            code = 3
        elif run["state"] in ("NEEDS_HUMAN", "BLOCKED"):
            code = 6
        elif row["state"] in ("FAILED", "CANCELLED", "BLOCKED"):
            code = 1
        else:
            code = 0
        retry = [t["id"] for t in self.reg.rows("tasks", retry_of=task_id)]
        out = {"task_id": task_id, "state": row["state"], "error_code": row["error_code"], "reason": row["reason"],
               "provider": row["provider"], "adapter": row["adapter"], "run_state": run["state"],
               "retry": retry[0] if retry else None, "log": str(self.task_dir(run["slug"], task_id) / "output.log"),
               "exit": code}
        out.update(extra)
        return out

    def run_task(self, task_id, caller_task=None):
        """`sentinel task run`: start a QUEUED task through its adapter. CLI tasks run to the end; native tasks
        wait for the orchestrator. Returns a dict with the JSON output and the exit code in "exit"."""
        self._refuse_agent(task_id, "task run", caller_task)
        check_task_id(task_id)
        t = self._task_row(task_id)
        slug = self.reg.get_run_by_id(t["run_id"])["slug"]
        self.bookkeep(slug)
        t = self._task_row(task_id)
        run = self.reg.get_run_by_id(t["run_id"])
        if t["state"] != "QUEUED":
            deps = self.open_dependencies(task_id) if t["state"] == "CREATED" else []
            raise SentinelError("E_TRANSITION", f"task {task_id} is {t['state']}, only a QUEUED task runs"
                                + (f"; open dependencies: {', '.join(deps)}" if deps else ""),
                                {"state": t["state"], "open_dependencies": deps})
        if t["adapter"] == "native":
            return self._run_native(run, t)
        return self._run_cli(run, t)

    def _run_native(self, run, t):
        tdir = self.task_dir(run["slug"], t["id"])
        self._render_prompt(run, t, tdir)
        adapter = adapters.get_adapter("native", self._run_config(run))
        job = adapters.Job(t["id"], str(tdir), str(self.workspace), (tdir / "prompt.md").read_text(encoding="utf-8"))
        self.start_task(t["id"])
        adapter.submit(job)
        self.wait_task(t["id"], "orchestrator")
        return self._outcome(t["id"], prompt=str(tdir / "prompt.md"), result=str(tdir / "result.json"),
                             waiting_on="orchestrator", next=f"sentinel task complete {t['id']}")

    def _fallback_runner(self, cfg, runner_id):
        from run_stage import all_runners
        providers = cfg.get("providers") or {}
        disabled = set(providers.get("disabled") or [])
        runners = all_runners(cfg)
        for name in providers.get("fallback") or []:
            if name in disabled or name == runner_id or name not in runners:
                continue
            if runner_installed(runners[name]):
                return name
        return None

    def _block_run(self, run, t, runner):
        cmd = runner_command(runner)
        reason = f"runner not installed: {cmd}"
        fix = f"install {cmd} or change agents.{t['role']} (or routing) in sentinel.config.yaml"
        with self.reg.transaction():
            self.reg.update_row("tasks", t["id"], blocked_command=runner.get("command"))
        self.request_state(run["slug"], "BLOCKED", machines.ENGINE, reason=reason)
        return self._outcome(t["id"], blocked=True, reason=reason, fix=fix, exit=6)

    def _run_cli(self, run, t):
        slug = run["slug"]
        tdir = self.task_dir(slug, t["id"])
        cfg = self._run_config(run)
        runner_id, model = t["provider"], t["model"]
        adapter = self.adapter_for(runner_id, slug)
        if model and not adapter.runner.get("model_flag"):
            raise SentinelError("E_VALIDATION", f"model {model} cannot be set: runners.{runner_id} has no model_flag; "
                                f"add model_flag to runners.{runner_id}", {"runner": runner_id, "model": model})
        self._render_prompt(run, t, tdir, require_template=True)
        fallback = None
        if not runner_installed(adapter.runner):
            alt = self._fallback_runner(cfg, runner_id)
            if not alt:
                return self._block_run(run, t, adapter.runner)
            fallback, runner_id, model = alt, alt, None
            adapter = self.adapter_for(alt, slug)
        self.start_task(t["id"], provider=fallback, owner=True)
        job = adapters.Job(t["id"], str(tdir), self._workdir(cfg, t["repo_id"]),
                           (tdir / "prompt.md").read_text(encoding="utf-8"), model=model,
                           extra_dirs=[self.state_dir])
        try:
            handle = adapter.submit(job)
        except SentinelError:
            self.finish_task(t["id"], exit_code=127)
            return self._outcome(t["id"])
        self.set_process(t["id"], handle.pid, handle.pid_started_at)
        return self._monitor(run, t, adapter, handle, tdir)

    def _workdir(self, cfg, repo_id):
        repo = next((r for r in cfg.get("repos") or [] if isinstance(r, dict) and r.get("id") == repo_id), {})
        return str(self.workspace / repo.get("path", repo_id))

    def heartbeat(self):
        import run_stage
        return run_stage.heartbeat_seconds()

    def _monitor(self, run, t, adapter, handle, tdir):
        import sys
        task_id = t["id"]
        started = time.time()
        timeout = t["timeout_seconds"] or DEFAULT_TIMEOUT
        beat = self.heartbeat()
        next_beat = started + beat
        name = f"{t['repo_id']}-{t['role']}"
        timed_out = cancelled = False
        while not adapter.wait(handle, TICK):
            now = time.time()
            if self.reg.get_row("tasks", task_id)["state"] == "CANCELLED":
                cancelled = True
                adapter.cancel(handle)
                break
            if now - started >= timeout:
                timed_out = True
                adapter.cancel(handle, grace=2.0)
                break
            if now >= next_beat:
                next_beat += beat
                elapsed = int(now - started)
                size = adapter.status(handle).get("output_bytes", 0)
                self._progress(run, task_id, elapsed, size, tdir)
                print(f"[{name}] running {elapsed // 60}m{elapsed % 60:02d}s, {size} bytes of output",
                      file=sys.stderr, flush=True)
        exit_code = adapter.reap(handle)
        seconds = round(time.time() - started, 3)
        if not cancelled:
            # before the log pumps are joined: from here on a recovery in another process finds the exit, not a lost task
            self._write_exit(tdir, {"exit_code": exit_code, "timed_out": timed_out, "seconds": seconds, "session_id": None,
                                    "pid": handle.pid, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        exit_code, stdout, stderr = adapter.result(handle, timed_out=timed_out)
        if cancelled:
            return self._outcome(task_id, exit_code=exit_code, stderr_tail=self._tail(stderr))
        session = None
        if adapter.runner.get("output") == "json_response":
            from run_stage import parse_output
            session = parse_output(adapter.runner, stdout)[1]
        if session:
            info = json.loads((tdir / "exit.json").read_text(encoding="utf-8"))
            self._write_exit(tdir, {**info, "session_id": session})
        try:
            self.finish_task(task_id, exit_code=0 if timed_out else exit_code, seconds=seconds, timed_out=timed_out,
                             session_id=session)
        except SentinelError as err:
            if err.code != "E_TRANSITION":
                raise  # a cancel or a recovery finished it first; its state stands
            if session and not self._task_row(task_id)["session_id"]:
                with self.reg.transaction():  # a recovery finished the task before the logs were complete
                    self.reg.update_row("tasks", task_id, session_id=session)
        return self._outcome(task_id, exit_code=exit_code, stderr_tail=self._tail(stderr))

    @staticmethod
    def _write_exit(tdir, info):
        tmp = tdir / "exit.json.tmp"
        tmp.write_text(json.dumps(info), encoding="utf-8")
        os.replace(tmp, tdir / "exit.json")

    @staticmethod
    def _tail(text, n=20):
        return "\n".join((text or "").strip().splitlines()[-n:])

    def _progress(self, run, task_id, elapsed, size, tdir):
        task = self._task_row(task_id)
        changed, _ = self._changed_files(run, task, tdir)
        with self.reg.transaction():
            self._task_event(run, task_id, "task.progress", machines.ENGINE,
                             {"elapsed_seconds": elapsed, "output_bytes": size, "changed_files": changed[:50]})

    def dispatch_ready(self, slug):
        """Run every ready CLI task of a run now, one after the other (no orchestrator session). Native tasks stay
        QUEUED for the orchestrator. Returns the ids run."""
        self.bookkeep(slug)
        done = []
        while True:
            run = self._get_v2(slug)
            ready = [t for t in self.reg.rows("tasks", run_id=run["id"], state="QUEUED")
                     if t["adapter"] == "cli" and self._task_start_problem(run, t) is None]
            if not ready:
                return done
            outcome = self.run_task(ready[0]["id"])
            done.append(ready[0]["id"])
            if outcome.get("blocked") or self._task_row(ready[0]["id"])["state"] == "QUEUED":
                return done

    # ---- task complete
    def complete_task(self, task_id, caller_task=None):
        """`sentinel task complete`: the orchestrator says a native task is done; the engine decides the outcome."""
        self._refuse_agent(task_id, "task complete", caller_task)
        check_task_id(task_id)
        t = self._task_row(task_id)
        slug = self.reg.get_run_by_id(t["run_id"])["slug"]
        self._sync(slug)
        t = self._task_row(task_id)
        if t["adapter"] != "native":
            raise SentinelError("E_PRECONDITION", f"task {task_id} is not a native task; it completes by itself",
                                {"adapter": t["adapter"]})
        if t["state"] != "WAITING_FOR_INPUT":
            raise SentinelError("E_TRANSITION", f"task {task_id} is {t['state']}, only a waiting native task completes",
                                {"state": t["state"]})
        age = _seconds_since(t["started_at"])
        late = age is not None and age > (t["timeout_seconds"] or DEFAULT_TIMEOUT)
        row = self.finish_task(task_id, exit_code=0, timed_out=late)
        self.audit("orchestrator", "cli", "task_complete", task_id)
        completion = row.get("completion")
        return self._outcome(task_id, **({"completion": completion} if completion else {}))

    # ---- next
    def _task_step(self, t, run, label=None, **extra):
        native = t["adapter"] == "native"
        waiting = t["state"] == "WAITING_FOR_INPUT"
        tdir = self.task_dir(run["slug"], t["id"])
        step = {"kind": "task", "task": t["id"], "role": t["role"], "adapter": t["adapter"], "provider": t["provider"],
                "state": t["state"],
                "label": label or ("waiting for orchestrator" if native else "ready to run"),
                "command": f"sentinel task complete {t['id']}" if waiting else f"sentinel task run {t['id']}"}
        if waiting:
            step.update(prompt=str(tdir / "prompt.md"), result=str(tdir / "result.json"))
        step.update(extra)
        return step

    def _stop_notices(self, run):
        """Native tasks cancelled or timed out while a subagent was working: tell the orchestrator once."""
        events = self.reg.list_events(run["id"])
        waited = {e["task_id"] for e in events if e["type"] == "task.waiting"}
        told = {e["task_id"] for e in events if e["type"] == "task.stop_requested"}
        stops = [t["id"] for t in self.reg.rows("tasks", run_id=run["id"])
                 if t["adapter"] == "native" and t["id"] in waited and t["id"] not in told
                 and (t["state"] == "CANCELLED" or (t["state"] == "FAILED" and t["error_code"] == "E_TIMEOUT"))]
        if stops:
            with self.reg.transaction():
                for tid in stops:
                    self._task_event(run, tid, "task.stop_requested", machines.ENGINE, {})
        return stops

    def next_step(self, slug):
        """`sentinel next`: exactly one step. kind is task, orchestrator, human, wait or done; "exit" is 6 for human."""
        self._get_v2(slug)
        run = self.bookkeep(slug)
        state = run["state"]
        base = {"run": slug, "state": state}
        stops = self._stop_notices(run) if state not in machines.RUN_FINAL else []
        if stops:
            return {**base, "kind": "orchestrator", "stop_tasks": stops, "exit": 0,
                    "action": "stop the subagent of task " + ", ".join(stops)}
        step = self._step_for(run, base)
        step.setdefault("exit", 6 if step["kind"] == "human" else 0)
        return step

    def _step_for(self, run, base):
        slug, state = run["slug"], run["state"]
        sdir = self.state_dir.name
        if state == "CREATED":
            return {**base, "kind": "orchestrator", "action": "triage the request",
                    "command": f"sentinel triage {slug} --factors repos=N,files=N,migration=no,auth=no,security=none,"
                               "regression=low,logic=simple"}
        if state == "TRIAGED":
            return {**base, "kind": "orchestrator", "action": f"write {sdir}/runs/{slug}/decisions.md",
                    "path": f"{sdir}/runs/{slug}/decisions.md"}
        if state in ("SPECIFICATION_REVIEW", "GHERKIN_REVIEW"):
            gate, what = ("spec", "the specification") if state == "SPECIFICATION_REVIEW" else ("gherkin", "the Gherkin scenarios")
            return {**base, "kind": "human", "reason": f"review and approve {what}",
                    "commands": [f"sentinel review {slug} {gate}", f"sentinel approve {slug} {gate}"]}
        if state == "NEEDS_HUMAN":
            return {**base, "kind": "human", "reason": self._state_reason(run, "NEEDS_HUMAN") or "a human decision is needed"}
        if state == "BLOCKED":
            reason = self._state_reason(run, "BLOCKED") or "blocked"
            m = re.match(r"runner not installed: (\S+)", reason)
            fix = (f"install {m.group(1)} or change the runner of the agent in sentinel.config.yaml (agents.<role> or routing)"
                   if m else "resolve the blocker, then run `sentinel next` again")
            return {**base, "kind": "human", "reason": reason, "fix": fix}
        if state in machines.RUN_FINAL:
            return {**base, "kind": "done", "execution": run["execution_status"], "acceptance": run["acceptance_status"]}
        return self._task_steps(run, base)

    def _state_reason(self, run, to):
        """The reason of the latest change of the run into `to`."""
        for ev in reversed(self.reg.list_events(run["id"], "run.state_changed")):
            if ev["payload"].get("to") == to:
                return ev["payload"].get("reason")
        return None

    def _task_steps(self, run, base):
        tasks = self.reg.rows("tasks", run_id=run["id"])
        queued = [t for t in tasks if t["state"] == "QUEUED"]
        for t in queued:
            if self._task_start_problem(run, t) is None:
                return {**base, **self._task_step(t, run)}
        waiting = [t for t in tasks if t["state"] == "WAITING_FOR_INPUT" and t["adapter"] == "native"]
        if waiting:
            return {**base, **self._task_step(waiting[0], run)}
        active = [t["id"] for t in tasks if t["state"] in ACTIVE]
        if active or queued:
            return {**base, "kind": "wait", "tasks": active,
                    "reason": "waiting for running tasks" if active else "queued tasks cannot start yet"}
        return {**base, "kind": "human", "reason": f"no task planned for {run['state']}"}
