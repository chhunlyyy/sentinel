"""Registry backup, verify and restore (OPS-05, PER-05).

A backup is the workspace registry (.sentinel/sentinel.db) copied with the sqlite3 backup API. user.db, config files
and run folders are not included. Old backups are never pruned. A `.sha256` file next to each copy lets verify catch
a changed byte that SQLite itself would not notice.
"""
import hashlib
import json
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


def _create_private(path):
    """Create an empty file that only the owner can open, before any data goes into it."""
    os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))


def create_backup(state_dir, out_dir=None, user=None, prefix="sentinel", audit=True, allow_broken=False):
    """Copy the registry, check the copy, and return {path, sha256, size, schema_version, counts, chain_ok, warnings}.
    A copy whose audit chain is broken is refused, unless `allow_broken` (the pre-restore copy, `backup --force`): it
    is kept, with chain_ok false and a warning, because it is the only record of the registry before a restore."""
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
    warnings = []
    try:
        _create_private(tmp)
        _copy_db(src, tmp)
        c = sqlite3.connect(tmp)
        try:
            c.execute("PRAGMA journal_mode=DELETE").fetchone()
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise _fail("E_INTEGRITY", "the copy failed PRAGMA integrity_check")
            counts, version = _counts(c), int(_meta(c, "schema_version") or 0)
        finally:
            c.close()
        chain = auditlog.verify_db(tmp) if version >= Registry.CHAIN_VERSION else {"ok": True}
        if not chain["ok"]:
            if not allow_broken:
                raise _fail("E_INTEGRITY", f"the copy failed its audit check: {chain['message']}")
            warnings.append(f"the audit chain is broken: {chain['message']}")
        digest = sha256_file(tmp)
        size = tmp.stat().st_size
        _create_private(side)
        side.write_text(f"{digest}  {final.name}\n")
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
                reg.add_audit(user or "unknown", "cli", "backup", str(final), after_sha=digest,
                              reason=json.dumps({"chain_ok": False}) if warnings else None)
        finally:
            reg.close()
    return {"path": str(final), "sha256": digest, "size": size, "schema_version": version, "counts": counts,
            "chain_ok": not warnings, "warnings": warnings}


def _read_sidecar(path):
    """The sha256 recorded next to a copy: None when there is no file, "" when it holds nothing."""
    side = Path(str(path) + ".sha256")
    if not side.is_file():
        return None
    words = side.read_text().split()
    return words[0] if words else ""


def _inspect(path, name, digest):
    """Open a copy read-only and check it; returns its info."""
    try:
        c = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True, timeout=10)
        try:
            result = c.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise _fail("E_INTEGRITY", f"{name} failed PRAGMA integrity_check: {result}")
            version = int(_meta(c, "schema_version") or 0)
            counts = _counts(c)
            registry_id = _meta(c, "registry_id")
        finally:
            c.close()
    except sqlite3.Error as e:
        raise _fail("E_INTEGRITY", f"{name} is damaged or truncated: {e}")
    if version > Registry.LATEST:
        raise _fail("E_INTEGRITY", f"{name} has schema_version {version}, newer than this Sentinel ({Registry.LATEST})")
    if version >= Registry.CHAIN_VERSION:
        chain = auditlog.verify_db(path)
        if not chain["ok"]:
            raise _fail("E_INTEGRITY", f"{name} has a broken audit chain: {chain['message']}")
    return {"path": str(path), "sha256": digest, "size": Path(path).stat().st_size, "schema_version": version,
            "counts": counts, "registry_id": registry_id}


def _check_magic(path):
    with open(path, "rb") as f:
        if f.read(16) != MAGIC:
            raise _fail("E_INTEGRITY", f"not a backup: {path} is not a SQLite file")


def verify_backup(path):
    """Check a copy and return its info (with `sidecar`: whether a recorded sha256 file exists), or raise
    E_INTEGRITY (exit 1) naming the problem."""
    path = Path(path)
    if not path.is_file():
        raise _fail("E_NOT_FOUND", f"not a backup: {path} is not a file")
    _check_magic(path)
    digest = sha256_file(path)
    want = _read_sidecar(path)
    if want is not None and want != digest:
        raise _fail("E_INTEGRITY", f"{path.name} does not match its recorded sha256 (the file was changed)")
    info = _inspect(path, path.name, digest)
    info["sidecar"] = want is not None
    return info


def running_conflicts(state_dir, config_dir):
    """What forbids a restore now: [(code detail text, details dict)]. A RUNNING task with a live process, or a
    Sentinel server holding the user's server lock."""
    found = []
    db = Path(state_dir) / "sentinel.db"
    if db.is_file():
        c = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True, timeout=10)
        try:
            for tid, pid, state in c.execute("SELECT id, pid, state FROM tasks WHERE state IN ('RUNNING', 'WAITING_FOR_INPUT')"):
                if pid is None:  # a native task has no process of its own: it runs inside Sentinel
                    found.append((f"task {tid} is {state} (native task)", {"task": tid, "pid": None}))
                    continue
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


