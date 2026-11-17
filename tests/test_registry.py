import hashlib
import json
import multiprocessing
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from errors import SentinelError  # noqa: E402
from registry import Registry  # noqa: E402

M1 = (1, "init", "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);\n"
      "CREATE TABLE runs (id TEXT PRIMARY KEY, slug TEXT UNIQUE, request TEXT, type TEXT,"
      " tier INTEGER, initial_tier INTEGER, state TEXT, execution_status TEXT,"
      " acceptance_status TEXT, workflow_version TEXT, config_snapshot_id INTEGER,"
      " created_at TEXT, updated_at TEXT, finished_at TEXT, adhoc INTEGER);")
BAD2 = (2, "bad", "CREATE TABLE half_done (a TEXT);\nINSERT INTO no_such_table VALUES (1);")


def _open_worker(args):
    state_dir, barrier = args
    barrier.wait()
    try:
        r = Registry.open(state_dir)
        v = r.schema_version()
        r.close()
        return v
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name) / ".sentinel"
        self._open = []

    def reg(self, migrations=None, state_dir=None):
        r = Registry.open(state_dir or self.state_dir, migrations)
        self._open.append(r)
        self.addCleanup(r.close)
        return r

    def raw(self):
        c = sqlite3.connect(self.state_dir / "sentinel.db", isolation_level=None)
        self.addCleanup(c.close)
        return c


