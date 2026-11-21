"""Knowledge base phase C: the kb_jobs queue, the complete_run hook and the background worker."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from pe_helpers import PE, SLUG
from pc_helpers import GIT_ENV

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import kb_worker  # noqa: E402
import knowledge  # noqa: E402
from registry import Registry  # noqa: E402


def sh(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, env=GIT_ENV)


class Queue(PE):
    def test_the_jobs_table_exists_and_a_job_is_queued_once_per_run(self):
        reg = self.eng.reg
        self.assertGreaterEqual(Registry.LATEST, 12)
        a = kb_worker.enqueue_harvest(reg, "one")
        self.assertEqual(kb_worker.enqueue_harvest(reg, "one"), a)
        job = reg.get_row("kb_jobs", a)
        self.assertEqual((job["kind"], job["run_slug"], job["state"], job["attempts"]), ("kb_harvest", "one", "queued", 0))
        self.assertNotEqual(kb_worker.enqueue_harvest(reg, "two"), a)
        self.assertEqual(kb_worker.job_summary(reg)["queued"], 2)

    def test_complete_run_enqueues_and_spawns(self):
        with mock.patch.object(kb_worker, "spawn_worker") as spawn:
            self.to_completed()
        spawn.assert_called_once_with(self.ws)
        jobs = self.eng.reg.rows("kb_jobs")
        self.assertEqual([(j["run_slug"], j["state"]) for j in jobs], [(SLUG, "queued")])

    def test_complete_run_skips_when_knowledge_is_disabled(self):
        with mock.patch.object(kb_worker, "spawn_worker") as spawn:
            self.to_completed(knowledge={"enabled": False})
        spawn.assert_not_called()
        self.assertEqual(self.eng.reg.rows("kb_jobs"), [])

    def test_a_raising_spawn_does_not_break_completion(self):
        with mock.patch.object(kb_worker, "spawn_worker", side_effect=RuntimeError("no fork")):
            self.to_completed()
        self.assertEqual(self.state(), "COMPLETED")
        with mock.patch.object(kb_worker, "enqueue_harvest", side_effect=RuntimeError("db gone")):
            self.eng._queue_knowledge(SLUG)

    def test_spawn_worker_never_raises(self):
        self.to_completed()
        with mock.patch.dict(os.environ, {"SENTINEL_KB_NO_SPAWN": ""}):
            with mock.patch("subprocess.Popen", side_effect=OSError("denied")):
                self.assertIsNone(kb_worker.spawn_worker(self.ws))
            with mock.patch("subprocess.Popen") as popen:
                popen.return_value.pid = 4242
                self.assertEqual(kb_worker.spawn_worker(self.ws), 4242)
            kw = popen.call_args.kwargs
            self.assertTrue(kw["start_new_session"])
            self.assertEqual(kw["stdin"], subprocess.DEVNULL)
            self.assertEqual(popen.call_args.args[0][-2:], ["kb", "worker"])
            self.assertTrue((self.ws / ".sentinel" / kb_worker.LOG_FILE).exists())

    def test_single_instance_guard(self):
        state = self.ws / ".sentinel"
        self.assertTrue(kb_worker.acquire_instance(state))
        self.assertFalse(kb_worker.acquire_instance(state))
        kb_worker.release_instance(state)
        self.assertFalse((state / kb_worker.PID_FILE).exists())
        (state / kb_worker.PID_FILE).write_text("999999 1\n")  # a dead process
        self.assertTrue(kb_worker.acquire_instance(state))
        self.assertEqual((state / kb_worker.PID_FILE).read_text().split()[0], str(os.getpid()))
        kb_worker.release_instance(state)

    def test_job_summary_from_the_database_file(self):
        self.to_completed()
        db = self.ws / ".sentinel" / "sentinel.db"
        self.assertEqual(kb_worker.job_summary_from_db(db)["queued"], 1)
        from apiserver import readroutes
        out = readroutes._knowledge_jobs([("p", None, {}, self.ws / ".sentinel"), ("q", None, {}, self.ws / "nowhere")])
        self.assertEqual(list(out), ["p"])
        self.assertIsNone(kb_worker.job_summary_from_db(self.ws / "missing.db"))

    def test_a_second_worker_exits_while_one_is_live(self):
        self.to_completed()
        state = self.ws / ".sentinel"
        self.assertTrue(kb_worker.acquire_instance(state))
        self.assertIsNone(kb_worker.run_worker(self.ws))
        kb_worker.release_instance(state)


class Worker(PE):
    """A completed run whose shared folder is a clone of a local bare repo."""

    def setUp(self):
        super().setUp()
        self.patch = mock.patch.object(kb_worker, "spawn_worker")
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp2.cleanup)

    def boot_remote(self, **cfg):
        self.to_completed(**cfg)
        base = Path(self.tmp2.name)
        self.bare = base / "shared.git"
        sh(base, "init", "-q", "--bare", "-b", "main", str(self.bare))
        seed = base / "seed"
        sh(base, "clone", "-q", str(self.bare), str(seed))
        sh(seed, "checkout", "-q", "-b", "main")
        (seed / "invariants.md").write_text("rules\n")
        sh(seed, "add", "-A")
        sh(seed, "commit", "-q", "-m", "init")
        sh(seed, "push", "-q", "origin", "main")
        shared = self.ws / ".sentinel" / "shared"
        moved = base / "moved"
        shared.rename(moved)
        sh(base, "clone", "-q", str(self.bare), str(shared))
        sh(shared, "checkout", "-q", "main")
        for p in (moved / "specs").rglob("*"):
            if p.is_file():
                t = shared / p.relative_to(moved)
                t.parent.mkdir(parents=True, exist_ok=True)
                t.write_bytes(p.read_bytes())
        self.shared = shared
        self.set_state_cfg(shared_repo=str(self.bare), shared_ref="main", shared_mode=None)
        return shared

    def set_state_cfg(self, **state):
        cfg = yaml.safe_load((self.ws / "sentinel.config.yaml").read_text())
        merged = {**cfg["state"], **state}
        cfg["state"] = {k: v for k, v in merged.items() if v is not None}
        (self.ws / "sentinel.config.yaml").write_text(yaml.safe_dump(cfg))

    def set_kb(self, **kb):
        cfg = yaml.safe_load((self.ws / "sentinel.config.yaml").read_text())
        cfg["knowledge"] = {**(cfg.get("knowledge") or {}), **kb}
        (self.ws / "sentinel.config.yaml").write_text(yaml.safe_dump(cfg))

    def job(self):
        return self.eng.reg.rows("kb_jobs")[-1]

    def remote_files(self):
        return sh(self.bare, "ls-tree", "-r", "--name-only", "main").stdout.split()

    def run_w(self):
        return kb_worker.run_worker(self.ws, sleep=lambda s: None)

    def test_the_worker_harvests_a_run_end_to_end(self):
        self.boot_remote()
        sh(self.ws / "backend", "add", "-A")
        sh(self.ws / "backend", "commit", "-q", "-m", "Add A (#7)")
        sha = sh(self.ws / "backend", "rev-parse", "HEAD").stdout.strip()
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("UPDATE run_repos SET final_sha=? WHERE repo_id='backend'", (sha,))
        (self.shared / "specs" / "scratch.txt").write_text("dirty\n")
        self.assertEqual(self.run_w(), 1)
        job = self.job()
        self.assertEqual((job["state"], job["attempts"]), ("done", 1))
        files = self.remote_files()
        rec = [f for f in files if f.endswith(f"run-{SLUG}.md")]
        self.assertEqual(len(rec), 1, files)
        meta, body = knowledge.read_record(self.shared / rec[0])
        self.assertEqual((meta["provenance"], meta["run"], meta["key"]), ("verified", SLUG, f"run-{SLUG}"))
        self.assertEqual(meta["spec"], f"specs/{SLUG}/spec.md")
        self.assertTrue(meta["features"] and all(f.startswith(f"specs/{SLUG}/features/") for f in meta["features"]))
        shas = {r["repo_id"]: r["final_sha"] for r in self.eng.reg.run_repos(self.run_row()["id"])}
        self.assertEqual(meta["final_shas"], shas)
        self.assertIn("backend/src/main/A.java", meta["files"])
        self.assertEqual({r["repo"] for r in meta["reached"]}, {"backend", "frontend"})
        self.assertIn("knowledge/index.json", files)
        self.assertIn(f"run-{SLUG}", knowledge.read_index(self.shared))
        # only knowledge/ was committed: the dirty spec files stay out of the remote
        self.assertTrue(all(f.startswith("knowledge/") or f == "invariants.md" for f in files), files)
        self.assertFalse(sh(self.shared, "status", "--porcelain", "--", "knowledge").stdout.strip())
        self.assertIn("specs/", sh(self.shared, "status", "--porcelain").stdout)
        self.assertEqual(sh(self.shared, "ls-remote", "origin", "refs/sentinel/locks/knowledge").stdout.strip(), "")

    def test_only_knowledge_paths_are_committed_with_other_files_staged(self):
        self.boot_remote()
        (self.shared / "invariants.md").write_text("changed\n")
        (self.shared / "other.md").write_text("new\n")
        sh(self.shared, "add", "other.md")
        self.run_w()
        self.assertEqual(self.job()["state"], "done")
        changed = sh(self.shared, "show", "--name-only", "--format=", "HEAD").stdout.split()
        self.assertTrue(changed and all(c.startswith("knowledge/") for c in changed), changed)
        self.assertNotIn("other.md", self.remote_files())

    def test_unpushed_non_knowledge_commits_are_never_published(self):
        self.boot_remote()
        before = sh(self.bare, "rev-parse", "main").stdout
        (self.shared / "invariants.md").write_text("unapproved rule\n")
        sh(self.shared, "add", "invariants.md")
        sh(self.shared, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "local only")
        self.run_w()
        self.assertEqual(self.job()["state"], "done")
        self.assertEqual(sh(self.bare, "rev-parse", "main").stdout, before)
        self.assertIn("knowledge/", sh(self.shared, "show", "--name-only", "--format=", "HEAD").stdout)

    def test_no_auto_push_commits_locally_only(self):
        self.boot_remote()
        self.set_kb(auto_push=False)
        before = sh(self.bare, "rev-parse", "main").stdout
        self.run_w()
        self.assertEqual(self.job()["state"], "done")
        self.assertEqual(sh(self.bare, "rev-parse", "main").stdout, before)
        self.assertIn("knowledge/", sh(self.shared, "show", "--name-only", "--format=", "HEAD").stdout)

    def test_a_scrub_failure_pushes_nothing_and_notifies(self):
        self.boot_remote()
        before = sh(self.bare, "rev-parse", "main").stdout
        fake = {str(self.shared / "knowledge" / "x.md"): ["email"]}
        with mock.patch("scrub.check_paths", return_value=fake):
            self.run_w()
        job = self.job()
        self.assertEqual((job["state"], job["attempts"]), ("failed", 1))
        self.assertIn("scrub check failed", job["error"])
        self.assertEqual(sh(self.bare, "rev-parse", "main").stdout, before)
        self.assertEqual(sh(self.shared, "status", "--porcelain", "--", "knowledge").stdout.strip(), "")
        self.assertEqual(len(self.events("knowledge.failed")), 1)

    def test_retry_then_failed_with_a_notification(self):
        self.boot_remote()
        sleeps = []
        with mock.patch.object(kb_worker, "process_job", side_effect=RuntimeError("remote down")) as proc:
            kb_worker.run_worker(self.ws, sleep=sleeps.append)
        self.assertEqual(proc.call_count, 3)
        self.assertEqual(sleeps, list(kb_worker.BACKOFF_SECONDS))
        job = self.job()
        self.assertEqual((job["state"], job["attempts"], job["error"]), ("failed", 3, "remote down"))
        ev = self.events("knowledge.failed")
        self.assertEqual(len(ev), 1)
        import notifications
        self.assertEqual(notifications.rule("knowledge.failed", ev[0]["payload"], SLUG)[:2], ("warning", "Knowledge harvest failed"))

    def test_a_job_that_fails_once_then_succeeds(self):
        self.boot_remote()
        real = kb_worker.process_job
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("blip")
            return real(*a, **k)

        with mock.patch.object(kb_worker, "process_job", side_effect=flaky):
            self.run_w()
        self.assertEqual((self.job()["state"], self.job()["attempts"]), ("done", 2))

    def test_local_shared_mode_just_writes_files(self):
        self.to_completed()
        self.run_w()
        self.assertEqual(self.job()["state"], "done")
        shared = self.ws / ".sentinel" / "shared"
        self.assertTrue(list((shared / "knowledge").rglob(f"run-{SLUG}.md")))

    def test_a_job_left_running_by_a_dead_worker_is_resumed(self):
        self.to_completed()
        self.eng.reg.update_row("kb_jobs", self.job()["id"], state="running", attempts=1)
        self.run_w()
        self.assertEqual((self.job()["state"], self.job()["attempts"]), ("done", 2))

    def test_kb_status_json_reports_the_jobs(self):
        self.to_completed()
        self.run_w()
        script = Path(kb_worker.__file__).parent / "sentinel.py"
        out = subprocess.run([sys.executable, str(script), "--dir", str(self.ws), "kb", "status", "--json"],
                             capture_output=True, text=True, env=GIT_ENV)
        self.assertEqual(out.returncode, 0, out.stderr)
        jobs = json.loads(out.stdout)["jobs"]
        self.assertEqual((jobs["queued"], jobs["last_success"]["run"], jobs["last_failure"]), (0, SLUG, None))


if __name__ == "__main__":
    unittest.main()
