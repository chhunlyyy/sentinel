"""Phase E: routing of failed verification checks (verification_routing.feature)."""
import hashlib
import json
import unittest

from pe_helpers import PE, SLUG
from pc_helpers import git
from errors import SentinelError

APPROVED = "backend/src/test/java/leave/RemainingBalanceTest.java"
FAIL_SH = "import sys\nsys.exit(1)\n"


class Routing(PE):
    def boot4(self, **kw):
        self.boot_ver(tier=4, **kw)
        self.write_file(APPROVED, "class RemainingBalanceTest {}\n")
        sha = hashlib.sha256((self.ws / APPROVED).read_bytes()).hexdigest()
        self.set_cycle("Remaining", approved_tests=[{"path": APPROVED, "sha256": sha}])
        self.write_file("backend/src/main/A.java", "class A {}\n")

    def fix_tasks(self):
        return [t for t in self.new_tasks() if t["role"] in ("tdd_green", "hardener") and t["cycle_id"] is None]

    def make_fail(self, kind, output):
        if kind == "test":
            self.mode("test", "backend", exit=1, report=[["LeaveFormTest", "submit", "failure"]], extra_passed=1, stdout=output)
        elif kind == "targeted":
            self.mode("targeted", "backend", exit=1, report=[["RemainingBalanceTest", "employeeSeesRemainingDays", "failure"]], stdout=output)
        elif kind in ("build", "lint", "typecheck"):
            self.mode(kind, "backend", exit=1, stdout=output)
        elif kind == "hygiene":
            self.write_file("backend/src/main/Balance.java", 'class B { void f() { System.out.println("x"); } }\n')
        elif kind == "secret":
            self.write_file("backend/src/main/resources/app.yml", 'password: "hunter2x9abc"\n')
        elif kind == "deps":
            self.write_file("backend/src/main/pom.xml", "<dependency>leftpad</dependency>\n")
            self.mode("audit", "backend", exit=1, stdout=output)
        elif kind == "mutation":
            self.mode("mutate", "backend", exit=1, stdout=output)

    def set_cycle(self, label, **fields):
        c = self.cycle(label)
        self.eng.reg.update_row("cycles", c["id"], **{k: (json.dumps(v) if isinstance(v, list) else v) for k, v in fields.items()})

    def test_AC_ORC_05i_routing_per_failing_check(self):
        rows = [("test", "LeaveFormTest.submit failed", "tdd_green"), ("targeted", "RemainingBalanceTest.balanceNeverBelowZero", "tdd_green"),
                ("build", "error: cannot find symbol LeaveBalance", "tdd_green"), ("lint", "src/main/java/leave/Balance.java:12 unused", "tdd_green"),
                ("typecheck", "src/main/java/leave/Balance.java:4 type", "tdd_green"), ("hygiene", "x", "tdd_green"),
                ("secret", "x", "tdd_green"), ("deps", "audit: 1 high vulnerability in leftpad 1.0", "tdd_green"),
                ("mutation", "3 mutants survived in Balance.java", "hardener")]
        for kind, output, role in rows:
            with self.subTest(kind=kind):
                self.boot4()
                self.make_fail(kind, output)
                res = self.verify()
                self.assertEqual(res["exit"], 1, res)
                self.assertEqual(self.state(), "VERIFYING")
                tasks = [t for t in self.fix_tasks() if t["state"] == "QUEUED"]
                self.assertEqual([(t["role"], t["repo_id"]) for t in tasks], [(role, "backend")])
                doc = self.task_json(tasks[0]["id"])
                want = ["backend/src/test/**"] if role == "hardener" else ["backend/src/main/**"]
                self.assertEqual(doc["permissions"]["write"], want)
                self.assertEqual(doc["permissions"]["readonly_approved"], [APPROVED])
                brief = (self.tdir(tasks[0]["id"]) / "brief.md").read_text()
                self.assertIn("round 1", brief)
                if kind not in ("hygiene", "secret"):
                    self.assertIn(output, brief)
                row = self.vrows(kind, "backend")[0]
                ev = [e for e in self.events("finding.routed") if e["payload"]["evidence"] == row["id"]]
                self.assertEqual(ev[0]["task_id"], tasks[0]["id"])
                self.reset_ws()

    def test_AC_ORC_05j_after_the_fix_verification_passes(self):
        self.boot4()
        self.agent_exec("tdd_green", 'write("backend/src/main/java/leave/Fixed.java", "class Fixed {}\\n")\nwrite_result()')
        self.mode("lint", "backend", exit=1, stdout="unused")
        self.verify()
        fix = self.fix_tasks()[0]
        out = self.eng.run_task(fix["id"])
        self.assertEqual(self.task(fix["id"])["state"], "COMPLETED", out)
        step = self.eng.next_step(SLUG)
        self.assertEqual((step["kind"], step["command"]), ("orchestrator", f"sentinel verify {SLUG}"))
        self.mode("lint", "backend", exit=0)
        res = self.verify()
        self.assertEqual((res["exit"], res["round"]), (0, 2))
        self.assertEqual(self.state(), "REVIEWING")

    def test_AC_ORC_05k_failures_in_two_repos_give_one_fix_task_per_repo(self):
        self.boot_ver(tier=4, policies={"max_parallel_tasks": 2})
        self.change()
        self.mode("test", "backend", exit=1, report=[["LeaveFormTest", "submit", "failure"]], extra_passed=1)
        self.mode("lint", "frontend", exit=1, stdout="lint bad")
        self.mode("typecheck", "frontend", exit=1, stdout="type bad")
        self.verify()
        tasks = self.fix_tasks()
        self.assertEqual(sorted(t["repo_id"] for t in tasks), ["backend", "frontend"])
        front = [t for t in tasks if t["repo_id"] == "frontend"][0]
        brief = (self.tdir(front["id"]) / "brief.md").read_text()
        self.assertIn("lint", brief)
        self.assertIn("typecheck", brief)
        self.assertEqual(self.eng.check_start(tasks[0]["id"])["ok"], True)
        self.assertEqual(self.eng.next_step(SLUG)["kind"], "task")
        for t in tasks:
            self.eng.reg.update_row("tasks", t["id"], state="COMPLETED")
        self.assertEqual(self.eng.next_step(SLUG)["command"], f"sentinel verify {SLUG}")

    def test_AC_TDD_08d_failure_only_an_approved_test_could_fix_goes_to_a_human(self):
        for kind in ("lint", "secret"):
            with self.subTest(kind=kind):
                self.boot4()
                if kind == "lint":
                    self.mode("lint", "backend", exit=1, stdout=f"{APPROVED} line 9 unused")
                else:
                    self.write_file(APPROVED, 'class RemainingBalanceTest { String p = "password: hunter2x9abc"; }\n')
                    sha = hashlib.sha256((self.ws / APPROVED).read_bytes()).hexdigest()
                    self.set_cycle("Remaining", approved_tests=[{"path": APPROVED, "sha256": sha}])
                res = self.verify()
                self.assertEqual(res["exit"], 6, res)
                self.assertFalse(self.fix_tasks())
                self.assertEqual(self.state(), "NEEDS_HUMAN")
                self.assertEqual(self.last_reason(), f"fix needs a change to approved test file {APPROVED}")
                self.reset_ws()

    def test_AC_TDD_08e_fix_task_editing_an_approved_test_fails_on_scope(self):
        self.boot4()
        self.agent_exec("tdd_green", f'write({APPROVED!r}, "class Changed {{}}\\n")\nwrite_result()')
        self.mode("test", "backend", exit=1, report=[["LeaveFormTest", "submit", "failure"]], extra_passed=1)
        self.verify()
        fix = self.fix_tasks()[0]
        out = self.eng.run_task(fix["id"])
        self.assertEqual(out["exit"], 3, out)
        t = self.task(fix["id"])
        self.assertEqual((t["state"], t["error_code"]), ("FAILED", "E_SCOPE"))
        self.assertIn("approved_test_changed", [e["payload"]["kind"] for e in self.events("task.scope_violation")])
        self.assertEqual(self.state(), "NEEDS_HUMAN")

    def test_AC_ORC_06a_a_scope_failure_stops_for_a_human(self):
        self.boot4()
        self.write_file("backend/build.gradle", "x\n")
        res = self.verify()
        self.assertEqual(res["exit"], 6)
        self.assertFalse(self.fix_tasks())
        self.assertEqual(self.last_reason(), "changes outside every task scope: backend/build.gradle")
        self.assertTrue((self.ws / "backend/build.gradle").exists())

    def test_AC_ORC_06b_06c_destructive_migration_needs_a_human_then_passes(self):
        mig = "backend/db/migration/V8__drop_legacy.sql"
        self.boot4()
        self.write_file(mig, "ALTER TABLE leave DROP COLUMN legacy_days;\n")
        res = self.verify()
        row = self.vrows("migration")[0]
        self.assertEqual((row["classification"], row["verdict"]), ("destructive", "fail"))
        self.assertIn("DROP COLUMN", row["failing"])
        self.assertEqual(res["exit"], 6)
        self.assertEqual(self.last_reason(), "destructive migration needs human approval (policy destructive_migration)")
        self.assertFalse(self.fix_tasks())
        self.eng.resolve(SLUG, user="dev", channel="tty", comment="reviewed", approve_file=mig)
        ap = self.approvals("migration")[0]
        self.assertEqual((ap["state"], ap["sha256"], ap["approver"], ap["channel"]),
                         ("APPROVED", hashlib.sha256((self.ws / mig).read_bytes()).hexdigest(), "dev", "tty"))
        self.assertTrue([a for a in self.audit() if a["action"] == "resolve"])
        self.assertEqual(self.state(), "VERIFYING")
        res = self.verify()
        self.assertEqual(self.vrows("migration", round=2)[0]["classification"], "destructive_approved")
        self.assertEqual(self.state(), "REVIEWING", res)

    def test_AC_ORC_06d_approval_is_void_once_the_file_changes(self):
        mig = "backend/db/migration/V8__drop_legacy.sql"
        self.boot4()
        self.write_file(mig, "ALTER TABLE leave DROP COLUMN legacy_days;\n")
        self.verify()
        self.eng.resolve(SLUG, user="dev", channel="tty", comment="ok", approve_file=mig)
        self.write_file(mig, "ALTER TABLE leave DROP COLUMN legacy_days;\n-- edited\n")
        self.verify()
        self.assertEqual(self.vrows("migration", round=2)[0]["classification"], "destructive")
        self.assertEqual(self.state(), "NEEDS_HUMAN")

    def test_AC_ORC_06e_editing_an_applied_migration_is_a_defect(self):
        self.write_file("backend/db/migration/V3__leave.sql", "CREATE TABLE leave (id INT);\n")
        git(self.ws / "backend", "add", "-A")
        git(self.ws / "backend", "commit", "-q", "-m", "v3")
        self.boot4()
        self.write_file("backend/db/migration/V3__leave.sql", "CREATE TABLE leave (id INT, x INT);\n")
        res = self.verify()
        self.assertEqual(res["exit"], 1)
        row = self.vrows("migration")[0]
        self.assertEqual(row["classification"], "applied_migration_changed")
        fix = [t for t in self.fix_tasks() if t["role"] == "tdd_green"]
        self.assertIn("V3__leave.sql", (self.tdir(fix[0]["id"]) / "brief.md").read_text())

    def test_AC_ORC_06f_unjudgeable_test_runs_go_to_a_human(self):
        for klass, sc in [("unknown", dict(exit=2)), ("environment", dict(exit=1, stdout="Connection refused"))]:
            with self.subTest(klass=klass):
                self.boot4()
                self.mode("test", "backend", **sc)
                res = self.verify()
                self.assertEqual(res["exit"], 6)
                self.assertEqual(self.vrows("test", "backend")[0]["classification"], klass)
                self.assertIn(klass, self.last_reason())
                self.assertIn("backend", self.last_reason())
                self.assertFalse(self.fix_tasks())
                self.reset_ws()

    def test_AC_ORC_05l_cap_on_verification_rounds(self):
        for cap, rounds, fixes in [(1, 1, 0), (3, 3, 2)]:
            with self.subTest(cap=cap):
                self.boot4(limits={"release_check_rounds": cap})
                self.mode("lint", "backend", exit=1, stdout="lint open")
                for _ in range(10):
                    step = self.eng.next_step(SLUG)
                    if step["kind"] == "human":
                        break
                    if step["kind"] == "orchestrator":
                        self.verify()
                    else:
                        self.eng.reg.update_row("tasks", step["task"], state="COMPLETED")
                self.assertEqual(len([r for r in self.rounds() if r["finished_at"]]), rounds)
                self.assertEqual(len(self.fix_tasks()), fixes)
                self.assertEqual(self.state(), "NEEDS_HUMAN")
                self.assertEqual(self.last_reason().split(":")[0], f"verification failed after {rounds} rounds")
                self.assertIn("lint", self.last_reason())
                self.reset_ws()

    def test_AC_ORC_05m_a_failing_fix_task_uses_the_retry_cap(self):
        self.boot4(agent_body=FAIL_SH, agents={"tdd_green": {"runner": "fake", "max_retries": 1}})
        self.mode("build", "backend", exit=1, stdout="broken")
        self.verify()
        for _ in range(6):
            step = self.eng.next_step(SLUG)
            if step["kind"] != "task":
                break
            self.eng.run_task(step["task"])
        tasks = self.fix_tasks()
        self.assertEqual([(t["state"], t["error_code"]) for t in tasks], [("FAILED", "E_EXIT")] * 2)
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertIn(tasks[-1]["id"], self.last_reason())
        self.assertIn("retry cap reached", self.last_reason())

    def test_AC_ORC_05n_fix_tasks_are_in_the_scope_union_and_the_trace(self):
        self.boot4()
        self.agent_exec("tdd_green", 'write("backend/src/main/java/leave/Balance.java", "class Balance {}\\n")\nwrite_result()')
        self.mode("lint", "backend", exit=1, stdout="unused")
        self.verify()
        fix = self.fix_tasks()[0]
        self.eng.run_task(fix["id"])
        self.assertEqual(self.task(fix["id"])["state"], "COMPLETED")
        self.mode("lint", "backend", exit=0)
        self.verify()
        self.assertEqual(self.vrows("scope", "backend", round=2)[0]["verdict"], "pass")
        row = self.vrows("lint", "backend", round=1)[0]
        self.assertIn((row["id"], fix["id"]), [(l["from_id"], l["to_id"]) for l in self.links("evidence", "task")])
        self.assertIn((fix["id"], "backend/src/main/java/leave/Balance.java"),
                      [(l["from_id"], l["to_id"]) for l in self.links("task", "file")])


if __name__ == "__main__":
    unittest.main()
