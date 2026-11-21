"""Tests for Sentinel 2.0 W3 part A backend APIs:
1. POST /api/v1/detect
2. POST /api/v1/shared/test
3. GET /api/v1/routing/suggest
4. GET /api/v1/projects/{pid}/config/form
   POST /api/v1/projects/{pid}/config/preview
   POST /api/v1/projects/{pid}/config/save
5. GET /api/v1/projects/{pid}/knowledge/status
   GET /api/v1/projects/{pid}/knowledge/records
   GET /api/v1/projects/{pid}/knowledge/records/{key}
   POST /api/v1/projects/{pid}/knowledge/ingest
   POST /api/v1/projects/{pid}/knowledge/snapshot
   POST /api/v1/projects/{pid}/knowledge/backfill/estimate
   POST /api/v1/projects/{pid}/knowledge/backfill
   GET /api/v1/projects/{pid}/knowledge/ci-template
"""
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import yaml

from pc_helpers import REPOS, git
from sv_helpers import SV, Http


class SetupBase(SV):
    def setUp(self):
        super().setUp()
        self.tmp_dirs = []

    def tearDown(self):
        super().tearDown()
        for d in self.tmp_dirs:
            if os.path.exists(d):
                import shutil
                shutil.rmtree(d, ignore_errors=True)

    def mktemp_dir(self, prefix="v2-test-"):
        d = tempfile.mkdtemp(prefix=prefix)
        self.tmp_dirs.append(d)
        return Path(d)

    def init_git_repo(self, path, branch="main", with_develop=False):
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        git(p, "init", "-b", branch)
        git(p, "config", "user.name", "Sentinel Test")
        git(p, "config", "user.email", "test@localhost")
        (p / "README.md").write_text("# Test Repo\n")
        git(p, "add", "README.md")
        git(p, "commit", "-m", "Initial commit")
        if with_develop:
            git(p, "branch", "develop")
        return p


class TestDetect(SetupBase):
    def test_detect_happy_path(self):
        self.serve()
        repo = self.mktemp_dir("detect-git-")
        self.init_git_repo(repo, branch="main", with_develop=True)
        # Create a python marker
        (repo / "pyproject.toml").write_text("[project]\nname = 'demo'\n")

        # Create a non-git directory with node marker
        non_git = self.mktemp_dir("detect-nongit-")
        (non_git / "package.json").write_text('{"name": "demo"}')

        r = self.http.post("/api/v1/detect", {"paths": [str(repo), str(non_git)]})
        self.assertEqual(r.status, 200, r.text)
        items = r.json["items"]
        self.assertEqual(len(items), 2)

        # Git repo item
        g_item = next(i for i in items if i["path"] == str(repo))
        self.assertTrue(g_item["is_git"])
        self.assertEqual(g_item["current_branch"], "main")
        self.assertIn("main", g_item["local_branches"])
        self.assertIn("develop", g_item["local_branches"])
        self.assertIn("develop", g_item["tracked_branches"])
        self.assertIn("main", g_item["tracked_branches"])
        self.assertEqual(g_item["profile"], "python")
        self.assertIn("test", g_item["commands"])
        self.assertEqual(g_item["commands"]["test"], "pytest")

        # Non-git item
        ng_item = next(i for i in items if i["path"] == str(non_git))
        self.assertFalse(ng_item["is_git"])
        self.assertIsNone(ng_item["current_branch"])
        self.assertEqual(ng_item["local_branches"], [])
        self.assertEqual(ng_item["tracked_branches"], [])
        self.assertEqual(ng_item["profile"], "node")

    def test_detect_validation_and_auth_refusals(self):
        self.serve()
        # Missing paths field
        r = self.http.post("/api/v1/detect", {})
        self.assertEqual(r.status, 400)
        self.assertEqual(r.code, "E_VALIDATION")

        # Paths not a list
        r = self.http.post("/api/v1/detect", {"paths": "not-a-list"})
        self.assertEqual(r.status, 400)

        # Non-existent directory
        r = self.http.post("/api/v1/detect", {"paths": ["/tmp/nonexistent-sentinel-dir-12345"]})
        self.assertEqual(r.status, 400)

        # Relative path
        r = self.http.post("/api/v1/detect", {"paths": ["relative/path"]})
        self.assertEqual(r.status, 400)

        # NUL byte in path
        r = self.http.post("/api/v1/detect", {"paths": ["/tmp/null\0byte"]})
        self.assertEqual(r.status, 400)

        # Auth refusal (no session cookie)
        unauth = Http(self.srv.port)
        r = unauth.post("/api/v1/detect", {"paths": []})
        self.assertEqual(r.status, 401)
        self.assertEqual(r.code, "E_AUTH")

        # CSRF refusal
        r = self.http.post("/api/v1/detect", {"paths": []}, csrf="bad-csrf")
        self.assertEqual(r.status, 403)
        self.assertEqual(r.code, "E_CSRF")


