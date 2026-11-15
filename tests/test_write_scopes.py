"""Phase D part 1 (PD-01): path-level write scopes, profile and repo globs (write_scopes.feature)."""
import json
import os
import sqlite3
import sys
import unittest
from pathlib import Path

import jsonschema
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import scopes  # noqa: E402
from errors import SentinelError  # noqa: E402
from pb_helpers import GOOD, spec_text  # noqa: E402
from pc_helpers import PC, PCX, REPOS, SLUG, git  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "sentinel"
SCHEMA = json.loads((ROOT / "core" / "schema" / "config.schema.json").read_text())
SPRING = {"id": "backend", "path": "backend", "role": "backend", "profile": "spring-gradle"}
FILES = {"src/main/java/leave/LeaveBalance.java": "class LeaveBalance {}\n",
         "src/test/java/leave/LeaveBalanceTest.java": "class LeaveBalanceTest {}\n",
         "docs/leave.md": "# leave\n", ".gitignore": "build/\n"}
LEAVE = "src/main/java/leave/LeaveBalance.java"


def profile(name):
    return json.loads((ROOT / "profiles" / f"{name}.json").read_text())


class Globs(PC):
    def test_AC_CFG_10a_shipped_code_profiles_name_globs_and_test_tooling(self):
        for name in ("spring-gradle", "python", "node", "nextjs", "flutter"):
            with self.subTest(name):
                p = profile(name)
                for key in ("test_globs", "production_globs"):
                    self.assertTrue(isinstance(p[key], list) and p[key] and all(isinstance(g, str) and g for g in p[key]), key)
                for key in ("targeted_test", "test_report", "failure_patterns", "scenario_ref"):
                    self.assertTrue(p.get(key), key)
                self.assertTrue("{tests}" in p["targeted_test"] or "{selectors}" in p["targeted_test"])
                self.assertEqual(p["test_report"]["kind"], "junit-xml")
                self.assertTrue(p["commands"]["test"])
                self.assertTrue(p["lanes"])
                self.assertEqual(scopes.config_problems({"repos": [{**SPRING, "profile": name}]}), [])

    def test_AC_CFG_10a_commands_and_lanes_are_unchanged_from_0_1(self):
        import subprocess
        for name in ("spring-gradle", "python", "node", "nextjs", "flutter", "generic"):
            with self.subTest(name):
                old = subprocess.run(["git", "show", f"HEAD:sentinel/profiles/{name}.json"], capture_output=True, text=True,
                                     cwd=ROOT.parent).stdout
                old = json.loads(old)
                new = profile(name)
                for key in old:
                    self.assertEqual(new[key], old[key], key)

    def test_AC_CFG_10a_generic_profile_ships_without_globs(self):
        p = profile("generic")
        self.assertNotIn("test_globs", p)
        self.assertNotIn("production_globs", p)

    def test_AC_CFG_10b_repo_entry_overrides_profile_globs_key_by_key(self):
        cfg = {"repos": [{**SPRING, "test_globs": ["src/test/**", "src/it/**"]}]}
        got = scopes.effective_globs(cfg, "backend")
        self.assertEqual(got["test_globs"], ["src/test/**", "src/it/**"])
        self.assertEqual(got["production_globs"], ["src/main/**"])
        self.assertEqual(scopes.effective_globs({"repos": [SPRING]}, "backend")["test_globs"], ["src/test/**"])

    def test_AC_CFG_10b_effective_globs_come_from_the_run_config_snapshot(self):
        self.use_config(repos=[{**SPRING, "test_globs": ["src/test/**", "src/it/**"]}, REPOS[1]])
        self.executing()
        self.eng.config = {**self.config, "repos": [SPRING, REPOS[1]]}  # later edit of the live config
        run = self.run_row()
        self.assertEqual(self.eng.repo_globs(run, "backend")["test_globs"], ["src/test/**", "src/it/**"])

    def test_AC_CFG_10c_invalid_glob_list_is_refused_by_config_validation(self):
        rows = [("test_globs", "src/test/**"), ("test_globs", ["/abs/src/**"]), ("production_globs", ["../frontend/**"]),
                ("production_globs", [""]), ("test_globs", [42])]
        for key, value in rows:
            with self.subTest(key=key, value=value):
                cfg = {"version": 1, "shape": "single", "repos": [{**SPRING, key: value}]}
                self.assertEqual([f for f, _ in scopes.config_problems(cfg)], [f"repos[backend].{key}"])
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(cfg, SCHEMA)
        good = {"version": 1, "shape": "single", "repos": [{**SPRING, "test_globs": ["a/**"], "production_globs": ["b/*.py"]}]}
        jsonschema.validate(good, SCHEMA)
        self.assertEqual(scopes.config_problems(good), [])

    def test_AC_CFG_10c_doctor_names_the_field(self):
        (self.ws / "sentinel.config.yaml").write_text(yaml.safe_dump(
            {**self.config, "repos": [{**REPOS[0], "test_globs": "src/test/**"}, REPOS[1]]}, sort_keys=False))
        import subprocess
        from pc_helpers import SENTINEL
        p = subprocess.run([sys.executable, SENTINEL, "--dir", str(self.ws), "doctor"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("repos[backend].test_globs", p.stdout + p.stderr)

    def test_AC_CFG_10d_code_repo_without_usable_globs_cannot_start_execution(self):
        rows = [({}, "test_globs"), ({"test_globs": ["tests/**"]}, "production_globs"),
                ({"test_globs": [], "production_globs": ["**"]}, "test_globs")]
        for i, (setting, missing) in enumerate(rows):
            with self.subTest(missing=missing, i=i):
                repos = [{"id": "backend", "path": "backend", "role": "backend", "profile": "generic", **setting}, REPOS[1]]
                self.use_config(repos=repos)
                slug = f"leave-{i}"
                self.to_gherkin_approved(slug, 3)
                with self.assertRaises(SentinelError):
                    self.eng.advance(slug)
                run = self.run_row(slug)
                self.assertEqual(run["state"], "NEEDS_HUMAN")
                reason = [e for e in self.eng.reg.list_events(run["id"]) if e["type"] == "run.state_changed"][-1]["payload"]["reason"]
                self.assertEqual(reason, f"repo backend has no {missing}")
                self.assertEqual(self.eng.reg.rows("cycles", run_id=run["id"]), [])

    def test_AC_CFG_10d_docs_run_needs_no_globs(self):
        repos = [{"id": "backend", "path": "backend", "role": "backend", "profile": "generic"}, REPOS[1]]
        self.use_config(repos=repos)
        self.to_spec_approved("docs-only", typ="docs")
        self.eng.advance("docs-only")
        self.assertEqual(self.state("docs-only"), "EXECUTING")

    def test_AC_CFG_10e_path_matching_both_lists_is_a_test_file(self):
        cfg = {"repos": [{**REPOS[0], "test_globs": ["src/**/*Test.java"], "production_globs": ["src/**"]}]}
        rows = [("src/main/java/leave/LeaveBalanceTest.java", "test"), ("src/main/java/leave/LeaveBalance.java", "production"),
                ("build.gradle", "other")]
        for path, kind in rows:
            with self.subTest(path=path):
                self.assertEqual(scopes.classify(cfg, "backend", path), kind)


GLOB_ROWS = [
    ("backend/src/main/**", "src/main/java/leave/LeaveBalance.java", True),
    ("backend/src/main/**", "src/mainx/A.java", False),
    ("backend/src/main/*", "src/main/A.java", True),
    ("backend/src/main/*", "src/main/java/A.java", False),
    ("backend/**/*Test.java", "LeaveBalanceTest.java", True),
    ("backend/**/*Test.java", "src/test/java/leave/LeaveBalanceTest.java", True),
    ("backend/src/main/**", "SRC/main/A.java", False),
    ("backend/src/main/**", ".hidden/x", False),
    ("backend/src/main/**", "src/main/.hidden/A.java", True),
    ("backend/docs/a b.md", "docs/a b.md", True),
    ("frontend/src/**", "src/App.tsx", False),
    (None, "docs/leave.md", False),
]


class Matching(unittest.TestCase):
    def test_AC_AGT_06f_glob_matching(self):
        for glob, path, allowed in GLOB_ROWS:
            with self.subTest(glob=glob, path=path):
                self.assertEqual(scopes.path_allowed([] if glob is None else [glob], "backend", path), allowed)

    def test_AC_AGT_06f_wildcard_repo_segment_and_whole_workspace(self):
        self.assertTrue(scopes.path_allowed(["**"], "frontend", "a/b.txt"))
        self.assertTrue(scopes.path_allowed(["*/docs/**"], "frontend", "docs/a.md"))
        self.assertFalse(scopes.path_allowed(["backend/docs/**"], "backend", "docs"))

    def test_AC_TDD_08c_widening_is_refused_with_E_POLICY(self):
        allowed = ["backend/src/test/**"]
        scopes.check_widening("tdd_red", ["backend/src/test/**"], allowed)
        scopes.check_widening("tdd_red", ["backend/src/test/java/**"], allowed)
        for requested in ("backend/src/main/**", "backend/**", "backend/src/test/../main/**", "**"):
            with self.subTest(requested), self.assertRaises(SentinelError) as cm:
                scopes.check_widening("tdd_red", [requested], allowed)
            self.assertEqual(cm.exception.code, "E_POLICY")
            self.assertIn("tdd_red", str(cm.exception))
            self.assertIn(requested, str(cm.exception))


def fake(body):
    return {"fake": (body, {})}


class Repo(PCX):
    """A PCX with committed backend files, spring-gradle globs and a fake runner for the docs role."""
    rows = 0

    def commit_files(self):
        for rel, text in FILES.items():
            p = self.ws / "backend" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        git(self.ws / "backend", "add", "-A")
        git(self.ws / "backend", "commit", "-q", "-m", "files")

    def boot_scope(self, body, agents=None, repos=None, runners=None, **cfg):
        """A fresh EXECUTING run (new slug per call) with the fake runner; the working trees are reset first."""
        for repo in ("backend", "frontend"):
            if (self.ws / repo).exists():
                git(self.ws / repo, "checkout", "-q", "--", ".")
                git(self.ws / repo, "clean", "-fdxq")
        if not (self.ws / "backend" / "docs").exists():
            self.commit_files()
        Repo.rows += 1
        self.slug = f"row-{Repo.rows}"
        self.use_config(single_model=False, repos=repos or [SPRING, REPOS[1]], runners={name: {"command": self.script(name, text)} for name, text in {"fake": body, **(runners or {})}.items()},
                        agents={role: {"runner": r} for role, r in (agents or {"docs": "fake"}).items()}, **cfg)
        return self.executing(self.slug)

    def scope_events(self, tid):
        return [e for e in self.eng.reg.list_events(self.run_row(self.slug)["id"], "task.scope_violation") if e["task_id"] == tid]

    def read(self, rel):
        return (self.ws / "backend" / rel).read_text()


ACTIONS = {
    "edit_doc": ('write("backend/docs/leave.md", "edited\\n")', 0, "COMPLETED", []),
    "create_doc": ('write("backend/docs/new/guide.md")', 0, "COMPLETED", []),
    "edit_prod": (f'write("backend/{LEAVE}", "changed\\n")', 3, "FAILED", [f"backend/{LEAVE}"]),
    "delete_test": ('os.remove(ws + "/backend/src/test/java/leave/LeaveBalanceTest.java")', 3, "FAILED",
                    ["backend/src/test/java/leave/LeaveBalanceTest.java"]),
    "rename": ('os.rename(ws + "/backend/docs/leave.md", ws + "/backend/leave.md")', 3, "FAILED", ["backend/leave.md"]),
    "ignored": ('write("backend/build/out.txt")', 0, "COMPLETED", []),
}


class Violations(Repo):
    def test_AC_AGT_06g_writes_inside_and_outside_the_scope(self):
        for name, (action, code, state, listed) in ACTIONS.items():
            with self.subTest(name):
                self.boot_scope(action + "\nwrite_result()\n")
                tid = self.docs_task(slug=self.slug)
                got, out, err = self.run_json(tid)
                self.assertEqual(got, code, out + err)
                row = self.task(tid)
                self.assertEqual(row["state"], state)
                events = self.scope_events(tid)
                paths = sorted(p for e in events for p in e["payload"]["paths"])
                self.assertEqual(paths, sorted(listed))
                if state == "FAILED":
                    self.assertEqual(row["error_code"], "E_SCOPE")

    def test_AC_AGT_06h_every_violation_is_listed_kept_and_sent_to_a_human(self):
        self.boot_scope(f'write("backend/docs/leave.md", "d\\n")\nwrite("backend/build.gradle", "b\\n")\n'
                        f'write("backend/{LEAVE}", "p\\n")\nwrite_result()\n')
        tid = self.docs_task(slug=self.slug)
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 3, out + err)
        (event,) = self.scope_events(tid)
        self.assertEqual(event["payload"]["kind"], "outside_write_scope")
        self.assertEqual(sorted(event["payload"]["paths"]), ["backend/build.gradle", f"backend/{LEAVE}"])
        self.assertEqual(len(self.states("docs", self.slug)), 1)
        self.assertEqual(self.state(self.slug), "NEEDS_HUMAN")
        reason = [e for e in self.events("run.state_changed", self.slug) if e["payload"]["to"] == "NEEDS_HUMAN"][-1]["payload"]["reason"]
        self.assertIn("scope violation", reason)
        self.assertIn(tid, reason)
        self.assertEqual(self.read("docs/leave.md"), "d\n")
        self.assertEqual(self.read("build.gradle"), "b\n")
        self.assertEqual(self.read(LEAVE), "p\n")
        report = json.loads((self.tdir(tid, self.slug) / "report.json").read_text())
        self.assertEqual(report["write_scope_checked"], ["backend/docs/**"])

    def test_AC_AGT_06i_preexisting_changes_are_judged_by_content_hash(self):
        rows = [('write("backend/docs/leave.md", "e\\n")', 0),
                (f'write("backend/{LEAVE}", "again\\n")', 3),
                (f'p = ws + "/backend/{LEAVE}"\ndata = open(p, "rb").read()\nopen(p, "wb").write(data)', 0)]
        for action, code in rows:
            with self.subTest(action=action):
                self.boot_scope(action + "\nwrite_result()\n")
                (self.ws / "backend" / LEAVE).write_text("uncommitted\n")
                tid = self.docs_task(slug=self.slug)
                got, out, err = self.run_json(tid)
                self.assertEqual(got, code, out + err)

    def test_AC_AGT_06i_a_deleted_file_is_a_change_even_when_nothing_else_changed(self):
        self.boot_scope('os.remove(ws + "/backend/docs/leave.md")\nwrite_result()\n')
        tid = self.docs_task(slug=self.slug)
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(json.loads(self.task(tid)["changed_files"]), ["backend/docs/leave.md"])

    def test_AC_CFG_08b_config_change_during_the_run_does_not_widen_a_running_scope(self):
        edit = ("import yaml\n"
                "p = ws + '/sentinel.config.yaml'\n"
                "c = yaml.safe_load(open(p))\n"
                "c['repos'][0]['test_globs'] = ['**']\n"
                "open(p, 'w').write(yaml.safe_dump(c))\n"
                'write("backend/src/main/java/leave/Extra.java")\nwrite_result()\n')
        self.boot_scope(edit, repos=[{**SPRING, "test_globs": ["src/test/**"]}, REPOS[1]])
        tid = self.docs_task(slug=self.slug)
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 3, out + err)
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
        listed = [p for e in self.scope_events(tid) for p in e["payload"]["paths"]]
        self.assertIn("backend/src/main/java/leave/Extra.java", listed)
        self.assertEqual(self.eng.task_scope(tid), ["backend/docs/**"])
        self.assertEqual(self.eng.repo_globs(self.run_row(self.slug), "backend")["test_globs"], ["src/test/**"])

    def test_AC_AGT_06j_shared_file_authors_write_only_their_own_files(self):
        feature = GOOD["balance.feature"]
        rows = [("specifier", "spec.md", None, 0),
                ("specifier", "features/a.feature", feature, 3),
                ("test_designer", "features/a.feature", feature, 0),
                ("test_designer", "notes.md", "n\n", 3),
                ("test_designer", "backend/src/test/java/leave/PlanTest.java", "t\n", 3)]
        for i, (role, path, text, code) in enumerate(rows):
            with self.subTest(role=role, path=path):
                slug = f"leave-plan-{i}"
                text = spec_text(slug, tier=1) if text is None else text
                if role == "specifier":
                    self.mk(slug, "PLANNED", 1)
                    tid = self.make(role, ["backend"], slug=slug)
                    self.eng.queue_task(tid)
                else:
                    self.to_spec_approved(slug)
                    (tid,) = [t["id"] for t in self.eng.reg.rows("tasks", run_id=self.run_row(slug)["id"])
                              if t["role"] == role and t["state"] == "QUEUED"]
                self.eng.start_task(tid, schedule=False)
                target = self.ws / path if path.startswith("backend/") else self.sdir(slug) / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
                self.write_result(tid, slug=slug)
                row = self.eng.finish_task(tid, exit_code=0)
                self.assertEqual(0 if row["state"] == "COMPLETED" else 3 if row["error_code"] == "E_SCOPE" else 1, code, row)


