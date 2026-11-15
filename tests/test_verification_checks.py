"""Phase E: verification checks by tier and config (verification_checks.feature)."""
import hashlib
import json
import unittest

from pe_helpers import PE, SLUG, git
from errors import SentinelError

CORE = ["targeted", "test", "build", "lint", "typecheck", "hygiene", "scope"]


class Checks(PE):
    def test_AC_VER_01a_checks_per_tier(self):
        rows = [(1, CORE, "secret"), (2, CORE + ["secret", "deps"], "mutation"), (3, CORE + ["secret", "deps"], "mutation"),
                (4, CORE + ["secret", "deps", "mutation"], "migration")]
        for tier, kinds, absent in rows:
            with self.subTest(tier=tier):
                self.boot_ver(tier=tier)
                self.change()
                res = self.verify()
                self.assertEqual(res["exit"], 0, res)
                for repo in ("backend", "frontend"):
                    self.assertTrue(set(kinds) <= self.vkinds(repo), self.vkinds(repo))
                self.assertFalse(self.vrows(absent))
                self.reset_ws()

    def _hygiene_frontend(self, approve):
        self.boot_ver(rules={"no_permanent_frontend_tests": True})
        self.change()
        cycle = next(c for c in self.cycles() if c["repo_id"] == "frontend")
        self.write_file("frontend/src/test/Form.test.ts", "test('x', () => {});\n")
        self.write_file("frontend/src/test/Other.spec.ts", "export default {};\n")
        if approve:
            sha = hashlib.sha256((self.ws / "frontend/src/test/Form.test.ts").read_bytes()).hexdigest()
            self.eng.reg.update_row("cycles", cycle["id"], approved_tests=json.dumps([{"path": "frontend/src/test/Form.test.ts", "sha256": sha}]))
        self.verify()
        row = self.vrows("hygiene", "frontend")[0]
        return row["verdict"], json.loads(row["failing"])

    def test_TDD_09_hygiene_skips_approved_cycle_test_files_but_flags_other_test_infrastructure(self):
        """With rules.no_permanent_frontend_tests, the test file Red wrote (approved in a cycle) is not left-behind
        infrastructure; an unapproved test file still is."""
        verdict, failing = self._hygiene_frontend(approve=True)
        self.assertEqual(verdict, "fail")
        self.assertTrue(any("Other.spec.ts" in f for f in failing), failing)
        self.assertFalse(any("Form.test.ts" in f for f in failing), failing)

    def test_TDD_09_hygiene_flags_a_test_file_no_cycle_approved(self):
        verdict, failing = self._hygiene_frontend(approve=False)
        self.assertEqual(verdict, "fail")
        self.assertTrue(any("Form.test.ts" in f for f in failing), failing)
        self.assertTrue(any("Other.spec.ts" in f for f in failing), failing)

    def test_AC_VER_01b_migration_safety_runs_when_a_migration_file_changed(self):
        for tier in (1, 3, 4):
            with self.subTest(tier=tier):
                self.boot_ver(tier=tier)
                self.change()
                self.write_file("backend/db/migration/V7__leave_balance.sql", "ALTER TABLE leave ADD COLUMN carry_over INT;\n")
                self.verify()
                rows = self.vrows("migration")
                self.assertEqual([(r["repo_id"], r["verdict"]) for r in rows], [("backend", "pass")])
                self.reset_ws()

    def test_AC_VER_01c_docs_only_run_checks_links_and_docs_build(self):
        self.boot_ver(tier=2, repos=("backend",), typ="docs")
        self.write_file("backend/docs/policy.md", "policy\n")
        self.write_file("backend/docs/leave.md", "see [policy](policy.md) and [web](https://x.example/a)\n")
        res = self.verify()
        self.assertEqual(res["exit"], 0, res)
        self.assertEqual(self.vkinds("backend"), {"docs_links", "docs_build", "scope"})
        self.assertEqual(self.state(), "REVIEWING")

    def test_AC_VER_01d_unchanged_repo_gets_only_scope(self):
        self.boot_ver()
        self.change(("backend",))
        res = self.verify()
        self.assertEqual([(e["kind"], e["verdict"]) for e in self.vrows(repo="frontend")], [("scope", "pass")])
        self.assertIn("frontend", res["summary"]["unchanged"])

    def test_AC_VER_01e_targeted_runs_tests_of_every_accepted_cycle(self):
        self.boot_ver(repos=("backend",))
        self.change(("backend",))
        self.verify()
        t = self.vrows("targeted", "backend")[0]
        self.assertIn("RemainingBalanceTest", t["command"])
        self.assertIn("CarryOverTest", t["command"])
        self.assertTrue(self.vrows("test", "backend")[0]["command"].endswith(" test"))

    def test_AC_VER_01f_full_suite_fails_only_on_a_new_failure(self):
        rows = [([], [], True, []), (["LegacyTest.flaky"], ["LegacyTest.flaky"], True, ["LegacyTest.flaky"]),
                (["LegacyTest.flaky"], [], True, []), ([], ["LeaveFormTest.submit"], False, []),
                (["LegacyTest.flaky"], ["LegacyTest.flaky", "PayTest.total"], False, ["LegacyTest.flaky"])]
        for base, now, ok, pre in rows:
            with self.subTest(base=base, now=now):
                self.boot_ver(repos=("backend",))
                self.change(("backend",))
                run = self.run_row()
                self.eng.reg.insert_row("evidence", {"run_id": run["id"], "kind": "baseline", "repo_id": "backend",
                                                     "classification": "assertion", "failing": json.dumps(base)})
                cases = [[t.split(".")[0], t.split(".")[1], "failure"] for t in now]
                self.mode("test", "backend", exit=1 if now else 0, report=cases, extra_passed=1)
                self.verify()
                row = self.vrows("test", "backend")[0]
                self.assertEqual(row["verdict"] == "pass", ok, row)
                self.assertEqual(json.loads(row["failing"]), now)
                self.assertEqual(json.loads(row["detail"])["preexisting"], pre)
                self.reset_ws()

    def test_AC_VER_01g_scope_check_outcomes(self):
        rows = [(None, "backend", True, []), ("backend/build.gradle", "backend", False, ["build.gradle"]),
                ("frontend/package.json", "frontend", False, ["package.json"]),
                ("sentinel.config.yaml", "backend", False, ["sentinel.config.yaml"]), ("HEAD", "backend", False, ["HEAD moved"])]
        for path, repo, ok, listed in rows:
            with self.subTest(path=path):
                self.boot_ver()
                self.change()
                if path == "HEAD":
                    git(self.ws / "backend", "add", "-A")
                    git(self.ws / "backend", "commit", "-q", "-m", "x")
                elif path == "sentinel.config.yaml":
                    (self.ws / path).write_text((self.ws / path).read_text() + "\n# edited\n")
                elif path:
                    self.write_file(path, "x\n")
                self.verify()
                row = self.vrows("scope", repo)[0]
                self.assertEqual(row["verdict"] == "pass", ok, row)
                self.assertEqual(json.loads(row["failing"]), listed)
                self.reset_ws()
                if path == "sentinel.config.yaml":
                    self.write_config_file()

    def test_AC_VER_01h_changes_before_the_run_are_not_blamed(self):
        self.boot_ver(repos=("backend",))
        self.write_file("backend/README.md", "changed before\n")
        sha = hashlib.sha256(b"changed before\n").hexdigest()
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("UPDATE run_repos SET baseline_dirty=?", (json.dumps({"README.md": sha}),))
        self.change(("backend",))
        res = self.verify()
        self.assertEqual(self.vrows("scope")[0]["verdict"], "pass")
        self.assertIn("backend/README.md", res["summary"]["changed_before_run"])

    def test_AC_CFG_11b_mutation_setting(self):
        for tier, setting, exists in [(4, "tier4", True), (3, "tier4", False), (3, "always", True), (4, "never", False)]:
            with self.subTest(tier=tier, setting=setting):
                self.boot_ver(tier=tier, repos=("backend",), verification={"mutation": setting})
                self.change(("backend",))
                self.verify()
                self.assertEqual(bool(self.vrows("mutation", "backend")), exists)
                self.reset_ws()

    def test_AC_CFG_11c_migration_check_setting(self):
        mig = "backend/db/migration/V7__leave_balance.sql"
        for setting, add, exists in [("auto", True, True), ("auto", False, False), ("always", False, True), ("never", True, False)]:
            with self.subTest(setting=setting, add=add):
                self.boot_ver(repos=("backend",), verification={"migration_check": setting})
                self.change(("backend",))
                if add:
                    self.write_file(mig, "ALTER TABLE leave ADD COLUMN c INT;\n")
                self.verify()
                self.assertEqual(bool(self.vrows("migration", "backend")), exists)
                self.reset_ws()

    def test_AC_CFG_11d_not_configured_and_disabled_are_recorded_not_run(self):
        for klass in ("not_configured", "disabled"):
            with self.subTest(klass=klass):
                if klass == "disabled":
                    self.boot_ver(tier=2, repos=("backend",), verification={"disabled": ["lint"]})
                else:
                    self.boot_ver(tier=2, repos=("backend",))
                    self.set_snapshot_config(lambda cfg: cfg["repos"][0]["commands"].update(lint=""))
                self.change(("backend",))
                self.verify()
                row = self.vrows("lint", "backend")[0]
                self.assertEqual(row["classification"], klass)
                self.assertFalse(self.tool_calls("lint"))
                self.assertEqual(self.state(), "REVIEWING")
                self.reset_ws()

    def test_AC_CFG_11e_config_that_weakens_checks_is_invalid(self):
        import verify
        rows = [({"disabled": ["test"]}, "verification.disabled"), ({"disabled": ["scope"]}, "verification.disabled"),
                ({"mutation": "sometimes"}, "verification.mutation"), ({"migration_check": "maybe"}, "verification.migration_check"),
                ({"unknown_key": True}, "verification")]
        for block, key in rows:
            with self.subTest(block=block):
                problems = verify.config_problems({"verification": block})
                self.assertTrue(any(f == key for f, _ in problems), problems)

    def test_AC_CFG_11f_no_verification_block_uses_defaults(self):
        import verify
        self.assertEqual(verify.config_problems({}), [])
        self.assertEqual(verify.settings({}), {"mutation": "tier4", "migration_check": "auto", "disabled": [], "extra": []})

    def test_AC_CFG_08c_verification_uses_the_config_snapshot(self):
        self.boot_ver(tier=3, repos=("backend",))
        cfg = self.ws / "sentinel.config.yaml"
        cfg.write_text(cfg.read_text() + "verification:\n  mutation: always\n")
        self.change(("backend",))
        res = self.verify()
        self.assertFalse(self.vrows("mutation"))
        self.assertIn(res["exit"], (0, 1, 6))

    def test_AC_CFG_11g_extra_checks_become_evidence(self):
        rule = {"name": "no-sysout", "type": "added_lines", "pattern": "System\\.out"}
        self.boot_ver(repos=("backend",), verification={"extra": [rule]})
        self.write_file("backend/src/main/A.java", 'class A { void f() { System.out.println("debug"); } }\n')
        self.verify()
        row = self.vrows("extra", "backend")[0]
        self.assertEqual((row["name"], row["verdict"]), ("no-sysout", "fail"))
        self.assertIn("src/main/A.java", json.dumps(json.loads(row["detail"])["hits"]))

    def test_AC_VER_01i_missing_required_command_stops_verification(self):
        for tier, key, reason in [(1, "test", "test command missing for repo backend"), (4, "mutate", "mutate command missing for repo backend")]:
            with self.subTest(key=key):
                self.boot_ver(tier=tier)
                self.set_snapshot_config(lambda cfg: cfg["repos"][0]["commands"].update({key: ""}))
                self.change()
                res = self.verify()
                self.assertEqual(res["exit"], 6)
                self.assertEqual(self.state(), "NEEDS_HUMAN")
                self.assertEqual(self.last_reason(), reason)
                self.assertFalse(self.vrows())
                self.reset_ws()

    def test_AC_ORC_01j_all_checks_pass_applies_R14(self):
        self.boot_ver(tier=3)
        self.change()
        res = self.verify()
        self.assertEqual(res["exit"], 0)
        self.assertEqual(self.state(), "REVIEWING")
        ev = [e for e in self.events("run.state_changed") if e["payload"]["to"] == "REVIEWING"][-1]
        self.assertEqual((ev["payload"]["transition"], ev["actor"]), ("R14", "engine"))
        self.assertEqual(len(self.events("evidence.recorded")), len(self.vrows()))

    def test_AC_ORC_01k_nobody_but_the_engine_moves_to_review(self):
        self.boot_ver()
        with self.assertRaises(SentinelError) as c:
            self.eng.request_state(SLUG, "REVIEWING", "orchestrator")
        self.assertEqual(c.exception.code, "E_ACTOR")
        self.assertEqual(self.state(), "VERIFYING")

    def test_AC_ORC_01l_gherkin_edit_wins_over_R14(self):
        self.boot_ver()
        p = self.sdir() / "features" / "balance.feature"
        p.write_text(p.read_text() + "\n# edit\n")
        with self.assertRaises(SentinelError) as c:
            self.verify()
        self.assertEqual(c.exception.code, "E_TRANSITION")
        self.assertEqual(self.state(), "GHERKIN_REVIEW")
        self.assertFalse(self.vrows())


if __name__ == "__main__":
    unittest.main()
