"""Dashboard management routes: providers, agents, project creation, repositories, profiles, orchestrator."""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from sv_helpers import SV, GIT_ENV, SENTINEL


class M(SV):
    def put(self, path, body, **kw):
        return self.http.req("PUT", path, body=body, **kw)

    def delete(self, path, **kw):
        return self.http.req("DELETE", path, **kw)

    def tmpdir(self):
        d = tempfile.mkdtemp(prefix="mng-")
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return Path(d)

    def repo_dir(self, parent, name, marker=None):
        p = parent / name
        p.mkdir()
        if marker:
            (p / marker).write_text("{}")
        return p

    def cfg_text(self):
        return (self.ws / "sentinel.config.yaml").read_text()

    def fake_cli(self):
        f = self.tmpdir() / "fakecli"
        f.write_text("#!/bin/sh\necho fakecli 9.9\n")
        f.chmod(0o755)
        return f

    def with_runner(self):
        f = self.fake_cli()
        self.use_config(runners={"fakecli": {"command": str(f)}})
        return f


class Providers(M):
    def test_providers_lists_runners(self):
        f = self.with_runner()
        self.serve()
        r = self.http.get("/api/v1/providers?project=digital-hr")
        self.assertEqual(r.status, 200, r.text)
        items = {i["id"]: i for i in r.json["items"]}
        self.assertEqual([i["id"] for i in r.json["items"]][:4], ["claude", "codex", "gemini", "agy"])
        self.assertTrue(items["fakecli"]["installed"])
        self.assertEqual(items["fakecli"]["path"], str(f))
        self.assertIn("orchestrator", r.json)

    def test_probe(self):
        self.with_runner()
        self.serve()
        r = self.http.post("/api/v1/providers/fakecli/test?project=digital-hr", {})
        self.assertEqual(r.status, 200, r.text)
        self.assertTrue(r.json["ok"])
        self.assertIn("9.9", r.json["message"])
        self.assertEqual(self.http.post("/api/v1/providers/nope/test", {}).status, 404)
        self.assertEqual(self.http.post("/api/v1/providers/fakecli/test?project=digital-hr", {}, csrf="bad").status, 403)

    def test_orchestrator_get_put(self):
        self.serve()
        with mock.patch("providers._path", lambda r: "/usr/bin/claude" if r.get("command") == "claude" else None):
            self.assertEqual(self.http.get("/api/v1/orchestrator").json, {"id": None, "installed_ids": ["claude"]})
            r = self.put("/api/v1/orchestrator", {"id": "claude"})
            self.assertEqual((r.status, r.json["id"]), (200, "claude"), r.text)
            self.assertEqual(self.srv.orchestrator, "claude")
            self.assertEqual(self.put("/api/v1/orchestrator", {"id": "codex"}).status, 422)
            self.assertEqual(self.put("/api/v1/orchestrator", {"id": "zzz"}).status, 400)
            self.assertEqual(self.put("/api/v1/orchestrator", {"id": None}).json["id"], None)
            self.assertEqual(self.put("/api/v1/orchestrator", {"id": "claude"}, csrf="bad").status, 403)


