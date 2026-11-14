"""Phase C part 1 (PC-01): task-v1, agent-result-v1, result ingestion. Engine level."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from errors import SentinelError  # noqa: E402
from pc_helpers import PC, SLUG  # noqa: E402


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Create(PC):
    def setUp(self):
        super().setUp()
        self.executing()

    def test_AC_AGT_02a_created_task_has_schema_valid_task_file(self):
        import jsonschema
        from tasks import load_schema
        row = self.eng.create_task(SLUG, "docs", "write docs", repos=["backend"], write=["backend/docs/**"])
        tid = row["id"]
        path = self.tdir(tid) / "task.json"
        self.assertTrue(path.is_file())
        doc = json.loads(path.read_text())
        jsonschema.validate(doc, load_schema("task-v1"))
        self.assertEqual((doc["run_id"], doc["role"], doc["repos"], doc["permissions"]["write"]),
                         (SLUG, "docs", ["backend"], ["backend/docs/**"]))
        spec = self.artifacts("spec")[-1]
        gh = self.artifacts("gherkin")[-1]
        self.assertEqual(doc["input"]["specification"]["sha256"], spec["sha256"])
        self.assertTrue(doc["input"]["specification"]["path"])
        self.assertEqual(doc["input"]["gherkin"]["sha256"], gh["sha256"])
        self.assertTrue(doc["input"]["gherkin"]["paths"])
        self.assertEqual(doc["constraints"]["timeout_seconds"], 5400)
        self.assertEqual(doc["expected_output"], {"schema": "agent-result-v1", "path": "result.json"})
        r = self.task(tid)
        self.assertEqual((r["state"], r["task_sha256"]), ("CREATED", sha(path)))
        ev = self.ev(tid, "task.created")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["payload"], {"role": "docs", "repo": "backend", "provider": "native",
                                            "model": None, "adapter": "native"})

    def test_AC_AGT_02b_broken_task_is_never_created(self):
        base = {"objective": "x", "repos": ["backend"]}
        rows = [("no objective", {"objective": None}, "objective"),
                ("empty objective", {"objective": ""}, "objective"),
                ("no repos", {"repos": None}, "repos"),
                ("empty repos", {"repos": []}, "repos"),
                ("role coder", {"role": "coder"}, "role"),
                ("timeout 0", {"timeout_seconds": 0}, "constraints.timeout_seconds"),
                ("timeout -5", {"timeout_seconds": -5}, "constraints.timeout_seconds"),
                ("retries -1", {"max_retries": -1}, "constraints.max_retries"),
                ("unknown repo", {"repos": ["mobile"]}, "repos")]
        before = len(self.eng.reg.rows("tasks"))
        tasks = self.ws / ".sentinel/runs" / SLUG / "tasks"
        folders = sorted(tasks.iterdir()) if tasks.exists() else []
        for name, over, field in rows:
            with self.subTest(name):
                kw = {**base, **over}
                role = kw.pop("role", "docs")
                with self.assertRaises(SentinelError) as c:
                    self.eng.create_task(SLUG, role, **kw)
                self.assertEqual(c.exception.code, "E_VALIDATION")
                self.assertEqual(c.exception.details["field"], field)
                self.assertIn(field, str(c.exception))
        self.assertEqual(len(self.eng.reg.rows("tasks")), before)
        self.assertEqual(sorted(tasks.iterdir()) if tasks.exists() else [], folders)

    def test_AC_AGT_02d_read_only_role_gets_empty_write_scope(self):
        tid = self.make("reviewer")
        doc = json.loads((self.tdir(tid) / "task.json").read_text())
        self.assertEqual(doc["permissions"]["write"], [])
        self.assertEqual(doc["permissions"]["read"], ["backend/**"])

    def test_AC_AGT_02c_limits_come_from_task_policy_default(self):
        rows = [({}, {}, 5400, 2),
                ({"policies": {"task_timeout_seconds": 600}}, {}, 600, 2),
                ({"policies": {"task_timeout_seconds": 600}, "agents": {"docs": {"max_retries": 4}}}, {}, 600, 4),
                ({"policies": {"task_timeout_seconds": 600}}, {"timeout_seconds": 30}, 30, 2)]
        for i, (cfg, setting, timeout, retries) in enumerate(rows):
            with self.subTest(i):
                slug = f"limits-{i}"
                self.use_config(**cfg)
                self.mk(slug, "EXECUTING", 3)
                tid = self.make("docs", slug=slug, **setting)
                doc = json.loads((self.tdir(tid, slug) / "task.json").read_text())
                self.assertEqual((doc["constraints"]["timeout_seconds"], doc["constraints"]["max_retries"]),
                                 (timeout, retries))


class Finish(PC):
    def setUp(self):
        super().setUp()
        self.executing()

    def test_AC_AGT_02e_valid_result_completes_task(self):
        tid = self.running()
        self.write_result(tid, summary="Docs updated")
        row = self.eng.finish_task(tid, exit_code=0)
        self.assertEqual(row["state"], "COMPLETED")
        art = self.eng.reg.get_row("artifacts", row["result_artifact_id"])
        self.assertEqual(art["sha256"], sha(self.tdir(tid) / "result.json"))
        fin = self.ev(tid, "task.finished")
        self.assertEqual(len(fin), 1)
        p = fin[0]["payload"]
        self.assertEqual((p["state"], p["error_code"]), ("COMPLETED", None))
        self.assertIsInstance(p["seconds"], (int, float))

    def test_AC_AGT_02f_broken_result_fails_the_task(self):
        rows = [("does not exist", "missing", "result.json missing"),
                ("not json", "Done! All good.", "not valid JSON"),
                ("no summary", {"schema": "agent-result-v1", "task_id": "$", "status": "completed"}, "summary"),
                ("bad status", {"schema": "agent-result-v1", "task_id": "$", "status": "done", "summary": "s"}, "status"),
                ("bad schema", {"schema": "agent-result-v0", "task_id": "$", "status": "completed", "summary": "s"}, "schema"),
                ("other task", {"schema": "agent-result-v1", "task_id": "t-other", "status": "completed", "summary": "s"}, "task_id"),
                ("bad severity", {"schema": "agent-result-v1", "task_id": "$", "status": "completed", "summary": "s",
                                  "findings": [{"severity": "critical", "location": "a:1", "text": "t"}]}, "findings[0].severity"),
                ("list", [1, 2], "must be an object")]
        for name, content, problem in rows:
            with self.subTest(name):
                tid = self.running()
                (self.tdir(tid) / "output.log").write_text("agent talk")
                if content != "missing":
                    if isinstance(content, dict):
                        content = {k: (tid if v == "$" else v) for k, v in content.items()}
                    self.write_result(tid, content)
                row = self.eng.finish_task(tid, exit_code=0)
                self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_RESULT_SCHEMA"))
                self.assertIn(problem, json.dumps(row["error_details"]))
                self.assertTrue((self.tdir(tid) / "output.log").is_file())
                self.assertEqual(self.ev(tid, "task.finished")[0]["payload"]["error_code"], "E_RESULT_SCHEMA")

    def test_AC_AGT_02g_empty_result_fails_the_task(self):
        for name, content in [("0 bytes", ""), ("whitespace", "  \n\t "), ("{}", "{}"), ("null", "null")]:
            with self.subTest(name):
                tid = self.running()
                self.write_result(tid, content)
                row = self.eng.finish_task(tid, exit_code=0)
                self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_RESULT_SCHEMA"))

    def test_AC_AGT_02h_unknown_extra_fields_are_kept(self):
        tid = self.running()
        self.write_result(tid, mood="confident")
        row = self.eng.finish_task(tid, exit_code=0)
        self.assertEqual(row["state"], "COMPLETED")
        stored = self.eng.reg.get_row("artifacts", row["result_artifact_id"])
        data = json.loads((self.ws / ".sentinel" / stored["path"]).read_text())
        self.assertEqual(data["mood"], "confident")

    def test_AC_AGT_02i_exit_code_and_status_decide_together(self):
        rows = [(0, "completed", "COMPLETED", None), (0, "failed", "FAILED", "E_AGENT"),
                (1, "completed", "FAILED", "E_EXIT"), (1, "failed", "FAILED", "E_EXIT"),
                (0, "blocked", "BLOCKED", None)]
        for code, status, state, err in rows:
            with self.subTest(exit=code, status=status):
                tid = self.running()
                self.write_result(tid, status=status)
                row = self.eng.finish_task(tid, exit_code=code)
                self.assertEqual((row["state"], row["error_code"]), (state, err))

    def test_AC_AGT_02j_changed_files_come_from_git(self):
        tid = self.running(write=["backend/docs/**"])
        (self.ws / "backend/docs").mkdir()
        (self.ws / "backend/docs/leave.md").write_text("x")
        self.write_result(tid, claimed_changed_files=["backend/docs/leave.md", "backend/docs/api.md"])
        row = self.eng.finish_task(tid, exit_code=0)
        self.assertEqual(row["state"], "COMPLETED")
        self.assertEqual(json.loads(row["changed_files"]), ["backend/docs/leave.md"])
        report = json.loads((self.tdir(tid) / "report.json").read_text())
        self.assertIn({"path": "backend/docs/api.md", "flag": "claimed but not changed"}, report["claim_flags"])

    def test_AC_VER_02a_claimed_commands_never_create_evidence(self):
        tid = self.running()
        self.write_result(tid, claimed_commands=[{"command": "./gradlew test", "exit_code": 0}])
        row = self.eng.finish_task(tid, exit_code=0)
        self.assertEqual(row["state"], "COMPLETED")
        self.assertEqual(self.eng.reg.rows("evidence", run_id=self.run_row()["id"]), [])
        stored = self.eng.reg.get_row("artifacts", row["result_artifact_id"])
        self.assertIn("./gradlew test", (self.ws / ".sentinel" / stored["path"]).read_text())

    def test_AC_AGT_02k_result_cannot_change_run_state(self):
        tid = self.running()
        self.write_result(tid, run_state="COMPLETED")
        n = len(self.events("run.state_changed"))
        row = self.eng.finish_task(tid, exit_code=0)
        self.assertEqual(row["state"], "COMPLETED")
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(len(self.events("run.state_changed")), n)

    def test_AC_AGT_06a_edited_task_file_fails_the_task(self):
        tid = self.running(write=["backend/docs/**"])
        p = self.tdir(tid) / "task.json"
        doc = json.loads(p.read_text())
        doc["permissions"]["write"].append("backend/**")
        p.write_text(json.dumps(doc))
        self.write_result(tid)
        row = self.eng.finish_task(tid, exit_code=0)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_INTEGRITY"))
        self.assertEqual(self.eng.task_scope(tid), ["backend/docs/**"])
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertEqual(self.events("run.state_changed")[-1]["payload"]["reason"],
                         f"task file changed during task {tid}")
        rows = self.audit("integrity_failed")
        self.assertEqual([r["target"] for r in rows], [tid])

    def test_scope_violation_in_other_repo_fails_with_E_SCOPE(self):
        tid = self.running(write=["backend/docs/**"])
        (self.ws / "frontend/x.txt").write_text("x")
        self.write_result(tid)
        row = self.eng.finish_task(tid, exit_code=0)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
        self.assertEqual(self.state(), "NEEDS_HUMAN")


if __name__ == "__main__":
    unittest.main()
