"""Tests for sentinel/scripts/knowledge.py — Phase A.

Uses temporary git repos; follows the existing test patterns (tempfile, unittest, sys.path insert).
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import knowledge  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(directory, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(directory)] + list(args),
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr}")
    return result


def make_repo(tmp, name="repo", bare=False):
    """Create a small git repo under *tmp* and return its path."""
    repo = Path(tmp) / name
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    return repo


def commit_file(repo, name, content, message, author_name=None, author_email=None):
    """Commit a single file and return the sha."""
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", name)
    env = {}
    if author_name:
        env["GIT_AUTHOR_NAME"] = author_name
    if author_email:
        env["GIT_AUTHOR_EMAIL"] = author_email
    extra = []
    if author_name:
        extra += ["--author", f"{author_name} <{author_email or 'test@example.com'}>"]
    _git(repo, "commit", "-m", message, *extra)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def merge_branch(repo, source, target="main", message=None):
    """Merge *source* into *target* and return the merge sha."""
    _git(repo, "checkout", target)
    if message:
        _git(repo, "merge", "--no-ff", source, "-m", message)
    else:
        _git(repo, "merge", "--no-ff", source)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


# ---------------------------------------------------------------------------
# PR key detection
# ---------------------------------------------------------------------------

class TestPRKeyDetection(unittest.TestCase):
    def test_github_merge(self):
        self.assertEqual(knowledge.extract_pr_number("Merge pull request #42 from feature/x"), 42)

    def test_azure_merge(self):
        self.assertEqual(knowledge.extract_pr_number("Merged PR 123: Add feature"), 123)

    def test_gitea_merge(self):
        self.assertEqual(knowledge.extract_pr_number("Merge pull request 'Add feature' (#7) from feat"), 7)

    def test_squash_pr(self):
        self.assertEqual(knowledge.extract_pr_number("Add leave balance export (#99)"), 99)

    def test_no_pr(self):
        self.assertIsNone(knowledge.extract_pr_number("fix: update readme"))

    def test_change_key_from_pr(self):
        self.assertEqual(knowledge.change_key_from_pr(42), "pr-42")


# ---------------------------------------------------------------------------
# Patch-id key
# ---------------------------------------------------------------------------

class TestPatchIdKey(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(self._tmp.name)

    def test_patch_id_key_prefix(self):
        sha = commit_file(self.repo, "file.txt", "hello", "init")
        key = knowledge.change_key_from_patch(self.repo, sha)
        self.assertTrue(key.startswith("p-"), f"expected p-... got {key}")
        self.assertEqual(len(key), 2 + 12)  # p- + 12 hex chars

    def test_change_key_no_pr_uses_patch_id(self):
        sha = commit_file(self.repo, "file.txt", "hello", "fix: something")
        key = knowledge.change_key(self.repo, sha, "fix: something")
        self.assertTrue(key.startswith("p-"))

    def test_change_key_with_pr_uses_pr(self):
        sha = commit_file(self.repo, "file.txt", "hello", "Add feature (#10)")
        key = knowledge.change_key(self.repo, sha, "Add feature (#10)")
        self.assertEqual(key, "pr-10")

    def test_merge_commit_without_pr_gets_stable_patch_id(self):
        # Initial commit
        commit_file(self.repo, "f.txt", "base\n", "init")
        # Feature branch 1
        _git(self.repo, "checkout", "-b", "feat1")
        commit_file(self.repo, "f.txt", "base\nchange\n", "feat change")
        _git(self.repo, "checkout", "main")
        merge_sha1 = merge_branch(self.repo, "feat1", "main", "Merge branch 'feat1'")

        key1 = knowledge.change_key(self.repo, merge_sha1, "Merge branch 'feat1'")
        self.assertTrue(key1.startswith("p-"))
        self.assertNotEqual(key1, f"p-{merge_sha1[:12]}")

        # Another branch with identical diff from the same parent state
        _git(self.repo, "checkout", "-b", "main2", f"{merge_sha1}^1")
        _git(self.repo, "checkout", "-b", "feat2")
        commit_file(self.repo, "f.txt", "base\nchange\n", "different message")
        _git(self.repo, "checkout", "main2")
        merge_sha2 = merge_branch(self.repo, "feat2", "main2", "Merge branch 'feat2'")

        key2 = knowledge.change_key(self.repo, merge_sha2, "Merge branch 'feat2'")
        self.assertNotEqual(merge_sha1, merge_sha2)
        self.assertEqual(key1, key2)


# ---------------------------------------------------------------------------
# Develop-then-main promotion keeps one record with two reached entries
# ---------------------------------------------------------------------------

class TestPromotionMerge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(self._tmp.name)
        self.shared = Path(self._tmp.name) / "shared"
        self.shared.mkdir()
        knowledge.ensure_layout(self.shared)

    def test_develop_then_main_keeps_one_record(self):
        # Initial commit on main
        commit_file(self.repo, "readme.md", "# project", "init")
        # Create develop branch
        _git(self.repo, "checkout", "-b", "develop")
        # Make a PR-like merge on develop
        _git(self.repo, "checkout", "-b", "feature/x")
        sha_feat = commit_file(self.repo, "src/app.py", "print('hi')", "feat: add app (#5)")
        _git(self.repo, "checkout", "develop")
        merge_sha_dev = merge_branch(self.repo, "feature/x", "develop", "Merge pull request #5 from feature/x")

        # Ingest develop
        config = {"repos": [{"id": "backend", "path": str(self.repo), "knowledge": {"branches": ["develop", "main"]}}]}
        knowledge.ingest_branch(str(self.shared), "backend", str(self.repo), "develop", config,
                                tracked_branches=["develop", "main"])

        # Now merge develop into main
        _git(self.repo, "checkout", "main")
        merge_sha_main = merge_branch(self.repo, "develop", "main", "Merge pull request #5 from develop")

        # Ingest main
        knowledge.ingest_branch(str(self.shared), "backend", str(self.repo), "main", config,
                                tracked_branches=["develop", "main"])

        # Should be one record with two reached entries
        index = knowledge.read_index(str(self.shared))
        self.assertIn("pr-5", index)
        reached = index["pr-5"]["reached"]
        branches = {r["branch"] for r in reached}
        self.assertEqual(branches, {"develop", "main"})

    def test_features_merged_to_develop_then_promoted_to_main(self):
        # Initial commit on main
        init_sha = commit_file(self.repo, "readme.md", "# project", "init")
        config = {"repos": [{"id": "backend", "path": str(self.repo), "knowledge": {"branches": ["develop", "main"]}}]}
        # Ingest main initially so cursor is at init
        knowledge.ingest_branch(str(self.shared), "backend", str(self.repo), "main", config,
                                tracked_branches=["develop", "main"])
        index_init = knowledge.read_index(str(self.shared))

        _git(self.repo, "checkout", "-b", "develop")

        # Feature 1 merged to develop via merge commit
        _git(self.repo, "checkout", "-b", "feature/1")
        commit_file(self.repo, "f1.py", "print(1)", "feat 1")
        _git(self.repo, "checkout", "develop")
        m_dev1 = merge_branch(self.repo, "feature/1", "develop", "Merge branch 'feature/1'")

        # Feature 2 merged to develop via merge commit
        _git(self.repo, "checkout", "-b", "feature/2")
        commit_file(self.repo, "f2.py", "print(2)", "feat 2")
        _git(self.repo, "checkout", "develop")
        m_dev2 = merge_branch(self.repo, "feature/2", "develop", "Merge branch 'feature/2'")

        # Ingest develop
        knowledge.ingest_branch(str(self.shared), "backend", str(self.repo), "develop", config,
                                tracked_branches=["develop", "main"])

        index_dev = knowledge.read_index(str(self.shared))
        dev_keys = list(set(index_dev.keys()) - set(index_init.keys()))
        self.assertEqual(len(dev_keys), 2)
        for k in dev_keys:
            reached_branches = [r["branch"] for r in index_dev[k]["reached"]]
            self.assertEqual(reached_branches, ["develop"])

        # Now merge develop into main with one merge commit
        _git(self.repo, "checkout", "main")
        m_main = merge_branch(self.repo, "develop", "main", "Merge branch 'develop' into main")

        # Ingest main
        knowledge.ingest_branch(str(self.shared), "backend", str(self.repo), "main", config,
                                tracked_branches=["develop", "main"])

        # Verify: no new record on main, each develop record gains a main reached entry
        index_main = knowledge.read_index(str(self.shared))
        new_on_main = set(index_main.keys()) - set(index_dev.keys())
        self.assertEqual(len(new_on_main), 0, "No new record on main")
        for k in dev_keys:
            entry = index_main[k]
            reached = entry["reached"]
            branches = [r["branch"] for r in reached]
            self.assertEqual(branches, ["develop", "main"])
            main_reached = [r for r in reached if r["branch"] == "main"][0]
            self.assertEqual(main_reached["sha"], m_main)
            info_m = knowledge.commit_info(str(self.repo), m_main)
            self.assertEqual(main_reached["at"], info_m["date"])

    def test_feature_merged_straight_into_main_creates_one_record(self):
        # Initial commit on main
        commit_file(self.repo, "readme.md", "# project", "init")
        config = {"repos": [{"id": "backend", "path": str(self.repo), "knowledge": {"branches": ["main"]}}]}
        # Ingest main initially
        knowledge.ingest_branch(str(self.shared), "backend", str(self.repo), "main", config,
                                tracked_branches=["main"])
        index_before = knowledge.read_index(str(self.shared))

        # Merge feature branch straight into main via merge commit
        _git(self.repo, "checkout", "-b", "feature/direct")
        commit_file(self.repo, "src/feature.py", "x = 42", "add direct feature")
        _git(self.repo, "checkout", "main")
        m_sha = merge_branch(self.repo, "feature/direct", "main", "Merge branch 'feature/direct'")

        count = knowledge.ingest_branch(str(self.shared), "backend", str(self.repo), "main", config,
                                        tracked_branches=["main"])
        self.assertEqual(count, 1)

        index = knowledge.read_index(str(self.shared))
        new_keys = list(set(index.keys()) - set(index_before.keys()))
        self.assertEqual(len(new_keys), 1)
        key = new_keys[0]
        self.assertTrue(key.startswith("p-"))
        self.assertEqual(index[key]["reached"][0]["branch"], "main")
        self.assertEqual(index[key]["reached"][0]["sha"], m_sha)
        info = knowledge.commit_info(str(self.repo), m_sha)
        self.assertEqual(index[key]["reached"][0]["at"], info["date"])
        self.assertEqual(index[key]["shas"], [m_sha])

    def test_reached_at_is_commit_date_not_ingest_time(self):
        commit_file(self.repo, "readme.md", "# project", "init")
        _git(self.repo, "checkout", "-b", "feat")
        commit_file(self.repo, "f.txt", "hello", "custom date commit")
        _git(self.repo, "checkout", "main")
        m_sha = merge_branch(self.repo, "feat", "main", "Merge feat")

        info = knowledge.commit_info(str(self.repo), m_sha)
        config = {"repos": [{"id": "backend", "path": str(self.repo), "knowledge": {"branches": ["main"]}}]}
        knowledge.ingest_branch(str(self.shared), "backend", str(self.repo), "main", config,
                                tracked_branches=["main"])

        index = knowledge.read_index(str(self.shared))
        entries = [r for e in index.values() for r in e.get("reached", []) if r.get("sha") == m_sha]
        self.assertEqual(len(entries), 1, index)
        self.assertEqual(entries[0]["at"], info["date"])


# ---------------------------------------------------------------------------
# Squash merge to main matches develop record via PR number
# ---------------------------------------------------------------------------

class TestSquashMerge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(self._tmp.name)
        self.shared = Path(self._tmp.name) / "shared"
        self.shared.mkdir()
        knowledge.ensure_layout(self.shared)

    def test_squash_merge_matches_via_pr_number(self):
        commit_file(self.repo, "readme.md", "# project", "init")
        _git(self.repo, "checkout", "-b", "develop")
        _git(self.repo, "checkout", "-b", "feature/y")
        commit_file(self.repo, "src/lib.py", "x = 1", "Add lib (#12)")
        _git(self.repo, "checkout", "develop")
        merge_branch(self.repo, "feature/y", "develop", "Merge pull request #12 from feature/y")

        config = {"repos": [{"id": "api", "path": str(self.repo), "knowledge": {"branches": ["develop", "main"]}}]}
        knowledge.ingest_branch(str(self.shared), "api", str(self.repo), "develop", config,
                                tracked_branches=["develop", "main"])

        # Squash merge to main with (#12) in the subject
        _git(self.repo, "checkout", "main")
        _git(self.repo, "merge", "--squash", "develop")
        _git(self.repo, "commit", "-m", "Add lib (#12)")

        knowledge.ingest_branch(str(self.shared), "api", str(self.repo), "main", config,
                                tracked_branches=["develop", "main"])

        index = knowledge.read_index(str(self.shared))
        self.assertIn("pr-12", index)
        reached = index["pr-12"]["reached"]
        branches = {r["branch"] for r in reached}
        self.assertEqual(branches, {"develop", "main"})


# ---------------------------------------------------------------------------
# Force-push on develop marks dropped records and restarts from merge-base
# ---------------------------------------------------------------------------

class TestForcePushDropped(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(self._tmp.name)
        self.shared = Path(self._tmp.name) / "shared"
        self.shared.mkdir()
        knowledge.ensure_layout(self.shared)

    def test_force_push_marks_dropped_and_restarts(self):
        # Base commit on main
        base_sha = commit_file(self.repo, "readme.md", "# project", "init")
        _git(self.repo, "checkout", "-b", "develop")
        old_sha = commit_file(self.repo, "old.py", "old", "old change")

        config = {"repos": [{"id": "api", "path": str(self.repo)}]}
        knowledge.ingest_branch(str(self.shared), "api", str(self.repo), "develop", config,
                                tracked_branches=["develop"])

        # Check cursor was set
        cursor = knowledge.read_cursor(str(self.shared))
        self.assertIn("api@develop", cursor)

        # Simulate force-push: reset develop to base and add a new commit
        _git(self.repo, "reset", "--hard", base_sha)
        new_sha = commit_file(self.repo, "new.py", "new", "new change after rebase")

        # Ingest again: should detect force-push
        knowledge.ingest_branch(str(self.shared), "api", str(self.repo), "develop", config,
                                tracked_branches=["develop"])

        # The old record should be marked dropped
        index = knowledge.read_index(str(self.shared))
        old_key = knowledge.change_key(str(self.repo), old_sha, "old change")
        new_key = knowledge.change_key(str(self.repo), new_sha, "new change after rebase")

        # The old record should exist and be dropped
        if old_key in index:
            self.assertEqual(index[old_key]["status"], "dropped")

        # The new record should exist and be active
        self.assertIn(new_key, index)
        self.assertEqual(index[new_key]["status"], "active")


# ---------------------------------------------------------------------------
# Cursor resume
# ---------------------------------------------------------------------------

class TestCursorResume(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(self._tmp.name)
        self.shared = Path(self._tmp.name) / "shared"
        self.shared.mkdir()
        knowledge.ensure_layout(self.shared)

    def test_cursor_resumes_from_last_position(self):
        commit_file(self.repo, "readme.md", "# project", "init")
        sha1 = commit_file(self.repo, "a.py", "a", "first change")
        sha2 = commit_file(self.repo, "b.py", "b", "second change")

        config = {"repos": [{"id": "api", "path": str(self.repo)}]}
        knowledge.ingest_branch(str(self.shared), "api", str(self.repo), "main", config,
                                tracked_branches=["main"])

        # cursor should point to sha2
        cursor = knowledge.read_cursor(str(self.shared))
        self.assertEqual(cursor["api@main"]["sha"], sha2)

        # Add more commits
        sha3 = commit_file(self.repo, "c.py", "c", "third change")

        # Ingest again: should only process sha3
        count = knowledge.ingest_branch(str(self.shared), "api", str(self.repo), "main", config,
                                        tracked_branches=["main"])
        self.assertEqual(count, 1)
        cursor = knowledge.read_cursor(str(self.shared))
        self.assertEqual(cursor["api@main"]["sha"], sha3)


# ---------------------------------------------------------------------------
# Cap (max_changes_per_ingest)
# ---------------------------------------------------------------------------

class TestCap(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(self._tmp.name)
        self.shared = Path(self._tmp.name) / "shared"
        self.shared.mkdir()
        knowledge.ensure_layout(self.shared)

    def test_cap_limits_changes(self):
        commit_file(self.repo, "readme.md", "# project", "init")
        for i in range(5):
            commit_file(self.repo, f"file{i}.py", f"content{i}", f"change {i}")

        # 6 commits total (init + 5 changes): cap at 3
        config = {"repos": [{"id": "api", "path": str(self.repo)}],
                  "knowledge": {"max_changes_per_ingest": 3}}
        count = knowledge.ingest_branch(str(self.shared), "api", str(self.repo), "main", config,
                                        tracked_branches=["main"])
        self.assertEqual(count, 3)

        # Next ingest picks up the remaining 3
        count2 = knowledge.ingest_branch(str(self.shared), "api", str(self.repo), "main", config,
                                         tracked_branches=["main"])
        self.assertEqual(count2, 3)


# ---------------------------------------------------------------------------
# Default branch fallback
# ---------------------------------------------------------------------------

class TestDefaultBranch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(self._tmp.name)

    def test_default_branch_returns_current_branch(self):
        commit_file(self.repo, "readme.md", "# project", "init")
        branch = knowledge.resolve_default_branch(str(self.repo))
        self.assertEqual(branch, "main")


# ---------------------------------------------------------------------------
# No emails in records
# ---------------------------------------------------------------------------

class TestNoEmails(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(self._tmp.name)
        self.shared = Path(self._tmp.name) / "shared"
        self.shared.mkdir()
        knowledge.ensure_layout(self.shared)

    def test_no_emails_in_records(self):
        commit_file(self.repo, "readme.md", "# project", "init",
                    author_name="Alice Smith", author_email="alice@company.com")
        sha = commit_file(self.repo, "a.py", "a", "add feature (#1)",
                          author_name="Bob Jones", author_email="bob@company.com")

        config = {"repos": [{"id": "api", "path": str(self.repo)}]}
        knowledge.ingest_branch(str(self.shared), "api", str(self.repo), "main", config,
                                tracked_branches=["main"])

        # Read all record files and check for emails
        changes = knowledge.changes_dir(str(self.shared), "api")
        all_content = ""
        for md_file in changes.rglob("*.md"):
            all_content += md_file.read_text()
        self.assertNotIn("alice@company.com", all_content)
        self.assertNotIn("bob@company.com", all_content)
        # Author names should be present across all records
        self.assertIn("Alice Smith", all_content)
        self.assertIn("Bob Jones", all_content)

    def test_clean_author_strips_email(self):
        self.assertEqual(knowledge.clean_author("Alice <alice@x.com>"), "Alice")
        self.assertEqual(knowledge.clean_author("Bob"), "Bob")
        self.assertEqual(knowledge.clean_author("Charlie Brown <cb@test.org>"), "Charlie Brown")


# ---------------------------------------------------------------------------
# Config schema accepts new keys and rejects bad ones
# ---------------------------------------------------------------------------

class TestConfigSchema(unittest.TestCase):
    def setUp(self):
        schema_path = Path(__file__).resolve().parents[1] / "sentinel" / "core" / "schema" / "config.schema.json"
        self.schema = json.loads(schema_path.read_text())
        try:
            import jsonschema
            self.validate = jsonschema.validate
            self.ValidationError = jsonschema.ValidationError
        except ImportError:
            self.skipTest("jsonschema not installed")

    def _base_config(self):
        return {
            "version": 1,
            "shape": "single",
            "repos": [{"id": "api", "path": "./api", "role": "backend", "profile": "java-spring"}],
        }

    def test_accepts_knowledge_on_repo(self):
        cfg = self._base_config()
        cfg["repos"][0]["knowledge"] = {"branches": ["develop", "main"]}
        self.validate(cfg, self.schema)

    def test_accepts_top_level_knowledge(self):
        cfg = self._base_config()
        cfg["knowledge"] = {"enabled": True, "backfill_months": 6, "max_changes_per_ingest": 100}
        self.validate(cfg, self.schema)

    def test_rejects_empty_branch_name(self):
        cfg = self._base_config()
        cfg["repos"][0]["knowledge"] = {"branches": [""]}
        with self.assertRaises(self.ValidationError):
            self.validate(cfg, self.schema)

    def test_rejects_duplicate_branches(self):
        cfg = self._base_config()
        cfg["repos"][0]["knowledge"] = {"branches": ["main", "main"]}
        with self.assertRaises(self.ValidationError):
            self.validate(cfg, self.schema)

    def test_rejects_unknown_knowledge_key(self):
        cfg = self._base_config()
        cfg["knowledge"] = {"enabled": True, "bogus_key": 42}
        with self.assertRaises(self.ValidationError):
            self.validate(cfg, self.schema)

    def test_rejects_unknown_repo_knowledge_key(self):
        cfg = self._base_config()
        cfg["repos"][0]["knowledge"] = {"branches": ["main"], "bogus": True}
        with self.assertRaises(self.ValidationError):
            self.validate(cfg, self.schema)


# ---------------------------------------------------------------------------
# Record parse / render round-trip
# ---------------------------------------------------------------------------

class TestRecordRoundTrip(unittest.TestCase):
    def test_round_trip(self):
        meta = {
            "key": "pr-42",
            "repo": "backend",
            "provenance": "inferred",
            "status": "active",
            "reached": [{"branch": "main", "sha": "abc123", "at": "2026-01-01T00:00:00Z"}],
            "authors": ["Alice"],
            "title": "Add feature",
            "files": ["src/app.py"],
            "modules": ["src"],
            "run": None,
            "spec": None,
        }
        body = "\n## What changed\nSome changes\n"
        text = knowledge.render_record(meta, body)
        parsed_meta, parsed_body = knowledge.parse_record(text)
        self.assertEqual(parsed_meta["key"], "pr-42")
        self.assertEqual(parsed_body.strip(), body.strip())


# ---------------------------------------------------------------------------
# Layout creation
# ---------------------------------------------------------------------------

class TestLayout(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.shared = Path(self._tmp.name) / "shared"

    def test_ensure_layout_creates_skeleton(self):
        knowledge.ensure_layout(str(self.shared))
        self.assertTrue((self.shared / "knowledge" / "README.md").exists())
        self.assertTrue((self.shared / "knowledge" / "cursor.json").exists())
        self.assertTrue((self.shared / "knowledge" / "index.json").exists())
        self.assertTrue((self.shared / "knowledge" / "patterns" / "README.md").exists())

    def test_ensure_layout_idempotent(self):
        knowledge.ensure_layout(str(self.shared))
        knowledge.ensure_layout(str(self.shared))
        self.assertTrue((self.shared / "knowledge" / "README.md").exists())


# ---------------------------------------------------------------------------
# Status output
# ---------------------------------------------------------------------------

class TestStatus(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = make_repo(self._tmp.name)
        self.shared = Path(self._tmp.name) / "shared"
        self.shared.mkdir()
        knowledge.ensure_layout(self.shared)

    def test_status_counts(self):
        commit_file(self.repo, "readme.md", "# project", "init")
        commit_file(self.repo, "a.py", "a", "first (#1)")
        commit_file(self.repo, "b.py", "b", "second")

        config = {"repos": [{"id": "api", "path": str(self.repo)}]}
        knowledge.ingest_branch(str(self.shared), "api", str(self.repo), "main", config,
                                tracked_branches=["main"])
        info = knowledge.status(str(self.shared), config)
        self.assertGreaterEqual(info["records"]["total"], 2)
        self.assertEqual(info["records"]["dropped"], 0)


# ---------------------------------------------------------------------------
# Phase B: Snapshot summaries, staleness, summarizer runner & routing
# ---------------------------------------------------------------------------

from unittest import mock


class TestPhaseB(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.repo = make_repo(self.ws, "backend")
        self.shared = self.ws / "shared"
        self.shared.mkdir()
        knowledge.ensure_layout(str(self.shared))

    def _cfg(self, **kb):
        return {
            "version": 1,
            "state": {"dir": ".sentinel", "shared_mode": "local"},
            "knowledge": {"enabled": True, **kb},
            "repos": [{"id": "backend", "path": "backend"}],
        }

    def test_snapshot_from_branch_tip_ignores_uncommitted_working_tree_files(self):
        commit_file(self.repo, "mod_a/foo.py", "print('hello')", "init mod_a")
        # Write uncommitted files directly to the working tree
        (self.repo / "mod_a" / "uncommitted.py").write_text("uncommitted file")
        uncommitted_mod = self.repo / "uncommitted_mod"
        uncommitted_mod.mkdir()
        (uncommitted_mod / "bar.py").write_text("bar")

        res = knowledge.snapshot_repo(
            str(self.shared), str(self.ws),
            {"id": "backend", "path": "backend"},
            self._cfg(),
        )
        self.assertIn("mod_a", res["modules"])
        self.assertNotIn("uncommitted_mod", res["modules"])

        mod_a_file = self.shared / "knowledge" / "repos" / "backend" / "modules" / "mod_a.md"
        self.assertTrue(mod_a_file.exists())
        meta, body = knowledge.read_record(mod_a_file)
        self.assertEqual(meta["module"], "mod_a")
        self.assertIn("- **Files**: 1", body)
        self.assertNotIn("uncommitted.py", body)

        summary_file = self.shared / "knowledge" / "repos" / "backend" / "summary.md"
        self.assertTrue(summary_file.exists())
        _, s_body = knowledge.read_record(summary_file)
        self.assertIn("- **Files**: 1", s_body)
        self.assertNotIn("uncommitted.py", s_body)
        self.assertFalse((self.shared / "knowledge" / "repos" / "backend" / "modules" / "uncommitted_mod.md").exists())

    def test_unchanged_module_skipped_changed_regenerated_removed_deleted(self):
        commit_file(self.repo, "mod_a/a.py", "x = 1\n", "init a")
        commit_file(self.repo, "mod_b/b.py", "y = 2\n", "init b")

        repo_cfg = {"id": "backend", "path": "backend"}
        knowledge.snapshot_repo(str(self.shared), str(self.ws), repo_cfg, self._cfg())

        mod_a_file = self.shared / "knowledge" / "repos" / "backend" / "modules" / "mod_a.md"
        mod_b_file = self.shared / "knowledge" / "repos" / "backend" / "modules" / "mod_b.md"
        self.assertTrue(mod_a_file.exists())
        self.assertTrue(mod_b_file.exists())

        # Modify on disk with marker comment to detect if skipped
        a_text = mod_a_file.read_text()
        mod_a_file.write_text(a_text + "\n<!-- custom-marker -->\n")

        # Snapshot again without changes (force=False)
        res = knowledge.snapshot_repo(str(self.shared), str(self.ws), repo_cfg, self._cfg(), force=False)
        self.assertEqual(res["generated"], [])  # both skipped
        self.assertIn("<!-- custom-marker -->", mod_a_file.read_text())

        # Snapshot with force=True regenerates even if unchanged
        res_forced = knowledge.snapshot_repo(str(self.shared), str(self.ws), repo_cfg, self._cfg(), force=True)
        self.assertIn("mod_a", res_forced["generated"])
        self.assertNotIn("<!-- custom-marker -->", mod_a_file.read_text())

        # Add marker back to mod_a
        mod_a_file.write_text(mod_a_file.read_text() + "\n<!-- custom-marker-2 -->\n")

        # Now commit change to mod_a and delete directory mod_b from git
        commit_file(self.repo, "mod_a/a.py", "x = 42\n", "update a")
        _git(self.repo, "rm", "-r", "mod_b")
        _git(self.repo, "commit", "-m", "remove mod_b")

        res_update = knowledge.snapshot_repo(str(self.shared), str(self.ws), repo_cfg, self._cfg(), force=False)
        self.assertIn("mod_a", res_update["generated"])
        self.assertNotIn("mod_b", res_update["modules"])
        # mod_a was regenerated (marker gone)
        self.assertNotIn("<!-- custom-marker-2 -->", mod_a_file.read_text())
        # mod_b was removed from git -> module file deleted
        self.assertFalse(mod_b_file.exists())

    def test_nested_source_roots_first_level_with_multiple_children(self):
        # Test the module discovery rule for source roots like src/main/java and packages/*
        commit_file(self.repo, "src/main/java/com/example/billing/Billing.java", "class Billing {}", "billing")
        commit_file(self.repo, "src/main/java/com/example/shipping/Shipping.java", "class Shipping {}", "shipping")
        commit_file(self.repo, "packages/core/index.js", "export const x = 1;", "core")
        commit_file(self.repo, "packages/ui/index.js", "export const y = 2;", "ui")
        commit_file(self.repo, "docs/readme.md", "# docs", "docs")

        tip = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        modules = knowledge.find_modules_at_tip(self.repo, tip)
        self.assertIn("src/main/java/com/example/billing", modules)
        self.assertIn("src/main/java/com/example/shipping", modules)
        self.assertIn("packages/core", modules)
        self.assertIn("packages/ui", modules)
        self.assertIn("docs", modules)

    def test_summarizer_failure_timeout_yields_deterministic_only_output(self):
        commit_file(self.repo, "mod_a/a.py", "x = 1\n", "init a")
        cfg = self._cfg(summarize=True)

        with mock.patch("adapters.get_adapter", side_effect=RuntimeError("runner error")):
            with mock.patch.dict(os.environ, {"SENTINEL_KB_NO_AGENT": ""}):
                res = knowledge.snapshot_repo(
                    str(self.shared), str(self.ws),
                    {"id": "backend", "path": "backend"},
                    cfg,
                )
                self.assertIsNotNone(res)
                mod_file = self.shared / "knowledge" / "repos" / "backend" / "modules" / "mod_a.md"
                self.assertTrue(mod_file.exists())
                meta, body = knowledge.read_record(mod_file)
                self.assertIn("## Overview", body)
                self.assertIn("- **Files**: 1", body)
                self.assertNotIn("## Summary", body)

        # Also test timeout path
        mock_adapter = mock.MagicMock()
        mock_handle = mock.MagicMock()
        mock_adapter.submit.return_value = mock_handle
        mock_adapter.wait.return_value = False  # timed out
        mock_adapter.result.return_value = (124, "", "timeout")

        with mock.patch("adapters.get_adapter", return_value=mock_adapter):
            with mock.patch.dict(os.environ, {"SENTINEL_KB_NO_AGENT": ""}):
                summary = knowledge.summarize_change(
                    self.repo, "HEAD", ["mod_a/a.py"], "test", "1 file changed",
                    config=cfg, workspace=str(self.ws),
                )
                self.assertIsNone(summary)
                mock_adapter.cancel.assert_called_once_with(mock_handle)

    def test_summarizer_disabled_by_config_and_by_env_var(self):
        sha = commit_file(self.repo, "mod_a/a.py", "x = 1\n", "init a")

        with mock.patch("adapters.get_adapter") as mock_adapter:
            # 1. Disabled by config
            cfg = self._cfg(summarize=False)
            res = knowledge.summarize_change(
                self.repo, sha, ["mod_a/a.py"], "init a", "1 file changed",
                config=cfg, workspace=str(self.ws),
            )
            self.assertIsNone(res)
            mock_adapter.assert_not_called()

            # 2. Disabled by env var SENTINEL_KB_NO_AGENT=1
            cfg_enabled = self._cfg(summarize=True)
            with mock.patch.dict(os.environ, {"SENTINEL_KB_NO_AGENT": "1"}):
                res2 = knowledge.summarize_change(
                    self.repo, sha, ["mod_a/a.py"], "init a", "1 file changed",
                    config=cfg_enabled, workspace=str(self.ws),
                )
                self.assertIsNone(res2)
                mock_adapter.assert_not_called()

    def test_routing_fallback_knowledge_coder_default(self):
        mock_adapter = mock.MagicMock()
        mock_adapter.submit.return_value = mock.MagicMock()
        mock_adapter.wait.return_value = True
        mock_adapter.result.return_value = (0, "Agent summary text", "")
        mock_adapter.runner = {"command": "fake"}

        with mock.patch.dict(os.environ, {"SENTINEL_KB_NO_AGENT": ""}):
            with tempfile.TemporaryDirectory() as tmp_cwd:
                # 1. Role knowledge specified
                with mock.patch("adapters.get_adapter", return_value=mock_adapter) as mock_get_adapter:
                    cfg = {"routing": {"knowledge": {"runner": "gemini"}}, "runners": {"gemini": {"command": "gemini"}}}
                    out = knowledge._run_summarizer(cfg, str(self.ws), "test prompt", tmp_cwd)
                    self.assertEqual(out, "Agent summary text")
                    mock_get_adapter.assert_called_once()
                    self.assertEqual(mock_get_adapter.call_args[1].get("runner_id") or mock_get_adapter.call_args[0][2], "gemini")

                # 2. Falls back to coder when knowledge not specified
                with mock.patch("adapters.get_adapter", return_value=mock_adapter) as mock_get_adapter:
                    cfg = {"routing": {"coder": {"runner": "codex"}}, "runners": {"codex": {"command": "codex"}}}
                    out = knowledge._run_summarizer(cfg, str(self.ws), "test prompt", tmp_cwd)
                    self.assertEqual(out, "Agent summary text")
                    mock_get_adapter.assert_called_once()
                    self.assertEqual(mock_get_adapter.call_args[1].get("runner_id") or mock_get_adapter.call_args[0][2], "codex")

                # 3. Falls back to default ("claude") when neither routed
                with mock.patch("adapters.get_adapter", return_value=mock_adapter) as mock_get_adapter:
                    cfg = {}
                    out = knowledge._run_summarizer(cfg, str(self.ws), "test prompt", tmp_cwd)
                    self.assertEqual(out, "Agent summary text")
                    mock_get_adapter.assert_called_once()
                    self.assertEqual(mock_get_adapter.call_args[1].get("runner_id") or mock_get_adapter.call_args[0][2], "claude")

    def test_kb_worker_refresh_summaries_signature(self):
        commit_file(self.repo, "mod_a/a.py", "x = 1\n", "init a")
        config = self._cfg()
        res = knowledge.refresh_summaries(str(self.shared), str(self.ws), config, scrubber=None)
        self.assertIn("backend", res)
        self.assertTrue((self.shared / "knowledge" / "repos" / "backend" / "summary.md").exists())
        self.assertTrue((self.shared / "knowledge" / "repos" / "backend" / "modules" / "mod_a.md").exists())

    def test_ingest_respects_no_summarize_and_writes_summary_when_present(self):
        commit_file(self.repo, "readme.md", "# init\n", "init")
        commit_file(self.repo, "src/app.py", "print(1)\n", "add app (#1)")
        config = self._cfg(summarize=True)

        mock_adapter = mock.MagicMock()
        mock_adapter.submit.return_value = mock.MagicMock()
        mock_adapter.wait.return_value = True
        mock_adapter.result.return_value = (0, "Landed new app entry point", "")
        mock_adapter.runner = {"command": "fake"}

        # 1. Ingest with summarizer active
        with mock.patch.dict(os.environ, {"SENTINEL_KB_NO_AGENT": ""}):
            with mock.patch("adapters.get_adapter", return_value=mock_adapter):
                knowledge.ingest(str(self.shared), str(self.ws), config, only_repo="backend")

        idx = knowledge.read_index(str(self.shared))
        self.assertIn("pr-1", idx)
        rec_path = self.shared / idx["pr-1"]["path"]
        meta, body = knowledge.read_record(rec_path)
        self.assertIn("## Summary", body)
        self.assertIn("Landed new app entry point", body)

        # 2. Ingest with no_summarize=True
        commit_file(self.repo, "src/app.py", "print(2)\n", "update app (#2)")
        with mock.patch.dict(os.environ, {"SENTINEL_KB_NO_AGENT": ""}):
            with mock.patch("adapters.get_adapter", return_value=mock_adapter) as mock_get:
                knowledge.ingest(str(self.shared), str(self.ws), config, only_repo="backend", no_summarize=True)
                mock_get.assert_not_called()

        idx2 = knowledge.read_index(str(self.shared))
        self.assertIn("pr-2", idx2)
        rec_path2 = self.shared / idx2["pr-2"]["path"]
        meta2, body2 = knowledge.read_record(rec_path2)
        self.assertNotIn("## Summary", body2)

    def test_cli_kb_snapshot(self):
        commit_file(self.repo, "mod_a/a.py", "x = 1\n", "init a")
        cfg_file = self.ws / "sentinel.config.yaml"
        cfg_file.write_text(yaml.safe_dump(self._cfg()))

        script = Path(__file__).resolve().parents[1] / "sentinel" / "scripts" / "sentinel.py"
        r = subprocess.run([sys.executable, str(script), "--dir", str(self.ws), "kb", "snapshot"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"stdout: {r.stdout}\nstderr: {r.stderr}")
        self.assertIn("snapshot completed for backend", r.stdout)

        cli_shared = self.ws / ".sentinel" / "shared"
        mod_file = cli_shared / "knowledge" / "repos" / "backend" / "modules" / "mod_a.md"
        self.assertTrue(mod_file.exists())

        # Test --force flag
        r_force = subprocess.run([sys.executable, str(script), "--dir", str(self.ws), "kb", "snapshot", "--force"],
                                 capture_output=True, text=True)
        self.assertEqual(r_force.returncode, 0)


if __name__ == "__main__":
    unittest.main()
