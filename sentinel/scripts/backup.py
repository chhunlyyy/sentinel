"""Registry backup, verify and restore (OPS-05, PER-05).

A backup is the workspace registry (.sentinel/sentinel.db) copied with the sqlite3 backup API. user.db, config files
and run folders are not included. Old backups are never pruned. A `.sha256` file next to each copy lets verify catch
a changed byte that SQLite itself would not notice.
"""
import hashlib
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import auditlog
from errors import SentinelError
from registry import Registry

COUNT_TABLES = ("runs", "tasks", "events", "audit")
MAGIC = b"SQLite format 3\x00"


def _fail(code, message, details=None, exit_code=1):
    return SentinelError(code, message, details, exit_code=exit_code)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_db(src, dst):
    """Copy one SQLite file to another with the backup API (readers and writers of the source are not blocked)."""
    s = sqlite3.connect(f"file:{Path(src).resolve()}?mode=ro", uri=True, timeout=10)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _counts(conn):
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in COUNT_TABLES}


def _meta(conn, key):
    try:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def create_backup(state_dir, out_dir=None, user=None, prefix="sentinel", audit=True):
    """Copy the registry, check the copy, and return {path, sha256, size, schema_version, counts}."""
    state_dir = Path(state_dir)
    src = state_dir / "sentinel.db"
    if not src.is_file():
        raise _fail("E_NOT_FOUND", f"nothing to back up: no registry at {src}")
    out = Path(out_dir) if out_dir else state_dir / "backups"
    try:
        created = not out.exists()
        out.mkdir(parents=True, exist_ok=True)
        if created:
            os.chmod(out, 0o700)
    except OSError as e:
        raise _fail("E_VALIDATION", f"cannot create {out}: {e}")
    base = f"{prefix}-{_stamp()}Z"
    final, n = out / f"{base}.db", 1
    while final.exists():
        n += 1
        final = out / f"{base}-{n}.db"
    tmp = out / f".{final.name}.tmp"
    side = Path(str(final) + ".sha256")
    try:
        _copy_db(src, tmp)
        c = sqlite3.connect(tmp)
        try:
            c.execute("PRAGMA journal_mode=DELETE").fetchone()
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise _fail("E_INTEGRITY", "the copy failed PRAGMA integrity_check")
            counts, version = _counts(c), int(_meta(c, "schema_version") or 0)
        finally:
            c.close()
        os.chmod(tmp, 0o600)
        chain = auditlog.verify_db(tmp) if version >= 10 else {"ok": True}
        if not chain["ok"]:
            raise _fail("E_INTEGRITY", f"the copy failed its audit check: {chain['message']}")
        digest = sha256_file(tmp)
        size = tmp.stat().st_size
        side.write_text(f"{digest}  {final.name}\n")
        os.chmod(side, 0o600)
        os.replace(tmp, final)
    except (sqlite3.Error, OSError) as e:
        for p in (tmp, side):
            p.unlink(missing_ok=True)
        raise _fail("E_VALIDATION", f"backup failed, nothing was written: {e}")
    except BaseException:
        for p in (tmp, side):
            p.unlink(missing_ok=True)
        raise
    if audit:
        reg = Registry.open(state_dir)
        try:
            with reg.transaction():
                reg.add_audit(user or "unknown", "cli", "backup", str(final), after_sha=digest)
        finally:
            reg.close()
    return {"path": str(final), "sha256": digest, "size": size, "schema_version": version, "counts": counts}


