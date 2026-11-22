"""Local analytics from the workspace registry (plan/v1.1/phaseH/features/analytics.feature).

One function, `compute`, serves `sentinel stats` and GET /api/v1/reports/analytics. It opens the registry read-only, reads
one snapshot, counts version 2 runs created in a date range and never estimates a value: a metric that cannot be
computed is `{"value": null, "reason": "..."}`.

Definitions (README point 5):
- lead time: finished_at minus created_at of runs that finished as COMPLETED or FAILED (the feature counts the FAILED run);
  a CANCELLED run never ran to an end, so it is left out; median (statistics.median) and p90 (nearest rank).
- acceptance rate: accepted over decided, where decided means a COMPLETED run with acceptance accepted or rejected.
- approval wait: `decided_at` of a specification or Gherkin approval minus the time of the latest `approval.requested` event
  of the same run, gate and version that is not later than the decision. A decision without such an event (none, or only a
  later one: a wait is never negative) is not measured; a gate with decisions but no measurable wait says "no request event".
- verification rates: evidence of finished runs only (a run that is still going has no final verification).
- provider failure rate: E_PROVIDER failures over finished (COMPLETED or FAILED) tasks of the provider.
- cost: summed from task rows that report one; partial when some tasks report none; nothing comes from tokens.
"""
import json
import math
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path

from errors import SentinelError
from util import connect_ro

OLDEST_SCHEMA = 9
GATES = ("specification", "gherkin")
PHASES = ("red", "green", "refactor")
CHANGES = ("changes", "changes_requested")
RUN_FILTER = "r.workflow_version = '2' AND substr(r.created_at, 1, 10) >= ? AND substr(r.created_at, 1, 10) <= ?"


def null(reason):
    return {"value": None, "reason": reason}


def is_null(metric):
    return isinstance(metric, dict) and "reason" in metric and metric.get("value", 0) is None


def parse_day(text, name):
    """A YYYY-MM-DD date, or an E_VALIDATION naming the argument."""
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        raise SentinelError("E_VALIDATION", f"{name} must be a date written YYYY-MM-DD, not {text!r}", {"field": name})


def check_range(start, end):
    """Validated (from, to) day strings or None."""
    start = parse_day(start, "from") if start not in (None, "") else None
    end = parse_day(end, "to") if end not in (None, "") else None
    if start and end and start > end:
        raise SentinelError("E_VALIDATION", f"from ({start}) must not be after to ({end})", {"field": "from"})
    return start, end


