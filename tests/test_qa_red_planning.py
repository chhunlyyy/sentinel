"""Phase J (TDD-09): when QA scenarios are the Red evidence, and when R12 refuses (qa_red_planning.feature)."""
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from errors import SentinelError  # noqa: E402
from pb_helpers import SLUG, spec_text  # noqa: E402
from pd_helpers import default_features, report, all_pass  # noqa: E402
from pj_helpers import FORM_LABEL, IDS, PJ, RULE, drive_qa  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "sentinel" / "core" / "schema" / "config.schema.json").read_text())


class Planning(PJ):
    def test_AC_TDD_09a_a_client_repo_with_the_rule_on_plans_a_qa_red_cycle(self):
        self.boot_qa()
        self.assertEqual((self.form()["red_method"], self.cycle("Remaining")["red_method"]), ("qa_scenario", "test_file"))
        self.prepare()
        self.assertEqual(self.qa_tasks()[0]["role"], "qa_red")
        self.assertEqual(self.tdd_tasks("tdd_red", "Remaining")[0]["role"], "tdd_red")
        evs = self.exc_events("planned")
        self.assertEqual(len(evs), 1)
        p = evs[0]["payload"]
        self.assertEqual((p["rule"], p["repo"], p["cycle"]), (RULE, "frontend", self.form()["id"]))
        self.assertEqual(len(p["scenarios"]), 2)

    def test_AC_TDD_09b_method_follows_rule_and_role(self):
        rows = [(True, "frontend", "qa_scenario"), (True, "mobile", "qa_scenario"), (True, "backend", "test_file"),
                (True, "app", "test_file"), (False, "frontend", "test_file"), (False, "mobile", "test_file")]
        for i, (rule, role, method) in enumerate(rows):
            with self.subTest(rule=rule, role=role):
                if i:
                    self.reset_ws()
                self.boot_qa(rule=rule, repo_over={"role": role})
                self.assertEqual(self.form()["red_method"], method)

    def test_AC_TDD_09c_rule_off_behaves_exactly_as_before(self):
        self.boot_qa(rule=False, features=default_features(True, True))
        self.prepare()
        self.targeted(report("request_form", "failure"))
        self.eng.run_task(self.tid("tdd_red", "request_form"))
        self.targeted(all_pass())
        self.eng.run_task(self.tid("tdd_green", "request_form"))
        self.eng.run_task(self.tid("tdd_refactor", "request_form"))
        roles = {t["role"] for t in self.eng.reg.rows("tasks", run_id=self.run_row()["id"], cycle_id=self.cycle("request_form")["id"])}
        self.assertEqual(roles, {"tdd_red", "tdd_green", "tdd_refactor"})
        red = self.evidence("red", label="request_form")[-1]
        self.assertEqual(red["method"], "test_file")
        self.assertIsNone(red["exception"])
        self.assertEqual(self.exc_events("planned") + self.exc_events("recorded"), [])
        rep = self.eng.build_report(SLUG)
        self.assertEqual(rep["tdd_exceptions"], [])
        self.assertNotIn("TDD exceptions", self.eng.render_report_md(rep))

    def test_AC_TDD_09d_a_config_edit_after_r12_does_not_change_the_method(self):
        self.boot_qa()
        self.config = {**self.config, "rules": {RULE: False}}
        self.write_config_file()
        self.eng.next_step(SLUG)
        self.assertEqual(self.qa_tasks()[-1]["role"], "qa_red")
        self.assertTrue(self.eng._run_config(self.run_row())["rules"][RULE])

    def test_AC_TDD_09e_docs_only_runs_are_unaffected(self):
        self.use_config(**{"rules": {RULE: True}, "qa": self.qa_cfg()})
        self.mk(SLUG, "PLANNED", 2, "docs")
        self.write_spec(spec_text(SLUG, tier=2, typ="docs"))
        self.assertTrue(self.submit("specifier")["accepted"])
        self.approve("spec")
        self.eng.advance(SLUG)
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(self.cycles(), [])
        self.eng.bookkeep(SLUG)
        self.assertFalse([t for t in self.eng.reg.rows("tasks", run_id=self.run_row()["id"]) if t["role"] == "qa_red"])

    def test_AC_TDD_09f_legacy_runs_are_untouched(self):
        self.use_config(**{"rules": {RULE: True}, "qa": self.qa_cfg()})
        self.mk(SLUG, "PLANNED", 1)
        self.eng.reg.update_run(SLUG, workflow_version=1)
        self.assertFalse(self.eng.is_v2(SLUG))
        self.assertEqual(self.cycles(), [])
        self.assertEqual([e for e in self.eng.reg.list_events(self.run_row()["id"]) if e["type"].startswith("tdd.")], [])
        # the release check is byte-identical to the commit before Phase J: pinned by content hash (no .git needed). A deliberate
        # later change of release_check.py updates this pin.
        self.assertEqual(hashlib.sha256((ROOT / "sentinel/scripts/release_check.py").read_bytes()).hexdigest(),
                         "581ee6b7a2d4bb55f5198a270ce78c27c6a6c5e281b59076ec909311e0bea28f")


