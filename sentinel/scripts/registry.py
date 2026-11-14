"""Workspace registry: SQLite store for runs, tasks, approvals, events and config history."""

import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from errors import SentinelError

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_ID_PREFIX = {"runs": "r-", "tasks": "t-", "approvals": "a-", "cycles": "c-",
              "evidence": "e-", "artifacts": "ar-", "findings": "f-"}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def legacy_statuses(outcome):
    """(execution_status, acceptance_status) of a 0.1 run from its recorded outcome."""
    if outcome in ("passed", "finished"):
        return "completed", "accepted"
    if outcome:
        return "cancelled", "rejected"
    return "running", "pending"


def _new_id(table):
    return _ID_PREFIX[table] + uuid.uuid4().hex[:12]


def _split_statements(sql):
    """Split SQL into complete statements (trigger bodies keep their inner semicolons)."""
    out, buf = [], ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def _load_file_migrations():
    found = []
    for p in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        m = re.match(r"(\d{4})_(.+)\.sql$", p.name)
        found.append((int(m.group(1)), m.group(2), p.read_text(encoding="utf-8")))
    return found


class Registry:
    LATEST = max(v for v, _, _ in _load_file_migrations())

    def __init__(self, conn, state_dir):
        self._c = conn
        self._dir = Path(state_dir)
        self._in_tx = False
        self._cols = {}

    # ---- lifecycle
    @classmethod
    def open(cls, state_dir, migrations=None):
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        migs = sorted(migrations if migrations is not None else _load_file_migrations())
        db = state_dir / "sentinel.db"
        conn = sqlite3.connect(db, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        reg = cls(conn, state_dir)
        try:
            reg._enable_wal()
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA recursive_triggers=ON")
            reg._migrate(migs)
        except SentinelError:
            conn.close()
            raise
        except Exception as e:
            conn.close()
            raise SentinelError("E_MIGRATION", f"cannot open registry: {e}") from e
        reg._index_legacy()
        return reg

    def close(self):
        try:
            self._c.close()
        except sqlite3.Error:
            pass

    def _enable_wal(self):
        if self.journal_mode().lower() == "wal":
            return
        self._c.execute("PRAGMA busy_timeout=1000")
        last = None
        for attempt in range(3):
            try:
                self._c.execute("PRAGMA journal_mode=WAL").fetchone()
                self._c.execute("PRAGMA busy_timeout=10000")
                return
            except sqlite3.OperationalError as e:
                last = e
                time.sleep(0.05 * (attempt + 1))
        raise SentinelError("E_MIGRATION", f"cannot switch registry to WAL: {last}")

    def _migrate(self, migs):
        if not [m for m in migs if m[0] > self.schema_version()]:
            return
        self._c.execute("BEGIN IMMEDIATE")
        version, name = 0, ""
        try:
            current = self.schema_version()  # re-read under the lock: another process may have migrated
            pending = [m for m in migs if m[0] > current]
            if not pending:
                self._c.execute("COMMIT")
                return
            if current >= 1:
                # second connection: backing up from the locked one would wait on its own lock
                bak = sqlite3.connect(self._dir / f"sentinel.db.bak-{current}")
                src = sqlite3.connect(self._dir / "sentinel.db")
                try:
                    src.backup(bak)
                finally:
                    src.close()
                    bak.close()
            for version, name, sql in pending:
                for stmt in _split_statements(sql):
                    self._c.execute(stmt)
                self._c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                                (str(version),))
            self._c.execute("COMMIT")
        except Exception as e:
            try:
                self._c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise SentinelError("E_MIGRATION", f"migration {version} ({name}) failed: {e}",
                                {"version": version, "name": name}) from e

    def schema_version(self):
        has = self._c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
        if not has:
            return 0
        row = self._c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row[0]) if row else 0

    def journal_mode(self):
        return self._c.execute("PRAGMA journal_mode").fetchone()[0]

    def _index_legacy(self):
        runs_dir = self._dir / "runs"
        if not runs_dir.is_dir():
            return
        with self.transaction():  # the write lock makes check-then-insert atomic across processes
            for f in sorted(runs_dir.glob("*/state.json")):
                try:
                    data = json.loads(f.read_bytes())
                except (OSError, ValueError):
                    continue
                if not isinstance(data, dict) or "schema_version" in data:
                    continue
                slug = data.get("slug") or f.parent.name
                if self.get_run(slug):
                    continue
                execution, acceptance = legacy_statuses(data.get("outcome"))
                self.insert_run({
                    "slug": slug, "request": data.get("request"), "tier": data.get("tier"),
                    "initial_tier": data.get("initial_tier", data.get("tier")),
                    "state": "LEGACY", "workflow_version": "0.1",
                    "execution_status": execution, "acceptance_status": acceptance,
                    "created_at": data.get("started") or _now(),
                })

    # ---- transactions
    @contextmanager
    def transaction(self):
        if self._in_tx:
            raise RuntimeError("nested registry transaction")
        self._c.execute("BEGIN IMMEDIATE")
        self._in_tx = True
        try:
            yield
        except BaseException:
            self._c.execute("ROLLBACK")
            raise
        else:
            self._c.execute("COMMIT")
        finally:
            self._in_tx = False

    # ---- helpers
    def _columns(self, table):
        if table not in self._cols:
            rows = self._c.execute(f'PRAGMA table_info("{table}")').fetchall() if re.fullmatch(r"\w+", table) else []
            self._cols[table] = {r["name"] for r in rows}
        return self._cols[table]

    def _check_table(self, table):
        if table not in _ID_PREFIX:
            raise ValueError(f"table not allowed: {table!r}")

    def _check_fields(self, table, fields):
        bad = set(fields) - self._columns(table)
        if bad:
            raise ValueError(f"unknown column(s) for {table}: {sorted(bad)}")

    def _insert(self, table, row):
        self._check_fields(table, row)
        keys = list(row)
        sql = (f'INSERT INTO "{table}" ({",".join(chr(34) + k + chr(34) for k in keys)}) '
               f'VALUES ({",".join("?" * len(keys))})')
        return self._c.execute(sql, [row[k] for k in keys])

    def _update(self, table, key_col, key, fields):
        if not fields:
            return
        self._check_fields(table, fields)
        sets = ",".join(f'"{k}"=?' for k in fields)
        self._c.execute(f'UPDATE "{table}" SET {sets} WHERE "{key_col}"=?', [*fields.values(), key])

    def _one(self, sql, args=()):
        r = self._c.execute(sql, args).fetchone()
        return dict(r) if r else None

    # ---- runs
    def insert_run(self, row):
        row = dict(row)
        row.setdefault("id", _new_id("runs"))
        now = _now()
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        self._insert("runs", row)

    def get_run(self, slug):
        return self._one("SELECT * FROM runs WHERE slug=?", (slug,))

    def get_run_by_id(self, run_id):
        return self._one("SELECT * FROM runs WHERE id=?", (run_id,))

    def list_runs(self):
        return [dict(r) for r in self._c.execute("SELECT * FROM runs ORDER BY created_at, slug")]

    def update_run(self, slug, **fields):
        fields["updated_at"] = _now()
        self._update("runs", "slug", slug, fields)

    def add_run_repo(self, run_id, repo_id, baseline_sha, branch=None):
        self._insert("run_repos", {"run_id": run_id, "repo_id": repo_id,
                                   "baseline_sha": baseline_sha, "branch": branch})

    def run_repos(self, run_id):
        return [dict(r) for r in self._c.execute(
            "SELECT * FROM run_repos WHERE run_id=? ORDER BY repo_id", (run_id,))]

    def store_config_version(self, scope, content, author=None, channel=None, comment=None):
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        last = self._one("SELECT id, sha256 FROM config_versions WHERE scope=? ORDER BY id DESC LIMIT 1",
                         (scope,))
        if last and last["sha256"] == sha:
            return last["id"]
        cur = self._insert("config_versions", {"scope": scope, "content": content, "sha256": sha,
                                               "author": author, "channel": channel,
                                               "created_at": _now(), "comment": comment})
        return cur.lastrowid

    def get_config_version(self, id):
        return self._one("SELECT * FROM config_versions WHERE id=?", (id,))

    # ---- events / audit
    def add_event(self, run_id, type, actor, payload=None, task_id=None):
        cur = self._c.execute(
            "INSERT INTO events(run_id, task_id, type, actor, payload, at) VALUES (?,?,?,?,?,?)",
            (run_id, task_id, type, actor, json.dumps(payload) if payload is not None else None, _now()))
        return cur.lastrowid

    def list_events(self, run_id=None, type=None):
        where, args = [], []
        if run_id is not None:
            where.append("run_id=?")
            args.append(run_id)
        if type is not None:
            where.append("type=?")
            args.append(type)
        sql = "SELECT * FROM events" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id"
        out = []
        for r in self._c.execute(sql, args):
            d = dict(r)
            d["payload"] = json.loads(d["payload"]) if d["payload"] is not None else None
            out.append(d)
        return out

    def add_audit(self, actor, channel, action, target, before_sha=None, after_sha=None, reason=None):
        cur = self._c.execute(
            "INSERT INTO audit(actor, channel, action, target, before_sha, after_sha, at, reason) VALUES (?,?,?,?,?,?,?,?)",
            (actor, channel, action, target, before_sha, after_sha, _now(), reason))
        return cur.lastrowid

    def audit_rows(self):
        return [dict(r) for r in self._c.execute("SELECT * FROM audit ORDER BY id")]

    def has_passing_evidence(self, run_id, kind="test"):
        return self._c.execute("SELECT 1 FROM evidence WHERE run_id=? AND kind=? AND passed > 0 LIMIT 1",
                               (run_id, kind)).fetchone() is not None

    # ---- generic rows
    def insert_row(self, table, row):
        self._check_table(table)
        row = dict(row)
        row.setdefault("id", _new_id(table))
        self._insert(table, row)
        return row["id"]

    def get_row(self, table, id):
        self._check_table(table)
        return self._one(f'SELECT * FROM "{table}" WHERE id=?', (id,))

    def rows(self, table, **where):
        """Rows of an id table (or trace_links) matching every column in `where`, in insertion order."""
        if table not in _ID_PREFIX and table != "trace_links":
            raise ValueError(f"table not allowed: {table!r}")
        self._check_fields(table, where)
        clause = " AND ".join(f'"{k}"=?' for k in where)
        sql = f'SELECT * FROM "{table}"' + (f" WHERE {clause}" if clause else "") + " ORDER BY rowid"
        return [dict(r) for r in self._c.execute(sql, list(where.values()))]

    def add_task_dep(self, task_id, depends_on):
        self._c.execute("INSERT INTO task_deps(task_id, depends_on) VALUES (?,?)", (task_id, depends_on))

    def task_deps(self, task_id):
        return [r[0] for r in self._c.execute(
            "SELECT depends_on FROM task_deps WHERE task_id=? ORDER BY rowid", (task_id,))]

    def add_trace_link(self, run_id, from_kind, from_id, to_kind, to_id):
        self._c.execute("INSERT INTO trace_links(run_id, from_kind, from_id, to_kind, to_id) VALUES (?,?,?,?,?)",
                        (run_id, from_kind, from_id, to_kind, to_id))

    def replace_trace_links(self, run_id, links, **match):
        """Delete the run's links matching `match` (column=value) and insert `links` (4-tuples)."""
        self._check_fields("trace_links", match)
        clause = "".join(f' AND "{k}"=?' for k in match)
        self._c.execute(f"DELETE FROM trace_links WHERE run_id=?{clause}", [run_id, *match.values()])
        for link in links:
            self.add_trace_link(run_id, *link)

    def update_row(self, table, id, **fields):
        self._check_table(table)
        if table == "runs":
            raise ValueError("use update_run for runs")
        self._update(table, "id", id, fields)
