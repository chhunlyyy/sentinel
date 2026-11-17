"""Phase H part C: MUST rows of SPEC.md that no earlier scenario tags (AC-OPS-04l). A test covers a requirement
when `REQ_<ID>` is in its name; tests/test_docs.py reads those names."""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import yaml

from sv_helpers import SV, SLUG

ROOT = Path(__file__).resolve().parent.parent
CLI = [sys.executable, str(ROOT / "sentinel" / "scripts" / "sentinel.py")]
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", "PYTHONDONTWRITEBYTECODE": "1"}


class Requirements(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.env = {**ENV, "HOME": str(self.root / "home")}
        (self.root / "home").mkdir()

    def cli(self, ws, *args):
        r = subprocess.run(CLI + ["--dir", str(ws), *args], capture_output=True, text=True, env=self.env, cwd=ws, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr

    def workspace(self, files=("a.txt",)):
        ws = self.root / "ws"
        (ws / "app").mkdir(parents=True)
        for f in files:
            (ws / "app" / f).write_text("x\n")
        for cmd in (["init", "-q", "-b", "main"], ["add", "."], ["commit", "-qm", "i"]):
            subprocess.run(["git", *cmd], cwd=ws / "app", env=self.env, capture_output=True, check=True)
        return ws

    def test_REQ_ARC_04_the_package_has_no_empty_directories(self):
        empty = [str(p.relative_to(ROOT)) for p in (ROOT / "sentinel").rglob("*")
                 if p.is_dir() and "__pycache__" not in p.parts and "dashboard_dist" not in p.parts and not any(p.iterdir())]
        self.assertEqual(empty, [])

    def test_REQ_ART_04_clean_keeps_the_newest_runs_the_retention_names(self):
        ws = self.workspace()
        code, out = self.cli(ws, "init", "--non-interactive", "--local-only", "--shape", "single", "--set", "app.path=./app")
        self.assertEqual(code, 0, out)
        import yaml
        cfg = ws / "sentinel.config.yaml"
        data = yaml.safe_load(cfg.read_text())
        data["state"]["retention"] = {"runs": 2, "logs_days": 14}
        cfg.write_text(yaml.safe_dump(data, sort_keys=False))
        runs = ws / ".sentinel" / "runs"
        for i, name in enumerate(["old-1", "old-2", "mid", "new"]):
            (runs / name).mkdir(parents=True)
            os.utime(runs / name, (time.time() - 1000 + i * 100,) * 2)
        code, out = self.cli(ws, "clean")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in runs.iterdir()), ["mid", "new"])

    def test_REQ_PRV_04_no_provider_api_keys_are_stored_or_served(self):
        """The config has no place for a key: a provider, runner or agent entry with an api key is refused by the schema, doctor
        reports it, and the server has no route that serves keys."""
        import jsonschema
        schema = json.loads((ROOT / "sentinel" / "core" / "schema" / "config.schema.json").read_text())
        validator = jsonschema.Draft202012Validator(schema)
        ws = self.workspace()
        code, out = self.cli(ws, "init", "--non-interactive", "--local-only", "--shape", "single", "--set", "app.path=./app")
        self.assertEqual(code, 0, out)
        base = yaml.safe_load((ws / "sentinel.config.yaml").read_text())
        self.assertEqual([e.message for e in validator.iter_errors(base)], [])
        bad = {"providers": {"claude": {"api_key": "sk-ant-secret"}}}, {"runners": {"x": {"command": "c", "api_key": "sk-ant-secret"}}}, \
              {"agents": {"coder": {"runner": "x", "apikey": "sk-ant-secret"}}}
        for extra in bad:
            with self.subTest(extra=list(extra)):
                self.assertTrue(list(validator.iter_errors({**base, **extra})), "the schema accepted a key")
        (ws / "sentinel.config.yaml").write_text(yaml.safe_dump({**base, **bad[1]}, sort_keys=False))
        code, out = self.cli(ws, "doctor")
        self.assertNotEqual(code, 0, out)
        self.assertNotIn("sk-ant-secret", out)

    def test_REQ_REP_06_init_detects_the_stack_with_detect_profile(self):
        ws = self.workspace(files=("pubspec.yaml",))
        code, out = self.cli(ws, "init", "--non-interactive", "--local-only", "--shape", "single", "--set", "app.path=./app")
        self.assertEqual(code, 0, out)
        import yaml
        cfg = yaml.safe_load((ws / "sentinel.config.yaml").read_text())
        self.assertEqual(cfg["repos"][0]["profile"], "flutter")

    def test_AC_OPS_03d_run_new_type_is_one_of_the_documented_types(self):
        ws = self.workspace()
        code, out = self.cli(ws, "init", "--non-interactive", "--local-only", "--shape", "single", "--set", "app.path=./app")
        self.assertEqual(code, 0, out)
        code, out = self.cli(ws, "run", "new", "bad-type", "--type", "feture")
        self.assertEqual(code, 5, out)
        self.assertIn("E_VALIDATION", out)
        for typ in ("feature", "bug", "docs", "refactor", "migration", "security", "chore"):
            self.assertIn(typ, out)
        self.assertFalse((ws / ".sentinel" / "runs" / "bad-type").exists())
        for typ in ("migration", "security"):
            with self.subTest(type=typ):
                code, out = self.cli(ws, "run", "new", f"ok-{typ}", "--type", typ)
                self.assertEqual(code, 0, out)

    def test_REQ_TST_02_the_tests_are_stdlib_unittest_under_tests(self):
        mods = sorted((ROOT / "tests").glob("test_*.py"))
        self.assertGreater(len(mods), 40)
        using = [m for m in mods if re.search(r"\bunittest\b|\b(SV|PCX|PDX|PEX|PBX|NT)\b", m.read_text())]
        self.assertEqual([m.name for m in mods if m not in using], [])
        for m in mods:
            self.assertNotRegex(m.read_text(), r"(?m)^\s*(import|from) pytest\b")
        self.assertFalse(list((ROOT / "tests").glob("conftest.py")))

    # REQ-TST-06 is a statement about how the work was done; the only observable evidence is the status file, so this stays a document check.
    def test_REQ_TST_06_each_phase_has_evidence_in_the_implementation_status(self):
        text = (ROOT / "IMPLEMENTATION_STATUS.md").read_text()
        for phase in "ABCDEFGH":
            self.assertRegex(text, rf"(?m)^\| P{phase}-00 \|.*Completed", f"Phase {phase} Gherkin row")
        self.assertGreaterEqual(len(re.findall(r"(?mi)^- (Evidence|Red recorded)|\bEvidence\b[^\n]*(unittest|selftest)", text)), 5)
        for phase in ("Phase D notes", "Phase F notes", "Phase G notes", "Phase H notes"):
            self.assertIn(phase, text)


