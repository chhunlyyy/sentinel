"""Read side of the API: JSON documents built from the registry through the engine and read-only queries."""
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

import artifacts as A
import machines
from errors import SentinelError
from paths import ROOT, slug_problem

LIMIT_DEFAULT, LIMIT_MAX = 50, 200
LOG_CHUNK = 1024 * 1024
APPROVAL_STATES = ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "REJECTED", "APPROVED", "INVALIDATED")
GATES = ("specification", "gherkin")


def validation(message, field=None, **details):
    if field:
        details["field"] = field
    return SentinelError("E_VALIDATION", message, details)


# ---- paging
def parse_limit(query):
    raw = query.get("limit")
    if raw is None:
        return LIMIT_DEFAULT
    try:
        n = int(raw)
    except ValueError:
        raise validation(f"limit must be an integer from 1 to {LIMIT_MAX}", "limit")
    if not 1 <= n <= LIMIT_MAX:
        raise validation(f"limit must be an integer from 1 to {LIMIT_MAX}", "limit")
    return n


def encode_cursor(*parts):
    return base64.urlsafe_b64encode(json.dumps(list(parts)).encode()).decode().rstrip("=")


def decode_cursor(text, size):
    try:
        data = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode())
        if isinstance(data, list) and len(data) == size:
            return data
    except (ValueError, UnicodeDecodeError):
        pass
    raise validation("cursor is not valid", "cursor")


# ---- projects and runs
def project_item(projects, project, with_counts=True):
    status, reason = projects.probe(project)
    item = {**project.public(), "status": status}
    if reason:
        item["reason"] = reason
    item["active_runs"] = 0
    if status == "available" and with_counts:
        with projects.reader(project) as conn:
            if conn is not None:
                item["active_runs"] = conn.execute(
                    "SELECT COUNT(*) FROM runs WHERE execution_status='running'").fetchone()[0]
    return item


RUN_LIST_COLUMNS = ("slug", "type", "tier", "state", "execution_status", "acceptance_status", "workflow_version",
                    "priority", "requested_tier", "origin", "created_at", "updated_at")


def list_runs(projects, project, query):
    limit = parse_limit(query)
    cursor = decode_cursor(query["cursor"], 2) if query.get("cursor") else None
    projects.require(project)
    with projects.reader(project) as conn:
        if conn is None:
            return {"items": [], "next": None}
        sql = f"SELECT {','.join(RUN_LIST_COLUMNS)} FROM runs"
        args = []
        if cursor:
            sql += " WHERE (updated_at < ? OR (updated_at = ? AND slug < ?))"
            args += [cursor[0], cursor[0], cursor[1]]
        sql += " ORDER BY updated_at DESC, slug DESC LIMIT ?"
        rows = [dict(r) for r in conn.execute(sql, [*args, limit + 1])]
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": rows, "next": encode_cursor(rows[-1]["updated_at"], rows[-1]["slug"]) if more else None}


def locate_run(projects, slug, pid=None):
    """The project that holds run `slug`. `pid` is required only when the slug exists in more than one project."""
    problem = slug_problem(slug)
    if problem:
        raise validation(problem, "slug")
    if pid:
        project = projects.get(pid)
        projects.require(project)
        with projects.reader(project) as conn:
            if conn is None or not conn.execute("SELECT 1 FROM runs WHERE slug=?", (slug,)).fetchone():
                raise SentinelError("E_NOT_FOUND", f"no run named {slug}", {"slug": slug})
        return project
    found = []
    for project in projects.list():
        if projects.probe(project)[0] != "available":
            continue
        with projects.reader(project) as conn:
            if conn is not None and conn.execute("SELECT 1 FROM runs WHERE slug=?", (slug,)).fetchone():
                found.append(project)
    if not found:
        raise SentinelError("E_NOT_FOUND", f"no run named {slug}", {"slug": slug})
    if len(found) > 1:
        raise validation(f"run {slug} exists in more than one project; add ?project=<id>", "project",
                         projects=sorted(p.id for p in found))
    return found[0]


def _latest(rows):
    return rows[-1] if rows else None


