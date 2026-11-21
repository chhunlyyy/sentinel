"""Local notifications (plan/v1.1/phaseH/features/notifications.feature).

Notifications are computed on read from the append-only `events` table of each registered workspace with the rule table
of docs/contracts/event-contracts.md section 4. Nothing is stored except the read state, which lives per OS user in
`~/.config/sentinel/user.db` (project, registry id, event id, event time, read time; no text). Nothing here touches the
network, an approval or the audit table.
"""
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

import scrub
from apiserver import userdir
from errors import SentinelError
from paths import slug_problem
from util import connect_ro

USER_DB = "user.db"
SCHEMA_VERSION = "1"
CANDIDATES = ("approval.requested", "approval.decided", "run.created", "run.state_changed", "task.finished",
              "evidence.recorded", "run.status_changed", "knowledge.failed")
ID = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*):(\d+)")
GATE_TITLE = {"specification": "Specification", "gherkin": "Gherkin"}
GATE_ARG = {"specification": "spec", "gherkin": "gherkin"}
CHANGES = ("changes", "changes_requested")
TEXT_MAX = 200


class UserDbError(Exception):
    """user.db cannot be written; `fix` names the file and what to do."""

    def __init__(self, message, fix):
        super().__init__(message)
        self.message, self.fix = message, fix


def user_db_path(environ=None):
    return userdir.config_dir(environ) / USER_DB


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---- the rule table
def _clip(text):
    text = " ".join(str(text).split())
    return text if len(text) <= TEXT_MAX else text[:TEXT_MAX - 3] + "..."


def rule(event_type, payload, slug):
    """(level, text, link, command) for an event of run `slug`, or None when no rule matches. The text is neither scrubbed nor
    clipped here; `_make` scrubs it first and clips it second, so a cut can never leave the start of a secret behind."""
    p = payload if isinstance(payload, dict) else {}
    base = f"/tasks/{slug}"
    nxt = f"sentinel next {slug}"
    if event_type == "approval.requested":
        gate = p.get("gate")
        if gate in GATE_TITLE:
            return "action", f"{GATE_TITLE[gate]} ready for review", f"{base}/{gate}", f"sentinel review {slug} {GATE_ARG[gate]}"
    elif event_type == "approval.decided":
        gate = p.get("gate")
        if p.get("decision") in CHANGES:
            return "info", "Changes requested", f"{base}/{gate}" if gate in GATE_TITLE else base, nxt
    elif event_type == "run.created":
        return "info", "Run started", base, nxt
    elif event_type == "run.state_changed":
        if p.get("to") == "NEEDS_HUMAN":
            return "action", p.get("reason") or "Run needs you", base, f"sentinel resolve {slug}"
        if p.get("to") == "BLOCKED":
            return "warning", p.get("reason") or "Run is blocked", base, nxt
    elif event_type == "task.finished":
        if p.get("state") == "FAILED":
            if p.get("error_code") == "E_PROVIDER":
                return "warning", f"Provider {p.get('provider') or 'unknown'} unavailable", f"{base}/workflow", nxt
            return "warning", f"{p.get('role') or 'task'} failed: {p.get('error_code') or 'error'}", f"{base}/workflow", nxt
    elif event_type == "evidence.recorded":
        if not p.get("cycle") and (p.get("verdict") == "fail" or p.get("passed") is False):
            return "warning", f"Verification failed: {p.get('kind') or 'check'}", f"{base}/verification", nxt
    elif event_type == "knowledge.failed":
        return "warning", "Knowledge harvest failed", base, "sentinel kb status"
    elif event_type == "run.status_changed":
        execution, acceptance = p.get("execution_status"), p.get("acceptance_status")
        if execution == "failed":
            return "warning", "Run failed", base, nxt
        if execution == "completed" and acceptance == "pending":
            return "action", "Run completed, waiting for acceptance", f"{base}/verification", f"sentinel accept {slug}"
        if execution == "completed" and acceptance == "accepted":
            return "info", "Run accepted", base, nxt
        if execution == "completed" and acceptance == "rejected":
            return "warning", "Run rejected", base, nxt
    return None


# ---- sources: one per registered workspace
class Source:
    def __init__(self, pid, db, scrub_text=None, unavailable=None):
        self.id, self.db, self.unavailable = pid, db, unavailable
        self._scrub = scrub_text

    def clean(self, text):
        return self._scrub(text) if self._scrub else text