def verify_backup(path):
    """Check a copy and return its info, or raise E_INTEGRITY (exit 1) naming the problem."""
    path = Path(path)
    if not path.is_file():
        raise _fail("E_NOT_FOUND", f"not a backup: {path} is not a file")
    with open(path, "rb") as f:
        if f.read(16) != MAGIC:
            raise _fail("E_INTEGRITY", f"not a backup: {path} is not a SQLite file")
    digest = sha256_file(path)
    side = Path(str(path) + ".sha256")
    if side.is_file():
        want = side.read_text().split()[0] if side.read_text().split() else ""
        if want != digest:
            raise _fail("E_INTEGRITY", f"{path.name} does not match its recorded sha256 (the file was changed)")
    try:
        c = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=10)
        try:
            result = c.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise _fail("E_INTEGRITY", f"{path.name} failed PRAGMA integrity_check: {result}")
            version = int(_meta(c, "schema_version") or 0)
            counts = _counts(c)
            registry_id = _meta(c, "registry_id")
        finally:
            c.close()
    except sqlite3.Error as e:
        raise _fail("E_INTEGRITY", f"{path.name} is damaged or truncated: {e}")
    if version > Registry.LATEST:
        raise _fail("E_INTEGRITY", f"{path.name} has schema_version {version}, newer than this Sentinel ({Registry.LATEST})")
    if version >= 10:
        chain = auditlog.verify_db(path)
        if not chain["ok"]:
            raise _fail("E_INTEGRITY", f"{path.name} has a broken audit chain: {chain['message']}")
    return {"path": str(path), "sha256": digest, "size": path.stat().st_size, "schema_version": version,
            "counts": counts, "registry_id": registry_id}


def running_conflicts(state_dir, config_dir):
    """What forbids a restore now: [(code detail text, details dict)]. A RUNNING task with a live process, or a
    Sentinel server holding the user's server lock."""
    found = []
    db = Path(state_dir) / "sentinel.db"
    if db.is_file():
        c = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True, timeout=10)
        try:
            for tid, pid in c.execute("SELECT id, pid FROM tasks WHERE state IN ('RUNNING', 'WAITING_FOR_INPUT') AND pid IS NOT NULL"):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                except PermissionError:
                    pass
                found.append((f"task {tid} is running (pid {pid})", {"task": tid, "pid": pid}))
        except sqlite3.Error:
            pass
        finally:
            c.close()
    from apiserver import userdir
    if (Path(config_dir) / userdir.LOCK).exists():
        lock = userdir.ServerLock(config_dir)
        if lock.acquire():
            lock.release()
        else:
            info = userdir.read_server_json(config_dir) or {}
            found.append((f"a Sentinel server is running (pid {info.get('pid', '?')}, port {info.get('port', '?')})",
                          {"server_pid": info.get("pid"), "port": info.get("port")}))
    return found


def restore(state_dir, backup_path, user=None):
    """Put a checked copy in place. The current registry is first copied to pre-restore-<time>.db and stays
    untouched when anything fails before the final rename."""
    state_dir = Path(state_dir)
    info = verify_backup(backup_path)
    live = state_dir / "sentinel.db"
    mine = None
    if live.is_file():
        c = sqlite3.connect(f"file:{live.resolve()}?mode=ro", uri=True, timeout=10)
        try:
            mine = _meta(c, "registry_id")
        finally:
            c.close()
    theirs = info["registry_id"]
    if mine and theirs and mine != theirs:
        raise _fail("E_VALIDATION", f"{Path(backup_path).name} belongs to another workspace "
                    f"(backup registry id {theirs}, this workspace {mine})", {"backup": theirs, "workspace": mine})
    if live.is_file():
        create_backup(state_dir, state_dir / "backups", user=user, prefix="pre-restore", audit=False)
    tmpdir = Path(tempfile.mkdtemp(dir=state_dir, prefix=".restore-"))
    try:
        tmpdb = tmpdir / "sentinel.db"
        _copy_db(backup_path, tmpdb)
        reg = Registry.open(tmpdir)  # migrates the copy to the current schema
        try:
            if mine:
                with reg.transaction():
                    reg._c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('registry_id', ?)", (mine,))
        finally:
            reg.close()
        c = sqlite3.connect(tmpdb)
        try:
            c.execute("PRAGMA journal_mode=DELETE").fetchone()
        finally:
            c.close()
        if live.is_file():
            c = sqlite3.connect(live)
            try:
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            finally:
                c.close()
        for ext in ("-wal", "-shm"):
            Path(str(live) + ext).unlink(missing_ok=True)
        os.replace(tmpdb, live)
    except (sqlite3.Error, OSError) as e:
        raise _fail("E_VALIDATION", f"restore failed, the current registry is unchanged: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    reg = Registry.open(state_dir)
    try:
        with reg.transaction():
            reg.add_audit(user or "unknown", "tty", "restore", str(backup_path), after_sha=info["sha256"])
    finally:
        reg.close()
    return info
