"""Phase H part B: audit hash chain, export and verify (audit_export.feature)."""
import csv
import hashlib
import io
import json
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from pb_helpers import CLIBase, CLI, CLI_ENV, SLUG, run_plain
from registry import Registry

ACTIONS = ["approve", "accepted", "cancel", "resume", "retry"]
TRIGGERS = ("audit_no_update", "audit_no_delete", "audit_no_replace")


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class AuditBase(CLIBase):
    def setUp(self):
        super().setUp()
        self.mk()
        self.seed(30)
        self.db = self.ws / ".sentinel" / "sentinel.db"

    def seed(self, n, start=0):
        with self.eng.reg.transaction():
            for i in range(start, start + n):
                day = "2026-11-01" if i < 10 else "2026-11-02" if i < 20 else "2026-11-05"
                self.eng.reg.add_audit("dev" if i % 2 == 0 else "engine", "tty" if i % 3 else "dashboard",
                                       ACTIONS[i % 5], f"{SLUG}/spec" if i % 4 else "other-run",
                                       after_sha=sha(str(i)), reason=f"r{i}", at=f"{day}T10:00:{i % 60:02d}.000000Z")

    def verify(self, *args):
        return run_plain(self.d + ["audit", "verify", *args])

    def export(self, *args, env=None):
        r = subprocess.run(CLI + self.d + ["audit", "export", *args], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, env=env or CLI_ENV, cwd=self.ws)
        return r.returncode, r.stdout + r.stderr

    def lines(self, name):
        return [json.loads(x) for x in (self.ws / name).read_text().splitlines()]


class AppendOnly(AuditBase):
    def test_AC_SEC_07c_the_registry_refuses_changes_to_audit_rows(self):
        for stmt in ("UPDATE audit SET actor = 'agent' WHERE id = 3", "DELETE FROM audit WHERE id = 3", "DELETE FROM audit"):
            with self.subTest(stmt=stmt):
                c = sqlite3.connect(self.db)
                with self.assertRaises(sqlite3.DatabaseError) as cm:
                    c.execute(stmt)
                self.assertIn("audit is append-only", str(cm.exception))
                self.assertEqual(c.execute("SELECT count(*) FROM audit").fetchone()[0], 30)
                c.close()

    def test_AC_SEC_07d_each_new_row_extends_the_chain(self):
        before = self.eng.reg.audit_rows()[-1]
        self.eng.audit("dev", "tty", "approve", f"{SLUG}/spec")
        new = self.eng.reg.audit_rows()[-1]
        self.assertEqual(new["chain_sha"], sha(before["chain_sha"] + new["row_sha"]))
        body = {k: new[k] for k in ("id", "at", "actor", "channel", "action", "target", "before_sha", "after_sha", "reason")}
        self.assertEqual(new["row_sha"], sha(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)))
        with self.assertRaises(RuntimeError):
            with self.eng.reg.transaction():
                self.eng.reg.add_audit("dev", "tty", "x", "y")
                raise RuntimeError("roll back")
        self.assertEqual(len(self.eng.reg.audit_rows()), 31)  # row and chain share the transaction of the caller

    def test_AC_SEC_07e_existing_rows_are_chained_by_the_migration(self):
        old = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, old, True)
        from registry import _load_file_migrations
        before = [m for m in _load_file_migrations() if m[0] < 10]
        reg = Registry.open(old, migrations=before)
        self.assertEqual(reg.schema_version(), 9)
        for i in range(30):
            reg._c.execute("INSERT INTO audit(actor, channel, action, target, at) VALUES (?,?,?,?,?)",
                           ("dev", "tty", "approve", f"t{i}", f"2026-11-01T00:00:{i:02d}Z"))
        reg.close()
        reg = Registry.open(old)
        self.assertTrue((old / "sentinel.db.bak-9").exists())
        rows = reg.audit_rows()
        self.assertEqual(len(rows), 30)
        self.assertTrue(all(r["row_sha"] and r["chain_sha"] for r in rows))
        reg.close()
        code, out = run_plain(["--dir", str(self.ws), "audit", "verify", "--db", str(old / "sentinel.db")])
        self.assertEqual(code, 0, out)

    def test_AC_SEC_07f_verify_finds_tampering(self):
        def insert_between(c):
            c.execute("UPDATE audit SET id=id+1000 WHERE id>12")
            c.execute("INSERT INTO audit(id, actor, channel, action, target, at) VALUES (13,'x','tty','approve','t','2026-11-01T00:00:00Z')")
            c.execute("UPDATE audit SET id=id-987 WHERE id>1000")
        cases = {
            "actor changed": (lambda c: c.execute("UPDATE audit SET actor='agent' WHERE id=12"), 12),
            "row deleted": (lambda c: c.execute("DELETE FROM audit WHERE id=12"), 13),
            "row inserted": (insert_between, 13),
            "triggers missing": (lambda c: None, None),
        }
        for n, (name, (tamper, broken)) in enumerate(cases.items()):
            with self.subTest(name):
                copy = self.ws / f"copy-{n}.db"
                src, dst = sqlite3.connect(self.db), sqlite3.connect(copy)
                src.backup(dst)
                src.close()
                dst.close()
                c = sqlite3.connect(copy)
                for t in TRIGGERS:
                    c.execute(f"DROP TRIGGER IF EXISTS {t}")
                tamper(c)
                c.commit()
                c.close()
                code, out = self.verify("--db", str(copy))
                self.assertEqual(code, 1, out)
                if broken:
                    self.assertIn(f"row {broken}", out)
                else:
                    self.assertIn("triggers", out)

    def test_AC_SEC_07g_verify_passes_on_an_untouched_registry(self):
        code, out = self.verify()
        self.assertEqual(code, 0, out)
        head = self.eng.reg.audit_rows()[-1]["chain_sha"]
        self.assertIn("30 rows", out)
        self.assertIn(head, out)


