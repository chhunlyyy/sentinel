"""Phase H part B: registry backup, verify and restore (backup.feature)."""
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from pb_helpers import CLIBase, CLI, CLI_ENV, PtyProc, SLUG, run_plain
from apiserver import userdir
import auditlog
import backup as backup_mod
from registry import Registry


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class BackupBase(CLIBase):
    def setUp(self):
        super().setUp()
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        self.home = Path(self._home.name)
        self.env = {k: v for k, v in CLI_ENV.items() if k not in ("XDG_CONFIG_HOME", "SENTINEL_TASK_ID")}
        self.env.update(HOME=str(self.home), USER="dev", LOGNAME="dev")
        for i in range(3):
            self.mk(f"run-{i}" if i else SLUG)
        for i in range(40):
            self.eng.create_task(SLUG, "docs", f"docs {i}", repos=["backend"])
        for i in range(300):
            self.eng.reg.add_event(self.run_row()["id"], "run.note", "engine", {"i": i})
        for i in range(30):
            self.eng.audit("dev", "tty", "approve", f"{SLUG}/spec")
        self.db = self.ws / ".sentinel" / "sentinel.db"
        self.bdir = self.ws / ".sentinel" / "backups"

    def cli(self, *args, env=None, stdin=subprocess.DEVNULL):
        r = subprocess.run(CLI + self.d + list(args), stdin=stdin, capture_output=True, text=True, env=env or self.env,
                           cwd=self.ws)
        return r.returncode, r.stdout + r.stderr

    def make(self):
        code, out = self.cli("backup")
        self.assertEqual(code, 0, out)
        return json.loads(out)

    def counts(self, path):
        c = sqlite3.connect(path)
        try:
            return {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("runs", "tasks", "events", "audit")}
        finally:
            c.close()


