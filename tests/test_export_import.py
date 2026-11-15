"""Phase E: run export and import (export_import.feature)."""
import hashlib
import io
import json
import os
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import yaml

from pe_helpers import PE, SLUG, git
from pb_helpers import PtyProc, CLI, CLI_ENV, run_plain
from errors import SentinelError
from engine import Engine

SECRET = "Pw-9f3kq2zz"


class Bundle(PE):
    def setUp(self):
        super().setUp()
        self.d = ["--dir", str(self.ws)]

    # ---- fixtures
    def completed(self, **kw):
        self.boot_ver(tier=3, repos=("backend",))
        self.change(("backend",))
        for c in self.cycles():
            self.eng.reg.add_trace_link(self.run_row()["id"], "cycle", c["id"], "file", self.BAL)
        assert self.verify()["exit"] == 0
        for t in self.new_tasks():
            self.eng.reg.update_row("tasks", t["id"], state="COMPLETED")
        self.eng.next_step(SLUG)
        assert self.state() == "COMPLETED"
        (self.ws / "backend" / ".env").write_text(f"DB_PASSWORD={SECRET}\n")

    def run_file(self, rel):
        return self.ws / ".sentinel" / "runs" / SLUG / rel

    def export_pty(self, *flags, slug=SLUG, answer="y", env=None):
        p = PtyProc(self.d + ["run", "export", slug, *flags], env)
        if "--yes" not in flags and p.wait_for("[y/N]", 10):
            p.send(answer + "\n")
        return p.finish()

    def bundle_path(self, slug=SLUG):
        return self.ws / f"{slug}.sentinel-run.tar.gz"

    def read_bundle(self, path=None):
        out = {}
        with tarfile.open(path or self.bundle_path(), "r:gz") as tar:
            for m in tar.getmembers():
                if m.isreg():
                    out[m.name] = tar.extractfile(m).read()
        return out

    def write_bundle(self, files, path, extra=None):
        with tarfile.open(path, "w:gz") as tar:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            for info, data in extra or []:
                tar.addfile(info, io.BytesIO(data) if data is not None else None)

    def fix_manifest(self, files):
        m = json.loads(files["manifest.json"])
        m["files"] = {k: {"sha256": hashlib.sha256(v).hexdigest(), "size": len(v)} for k, v in files.items() if k != "manifest.json"}
        files["manifest.json"] = json.dumps(m).encode()
        return files

    def second(self):
        """A second workspace: same config, repo backend with the same commit, empty registry."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ws = Path(tmp.name)
        (ws / "sentinel.config.yaml").write_text((self.ws / "sentinel.config.yaml").read_text())
        (ws / "backend").mkdir()
        git(ws / "backend", "init", "-q")
        (ws / "backend" / "README.md").write_text("hello\n")
        git(ws / "backend", "add", "-A")
        git(ws / "backend", "commit", "-q", "-m", "init")
        eng = Engine(ws / ".sentinel", ws, yaml.safe_load((ws / "sentinel.config.yaml").read_text()))
        self.addCleanup(eng.close)
        return ws, eng

    def import_pty(self, ws, bundle, env=None, flags=("--yes",)):
        p = PtyProc(["--dir", str(ws), "run", "import", str(bundle), *flags], env)
        return p.finish()

    # ---- export
    def test_AC_ART_03a_a_human_exports_a_run(self):
        self.completed()
        code, out = self.export_pty()
        self.assertEqual(code, 0, out)
        path = self.bundle_path()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        files = self.read_bundle()
        self.assertTrue({"manifest.json", "rows.json"} <= set(files))
        self.assertTrue(any(n.startswith("run/") for n in files))
        self.assertIn(f"shared/specs/{SLUG}/spec.md", files)
        self.assertTrue(any(n.startswith(f"shared/specs/{SLUG}/features/") for n in files))
        m = json.loads(files["manifest.json"])
        self.assertEqual((m["format"], m["slug"]), ("sentinel-run-bundle-v1", SLUG))
        self.assertTrue(m["sentinel_version"] and m["registry_schema_version"])
        for name, meta in m["files"].items():
            self.assertEqual((meta["sha256"], meta["size"]), (hashlib.sha256(files[name]).hexdigest(), len(files[name])))
        rows = json.loads(files["rows.json"])
        for t in ("runs", "run_repos", "artifacts", "approvals", "tasks", "task_deps", "cycles", "evidence", "findings", "trace_links",
                  "events", "audit", "config"):
            self.assertIn(t, rows)
        self.assertTrue([a for a in self.audit() if a["action"] == "run_exported" and a["reason"] == hashlib.sha256(path.read_bytes()).hexdigest()])

    def test_AC_ART_03b_secrets_and_qa_data_never_enter_the_bundle(self):
        rows = [("qa output", "output.log", f"DB_PASSWORD={SECRET}", SECRET), ("reviewer summary", "result.json", "token=ghp_abcdef123456", "ghp_abcdef123456"),
                ("brief", "brief.md", "jane.doe@corp-mail.com", "jane.doe@corp-mail.com"),
                ("decisions", None, "AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP")]
        for name, fname, text, secret in rows:
            with self.subTest(name=name):
                self.completed()
                tid = self.tasks_of()[0]["id"]
                target = self.run_file(f"tasks/{tid}/{fname}") if fname else self.run_file("decisions.md")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text + "\n")
                code, out = self.export_pty("--yes")
                self.assertEqual(code, 0, out)
                for fn, data in self.read_bundle().items():
                    self.assertNotIn(secret.encode(), data, fn)
                with tempfile.TemporaryDirectory() as d:
                    with tarfile.open(self.bundle_path()) as tar:
                        tar.extractall(d)
                    import scrub
                    self.assertEqual(scrub.check_paths([d], scrub.Scrubber(self.ws, scrub.env_values(self.ws))), {})
                self.bundle_path().unlink()
                self.reset_ws()

    def test_AC_ART_03b_event_payloads_and_evidence_output_are_scrubbed(self):
        self.completed()
        self.eng.reg.add_event(self.run_row()["id"], "task.waiting", "engine", {"q": f"mysql://qa:{SECRET}@10.0.0.5/leave"})
        e = self.vrows("test")[0]
        art = self.eng.reg.get_row("artifacts", e["output_artifact_id"])
        (self.ws / ".sentinel" / art["path"]).write_text(f"path {self.ws}/backend\n")
        with self.eng.reg.transaction():
            sha = hashlib.sha256((self.ws / ".sentinel" / art["path"]).read_bytes()).hexdigest()
            self.eng.reg._c.execute("UPDATE artifacts SET sha256=? WHERE id=?", (sha, art["id"]))
            self.eng.reg._c.execute("UPDATE evidence SET output_sha256=? WHERE id=?", (sha, e["id"]))
        code, out = self.export_pty("--yes")
        self.assertEqual(code, 0, out)
        files = self.read_bundle()
        blob = b"".join(files.values())
        self.assertNotIn(SECRET.encode(), blob)
        self.assertNotIn(str(self.ws).encode(), blob)

    def test_AC_ART_03c_files_with_secrets_or_qa_data_are_left_out(self):
        self.completed()
        for rel in (".sentinel/cache/qa/storage/leave_qa.sql", ".sentinel/cache/runs/leave-balance/live.log"):
            (self.ws / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.ws / rel).write_text("x\n")
        self.write_file(".sentinel/runs/leave-balance/.env.local", "A=1\n")
        code, out = self.export_pty("--yes")
        names = set(self.read_bundle())
        self.assertFalse([n for n in names if ".sentinel/cache" in n or n.endswith((".env", "sentinel.db", "server.json")) or "/.env" in n])
        self.assertFalse([n for n in names if n.startswith("run/") and "other" in n])

    def test_AC_ART_03d_binary_files_are_excluded_and_listed(self):
        self.completed()
        tid = self.tasks_of()[0]["id"]
        png = self.run_file(f"tasks/{tid}/screen.png")
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")
        self.export_pty("--yes")
        files = self.read_bundle()
        self.assertNotIn(f"run/tasks/{tid}/screen.png", files)
        m = json.loads(files["manifest.json"])
        self.assertIn({"path": f"run/tasks/{tid}/screen.png", "reason": "binary"}, m["excluded"])

    def test_AC_ART_03e_scrubbed_artifacts_carry_the_scrubbed_hash(self):
        self.completed()
        e = self.vrows("test")[0]
        art = self.eng.reg.get_row("artifacts", e["output_artifact_id"])
        p = self.ws / ".sentinel" / art["path"]
        p.write_text("ran in /home/alice/work\n")
        orig = hashlib.sha256(p.read_bytes()).hexdigest()
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("UPDATE artifacts SET sha256=? WHERE id=?", (orig, art["id"]))
            self.eng.reg._c.execute("UPDATE evidence SET output_sha256=? WHERE id=?", (orig, e["id"]))
        self.export_pty("--yes")
        files = self.read_bundle()
        rows = json.loads(files["rows.json"])
        a = [x for x in rows["artifacts"] if x["id"] == art["id"]][0]
        rel = "run/" + art["path"].split("runs/leave-balance/", 1)[1]
        self.assertEqual((a["scrubbed"], a["original_sha256"], a["sha256"]), (1, orig, hashlib.sha256(files[rel]).hexdigest()))
        self.assertEqual(json.loads(files["manifest.json"])["files"][rel]["sha256"], a["sha256"])

    def test_AC_ART_03f_an_approved_spec_that_scrubbing_would_change_stops_the_export(self):
        self.completed()
        p = self.sdir() / "spec.md"
        p.write_text(p.read_text() + "\nkey AKIAABCDEFGHIJKLMNOP\n")
        code, out = self.export_pty("--yes")
        self.assertEqual(code, 5, out)
        self.assertIn("E_POLICY", out)
        self.assertIn("approval hash would change", out)
        self.assertFalse(self.bundle_path().exists())
        self.assertFalse(list(self.ws.glob(".*.tmp")))

    def test_AC_ART_03g_who_may_export(self):
        self.completed()
        code, out = self.export_pty("--yes")
        self.assertEqual(code, 0, out)
        self.assertNotIn("[y/N]", out)
        self.bundle_path().unlink()
        code, out = run_plain(self.d + ["run", "export", SLUG, "--yes"])
        self.assertEqual(code, 5)
        self.assertIn("E_NOT_TTY", out)
        code, out = self.export_pty("--yes", env={**CLI_ENV, "SENTINEL_TASK_ID": "t-000000000000"})
        self.assertEqual(code, 5)
        self.assertIn("E_ACTOR", out)
        self.assertFalse(self.bundle_path().exists())

    def test_AC_ART_03h_export_requests_that_are_refused(self):
        self.completed()
        self.cli("run", "new", "old-fix", "--tier", "2")
        self.bundle_path().write_text("x")
        for slug, err in [("no-such-run", "E_NOT_FOUND"), ("old-fix", "E_TRANSITION"), (SLUG, "E_PRECONDITION")]:
            with self.subTest(slug=slug):
                code, out = self.export_pty("--yes", slug=slug)
                self.assertEqual(code, 5, out)
                self.assertIn(err, out)
        self.assertEqual(self.bundle_path().read_text(), "x")

    def test_AC_ART_03i_a_run_with_a_task_in_progress_is_not_exported(self):
        self.completed()
        t = self.tasks_of()[0]
        self.set_state("EXECUTING")
        self.eng.reg.update_row("tasks", t["id"], state="RUNNING")
        code, out = self.export_pty("--yes")
        self.assertEqual(code, 5, out)
        self.assertIn("E_PRECONDITION", out)
        self.assertIn(t["id"], out)

    # ---- import
    def exported(self):
        self.completed()
        code, out = self.export_pty("--yes")
        assert code == 0, out
        return self.bundle_path()

    def test_AC_ART_03j_a_bundle_is_imported_on_another_machine(self):
        bundle = self.exported()
        ws, eng = self.second()
        code, out = self.import_pty(ws, bundle)
        self.assertEqual(code, 0, out)
        run = eng.reg.get_run(SLUG)
        self.assertEqual((run["state"], run["acceptance_status"]), ("COMPLETED", "accepted"))
        src = {t: len(self.eng.reg.rows(t, run_id=self.run_row()["id"])) for t in ("tasks", "cycles", "evidence", "approvals", "findings", "artifacts")}
        got = {t: len(eng.reg.rows(t, run_id=run["id"])) for t in src}
        self.assertEqual(got, src)
        spec = ws / ".sentinel/shared/specs" / SLUG / "spec.md"
        self.assertEqual(spec.read_bytes(), (self.sdir() / "spec.md").read_bytes())
        for gate, kind in (("specification", "spec"), ("gherkin", "gherkin")):
            ap = eng._latest_approval(run, gate, "APPROVED")
            self.assertEqual(eng._current_hash(SLUG, kind), ap["sha256"])
        self.assertEqual(len(eng.reg.list_events(run["id"], "run.imported")), 1)
        self.assertTrue([a for a in eng.reg.audit_rows() if a["action"] == "run_imported"
                         and a["after_sha"] == hashlib.sha256(bundle.read_bytes()).hexdigest()])
        orig = [e for e in eng.reg.list_events(run["id"]) if e["type"] == "run.state_changed"][0]
        self.assertIn("original_event_id", orig["payload"])
        self.assertEqual(eng.compute_acceptance(SLUG)["status"], "accepted")

    def test_AC_ART_03k_a_tampered_bundle_is_refused(self):
        bundle = self.exported()
        orig = self.read_bundle()
        rows = json.loads(orig["rows.json"])
        rows["runs"][0]["acceptance_status"] = "rejected"
        cases = [("report byte", lambda f: f.update({"run/report.json": f["run/report.json"] + b" "}), "E_INTEGRITY", "run/report.json"),
                 ("rows", lambda f: f.update({"rows.json": json.dumps(rows).encode()}), "E_INTEGRITY", "rows.json"),
                 ("spec", lambda f: f.update({f"shared/specs/{SLUG}/spec.md": b"other"}), "E_INTEGRITY", "spec.md"),
                 ("removed", lambda f: f.pop("run/report.md"), "E_INTEGRITY", "run/report.md"),
                 ("added", lambda f: f.update({"run/extra.txt": b"x"}), "E_INTEGRITY", "run/extra.txt"),
                 ("no manifest", lambda f: f.pop("manifest.json"), "E_VALIDATION", "manifest.json"),
                 ("format", lambda f: f.update({"manifest.json": json.dumps({**json.loads(f["manifest.json"]), "format": "sentinel-run-bundle-v9"}).encode()}),
                  "E_VALIDATION", "format")]
        for name, change, err, what in cases:
            with self.subTest(case=name):
                files = dict(orig)
                change(files)
                bad = self.ws / "bad.tar.gz"
                self.write_bundle(files, bad)
                ws, eng = self.second()
                code, out = self.import_pty(ws, bad)
                self.assertEqual(code, 5, out)
                self.assertIn(err, out)
                self.assertIn(what, out)
                self.assertIsNone(eng.reg.get_run(SLUG))
                self.assertFalse((ws / ".sentinel/runs" / SLUG).exists() or (ws / ".sentinel/shared/specs" / SLUG).exists())

    def test_AC_ART_03l_unsafe_archive_entries_are_refused(self):
        self.exported()
        orig = self.read_bundle()
        sym = tarfile.TarInfo("run/link")
        sym.type, sym.linkname = tarfile.SYMTYPE, "/etc/passwd"
        hard = tarfile.TarInfo("run/hard")
        hard.type, hard.linkname = tarfile.LNKTYPE, "rows.json"
        for name, files, extra in [("dotdot", {**orig, "../../.bashrc": b"x"}, None), ("absolute", {**orig, "/etc/cron.d/x": b"x"}, None),
                                   ("symlink", dict(orig), [(sym, None)]), ("hardlink", dict(orig), [(hard, None)])]:
            with self.subTest(entry=name):
                files = self.fix_manifest(dict(files)) if name in ("dotdot", "absolute") else files
                bad = self.ws / "bad.tar.gz"
                self.write_bundle(files, bad, extra)
                ws, eng = self.second()
                code, out = self.import_pty(ws, bad)
                self.assertEqual(code, 5, out)
                self.assertIn("E_VALIDATION", out)
                self.assertIsNone(eng.reg.get_run(SLUG))
                self.assertFalse((ws.parent / ".bashrc").exists())
                self.assertEqual(os.listdir(ws / ".sentinel" / "tmp") if (ws / ".sentinel" / "tmp").exists() else [], [])

    def test_AC_ART_03n_rows_of_another_run_are_never_imported(self):
        bundle = self.exported()
        orig = self.read_bundle()
        ws, eng = self.second()
        eng.create_run("victim", "human", type="feature", baseline={"backend": "abc"}, request="x")
        victim = eng.reg.get_run("victim")
        victim_task = eng.create_task("victim", "docs", "docs", repos=["backend"], write=["backend/docs/**"])["id"]
        rows = json.loads(orig["rows.json"])
        forged = {"id": "a-forged000001", "run_id": victim["id"], "gate": "security", "state": "APPROVED", "decision": "approve",
                  "approver": "attacker", "version": 1}
        t0 = rows["tasks"][0]["id"]

        def forge(key):
            def go(r):
                if key == "approval of another run":
                    r["approvals"].append(forged)
                elif key == "dependency on another run":
                    r["task_deps"].append({"task_id": t0, "depends_on": "t-foreign00001"})
                elif key == "other slug":
                    r["runs"][0]["slug"] = "victim"
                elif key == "audit of another run":
                    r["audit"].append({"actor": "x", "channel": "tty", "action": "resolve", "target": "victim/security",
                                       "before_sha": None, "after_sha": None, "at": "2026-01-01T00:00:00Z", "reason": "approve"})
                elif key == "task of another run":
                    r["events"].append({**r["events"][0], "task_id": victim_task})
                elif key == "artifact outside the run":
                    r["artifacts"][0]["path"] = "../../etc/passwd"
                elif key == "two runs":
                    r["runs"].append(dict(r["runs"][0]))
            return go
        for key in ("approval of another run", "dependency on another run", "other slug", "audit of another run",
                    "task of another run", "artifact outside the run", "two runs"):
            with self.subTest(case=key):
                doc = json.loads(orig["rows.json"])
                forge(key)(doc)
                files = dict(orig)
                files["rows.json"] = json.dumps(doc).encode()
                bad = self.ws / "bad.tar.gz"
                self.write_bundle(self.fix_manifest(files), bad)
                code, out = self.import_pty(ws, bad)
                self.assertEqual(code, 5, out)
                self.assertIn("E_VALIDATION", out)
                self.assertEqual(eng.reg.rows("approvals", run_id=victim["id"]), [])
                self.assertIsNone(eng.reg.get_run(SLUG))
                self.assertEqual([r["slug"] for r in eng.reg.rows("runs")], ["victim"])

    def test_import_refuses_audit_values_that_are_not_text(self):
        self.exported()
        orig = self.read_bundle()
        ws, eng = self.second()
        for field, value in (("reason", 12345), ("at", 1700000000), ("actor", ["x"])):
            with self.subTest(field=field):
                doc = json.loads(orig["rows.json"])
                doc["audit"].append({"actor": "x", "channel": "tty", "action": "approve", "target": f"{SLUG}/spec",
                                     "before_sha": None, "after_sha": None, "at": "2026-01-01T00:00:00Z", "reason": None, field: value})
                files = dict(orig)
                files["rows.json"] = json.dumps(doc).encode()
                bad = self.ws / "bad.tar.gz"
                self.write_bundle(self.fix_manifest(files), bad)
                code, out = self.import_pty(ws, bad)
                self.assertEqual(code, 5, out)
                self.assertIn("E_VALIDATION", out)
                self.assertIsNone(eng.reg.get_run(SLUG))

    def test_imported_audit_rows_are_marked_as_imported(self):
        bundle = self.exported()
        orig_rows = json.loads(self.read_bundle()["rows.json"])["audit"]
        self.assertTrue(orig_rows)
        ws, eng = self.second()
        code, out = self.import_pty(ws, bundle)
        self.assertEqual(code, 0, out)
        import auditlog
        sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
        imported = [a for a in eng.reg.audit_rows() if a["channel"] == "import"]
        self.assertEqual(len(imported), len(orig_rows))
        for a, o in zip(imported, orig_rows):
            note = json.loads(a["reason"])
            self.assertEqual(note["imported_from"], sha)
            self.assertEqual(note["orig"], {"actor": o["actor"], "channel": o["channel"], "at": o["at"]})
            self.assertEqual((a["action"], a["target"]), (o["action"], o["target"]))
        self.assertEqual(auditlog.verify_db(ws / ".sentinel" / "sentinel.db")["imported"], len(orig_rows))
        out_file = ws / "a.jsonl"
        r = subprocess.run(CLI + ["--dir", str(ws), "audit", "export", "--out", str(out_file)], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, env=CLI_ENV, cwd=ws)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = [json.loads(x) for x in out_file.read_text().splitlines()[1:]]
        self.assertEqual(len([x for x in rows if x.get("imported")]), len(orig_rows))

    def test_AC_ART_03o_import_caps_and_unreadable_files_are_validation_errors(self):
        import gzip
        self.exported()
        orig = self.read_bundle()
        ws, eng = self.second()
        many = self.ws / "many.tar.gz"
        self.write_bundle({**orig, **{f"run/pad/{i}.txt": b"x" for i in range(10001)}}, many)
        huge = self.ws / "huge.tar.gz"
        info = tarfile.TarInfo("run/big.bin")
        info.size = 300 << 20
        with gzip.open(huge, "wb") as fh:
            fh.write(info.tobuf())
        locked = self.ws / "locked.tar.gz"
        self.write_bundle(orig, locked)
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o600)
        garbage = self.ws / "garbage.tar.gz"
        garbage.write_bytes(b"not gzip at all")
        for name, path in [("member count", many), ("declared size", huge), ("unreadable", locked), ("not an archive", garbage)]:
            with self.subTest(case=name):
                code, out = self.import_pty(ws, path)
                self.assertEqual(code, 5, out)
                self.assertIn("E_VALIDATION", out)
                self.assertNotIn("Traceback", out)
        self.assertEqual(os.listdir(ws / ".sentinel" / "tmp"), [])

    def test_AC_ART_03p_refused_imports_are_audited(self):
        bundle = self.exported()
        ws, eng = self.second()
        code, out = run_plain(["--dir", str(ws), "run", "import", str(bundle)])
        self.assertEqual(code, 5, out)
        self.assertIn("E_NOT_TTY", out)
        bad = self.ws / "bad.tar.gz"
        bad.write_bytes(b"not gzip at all")
        self.assertEqual(self.import_pty(ws, bad)[0], 5)
        refused = [(a["action"], a["target"], a["reason"]) for a in eng.reg.audit_rows() if a["action"].endswith("_refused")]
        self.assertEqual(refused, [("run_import_refused", bundle.name, "E_NOT_TTY"), ("run_import_refused", "bad.tar.gz", "E_VALIDATION")])

    def test_AC_ART_03m_an_existing_slug_is_never_overwritten(self):
        bundle = self.exported()
        for existing in ("row", "run folder", "shared folder"):
            with self.subTest(existing=existing):
                ws, eng = self.second()
                if existing == "row":
                    eng.create_run(SLUG, "orchestrator", type="feature", baseline={})
                elif existing == "run folder":
                    (ws / ".sentinel/runs" / SLUG).mkdir(parents=True)
                    (ws / ".sentinel/runs" / SLUG / "keep.txt").write_text("keep")
                else:
                    (ws / ".sentinel/shared/specs" / SLUG).mkdir(parents=True)
                    (ws / ".sentinel/shared/specs" / SLUG / "keep.txt").write_text("keep")
                code, out = self.import_pty(ws, bundle)
                self.assertEqual(code, 5, out)
                self.assertIn("E_PRECONDITION", out)
                self.assertIn("slug exists", out)
                if existing != "row":
                    d = ws / ".sentinel" / ("runs" if existing == "run folder" else "shared/specs") / SLUG
                    self.assertEqual(os.listdir(d), ["keep.txt"])

    def test_AC_ART_03n_who_may_import(self):
        bundle = self.exported()
        ws, eng = self.second()
        code, out = run_plain(["--dir", str(ws), "run", "import", str(bundle), "--yes"])
        self.assertEqual(code, 5)
        self.assertIn("E_NOT_TTY", out)
        code, out = self.import_pty(ws, bundle, env={**CLI_ENV, "SENTINEL_TASK_ID": "t-000000000000"})
        self.assertEqual(code, 5)
        self.assertIn("E_ACTOR", out)
        self.assertIsNone(eng.reg.get_run(SLUG))

    def test_AC_ART_03o_a_bundle_from_a_newer_schema_is_refused(self):
        self.exported()
        files = self.read_bundle()
        m = json.loads(files["manifest.json"])
        m["registry_schema_version"] = 999
        files["manifest.json"] = json.dumps(m).encode()
        bad = self.ws / "new.tar.gz"
        self.write_bundle(files, bad)
        ws, eng = self.second()
        code, out = self.import_pty(ws, bad)
        self.assertEqual(code, 5, out)
        self.assertIn("E_VALIDATION", out)
        self.assertIn("upgrade Sentinel", out)

    def test_AC_ART_03p_a_failed_registry_write_leaves_nothing_behind(self):
        bundle = self.exported()
        ws, eng = self.second()
        real = eng._insert_raw
        count = {"n": 0}

        def flaky(table, row):
            count["n"] += 1
            if count["n"] > 10:
                raise sqlite3.OperationalError("disk I/O error")
            return real(table, row)
        with mock.patch.object(eng, "_insert_raw", flaky):
            with self.assertRaises(SentinelError) as c:
                eng.import_run(bundle)
        self.assertEqual(c.exception.exit_code, 1)
        self.assertIsNone(eng.reg.get_run(SLUG))
        self.assertFalse((ws / ".sentinel/runs" / SLUG).exists() or (ws / ".sentinel/shared/specs" / SLUG).exists())

    def test_AC_ART_03q_two_imports_of_one_bundle(self):
        bundle = self.exported()
        ws, eng = self.second()
        procs = [PtyProc(["--dir", str(ws), "run", "import", str(bundle), "--yes"]) for _ in range(2)]
        codes = sorted(p.finish()[0] for p in procs)
        self.assertEqual(codes, [0, 5])
        run = eng.reg.get_run(SLUG)
        self.assertEqual(len(eng.reg.rows("tasks", run_id=run["id"])), len(self.tasks_of()))

    # ---- an imported run in progress
    def executing(self):
        self.boot_ver(tier=3, repos=("backend",))
        self.set_state("EXECUTING")
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("UPDATE cycles SET state='PLANNED', tests=NULL")
            self.eng.reg._c.execute("DELETE FROM tasks")
        self.eng.bookkeep(SLUG)
        code, out = self.export_pty("--yes")
        assert code == 0, out

    def test_AC_ORC_07g_an_imported_run_in_progress_resumes(self):
        self.executing()
        before = self.eng.next_step(SLUG)
        ws, eng = self.second()
        base = self.eng.reg.run_repos(self.run_row()["id"])[0]["baseline_sha"]
        git(ws / "backend", "fetch", "-q", str(self.ws / "backend"))
        git(ws / "backend", "update-ref", "refs/heads/seed", base)
        code, out = self.import_pty(ws, self.bundle_path())
        self.assertEqual(code, 0, out)
        self.assertTrue((ws / ".sentinel/shared/locks" / SLUG).exists())
        after = eng.next_step(SLUG)
        self.assertEqual({k: after[k] for k in ("kind", "task", "role")}, {k: before[k] for k in ("kind", "task", "role")})

    def test_AC_ORC_07h_an_imported_run_whose_baseline_is_missing_is_blocked(self):
        self.executing()
        ws, eng = self.second()
        code, out = self.import_pty(ws, self.bundle_path())
        self.assertEqual(code, 0, out)
        step = eng.next_step(SLUG)
        self.assertEqual(eng.reg.get_run(SLUG)["state"], "BLOCKED")
        self.assertEqual(step["kind"], "human")
        self.assertIn("backend", step["reason"])
        self.assertIn("baseline commit", step["reason"])


if __name__ == "__main__":
    unittest.main()
