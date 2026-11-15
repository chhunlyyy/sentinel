"""Audit hash chain, verify and export (SEC-07).

Each audit row stores row_sha (sha256 of its canonical JSON) and chain_sha (sha256 of the previous chain_sha and
its row_sha, as hex text; the first row chains from 64 zeros). The registry also refuses UPDATE and DELETE with
triggers. A same-user attacker can drop the triggers and rewrite the whole chain (docs/security.md, R1): the chain
proves that nobody changed history by accident or partially, not that nobody could.
"""
import csv
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import scrub
from errors import SentinelError

ZERO = "0" * 64
FIELDS = ("id", "at", "actor", "channel", "action", "target", "before_sha", "after_sha", "reason")
FORMAT = "sentinel-audit-v1"
TRIGGERS = {
    "audit_no_update": "CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit\nBEGIN SELECT RAISE(ABORT, 'audit is append-only'); END",
    "audit_no_delete": "CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit\nBEGIN SELECT RAISE(ABORT, 'audit is append-only'); END",
    "audit_no_replace": "CREATE TRIGGER audit_no_replace BEFORE INSERT ON audit\nWHEN EXISTS (SELECT 1 FROM audit WHERE id = NEW.id)\nBEGIN SELECT RAISE(ABORT, 'audit is append-only'); END",
}
TEXT_FIELDS = ("actor", "channel", "action", "target", "before_sha", "after_sha", "reason")
SCRUB_MARKS = ("[REDACTED", "$WORKSPACE", "$HOME", "[redacted]")  # what the scrubber leaves where it changed a value
IMPORT_CHANNEL = "import"
COLUMNS = FIELDS + ("row_sha", "prev_chain_sha", "chain_sha")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def row_sha(row):
    body = {k: row.get(k) for k in FIELDS}
    return _sha(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def chain_sha(prev, rsha):
    return _sha((prev or ZERO) + rsha)


def backfill(conn):
    """Chain every audit row that has no chain_sha yet, in id order. Runs inside the migration transaction; the
    append-only triggers are dropped for the UPDATEs and put back."""
    rows = conn.execute("SELECT * FROM audit ORDER BY id").fetchall()
    if not rows or all(r["chain_sha"] for r in rows):
        return
    for name in TRIGGERS:
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    prev = ZERO
    for r in rows:
        d = dict(r)
        rs = d.get("row_sha") or row_sha(d)
        cs = d.get("chain_sha") or chain_sha(prev, rs)
        conn.execute("UPDATE audit SET row_sha=?, chain_sha=? WHERE id=?", (rs, cs, d["id"]))
        prev = cs
    for sql in TRIGGERS.values():
        conn.execute(sql)


def _norm_sql(sql):
    return re.sub(r"\s+", " ", sql or "").strip().lower()


def is_imported(row):
    return row.get("channel") == IMPORT_CHANNEL


def _problem(message, row_id=None):
    return {"ok": False, "row": row_id, "message": message}


def verify_db(path):
    """Check the chain of a registry file without opening it for writing. Returns a dict with ok, rows, head or the
    first broken row."""
    try:
        c = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True, timeout=10)
        c.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        return _problem(f"cannot open {path}: {e}")
    try:
        try:
            triggers = {r[0]: r[1] for r in c.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='audit'")}
            cols = {r[1] for r in c.execute("PRAGMA table_info(audit)")}
            rows = c.execute("SELECT * FROM audit ORDER BY id").fetchall()
        except sqlite3.Error as e:
            return _problem(f"cannot read the audit table: {e}")
    finally:
        c.close()
    if "chain_sha" not in cols:
        return _problem("the audit table has no hash chain (registry older than schema 10)")
    prev, imported = ZERO, 0
    for r in rows:
        d = dict(r)
        imported += is_imported(d)
        if d["row_sha"] != row_sha(d):
            return _problem(f"audit chain broken at row {d['id']}: its content does not match its row_sha", d["id"])
        if d["chain_sha"] != chain_sha(prev, d["row_sha"]):
            return _problem(f"audit chain broken at row {d['id']}: its chain_sha does not follow the row before it", d["id"])
        prev = d["chain_sha"]
    missing = sorted(set(TRIGGERS) - set(triggers))
    if missing:
        return _problem(f"the append-only triggers are missing: {', '.join(missing)}")
    changed = sorted(n for n, sql in TRIGGERS.items() if _norm_sql(triggers[n]) != _norm_sql(sql))
    if changed:
        return _problem(f"the append-only triggers were changed: {', '.join(changed)}")
    return {"ok": True, "rows": len(rows), "head": prev, "imported": imported}


def verify_file(path, db=None):
    """Check an exported file: each row against its own prev_chain_sha, and the link between neighbours that
    are consecutive ids. An export without filters must hold ids 1..N. Scrubbed rows are checked for their chain link
    only (their content is not the original), must show a mark of the scrubber, and are counted in `scrubbed`.
    With `db` (a registry file) every row's chain_sha must equal the registry's row of the same id."""
    try:
        lines = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError) as e:
        return _problem(f"cannot read {path}: {e}")
    if not lines or not isinstance(lines[0], dict) or lines[0].get("format") != FORMAT:
        return _problem(f"{path} is not a {FORMAT} file")
    head, rows = lines[0], lines[1:]
    if head.get("rows") != len(rows):
        return _problem(f"header says {head.get('rows')} rows, file holds {len(rows)}")
    if not all(isinstance(d, dict) and isinstance(d.get("id"), int) for d in rows):
        return _problem("a row has no integer id")
    unfiltered = not head.get("filters")
    last, scrubbed, imported = None, 0, 0
    for n, d in enumerate(rows, 1):
        if unfiltered and d["id"] != n:
            return _problem(f"audit chain broken at row {d['id']}: an export without filters must hold rows 1 to {len(rows)} in order", d["id"])
        if unfiltered and n == 1 and d.get("prev_chain_sha") != ZERO:
            return _problem(f"audit chain broken at row {d['id']}: the first row does not start the chain", d["id"])
        if d.get("scrubbed"):
            if d.get("scrubbed") is not True or not any(m in str(d.get(k) or "") for k in TEXT_FIELDS for m in SCRUB_MARKS):
                return _problem(f"audit chain broken at row {d['id']}: it is marked scrubbed but shows no scrubbed value", d["id"])
            scrubbed += 1
        elif d.get("row_sha") != row_sha(d):
            return _problem(f"audit chain broken at row {d.get('id')}: its content does not match its row_sha", d.get("id"))
        imported += is_imported(d)
        if d.get("chain_sha") != chain_sha(d.get("prev_chain_sha"), d.get("row_sha") or ""):
            return _problem(f"audit chain broken at row {d.get('id')}: its chain_sha does not follow its prev_chain_sha", d.get("id"))
        if last and d["id"] == last["id"] + 1 and d["prev_chain_sha"] != last["chain_sha"]:
            return _problem(f"audit chain broken at row {d['id']}: it does not follow row {last['id']}", d["id"])
        last = d
    if rows and head.get("head_chain_sha") != rows[-1]["chain_sha"]:
        return _problem("the header head_chain_sha is not the last row's chain_sha", rows[-1]["id"])
    if db is not None:
        try:
            c = sqlite3.connect(f"file:{Path(db).resolve()}?mode=ro", uri=True, timeout=10)
            try:
                registry = dict(c.execute("SELECT id, chain_sha FROM audit"))
            finally:
                c.close()
        except sqlite3.Error as e:
            return _problem(f"cannot read the registry {db}: {e}")
        for d in rows:
            if registry.get(d["id"]) != d.get("chain_sha"):
                return _problem(f"row {d['id']} of the file is not row {d['id']} of the registry {db}", d["id"])
    return {"ok": True, "rows": len(rows), "head": rows[-1]["chain_sha"] if rows else None, "scrubbed": scrubbed,
            "imported": imported, "registry_checked": db is not None}