WRITES = ("insert_run", "update_run", "add_run_repo", "add_event", "insert_row", "update_row", "add_task_dep", "add_trace_link")
SCRIPTS = ROOT / "sentinel" / "scripts"


class EngineOwnsState(SV):
    def test_REQ_ARC_01_runs_change_only_through_engine_methods(self):
        """The API routes and the CLI never write run state themselves: every registry write made while the API creates and
        cancels a run is issued by an engine module, never by apiserver/ or sentinel.py, and the engine recorded the events."""
        from registry import Registry
        callers = []
        patches = []
        for name in WRITES:
            orig = getattr(Registry, name)

            def spy(self_, *a, _orig=orig, **kw):
                callers.append(Path(sys._getframe(1).f_code.co_filename).resolve())
                return _orig(self_, *a, **kw)
            patches.append(mock.patch.object(Registry, name, spy))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.serve()
        r = self.http.post("/api/v1/projects/digital-hr/tasks", {"slug": "arc-run", "request": "x", "type": "feature"})
        self.assertEqual(r.status, 201, r.text)
        r = self.http.post("/api/v1/tasks/arc-run/control", {"action": "cancel", "comment": "test"})
        self.assertEqual(r.status, 200, r.text)
        self.assertTrue(callers)
        files = {c.name for c in callers}
        for c in callers:
            self.assertNotIn("apiserver", c.parts, f"a route wrote registry state itself: {c}")
            self.assertEqual(c.parent, SCRIPTS, c)
            self.assertNotEqual(c.name, "sentinel.py", c)
        self.assertIn("engine.py", files)
        types = [e["type"] for e in self.events_rows()]
        self.assertIn("run.created", types)
        self.assertIn("run.state_changed", types)
        # the CLI: `run new` is recorded as an engine event, with the engine's actor
        env = {**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        out = subprocess.run(CLI + ["--dir", str(self.ws), "run", "new", "cli-run", "--type", "feature"], capture_output=True, text=True,
                             env=env, cwd=self.ws, stdin=subprocess.DEVNULL)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        rows = [e for e in self.events_rows(type="run.created")]
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual(rows[-1]["actor"], "orchestrator")

    def test_REQ_ARC_01_the_only_direct_registry_writes_outside_the_engine_are_the_legacy_mirror_and_audit_rows(self):
        pattern = re.compile(r"\.(" + "|".join(WRITES) + r")\(")
        found = {}
        for f in [SCRIPTS / "sentinel.py"] + sorted((SCRIPTS / "apiserver").glob("*.py")):
            hits = [m.group(1) for m in pattern.finditer(f.read_text())]
            if hits:
                found[f.name] = hits
        self.assertEqual(found, {"sentinel.py": ["update_run"]})  # the 0.1 `run finish` status mirror (workflow version 0.1 only)


class ProjectsAndRepos(SV):
    def test_REQ_PRJ_01_the_dashboard_shows_the_values_of_the_config_file_and_follows_edits(self):
        """A project is the workspace folder that holds sentinel.config.yaml, and the file stays the source of truth."""
        self.use_config(limits={"review_rounds": 4})
        self.serve()
        items = {i["key"]: i["value"] for i in self.http.get("/api/v1/projects/digital-hr/configuration").json["items"]}
        file_cfg = yaml.safe_load((self.ws / "sentinel.config.yaml").read_text())
        self.assertEqual(items["limits.review_rounds"], file_cfg["limits"]["review_rounds"])
        self.assertEqual(items["limits.review_rounds"], 4)
        project = next(p for p in self.http.get("/api/v1/projects").json["items"] if p["id"] == "digital-hr")
        self.assertEqual(Path(project["path"]), self.ws)
        self.assertTrue((Path(project["path"]) / "sentinel.config.yaml").exists())
        file_cfg["limits"]["review_rounds"] = 6  # the user edits the file; the dashboard follows without a restart
        (self.ws / "sentinel.config.yaml").write_text(yaml.safe_dump(file_cfg, sort_keys=False))
        r = self.http.get("/api/v1/projects/digital-hr/configuration")
        self.assertEqual({i["key"]: i["value"] for i in r.json["items"]}["limits.review_rounds"], 6)
        import hashlib
        self.assertEqual(r.json["sha256"], hashlib.sha256((self.ws / "sentinel.config.yaml").read_bytes()).hexdigest())

    def test_REQ_REP_07_a_run_targets_the_repos_it_names_or_all_of_them(self):
        self.serve()
        url = "/api/v1/projects/digital-hr/tasks"
        rows = {"one": ["backend"], "both": ["backend", "frontend"], "all": None}
        for slug, repos in rows.items():
            with self.subTest(slug=slug):
                body = {"slug": f"t-{slug}", "request": "x", "type": "feature"}
                if repos is not None:
                    body["repos"] = repos
                r = self.http.post(url, body)
                self.assertEqual(r.status, 201, r.text)
                got = {x["repo_id"] for x in self.eng.reg.run_repos(self.eng.reg.get_run(f"t-{slug}")["id"])}
                self.assertEqual(got, set(repos or ["backend", "frontend"]))
        r = self.http.post(url, {"slug": "t-bad", "request": "x", "type": "feature", "repos": ["nope"]})
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)
        self.assertIsNone(self.eng.reg.get_run("t-bad"))
        env = {**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        out = subprocess.run(CLI + ["--dir", str(self.ws), "run", "new", "t-cli", "--type", "feature", "--repos", "frontend"],
                             capture_output=True, text=True, env=env, cwd=self.ws, stdin=subprocess.DEVNULL)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        db = sqlite3.connect(self.ws / ".sentinel" / "sentinel.db")
        self.addCleanup(db.close)
        rows = db.execute("SELECT rr.repo_id FROM run_repos rr JOIN runs r ON r.id = rr.run_id WHERE r.slug = 't-cli'").fetchall()
        self.assertEqual(rows, [("frontend",)])

    def test_REQ_PRV_04_the_server_has_no_route_that_serves_keys(self):
        self.serve()
        for path in ("/api/v1/secrets", "/api/v1/keys", "/api/v1/providers/keys", "/api/v1/projects/digital-hr/secrets"):
            with self.subTest(path=path):
                self.assertEqual(self.http.get(path).status, 404)


if __name__ == "__main__":
    unittest.main()
