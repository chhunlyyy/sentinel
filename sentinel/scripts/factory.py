"""Factory driver (Sentinel 2.0, W1): the engine does the work an AI tool does for a run that is not engine-driven.

For a run with `driver = engine` the Dispatcher calls `drive` on every pass. `drive` takes the same step `sentinel next`
would hand to the skill (`RuntimeOps._step_for`) and does it here:

- triage: an agent task with role `triage` returns the seven factors as JSON; once it is COMPLETED the engine applies the
  same transition `sentinel triage` applies (`Engine.triage`).
- decisions: an agent task with role `planner` writes decisions.md in its write scope; the engine copies it into the run
  folder and continues the run with `bookkeep`, the function `sentinel next` calls first.
- verify: `verify` calls `Engine.verify`, the function `sentinel verify` calls, in this process.
- stop notices: the task is cancelled through the adapter of that task.

Agents never decide anything: a result is checked by `result_problems` before the task can be COMPLETED, and the tier is
computed by the engine from the factors. `snapshot` builds the factory view for the dashboard from the registry.
"""
import hashlib
import json
import os
from pathlib import Path

import adapters
import machines
from errors import SentinelError

DRIVER_DEFAULT = "engine"
MAX_TASKS_PER_PROJECT = 2
MAX_AGENTS = 4
PREFLIGHT = "routing preflight failed: "
FACTOR_KEYS = tuple(machines.FACTORS)
# every role an engine-driven run may start; qa_red joins when the QA scenario rule is on
ENGINE_ROLES = ("triage", "planner", "specifier", "test_designer", "tdd_red", "tdd_green", "tdd_refactor", "reviewer", "qa",
                "hardener", "docs")
OPEN = ("CREATED", "QUEUED", "RUNNING", "WAITING_FOR_INPUT")
LIVE = ("RUNNING", "WAITING_FOR_INPUT")


def factory_config(config):
    """The `factory` block with its defaults: {"driver", "max_tasks_per_project", "max_agents"}."""
    block = (config or {}).get("factory") or {}
    out = {"driver": block.get("driver") or DRIVER_DEFAULT,
           "max_tasks_per_project": block.get("max_tasks_per_project", MAX_TASKS_PER_PROJECT),
           "max_agents": block.get("max_agents", MAX_AGENTS)}
    for key, default in (("max_tasks_per_project", MAX_TASKS_PER_PROJECT), ("max_agents", MAX_AGENTS)):
        value = out[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            out[key] = default
    if out["driver"] not in ("engine", "ai-tool"):
        out["driver"] = DRIVER_DEFAULT
    return out


# ---- whole-factory pause (stored in the user config dir, read by the service on every pass)
PAUSE_FILE = "factory.json"


def pause_state(cfgdir=None):
    """{"paused": bool, "paused_at": str|None} from <config dir>/factory.json. A missing or unreadable file means running."""
    from apiserver import userdir
    path = (userdir.config_dir() if cfgdir is None else Path(cfgdir)) / PAUSE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"paused": False, "paused_at": None}
    if not isinstance(data, dict) or data.get("paused") is not True:
        return {"paused": False, "paused_at": None}
    at = data.get("paused_at")
    return {"paused": True, "paused_at": at if isinstance(at, str) else None}


def set_paused(cfgdir, paused, user, channel, comment=None, projects=None):
    """Pause or resume the whole factory: the service starts no new agent task in any project while paused; running tasks
    finish and runs keep their own paused flag. Idempotent. Each change is audited in every available project.
    Returns the new state."""
    from apiserver import userdir
    from apiserver.projects import ProjectSet
    cfgdir = Path(cfgdir) if cfgdir is not None else userdir.config_dir()
    paused = bool(paused)
    if pause_state(cfgdir)["paused"] == paused:
        return pause_state(cfgdir)
    userdir.ensure_dir(cfgdir)
    state = {"paused": True, "paused_at": userdir.now()} if paused else {"paused": False, "paused_at": None}
    userdir._atomic_write(cfgdir / PAUSE_FILE, json.dumps(state, indent=2) + "\n")
    projects = projects or ProjectSet(cfgdir)
    for project in projects.list():
        try:
            if projects.probe(project)[0] != "available":
                continue
            with projects.engine(project, user, channel) as eng:
                eng.audit(user, channel, "factory_pause" if paused else "factory_resume", "factory", reason=comment)
        except Exception:
            continue   # one broken project must not undo the change
    return state