# ---- export
def parse_day(text, name):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise SentinelError("E_VALIDATION", f"{name} must be a date like 2026-11-01, got {text!r}", exit_code=2)


def snapshot(reg, filters):
    """Rows matching the filters, read in one transaction, each with its prev_chain_sha."""
    where, args = [], []
    if filters.get("from"):
        where.append("at >= ?")
        args.append(filters["from"])
    if filters.get("to"):
        where.append("at < date(?, '+1 day')")
        args.append(filters["to"])
    for key in ("actor", "channel", "action"):
        if filters.get(key):
            where.append(f"{key} = ?")
            args.append(filters[key])
    if filters.get("run"):
        where.append("(target = ? OR target LIKE ? ESCAPE '\\')")
        run = filters["run"]
        args += [run, run.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"]
    sql = (f"SELECT * FROM (SELECT *, LAG(chain_sha, 1, '{ZERO}') OVER (ORDER BY id) AS prev_chain_sha FROM audit)"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id")
    c = reg._c
    c.execute("BEGIN")
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.execute("COMMIT")


def _csv_safe(value):
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def export(reg, out, fmt, filters, scrubber, version, project, workspace, force=False):
    """Write the scrubbed export atomically; returns (sha256 of the file, rows written, head chain_sha)."""
    out = Path(out)
    if out.exists() and not force:
        raise SentinelError("E_VALIDATION", f"{out} exists; use --force to replace it", exit_code=1)
    if not out.parent.is_dir():
        raise SentinelError("E_VALIDATION", f"the folder {out.parent} does not exist", exit_code=1)
    rows = snapshot(reg, filters)
    items = []
    for r in rows:
        item = {k: r.get(k) for k in COLUMNS}
        scrubbed = False
        for k in TEXT_FIELDS:
            if isinstance(item[k], str):
                clean = scrub.clean_text(scrubber, item[k])
                if clean != item[k]:
                    item[k], scrubbed = clean, True
        if scrubbed:
            item["scrubbed"] = True
        if is_imported(r):
            item["imported"] = True
        items.append(item)
    head_sha = items[-1]["chain_sha"] if items else None
    header = {"format": FORMAT, "project": project, "sentinel_version": version,
              "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "filters": {k: v for k, v in filters.items() if v}, "rows": len(items), "head_chain_sha": head_sha}
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.audit-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            if fmt == "csv":
                w = csv.writer(f)
                cols = COLUMNS + ("scrubbed", "imported")
                w.writerow(cols)
                for item in items:
                    w.writerow([_csv_safe(item.get(k)) if k not in ("scrubbed", "imported") else item.get(k, False) for k in cols])
            else:
                f.write(json.dumps(header) + "\n")
                for item in items:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
        digest = hashlib.sha256(Path(tmp).read_bytes()).hexdigest()
        return tmp, digest, len(items), head_sha
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
