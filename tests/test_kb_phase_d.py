"""Tests for Knowledge base Phase D: catch-up ingest on pull, CI template, prompt injection."""
import argparse
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

import kb_context  # noqa: E402
import kb_worker  # noqa: E402
import knowledge  # noqa: E402
import sentinel  # noqa: E402
from shared import Shared  # noqa: E402


def sh(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, env=GIT_ENV)


class TestKBPhaseD(PE):
    def setUp(self):
        super().setUp()
        self.spawn_patch = mock.patch.object(kb_worker, "spawn_worker")
        self.spawn_patch.start()
        self.addCleanup(self.spawn_patch.stop)
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
        (seed / "invariants.md").write_text("invariants rule\n")
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

    def remote_files(self):
        return sh(self.bare, "ls-tree", "-r", "--name-only", "main").stdout.split()

    # ---- 1. Sync pull enqueues refresh and dedupes
    def test_sync_pull_enqueues_one_refresh_job_and_dedupes(self):
        self.boot_remote()
        # Clear existing jobs from boot_remote
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("DELETE FROM kb_jobs")
        self.assertEqual(self.eng.reg.rows("kb_jobs"), [])

        cfg = yaml.safe_load((self.ws / "sentinel.config.yaml").read_text())
        shared = Shared(self.ws, cfg)
        shared.pull()

        jobs = self.eng.reg.rows("kb_jobs", kind="refresh")
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual((job["kind"], job["run_slug"], job["state"], job["attempts"]),
                         ("refresh", None, "queued", 0))

        # Pulling a second time dedupes: still only 1 queued refresh job
        shared.pull()
        jobs_after = self.eng.reg.rows("kb_jobs", kind="refresh")
        self.assertEqual(len(jobs_after), 1)
        self.assertEqual(jobs_after[0]["id"], job["id"])

    # ---- 2. Pull succeeds when enqueue raises
    def test_pull_succeeds_when_enqueue_raises(self):
        self.boot_remote()
        cfg = yaml.safe_load((self.ws / "sentinel.config.yaml").read_text())
        shared = Shared(self.ws, cfg)
        with mock.patch.object(kb_worker, "enqueue_refresh", side_effect=RuntimeError("queue broken")):
            # Pull must never fail or slow down because of knowledge
            shared.pull()

    # ---- 3. Refresh job runs ingest + publish
    def test_refresh_job_runs_ingest_and_publish(self):
        self.boot_remote()
        # Add a commit on backend repo
        sh(self.ws / "backend", "add", "-A")
        sh(self.ws / "backend", "commit", "-q", "-m", "Refresh feature (#99)")

        # Clear existing harvest jobs and enqueue a refresh job
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("DELETE FROM kb_jobs")
        job_id = kb_worker.enqueue_refresh(self.eng.reg)
        self.assertIsNotNone(job_id)

        # Run the background worker
        handled = kb_worker.run_worker(self.ws, sleep=lambda s: None)
        self.assertEqual(handled, 1)

        job = self.eng.reg.get_row("kb_jobs", job_id)
        self.assertEqual((job["state"], job["attempts"]), ("done", 1))

        # Changes were ingested and published to the remote
        files = self.remote_files()
        self.assertIn("knowledge/index.json", files)
        rec = [f for f in files if "pr-99.md" in f or "p-" in f]
        self.assertTrue(len(rec) > 0, f"Expected change record in {files}")

    # ---- 4. kb ingest --publish publishes only knowledge paths
    def test_kb_ingest_publish_publishes_only_knowledge_paths(self):
        self.boot_remote()
        # Add a change to backend
        sh(self.ws / "backend", "add", "-A")
        sh(self.ws / "backend", "commit", "-q", "-m", "Ingest and publish (#101)")

        # Dirty the shared repo outside knowledge/
        (self.shared / "specs" / "scratch.txt").write_text("unapproved scratch\n")
        (self.shared / "invariants.md").write_text("modified rule\n")

        args = argparse.Namespace(
            dir=str(self.ws),
            repo="backend",
            branch=None,
            publish=True,
            no_summarize=True,
        )
        sentinel.cmd_kb_ingest(args)

        files = self.remote_files()
        # Knowledge index should be published
        self.assertIn("knowledge/index.json", files)
        # Non-knowledge files must NOT be in the remote
        self.assertNotIn("specs/scratch.txt", files)
        # Unapproved invariants must remain unpushed
        self.assertNotEqual(sh(self.bare, "show", "main:invariants.md").stdout.strip(), "modified rule")

    # ---- 5. Prompt injection includes summary/module/invariants/changes overlapping write scope
    def test_prompt_injection_includes_overlapping_and_excludes_non_overlapping(self):
        self.to_completed()
        shared_dir = self.ws / ".sentinel" / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)
        knowledge.ensure_layout(shared_dir)

        # 1. Repo summary for backend
        repo_sum = shared_dir / "knowledge" / "repos" / "backend" / "summary.md"
        repo_sum.parent.mkdir(parents=True, exist_ok=True)
        repo_sum.write_text("# Backend repo summary\nOverview of backend.\n")

        # 2. Module summaries: one overlapping (src/main), one non-overlapping (src/other)
        mod_dir = shared_dir / "knowledge" / "repos" / "backend" / "modules"
        mod_dir.mkdir(parents=True, exist_ok=True)
        (mod_dir / "src-main.md").write_text("---\nmodule: src/main\n---\n## Module src/main\nHandles core business.\n")
        (mod_dir / "src-other.md").write_text("---\nmodule: src/other\n---\n## Module src/other\nHandles other things.\n")

        # 3. invariants.md
        (shared_dir / "invariants.md").write_text("# Team invariants\nMust follow clean architecture.\n")

        # 4. Change records: one touching src/main, one touching src/other
        changes_dir = shared_dir / "knowledge" / "changes" / "backend" / "2026-11"
        changes_dir.mkdir(parents=True, exist_ok=True)
        rec1_path = changes_dir / "pr-10.md"
        rec1_path.write_text("---\nkey: pr-10\nrepo: backend\nmodules: [src/main]\n---\n## What changed\nAdded main feature.\n")
        rec2_path = changes_dir / "pr-20.md"
        rec2_path.write_text("---\nkey: pr-20\nrepo: backend\nmodules: [src/other]\n---\n## What changed\nAdded other feature.\n")

        index = {
            "pr-10": {
                "path": str(rec1_path.relative_to(shared_dir)),
                "repo": "backend",
                "modules": ["src/main"],
                "reached": [{"branch": "main", "sha": "1111", "at": "2026-11-20T10:00:00Z"}],
            },
            "pr-20": {
                "path": str(rec2_path.relative_to(shared_dir)),
                "repo": "backend",
                "modules": ["src/other"],
                "reached": [{"branch": "main", "sha": "2222", "at": "2026-11-21T10:00:00Z"}],
            },
        }
        knowledge.write_index(shared_dir, index)

        # Create task with write scope covering backend/src/main/**
        self.set_state("EXECUTING")
        run = self.run_row()
        tid = self.eng.create_task(SLUG, "tdd_green", "Implement task", repos=["backend"], write=["backend/src/main/**"])["id"]
        t = self.task(tid)
        tdir = self.tdir(tid)

        prompt = self.eng._render_prompt(run, t, tdir)

        # Assert ## Project knowledge exists
        self.assertIn("## Project knowledge", prompt)
        # Assert repo summary is included
        self.assertIn(str(repo_sum.resolve()), prompt)
        self.assertIn("Overview of backend", prompt)
        # Assert overlapping module summary is included
        self.assertIn(str((mod_dir / "src-main.md").resolve()), prompt)
        self.assertIn("Handles core business", prompt)
        # Assert non-overlapping module summary is EXCLUDED
        self.assertNotIn("src-other.md", prompt)
        self.assertNotIn("Handles other things", prompt)
        # Assert invariants.md is included
        self.assertIn(str((shared_dir / "invariants.md").resolve()), prompt)
        self.assertIn("Must follow clean architecture", prompt)
        # Assert overlapping change record is included
        self.assertIn(str(rec1_path.resolve()), prompt)
        self.assertIn("Added main feature", prompt)
        # Assert non-overlapping change record is EXCLUDED
        self.assertNotIn("pr-20.md", prompt)
        self.assertNotIn("Added other feature", prompt)

    # ---- 6. Prompt injection respects 6000-char cap
    def test_prompt_injection_respects_6000_char_cap(self):
        self.to_completed()
        shared_dir = self.ws / ".sentinel" / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)
        knowledge.ensure_layout(shared_dir)

        # Create large files
        repo_sum = shared_dir / "knowledge" / "repos" / "backend" / "summary.md"
        repo_sum.parent.mkdir(parents=True, exist_ok=True)
        repo_sum.write_text("A" * 3000)

        inv_path = shared_dir / "invariants.md"
        inv_path.write_text("B" * 3000)

        mod_dir = shared_dir / "knowledge" / "repos" / "backend" / "modules"
        mod_dir.mkdir(parents=True, exist_ok=True)
        (mod_dir / "src-main.md").write_text("---\nmodule: src/main\n---\n" + ("C" * 3000))

        self.set_state("EXECUTING")
        run = self.run_row()
        tid = self.eng.create_task(SLUG, "tdd_green", "Implement task", repos=["backend"], write=["backend/src/main/**"])["id"]
        t = self.task(tid)
        tdir = self.tdir(tid)

        prompt = self.eng._render_prompt(run, t, tdir)
        self.assertIn("## Project knowledge", prompt)
        kb_section = prompt[prompt.index("## Project knowledge"):]
        self.assertLessEqual(len(kb_section.strip()), 6000)

    # ---- 7. Prompt injection absent when knowledge is disabled
    def test_prompt_injection_absent_when_knowledge_disabled(self):
        self.to_completed(knowledge={"enabled": False})
        shared_dir = self.ws / ".sentinel" / "shared"
        shared_dir.mkdir(parents=True, exist_ok=True)
        knowledge.ensure_layout(shared_dir)
        sum_file = shared_dir / "knowledge" / "repos" / "backend" / "summary.md"
        sum_file.parent.mkdir(parents=True, exist_ok=True)
        sum_file.write_text("Backend summary\n")

        self.set_state("EXECUTING")
        run = self.run_row()
        tid = self.eng.create_task(SLUG, "tdd_green", "Implement task", repos=["backend"], write=["backend/src/main/**"])["id"]
        t = self.task(tid)
        tdir = self.tdir(tid)

        prompt = self.eng._render_prompt(run, t, tdir)
        self.assertNotIn("## Project knowledge", prompt)

    # ---- 8. CI template is valid YAML with push trigger and concurrency group
    def test_ci_template_is_valid_yaml_with_push_and_concurrency(self):
        template_file = Path(__file__).resolve().parents[1] / "sentinel" / "templates" / "ci" / "knowledge-ingest.yml"
        self.assertTrue(template_file.is_file(), f"Missing template file: {template_file}")
        content = template_file.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        self.assertIsInstance(data, dict)

        # Verify on.push trigger
        on_clause = data.get("on") or data.get(True)  # PyYAML might parse 'on' as True if unquoted
        self.assertIsNotNone(on_clause)
        push_trigger = on_clause.get("push")
        self.assertIsNotNone(push_trigger)
        branches = push_trigger.get("branches")
        self.assertIn("develop", branches)
        self.assertIn("main", branches)

        # Verify concurrency group
        concurrency = data.get("concurrency")
        self.assertIsNotNone(concurrency)
        self.assertTrue(concurrency.get("group"))

        # Check comment notes
        self.assertIn("Gitea", content)

    def test_ci_template_writes_a_valid_config(self):
        import jsonschema
        root = Path(__file__).resolve().parents[1]
        data = yaml.safe_load((root / "sentinel" / "templates" / "ci" / "knowledge-ingest.yml").read_text())
        step = next(s for s in data["jobs"]["ingest"]["steps"] if s["name"] == "Write a one-repo Sentinel config")
        body = step["run"].split("<<CONFIG\n", 1)[1].split("\nCONFIG", 1)[0]
        env = dict(data["env"], SHARED_URL="https://git.example.com/team/shared.git")
        for name, value in env.items():
            body = body.replace("${" + name + "}", str(value))
        config = yaml.safe_load(body)
        schema = json.loads((root / "sentinel" / "core" / "schema" / "config.schema.json").read_text())
        self.assertEqual(list(jsonschema.Draft202012Validator(schema).iter_errors(config)), [])
        self.assertEqual(config["repos"][0]["knowledge"]["branches"], ["develop", "main"])
        self.assertEqual(data["env"]["SENTINEL_KB_NO_SPAWN"], "1")


if __name__ == "__main__":
    unittest.main()