class TestShared(SetupBase):
    def test_shared_test_happy_path(self):
        self.serve()
        # Create a local bare repository to test against
        bare = self.mktemp_dir("bare-") / "remote.git"
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)

        r = self.http.post("/api/v1/shared/test", {"url": str(bare)})
        self.assertEqual(r.status, 200, r.text)
        self.assertTrue(r.json["ok"])
        self.assertTrue(r.json["read"])
        self.assertTrue(r.json["write"])
        self.assertEqual(r.json["error"], "")

    def test_shared_test_failure_path(self):
        self.serve()
        # Unreachable URL
        r = self.http.post("/api/v1/shared/test", {"url": "https://127.0.0.1:9999/repo.git"})
        self.assertEqual(r.status, 200, r.text)
        self.assertFalse(r.json["ok"])
        self.assertFalse(r.json["read"])
        self.assertFalse(r.json["write"])
        self.assertTrue(r.json["error"])

    def test_shared_test_validation_and_auth_refusals(self):
        self.serve()
        # Missing url
        r = self.http.post("/api/v1/shared/test", {})
        self.assertEqual(r.status, 400)

        # Non-string url
        r = self.http.post("/api/v1/shared/test", {"url": 123})
        self.assertEqual(r.status, 400)

        # NUL byte in url
        r = self.http.post("/api/v1/shared/test", {"url": "git@github.com\0foo"})
        self.assertEqual(r.status, 400)

        # a git option is never accepted as the url, and git is never called with it
        marker = Path(tempfile.mkdtemp()) / "pwned"
        for evil in (f"--upload-pack=touch {marker}", "-c core.sshCommand=touch", "ext::sh -c touch"):
            r = self.http.post("/api/v1/shared/test", {"url": evil})
            self.assertEqual(r.status, 400, evil)
        self.assertFalse(marker.exists())

        # Auth refusal
        unauth = Http(self.srv.port)
        r = unauth.post("/api/v1/shared/test", {"url": "foo"})
        self.assertEqual(r.status, 401)

        # CSRF refusal
        r = self.http.post("/api/v1/shared/test", {"url": "foo"}, csrf="bad")
        self.assertEqual(r.status, 403)


class TestRouting(SetupBase):
    def test_routing_suggest_happy_path(self):
        self.serve()
        r = self.http.get("/api/v1/routing/suggest")
        self.assertEqual(r.status, 200, r.text)
        data = r.json
        self.assertIn("roles", data)
        self.assertIn("items", data)

        roles = data["roles"]
        # Required roles from prompt
        for role in ("triage", "gherkin", "planner", "knowledge", "specifier", "coder", "reviewer"):
            self.assertIn(role, roles)
            self.assertIn("runner", roles[role])
            self.assertIn(roles[role]["runner"], ("claude", "gemini", "agy", "codex"))

        # Fast/cheap models vs strong models check
        # E.g. triage, planner, knowledge vs specifier, coder, reviewer
        fast_roles = ["triage", "gherkin", "planner", "knowledge"]
        strong_roles = ["specifier", "coder", "reviewer"]
        for f in fast_roles:
            self.assertIn(roles[f]["runner"], ("claude", "gemini", "agy", "codex"))
        for s in strong_roles:
            self.assertIn(roles[s]["runner"], ("claude", "gemini", "agy", "codex"))

    def test_routing_suggest_auth(self):
        self.serve()
        unauth = Http(self.srv.port)
        r = unauth.get("/api/v1/routing/suggest")
        self.assertEqual(r.status, 401)