class Refusal(PJ):
    ROWS = [({"driver": "none"}, "QA driver is none"), (False, "QA driver is not configured"),
            ({"scenario_run": None}, "qa.scenario_run is not configured"),
            ({"scenario_report": None}, "qa.scenario_report is not configured"),
            ({"start_commands": {"backend": "true"}}, "no QA start command for repo frontend"),
            ({"scenario_run": "python3 /nonexistent/qa_run.py {scripts}"}, "qa.scenario_run does not exist")]

    def test_AC_CFG_12a_a_missing_or_unusable_qa_driver_is_refused_at_r12(self):
        for i, (qa, reason) in enumerate(self.ROWS):
            with self.subTest(reason=reason):
                self.reset_ws()
                self.boot_qa(execute=False, qa=qa)
                with self.assertRaises(SentinelError) as cm:
                    self.eng.advance(SLUG)
                self.assertEqual(cm.exception.code, "E_PRECONDITION")
                self.assertIn("frontend", cm.exception.message)
                self.assertIn(reason, cm.exception.message)
                self.assertEqual(self.state(), "NEEDS_HUMAN")
                self.assertIn(reason, self.last_reason())
                self.assertEqual(self.cycles(), [])
                self.assertEqual(self.eng.reg.rows("tasks", run_id=self.run_row()["id"], role="qa_red"), [])
                self.assertEqual(self.eng.reg.rows("tasks", run_id=self.run_row()["id"], role="tdd_red"), [])

    def test_AC_CFG_12b_the_refusal_names_the_way_out(self):
        self.boot_qa(execute=False, qa={"driver": "none"})
        with self.assertRaises(SentinelError) as cm:
            self.eng.advance(SLUG)
        text = cm.exception.message
        self.assertIn("configure the QA driver", text)
        self.assertIn(RULE, text)
        rows = [a for a in self.eng.reg.audit_rows() if a["action"] == "tdd_exception_refused"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["actor"], (rows[0]["target"] or "").split("/")[0]), ("engine", SLUG))

    def test_AC_CFG_12c_a_human_fixes_the_config_and_the_run_resumes_with_qa_red(self):
        self.boot_qa(execute=False, qa={"scenario_run": None})
        with self.assertRaises(SentinelError):
            self.eng.advance(SLUG)
        self.config = {**self.config, "shape": "custom", "qa": self.qa_cfg()}
        self.write_config_file()
        prefix = hashlib.sha256((self.ws / "sentinel.config.yaml").read_bytes()).hexdigest()[:8]
        self.eng.resolve(SLUG, user="dev", channel="tty", comment="driver configured", refresh_config=True, config_sha_prefix=prefix)
        self.eng.bookkeep(SLUG)
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(self.form()["red_method"], "qa_scenario")
        self.assertTrue([a for a in self.eng.reg.audit_rows() if a["action"] == "resolve_refresh_config"])

    def test_refresh_config_needs_a_parked_run_and_a_human(self):
        self.boot_qa()
        with self.assertRaises(SentinelError) as cm:
            self.eng.resolve(SLUG, user="dev", channel="tty", comment="x", refresh_config=True)
        self.assertEqual(cm.exception.code, "E_PRECONDITION")


def qa_errors(cfg):
    return [e.message for e in jsonschema.Draft202012Validator(SCHEMA).iter_errors(cfg) if list(e.absolute_path)[:1] == ["qa"]]


class QaKeys(unittest.TestCase):
    def check(self, key, value):
        qa = {"driver": "playwright", key.split(".")[1]: value}
        cfg = {"version": 1, "state": {"dir": ".sentinel"}, "repos": [{"id": "a", "path": "a", "role": "frontend", "profile": "generic"}], "qa": qa}
        return qa_errors(cfg)

    def test_AC_CFG_12d_the_new_qa_keys_are_validated(self):
        rows = [("qa.scenario_run", "node qa/run.js {scripts}", True), ("qa.scenario_run", "", False), ("qa.scenario_run", 5, False),
                ("qa.scenario_report", "qa-report.xml", True), ("qa.scenario_report", "../outside.xml", False),
                ("qa.unknown_key", "x", False)]
        for key, value, ok in rows:
            with self.subTest(key=key, value=value):
                self.assertEqual(self.check(key, value) == [], ok, self.check(key, value))

    def test_AC_CFG_12e_a_config_without_the_new_keys_stays_valid(self):
        cfg = {"version": 1, "state": {"dir": ".sentinel"}, "repos": [{"id": "a", "path": "a", "role": "frontend", "profile": "generic"}],
               "qa": {"driver": "playwright", "ports": [4173], "start_commands": {"a": "x"}, "db_clone": "none", "fixtures": "sanitized"}}
        self.assertEqual(qa_errors(cfg), [])


class Mixed(PJ):
    def test_AC_TDD_09g_a_backend_cycle_and_a_frontend_cycle_run_side_by_side(self):
        self.boot_qa()
        drive_qa(self)
        self.assertEqual(self.cycle("Remaining")["state"], "CYCLE_ACCEPTED")
        self.assertEqual(self.form()["state"], "CYCLE_ACCEPTED")
        self.assertEqual(self.evidence("red", label="Remaining")[-1]["method"], "test_file")
        self.assertEqual(self.evidence("red", label=FORM_LABEL)[-1]["method"], "qa_scenario")
        self.assertIn(self.state(), ("VERIFYING", "REVIEWING"))
        self.assertTrue(self.cycle("Remaining")["approved_tests"])
        self.assertEqual(list((self.ws / "frontend" / "src").glob("test/**/*")), [])

    def test_AC_TDD_09h_a_backend_failure_does_not_change_the_frontend_method(self):
        self.boot_qa(tdd={"red_retries": 0})
        self.prepare()
        self.targeted(all_pass())
        self.run_red("Remaining")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertEqual(self.form()["red_method"], "qa_scenario")
        self.assertEqual([t for t in self.qa_tasks() if t["started_at"]], [])


if __name__ == "__main__":
    unittest.main()