def approval_summary(reg, run):
    out = {}
    for gate in GATES:
        ap = _latest(reg.rows("approvals", run_id=run["id"], gate=gate))
        if ap:
            out[gate] = {"state": ap["state"], "version": ap["version"], "sha256": ap["sha256"],
                         "decision": ap["decision"], "approver": ap["approver"], "channel": ap["channel"],
                         "comment": ap["comment"], "decided_at": ap["decided_at"]}
    return out


def _mark_dashboard(step, run, slug):
    if run.get("origin") == "dashboard" and step.get("kind") == "orchestrator":
        step["label"] = "waiting for AI tool"
        step["resume_command"] = f"/sentinel resume {slug}"
    return step


def next_step(eng, slug, run):
    """What `sentinel next --json` prints: the engine does its bookkeeping first, exactly as for the CLI."""
    step = eng.next_step(slug)
    step.pop("exit", None)
    return _mark_dashboard(step, run, slug)


def peek_step(eng, slug, run):
    """The step for a run detail: no bookkeeping, so reading a run never starts or queues anything."""
    if run["state"] in ("GHERKIN_APPROVED", "SPECIFICATION_APPROVED"):
        step = {"run": slug, "state": run["state"], "kind": "wait",
                "reason": "execution starts when the engine takes its next step (`sentinel next`)"}
    else:
        step = eng._step_for(run, {"run": slug, "state": run["state"]})
    step.pop("exit", None)
    return _mark_dashboard(step, run, slug)


def run_detail(eng, project, slug):
    """The run as the engine stored it, after applying changes to the shared files (as `sentinel review` does)."""
    run = eng._get(slug)
    v2 = run["workflow_version"] == "2"
    if v2:
        run = eng.load_run(slug)
    reg = eng.reg
    counts = {}
    for t in reg.rows("tasks", run_id=run["id"]):
        counts[t["state"]] = counts.get(t["state"], 0) + 1
    detail = {k: run.get(k) for k in ("slug", "request", "type", "tier", "initial_tier", "state", "execution_status",
                                      "acceptance_status", "workflow_version", "priority", "requested_tier", "origin",
                                      "created_at", "updated_at", "finished_at")}
    detail["project"] = project.id
    detail["repos"] = [{"repo_id": r["repo_id"], "baseline_sha": r["baseline_sha"], "branch": r["branch"],
                        "final_sha": r["final_sha"]} for r in reg.run_repos(run["id"])]
    detail["approvals"] = approval_summary(reg, run) if v2 else {}
    detail["task_counts"] = counts
    detail["next"] = peek_step(eng, slug, run) if v2 else None
    return detail


def workflow(reg, run):
    nodes, edges = [], []
    for t in reg.rows("tasks", run_id=run["id"]):
        label = "waiting for orchestrator" if t["adapter"] == "native" and t["state"] in ("QUEUED", "WAITING_FOR_INPUT") else None
        nodes.append({"id": t["id"], "role": t["role"], "repo": t["repo_id"], "state": t["state"], "adapter": t["adapter"],
                      "provider": t["provider"], "model": t["model"], "attempt": t["attempt"], "retry_of": t["retry_of"],
                      "error_code": t["error_code"], "started_at": t["started_at"], "finished_at": t["finished_at"],
                      "seconds": t["seconds"], "label": label})
        edges += [{"from": dep, "to": t["id"]} for dep in reg.task_deps(t["id"])]
    gates = [{"gate": g, **{k: a[k] for k in ("state", "version", "sha256")}}
             for g, a in approval_summary(reg, run).items()]
    return {"nodes": nodes, "edges": edges, "gates": gates}


def tdd(reg, run):
    evidence = reg.rows("evidence", run_id=run["id"])
    cycles = []
    for c in reg.rows("cycles", run_id=run["id"]):
        cycles.append({"id": c["id"], "behavior": c["behavior"], "state": c["state"],
                       "phase_tasks": {"red": c["red_task"], "green": c["green_task"], "refactor": c["refactor_task"]},
                       "evidence_ids": [e["id"] for e in evidence if e["cycle_id"] == c["id"]]})
    return {"cycles": cycles}