class TestConfigForm(SetupBase):
    def test_config_form_happy_path(self):
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/config/form")
        self.assertEqual(r.status, 200, r.text)
        data = r.json
        self.assertEqual(data["project"], "digital-hr")
        self.assertIn("sections", data)
        self.assertIn("fields", data)
        self.assertTrue(len(data["fields"]) > 0)

        # Verify fields structure
        paths = {f["path"]: f for f in data["fields"]}
        self.assertIn("factory.driver", paths)
        f_driver = paths["factory.driver"]
        self.assertEqual(f_driver["type"], "string")
        self.assertEqual(f_driver["enum"], ["engine", "ai-tool"])
        self.assertTrue(f_driver["editable"])

        # Check that state.shared_repo is marked non-editable
        self.assertIn("state.shared_repo", paths)
        self.assertFalse(paths["state.shared_repo"]["editable"])

        # Check repo path is marked non-editable
        self.assertIn("repos.0.path", paths)
        self.assertFalse(paths["repos.0.path"]["editable"])

    def test_config_preview_and_save(self):
        self.serve()
        # Preview a change to factory.max_tasks_per_project
        changes = [{"path": "factory.max_tasks_per_project", "value": 5}]
        r_prev = self.http.post("/api/v1/projects/digital-hr/config/preview", {"changes": changes})
        self.assertEqual(r_prev.status, 200, r_prev.text)
        self.assertTrue(r_prev.json["valid"])
        self.assertIn("+", r_prev.json["diff"])
        self.assertIn("max_tasks_per_project: 5", r_prev.json["diff"])

        # Save the change
        r_save = self.http.post("/api/v1/projects/digital-hr/config/save", {
            "changes": changes,
            "comment": "Raised max tasks",
        })
        self.assertEqual(r_save.status, 200, r_save.text)
        self.assertTrue(r_save.json["ok"])
        self.assertTrue(r_save.json["sha256"])

        # Verify configuration history recorded the version
        r_hist = self.http.get("/api/v1/projects/digital-hr/configuration/history")
        self.assertEqual(r_hist.status, 200)
        items = r_hist.json["items"]
        self.assertTrue(len(items) > 0)
        latest = items[0]
        self.assertEqual(latest["comment"], "Raised max tasks")

        # Verify audit row written
        r_audit = self.http.get("/api/v1/audit?project=digital-hr")
        self.assertEqual(r_audit.status, 200)
        audit_items = r_audit.json["items"]
        config_audits = [a for a in audit_items if a["action"] == "config_changed"]
        self.assertTrue(len(config_audits) > 0)
        self.assertEqual(config_audits[0]["reason"], "Raised max tasks")

    def test_config_refused_paths(self):
        self.serve()
        # Attempt to modify state.shared_repo via preview
        r = self.http.post("/api/v1/projects/digital-hr/config/preview", {
            "changes": [{"path": "state.shared_repo", "value": "https://hacker.com/evil.git"}],
        })
        self.assertEqual(r.status, 400)
        self.assertEqual(r.code, "E_VALIDATION")

        # Attempt to modify repos.0.path via preview
        r = self.http.post("/api/v1/projects/digital-hr/config/preview", {
            "changes": [{"path": "repos.0.path", "value": "/etc"}],
        })
        self.assertEqual(r.status, 400)
        self.assertEqual(r.code, "E_VALIDATION")

        # Attempt to modify state.shared_repo via save
        r = self.http.post("/api/v1/projects/digital-hr/config/save", {
            "changes": [{"path": "state.shared_repo", "value": "https://hacker.com/evil.git"}],
        })
        self.assertEqual(r.status, 400)
        self.assertEqual(r.code, "E_VALIDATION")

        # Attempt to modify repo path via save
        r = self.http.post("/api/v1/projects/digital-hr/config/save", {
            "changes": [{"path": "repos.0.path", "value": "/etc"}],
        })
        self.assertEqual(r.status, 400)
        self.assertEqual(r.code, "E_VALIDATION")

    def test_config_auth_csrf_refusals(self):
        self.serve()
        unauth = Http(self.srv.port)
        self.assertEqual(unauth.get("/api/v1/projects/digital-hr/config/form").status, 401)
        self.assertEqual(unauth.post("/api/v1/projects/digital-hr/config/preview", {"changes": []}).status, 401)
        self.assertEqual(unauth.post("/api/v1/projects/digital-hr/config/save", {"changes": []}).status, 401)

        self.assertEqual(self.http.post("/api/v1/projects/digital-hr/config/preview", {"changes": []}, csrf="bad").status, 403)
        self.assertEqual(self.http.post("/api/v1/projects/digital-hr/config/save", {"changes": []}, csrf="bad").status, 403)