class Backup(BackupBase):
    def test_AC_OPS_05a_a_backup_is_a_checked_copy(self):
        before = self.counts(self.db)
        info = self.make()
        p = Path(info["path"])
        self.assertEqual(p.parent, self.bdir)
        self.assertRegex(p.name, r"^sentinel-\d{8}T\d{6}.*Z\.db$")
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.bdir.stat().st_mode), 0o700)
        c = sqlite3.connect(p)
        self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        c.close()
        self.assertEqual(info["counts"], before)
        self.assertEqual(self.counts(p), before)
        self.assertEqual(info["sha256"], sha_file(p))
        self.assertEqual(info["size"], p.stat().st_size)
        self.assertEqual(info["schema_version"], self.eng.reg.schema_version())
        self.assertEqual(run_plain(self.d + ["audit", "verify", "--db", str(p)])[0], 0)

    def test_AC_OPS_05b_backup_while_a_run_writes(self):
        errors, stop = [], threading.Event()

        def writer():
            from registry import Registry
            r = Registry.open(self.ws / ".sentinel")
            rid = r.get_run(SLUG)["id"]
            try:
                while not stop.is_set():
                    try:
                        with r.transaction():
                            r.add_event(rid, "run.note", "engine", {})
                    except sqlite3.OperationalError as e:
                        errors.append(str(e))
                    time.sleep(0.01)
            finally:
                r.close()
        t = threading.Thread(target=writer)
        t.start()
        try:
            info = self.make()
        finally:
            stop.set()
            t.join()
        self.assertEqual(errors, [])
        c = sqlite3.connect(info["path"])
        self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        c.close()

    def test_AC_OPS_05c_backup_to_a_chosen_folder(self):
        target = self.home / "x" / "bk"
        code, out = self.cli("backup", "--out", str(target))
        self.assertEqual(code, 0, out)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
        self.assertEqual(len(list(target.glob("sentinel-*.db"))), 1)

    def test_AC_OPS_05d_the_target_cannot_be_written(self):
        before = sha_file(self.db)
        target = self.home / "full"

        def boom(src, dst):
            Path(dst).write_bytes(b"partial")
            raise sqlite3.OperationalError("database or disk is full")
        with mock.patch.object(backup_mod, "_copy_db", boom):  # fault injected: a full file system is not available
            with self.assertRaises(Exception) as cm:
                backup_mod.create_backup(self.ws / ".sentinel", target, user="dev")
        self.assertIn("disk is full", str(cm.exception))
        self.assertEqual(list(target.iterdir()) if target.exists() else [], [])
        self.assertEqual(sha_file(self.db), before)

    def test_AC_OPS_05e_no_registry_yet(self):
        fresh = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, fresh, True)
        (fresh / "sentinel.config.yaml").write_text("version: 1\nstate:\n  dir: .sentinel\nrepos: []\n")
        r = subprocess.run(CLI + ["--dir", str(fresh), "backup"], capture_output=True, text=True, env=self.env,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("nothing to back up", r.stdout + r.stderr)
        self.assertFalse((fresh / ".sentinel" / "sentinel.db").exists())

    def test_AC_OPS_05f_a_task_process_cannot_back_up_or_restore(self):
        info = self.make()
        env = {**self.env, "SENTINEL_TASK_ID": "t-1"}
        for args in (("backup",), ("backup", "restore", info["path"], "--yes")):
            with self.subTest(args=args):
                code, out = self.cli(*args, env=env)
                self.assertEqual(code, 5, out)
                self.assertIn("E_ACTOR", out)
        self.assertEqual(len(list(self.bdir.glob("sentinel-*.db"))), 1)

    def test_AC_OPS_05g_the_backup_is_audited(self):
        info = self.make()
        last = self.eng.reg.audit_rows()[-1]
        self.assertEqual((last["action"], last["after_sha"]), ("backup", info["sha256"]))
        self.assertIn(info["path"], last["target"])
        self.assertEqual(self.counts(info["path"])["audit"], 30)  # appended after the copy


class VerifyRestore(BackupBase):
    def bad_copy(self, problem):
        info = self.make()
        p = Path(info["path"])
        if problem == "byte":
            data = bytearray(p.read_bytes())
            data[len(data) // 2] ^= 0xFF
            p.write_bytes(bytes(data))
        elif problem == "truncated":
            p.write_bytes(p.read_bytes()[: p.stat().st_size // 2])
        elif problem == "not sqlite":
            p.write_bytes(b"hello, I am not a database" * 100)
        elif problem == "newer":
            c = sqlite3.connect(p)
            c.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
            c.commit()
            c.close()
            Path(str(p) + ".sha256").unlink(missing_ok=True)
        elif problem == "chain":
            c = sqlite3.connect(p)
            for t in ("audit_no_update",):
                c.execute(f"DROP TRIGGER {t}")
            c.execute("UPDATE audit SET actor='agent' WHERE id=5")
            c.commit()
            c.close()
            Path(str(p) + ".sha256").unlink(missing_ok=True)
        return p

    def test_AC_OPS_05h_verify_refuses_a_bad_copy(self):
        for problem in ("byte", "truncated", "not sqlite", "newer", "chain"):
            with self.subTest(problem):
                p = self.bad_copy(problem)
                code, out = self.cli("backup", "--verify", str(p))
                self.assertEqual(code, 1, out)
                self.assertTrue(out.strip())
        good = self.make()
        self.assertEqual(self.cli("backup", "--verify", good["path"])[0], 0)

    def restore_tty(self, path, answer=None, env=None):
        p = PtyProc(self.d + ["backup", "restore", str(path)], env or self.env)
        if p.wait_for("first 8 characters", 10):
            p.send((answer if answer is not None else sha_file(path)[:8]) + "\n")
        return p.finish()

    def test_AC_OPS_05i_restore_from_a_terminal(self):
        info = self.make()
        self.eng.audit("dev", "tty", "approve", "after-backup")
        code, out = self.restore_tty(info["path"])
        self.assertEqual(code, 0, out)
        pre = list(self.bdir.glob("pre-restore-*.db"))
        self.assertEqual(len(pre), 1)
        self.assertEqual(self.counts(pre[0])["audit"], 32)
        from registry import Registry
        reg = Registry.open(self.ws / ".sentinel")
        rows = reg.audit_rows()
        reg.close()
        self.assertEqual(rows[-1]["action"], "restore")
        self.assertEqual(rows[-1]["after_sha"], info["sha256"])
        self.assertEqual(len(rows), 31)  # the copy held 30 rows (its own backup row is appended after it) + the restore row
        self.assertNotIn("after-backup", [r["target"] for r in rows])
        code, out = self.cli("next", SLUG, "--json")
        self.assertIn(code, (0, 6), out)
        json.loads(out[out.index("{"):])

    def test_AC_OPS_05i_a_wrong_prefix_restores_nothing(self):
        info = self.make()
        before = sha_file(self.db)
        code, out = self.restore_tty(info["path"], answer="deadbeef")
        self.assertNotEqual(code, 0, out)
        self.assertEqual(sha_file(self.db), before)

    def test_AC_OPS_05j_restore_needs_a_terminal(self):
        info = self.make()
        before = sha_file(self.db)
        code, out = self.cli("backup", "restore", info["path"])
        self.assertEqual(code, 5, out)
        self.assertIn("E_NOT_TTY", out)
        reg = Registry.open(self.ws / ".sentinel")  # the refusal is the only change: one audit row
        rows = reg.audit_rows()
        reg.close()
        self.assertEqual(rows[-1]["action"], "restore_refused")
        self.assertEqual(rows[-1]["reason"], "E_NOT_TTY")
        self.assertEqual(len(rows), 32)  # 30 + the backup row + the refusal
        self.assertTrue(auditlog.verify_db(self.db)["ok"])

    def test_AC_OPS_05k_restore_refuses_while_something_runs(self):
        info = self.make()
        before = sha_file(self.db)
        with self.subTest("running task"):
            sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            self.addCleanup(sleeper.kill)
            tid = self.eng.reg.rows("tasks")[0]["id"]
            self.eng.reg.update_row("tasks", tid, state="RUNNING", pid=sleeper.pid)
            code, out = self.restore_tty(info["path"])
            self.assertEqual(code, 5, out)
            self.assertIn("E_LOCKED", out)
            self.assertIn(tid, out)
            self.eng.reg.update_row("tasks", tid, state="CREATED", pid=None)
            sleeper.kill()
        with self.subTest("server"):
            cfg = userdir.config_dir(self.env)
            userdir.ensure_dir(cfg)
            lock = userdir.ServerLock(cfg)
            self.assertTrue(lock.acquire())
            self.addCleanup(lock.release)
            userdir.write_server_json(cfg, {"pid": os.getpid(), "port": 4321, "token": "t"})
            code, out = self.restore_tty(info["path"])
            self.assertEqual(code, 5, out)
            self.assertIn("E_LOCKED", out)
            self.assertIn("4321", out)
            self.assertIn(str(os.getpid()), out)
        self.assertEqual(sha_file(self.db), before)

    def test_AC_OPS_05l_restore_refuses_a_copy_of_another_workspace(self):
        info = self.make()
        c = sqlite3.connect(info["path"])
        c.execute("UPDATE meta SET value='other-registry-id' WHERE key='registry_id'")
        c.commit()
        c.close()
        Path(info["path"] + ".sha256").unlink(missing_ok=True)
        mine = self.eng.reg._c.execute("SELECT value FROM meta WHERE key='registry_id'").fetchone()[0]
        code, out = self.restore_tty(info["path"])
        self.assertEqual(code, 1, out)
        self.assertIn("other-registry-id", out)
        self.assertIn(mine, out)

    def test_AC_OPS_05m_missing_arguments(self):
        for args in (("backup", "restore"), ("backup", "--verify"), ("backup", "--out")):
            with self.subTest(args=args):
                before = sha_file(self.db)
                code, out = self.cli(*args)
                self.assertEqual(code, 2, out)
                self.assertIn("usage", out.lower())
                self.assertEqual(sha_file(self.db), before)
        self.assertFalse(self.bdir.exists())

    def test_AC_PER_05c_a_failed_restore_leaves_the_current_registry_in_place(self):
        info = self.make()
        self.eng.audit("dev", "tty", "approve", "after-backup")
        self.eng.close()
        before = sha_file(self.db)

        real, calls = backup_mod._copy_db, []

        def boom(src, dst):
            calls.append(dst)
            if len(calls) == 1:  # the pre-restore copy works, the copy into the live registry fails (a failed backup-API
                return real(src, dst)  # copy is rolled back by SQLite, so the fault injected here writes nothing)
            raise sqlite3.OperationalError("disk I/O error")
        with mock.patch.object(backup_mod, "_copy_db", boom):
            with self.assertRaises(Exception):
                backup_mod.restore(self.ws / ".sentinel", info["path"], user="dev")
        self.assertEqual(sha_file(self.db), before)
        self.assertEqual(len(list(self.bdir.glob("pre-restore-*.db"))), 1)

    # ---- review fixes
    def audit_actions(self):
        reg = Registry.open(self.ws / ".sentinel")
        try:
            return [(r["action"], r["reason"]) for r in reg.audit_rows()]
        finally:
            reg.close()

    def test_restore_checks_for_running_work_itself(self):
        info = self.make()
        tid = self.eng.reg.rows("tasks")[0]["id"]
        cfg = self.home / "cfg"
        cfg.mkdir()
        for pid in (None, os.getpid()):  # a native task has no pid of its own; the other has a live process
            with self.subTest(pid=pid):
                self.eng.reg.update_row("tasks", tid, state="RUNNING", pid=pid)
                with self.assertRaises(backup_mod.SentinelError) as cm:
                    backup_mod.restore(self.ws / ".sentinel", info["path"], user="dev", config_dir=cfg)
                self.assertEqual(cm.exception.code, "E_LOCKED")
        self.eng.reg.update_row("tasks", tid, state="CREATED", pid=None)
        self.assertEqual(list(self.bdir.glob("pre-restore-*.db")), [])

    def test_restore_keeps_what_an_open_connection_writes_afterwards(self):
        info = self.make()
        cfg = self.home / "cfg"
        cfg.mkdir()
        backup_mod.restore(self.ws / ".sentinel", info["path"], user="dev", config_dir=cfg)
        with self.eng.reg.transaction():  # the engine of setUp still holds its connection from before the restore
            self.eng.reg.add_audit("dev", "tty", "approve", "after-restore")
        c = sqlite3.connect(self.db)
        self.assertEqual(c.execute("SELECT count(*) FROM audit WHERE target='after-restore'").fetchone()[0], 1)
        c.close()
        self.assertTrue(auditlog.verify_db(self.db)["ok"])

    def test_restore_hashes_what_it_copies(self):
        info = self.make()
        other = self.make()
        Path(other["path"] + ".sha256").unlink()
        Path(info["path"]).write_bytes(Path(other["path"]).read_bytes())  # swapped after the user confirmed
        Path(info["path"] + ".sha256").unlink()
        cfg = self.home / "cfg"
        cfg.mkdir()
        with self.assertRaises(backup_mod.SentinelError) as cm:
            backup_mod.restore(self.ws / ".sentinel", info["path"], user="dev", expected_sha=info["sha256"], config_dir=cfg)
        self.assertEqual(cm.exception.code, "E_INTEGRITY")
        self.assertEqual(list(self.bdir.glob("pre-restore-*.db")), [])

    def test_an_unverified_copy_needs_a_second_confirmation(self):
        info = self.make()
        Path(info["path"] + ".sha256").unlink()
        c = sqlite3.connect(info["path"])
        c.execute("DELETE FROM meta WHERE key='registry_id'")
        c.commit()
        c.close()
        info["sha256"] = sha_file(info["path"])
        cfg = self.home / "cfg"
        cfg.mkdir()
        with self.assertRaises(backup_mod.SentinelError) as cm:
            backup_mod.restore(self.ws / ".sentinel", info["path"], user="dev", config_dir=cfg)
        self.assertEqual(cm.exception.code, "E_VALIDATION")
        self.assertIn("not verified", cm.exception.message)
        before = sha_file(self.db)
        p = PtyProc(self.d + ["backup", "restore", info["path"]], self.env)
        p.wait_for("first 8 characters", 10)
        p.send(info["sha256"][:8] + "\n")
        self.assertTrue(p.wait_for("restore anyway", 10))
        p.send("yes\n")
        code, out = p.finish()
        self.assertEqual(code, 1, out)
        self.assertEqual(sha_file(self.db), before)
        p = PtyProc(self.d + ["backup", "restore", info["path"]], self.env)
        p.wait_for("first 8 characters", 10)
        p.send(info["sha256"][:8] + "\n")
        p.wait_for("restore anyway", 10)
        p.send("restore anyway\n")
        code, out = p.finish()
        self.assertEqual(code, 0, out)
        self.assertIn("warning", out)
        self.assertEqual(self.audit_actions()[-1][0], "restore")

    def test_backup_and_sidecar_are_private_from_the_start(self):
        old = os.umask(0o022)
        self.addCleanup(os.umask, old)
        seen = {}
        real = backup_mod._copy_db

        def spy(src, dst):
            real(src, dst)
            seen["tmp"] = stat.S_IMODE(os.stat(dst).st_mode)
        with mock.patch.object(backup_mod, "_copy_db", spy), mock.patch.object(backup_mod.os, "chmod", lambda *a: None):
            info = backup_mod.create_backup(self.ws / ".sentinel", self.home / "bk", audit=False)
        self.assertEqual(seen["tmp"], 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(info["path"]).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(info["path"] + ".sha256").st_mode), 0o600)

    def test_a_refused_export_backup_or_restore_is_audited(self):
        info = self.make()
        env = dict(self.env, SENTINEL_TASK_ID="t-1")
        for args, action in ((("backup",), "backup_refused"), (("audit", "export", "--out", "x.jsonl"), "audit_export_refused"),
                             (("backup", "restore", info["path"]), "restore_refused")):
            with self.subTest(action=action):
                code, out = self.cli(*args, env=env)
                self.assertEqual(code, 5, out)
                self.assertIn("E_ACTOR", out)
                self.assertEqual(self.audit_actions()[-1], (action, "E_ACTOR"))
        self.assertTrue(auditlog.verify_db(self.db)["ok"])


if __name__ == "__main__":
    unittest.main()