def verification(reg, run):
    events = reg.list_events(run["id"], "run.status_changed")
    reasons = (events[-1]["payload"] or {}).get("reasons", []) if events else []
    evidence = [{k: e[k] for k in ("id", "task_id", "cycle_id", "kind", "command", "exit_code", "classification",
                                    "passed", "failed", "skipped", "output_artifact_id", "started_at", "finished_at")}
                for e in reg.rows("evidence", run_id=run["id"])]
    return {"evidence": evidence, "acceptance": {"execution_status": run["execution_status"],
                                                 "acceptance_status": run["acceptance_status"], "reasons": reasons}}


def trace(reg, run):
    links = [{"from_kind": l["from_kind"], "from_id": l["from_id"], "to_kind": l["to_kind"], "to_id": l["to_id"]}
             for l in reg.rows("trace_links", run_id=run["id"])]
    covered = {l["from_id"] for l in links if l["from_kind"] == "ac" and l["to_kind"] == "scenario"}
    acs = {l["to_id"] for l in links if l["to_kind"] == "ac"} | {l["from_id"] for l in links if l["from_kind"] == "ac"}
    gaps = [{"kind": "ac_without_scenario", "id": a} for a in sorted(acs - covered)]
    return {"links": links, "gaps": gaps}


def specification(eng, slug):
    info = eng.review(slug, "spec")
    return {"version": info["version"], "sha256": info["sha256"], "approval_state": info["approval_state"],
            "run_state": info["run_state"], "text": info["text"],
            "validation": {"errors": info["errors"], "warnings": info["warnings"]},
            "diff": info["diff"], "previous_version": info.get("previous_version")}


def specification_version(eng, slug, version):
    run = eng._get_v2(slug)
    try:
        v = int(version)
    except ValueError:
        raise validation("version must be a number", "version")
    rows = [a for a in eng.reg.rows("artifacts", run_id=run["id"], kind="spec") if a["version"] == v]
    if not rows:
        raise SentinelError("E_NOT_FOUND", f"no specification version {v}", {"version": v})
    A.verify_stored(eng.state_dir, slug, "spec", v, rows[0]["sha256"])
    return {"version": v, "sha256": rows[0]["sha256"], "text": eng._stored_text(slug, v)}


def gherkin(eng, slug):
    info = eng.review(slug, "gherkin")
    return {"version": info["version"], "sha256": info["sha256"], "approval_state": info["approval_state"],
            "run_state": info["run_state"], "files": info["files"], "scenarios": info["scenarios"],
            "coverage": info["coverage"], "validation": {"errors": info["errors"], "warnings": info["warnings"]},
            "diff": info["diff"], "previous_version": info.get("previous_version")}


# ---- reports, artifacts, logs
def _run_dir(state_dir, slug):
    return Path(state_dir) / "runs" / slug


def report(state_dir, slug, fmt):
    if fmt not in ("json", "md"):
        raise validation("format must be json or md", "format")
    path = _run_dir(state_dir, slug) / ("report.json" if fmt == "json" else "report.md")
    if not path.is_file():
        raise SentinelError("E_PRECONDITION", f"run {slug} has no report yet", {"slug": slug})
    text = path.read_text(encoding="utf-8", errors="replace")
    if fmt == "md":
        return {"format": "md", "content": text}
    try:
        return json.loads(text)
    except ValueError:
        return {"format": "json", "content": text}


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


def artifact(reg, state_dir, slug, run, aid):
    row = reg.get_row("artifacts", aid) if isinstance(aid, str) and aid.replace("-", "").replace("_", "").isalnum() else None
    if not row or row["run_id"] != run["id"]:
        raise SentinelError("E_NOT_FOUND", f"no artifact {aid} in run {slug}", {"artifact": aid})
    path = Path(row["path"] or "")
    path = path if path.is_absolute() else Path(state_dir) / path
    if not _inside(path, _run_dir(state_dir, slug)):
        raise SentinelError("E_NOT_FOUND", f"no artifact {aid} in run {slug}", {"artifact": aid})
    if not path.exists():
        raise SentinelError("E_NOT_FOUND", f"artifact {aid} has no file", {"artifact": aid})
    stored = row["sha256"]
    if row["kind"] in ("spec", "gherkin") and row["version"]:
        actual = A.stored_hash(state_dir, slug, row["kind"], row["version"])
    elif path.is_file():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        actual = stored
    if stored and actual != stored:
        raise SentinelError("E_INTEGRITY", f"artifact {aid} no longer matches its stored hash",
                            {"artifact": aid, "stored_sha256": stored})
    if path.is_dir():
        content = "".join(f"### {p.relative_to(path).as_posix()}\n{p.read_text(encoding='utf-8', errors='replace')}\n"
                          for p in sorted(path.rglob("*")) if p.is_file())
    else:
        content = path.read_text(encoding="utf-8", errors="replace")
    return {"id": row["id"], "kind": row["kind"], "version": row["version"], "sha256": stored,
            "path": str(Path(row["path"] or "")), "content": content}


