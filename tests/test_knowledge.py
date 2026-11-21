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


if __name__ == "__main__":
    unittest.main()