class Concurrent(Repo):
    def scope_events_all(self):
        return self.events("task.scope_violation", self.slug)

    def two(self, a_body, b_body):
        self.boot_scope("pass\n", agents={"docs": "fa", "hardener": "fb"}, policies={"max_parallel_tasks": 2},
                        runners={"fa": a_body + "\nwrite_result()\n", "fb": b_body + "\nwrite_result()\n"})
        a = self.make("docs", ["backend"], ["backend/docs/**"], slug=self.slug)
        b = self.make("hardener", ["backend"], ["backend/src/main/**"], slug=self.slug)
        for t in (a, b):
            self.eng.queue_task(t)
        procs = [self.popen("task", "run", t) for t in (a, b)]
        return a, b, [self.finish(p) for p in procs]

    def test_AC_AGT_06k_writes_inside_another_running_tasks_scope_are_attributed_to_it(self):
        a, b, results = self.two('write("backend/docs/a.md")\ntime.sleep(2)',
                                 'write("backend/src/main/java/B.java")\ntime.sleep(2)')
        self.assertEqual([r[0] for r in results], [0, 0], results)
        self.assertEqual([self.task(t)["state"] for t in (a, b)], ["COMPLETED", "COMPLETED"])
        self.assertEqual(self.events("task.scope_violation", self.slug), [])

    def test_AC_AGT_06k_attribution_survives_a_task_that_finished_first(self):
        a, b, results = self.two('write("backend/docs/a.md")\ntime.sleep(3)',
                                 'write("backend/src/main/java/B.java")')
        self.assertEqual([r[0] for r in results], [0, 0], results)

    def test_AC_AGT_06l_unattributed_write_is_blamed_on_every_task_in_the_repo(self):
        a, b, results = self.two('write("backend/docs/a.md")\ntime.sleep(2)',
                                 'write("backend/build.gradle")\nwrite("backend/src/main/java/B.java")\ntime.sleep(2)')
        self.assertEqual([r[0] for r in results], [3, 3], results)
        for t in (a, b):
            row = self.task(t)
            self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
            listed = [p for e in [e for e in self.scope_events_all() if e["task_id"] == t] for p in e["payload"]["paths"]]
            self.assertEqual(listed, ["backend/build.gradle"])
        self.assertEqual(self.state(self.slug), "NEEDS_HUMAN")