def sources_from_registry(cfgdir, scrubber_for=None):
    """A Source for every project of projects.json. A workspace that cannot be read is marked unavailable with a reason."""
    try:
        data = userdir.load_projects(cfgdir)
    except userdir.ProjectsFileError:
        return []
    out = []
    for entry in data["projects"]:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        pid, path = entry["id"], Path(entry.get("path") or "")
        if not path.is_dir():
            out.append(Source(pid, None, unavailable="workspace missing"))
            continue
        try:
            config = yaml.safe_load((path / "sentinel.config.yaml").read_text(encoding="utf-8"))
            state = (config.get("state") or {}).get("dir", ".sentinel")
        except (OSError, yaml.YAMLError, AttributeError):
            out.append(Source(pid, None, unavailable="invalid configuration"))
            continue
        clean = (lambda text, entry=entry: scrub.clean_text(scrubber_for(entry), text)) if scrubber_for else _lazy_scrubber(path)
        out.append(Source(pid, path / state / "sentinel.db", clean))
    return out


def sources_from_projects(projects, scrubber_for):
    """A Source for every project of a server's ProjectSet, using its cached configuration and database path."""
    out = []
    for project in projects.list():
        if not project.path.is_dir():
            out.append(Source(project.id, None, unavailable="workspace missing"))
            continue
        config, reason = projects._load_config(project)
        if reason:
            out.append(Source(project.id, None, unavailable=reason))
            continue
        out.append(Source(project.id, projects.db_path(project, config),
                          lambda text, project=project: scrub.clean_text(scrubber_for(project), text)))
    return out


def _lazy_scrubber(path):
    holder = []

    def clean(text):
        if not holder:
            holder.append(scrub.Scrubber(path, scrub.env_values(path)))
        return scrub.clean_text(holder[0], text)
    return clean


# ---- reading the registries
EVENT_SQL = ("SELECT e.id, e.type, e.at, e.payload, r.slug FROM events e JOIN runs r ON r.id = e.run_id "
             "WHERE r.workflow_version = '2' AND e.type IN ({marks}){extra} ORDER BY e.id")


def _registry_id(conn):
    row = conn.execute("SELECT id, at, run_id FROM events ORDER BY id LIMIT 1").fetchone()
    return hashlib.sha1(f"{row[1]}|{row[2]}".encode()).hexdigest()[:12] if row else ""