class Agents(M):
    def test_get_defaults(self):
        self.serve()
        r = self.http.get("/api/v1/agents?project=digital-hr")
        self.assertEqual(r.status, 200, r.text)
        j = r.json
        self.assertEqual(j["project"], "digital-hr")
        self.assertIn("tdd_green", j["roles"])
        self.assertIn("backend-coder", j["roles"])
        self.assertTrue(all(i["runner"] == "claude" and i["source"] == "default" for i in j["items"]))
        self.assertEqual(j["providers"], {"default": None, "fallback": [], "disabled": []})
        self.assertEqual(len(j["sha256"]), 64)
        self.assertEqual(self.http.get("/api/v1/agents?project=nope").status, 404)

    def test_put_project_writes_config_and_history(self):
        self.serve()
        sha = self.http.get("/api/v1/agents?project=digital-hr").json["sha256"]
        r = self.put("/api/v1/agents", {"project": "digital-hr", "scope": "project", "sha256": sha, "single_model": False,
                                        "agents": {"reviewer": {"runner": "codex", "model": "gpt-5"}},
                                        "providers": {"default": "codex", "fallback": ["claude"]}})
        self.assertEqual(r.status, 200, r.text)
        item = next(i for i in r.json["items"] if i["role"] == "reviewer")
        self.assertEqual((item["runner"], item["model"], item["source"]), ("codex", "gpt-5", "project"))
        self.assertFalse(r.json["single_model"])
        cfg = yaml.safe_load(self.cfg_text())
        self.assertEqual(cfg["agents"]["reviewer"], {"runner": "codex", "model": "gpt-5"})
        self.assertEqual(cfg["providers"]["default"], "codex")
        self.assertEqual(cfg["repos"][0]["id"], "backend")
        hist = self.http.get("/api/v1/projects/digital-hr/configuration/history").json["items"]
        self.assertEqual(hist[0]["channel"], "dashboard")
        self.assertEqual(hist[0]["author"], "dev")
        # stale sha
        r = self.put("/api/v1/agents", {"project": "digital-hr", "scope": "project", "sha256": sha, "agents": {}})
        self.assertEqual((r.status, r.code), (409, "E_PRECONDITION"))
        # clearing a value
        r = self.put("/api/v1/agents", {"project": "digital-hr", "scope": "project", "agents": {"reviewer": {"runner": None, "model": None}}})
        self.assertEqual(r.status, 200, r.text)
        self.assertNotIn("reviewer", yaml.safe_load(self.cfg_text()).get("agents", {}))

    def test_put_validation(self):
        self.serve()
        before = self.cfg_text()
        for body in ({"scope": "project", "agents": {}},
                     {"project": "digital-hr", "scope": "x"},
                     {"project": "digital-hr", "scope": "project", "agents": {"qa": {"runner": "nope"}}},
                     {"project": "digital-hr", "scope": "project", "agents": {"qa": {"model": "--evil x"}}},
                     {"project": "digital-hr", "scope": "project", "providers": {"fallback": ["nope"]}},
                     {"project": "digital-hr", "scope": "project", "agents": {"qa": {"bogus": 1}}},
                     {"project": "digital-hr", "scope": "project", "extra": 1}):
            r = self.put("/api/v1/agents", body)
            self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), (body, r.text))
        self.assertEqual(self.put("/api/v1/agents", {"project": "nope", "scope": "project"}).status, 404)
        self.assertEqual(self.put("/api/v1/agents", {"project": "digital-hr", "scope": "project"}, csrf="bad").status, 403)
        self.assertEqual(before, self.cfg_text())

    def test_global_scope_and_seeding(self):
        self.serve()
        r = self.put("/api/v1/agents", {"scope": "global", "agents": {"qa": {"runner": "gemini"}}, "providers": {"default": "gemini"}})
        self.assertEqual(r.status, 200, r.text)
        gf = self.cfgdir / "config.yaml"
        self.assertEqual(stat.S_IMODE(gf.stat().st_mode), 0o600)
        self.assertEqual(yaml.safe_load(gf.read_text()), {"agents": {"qa": {"runner": "gemini"}}, "providers": {"default": "gemini"}})
        j = self.http.get("/api/v1/agents?project=digital-hr").json
        qa = next(i for i in j["items"] if i["role"] == "qa")
        self.assertEqual((qa["runner"], qa["source"]), ("gemini", "global"))
        self.assertEqual(j["providers"]["default"], "gemini")
        self.assertEqual(self.put("/api/v1/agents", {"scope": "global", "single_model": True}).status, 400)
        # a new project is seeded
        base = self.tmpdir()
        repo = self.repo_dir(base, "app")
        r = self.http.post("/api/v1/projects", {"name": "Seeded", "path": str(base / "ws"), "repos": [{"path": str(repo), "role": "app"}]})
        self.assertEqual(r.status, 201, r.text)
        cfg = yaml.safe_load((base / "ws" / "sentinel.config.yaml").read_text())
        self.assertEqual(cfg["agents"], {"qa": {"runner": "gemini"}})
        self.assertEqual(cfg["providers"], {"default": "gemini"})