class TestKnowledge(SetupBase):
    def setUp(self):
        super().setUp()
        # Enable knowledge and set up shared dir in workspace
        self.shared_dir = self.ws / ".sentinel" / "shared"
        self.shared_dir.mkdir(parents=True, exist_ok=True)
        (self.shared_dir / "invariants.md").write_text("# Invariants\n")

    def test_knowledge_status(self):
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/knowledge/status")
        self.assertEqual(r.status, 200, r.text)
        data = r.json
        self.assertIn("records", data)
        self.assertIn("cursors", data)
        self.assertIn("jobs", data)

    def test_knowledge_records_and_record_detail(self):
        self.serve()
        import knowledge
        shared_path = str(self.shared_dir)
        knowledge.ensure_layout(shared_path)

        # Write two test records (one verified, one inferred)
        rec1_meta = {
            "key": "run-test-1",
            "repo": "backend",
            "provenance": "verified",
            "status": "active",
            "title": "Add feature X",
            "files": ["backend/main.py"],
        }
        rec1_body = "## What changed\nFeature X implemented."
        rec1_path = knowledge.record_path(shared_path, "backend", "run-test-1", "2026-11")
        knowledge.write_record(rec1_path, rec1_meta, rec1_body)

        rec2_meta = {
            "key": "pr-42",
            "repo": "backend",
            "provenance": "inferred",
            "status": "active",
            "title": "Fix bug in Y",
            "files": ["backend/util.py"],
        }
        rec2_body = "## What changed\nFixed Y."
        rec2_path = knowledge.record_path(shared_path, "backend", "pr-42", "2026-11")
        knowledge.write_record(rec2_path, rec2_meta, rec2_body)

        # Write index
        index = {
            "run-test-1": {
                "path": str(rec1_path.relative_to(shared_path)),
                "repo": "backend",
                "provenance": "verified",
                "status": "active",
                "files": ["backend/main.py"],
            },
            "pr-42": {
                "path": str(rec2_path.relative_to(shared_path)),
                "repo": "backend",
                "provenance": "inferred",
                "status": "active",
                "files": ["backend/util.py"],
            },
        }
        knowledge.write_index(shared_path, index)

        # List all records
        r = self.http.get("/api/v1/projects/digital-hr/knowledge/records")
        self.assertEqual(r.status, 200, r.text)
        items = r.json["items"]
        self.assertEqual(len(items), 2)

        # Filter verified
        r_ver = self.http.get("/api/v1/projects/digital-hr/knowledge/records?filter=verified")
        self.assertEqual(len(r_ver.json["items"]), 1)
        self.assertEqual(r_ver.json["items"][0]["key"], "run-test-1")

        # Filter inferred
        r_inf = self.http.get("/api/v1/projects/digital-hr/knowledge/records?filter=inferred")
        self.assertEqual(len(r_inf.json["items"]), 1)
        self.assertEqual(r_inf.json["items"][0]["key"], "pr-42")

        # Search query
        r_q = self.http.get("/api/v1/projects/digital-hr/knowledge/records?q=main.py")
        self.assertEqual(len(r_q.json["items"]), 1)
        self.assertEqual(r_q.json["items"][0]["key"], "run-test-1")

        # Read single record
        r_rec = self.http.get("/api/v1/projects/digital-hr/knowledge/records/run-test-1")
        self.assertEqual(r_rec.status, 200, r_rec.text)
        self.assertEqual(r_rec.json["key"], "run-test-1")
        self.assertIn("Feature X implemented", r_rec.json["body"])

        # Not found record
        self.assertEqual(self.http.get("/api/v1/projects/digital-hr/knowledge/records/nonexistent").status, 404)

    def test_knowledge_ingest_and_snapshot(self):
        self.serve()
        with mock.patch("kb_worker.spawn_worker") as mock_spawn:
            # POST ingest
            r_ing = self.http.post("/api/v1/projects/digital-hr/knowledge/ingest", {})
            self.assertEqual(r_ing.status, 202, r_ing.text)
            self.assertTrue(r_ing.json["ok"])
            self.assertEqual(r_ing.json["state"], "queued")
            mock_spawn.assert_called()

            # Audit row for ingest
            r_audit = self.http.get("/api/v1/audit?project=digital-hr")
            ingest_audits = [a for a in r_audit.json["items"] if a["action"] == "knowledge_ingest"]
            self.assertTrue(len(ingest_audits) > 0)

            # POST snapshot
            r_snap = self.http.post("/api/v1/projects/digital-hr/knowledge/snapshot", {})
            self.assertEqual(r_snap.status, 202, r_snap.text)
            self.assertTrue(r_snap.json["ok"])
            self.assertEqual(r_snap.json["state"], "queued")

            # Audit row for snapshot
            r_audit = self.http.get("/api/v1/audit?project=digital-hr")
            snap_audits = [a for a in r_audit.json["items"] if a["action"] == "knowledge_snapshot"]
            self.assertTrue(len(snap_audits) > 0)

    def test_knowledge_backfill_estimate_and_run(self):
        self.serve()
        # POST estimate
        r_est = self.http.post("/api/v1/projects/digital-hr/knowledge/backfill/estimate", {})
        self.assertEqual(r_est.status, 200, r_est.text)
        token = r_est.json["token"]
        self.assertTrue(token)
        self.assertIn("estimate", r_est.json)

        # POST backfill without token -> refusal
        r_fail = self.http.post("/api/v1/projects/digital-hr/knowledge/backfill", {})
        self.assertEqual(r_fail.status, 400)
        self.assertEqual(r_fail.code, "E_VALIDATION")

        # POST backfill with wrong token -> refusal
        r_fail2 = self.http.post("/api/v1/projects/digital-hr/knowledge/backfill", {"token": "invalid-token"})
        self.assertEqual(r_fail2.status, 400)

        # POST backfill with valid token
        with mock.patch("knowledge.ingest", return_value={"backend": {"main": 3}}):
            r_run = self.http.post("/api/v1/projects/digital-hr/knowledge/backfill", {"token": token})
            self.assertEqual(r_run.status, 200, r_run.text)
            self.assertTrue(r_run.json["ok"])
            self.assertEqual(r_run.json["total"], 3)

        # Audit row for backfill
        r_audit = self.http.get("/api/v1/audit?project=digital-hr")
        bf_audits = [a for a in r_audit.json["items"] if a["action"] == "knowledge_backfill"]
        self.assertTrue(len(bf_audits) > 0)

    def test_knowledge_ci_template(self):
        self.serve()
        # Happy path for backend repo
        r = self.http.get("/api/v1/projects/digital-hr/knowledge/ci-template?repo=backend")
        self.assertEqual(r.status, 200, r.text)
        data = r.json
        self.assertEqual(data["repo"], "backend")
        self.assertIn("REPO_ID: backend", data["template"])
        self.assertIn("REPO_PROFILE: generic", data["template"])
        self.assertIn("TRACKED_BRANCHES:", data["template"])

        # Missing repo param -> 400
        r_bad = self.http.get("/api/v1/projects/digital-hr/knowledge/ci-template")
        self.assertEqual(r_bad.status, 400)

        # Unknown repo -> 404
        r_404 = self.http.get("/api/v1/projects/digital-hr/knowledge/ci-template?repo=nonexistent")
        self.assertEqual(r_404.status, 404)

    def test_knowledge_auth_and_csrf_refusals(self):
        self.serve()
        unauth = Http(self.srv.port)
        self.assertEqual(unauth.get("/api/v1/projects/digital-hr/knowledge/status").status, 401)
        self.assertEqual(unauth.get("/api/v1/projects/digital-hr/knowledge/records").status, 401)
        self.assertEqual(unauth.get("/api/v1/projects/digital-hr/knowledge/records/rec1").status, 401)
        self.assertEqual(unauth.get("/api/v1/projects/digital-hr/knowledge/ci-template?repo=backend").status, 401)
        self.assertEqual(unauth.post("/api/v1/projects/digital-hr/knowledge/ingest", {}).status, 401)
        self.assertEqual(unauth.post("/api/v1/projects/digital-hr/knowledge/snapshot", {}).status, 401)
        self.assertEqual(unauth.post("/api/v1/projects/digital-hr/knowledge/backfill/estimate", {}).status, 401)
        self.assertEqual(unauth.post("/api/v1/projects/digital-hr/knowledge/backfill", {"token": "x"}).status, 401)

        # CSRF refusal for mutating endpoints
        self.assertEqual(self.http.post("/api/v1/projects/digital-hr/knowledge/ingest", {}, csrf="bad").status, 403)
        self.assertEqual(self.http.post("/api/v1/projects/digital-hr/knowledge/snapshot", {}, csrf="bad").status, 403)
        self.assertEqual(self.http.post("/api/v1/projects/digital-hr/knowledge/backfill/estimate", {}, csrf="bad").status, 403)
        self.assertEqual(self.http.post("/api/v1/projects/digital-hr/knowledge/backfill", {"token": "x"}, csrf="bad").status, 403)


if __name__ == "__main__":
    unittest.main()
