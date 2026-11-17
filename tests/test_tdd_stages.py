"""Phase D part 2a (PD-02): stage templates and permissions of the TDD roles (tdd_stages.feature)."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import render_stage  # noqa: E402
from errors import SentinelError  # noqa: E402
from pd_helpers import CARRY, REMAINING, SLUG, T1, T2, TEST_FILE, PD  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "stages"
MAIN_GLOB, TEST_GLOB = "backend/src/main/**", "backend/src/test/**"
APPROVED = [{"path": TEST_FILE, "sha256": "b" * 64}]


class Templates(PD):
    def setUp(self):
        super().setUp()
        self.boot_exec()
        self.cid = self.cycle("Remaining")["id"]

    def make_for(self, role, **kw):
        return self.eng.create_task(SLUG, role, f"{role} work", repos=["backend"], cycle_id=self.cid, **kw)

    def prompt(self, role, **kw):
        t = self.make_for(role, **kw) if role != "test_designer" else self.eng.create_task(SLUG, role, "designer work", repos=["backend"])
        run = self.run_row()
        return self.eng._render_prompt(run, t, self.tdir(t["id"]), require_template=True)

    def test_AC_AGT_01a_the_new_stage_templates_render(self):
        rows = [("test_designer", False, "gherkin"), ("tdd_red", True, "tests"), ("tdd_green", True, "production"),
                ("tdd_refactor", True, "production")]
        for stage, per_repo, writes in rows:
            with self.subTest(stage):
                text = (ROOT / "sentinel" / "core" / "stages" / f"{stage}.md").read_text()
                front = yaml.safe_load(render_stage.FRONT.match(text).group(1))
                self.assertEqual((front["stage"], front["per_repo"], front["writes"]), (stage, per_repo, writes))
                out = self.prompt(stage)
                self.assertNotIn("{{", out)
                self.assertNotIn("KeyError", out)

    def test_AC_AGT_01b_the_red_prompt_names_the_scenarios_the_scope_and_the_rules(self):
        self.prepare()
        tid = self.next_red("Remaining")
        run = self.run_row()
        out = self.eng._render_prompt(run, self.task(tid), self.tdir(tid), require_template=True)
        for key in REMAINING:
            self.assertIn(key, out)
        self.assertNotIn(CARRY, out)
        self.assertEqual(out.count("Scenario: Employee sees remaining days"), 1)  # scenario text of the approved version
        self.assertIn("Given x", out)
        self.assertIn(TEST_GLOB, out)
        self.assertIn(" targeted {tests}", out)
        self.assertIn("@Scenario", out)
        for rule in ("feature files", "production files", "commits"):
            self.assertIn(rule, out)
        self.assertIn(f".sentinel/runs/{SLUG}/tasks/{tid}/result.json", out)

    def test_AC_AGT_01c_the_green_prompt_names_the_approved_tests_as_read_only(self):
        c = self.eng.reg.get_row("cycles", self.cid)
        self.eng.reg.update_row("cycles", self.cid, state="RED_VERIFIED", approved_tests=json.dumps(APPROVED))
        self.eng.reg.insert_row("evidence", {"run_id": c["run_id"], "cycle_id": self.cid, "kind": "red", "failing": json.dumps([T1, T2]),
                                             "verdict": "accepted"})
        out = self.prompt("tdd_green")
        self.assertIn(MAIN_GLOB, out)
        self.assertIn(TEST_FILE, out)
        self.assertIn("read-only", out)
        self.assertIn(T1, out)
        self.assertIn(T2, out)
        self.assertIn("runs the targeted tests itself", out)

    def test_AC_AGT_01d_the_refactor_prompt_names_the_related_tests(self):
        self.eng.reg.update_row("cycles", self.cid, state="GREEN_VERIFIED", tests=json.dumps([T1, T2]))
        self.eng.reg.update_row("cycles", self.cycle("Carry")["id"], state="CYCLE_ACCEPTED", tests=json.dumps(["CarryOverTest.unusedDaysCarryOver"]))
        out = self.prompt("tdd_refactor")
        self.assertIn(MAIN_GLOB, out)
        for t in (T1, T2, "CarryOverTest.unusedDaysCarryOver"):
            self.assertIn(t, out)
        self.assertIn("behavior must not change", out)
        self.assertIn("read-only", out)

    def test_AC_AGT_01e_a_missing_profile_value_stops_creation_with_a_clear_error(self):
        self.reset_ws()
        self.boot_exec(repo_over={"targeted_test": None})
        cid = self.cycle("Remaining")["id"]
        with self.assertRaises(SentinelError) as cm:
            self.eng.create_task(SLUG, "tdd_red", "r", repos=["backend"], cycle_id=cid)
        self.assertEqual(cm.exception.code, "E_PRECONDITION")
        self.assertIn("targeted_test", str(cm.exception))
        self.assertIn("backend", str(cm.exception))
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertEqual(self.eng.reg.rows("tasks", run_id=self.run_row()["id"], role="tdd_red"), [])


class Permissions(PD):
    def setUp(self):
        super().setUp()
        self.boot_exec()
        self.cid = self.cycle("Remaining")["id"]

    def test_AC_TDD_08a_write_scope_and_read_only_files_per_role(self):
        rows = [("PLANNED", "tdd_red", [TEST_GLOB], []), ("RED_VERIFIED", "tdd_green", [MAIN_GLOB], [TEST_FILE]),
                ("GREEN_VERIFIED", "tdd_refactor", [MAIN_GLOB], [TEST_FILE])]
        for state, role, write, readonly in rows:
            with self.subTest(role=role):
                self.eng.reg.update_row("cycles", self.cid, state=state, approved_tests=json.dumps(APPROVED if state != "PLANNED" else []))
                t = self.eng.create_task(SLUG, role, "x", repos=["backend"], cycle_id=self.cid)
                perm = self.task_json(t["id"])["permissions"]
                self.assertEqual(perm["write"], write)
                self.assertEqual(perm.get("readonly_approved", []), readonly)

    def test_AC_TDD_08b_read_only_roles_get_an_empty_write_scope(self):
        for role in ("reviewer", "qa"):
            with self.subTest(role):
                t = self.eng.create_task(SLUG, role, "x", repos=["backend"])
                self.assertEqual(self.task_json(t["id"])["permissions"]["write"], [])

    def test_AC_TDD_08c_a_tdd_task_that_asks_for_more_than_its_role_allows_is_never_created(self):
        rows = [("tdd_red", MAIN_GLOB), ("tdd_green", TEST_GLOB), ("tdd_refactor", "backend/**"),
                ("tdd_green", f".sentinel/shared/specs/{SLUG}/**")]
        tasks_dir = self.ws / ".sentinel" / "runs" / SLUG / "tasks"
        for role, glob in rows:
            with self.subTest(role=role, glob=glob):
                n_rows = len(self.eng.reg.rows("tasks"))
                n_dirs = len(list(tasks_dir.iterdir())) if tasks_dir.exists() else 0
                with self.assertRaises(SentinelError) as cm:
                    self.eng.create_task(SLUG, role, "x", repos=["backend"], cycle_id=self.cid, write=[glob])
                self.assertEqual(cm.exception.code, "E_POLICY")
                self.assertIn(role, str(cm.exception))
                self.assertIn(glob, str(cm.exception))
                self.assertEqual(len(self.eng.reg.rows("tasks")), n_rows)
                self.assertEqual(len(list(tasks_dir.iterdir())) if tasks_dir.exists() else 0, n_dirs)

    def test_AC_TDD_08c_a_narrower_scope_is_allowed(self):
        t = self.eng.create_task(SLUG, "tdd_green", "x", repos=["backend"], cycle_id=self.cid, write=["backend/src/main/java/**"])
        self.assertEqual(self.task_json(t["id"])["permissions"]["write"], ["backend/src/main/java/**"])


class Adapters(PD):
    def test_AC_AGT_04f_the_cli_adapter_runs_a_tdd_red_task_with_the_rendered_prompt(self):
        body = "open(os.path.join(ws, 'seen-prompt.txt'), 'w').write(prompt)\nopen(os.path.join(ws, 'seen-cwd.txt'), 'w').write(os.getcwd())\nwrite_result()\n"
        self.boot_exec(agent_body=body)
        self.prepare()
        tid = self.next_red("Remaining")
        out = self.eng.run_task(tid)
        self.assertNotEqual(out.get("error_code"), "E_PRECONDITION")
        self.assertEqual(self.task(tid)["adapter"], "cli")
        self.assertEqual(Path((self.ws / "seen-cwd.txt").read_text()), self.ws / "backend")
        seen = (self.ws / "seen-prompt.txt").read_text()
        self.assertEqual(seen.strip(), (self.tdir(tid) / "prompt.md").read_text().strip())
        for key in REMAINING:
            self.assertIn(key, seen)

    def test_AC_AGT_04g_a_native_tdd_green_task_gets_the_same_checks_at_task_complete(self):
        self.boot_exec(single_model=True)
        cid = self.cycle("Remaining")["id"]
        path = self.ws / TEST_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("class RemainingBalanceTest {}\n")
        import hashlib
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.eng.reg.update_row("cycles", cid, state="RED_VERIFIED", approved_tests=json.dumps([{"path": TEST_FILE, "sha256": sha}]))
        tid = self.eng.create_task(SLUG, "tdd_green", "g", repos=["backend"], cycle_id=cid, queue=True)["id"]
        out = self.eng.run_task(tid)
        self.assertEqual((out["state"], self.task(tid)["waiting_on"]), ("WAITING_FOR_INPUT", "orchestrator"))
        path.write_text("class RemainingBalanceTest { /* edited */ }\n")
        self.eng.complete_task(tid)
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
        kinds = [e["payload"]["kind"] for e in self.ev(tid, "task.scope_violation")]
        self.assertEqual(kinds, ["approved_test_changed"])
        self.assertEqual(self.eng._outcome(tid)["exit"], 3)


class ZeroOneStages(unittest.TestCase):
    def test_AC_ORC_08j_0_1_stages_render_byte_for_byte_as_before_phase_d(self):
        for stage in ("coder", "specifier", "repro", "hardener", "reviewer"):
            with self.subTest(stage):
                p = subprocess.run([sys.executable, str(ROOT / "sentinel" / "scripts" / "render_stage.py"), "--config",
                                    str(FIX / "config.yaml"), "--stage", stage, "--repo", "backend", "--slug", "demo"],
                                   capture_output=True)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout, (FIX / f"{stage}.golden.md").read_bytes())


if __name__ == "__main__":
    unittest.main()