class Legacy01(PCX):
    ROWS = [('write("backend/build.gradle")', [], 0), ('write("backend/src/test/java/leave/X.java")', [], 0),
            ('write("frontend/stray.txt")', [], 3), ('write("frontend/stray.txt")', ["--concurrent", "frontend"], 0),
            ('subprocess.run(["git", "-c", "user.name=a", "-c", "user.email=a@b.c", "commit", "--allow-empty", "-m", "x"], check=True)', [], 3)]

    def test_AC_ORC_08i_stage_run_on_a_0_1_run_checks_whole_repos(self):
        import subprocess
        for i, (action, flags, code) in enumerate(self.ROWS):
            with self.subTest(action=action, flags=flags):
                self.use_config(repos=[{**REPOS[0], "test_globs": 42}, REPOS[1]],
                                runners={"fake": {"command": self.script("fake", action + "\n")}})
                p = subprocess.run([sys.executable, str(Path(ROOT / "scripts" / "run_stage.py")), "--config",
                                    str(self.ws / "sentinel.config.yaml"), "--slug", f"demo{i}", "--stage", "coder",
                                    "--repo", "backend", "--runner", "fake", *flags],
                                   capture_output=True, text=True, cwd=self.ws, env=self.env())
                self.assertEqual(p.returncode, code, p.stdout + p.stderr)
                git(self.ws / "frontend", "clean", "-fdq")
                git(self.ws / "backend", "clean", "-fdq")

    def test_AC_ORC_08i_the_0_1_boundary_does_not_read_profile_globs(self):
        for name in ("run_stage.py", "boundary.py"):
            text = (ROOT / "scripts" / name).read_text()
            self.assertNotIn("scopes", text)
            self.assertNotIn("test_globs", text)


class Migration(unittest.TestCase):
    def test_migration_0004_adds_changed_files_and_evidence_columns(self):
        import tempfile
        from registry import Registry
        with tempfile.TemporaryDirectory() as d:
            reg = Registry.open(Path(d))
            self.assertGreaterEqual(reg.LATEST, 4)
            reg.close()
            db = sqlite3.connect(Path(d) / "sentinel.db")
            cols = lambda t: {r[1] for r in db.execute(f"PRAGMA table_info({t})")}
            self.assertTrue({"run_id", "task_id", "cycle_id", "repo_id", "path", "before_sha256", "after_sha256", "phase"} <= cols("changed_files"))
            self.assertTrue({"output_sha256", "repo_sha", "provider", "model", "failing", "verdict", "reason"} <= cols("evidence"))
            self.assertTrue({"repo_id", "retry_of", "reason"} <= cols("cycles"))
            db.close()


if __name__ == "__main__":
    unittest.main()