class Export(AuditBase):
    def test_AC_SEC_07h_export_to_a_json_lines_file(self):
        code, out = self.export("--out", "audit.jsonl")
        self.assertEqual(code, 0, out)
        p = self.ws / "audit.jsonl"
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        head, *rows = self.lines("audit.jsonl")
        self.assertEqual(head["format"], "sentinel-audit-v1")
        for k in ("project", "sentinel_version", "exported_at", "filters", "rows", "head_chain_sha"):
            self.assertIn(k, head)
        self.assertEqual(head["rows"], 30)
        self.assertEqual(len(rows), 30)
        for k in ("id", "at", "actor", "channel", "action", "target", "before_sha", "after_sha", "reason", "row_sha",
                  "prev_chain_sha", "chain_sha"):
            self.assertIn(k, rows[0])
        self.assertEqual(head["head_chain_sha"], rows[-1]["chain_sha"])
        self.assertEqual(self.verify("--file", str(p))[0], 0)

    def test_AC_SEC_07i_filters(self):
        cases = [(["--from", "2026-11-01", "--to", "2026-11-02"], lambda r: r["at"][:10] in ("2026-11-01", "2026-11-02")),
                 (["--actor", "dev"], lambda r: r["actor"] == "dev"),
                 (["--channel", "dashboard"], lambda r: r["channel"] == "dashboard"),
                 (["--action", "approve"], lambda r: r["action"] == "approve"),
                 (["--run", SLUG], lambda r: r["target"] == SLUG or r["target"].startswith(SLUG + "/"))]
        for flags, pred in cases:
            with self.subTest(flags=flags):
                allrows = [r for r in self.eng.reg.audit_rows() if r["action"] != "audit_exported"]
                code, out = self.export("--out", "a.jsonl", "--force", *flags)
                self.assertEqual(code, 0, out)
                head, *rows = self.lines("a.jsonl")
                self.assertEqual([r["id"] for r in rows], [r["id"] for r in allrows if pred(r)])
                self.assertTrue(rows)
                self.assertTrue(head["filters"])
                self.assertEqual(self.verify("--file", str(self.ws / "a.jsonl"))[0], 0)

    def test_AC_SEC_07j_csv_export(self):
        self.eng.audit("=cmd|x", "tty", "+approve", "-t", reason="@sum")
        code, out = self.export("--format", "csv", "--out", "audit.csv")
        self.assertEqual(code, 0, out)
        rows = list(csv.DictReader(io.StringIO((self.ws / "audit.csv").read_text())))
        self.assertEqual(len(rows), 31)
        bad = rows[-1]
        self.assertEqual((bad["actor"], bad["action"], bad["target"], bad["reason"]), ("'=cmd|x", "'+approve", "'-t", "'@sum"))

    def test_AC_SEC_07k_the_export_is_scrubbed_and_marks_scrubbed_rows(self):
        self.eng.audit("dev", "tty", "approve", "plain", reason="token=abcd1234efgh5678")
        self.eng.audit("dev", "tty", "approve", str(self.ws / "x" / "file"))
        code, out = self.export("--out", "audit.jsonl")
        self.assertEqual(code, 0, out)
        text = (self.ws / "audit.jsonl").read_text()
        self.assertNotIn("abcd1234efgh5678", text)
        self.assertNotIn(str(self.ws), text)
        rows = self.lines("audit.jsonl")[1:]
        self.assertEqual([r["id"] for r in rows if r.get("scrubbed")], [31, 32])
        self.assertEqual(self.verify("--file", str(self.ws / "audit.jsonl"))[0], 0)

    def test_AC_SEC_07l_nothing_matches(self):
        code, out = self.export("--out", "a.jsonl", "--actor", "nobody")
        self.assertEqual(code, 0, out)
        lines = self.lines("a.jsonl")
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["rows"], 0)

    def test_AC_SEC_07m_bad_arguments(self):
        (self.ws / "existing.jsonl").write_text("x")
        for args, code in ((["--out", "a.jsonl", "--from", "2026-99-01"], 2), (["--out", "a.jsonl", "--format", "xml"], 2),
                           (["--out", "existing.jsonl"], 1), (["--out", "/nonexistent/dir/a.jsonl"], 1)):
            with self.subTest(args=args):
                c, out = self.export(*args)
                self.assertEqual(c, code, out)
                self.assertFalse((self.ws / "a.jsonl").exists())
        self.assertEqual((self.ws / "existing.jsonl").read_text(), "x")

    def test_AC_SEC_07n_overwrite_only_with_force(self):
        (self.ws / "existing.jsonl").write_text("x")
        code, out = self.export("--out", "existing.jsonl", "--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.lines("existing.jsonl")[0]["format"], "sentinel-audit-v1")
        self.assertEqual([p.name for p in self.ws.glob(".*audit*")], [])  # temporary file renamed away

    def test_AC_SEC_07o_a_task_process_cannot_export_the_audit(self):
        code, out = self.export("--out", "a.jsonl", env={**CLI_ENV, "SENTINEL_TASK_ID": "t-1"})
        self.assertEqual(code, 5, out)
        self.assertIn("E_ACTOR", out)
        self.assertFalse((self.ws / "a.jsonl").exists())

    def test_AC_SEC_07p_the_export_itself_is_audited(self):
        code, out = self.export("--out", "a.jsonl", "--actor", "dev")
        self.assertEqual(code, 0, out)
        last = self.eng.reg.audit_rows()[-1]
        self.assertEqual(last["id"], 31)
        self.assertEqual(last["action"], "audit_exported")
        self.assertEqual(last["after_sha"], hashlib.sha256((self.ws / "a.jsonl").read_bytes()).hexdigest())
        self.assertIn("dev", last["reason"])
        self.assertEqual(self.lines("a.jsonl")[0]["rows"], 15)

    def test_AC_SEC_07q_export_while_approvals_are_written(self):
        def writer():
            c = Registry.open(self.ws / ".sentinel")
            try:
                for i in range(50):
                    with c.transaction():
                        c.add_audit("dev", "tty", "approve", f"w{i}")
                    time.sleep(0.01)
            finally:
                c.close()
        t = threading.Thread(target=writer)
        t.start()
        code, out = self.export("--out", "a.jsonl")
        t.join()
        self.assertEqual(code, 0, out)
        head, *rows = self.lines("a.jsonl")
        self.assertEqual(head["rows"], len(rows))
        self.assertIn(head["head_chain_sha"], [r["chain_sha"] for r in self.eng.reg.audit_rows()])
        self.assertEqual(self.verify("--file", str(self.ws / "a.jsonl"))[0], 0)

    def test_AC_SEC_07r_the_registry_is_locked_for_writing(self):
        lock = sqlite3.connect(self.db, isolation_level=None)
        lock.execute("BEGIN EXCLUSIVE")
        self.addCleanup(lock.close)
        code, out = self.export("--out", "a.jsonl", env={**CLI_ENV, "SENTINEL_BUSY_TIMEOUT_MS": "500"})
        self.assertEqual(code, 1, out)
        self.assertIn("E_LOCKED", out)
        self.assertFalse((self.ws / "a.jsonl").exists())
        self.assertEqual([p for p in self.ws.iterdir() if "audit" in p.name], [])

    def test_AC_SEC_07s_the_dashboard_audit_view_uses_the_same_rows(self):
        from apiserver import views
        rows = self.eng.reg._c.execute("SELECT id, row_sha, chain_sha FROM audit ORDER BY id").fetchall()
        self.assertTrue(all(r["row_sha"] and r["chain_sha"] for r in rows))
        self.assertIn("row_sha", views.AUDIT_COLUMNS)
        self.assertIn("chain_sha", views.AUDIT_COLUMNS)


if __name__ == "__main__":
    unittest.main()