def check_workspace(state_dir, info, backup_name):
    """E_VALIDATION when the copy belongs to another workspace."""
    live = Path(state_dir) / "sentinel.db"
    mine = None
    if live.is_file():
        c = sqlite3.connect(f"file:{live.resolve()}?mode=ro", uri=True, timeout=10)
        try:
            mine = _meta(c, "registry_id")
        finally:
            c.close()
    theirs = info["registry_id"]
    if mine and theirs and mine != theirs:
        raise _fail("E_VALIDATION", f"{backup_name} belongs to another workspace "
                    f"(backup registry id {theirs}, this workspace {mine})", {"backup": theirs, "workspace": mine})
    return mine


def unverified_reasons(info):
    """Why a copy cannot be tied to this workspace: it has no registry id, or no recorded sha256 file."""
    out = []
    if not info.get("registry_id"):
        out.append("it holds no registry id, so it cannot be tied to this workspace")
    if not info.get("sidecar"):
        out.append("it has no recorded .sha256 file, so a changed byte would not be noticed")
    return out


def restore(state_dir, backup_path, user=None, expected_sha=None, allow_unverified=False, config_dir=None):
    """Put a checked copy into the live registry with the sqlite3 backup API, so a connection that is open
    keeps working and no write is lost to a swapped file. The copy is read once into a private temp file, which is hashed
    and checked (against `expected_sha` and the recorded sha256). The current registry is first copied to
    pre-restore-<time>.db, even when its audit chain is broken (the copy then records chain_ok false)."""
    state_dir = Path(state_dir)
    backup_path = Path(backup_path)
    if not backup_path.is_file():
        raise _fail("E_NOT_FOUND", f"not a backup: {backup_path} is not a file")
    from apiserver import userdir
    busy = running_conflicts(state_dir, config_dir if config_dir is not None else userdir.config_dir())
    if busy:
        raise SentinelError("E_LOCKED", "cannot restore while something runs: " + "; ".join(t for t, _ in busy),
                            {"running": [d for _, d in busy]})
    live = state_dir / "sentinel.db"
    tmpdir = Path(tempfile.mkdtemp(dir=state_dir, prefix=".restore-"))
    try:
        os.chmod(tmpdir, 0o700)
        tmpdb = tmpdir / "sentinel.db"
        h = hashlib.sha256()
        with open(backup_path, "rb") as src, open(os.open(tmpdb, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as dst:
            for chunk in iter(lambda: src.read(1 << 20), b""):
                h.update(chunk)
                dst.write(chunk)
        digest = h.hexdigest()
        _check_magic(tmpdb)
        want = _read_sidecar(backup_path)
        if want is not None and want != digest:
            raise _fail("E_INTEGRITY", f"{backup_path.name} does not match its recorded sha256 (the file was changed)")
        if expected_sha and digest != expected_sha:
            raise _fail("E_INTEGRITY", f"{backup_path.name} changed after it was checked (sha256 {digest}, expected {expected_sha})")
        info = _inspect(tmpdb, backup_path.name, digest)
        info["path"], info["sidecar"] = str(backup_path), want is not None
        mine = check_workspace(state_dir, info, backup_path.name)
        reasons = unverified_reasons(info)
        if reasons and not allow_unverified:
            raise _fail("E_VALIDATION", f"{backup_path.name} is not verified: " + "; ".join(reasons), {"unverified": reasons})
        pre = None
        if live.is_file():
            pre = create_backup(state_dir, state_dir / "backups", user=user, prefix="pre-restore", audit=False, allow_broken=True)
        reg = Registry.open(tmpdir)  # migrates the copy to the current schema
        try:
            if mine:
                with reg.transaction():
                    reg._c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('registry_id', ?)", (mine,))
        finally:
            reg.close()
        _copy_db(tmpdb, live)
    except (sqlite3.Error, OSError) as e:
        raise _fail("E_VALIDATION", f"restore failed, the current registry is unchanged: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    info["pre_restore"] = {"path": pre["path"], "chain_ok": pre["chain_ok"]} if pre else None
    info["warnings"] = list(pre["warnings"]) if pre else []
    info["warnings"] += [f"the copy is unverified: {r}" for r in reasons]
    reg = Registry.open(state_dir)
    try:
        with reg.transaction():
            reg.add_audit(user or "unknown", "tty", "restore", str(backup_path), after_sha=digest,
                          reason=json.dumps({"pre_restore": info["pre_restore"]["path"] if pre else None,
                                             "chain_ok": pre["chain_ok"] if pre else None,
                                             "unverified": reasons or None}))
    finally:
        reg.close()
    return info
