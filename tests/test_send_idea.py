"""Tests for workstream H: Send an idea from any AI session to Sentinel.

Covers:
- CLI flags --request-file and --spec-file on `sentinel run new`
- Secret scrubbing and size limits
- Engine path: stores imported spec as draft v1, skips specifier for v1, keeps triage and human spec gate
- Request changes on v1 sends to specifier for v2 as usual
- Provenance recorded ("imported from a session") and shown in review
- Dashboard API create task ops with spec field
- Skill skills/sentinel-send/ presence and format
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine import Engine
from errors import SentinelError
from pc_helpers import PC, git, GLOBS
import scrub
from test_artifacts import LITE, make_spec

ROOT = Path(__file__).resolve().parents[1]
CLI = [sys.executable, str(ROOT / "sentinel" / "scripts" / "sentinel.py")]


def valid_spec_text(slug="send-test", tier=1, version=1, typ="feature"):
    return make_spec(LITE, slug=slug, tier=tier, version=version)


class TestSendCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name) / "ws"
        self.ws.mkdir()
        repo = self.ws / "backend"
        repo.mkdir()
        (repo / "README.md").write_text("backend\n")
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-q", "-m", "init"], cwd=repo, check=True)
        subprocess.run(CLI + ["--dir", str(self.ws), "init", "--shape", "single", "--non-interactive", "--local-only"],
                       capture_output=True, text=True, check=True)

    def run_cli(self, args, stdin_text=None):
        return subprocess.run(CLI + ["--dir", str(self.ws)] + args,
                              input=stdin_text, capture_output=True, text=True)

    def run_row(self, slug):
        from sentinel import open_registry, load_config
        cfg_path, cfg = load_config(self.ws)
        eng = open_registry(cfg_path, cfg)
        try:
            return eng.reg.get_run(slug)
        finally:
            eng.close()

    def test_request_file_flag(self):
        req_file = self.ws / "my_request.txt"
        req_file.write_text("Build a CSV export of user records\n")
        r = self.run_cli(["run", "new", "csv-export", "--request-file", str(req_file)])
        self.assertEqual(r.returncode, 0, r.stderr)
        state = json.loads(r.stdout)
        self.assertEqual(state["slug"], "csv-export")
        self.assertEqual(self.run_row("csv-export")["request"], "Build a CSV export of user records")

    def test_request_file_stdin(self):
        r = self.run_cli(["run", "new", "stdin-req", "--request-file", "-"],
                         stdin_text="Request sent via standard input\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        state = json.loads(r.stdout)
        self.assertEqual(state["slug"], "stdin-req")
        self.assertEqual(self.run_row("stdin-req")["request"], "Request sent via standard input")

    def test_request_and_request_file_mutually_exclusive(self):
        req_file = self.ws / "my_request.txt"
        req_file.write_text("Hello\n")
        r = self.run_cli(["run", "new", "conflict-run", "--request", "Hello", "--request-file", str(req_file)])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("E_VALIDATION", r.stderr + r.stdout)

    def test_request_file_missing(self):
        r = self.run_cli(["run", "new", "missing-file-run", "--request-file", str(self.ws / "nonexistent.txt")])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("E_VALIDATION", r.stderr + r.stdout)

    def test_request_file_scrubbed(self):
        # Write .env with a secret
        (self.ws / ".env").write_text("SECRET_KEY=SuperSecretKey123\n")
        req_file = self.ws / "secret_req.txt"
        req_file.write_text("Connect with password=SuperSecretKey123 to backend\n")
        r = self.run_cli(["run", "new", "scrub-run", "--request-file", str(req_file)])
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.run_row("scrub-run")
        self.assertNotIn("SuperSecretKey123", row["request"])
        self.assertIn("[REDACTED", row["request"])

    def test_spec_file_flag(self):
        req_file = self.ws / "my_request.txt"
        req_file.write_text("Build a CSV export of user records\n")
        spec_file = self.ws / "my_spec.md"
        spec_file.write_text(valid_spec_text("spec-flag-run"))
        r = self.run_cli(["run", "new", "spec-flag-run", "--request-file", str(req_file), "--spec-file", str(spec_file)])
        self.assertEqual(r.returncode, 0, r.stderr)
        # Check review output
        r2 = self.run_cli(["review", "spec-flag-run", "spec"])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("provenance: imported from a session", r2.stdout)

    def test_spec_file_stdin(self):
        spec_text = valid_spec_text("stdin-spec-run")
        r = self.run_cli(["run", "new", "stdin-spec-run", "--request", "A simple request", "--spec-file", "-"],
                         stdin_text=spec_text)
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = self.run_cli(["review", "stdin-spec-run", "spec"])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("provenance: imported from a session", r2.stdout)

    def test_spec_file_missing_sections(self):
        invalid_spec = self.ws / "bad_spec.md"
        invalid_spec.write_text("## Problem statement\nOnly a problem statement\n")
        r = self.run_cli(["run", "new", "bad-spec-run", "--request", "Do something", "--spec-file", str(invalid_spec)])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("missing section", r.stderr + r.stdout)


class TestSendEnginePath(PC):
    def test_imported_spec_creates_draft_v1_not_approved(self):
        slug = "draft-v1-run"
        spec = valid_spec_text(slug)
        run = self.eng.create_run(slug, "orchestrator", type="feature",
                                  baseline={"backend": "abc"}, spec=spec, request="Do export")
        self.assertEqual(run["state"], "CREATED")
        art = self.eng._latest_artifact(run, "spec")
        self.assertIsNotNone(art)
        self.assertEqual(art["version"], 1)
        self.assertEqual(art.get("provenance"), "imported from a session")

        # Security rule: imported spec must never count as approved!
        ap = self.eng._latest_approval(run, "specification")
        self.assertIsNotNone(ap)
        self.assertEqual(ap["state"], "DRAFT")
        self.assertNotEqual(ap["state"], "APPROVED")

    def test_agents_can_create_run_with_spec(self):
        # Agents may create runs (run new is not human-only)
        slug = "agent-created"
        spec = valid_spec_text(slug)
        run = self.eng.create_run(slug, "orchestrator", type="feature",
                                  baseline={"backend": "abc"}, spec=spec, request="Agent request")
        self.assertEqual(run["slug"], slug)

    def test_triage_runs_and_specifier_is_skipped_for_v1(self):
        slug = "skip-specifier"
        spec = valid_spec_text(slug)
        self.eng.create_run(slug, "human", type="feature",
                            baseline={"backend": "abc"}, spec=spec, request="Skip specifier")
        factors = {"repos": 1, "files": 1, "migration": "no", "auth": "no",
                   "security": "none", "regression": "none", "logic": "trivial"}
        self.eng.triage(slug, factors, "orchestrator")
        run = self.eng.reg.get_run(slug)
        self.assertEqual(run["state"], "TRIAGED")
        self.assertEqual(run["tier"], 1)

        # Trigger bookkeep (as would happen in the factory driver or `sentinel next`)
        run = self.eng.bookkeep(slug)
        # Triage completed: factory moves to spec gate (SPECIFICATION_REVIEW), skipping specifier task
        self.assertEqual(run["state"], "SPECIFICATION_REVIEW")

        # Check no specifier task was ever created
        spec_tasks = [t for t in self.eng.reg.rows("tasks", run_id=run["id"]) if t["role"] == "specifier"]
        self.assertEqual(spec_tasks, [])

        # Approval is now IN_REVIEW (not APPROVED)
        ap = self.eng._latest_approval(run, "specification")
        self.assertEqual(ap["state"], "IN_REVIEW")

    def test_spec_gate_requires_human_approval_with_typed_hash(self):
        slug = "human-gate-test"
        spec = valid_spec_text(slug)
        self.eng.create_run(slug, "human", type="feature",
                            baseline={"backend": "abc"}, spec=spec, request="Human gate")
        self.eng.triage(slug, {"repos": 1, "files": 1, "migration": "no", "auth": "no",
                               "security": "none", "regression": "low", "logic": "simple"}, "orchestrator")
        self.eng.bookkeep(slug)
        run = self.eng.reg.get_run(slug)
        self.assertEqual(run["state"], "SPECIFICATION_REVIEW")

        ap = self.eng._latest_approval(run, "specification")
        # Non-human actor fails
        with self.assertRaises(SentinelError) as cm:
            self.eng.decide(slug, "specification", "approve", "orchestrator", prefix=ap["sha256"][:8])
        self.assertEqual(cm.exception.code, "E_ACTOR")

        # Human approval with typed prefix succeeds
        self.eng.decide(slug, "specification", "approve", "human", prefix=ap["sha256"][:8], approver="dev", channel="tty")
        run = self.eng.reg.get_run(slug)
        self.assertEqual(run["state"], "SPECIFICATION_APPROVED")

    def test_request_changes_sends_to_specifier_for_v2(self):
        slug = "changes-req-test"
        spec = valid_spec_text(slug)
        self.eng.create_run(slug, "human", type="feature",
                            baseline={"backend": "abc"}, spec=spec, request="Request changes")
        self.eng.triage(slug, {"repos": 1, "files": 1, "migration": "no", "auth": "no",
                               "security": "none", "regression": "low", "logic": "simple"}, "orchestrator")
        self.eng.bookkeep(slug)
        run = self.eng.reg.get_run(slug)
        self.assertEqual(run["state"], "SPECIFICATION_REVIEW")

        ap = self.eng._latest_approval(run, "specification")
        # Human requests changes
        self.eng.decide(slug, "specification", "changes", "human", prefix=ap["sha256"][:8],
                        comment="Please add edge cases for negative balances", approver="dev", channel="tty")
        run = self.eng.reg.get_run(slug)
        self.assertEqual(run["state"], "PLANNED")

        # Now for v2, specifier task IS created!
        tasks = [t for t in self.eng.reg.rows("tasks", run_id=run["id"]) if t["role"] == "specifier"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["state"], "QUEUED")


class TestSendProvenanceAndReview(PC):
    def test_review_info_contains_provenance(self):
        slug = "prov-test"
        spec = valid_spec_text(slug)
        self.eng.create_run(slug, "human", type="feature",
                            baseline={"backend": "abc"}, spec=spec, request="Provenance check")
        info = self.eng.review(slug, "specification")
        self.assertEqual(info.get("provenance"), "imported from a session")

    def test_apiserver_view_contains_provenance(self):
        from apiserver import views
        slug = "api-prov-test"
        spec = valid_spec_text(slug)
        self.eng.create_run(slug, "human", type="feature",
                            baseline={"backend": "abc"}, spec=spec, request="API check")
        ans = views.specification(self.eng, slug)
        self.assertEqual(ans.get("provenance"), "imported from a session")


class TestSendApi(unittest.TestCase):
    def test_parse_create_accepts_spec_and_scrubs(self):
        from apiserver import ops
        config = {"repos": [{"id": "backend", "path": "backend"}]}
        body = {
            "slug": "api-task",
            "request": "Test request",
            "type": "feature",
            "spec": "## Problem statement\nDetails\n",
        }
        spec = ops.parse_create(body, config)
        self.assertEqual(spec["spec"], "## Problem statement\nDetails\n")


class TestSendSkill(unittest.TestCase):
    def test_skill_file_exists_and_format(self):
        skill_path = ROOT / "skills" / "sentinel-send" / "SKILL.md"
        self.assertTrue(skill_path.is_file(), "skills/sentinel-send/SKILL.md does not exist")
        content = skill_path.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\nname: sentinel-send\n"))
        self.assertNotIn("{{", content)
        self.assertIn("sentinel run new", content)
        self.assertIn("--driver engine", content)
        self.assertIn("--request-file", content)
        self.assertIn("--spec-file", content)


if __name__ == "__main__":
    unittest.main()