def _open_registry(source):
    if not source.db.exists():
        return None
    conn = connect_ro(source.db, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _make(source, row):
    try:
        payload = json.loads(row["payload"]) if row["payload"] else {}
    except ValueError:
        payload = {}
    hit = rule(row["type"], payload, row["slug"])
    if hit is None:
        return None
    level, text, link, command = hit
    if slug_problem(str(row["slug"])) is not None:  # AC-SEC-09b: a link is always a dashboard route of a real run name
        link = command = None
    return {"id": f"{source.id}:{row['id']}", "project": source.id, "run": row["slug"], "level": level, "text": _clip(source.clean(text)),
            "link": link, "at": row["at"], "read_at": None, "command": command, "_event": row["id"]}


def _project_items(source, event_id=None):
    """(registry id, notifications of one workspace, oldest first); (None, []) when it has no registry yet."""
    conn = _open_registry(source)
    if conn is None:
        return None, []
    try:
        marks = ",".join("?" * len(CANDIDATES))
        extra = " AND e.id = ?" if event_id is not None else ""
        args = [*CANDIDATES, *([event_id] if event_id is not None else [])]
        items = [n for n in (_make(source, r) for r in conn.execute(EVENT_SQL.format(marks=marks, extra=extra), args)) if n]
        return _registry_id(conn), items
    finally:
        conn.close()


# ---- read state (user.db)
def _read_state(path):
    """{(project, registry id, event id, event time): read time}; empty when there is no readable user.db."""
    try:
        conn = connect_ro(path, timeout=5)
    except sqlite3.Error:
        return {}
    try:
        return {(r[0], r[1], r[2], r[3]): r[4] for r in conn.execute(
            "SELECT project, registry_id, event_id, event_at, read_at FROM notification_reads")}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def _writable(path):
    path = Path(path)
    if path.exists() and not os.access(path, os.W_OK):
        mode = f"{stat.S_IMODE(path.stat().st_mode):04o}"
        raise UserDbError(f"{path} is not writable (mode {mode})", f"make {path} writable by you: chmod 600 {path} (its mode is {mode}, expected 0600)")


LOCK_WAIT = 5.0


def _write_state(path, rows):
    """Add read rows (INSERT OR IGNORE: the first read time stays). Creates the 0700 folder and the 0600 file.

    Writers (the dashboard server and any number of terminals) take an exclusive lock on `user.db.lock` while they create
    the file, switch it to WAL, create the schema and insert, and retry a transaction that SQLite refuses with
    `OperationalError` (locked, disk I/O during a concurrent first creation) for up to LOCK_WAIT seconds."""
    path = Path(path)
    _writable(path)
    try:
        userdir.ensure_dir(path.parent)
        lock_fd = os.open(path.parent / (USER_DB + ".lock"), os.O_CREAT | os.O_WRONLY, 0o600)
    except OSError as e:
        raise UserDbError(f"{path} cannot be opened: {e}", f"check the folder and mode of {path} (expected 0700 and 0600)") from e
    deadline, delay, last = time.monotonic() + LOCK_WAIT, 0.02, None
    try:
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                time.sleep(delay)
                continue
            try:
                _write_once(path, rows)
                return
            except sqlite3.OperationalError as e:
                last = e
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            time.sleep(delay)
            delay = min(delay * 2, 0.5)
    finally:
        os.close(lock_fd)
    raise UserDbError(f"{path} cannot be written: {last or 'it stayed locked'}", f"make {path} writable by you: chmod 600 {path}")


def _write_once(path, rows):
    try:
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    except (OSError, sqlite3.Error) as e:
        raise UserDbError(f"{path} cannot be opened: {e}", f"check the folder and mode of {path} (expected 0700 and 0600)") from e
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS notification_reads (project TEXT NOT NULL, registry_id TEXT NOT NULL, "
                     "event_id INTEGER NOT NULL, event_at TEXT NOT NULL, read_at TEXT NOT NULL, "
                     "PRIMARY KEY (project, registry_id, event_id, event_at))")
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        stamp = now()
        conn.executemany("INSERT OR IGNORE INTO notification_reads(project, registry_id, event_id, event_at, read_at) VALUES (?,?,?,?,?)",
                         [(p, reg, eid, at, stamp) for p, reg, eid, at in rows])
        conn.execute("COMMIT")
    except sqlite3.Error as e:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        if isinstance(e, sqlite3.OperationalError):
            raise
        raise UserDbError(f"{path} cannot be written: {e}", f"make {path} writable by you: chmod 600 {path}") from e
    finally:
        conn.close()


# ---- the engine function
def public(n):
    """The fields of a notification that leave the engine function."""
    return {k: n[k] for k in ("id", "project", "run", "level", "text", "link", "at", "read_at")}


def collect(sources, user_db, project=None):
    """Every notification (newest first) with its read time, the unavailable projects and the read keys."""
    state = _read_state(user_db)
    items, unavailable, keys = [], [], {}
    for source in sources:
        if project and source.id != project:
            continue
        if source.unavailable:
            unavailable.append({"project": source.id, "reason": source.unavailable})
            continue
        try:
            registry, found = _project_items(source)
        except sqlite3.Error:
            unavailable.append({"project": source.id, "reason": "database unreadable"})
            continue
        for n in found:
            key = (source.id, registry, n["_event"], n["at"])
            n["read_at"] = state.get(key)
            keys[n["id"]] = key
            items.append(n)
    items.sort(key=lambda n: (n["at"], n["project"], n["_event"]), reverse=True)
    return items, unavailable, keys


def compute(sources, user_db, project=None, limit=50, cursor=None, unread_only=False):
    """{"items", "next", "unread", "unavailable"}. `cursor` is [at, project, event id] of the last item of the previous page."""
    items, unavailable, _ = collect(sources, user_db, project)
    unread = sum(1 for n in items if not n["read_at"])
    if unread_only:
        items = [n for n in items if not n["read_at"]]
    if cursor:
        at, pid, eid = cursor
        items = [n for n in items if (n["at"], n["project"], n["_event"]) < (at, pid, eid)]
    page = items[:limit]
    nxt = [page[-1]["at"], page[-1]["project"], page[-1]["_event"]] if len(items) > limit else None
    return {"items": [_with_command(n) for n in page], "next": nxt, "unread": unread, "unavailable": unavailable}


def _with_command(n):
    return {k: v for k, v in n.items() if k != "_event"}


def parse_id(nid):
    m = ID.fullmatch(nid or "")
    if not m:
        raise SentinelError("E_VALIDATION", f"notification id {nid!r} must look like <project>:<event number>", {"field": "id"})
    return m.group(1), int(m.group(2))


def mark_read(sources, user_db, nid):
    """Mark one notification read; returns it with its (first) read time."""
    pid, eid = parse_id(nid)
    source = next((s for s in sources if s.id == pid), None)
    if source is None:
        raise SentinelError("E_NOT_FOUND", f"no project {pid}", {"project": pid})
    if source.unavailable:
        raise SentinelError("E_NOT_FOUND", f"project {pid} is unavailable: {source.unavailable}", {"project": pid})
    try:
        registry, found = _project_items(source, eid)
    except sqlite3.Error:
        raise SentinelError("E_NOT_FOUND", f"project {pid} cannot be read", {"project": pid})
    if not found:
        raise SentinelError("E_NOT_FOUND", f"no notification {nid}", {"id": nid})
    n = found[0]
    _write_state(user_db, [(pid, registry, eid, n["at"])])
    n["read_at"] = _read_state(user_db).get((pid, registry, eid, n["at"]))
    return _with_command(n)


def mark_all(sources, user_db, project=None):
    """Mark every unread notification read; returns how many."""
    items, _, keys = collect(sources, user_db, project)
    rows = [keys[n["id"]] for n in items if not n["read_at"]]
    if rows:
        _write_state(user_db, rows)
    return len(rows)