def max_agents_over(projects):
    """The largest `factory.max_agents` over the available projects (default 4)."""
    best = None
    for project in projects.list():
        try:
            if projects.probe(project)[0] != "available":
                continue
            best = max(best or 0, factory_config(projects.require(project))["max_agents"])
        except Exception:
            continue
    return best or MAX_AGENTS


# ---- routing preflight
def routing_problems(config):
    """[text] for every role an engine-driven run may use that does not route to a CLI runner (the native adapter needs an
    AI tool session). Empty when the run can start."""
    import run_stage
    from tasks import select_adapter
    roles = list(ENGINE_ROLES)
    try:
        import qa_scenarios
        if (config.get("rules") or {}).get(qa_scenarios.RULE):
            roles.insert(roles.index("tdd_green"), "qa_red")
    except ImportError:
        pass
    runners = run_stage.all_runners(config)
    repos = [r["id"] for r in config.get("repos") or [] if isinstance(r, dict) and r.get("id")]
    problems = []
    for role in roles:
        found = None
        for repo in [None, *repos]:
            adapter, runner, _ = select_adapter(config, role, repo)
            if adapter != "cli":
                found = f"{role} routes to the native adapter" + (f" (repo {repo})" if repo else "")
            elif runner not in runners:
                found = f"{role} routes to runner {runner}, which is not defined"
            if found:
                break
        if found:
            problems.append(found)
    return problems


def preflight_message(slug, problems):
    return (f"{PREFLIGHT}an engine-driven run needs a CLI runner for every role: {'; '.join(problems)}. "
            f"Set agents.<role>.runner (or routing) in sentinel.config.yaml, then run "
            f"`sentinel resolve {slug} --refresh-config -m \"<why>\"`; the engine then resumes the run")


# ---- results (called by the task judge, so an invalid result fails the task and follows the normal retry rules)
def decisions_path(eng, slug):
    return eng.state_dir / "shared" / "specs" / slug / "decisions.md"


def factor_problems(factors):
    """[text] for a `factors` value: all seven keys, each value valid under the rules `sentinel triage` uses."""
    if not isinstance(factors, dict):
        return ["factors: must be an object with the seven triage factors"]
    missing = [k for k in FACTOR_KEYS if k not in factors]
    if missing:
        return [f"factors: missing {', '.join(missing)}"]
    try:
        machines.compute_tier({k: str(v) for k, v in factors.items()})
    except SentinelError as err:
        return [f"factors: {err.message}"]
    return []


def result_problems(eng, run, task, data):
    """[text] when a completed result of a factory role does not carry what the engine needs; [] for every other role."""
    role = task["role"]
    if role == "triage":
        return factor_problems(data.get("factors"))
    if role == "planner":
        try:
            text = decisions_path(eng, run["slug"]).read_text(encoding="utf-8")
        except (OSError, ValueError):
            return ["decisions.md was not written in the shared specs folder of the run"]
        return [] if text.strip() else ["decisions.md is empty"]
    return []


# ---- driving
def _tasks(eng, run, role):
    return [t for t in eng.reg.rows("tasks", run_id=run["id"]) if t["role"] == role]


def _repos(eng, run):
    cfg = eng._run_config(run)
    return [r["repo_id"] for r in eng.reg.run_repos(run["id"])] or \
        [r["id"] for r in cfg.get("repos") or [] if isinstance(r, dict) and r.get("id")]


def _request_brief(run):
    return "## Request\n\n" + (run.get("request") or "(no request text was stored for this run)").strip() + "\n"


def _plan_task(eng, run, role, objective):
    repos = _repos(eng, run)
    if not repos:
        raise SentinelError("E_PRECONDITION", f"run {run['slug']} has no repos for its {role} task")
    return eng.create_task(run["slug"], role, objective, repos=repos, brief=_request_brief(run), queue=True)


def _park(eng, slug, reason):
    try:
        eng.request_state(slug, "NEEDS_HUMAN", machines.ENGINE, reason=reason)
    except SentinelError:
        pass