class Projects(M):
    def create(self, base, **over):
        repo = self.repo_dir(base, "api", "package.json") if not (base / "api").exists() else base / "api"
        body = {"name": "New One", "path": str(base / "ws"), "repos": [{"path": str(repo), "role": "backend"}]}
        body.update(over)
        return self.http.post("/api/v1/projects", body)

    def test_create_project(self):
        self.serve()
        base = self.tmpdir()
        r = self.create(base)
        self.assertEqual(r.status, 201, r.text)
        self.assertEqual(r.json["name"], "New One")
        self.assertEqual(r.json["status"], "available")
        cfg = yaml.safe_load((base / "ws" / "sentinel.config.yaml").read_text())
        self.assertEqual(cfg["repos"], [{"id": "api", "path": str(base / "api"), "role": "backend", "profile": "node"}])
        self.assertEqual(cfg["state"]["shared_mode"], "local")
        self.assertTrue((base / "ws" / ".sentinel" / "runs").is_dir())
        self.assertIn(".sentinel/runs/", (base / "ws" / ".gitignore").read_text())
        self.assertEqual(self.http.get(f"/api/v1/projects/{r.json['id']}").status, 200)
        self.assertEqual(self.create(base).status, 409)

    def test_create_inside_repo_is_relative_and_git_mode(self):
        self.serve()
        base = self.tmpdir()
        ws = base / "ws"
        ws.mkdir()
        self.repo_dir(ws, "web", "next.config.js")
        r = self.http.post("/api/v1/projects", {"name": "W", "path": str(ws), "shared": {"mode": "git", "url": "https://example.com/x/y.git"},
                                                "repos": [{"path": "web", "role": "frontend", "id": "web"}]})
        self.assertEqual(r.status, 201, r.text)
        cfg = yaml.safe_load((ws / "sentinel.config.yaml").read_text())
        self.assertEqual(cfg["repos"][0]["path"], "./web")
        self.assertEqual(cfg["state"]["shared_repo"], "https://example.com/x/y.git")

    def test_create_validation(self):
        self.serve()
        base = self.tmpdir()
        repo = self.repo_dir(base, "r")
        good = {"name": "x", "path": str(base / "ws"), "repos": [{"path": str(repo), "role": "app"}]}
        cases = [{**good, "repos": []}, {**good, "path": "rel"}, {**good, "path": str(base / "no" / "ws")},
                 {**good, "repos": [{"path": str(base / "missing"), "role": "app"}]},
                 {**good, "repos": [{"path": "../x", "role": "app"}]},
                 {**good, "repos": [{"path": str(repo), "role": "Bad Role"}]},
                 {**good, "repos": [{"path": str(repo), "role": "app", "profile": "nope"}]},
                 {**good, "shared": {"mode": "git"}}, {**good, "shared": {"mode": "x"}}, {**good, "name": ""},
                 {**good, "path": "/tmp/a\u0000b"}, {**good, "extra": 1},
                 {**good, "repos": [{"path": str(repo), "role": "app", "id": "a"}, {"path": str(repo), "role": "app", "id": "a"}]}]
        for body in cases:
            r = self.http.post("/api/v1/projects", body)
            self.assertIn(r.status, (400, 409), (body, r.text))
        self.assertFalse((base / "ws").exists())
        self.assertEqual(self.http.post("/api/v1/projects", good, csrf="bad").status, 403)

    def test_register(self):
        self.serve()
        d = self.tmpdir()
        self.assertEqual(self.http.post("/api/v1/projects/register", {"path": str(d)}).status, 404)
        (d / "sentinel.config.yaml").write_text("not: [valid")
        self.assertEqual(self.http.post("/api/v1/projects/register", {"path": str(d)}).status, 409)
        (d / "sentinel.config.yaml").write_text(yaml.safe_dump(self.config))
        r = self.http.post("/api/v1/projects/register", {"path": str(d)})
        self.assertEqual(r.status, 201, r.text)
        self.assertEqual(self.http.post("/api/v1/projects/register", {"path": str(d)}).status, 200)

    def test_repositories_add_remove(self):
        self.serve()
        base = self.tmpdir()
        mob = self.repo_dir(base, "mobile-app", "pubspec.yaml")
        r = self.http.post("/api/v1/projects/digital-hr/repositories", {"path": str(mob), "role": "mobile"})
        self.assertEqual(r.status, 201, r.text)
        self.assertEqual((r.json["id"], r.json["profile"]), ("mobile-app", "flutter"))
        ids = [x["id"] for x in self.http.get("/api/v1/projects/digital-hr/repositories").json["items"]]
        self.assertEqual(ids, ["backend", "frontend", "mobile-app"])
        dup = self.http.post("/api/v1/projects/digital-hr/repositories", {"id": "backend", "path": str(mob), "role": "app"})
        self.assertEqual(dup.status, 409)
        self.assertEqual(self.http.post("/api/v1/projects/digital-hr/repositories", {"path": str(base / "zz"), "role": "app"}).status, 400)
        self.assertEqual(self.delete("/api/v1/projects/digital-hr/repositories/mobile-app").status, 200)
        self.assertEqual(self.delete("/api/v1/projects/digital-hr/repositories/mobile-app").status, 404)
        self.assertEqual(self.delete("/api/v1/projects/digital-hr/repositories/frontend", csrf="bad").status, 403)
        self.assertEqual(self.http.get("/api/v1/projects/digital-hr/configuration/history").json["items"][0]["channel"], "dashboard")

    def test_remove_refusals(self):
        self.serve()
        self.assertEqual(self.delete("/api/v1/projects/digital-hr/repositories/frontend").status, 200)
        r = self.delete("/api/v1/projects/digital-hr/repositories/backend")
        self.assertEqual((r.status, r.code), (409, "E_PRECONDITION"))

    def test_remove_refused_with_live_run(self):
        base = self.tmpdir()
        mob = self.repo_dir(base, "m")
        self.serve()
        self.http.post("/api/v1/projects/digital-hr/repositories", {"path": str(mob), "role": "mobile"})
        self.eng.create_run("live-one", "orchestrator", type="feature", baseline={})
        r = self.delete("/api/v1/projects/digital-hr/repositories/m")
        self.assertEqual(r.status, 409, r.text)