class TestMigrations(Base):
    def test_AC_PER_01a_creates_db_wal_latest_version(self):
        r = self.reg()
        self.assertTrue((self.state_dir / "sentinel.db").exists())
        self.assertEqual(r.journal_mode().lower(), "wal")
        self.assertEqual(r.schema_version(), Registry.LATEST)
        self.assertEqual(list(self.state_dir.glob("sentinel.db.bak-*")), [])

    def test_AC_PER_05a_failing_migration_leaves_database_untouched(self):
        r = self.reg([M1])
        r.insert_run({"slug": "old-run", "state": "CREATED"})
        r.close()
        with self.assertRaises(SentinelError) as cm:
            Registry.open(self.state_dir, [M1, BAD2])
        self.assertEqual(cm.exception.code, "E_MIGRATION")
        r2 = self.reg([M1])
        self.assertEqual(r2.schema_version(), 1)
        self.assertIsNotNone(r2.get_run("old-run"))
        tables = {x[0] for x in self.raw().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("half_done", tables)
        self.assertTrue((self.state_dir / "sentinel.db.bak-1").exists())
        bak = sqlite3.connect(self.state_dir / "sentinel.db.bak-1")
        self.addCleanup(bak.close)
        self.assertEqual(bak.execute("SELECT slug FROM runs").fetchall(), [("old-run",)])

    def test_AC_PER_05b_up_to_date_open_makes_no_backup(self):
        self.reg().close()
        self.reg().close()
        self.reg()
        self.assertEqual(list(self.state_dir.glob("sentinel.db.bak-*")), [])

    def test_AC_PER_05a_successful_upgrade_applies_and_backs_up(self):
        self.reg([M1]).close()
        ok2 = (2, "extra", "CREATE TABLE extra (a TEXT);")
        r = self.reg([M1, ok2])
        self.assertEqual(r.schema_version(), 2)
        self.assertTrue((self.state_dir / "sentinel.db.bak-1").exists())

    def test_AC_C_36a_concurrent_first_open(self):
        n = 4
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Manager().Barrier(n)
        with ctx.Pool(n) as pool:
            res = pool.map(_open_worker, [(str(self.state_dir), barrier)] * n)
        self.assertEqual(res, [Registry.LATEST] * n)

    def test_journal_mode_retry_failure_is_migration_error(self):
        self.reg().close()
        c = sqlite3.connect(self.state_dir / "sentinel.db")
        self.addCleanup(c.close)
        c.execute("PRAGMA journal_mode=DELETE")
        c.execute("BEGIN IMMEDIATE")
        with self.assertRaises(SentinelError) as cm:
            Registry.open(self.state_dir)
        self.assertEqual(cm.exception.code, "E_MIGRATION")

    def test_migration_file_with_triggers_applies(self):
        r = self.reg()
        names = {x[0] for x in self.raw().execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        self.assertEqual(names, {"events_no_update", "events_no_delete", "audit_no_update", "audit_no_delete",
                                 "events_no_replace", "audit_no_replace"})
        self.assertGreaterEqual(r.LATEST, 1)


class TestAppendOnly(Base):
    def test_AC_PER_03a_events_cannot_be_changed(self):
        r = self.reg()
        r.insert_run({"slug": "x"})
        run_id = r.get_run("x")["id"]
        eid = r.add_event(run_id, "run.created", "engine", {"a": 1})
        before = r.list_events(run_id)
        with self.assertRaises(ValueError):
            r.update_row("events", eid, type="hacked")
        with self.assertRaises(ValueError):
            r.update_row("audit", 1, action="hacked")
        c = self.raw()
        for sql in ("UPDATE events SET type='z'", "DELETE FROM events"):
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute(sql)
        self.assertEqual(r.list_events(run_id), before)
        self.assertEqual(before[0]["payload"], {"a": 1})

    def test_AC_PER_03a_audit_cannot_be_changed(self):
        r = self.reg()
        r.add_audit("alice", "cli", "config.set", "cfg", "a", "b")
        c = self.raw()
        for sql in ("UPDATE audit SET actor='z'", "DELETE FROM audit"):
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute(sql)
        self.assertEqual(c.execute("SELECT actor FROM audit").fetchall(), [("alice",)])

    def test_insert_or_replace_cannot_bypass_append_only(self):
        r = self.reg()
        r.add_event("r-1", "a.b", "engine")
        r.add_audit("human", "cli", "x", "y")
        c = self.raw()
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("INSERT OR REPLACE INTO events(id, type) VALUES (1, 'forged')")
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("INSERT OR REPLACE INTO audit(id, action) VALUES (1, 'forged')")
        with self.assertRaises(sqlite3.DatabaseError):
            r._c.execute("INSERT OR REPLACE INTO events(id, type) VALUES (1, 'forged')")
        self.assertEqual(r.list_events()[0]["type"], "a.b")

    def test_list_events_filters(self):
        r = self.reg()
        r.insert_run({"slug": "x"})
        rid = r.get_run("x")["id"]
        r.add_event(rid, "a.b", "engine")
        r.add_event(rid, "c.d", "engine", {"k": "v"}, task_id="t-1")
        self.assertEqual(len(r.list_events(rid)), 2)
        self.assertEqual([e["type"] for e in r.list_events(type="c.d")], ["c.d"])
        self.assertEqual(r.list_events(type="c.d")[0]["task_id"], "t-1")


class TestLegacy(Base):
    def test_AC_ORC_08a_legacy_run_indexed_file_unchanged(self):
        d = self.state_dir / "runs" / "old-run"
        d.mkdir(parents=True)
        blob = json.dumps({"slug": "old-run", "tier": 2, "outcome": "finished"}, indent=2).encode()
        (d / "state.json").write_bytes(blob)
        d2 = self.state_dir / "runs" / "open-run"
        d2.mkdir(parents=True)
        (d2 / "state.json").write_text(json.dumps({"slug": "open-run", "tier": 1}))
        d3 = self.state_dir / "runs" / "new-run"
        d3.mkdir(parents=True)
        (d3 / "state.json").write_text(json.dumps({"schema_version": 2, "slug": "new-run"}))
        r = self.reg()
        row = r.get_run("old-run")
        self.assertEqual(row["workflow_version"], "0.1")
        self.assertEqual(row["state"], "LEGACY")
        self.assertEqual(row["tier"], 2)
        self.assertEqual(row["execution_status"], "completed")
        self.assertEqual(r.get_run("open-run")["execution_status"], "running")
        self.assertEqual(r.get_run("open-run")["acceptance_status"], "pending")
        self.assertIsNone(r.get_run("new-run"))
        self.assertEqual((d / "state.json").read_bytes(), blob)
        r.close()
        self.reg()
        self.assertEqual(len(self.reg().list_runs()), 2)


def _legacy_worker(args):
    state_dir, barrier = args
    barrier.wait()
    try:
        r = Registry.open(state_dir)
        n = len(r.list_runs())
        r.close()
        return n
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"


class TestLegacyRace(Base):
    def test_concurrent_legacy_indexing(self):
        self.reg().close()
        for k in range(30):
            d = self.state_dir / "runs" / f"old{k}"
            d.mkdir(parents=True)
            (d / "state.json").write_text(json.dumps({"slug": f"old{k}", "tier": 1}))
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Manager().Barrier(4)
        with ctx.Pool(4) as pool:
            res = pool.map(_legacy_worker, [(str(self.state_dir), barrier)] * 4)
        self.assertEqual(res, [30] * 4)


class TestRows(Base):
    def test_generic_rows_restricted_to_id_tables(self):
        r = self.reg()
        r.insert_run({"slug": "a", "state": "CREATED"})
        rid = r.get_run("a")["id"]
        for table in ("run_repos", "meta", "events"):
            with self.assertRaises(ValueError):
                r.insert_row(table, {})
        with self.assertRaises(ValueError):
            r.get_row("meta", "x")
        with self.assertRaises(ValueError):
            r.update_row("runs", rid, state="FAILED")
        self.assertEqual(r.get_run("a")["state"], "CREATED")

    def test_has_passing_evidence(self):
        r = self.reg()
        self.assertFalse(r.has_passing_evidence("r-1"))
        r.insert_row("evidence", {"run_id": "r-1", "kind": "test", "passed": 0, "failed": 2})
        self.assertFalse(r.has_passing_evidence("r-1"))
        r.insert_row("evidence", {"run_id": "r-1", "kind": "test", "passed": 2, "failed": 0})
        self.assertTrue(r.has_passing_evidence("r-1"))
        self.assertFalse(r.has_passing_evidence("r-1", kind="lint"))


    def test_AC_PER_02a_run_repos_and_config_version_hash(self):
        r = self.reg()
        content = "version: 1\n"
        cid = r.store_config_version("project", content, author="me")
        self.assertEqual(r.get_config_version(cid)["sha256"], hashlib.sha256(content.encode()).hexdigest())
        self.assertEqual(r.store_config_version("project", content), cid)
        self.assertNotEqual(r.store_config_version("project", content + "x"), cid)
        r.insert_run({"slug": "lb", "config_snapshot_id": cid, "state": "CREATED"})
        run = r.get_run("lb")
        self.assertTrue(run["id"].startswith("r-"))
        self.assertEqual(run["config_snapshot_id"], cid)
        r.add_run_repo(run["id"], "backend", "aaa", "main")
        r.add_run_repo(run["id"], "frontend", "bbb")
        repos = {x["repo_id"]: x for x in r.run_repos(run["id"])}
        self.assertEqual(repos["backend"]["baseline_sha"], "aaa")
        self.assertEqual(repos["backend"]["branch"], "main")
        self.assertEqual(repos["frontend"]["baseline_sha"], "bbb")

    def test_update_run_sets_updated_at_and_rejects_bad_column(self):
        r = self.reg()
        r.insert_run({"slug": "a", "state": "CREATED"})
        r.update_run("a", state="TRIAGED", tier=2)
        run = r.get_run("a")
        self.assertEqual((run["state"], run["tier"]), ("TRIAGED", 2))
        self.assertTrue(run["updated_at"].endswith("Z") or "+00:00" in run["updated_at"])
        with self.assertRaises(ValueError):
            r.update_run("a", **{"state='x', slug": "b"})
        with self.assertRaises(ValueError):
            r.insert_row("nope; DROP TABLE runs", {})
        self.assertEqual(len(r.list_runs()), 1)

    def test_generic_rows(self):
        r = self.reg()
        tid = r.insert_row("tasks", {"run_id": "r-1", "role": "coder"})
        self.assertTrue(tid.startswith("t-"))
        r.update_row("tasks", tid, state="DONE")
        self.assertEqual(r.get_row("tasks", tid)["state"], "DONE")
        self.assertTrue(r.insert_row("approvals", {"run_id": "r-1"}).startswith("a-"))
        self.assertTrue(r.insert_row("cycles", {"run_id": "r-1"}).startswith("c-"))
        self.assertIsNone(r.get_row("tasks", "t-missing"))

    def test_transaction_commit_rollback_nested(self):
        r = self.reg()
        with r.transaction():
            r.insert_run({"slug": "a"})
        with self.assertRaises(KeyError):
            with r.transaction():
                r.insert_run({"slug": "b"})
                raise KeyError("boom")
        self.assertEqual([x["slug"] for x in r.list_runs()], ["a"])
        with r.transaction():
            with self.assertRaises(Exception):
                with r.transaction():
                    pass


class TestConcurrency(Base):
    def test_AC_C_36a_two_writers_exactly_one_wins(self):
        r0 = self.reg()
        r0.insert_run({"slug": "lb", "state": "CREATED"})
        barrier = threading.Barrier(2)
        results = []

        def worker():
            reg = Registry.open(self.state_dir)
            try:
                barrier.wait()
                try:
                    with reg.transaction():
                        run = reg.get_run("lb")
                        if run["state"] != "CREATED":
                            raise SentinelError("E_TRANSITION", "not CREATED")
                        reg.update_run("lb", state="TRIAGED")
                        reg.add_event(run["id"], "run.state_changed", "orchestrator",
                                      {"from": "CREATED", "to": "TRIAGED"})
                    results.append("ok")
                except SentinelError as e:
                    results.append(e.code)
            finally:
                reg.close()

        ts = [threading.Thread(target=worker) for _ in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(results), ["E_TRANSITION", "ok"])
        self.assertEqual(len(r0.list_events(type="run.state_changed")), 1)


if __name__ == "__main__":
    unittest.main()
