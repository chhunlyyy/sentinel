"""Phase G: read routes added to the Phase F server (plan/v1.1/phaseG/features/server_read_routes.feature)."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import yaml

from sv_helpers import SV, SENTINEL, GIT_ENV, git
from pc_helpers import REPOS

SECRET = "hunter2-secret"
CMD = {"commands": {"build": "python3 -c pass", "test": "python3 -m pytest", "lint": "python3 -c pass"}}
READY_REPOS = [{**r, **CMD} for r in REPOS]


class RR(SV):
    def setUp(self):
        super().setUp()
        (self.ws / ".env").write_text(f"DB_PASSWORD={SECRET}\n")

    def cfg(self, **extra):
        self.config = {**self.config, **extra}
        self.write_config_file()

    def sql(self, sql, args=()):
        import sqlite3
        c = sqlite3.connect(self.ws / ".sentinel" / "sentinel.db")
        try:
            c.execute(sql, args)
            c.commit()
        finally:
            c.close()

    def run_with_repos(self, slug="leave-balance"):
        base = {r["id"]: git(self.ws / r["path"], "rev-parse", "HEAD").strip() for r in REPOS}
        self.eng.create_run(slug, "orchestrator", type="feature", baseline=base)
        return slug

    def write(self, repo, rel, text):
        p = self.ws / repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text) if isinstance(text, str) else p.write_bytes(text)

    def path_of(self, p):
        return self.ws / p


class Health(RR):
    def test_AC_INS_03e_the_health_answer(self):
        self.serve()
        r = self.http.get("/api/v1/installation/health")
        self.assertEqual(r.status, 200, r.text)
        j = r.json
        self.assertEqual([i["name"] for i in j["items"]], ["installation", "version", "git", "python", "pyyaml",
                                                            "jsonschema", "registry_writable", "provider", "storage",
                                                            "repo_access"])
        for i in j["items"]:
            self.assertTrue({"name", "required", "status", "message", "fix"} <= set(i))
            self.assertIn(i["status"], ("passed", "warning", "failed", "not_configured"))
        self.assertEqual(j["ready"], not any(i["required"] and i["status"] == "failed" for i in j["items"]))

    def test_AC_INS_07a_the_api_and_doctor_run_the_same_checks(self):
        import health
        self.serve()
        calls = []
        real = health.doctor_problems

        def spy(*a, **k):
            calls.append(1)
            return real(*a, **k)
        with mock.patch.object(health, "doctor_problems", spy):
            items = {i["name"]: i["status"] for i in self.http.get("/api/v1/installation/health").json["items"]}
        self.assertTrue(calls, "the API did not call the doctor function")
        code, out = self.run_tty(["doctor"])
        self.assertIn(items["storage"], ("passed", "failed"))
        self.assertEqual(code == 0, items["storage"] == "passed" and items["repo_access"] == "passed" and
                         items["provider"] != "failed", out)
        src = (Path(SENTINEL).parent / "sentinel.py").read_text()
        self.assertIn("health.doctor_problems", src)
        # a problem seen by doctor is a failed item in the API
        self.sql("SELECT 1")
        shutil.rmtree(self.ws / "frontend")
        code, out = self.run_tty(["doctor"])
        self.assertNotEqual(code, 0)
        self.assertIn("repo path missing: frontend", out)
        items = {i["name"]: i["status"] for i in self.http.get("/api/v1/installation/health").json["items"]}
        self.assertEqual(items["repo_access"], "failed")

    def test_AC_INS_03f_a_missing_dependency_fails_its_check_with_a_fix(self):
        problems = {
            "git": lambda: mock.patch.dict(os.environ, {"PATH": "/nonexistent-bin"}),
            "registry_writable": None,
            "provider": None,
        }
        self.serve()
        with problems["git"]():
            j = self.http.get("/api/v1/installation/health").json
        self.assertFalse(j["ready"])
        git_item = next(i for i in j["items"] if i["name"] == "git")
        self.assertEqual(git_item["status"], "failed")
        self.assertTrue(git_item["fix"])
        os.chmod(self.cfgdir, 0o500)
        try:
            if os.access(self.cfgdir, os.W_OK):
                self.skipTest("running as a user that ignores directory modes")
            j = self.http.get("/api/v1/installation/health").json
        finally:
            os.chmod(self.cfgdir, 0o700)
        item = next(i for i in j["items"] if i["name"] == "registry_writable")
        self.assertEqual(item["status"], "failed")
        self.assertTrue(item["fix"])
        self.assertFalse(j["ready"])
        self.cfg(runners={"fake": {"command": "no-such-runner-cli"}})
        j = self.http.get("/api/v1/installation/health").json
        item = next(i for i in j["items"] if i["name"] == "provider")
        self.assertEqual(item["status"], "failed")
        self.assertTrue(item["fix"])
        self.assertFalse(j["ready"])


class Readiness(RR):
    def ready_config(self):
        self.cfg(repos=READY_REPOS)

    def test_AC_DSH_03d_the_readiness_answer(self):
        self.ready_config()
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/readiness")
        self.assertEqual(r.status, 200, r.text)
        j = r.json
        self.assertIn(j["state"], ("ready", "ready_with_warnings", "needs_configuration", "invalid_configuration",
                                   "connection_unavailable"))
        self.assertEqual(j["state"], "ready_with_warnings" if any(i["status"] in ("warning", "failed") for i in j["items"])
                         else "ready")
        for i in j["items"]:
            self.assertTrue({"name", "repo", "required", "status", "message", "fix", "checked_at"} <= set(i))
            if i["status"] == "passed":
                self.assertTrue(i["checked_at"])
            self.assertNotEqual(i["status"], "passed" if i["name"].endswith("_command") else "x")

    def test_AC_DSH_03e_readiness_never_runs_project_commands(self):
        marker = self.ws / "ran.marker"
        cmd = f"python3 -c \"open('{marker}','w').write('x')\""
        self.cfg(repos=[{**REPOS[0], "commands": {"build": cmd, "test": cmd}}, REPOS[1]])
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/readiness")
        self.assertEqual(r.status, 200, r.text)
        self.assertFalse(marker.exists())
        items = {i["name"]: i for i in r.json["items"] if i["repo"] == "backend"}
        self.assertEqual(items["build_command"]["status"], "not_checked")
        self.assertEqual(items["test_command"]["status"], "not_checked")

    def test_AC_DSH_03f_readiness_inputs_and_broken_configurations(self):
        self.ready_config()
        self.serve()
        base = "/api/v1/projects/digital-hr/readiness"
        r = self.http.get(base + "?workflow=party")
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))
        self.assertIn("feature", r.json["error"]["details"]["allowed"])
        cfg_file = self.ws / "sentinel.config.yaml"
        good = cfg_file.read_text()
        cfg_file.write_text(yaml.safe_dump({**self.config, "version": 7}))
        r = self.http.get(base)
        self.assertEqual((r.status, r.json["state"]), (200, "invalid_configuration"))
        self.assertTrue(r.json["errors"] and all({"path", "message"} <= set(e) for e in r.json["errors"]))
        cfg_file.write_text(good)
        os.rename(self.ws / "frontend", self.ws / "frontend.gone")
        r = self.http.get(base)
        self.assertEqual(r.json["state"], "connection_unavailable")
        self.assertTrue(any(i["repo"] == "frontend" and i["status"] == "failed" for i in r.json["items"]))
        os.rename(self.ws / "frontend.gone", self.ws / "frontend")
        notest = [{**r_, "commands": {"build": "python3 -c pass"}} for r_ in REPOS]
        self.cfg(repos=notest)
        self.assertNotEqual(self.http.get(base + "?workflow=docs").json["state"], "needs_configuration")
        r = self.http.get(base + "?workflow=feature")
        self.assertEqual(r.json["state"], "needs_configuration")
        self.assertTrue(any(i["name"] == "test_command" and i["status"] == "failed" for i in r.json["items"]))


class Repositories(RR):
    def test_AC_REP_03a_REQ_REP_01_the_repository_list(self):
        self.cfg(repos=[{**REPOS[1], "commands": {"test": "npm test"}, "guidelines": "g.md"}, REPOS[0]])
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/repositories")
        self.assertEqual(r.status, 200, r.text)
        items = r.json["items"]
        self.assertEqual([i["id"] for i in items], ["frontend", "backend"])
        for k in ("id", "path", "remote", "default_branch", "current_branch", "role", "profile", "commands", "guidelines"):
            self.assertIn(k, items[0])
        self.assertEqual(set(items[0]["commands"]), {"build", "test", "lint", "typecheck", "mutate"})
        self.assertEqual(items[0]["commands"]["test"], "npm test")
        self.assertEqual(items[0]["guidelines"], "g.md")

    def test_AC_REP_03c_remote_urls_are_served_without_credentials(self):
        git(self.ws / "backend", "remote", "add", "origin", "https://dev:ghp_abc123secret@git.example/acme/backend.git")
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/repositories")
        by = {i["id"]: i for i in r.json["items"]}
        self.assertEqual(by["backend"]["remote"], "https://git.example/acme/backend.git")
        self.assertNotIn("ghp_abc123secret", r.text)

    def test_AC_REP_04a_repository_validation(self):
        def item(name):
            r = self.http.get("/api/v1/projects/digital-hr/repositories")
            by = {i["id"]: {v["name"]: v for v in i["validation"]} for i in r.json["items"]}
            self.assertTrue(all(v["status"] == "passed" for v in by["backend"].values()), by["backend"])
            return by["frontend"][name]
        self.serve()
        front = self.ws / "frontend"
        problems = []
        # profile
        self.cfg(repos=[REPOS[0], {**REPOS[1], "profile": "fake-junit"}])
        v = item("profile")
        problems.append(v)
        self.cfg(repos=REPOS)
        # branch: origin/HEAD points to a branch that does not exist
        git(front, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        problems.append(item("branch"))
        git(front, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        # writable
        os.chmod(front, 0o500)
        try:
            if not os.access(front, os.W_OK):
                problems.append(item("writable"))
        finally:
            os.chmod(front, 0o700)
        # not a git repo
        shutil.move(str(front / ".git"), str(self.ws / "gitdir.bak"))
        problems.append(item("git"))
        shutil.move(str(self.ws / "gitdir.bak"), str(front / ".git"))
        # missing folder
        shutil.move(str(front), str(self.ws / "front.bak"))
        problems.append(item("exists"))
        for v in problems:
            self.assertEqual(v["status"], "failed", v)
            self.assertTrue(v["fix"], v)


class Configuration(RR):
    def test_AC_CFG_06a_the_effective_configuration_with_its_sources(self):
        (self.cfgdir).mkdir(parents=True, exist_ok=True)
        (self.cfgdir / "config.yaml").write_text(yaml.safe_dump({"policies": {"task_timeout_seconds": 900}}))
        self.cfg(policies={"task_timeout_seconds": 1200}, repos=[{**REPOS[0], "commands": {"test": "make t"}}, REPOS[1]])
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/configuration")
        self.assertEqual(r.status, 200, r.text)
        j = r.json
        by = {i["key"]: i for i in j["items"]}
        t = by["policies.task_timeout_seconds"]
        self.assertEqual((t["value"], t["source"]), (1200, "project"))
        self.assertIn({"source": "global", "value": 900}, t["overridden"])
        self.assertIn({"source": "default", "value": 5400}, t["overridden"])
        self.assertEqual(by["repos.backend.commands.test"]["source"], "repo:backend")
        self.assertEqual(by["limits.review_rounds"]["source"], "default")
        import hashlib
        self.assertEqual(j["sha256"], hashlib.sha256((self.ws / "sentinel.config.yaml").read_bytes()).hexdigest())

    def test_AC_CFG_06c_configuration_values_are_scrubbed(self):
        self.cfg(policies={"redact_env": ["DB_PASSWORD"]},
                 repos=[{**REPOS[0], "commands": {"build": f"deploy --password {SECRET}"}}, REPOS[1]])
        self.serve()
        a = self.http.get("/api/v1/projects/digital-hr/configuration")
        b = self.http.get("/api/v1/projects/digital-hr/configuration/history")
        self.assertEqual((a.status, b.status), (200, 200))
        self.assertNotIn(SECRET, a.text)
        self.assertNotIn(SECRET, b.text)

    def versions(self):
        for i, n in enumerate((1, 2, 3)):
            self.cfg(limits={"review_rounds": n + 1})
            self.eng.reg.store_config_version("workspace", (self.ws / "sentinel.config.yaml").read_text() + f"\n# {SECRET} v{n}\n",
                                              author="dev", comment=f"c{n}")

    def test_AC_CFG_05a_configuration_history(self):
        self.versions()
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/configuration/history")
        self.assertEqual(r.status, 200, r.text)
        items = r.json["items"]
        self.assertIsNone(r.json["next"])
        self.assertEqual(len(items), 3)
        for k in ("id", "scope", "sha256", "author", "channel", "created_at", "comment"):
            self.assertIn(k, items[0])
        self.assertEqual([i["id"] for i in items], sorted((i["id"] for i in items), reverse=True))

    def test_AC_CFG_05b_diff_between_two_versions(self):
        self.versions()
        self.serve()
        base = "/api/v1/projects/digital-hr/configuration/diff"
        ids = [i["id"] for i in self.http.get("/api/v1/projects/digital-hr/configuration/history").json["items"]][::-1]
        r = self.http.get(f"{base}?a={ids[0]}&b={ids[2]}")
        self.assertEqual(r.status, 200)
        self.assertIn("@@", r.json["diff"])
        self.assertNotIn(SECRET, r.text)
        r = self.http.get(f"{base}?a={ids[1]}&b={ids[1]}")
        self.assertEqual((r.status, r.json["diff"]), (200, ""))
        r = self.http.get(f"{base}?a={ids[0]}&b=99999")
        self.assertEqual((r.status, r.code), (404, "E_NOT_FOUND"))
        r = self.http.get(f"{base}?a=1&b=x")
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))
        r = self.http.get(f"{base}?a={ids[0]}&b=current")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.json["diff"])
        r = self.http.get(f"{base}?a=other-proj&b=1")
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))

    def test_AC_CFG_05c_the_registry_cannot_be_read(self):
        self.serve()
        self.eng.close()
        (self.ws / ".sentinel" / "sentinel.db").write_bytes(b"this is not a database" * 100)
        r = self.http.get("/api/v1/projects/digital-hr/configuration/history")
        self.assertEqual((r.status, r.code), (422, "E_PRECONDITION"))
        self.assertNotIn("Traceback", r.text)


class Changes(RR):
    def changed_run(self):
        slug = self.run_with_repos()
        self.write("backend", "src/main/Leave.java", "class Leave {}\n")
        self.write("backend", "src/main/Other.java", "class Other {}\n")
        self.write("frontend", "a.txt", "a\n")
        return slug

    def committed_change(self, repo, rel, old, new):
        """A tracked file that changes after the baseline: the run is created after the first commit."""
        self.write(repo, rel, old)
        git(self.ws / repo, "add", "-A")
        git(self.ws / repo, "commit", "-q", "-m", "base")

    def test_AC_GIT_01a_the_changes_of_a_run(self):
        self.committed_change("backend", "src/main/Leave.java", "class Leave {}\n", None)
        slug = self.run_with_repos()
        self.write("backend", "src/main/Leave.java", "class Leave { int x; }\n")
        self.write("backend", "src/main/New.java", "class New {}\n")
        self.write("frontend", "a.txt", "a\n")
        self.sql("SELECT 1")
        run = self.eng.reg.get_run(slug)
        self.eng.reg.insert_row("tasks", {"run_id": run["id"], "role": "backend", "repo_id": "backend", "state": "COMPLETED",
                                          "cycle_id": None})
        self.serve()
        r = self.http.get(f"/api/v1/tasks/{slug}/changes")
        self.assertEqual(r.status, 200, r.text)
        repos = {x["repo"]: x for x in r.json["repos"]}
        self.assertEqual(set(repos), {"backend", "frontend"})
        for x in repos.values():
            for k in ("base_sha", "branch", "head_sha", "files"):
                self.assertIn(k, x)
        files = {f["path"]: f for f in repos["backend"]["files"]}
        self.assertEqual(set(files), {"src/main/Leave.java", "src/main/New.java"})
        self.assertEqual(files["src/main/Leave.java"]["status"], "modified")
        self.assertEqual(files["src/main/New.java"]["status"], "added")
        for f in files.values():
            for k in ("path", "status", "additions", "deletions", "binary", "tasks", "cycles"):
                self.assertIn(k, f)
        self.assertEqual([f["path"] for f in repos["frontend"]["files"]], ["a.txt"])

    def diff(self, slug, repo, path, mode):
        from urllib.parse import quote
        return self.http.get(f"/api/v1/tasks/{slug}/changes/diff?repo={quote(repo)}&path={quote(path)}&mode={mode}")

    def test_AC_GIT_01b_diff_of_one_file(self):
        self.committed_change("backend", "src/main/Leave.java", "a\nb\nc\n", None)
        self.committed_change("backend", "src/main/Unchanged.java", "u\n", None)
        slug = self.run_with_repos()
        self.write("backend", "src/main/Leave.java", "a\nB\nc\nd\n")
        self.serve()
        r = self.diff(slug, "backend", "src/main/Leave.java", "inline")
        self.assertEqual(r.status, 200, r.text)
        types = [ln["type"] for h in r.json["hunks"] for ln in h["lines"]]
        self.assertIn("add", types)
        self.assertIn("del", types)
        r = self.diff(slug, "backend", "src/main/Leave.java", "split")
        self.assertEqual(r.status, 200)
        rows = [row for h in r.json["hunks"] for row in h["rows"]]
        self.assertTrue(any(row["old"] and row["new"] and row["old"]["text"] == "b" and row["new"]["text"] == "B" for row in rows))
        for path, mode, status, code in [
                ("src/main/Leave.java", "wide", 400, "E_VALIDATION"),
                ("src/main/Unchanged.java", "inline", 404, "E_NOT_FOUND"),
                ("../../../etc/passwd", "inline", 404, "E_NOT_FOUND"),
                ("/home/dev/.config/sentinel/server.json", "inline", 404, "E_NOT_FOUND")]:
            r = self.diff(slug, "backend", path, mode)
            self.assertEqual((r.status, r.code), (status, code), path)
        r = self.diff(slug, "mobile", "src/main/Leave.java", "inline")
        self.assertEqual((r.status, r.code), (404, "E_NOT_FOUND"))

    def test_AC_SEC_06h_diffs_are_scrubbed(self):
        self.committed_change("backend", "src/main/resources/app.properties", "x=1\n", None)
        slug = self.run_with_repos()
        self.write("backend", "src/main/resources/app.properties", f"x=1\nDB_PASSWORD={SECRET}\n")
        self.serve()
        for mode in ("inline", "split"):
            r = self.diff(slug, "backend", "src/main/resources/app.properties", mode)
            self.assertEqual(r.status, 200, r.text)
            self.assertNotIn(SECRET, r.text)
        self.assertNotIn(SECRET, self.http.get(f"/api/v1/tasks/{slug}/changes").text)

    def test_AC_GIT_01c_binary_and_large_files(self):
        self.committed_change("backend", "same.txt", "same\n", None)
        self.committed_change("backend", "big.txt", "start\n", None)
        slug = self.run_with_repos()
        self.write("backend", "logo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00binary")
        self.write("backend", "big.txt", "".join(f"line {i} {'x' * 90}\n" for i in range(30000)))
        self.write("backend", "same.txt", "same\n")
        self.serve()
        files = {f["path"]: f for f in self.http.get(f"/api/v1/tasks/{slug}/changes").json["repos"][0]["files"]}
        self.assertNotIn("same.txt", files)
        self.assertTrue(files["logo.png"]["binary"])
        r = self.diff(slug, "backend", "logo.png", "inline")
        self.assertEqual((r.status, r.json["binary"], r.json["hunks"]), (200, True, []))
        r = self.diff(slug, "backend", "big.txt", "inline")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.json["truncated"])
        used = sum(len(ln["text"]) + 2 for h in r.json["hunks"] for ln in h["lines"])
        self.assertLessEqual(used, 1024 * 1024 + 1000)
        self.assertGreater(used, 900 * 1024)

    def test_AC_GIT_01d_a_5000_line_diff_is_served_fast(self):
        self.committed_change("backend", "big.txt", "".join(f"l{i}\n" for i in range(5000)), None)
        slug = self.run_with_repos()
        self.write("backend", "big.txt", "".join(f"m{i}\n" for i in range(5000)))
        self.serve()
        for _ in range(10):
            t = time.time()
            r = self.diff(slug, "backend", "big.txt", "split")
            self.assertEqual(r.status, 200)
            self.assertLess(time.time() - t, 1.0)


class Closed(RR):
    def test_AC_INS_06a_mutating_routes_of_the_contract_are_still_not_offered(self):
        self.serve()
        before = sorted(str(p) for p in self.home.rglob("*"))
        for method, path in [("PATCH", "/api/v1/projects/digital-hr"), ("DELETE", "/api/v1/projects/digital-hr"),
                             ("PUT", "/api/v1/projects/digital-hr/configuration"),
                             ("POST", "/api/v1/projects/digital-hr/configuration/restore/1"),
                             ("POST", "/api/v1/projects/digital-hr/configuration/import"),
                             ("POST", "/api/v1/tasks/leave-balance/publish")]:
            r = self.http.req(method, path, body={"a": 1})
            self.assertEqual((r.status, r.code), (404, "E_NOT_FOUND"), (method, path))
        self.assertEqual(before, sorted(str(p) for p in self.home.rglob("*")))

    def test_AC_INS_06b_the_new_routes_have_the_phase_f_checks(self):
        slug = RR.run_with_repos(self)
        self.serve()
        port = self.srv.port
        self.assertEqual(self.http.get("/api/v1/installation/health", cookie=False).status, 401)
        self.assertEqual(self.http.get("/api/v1/projects/digital-hr/readiness", cookie=False).status, 401)
        self.assertEqual(self.http.get("/api/v1/projects/digital-hr/configuration", host=f"evil.example:{port}").status, 403)
        r = self.http.get(f"/api/v1/tasks/{slug}/changes/diff?repo=backend&path=a&mode=inline",
                          origin="http://evil.example")
        self.assertEqual(r.status, 403)
        self.assertEqual(self.http.get("/api/v1/projects/digital-hr/repositories", csrf="").status, 200)


if __name__ == "__main__":
    unittest.main()