def _result_doc(eng, run, task):
    """The stored result of a COMPLETED task, read from the artifact the engine saved (never from the task folder) and
    checked against its hash."""
    art = eng.reg.get_row("artifacts", task["result_artifact_id"]) if task["result_artifact_id"] else None
    if not art:
        raise SentinelError("E_INTEGRITY", f"task {task['id']} has no stored result")
    raw = (eng.state_dir / art["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != art["sha256"]:
        raise SentinelError("E_INTEGRITY", f"the stored result of task {task['id']} was changed")
    return json.loads(raw)


def apply_triage(eng, run, task):
    """The triage transition, exactly as `sentinel triage` does it, from the factors of a COMPLETED triage task."""
    data = _result_doc(eng, run, task)
    factors = {k: str(v) for k, v in data["factors"].items()}
    eng.triage(run["slug"], factors, machines.ORCHESTRATOR)
    eng.audit("engine", "engine", "factory_triage", run["slug"], reason=f"task {task['id']}")
    return {"action": "triaged", "task": task["id"]}


def apply_decisions(eng, run, task):
    """Copy the planner's decisions.md into the run folder (the file `bookkeep` waits for), then continue the run."""
    src = decisions_path(eng, run["slug"])
    dest = eng.run_dir(run["slug"]) / "decisions.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".decisions.md.{os.getpid()}.tmp")
    tmp.write_bytes(src.read_bytes())
    os.replace(tmp, dest)
    eng.audit("engine", "engine", "factory_decisions", run["slug"], reason=f"task {task['id']}")
    eng.bookkeep(run["slug"])
    return {"action": "planned", "task": task["id"]}


def _handle_role(eng, run, role, objective, apply):
    """One factory role: plan its task once, wait while it is open, apply it when it completed."""
    tasks = _tasks(eng, run, role)
    if not tasks:
        row = _plan_task(eng, run, role, objective)
        return {"action": f"planned {role} task", "task": row["id"]}
    if any(t["state"] in OPEN for t in tasks):
        return {"action": "wait", "reason": f"{role} task is open"}
    last = tasks[-1]
    if last["state"] == "COMPLETED":
        return apply(eng, run, last)
    return {"action": "wait", "reason": f"{role} task is {last['state']}"}  # a human retries or cancels it


def stop_notices(eng, run):
    """Cancel, through the adapter of the task, every task a stop notice names."""
    stopped = []
    for tid in eng._stop_notices(run):
        t = eng.get_task(tid)
        adapter = eng.adapter_for("native" if t["adapter"] == "native" else t["provider"], run["slug"])
        adapter.cancel(adapters.Handle(tid, pid=t["pid"], pid_started_at=t["pid_started_at"], session_id=t["session_id"],
                                       workdir=str(eng.workspace), model=t["model"],
                                       task_dir=str(eng.task_dir(run["slug"], tid))))
        stopped.append(tid)
    return stopped


def _state_reason(eng, run):
    return eng._state_reason(run, "BLOCKED") or ""


def drive(eng, slug):
    """One pass for one engine-driven run. Returns what was done: {"action": ...}, or None when the run is not the engine's
    to drive (another driver, paused, finished). Raises nothing for a refused transition; the run is parked instead."""
    run = eng._get_v2(slug)
    if run["driver"] != "engine" or run["paused"] or run["state"] in machines.RUN_FINAL:
        return None
    if run["state"] == "CREATED":
        problems = routing_problems(eng._run_config(run))
        if problems:
            message = preflight_message(slug, problems)
            eng.audit("engine", "engine", "routing_preflight_failed", slug, reason="; ".join(problems))
            eng.request_state(slug, "BLOCKED", machines.ENGINE, reason=message)
            return {"action": "blocked", "reason": message}
    if run["state"] == "BLOCKED" and _state_reason(eng, run).startswith(PREFLIGHT) \
            and not routing_problems(eng._run_config(run)):
        eng.request_state(slug, run["previous_state"], machines.ENGINE, reason="routing preflight passes")  # R22, after a refreshed snapshot
    run = eng.bookkeep(slug)
    if run["state"] in machines.RUN_FINAL or run["paused"]:
        return {"action": "idle"}
    stopped = stop_notices(eng, run)
    step = eng._step_for(run, {"run": slug, "state": run["state"]})
    if step["kind"] != "orchestrator":
        return {"action": step["kind"], **({"stopped": stopped} if stopped else {})}
    try:
        if run["state"] == "CREATED":
            return _handle_role(eng, run, "triage", f"Triage the request of {slug}", apply_triage)
        if run["state"] == "TRIAGED":
            return _handle_role(eng, run, "planner", f"Write the decisions of {slug}", apply_decisions)
    except SentinelError as err:
        _park(eng, slug, f"factory step failed: {err.code}: {err.message}")
        return {"action": "parked", "reason": err.message}
    if run["state"] == "VERIFYING":
        return {"action": "verify"}
    return {"action": "wait", "reason": step.get("action")}


def verify(eng, slug):
    """`sentinel verify`, in this process: one verification round through the same engine function."""
    return eng.verify(slug)


# ---- the factory snapshot
STATIONS = ("intake", "triage", "spec", "gate_spec", "gherkin", "gate_gherkin", "build", "verify", "report", "gate_accept",
            "knowledge")
GATE_STATIONS = ("gate_spec", "gate_gherkin", "gate_accept")
STATE_STATION = {"CREATED": "triage", "TRIAGED": "triage", "PLANNED": "spec", "SPECIFICATION_REVIEW": "gate_spec",
                 "SPECIFICATION_APPROVED": "gherkin", "GHERKIN_REVIEW": "gate_gherkin", "GHERKIN_APPROVED": "build",
                 "EXECUTING": "build", "VERIFYING": "verify", "REVIEWING": "report"}
ROLE_STATION = {"triage": "triage", "planner": "triage", "specifier": "spec", "test_designer": "gherkin",
                "reviewer": "report", "qa": "report"}  # every other role works in the build station
CYCLE_ORDER = ("PLANNED", "RED_RUNNING", "RED_VERIFIED", "GREEN_RUNNING", "GREEN_VERIFIED", "REFACTOR_RUNNING",
               "REFACTOR_VERIFIED", "CYCLE_ACCEPTED")
PHASES = (("red", "RED_RUNNING", "RED_VERIFIED", "red_task"), ("green", "GREEN_RUNNING", "GREEN_VERIFIED", "green_task"),
          ("refactor", "REFACTOR_RUNNING", "REFACTOR_VERIFIED", "refactor_task"))
TITLE_MAX = 80


def title_of(run):
    first = (run.get("request") or "").strip().splitlines()
    text = first[0].strip() if first else ""
    return (text[:TITLE_MAX - 1] + "…" if len(text) > TITLE_MAX else text) or run["slug"]


def _lanes(reg, run, tasks, paused):
    by_id = {t["id"]: t for t in tasks}
    lanes = []
    for c in reg.rows("cycles", run_id=run["id"]):
        if c["state"] == "REJECTED":
            lane = {"red": "todo", "green": "todo", "refactor": "todo"}
        else:
            at = CYCLE_ORDER.index(c["state"]) if c["state"] in CYCLE_ORDER else 0
            lane = {}
            for phase, running, verified, col in PHASES:
                if at >= CYCLE_ORDER.index(verified):
                    lane[phase] = "done"
                elif at == CYCLE_ORDER.index(running):
                    lane[phase] = "paused" if paused else "working"
                elif (by_id.get(c.get(col)) or {}).get("state") in ("CREATED", "QUEUED"):
                    lane[phase] = "queued"
                else:
                    lane[phase] = "todo"
        lanes.append({"cycle": c["id"], "name": c["behavior"], "repo": c.get("repo_id"), "state": c["state"], **lane})
    return lanes


def _knowledge(reg, slug):
    jobs = [j for j in reg.rows("kb_jobs", run_slug=slug) if j["kind"] == "kb_harvest"]
    return jobs[-1]["state"] if jobs else None


def _station_states(eng, run, tasks, paused):
    """(current station, {station: state}, attention) from the run state, its tasks and its verification and knowledge rows."""
    reg = eng.reg
    state = run["state"]
    attention = None
    if state == "COMPLETED":
        if eng.human_acceptance(run) == "pending":
            current, here = "gate_accept", "waiting"
        else:
            current = "knowledge"
            job = _knowledge(reg, run["slug"])
            here = {"running": "working", "queued": "queued", "done": "done", "failed": "waiting"}.get(job, "queued")
    else:
        parked = state in ("NEEDS_HUMAN", "BLOCKED")
        current = STATE_STATION[(run["previous_state"] or "CREATED") if parked else state]
        if parked:
            here = "waiting"
            attention = {"kind": state.lower(), "reason": eng._state_reason(run, state)}
        elif current in GATE_STATIONS:
            here = "waiting"
        else:
            mine = [t for t in tasks if ROLE_STATION.get(t["role"], "build") == current]
            rounds = reg.rows("verification_rounds", run_id=run["id"]) if current == "verify" else []
            if any(t["state"] in LIVE for t in mine) or any(not r["finished_at"] and not r["interrupted"] for r in rounds):
                here = "working"
            else:
                here = "queued"
        if paused and here in ("working", "queued"):
            here = "paused"
    index = STATIONS.index(current)
    states = {}
    for i, station in enumerate(STATIONS):
        states[station] = "done" if i < index else here if i == index else "next" if i == index + 1 else "todo"
    if current == "knowledge" and here == "done":
        states["knowledge"] = "done"
    return current, states, attention


def _agents(tasks, current, states):
    out = {}
    if states.get(current) not in ("working", "paused"):
        return out
    for t in tasks:
        if t["state"] in LIVE and ROLE_STATION.get(t["role"], "build") == current:
            out.setdefault(current, []).append({"task": t["id"], "role": t["role"], "runner": t["provider"],
                                                "model": t["model"], "adapter": t["adapter"], "started_at": t["started_at"]})
    return out


WHO_ROLES = (("triage", "triage"), ("spec", "specifier"), ("gherkin", "test_designer"), ("build", "tdd_green"))
STATION_LABEL = {"intake": "Intake", "triage": "Triage", "spec": "Specification", "gherkin": "Gherkin", "build": "Build",
                 "verify": "Verification", "report": "Report", "knowledge": "Knowledge"}
ACTIVITY_MAX = 20


def who(config):
    """{station: {"role", "runner", "model"}} for the agent stations, from the routing the dispatcher uses (`select_adapter`;
    knowledge summaries use the route `find_route` gives, as knowledge.py does). A station without a CLI route is left out."""
    from run_stage import find_route
    from tasks import select_adapter
    out = {}
    for station, role in WHO_ROLES:
        adapter, runner, model = select_adapter(config, role)
        if adapter == "cli":
            out[station] = {"role": role, "runner": runner, "model": model}
    route = find_route(config, "knowledge") or find_route(config, "coder")
    if route and route.get("runner"):
        out["knowledge"] = {"role": "knowledge", "runner": route["runner"], "model": route.get("model")}
    return out


def _activity_station(type_, p):
    if type_ in ("approval.requested", "approval.decided"):
        return "gate_spec" if p.get("gate") == "specification" else "gate_gherkin"
    if type_ == "acceptance.decided":
        return "gate_accept"
    if type_ == "knowledge.failed":
        return "knowledge"
    return ROLE_STATION.get(p["role"], "build") if p.get("role") else "intake"


def _activity_text(type_, p, station):
    label = STATION_LABEL.get(station, station)
    state = p.get("state")
    if type_ == "task.started":
        return f"{label} agent started"
    if type_ == "task.finished":
        return {"COMPLETED": f"{label} agent finished", "FAILED": f"{label} agent failed"}.get(state)
    if type_ == "approval.requested":
        return f"{'Specification' if p.get('gate') == 'specification' else 'Gherkin'} is waiting for you"
    if type_ == "approval.decided":
        what = "Changes requested on" if p.get("decision") in ("changes", "changes_requested") else "You approved"
        return f"{what} the {'specification' if p.get('gate') == 'specification' else 'Gherkin'}"
    if type_ == "acceptance.decided":
        return "You accepted the result" if p.get("decision") == "accept" else "You rejected the result"
    return {"run.created": "Task created", "run.paused": "Run paused", "run.unpaused": "Run resumed",
            "run.note_added": "Note added", "knowledge.failed": "Knowledge job failed"}.get(type_)


ACTIVITY_TYPES = ("task.started", "task.finished", "approval.requested", "approval.decided", "acceptance.decided", "run.created",
                  "run.paused", "run.unpaused", "run.note_added", "knowledge.failed")


def activity(reg, slugs):
    """The latest registry rows of the given runs as [{"at", "run", "station", "text"}], newest first, at most ACTIVITY_MAX."""
    marks = ",".join("?" * len(ACTIVITY_TYPES))
    items = []
    for row in reg._c.execute(
            f"SELECT e.at, e.type, e.payload, r.slug FROM events e JOIN runs r ON r.id = e.run_id WHERE e.type IN ({marks}) "
            "ORDER BY e.id DESC LIMIT 400", ACTIVITY_TYPES):
        if row["slug"] not in slugs:
            continue
        p = json.loads(row["payload"]) if row["payload"] else {}
        p = p if isinstance(p, dict) else {}
        t = row["type"]
        station = _activity_station(t, p)
        text = _activity_text(t, p, station)
        if text:
            items.append({"at": row["at"], "run": row["slug"], "station": station, "text": text})
    for job in reg.rows("kb_jobs"):
        if job["kind"] == "kb_harvest" and job["state"] == "done" and job["run_slug"] in slugs:
            items.append({"at": job["updated_at"], "run": job["run_slug"], "station": "knowledge", "text": "Knowledge job done"})
    items.sort(key=lambda i: i["at"] or "", reverse=True)
    return items[:ACTIVITY_MAX]


def running_tasks(reg):
    """How many tasks are RUNNING in a registry."""
    return reg._c.execute("SELECT COUNT(*) FROM tasks WHERE state='RUNNING'").fetchone()[0]


def snapshot(eng, project_id, total_running=None, now=None, factory_paused=False):
    """The factory of one project: every non-final run with its stations, build lanes and agents, plus the queue of runs the
    limits keep from starting. Everything is read from the registry and the engine's own views; nothing is stored for display.
    A COMPLETED run stays until its acceptance is decided and its knowledge job ended. `total_running` is the number of
    running tasks over all projects (the global limit); it defaults to this project's own count. `factory_paused` is the
    whole-factory pause flag; `who` and `activity` are built from the routing config and the registry."""
    reg = eng.reg
    limits = factory_config(eng.config)
    here = running_tasks(reg)
    total = max(here, total_running if total_running is not None else here)
    full = None
    if here >= limits["max_tasks_per_project"]:
        full = f"the project limit of {limits['max_tasks_per_project']} running tasks is reached"
    elif total >= limits["max_agents"]:
        full = f"the limit of {limits['max_agents']} running agents is reached"
    runs, queue = [], []
    for run in reg.list_runs():
        if run["workflow_version"] != "2" or run["state"] in ("FAILED", "CANCELLED"):
            continue
        if run["state"] == "COMPLETED" and eng.human_acceptance(run) != "pending" and \
                _knowledge(reg, run["slug"]) not in ("queued", "running"):
            continue
        tasks = reg.rows("tasks", run_id=run["id"])
        paused = bool(run["paused"])
        current, states, attention = _station_states(eng, run, tasks, paused)
        item = {"slug": run["slug"], "title": title_of(run), "type": run["type"], "driver": run["driver"], "paused": paused,
                "state": run["state"], "tier": run["tier"], "station": current, "stations": states,
                "next_station": STATIONS[STATIONS.index(current) + 1] if current != STATIONS[-1] else None,
                "agents": _agents(tasks, current, states), "lanes": _lanes(reg, run, tasks, paused), "attention": attention,
                "pending_notes": len(eng.unread_notes(run)), "created_at": run["created_at"], "updated_at": run["updated_at"]}
        runs.append(item)
        if full and run["driver"] != "cli" and not paused and run["state"] not in machines.RUN_FINAL \
                and not any(t["state"] in LIVE for t in tasks) \
                and any(t["state"] == "QUEUED" and t["adapter"] == "cli" for t in tasks):
            queue.append({"slug": run["slug"], "title": item["title"], "position": len(queue) + 1, "reason": full})
    return {"project": project_id, "generated_at": now or _now(), "stations": list(STATIONS),
            "limits": {**limits, "running_in_project": here, "running_total": total}, "runs": runs, "queue": queue,
            "factory_paused": bool(factory_paused), "who": who(eng.config), "activity": activity(reg, {r["slug"] for r in runs})}


def _now():
    from registry import _now as now
    return now()