def log_tail(reg, state_dir, slug, run, task_id, query):
    ok = isinstance(task_id, str) and task_id.replace("-", "").replace("_", "").isalnum()
    task = reg.get_row("tasks", task_id) if ok else None
    if not task or task["run_id"] != run["id"]:
        raise SentinelError("E_NOT_FOUND", f"no task {task_id} in run {slug}", {"task": task_id})
    raw = query.get("offset", "0")
    try:
        offset = int(raw)
    except ValueError:
        raise validation("offset must be a non-negative integer", "offset")
    if offset < 0:
        raise validation("offset must be a non-negative integer", "offset")
    log = _run_dir(state_dir, slug) / "tasks" / task["id"] / "output.log"
    data = b""
    if log.is_file():
        size = log.stat().st_size
        if offset > size:
            raise validation("offset is past the end of the log", "offset")
        with open(log, "rb") as f:
            if offset:
                f.seek(offset - 1)
                if f.read(1) != b"\n":
                    raise validation("offset is not the start of a line", "offset")
            data = f.read(LOG_CHUNK)
    elif offset:
        raise validation("offset is past the end of the log", "offset")
    cut = data.rfind(b"\n") + 1
    whole = data[:cut]
    return {"task_id": task["id"], "lines": whole.decode("utf-8", errors="replace").splitlines(),
            "next_offset": offset + len(whole), "running": task["state"] == "RUNNING"}


# ---- approvals and audit across projects
def approvals_in(projects, state):
    if state not in APPROVAL_STATES:
        raise validation(f"state must be one of {', '.join(APPROVAL_STATES)}", "state", allowed=list(APPROVAL_STATES))
    items = []
    for project in projects.list():
        if projects.probe(project)[0] != "available":
            continue
        with projects.reader(project) as conn:
            if conn is None:
                continue
            for r in conn.execute(
                    "SELECT r.slug, a.gate, a.version, a.sha256, a.state, a.artifact_id, x.created_at AS requested_at "
                    "FROM approvals a JOIN runs r ON r.id = a.run_id LEFT JOIN artifacts x ON x.id = a.artifact_id "
                    "WHERE a.state = ? ORDER BY x.created_at DESC, r.slug", (state,)):
                items.append({"project": project.id, **dict(r)})
    return {"items": items, "next": None}


def audit_rows(projects, pid, query):
    limit = parse_limit(query)
    cursor = decode_cursor(query["cursor"], 1)[0] if query.get("cursor") else None
    targets = [projects.get(pid)] if pid else [p for p in projects.list() if projects.probe(p)[0] == "available"]
    items = []
    for project in targets:
        projects.require(project)
        with projects.reader(project) as conn:
            if conn is None:
                continue
            sql = "SELECT id, actor, channel, action, target, before_sha, after_sha, reason, at FROM audit"
            args = []
            if cursor is not None:
                sql += " WHERE id < ?"
                args.append(cursor)
            sql += " ORDER BY id DESC LIMIT ?"
            items += [{"project": project.id, **dict(r)} for r in conn.execute(sql, [*args, limit + 1])]
    items.sort(key=lambda r: (r["at"] or "", r["id"]), reverse=True)
    more = len(items) > limit
    items = items[:limit]
    return {"items": items, "next": encode_cursor(items[-1]["id"]) if more and pid else None}


def installation():
    version = (ROOT / "VERSION").read_text().strip()
    install = str(ROOT)
    method = "pip" if "site-packages" in install else "source"
    return {"version": version, "install_path": install, "python": sys.version.split()[0], "method": method}