def _when(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _seconds(start, end):
    a, b = _when(start), _when(end)
    if a is None or b is None:
        return None
    return (b - a).total_seconds()


def _p90(values):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def _num(x):
    return int(x) if float(x).is_integer() else round(float(x), 6)


def _stats(values):
    return {"count": len(values), "median": _num(statistics.median(values)), "p90": _num(_p90(values))}


def open_readonly(db):
    """A read-only connection; the registry is never created or changed."""
    db = Path(db)
    try:
        conn = connect_ro(db, timeout=10, isolation_level=None)
    except sqlite3.Error as e:
        raise SentinelError("E_INTEGRITY", f"cannot open the registry {db}: {e}", {"path": str(db)}, exit_code=1)
    conn.row_factory = sqlite3.Row
    return conn


def compute(db, start=None, end=None, providers=()):
    """The analytics answer for the registry file `db`. Raises E_INTEGRITY (exit 1) when it is not a usable registry."""
    start, end = check_range(start, end)
    db = Path(db)
    if not db.exists():
        return null("no registry")
    conn = open_readonly(db)
    try:
        try:
            conn.execute("BEGIN")
            row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            version = int(row[0]) if row else 0
            if version > _latest():
                raise SentinelError("E_MIGRATION", f"the registry {db} has schema {version}, newer than this Sentinel",
                                    {"path": str(db), "schema_version": version}, exit_code=1)
            if version < OLDEST_SCHEMA:
                return null("the registry needs a migration; run any sentinel command in the workspace")
            return _answer(conn, start or "0000-01-01", end or "9999-12-31", start, end, providers)
        except sqlite3.DatabaseError as e:
            raise SentinelError("E_INTEGRITY", f"the registry {db} cannot be read: {e}", {"path": str(db)}, exit_code=1)
        finally:
            try:
                conn.execute("COMMIT")
            except sqlite3.Error:
                pass
    finally:
        conn.close()


def runner_ids(config):
    """The configured runner ids (the providers a failure rate is reported for); [] when the runners section is unusable."""
    try:
        from run_stage import all_runners
        return sorted(all_runners(config))
    except Exception:
        return []


def _latest():
    from registry import Registry
    return Registry.LATEST


def _answer(conn, lo, hi, start, end, providers):
    args = (lo, hi)
    runs = [dict(r) for r in conn.execute(
        f"SELECT r.id, r.type, r.state, r.created_at, r.finished_at, r.acceptance_status FROM runs r WHERE {RUN_FILTER}", args)]
    out = {"range": {"from": start, "to": end}}
    by_state, by_type = {}, {}
    for r in runs:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
        by_type[r["type"] or "unknown"] = by_type.get(r["type"] or "unknown", 0) + 1
    out["runs"] = {"total": len(runs), "by_state": by_state, "by_type": by_type}
    if not runs:
        reason = "no runs in range"
        out.update({name: null(reason) for name in ("lead_time_seconds", "acceptance_rate", "approval_wait_seconds", "tasks", "retries", "tdd", "rework")})
        out["provider_failure_rate"] = {p: null(reason) for p in sorted(set(providers))}
        out["verification"] = {"pass_rate": null(reason), "first_attempt_pass_rate": null(reason)}
        out["cost"] = {"total": null(reason), "partial": False, "by_task": {}, "by_role": {}, "by_provider": {}}
        out["usage"] = {"total": null(reason), "by_model": {}, "by_week": {}, "by_role": {}}
        return out

    lead = [s for s in (_seconds(r["created_at"], r["finished_at"]) for r in runs if r["finished_at"] and r["state"] != "CANCELLED")
            if s is not None]
    out["lead_time_seconds"] = _stats(lead) if lead else null("no finished runs")
    decided = [r for r in runs if r["state"] == "COMPLETED" and r["acceptance_status"] in ("accepted", "rejected")]
    accepted = sum(1 for r in decided if r["acceptance_status"] == "accepted")
    out["acceptance_rate"] = ({"value": accepted / len(decided), "accepted": accepted, "decided": len(decided)}
                              if decided else null("no decided runs"))
    out["approval_wait_seconds"] = _approval_wait(conn, args)
    out["tasks"], out["retries"] = _tasks(conn, args)
    out["provider_failure_rate"] = _providers(conn, args, providers)
    out["cost"] = _cost(conn, args)
    out["usage"] = _usage(conn, args)
    out["tdd"] = _tdd(conn, args)
    out["verification"] = _verification(conn, args)
    out["rework"] = _rework(conn, args)
    return out


def _approval_wait(conn, args):
    requested = {}
    for e in conn.execute(
            f"SELECT e.id, e.run_id, e.at, e.payload FROM events e JOIN runs r ON r.id = e.run_id "
            f"WHERE e.type = 'approval.requested' AND {RUN_FILTER} ORDER BY e.id", args):
        p = _payload(e["payload"])
        when = _when(e["at"])
        if when is not None:
            requested.setdefault((e["run_id"], p.get("gate"), p.get("version")), []).append(when)
    waits = {g: [] for g in GATES}
    decided = {g: 0 for g in GATES}
    for a in conn.execute(
            f"SELECT a.run_id, a.gate, a.version, a.decided_at FROM approvals a JOIN runs r ON r.id = a.run_id "
            f"WHERE a.decided_at IS NOT NULL AND a.gate IN ('specification','gherkin') AND {RUN_FILTER}", args):
        decided[a["gate"]] += 1
        at = _when(a["decided_at"])
        before = [w for w in requested.get((a["run_id"], a["gate"], a["version"]), []) if at is not None and w <= at]
        if before:
            waits[a["gate"]].append((at - max(before)).total_seconds())
    if not any(decided.values()):
        return null("no decided approvals")
    return {g: _stats(waits[g]) if waits[g] else null("no request event" if decided[g] else "no decided approvals") for g in GATES}


def _payload(text):
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _tasks(conn, args):
    roles, retries = {}, 0
    seconds = {}
    for t in conn.execute(
            f"SELECT t.role, t.seconds, t.retry_of FROM tasks t JOIN runs r ON r.id = t.run_id WHERE {RUN_FILTER}", args):
        roles[t["role"]] = roles.get(t["role"], 0) + 1
        if t["seconds"] is not None:
            seconds.setdefault(t["role"], []).append(t["seconds"])
        if t["retry_of"]:
            retries += 1
    by_role = {role: {"count": n, "median_seconds": _num(statistics.median(seconds[role])) if seconds.get(role) else None}
               for role, n in roles.items()}
    return {"by_role": by_role}, {"total": retries}


def _providers(conn, args, known):
    counts = {}
    for t in conn.execute(
            f"SELECT t.provider, t.state, t.error_code FROM tasks t JOIN runs r ON r.id = t.run_id "
            f"WHERE t.provider IS NOT NULL AND {RUN_FILTER}", args):
        c = counts.setdefault(t["provider"], [0, 0])
        if t["state"] in ("COMPLETED", "FAILED"):
            c[1] += 1
            if t["state"] == "FAILED" and t["error_code"] == "E_PROVIDER":
                c[0] += 1
    out = {}
    for p in sorted(set(counts) | set(known)):
        failures, finished = counts.get(p, [0, 0])
        out[p] = ({"value": failures / finished, "failures": failures, "tasks": finished} if finished
                  else null("no tasks for this provider"))
    return out


def _cost(conn, args):
    by_task, by_role, by_provider = {}, {}, {}
    reported = unreported = 0
    total = 0.0
    for t in conn.execute(
            f"SELECT t.id, t.role, t.provider, t.cost FROM tasks t JOIN runs r ON r.id = t.run_id WHERE {RUN_FILTER} ORDER BY t.id", args):
        if t["cost"] is None:
            unreported += 1
            continue
        reported += 1
        total += t["cost"]
        by_task[t["id"]] = t["cost"]
        by_role[t["role"]] = by_role.get(t["role"], 0) + t["cost"]
        if t["provider"]:
            by_provider[t["provider"]] = by_provider.get(t["provider"], 0) + t["cost"]
    partial = bool(reported and unreported)
    return {"total": ({"value": total, "partial": partial, "reported_tasks": reported, "unreported_tasks": unreported}
                      if reported else null("not reported")),
            "partial": partial, "by_task": by_task, "by_role": by_role, "by_provider": by_provider}


def _iso_week(ts):
    if not ts:
        return "unknown"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        year, week, _ = dt.isocalendar()
        return f"{year}-W{week:02d}"
    except Exception:
        return ts[:7]


def _usage(conn, args):
    by_model, by_week, by_role = {}, {}, {}
    reported = unreported = 0
    total_tokens = total_input = total_output = 0
    total_cost = 0.0
    total_seconds = 0.0

    cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    in_out = "t.input_tokens, t.output_tokens," if "input_tokens" in cols else "NULL as input_tokens, NULL as output_tokens,"
    model_col = "t.model," if "model" in cols else "NULL as model,"

    query = (
        f"SELECT t.id, t.role, t.provider, {model_col} t.tokens, {in_out} t.cost, t.seconds, "
        f"COALESCE(t.created_at, r.created_at) as created_at "
        f"FROM tasks t JOIN runs r ON r.id = t.run_id WHERE {RUN_FILTER} ORDER BY t.id"
    )
    for t in conn.execute(query, args):
        tokens = t["tokens"]
        inp = t["input_tokens"]
        outp = t["output_tokens"]
        cost = t["cost"]
        secs = t["seconds"]
        model = t["model"] or "unspecified"
        week = _iso_week(t["created_at"])
        role = t["role"] or "unknown"

        has_data = any(x is not None for x in (tokens, inp, outp, cost))
        if not has_data:
            unreported += 1
            continue
        reported += 1

        if tokens is not None:
            total_tokens += tokens
        if inp is not None:
            total_input += inp
        if outp is not None:
            total_output += outp
        if cost is not None:
            total_cost += cost
        if secs is not None:
            total_seconds += secs

        m = by_model.setdefault(model, {"tokens": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "seconds": 0.0, "tasks": 0})
        m["tasks"] += 1
        if tokens: m["tokens"] += tokens
        if inp: m["input_tokens"] += inp
        if outp: m["output_tokens"] += outp
        if cost: m["cost"] = round(m["cost"] + cost, 4)
        if secs: m["seconds"] = round(m["seconds"] + secs, 2)

        w = by_week.setdefault(week, {"tokens": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "seconds": 0.0, "tasks": 0})
        w["tasks"] += 1
        if tokens: w["tokens"] += tokens
        if inp: w["input_tokens"] += inp
        if outp: w["output_tokens"] += outp
        if cost: w["cost"] = round(w["cost"] + cost, 4)
        if secs: w["seconds"] = round(w["seconds"] + secs, 2)

        r = by_role.setdefault(role, {"tokens": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "seconds": 0.0, "tasks": 0})
        r["tasks"] += 1
        if tokens: r["tokens"] += tokens
        if inp: r["input_tokens"] += inp
        if outp: r["output_tokens"] += outp
        if cost: r["cost"] = round(r["cost"] + cost, 4)
        if secs: r["seconds"] = round(r["seconds"] + secs, 2)

    total_cost = round(total_cost, 4)
    total_seconds = round(total_seconds, 2)
    tot = {
        "tokens": total_tokens if reported else None,
        "input_tokens": total_input if reported else None,
        "output_tokens": total_output if reported else None,
        "cost": total_cost if reported else None,
        "seconds": total_seconds if reported else None,
        "reported_tasks": reported,
        "unreported_tasks": unreported,
    } if reported else null("no usage reported")

    return {
        "total": tot,
        "by_model": by_model,
        "by_week": by_week,
        "by_role": by_role,
    }


def compute_usage(sources, project=None, since=None, end=None):
    """Compute usage across sources (list of (pid, db_path)) or a single (pid, db_path).
    Returns {"range": ..., "totals": ..., "by_project": ..., "by_model": ..., "by_week": ...}."""
    start = parse_day(since, "since") if since else None
    end = parse_day(end, "to") if end else None
    if start and end and start > end:
        raise SentinelError("E_VALIDATION", f"since ({start}) must not be after to ({end})", {"field": "since"})
    if isinstance(sources, tuple):
        sources = [sources]
    by_project, by_model, by_week = {}, {}, {}
    total_tokens = total_input = total_output = 0
    total_cost = 0.0
    total_seconds = 0.0
    total_reported = total_unreported = 0

    for pid, db in sources:
        if project and pid != project:
            continue
        db_path = Path(db)
        if not db_path.exists():
            continue
        try:
            conn = open_readonly(db_path)
            try:
                args = (start or "0000-01-01", end or "9999-12-31")
                u = _usage(conn, args)
                tot = u["total"]
                if not is_null(tot):
                    total_reported += tot.get("reported_tasks") or 0
                    total_unreported += tot.get("unreported_tasks") or 0
                    if tot.get("tokens"): total_tokens += tot["tokens"]
                    if tot.get("input_tokens"): total_input += tot["input_tokens"]
                    if tot.get("output_tokens"): total_output += tot["output_tokens"]
                    if tot.get("cost"): total_cost += tot["cost"]
                    if tot.get("seconds"): total_seconds += tot["seconds"]

                    proj_m = by_project.setdefault(pid, {"tokens": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "seconds": 0.0, "tasks": 0})
                    proj_m["tasks"] += tot.get("reported_tasks") or 0
                    if tot.get("tokens"): proj_m["tokens"] += tot["tokens"]
                    if tot.get("input_tokens"): proj_m["input_tokens"] += tot["input_tokens"]
                    if tot.get("output_tokens"): proj_m["output_tokens"] += tot["output_tokens"]
                    if tot.get("cost"): proj_m["cost"] = round(proj_m["cost"] + tot["cost"], 4)
                    if tot.get("seconds"): proj_m["seconds"] = round(proj_m["seconds"] + tot["seconds"], 2)

                for m_k, m_v in u["by_model"].items():
                    m = by_model.setdefault(m_k, {"tokens": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "seconds": 0.0, "tasks": 0})
                    m["tasks"] += m_v["tasks"]
                    m["tokens"] += m_v["tokens"]
                    m["input_tokens"] += m_v["input_tokens"]
                    m["output_tokens"] += m_v["output_tokens"]
                    m["cost"] = round(m["cost"] + m_v["cost"], 4)
                    m["seconds"] = round(m["seconds"] + m_v["seconds"], 2)

                for w_k, w_v in u["by_week"].items():
                    w = by_week.setdefault(w_k, {"tokens": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "seconds": 0.0, "tasks": 0})
                    w["tasks"] += w_v["tasks"]
                    w["tokens"] += w_v["tokens"]
                    w["input_tokens"] += w_v["input_tokens"]
                    w["output_tokens"] += w_v["output_tokens"]
                    w["cost"] = round(w["cost"] + w_v["cost"], 4)
                    w["seconds"] = round(w["seconds"] + w_v["seconds"], 2)
            finally:
                conn.close()
        except Exception:
            continue

    total_cost = round(total_cost, 4)
    total_seconds = round(total_seconds, 2)
    totals = {
        "tokens": total_tokens if total_reported else None,
        "input_tokens": total_input if total_reported else None,
        "output_tokens": total_output if total_reported else None,
        "cost": total_cost if total_reported else None,
        "seconds": total_seconds if total_reported else None,
        "reported_tasks": total_reported,
        "unreported_tasks": total_unreported,
    } if total_reported else null("no usage reported")

    return {
        "range": {"since": since, "to": end},
        "totals": totals,
        "by_project": by_project,
        "by_model": by_model,
        "by_week": by_week,
    }


def markdown_usage(usage):
    lines = ["# Usage Report", ""]
    tot = usage.get("totals") or usage.get("total") or {}
    if is_null(tot):
        return f"No usage reported: {tot.get('reason', 'none')}.\n"
    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Total tokens | {tot.get('tokens', 0) or 0:,} |")
    if tot.get("input_tokens") is not None:
        lines.append(f"| Input tokens | {tot.get('input_tokens', 0) or 0:,} |")
    if tot.get("output_tokens") is not None:
        lines.append(f"| Output tokens | {tot.get('output_tokens', 0) or 0:,} |")
    lines.append(f"| Cost | ${tot.get('cost', 0.0) or 0.0:.2f} |")
    lines.append(f"| Tasks | {tot.get('reported_tasks', 0)} reported, {tot.get('unreported_tasks', 0)} unreported |")
    lines.append("")

    if usage.get("by_project"):
        lines.append("## Usage by Project")
        lines.append("")
        lines.append("| Project | Tokens | Cost | Tasks |")
        lines.append("|---|---|---|---|")
        for p, d in sorted(usage["by_project"].items()):
            lines.append(f"| {p} | {d.get('tokens', 0) or 0:,} | ${d.get('cost', 0.0) or 0.0:.2f} | {d.get('tasks', 0)} |")
        lines.append("")

    if usage.get("by_model"):
        lines.append("## Usage by Model")
        lines.append("")
        lines.append("| Model | Tokens | Input | Output | Cost | Tasks |")
        lines.append("|---|---|---|---|---|---|")
        for m, d in sorted(usage["by_model"].items()):
            lines.append(f"| {m} | {d.get('tokens', 0) or 0:,} | {d.get('input_tokens', 0) or 0:,} | {d.get('output_tokens', 0) or 0:,} | ${d.get('cost', 0.0) or 0.0:.2f} | {d.get('tasks', 0)} |")
        lines.append("")

    if usage.get("by_week"):
        lines.append("## Usage by Week")
        lines.append("")
        lines.append("| Week | Tokens | Cost | Tasks |")
        lines.append("|---|---|---|---|")
        for w, d in sorted(usage["by_week"].items()):
            lines.append(f"| {w} | {d.get('tokens', 0) or 0:,} | ${d.get('cost', 0.0) or 0.0:.2f} | {d.get('tasks', 0)} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def _tdd(conn, args):
    row = conn.execute(
        f"SELECT COUNT(*) AS total, SUM(c.state = 'CYCLE_ACCEPTED') AS accepted FROM cycles c JOIN runs r ON r.id = c.run_id "
        f"WHERE {RUN_FILTER}", args).fetchone()
    rejected = {p: 0 for p in PHASES}
    for e in conn.execute(
            f"SELECT e.type, COUNT(*) AS n FROM events e JOIN runs r ON r.id = e.run_id "
            f"WHERE e.type IN ('red.rejected','green.rejected','refactor.rejected') AND {RUN_FILTER} GROUP BY e.type", args):
        rejected[e["type"].split(".")[0]] = e["n"]
    return {"cycles": {"total": row["total"] or 0, "accepted": row["accepted"] or 0, "rejected": rejected}}


def _verification(conn, args):
    rows = conn.execute(
        f"SELECT v.run_id, v.kind, v.round, v.verdict FROM evidence v JOIN runs r ON r.id = v.run_id "
        f"WHERE v.round IS NOT NULL AND v.verdict IN ('pass','fail') AND r.finished_at IS NOT NULL AND {RUN_FILTER}", args).fetchall()
    if not rows:
        reason = "no verification evidence"
        return {"pass_rate": null(reason), "first_attempt_pass_rate": null(reason)}
    kinds = {}
    for r in rows:
        k = kinds.setdefault(r["kind"], [0, 0])
        k[1] += 1
        k[0] += r["verdict"] == "pass"
    first = {}
    for r in rows:
        low = first.get(r["run_id"])
        if low is None or r["round"] < low[0]:
            first[r["run_id"]] = [r["round"], r["verdict"] == "pass"]
        elif r["round"] == low[0]:
            low[1] = low[1] and r["verdict"] == "pass"
    clean = sum(1 for v in first.values() if v[1])
    return {"pass_rate": {k: {"value": p / n, "passed": p, "total": n} for k, (p, n) in sorted(kinds.items())},
            "first_attempt_pass_rate": {"value": clean / len(first), "passed_first": clean, "verified": len(first)}}


def _rework(conn, args):
    def revised(kind):
        return conn.execute(
            f"SELECT COUNT(*) FROM (SELECT a.run_id FROM artifacts a JOIN runs r ON r.id = a.run_id WHERE a.kind = ? AND {RUN_FILTER} "
            f"GROUP BY a.run_id HAVING COUNT(*) > 1)", (kind, *args)).fetchone()[0]

    def events(kind):
        n = 0
        for e in conn.execute(f"SELECT e.payload FROM events e JOIN runs r ON r.id = e.run_id WHERE e.type = ? AND {RUN_FILTER}", (kind, *args)):
            n += 1 if kind != "approval.decided" or _payload(e["payload"]).get("decision") in CHANGES else 0
        return n
    return {"spec_revisions": revised("spec"), "gherkin_revisions": revised("gherkin"),
            "changes_requested": events("approval.decided"), "findings_routed": events("finding.routed")}


# ---- text output
def flatten(answer, prefix=""):
    """(metric name, text) rows of an answer, in key order."""
    rows = []
    if isinstance(answer, dict):
        if is_null(answer):
            return [(prefix, f"not reported ({answer['reason']})")]
        for key, value in answer.items():
            rows += flatten(value, f"{prefix}.{key}" if prefix else key)
        if not answer and prefix:
            rows.append((prefix, "none"))
    elif answer is None:
        rows.append((prefix, "not reported"))
    else:
        rows.append((prefix, str(answer)))
    return rows


def markdown(answer):
    if is_null(answer):
        return f"No analytics: {answer['reason']}.\n"
    lines = ["| Metric | Value |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in flatten(answer)]
    return "\n".join(lines) + "\n"