class Misc(M):
    def test_fs_dirs(self):
        self.serve()
        base = self.tmpdir()
        (base / "a").mkdir()
        (base / "b" / ".git").mkdir(parents=True)
        (base / ".hidden").mkdir()
        (base / "file.txt").write_text("x")
        r = self.http.get(f"/api/v1/fs/dirs?path={base}")
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual([(i["name"], i["is_git"]) for i in r.json["items"]], [("a", False), ("b", True)])
        self.assertEqual(r.json["parent"], str(base.parent))
        self.assertEqual(self.http.get("/api/v1/fs/dirs?path=/").json["parent"], None)
        self.assertEqual(self.http.get("/api/v1/fs/dirs").status, 200)
        self.assertEqual(self.http.get(f"/api/v1/fs/dirs?path={base}/file.txt").status, 404)
        self.assertEqual(self.http.get("/api/v1/fs/dirs?path=rel").status, 400)
        self.assertEqual(self.http.get("/api/v1/fs/dirs?path=%2Ftmp%2F%00x").status, 400)
        self.assertEqual(self.http.get("/api/v1/fs/dirs", cookie=False).status, 401)

    def test_profiles(self):
        self.serve()
        r = self.http.get("/api/v1/profiles")
        self.assertEqual(r.status, 200, r.text)
        ids = [i["id"] for i in r.json["items"]]
        self.assertIn("node", ids)
        self.assertTrue(all(isinstance(i["detect"], list) for i in r.json["items"]))
        self.assertTrue({"backend", "frontend", "mobile", "app"} <= set(r.json["roles"]))


class Init(unittest.TestCase):
    def test_init_non_interactive_is_unchanged(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        (Path(d) / "app").mkdir()
        (Path(d) / "app" / "package.json").write_text("{}")
        r = subprocess.run([sys.executable, SENTINEL, "--dir", d, "init", "--shape", "single", "--local-only", "--non-interactive"],
                           capture_output=True, text=True, env={**GIT_ENV, "HOME": d})
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = yaml.safe_load((Path(d) / "sentinel.config.yaml").read_text())
        self.assertEqual(cfg["repos"], [{"id": "app", "path": "./app", "role": "app", "profile": "node"}])
        self.assertEqual(cfg["state"]["shared_mode"], "local")
        self.assertEqual(cfg["qa"]["db_clone"], "none")
        self.assertTrue((Path(d) / ".sentinel" / "cache").is_dir())


if __name__ == "__main__":
    unittest.main()
