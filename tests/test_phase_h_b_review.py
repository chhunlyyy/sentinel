"""Phase H part B review fixes: backup/restore, audit chain, verify --file, imports, log scrubbing."""
import json
import os
import sqlite3
import tempfile
import unittest
import pb_helpers  # noqa: F401 (puts sentinel/scripts on the path)
from pathlib import Path

import auditlog
import backup
import scrub
from errors import SentinelError
from registry import Registry


def fresh(n=10):
    d = Path(tempfile.mkdtemp())
    reg = Registry.open(d)
    with reg.transaction():
        for i in range(n):
            reg.add_audit("dev", "tty", "approve", f"run/{i}")
    reg.close()
    return d


def raw(d):
    c = sqlite3.connect(d / "sentinel.db")
    for t in auditlog.TRIGGERS:
        c.execute(f"DROP TRIGGER IF EXISTS {t}")
    return c


def break_chain(d):
    c = raw(d)
    c.execute("UPDATE audit SET actor='x' WHERE id=3")
    for s in auditlog.TRIGGERS.values():
        c.execute(s)
    c.commit()
    c.close()


class T(unittest.TestCase):
    def setUp(self):
        self.d = fresh()
        self.addCleanup(__import__("shutil").rmtree, self.d, True)

    def export_file(self, d=None, name="a.jsonl"):
        d = d or self.d
        reg = Registry.open(d)
        tmp, dig, n, head = auditlog.export(reg, d / name, "jsonl", {}, scrub.Scrubber(d, set()), "x", "p", d)
        os.replace(tmp, d / name)
        reg.close()
        return d / name

    # 1
    def test_restore_works_when_the_live_chain_is_broken(self):
        b = backup.create_backup(self.d, audit=False)
        break_chain(self.d)
        # an empty temporary config folder: restore asks it whether a server runs, and the real one may hold a live service
        with tempfile.TemporaryDirectory() as cfg:
            info = backup.restore(self.d, b["path"], user="dev", config_dir=Path(cfg))
        self.assertTrue(auditlog.verify_db(self.d / "sentinel.db")["ok"])
        pre = list((self.d / "backups").glob("pre-restore-*.db"))
        self.assertEqual(len(pre), 1)
        self.assertFalse(info.get("pre_restore", {}).get("chain_ok", True))
        self.assertTrue(info["warnings"])
        self.assertEqual(auditlog.verify_db(pre[0])["ok"], False)

    # 2
    def test_add_audit_takes_text_or_none_only(self):
        reg = Registry.open(self.d)
        for field, value in (("reason", 12345), ("at", 1700000000), ("target", ["x"]), ("actor", 7), ("after_sha", 1.5),
                             ("before_sha", {"a": 1})):
            with self.subTest(field=field):
                kw = {"actor": "dev", "channel": "tty", "action": "approve", "target": "run/x"}
                kw[field] = value
                with self.assertRaises(SentinelError) as cm:
                    reg.add_audit(**kw)
                self.assertEqual(cm.exception.code, "E_VALIDATION")
        reg.add_audit("dev", "tty", "approve", "run/ok", reason=None)
        reg.close()
        self.assertTrue(auditlog.verify_db(self.d / "sentinel.db")["ok"])
        self.assertEqual(backup.create_backup(self.d, audit=False)["chain_ok"], True)

    # 3
    def rewrite(self, lines, name):
        p = self.d / name
        p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        return p

    def read(self, p):
        return [json.loads(x) for x in Path(p).read_text().splitlines()]

    def test_verify_file_refuses_a_forged_scrubbed_flag(self):
        lines = self.read(self.export_file())
        lines[3]["actor"] = "mallory"
        lines[3]["scrubbed"] = True
        res = auditlog.verify_file(self.rewrite(lines, "b.jsonl"))
        self.assertFalse(res["ok"], res)
        self.assertEqual(res["row"], lines[3]["id"])

    def test_verify_file_needs_every_row_when_nothing_was_filtered(self):
        src = self.export_file()
        lines = self.read(src)
        del lines[5]
        lines[0]["rows"] -= 1
        res = auditlog.verify_file(self.rewrite(lines, "c.jsonl"))
        self.assertFalse(res["ok"], res)
        lines = self.read(src)
        del lines[1]  # the first row
        lines[0]["rows"] -= 1
        self.assertFalse(auditlog.verify_file(self.rewrite(lines, "c2.jsonl"))["ok"])

    def test_verify_file_checks_the_link_between_neighbours(self):
        lines = self.read(self.export_file())
        row = lines[4]  # id 4: new content and new hashes that still start from its own prev_chain_sha
        row["actor"] = "mallory"
        row["row_sha"] = auditlog.row_sha(row)
        row["chain_sha"] = auditlog.chain_sha(row["prev_chain_sha"], row["row_sha"])
        res = auditlog.verify_file(self.rewrite(lines, "d.jsonl"))
        self.assertFalse(res["ok"], res)
        self.assertEqual(res["row"], lines[5]["id"])

    def test_verify_file_counts_the_rows_it_could_only_link_check(self):
        reg = Registry.open(self.d)
        reg.add_audit("dev", "tty", "approve", "run/s", reason="password=Sup3rSecretValue99")
        reg.close()
        p = self.export_file()
        res = auditlog.verify_file(p)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["scrubbed"], 1)

    def rechain(self, lines):
        prev = auditlog.ZERO
        for row in lines[1:]:
            row["prev_chain_sha"] = prev
            row["row_sha"] = auditlog.row_sha(row)
            row["chain_sha"] = prev = auditlog.chain_sha(prev, row["row_sha"])
        lines[0]["head_chain_sha"] = prev

    def test_verify_file_against_the_registry(self):
        p = self.export_file()
        db = self.d / "sentinel.db"
        self.assertTrue(auditlog.verify_file(p, db=db)["ok"])
        lines = self.read(p)
        lines[4]["actor"] = "mallory"  # a file that is consistent with itself, but not with the registry
        self.rechain(lines)
        bad = self.rewrite(lines, "e.jsonl")
        self.assertTrue(auditlog.verify_file(bad)["ok"])
        res = auditlog.verify_file(bad, db=db)
        self.assertFalse(res["ok"], res)
        self.assertEqual(res["row"], 4)

    # 10
    def test_triggers_that_do_nothing_are_found(self):
        c = raw(self.d)
        for name in auditlog.TRIGGERS:
            event = {"audit_no_update": "UPDATE", "audit_no_delete": "DELETE", "audit_no_replace": "INSERT"}[name]
            c.execute(f"CREATE TRIGGER {name} BEFORE {event} ON audit WHEN 0 BEGIN SELECT 1; END")
        c.commit()
        c.close()
        res = auditlog.verify_db(self.d / "sentinel.db")
        self.assertFalse(res["ok"])
        self.assertIn("trigger", res["message"])

    def test_missing_triggers_are_named_as_missing(self):
        c = raw(self.d)
        c.commit()
        c.close()
        res = auditlog.verify_db(self.d / "sentinel.db")
        self.assertFalse(res["ok"])
        self.assertIn("are missing", res["message"])
        self.assertIn("audit_no_update", res["message"])

    # 13
    def test_csv_guard_covers_tab_and_carriage_return(self):
        for v in ("=1+1", "+1", "-1", "@x", "\tx", "\rx"):
            self.assertTrue(auditlog._csv_safe(v).startswith("'"), v)
        self.assertEqual(auditlog._csv_safe("plain"), "plain")

    # 14
    def test_export_scrubs_like_the_logs_do(self):
        os.environ["SENTINEL_DASHBOARD_TOKEN"] = "canary-dash-token-123456"
        self.addCleanup(os.environ.pop, "SENTINEL_DASHBOARD_TOKEN", None)
        reg = Registry.open(self.d)
        reg.add_audit("dev", "tty", "approve", "run/t", reason="saw canary-dash-token-123456 here")
        reg.close()
        text = self.export_file().read_text()
        self.assertNotIn("canary-dash-token-123456", text)
        self.assertEqual(scrub.clean_text(scrub.Scrubber(self.d, set()), "x canary-dash-token-123456"), "x [redacted]")

    # 15
    def test_backfill_follows_the_migration_name_not_its_number(self):
        from registry import _load_file_migrations
        old = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, old, True)
        migs = _load_file_migrations()
        reg = Registry.open(old, migrations=[m for m in migs if m[1] != "audit_chain"])
        for i in range(5):
            reg._c.execute("INSERT INTO audit(actor, channel, action, target, at) VALUES ('dev','tty','approve',?,?)",
                           (f"t{i}", f"2026-11-01T00:00:0{i}Z"))
        reg.close()
        moved = [(v + 100 if n == "audit_chain" else v, n, sql) for v, n, sql in migs]
        reg = Registry.open(old, migrations=moved)
        reg.close()
        self.assertTrue(auditlog.verify_db(old / "sentinel.db")["ok"])
