"""Phase J (TDD-09): the QA-driven Red phase, engine run, failure classes, retries, caps, scrubbing (qa_red_phase.feature)."""
import hashlib
import json
import sys
import tarfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from errors import SentinelError  # noqa: E402
from pb_helpers import SLUG  # noqa: E402
from pc_helpers import SENTINEL  # noqa: E402
from pj_helpers import DRIVER, FORM_LABEL, IDS, PJ  # noqa: E402

SCRIPTS = '''for sid, rel in re.findall(r"^- `([^`]+)` -> `([^`]+)`$", prompt, re.M):
    write(rel, "scenario " + sid + "\\n")
'''
OBJ = ("write(" + repr("x") + ")\n")


class QaBase(PJ):
    def attempt(self):
        """Prepare and run the newest qa_red task; returns the outcome."""
        return self.run_qa()

    def red_rows(self):
        return self.evidence("red", label=FORM_LABEL)

    def last_red(self):
        return self.red_rows()[-1]

    def retry_brief(self):
        t = self.qa_tasks()[-1]
        p = self.tdir(t["id"]) / "brief.md"
        return p.read_text() if p.exists() else ""


class Task(QaBase):
    def test_AC_TDD_09i_the_qa_red_task_starts_with_the_narrow_scope_and_the_cycle_enters_red_running(self):
        self.boot_qa()
        self.agent_exec("qa_red", "write('env.txt', os.environ.get('SENTINEL_TASK_ID', ''))\n" + SCRIPTS + "write_result()")
        self.prepare()
        tid = self.qid()
        self.run_qa()
        self.assertIn("RED_RUNNING", self.moves(FORM_LABEL))
        doc = self.task_json(tid)
        self.assertEqual(doc["role"], "qa_red")
        self.assertEqual(doc["permissions"]["write"], [f".sentinel/cache/qa/tests/current/{SLUG}/**"])
        self.assertEqual((self.ws / "env.txt").read_text(), tid)
        prompt = (self.tdir(tid) / "prompt.md").read_text()
        for sid in IDS:
            self.assertIn(sid, prompt)
        self.assertIn("no test file", prompt.lower())

    def test_AC_TDD_09j_a_qa_red_task_that_writes_into_a_repo_is_a_scope_violation(self):
        paths = ["frontend/src/test/RequestForm.test.ts", "frontend/src/main/RequestForm.ts", "frontend/playwright.config.ts",
                 "frontend/e2e/request.spec.ts", "sentinel.config.yaml", ".sentinel/shared/specs/leave-balance/spec.md"]
        for i, path in enumerate(paths):
            with self.subTest(path=path):
                if i:
                    self.reset_ws()
                self.boot_qa()
                self.agent_exec("qa_red", f"write({path!r}, 'x\\n')\nwrite_result()")
                self.prepare()
                tid = self.qid()
                self.run_qa()
                row = self.task(tid)
                self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
                self.assertIn(path.split("/", 1)[-1] if path.startswith("frontend") else path, row["reason"])
                self.assertEqual(self.red_rows(), [])
                self.assertNotEqual(self.form()["state"], "RED_VERIFIED")

    def test_AC_TDD_09k_a_tdd_red_task_cannot_be_created_for_a_qa_red_cycle(self):
        # engine level: no CLI command or API route creates a task (tasks come from `sentinel next`), so the refusal is checked here
        self.boot_qa()
        with self.assertRaises(SentinelError) as cm:
            self.eng.create_task(SLUG, "tdd_red", "x", repos=["frontend"], cycle_id=self.form()["id"])
        self.assertEqual(cm.exception.code, "E_PRECONDITION")
        self.assertIn("QA scenarios", cm.exception.message)
        self.assertEqual(self.tdd_tasks("tdd_red", FORM_LABEL), [])

    def test_AC_TDD_09l_a_qa_red_task_cannot_widen_its_scope_to_repo_test_globs(self):
        self.boot_qa()
        before = len(self.eng.reg.rows("tasks", run_id=self.run_row()["id"]))
        with self.assertRaises(SentinelError) as cm:
            self.eng.create_task(SLUG, "qa_red", "x", repos=["frontend"], write=["frontend/src/test/**"], cycle_id=self.form()["id"])
        self.assertEqual(cm.exception.code, "E_SCOPE")
        self.assertEqual(len(self.eng.reg.rows("tasks", run_id=self.run_row()["id"])), before)


class Judging(QaBase):
    def test_AC_TDD_09m_every_scenario_fails_at_a_then_step_so_red_is_accepted(self):
        self.boot_qa()
        self.run_qa()
        e = self.last_red()
        self.assertEqual((e["verdict"], e["classification"], e["method"], e["kind"]), ("accepted", "assertion", "qa_scenario", "red"))
        for col in ("command", "cwd", "exit_code", "started_at", "finished_at", "task_id", "repo_sha"):
            self.assertIsNotNone(e[col], col)
        self.assertEqual(sorted(json.loads(e["failing"])), sorted(IDS))
        scripts = json.loads(e["scripts"])
        self.assertEqual(sorted(s["scenario"] for s in scripts), sorted(IDS))
        for s in scripts:
            self.assertEqual(s["sha256"], hashlib.sha256((self.ws / s["path"]).read_bytes()).hexdigest())
        c = self.form()
        self.assertEqual(c["state"], "RED_VERIFIED")
        self.assertEqual(json.loads(c["approved_scripts"]), scripts)
        self.assertFalse(json.loads(c["approved_tests"] or "[]"))
        self.assertEqual(len(self.qa_tasks("tdd_green")), 1)

    ROWS = [("assertion", None, "accepted", "assertion"),
            ("unexpected_pass", {"default": {"*": "pass"}}, "rejected", "unexpected_pass"),
            ("one_pass", {"default": {"AC-5": "pass"}}, "rejected", "unexpected_pass"),
            ("given", {"default": {"AC-4": "fail_given"}}, "rejected", "setup_failure"),
            ("when", {"default": {"AC-4": "fail_when"}}, "rejected", "setup_failure"),
            ("syntax", {"default": {"AC-4": "script_error"}}, "rejected", "script_error"),
            ("missing", {"default": {"AC-5": "missing"}}, "rejected", "unbound_scenario"),
            ("foreign", {"extra": ["AC-99"]}, "rejected", "unbound_scenario"),
            ("app_down", {"all": "app_down"}, "needs_human", "app_not_running"),
            ("driver", {"all": "driver_missing"}, "needs_human", "driver_error"),
            ("timeout", {"all": "timeout"}, "needs_human", "driver_error"),
            ("unknown", {"all": "nothing"}, "needs_human", "unknown")]

    def test_AC_TDD_09n_red_is_judged_by_the_engines_own_run_per_failure_class(self):
        for i, (name, plan, verdict, klass) in enumerate(self.ROWS):
            with self.subTest(name):
                if i:
                    self.reset_ws()
                self.boot_qa(policies={"test_timeout_seconds": 1})
                self.plan(**(plan or {}))
                self.run_qa()
                e = self.last_red()
                self.assertEqual((e["verdict"], e["classification"]), (verdict, klass))
                if verdict == "accepted":
                    self.assertEqual(self.form()["state"], "RED_VERIFIED")
                elif verdict == "rejected":
                    self.assertEqual(len(self.qa_tasks()), 2)
                    brief = self.retry_brief()
                    self.assertTrue(brief)
                    if name == "one_pass":
                        self.assertIn("AC-5", brief)
                    if name == "missing":
                        self.assertIn("AC-5", brief)
                    if name == "foreign":
                        self.assertIn("AC-99", brief)
                else:
                    self.assertEqual(self.state(), "NEEDS_HUMAN")
                    self.assertEqual(len(self.qa_tasks()), 1)
                    self.assertEqual(self.form()["state"], "RED_RUNNING")

    def test_AC_TDD_09o_a_passing_red_is_not_accepted_even_when_the_agent_says_it_failed(self):
        self.boot_qa()
        self.agent_exec("qa_red", SCRIPTS + "write_result(summary='all scenarios failed as expected')")
        self.plan(default={"*": "pass"})
        self.run_qa()
        rows = self.red_rows()
        self.assertEqual([(r["verdict"], r["classification"]) for r in rows], [("rejected", "unexpected_pass")])
        self.assertNotIn("failed as expected", json.dumps(rows[0], default=str))
        self.assertIn("passed before any production change", self.retry_brief())

    def test_AC_TDD_09p_a_scenario_that_passes_already_is_not_retried_forever(self):
        self.boot_qa(tdd={"red_retries": 1})
        self.plan(default={"AC-4": "pass", "*": "fail_then"})
        for _ in range(5):
            if self.state() != "EXECUTING":
                break
            self.run_qa()
        c = self.form()
        self.assertEqual((c["state"], c["reason"]), ("REJECTED", "red cap reached"))
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertIn("AC-4", self.last_reason())

    def test_AC_TDD_09q_the_engine_reruns_a_failing_scenario_once_and_a_flip_is_flaky(self):
        self.boot_qa()
        self.plan(runs={"2": {"AC-4": "pass"}})
        self.run_qa()
        e = self.last_red()
        self.assertEqual((e["classification"], e["verdict"]), ("flaky", "rejected"))
        self.assertEqual(len(json.loads(e["runs"])), 2)
        self.assertEqual(len(self.qa_tasks()), 2)

    def test_AC_TDD_09r_an_environment_failure_is_retried_once_by_the_engine(self):
        self.boot_qa()
        self.plan(run_modes={"1": "app_down"})
        self.run_qa()
        e = self.last_red()
        self.assertEqual([r["class"] for r in json.loads(e["runs"])], ["app_not_running", "assertion"])
        self.assertEqual(e["verdict"], "accepted")
        self.assertEqual(self.state(), "EXECUTING")


class Retries(QaBase):
    def test_AC_ORC_09a_the_red_retry_cap_applies_to_qa_red(self):
        for i, (cap, attempts) in enumerate([(0, 1), (1, 2), (2, 3)]):
            with self.subTest(cap=cap):
                if i:
                    self.reset_ws()
                self.boot_qa(tdd={"red_retries": cap})
                self.plan(default={"*": "pass"})
                for _ in range(6):
                    if self.state() != "EXECUTING":
                        break
                    self.run_qa()
                self.assertEqual(len(self.qa_tasks()), attempts)
                self.assertEqual(self.last_red()["verdict"], "rejected")
                self.assertEqual((self.form()["state"], self.form()["reason"]), ("REJECTED", "red cap reached"))
                self.assertEqual(self.state(), "NEEDS_HUMAN")
                self.assertEqual(self.last_reason(), f"cycle {self.form()['behavior']}: red cap reached; last rejection: red passed unexpectedly")

    def test_AC_ORC_09b_the_retry_task_sees_what_was_wrong_and_the_earlier_failures(self):
        self.boot_qa()
        self.plan(default={"AC-4": "fail_given"})
        self.run_qa()
        brief = self.retry_brief()
        self.assertIn("attempt 2 of 3", brief)
        self.assertIn("Given the employee has 5 days left", brief)
        self.assertEqual(sorted(p.name for p in self.scripts_dir().iterdir()), [f"{i}.spec" for i in IDS])

    def test_AC_ORC_09c_needs_human_for_a_driver_error_never_counts_as_an_agent_attempt(self):
        self.boot_qa()
        self.plan(all="driver_missing")
        self.run_qa()
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertTrue(self.last_reason().startswith(f"cycle {self.form()['behavior']}: QA driver error: "), self.last_reason())
        self.assertEqual(self.form()["state"], "RED_RUNNING")
        self.assertEqual(len(self.qa_tasks()), 1)
        self.assertEqual(self.qa_tasks()[0]["attempt"], 1)

    def test_AC_ORC_09d_a_human_resume_after_a_driver_error_runs_red_again(self):
        self.boot_qa()
        self.plan(all="driver_missing")
        self.run_qa()
        self.plan()
        self.eng.resume_run(SLUG, "driver fixed", user="dev", channel="tty")
        self.eng.bookkeep(SLUG)
        self.assertEqual(self.form()["state"], "RED_VERIFIED")
        self.assertEqual(len(self.qa_tasks()), 1)
        self.assertEqual([e["verdict"] for e in self.red_rows()], ["needs_human", "accepted"])

    def test_AC_ORC_09e_a_failed_qa_red_task_retries_like_a_failed_tdd_red_task(self):
        self.boot_qa()
        self.agent_exec("qa_red", "sys.exit(1)")
        self.run_qa()
        self.assertEqual(len(self.qa_tasks()), 2)
        self.assertEqual(self.qa_tasks()[0]["state"], "FAILED")
        self.assertEqual(self.form()["state"], "PLANNED")


class Scrubbing(QaBase):
    def test_AC_SEC_11a_driver_output_is_scrubbed_before_it_is_stored_or_shown(self):
        for i, secret in enumerate(["Pw-9f3kq2", "ghp_abcdef123456", "jane.doe@corp-mail.com", "mysql://qa:Pw-9f3kq2@10.0.0.5/leave", "WS"]):
            with self.subTest(secret=secret):
                if i:
                    self.reset_ws()
                self.boot_qa()
                secret = str(self.ws) if secret == "WS" else secret
                text = {"Pw-9f3kq2": "password=Pw-9f3kq2", "ghp_abcdef123456": "token=ghp_abcdef123456"}.get(secret, secret)
                needle = "Pw-9f3kq2" if "Pw-9f3kq2" in secret else secret
                self.plan(**{"print": text, "default": {"*": "fail_given"}})
                self.run_qa()
                e = self.last_red()
                art = self.eng.reg.get_row("artifacts", e["output_artifact_id"])
                data = (self.state_dir_path() / art["path"]).read_bytes()
                self.assertNotIn(needle.encode(), data)
                self.assertEqual(e["output_sha256"], hashlib.sha256(data).hexdigest())
                shown = json.dumps({k: e[k] for k in ("failing", "reason", "scenarios", "runs", "detail")}, default=str) + self.retry_brief() + json.dumps(
                    [ev["payload"] for ev in self.eng.reg.list_events(self.run_row()["id"])], default=str)
                self.assertNotIn(needle, shown)

    def state_dir_path(self):
        return self.ws / ".sentinel"

    def test_AC_SEC_11b_screenshots_and_traces_stay_in_the_cache_and_out_of_the_export(self):
        self.boot_qa()
        self.plan(artifacts=True)
        self.run_qa()
        runs = json.loads(self.last_red()["runs"])
        found = [a for r in runs for a in r["artifacts"]]
        self.assertTrue(found)
        for a in found:
            self.assertTrue(a.startswith("cache/qa/"), a)
        (self.ws / "out").mkdir()
        res = self.eng.export_run(SLUG, out_dir=str(self.ws / "out"), user="dev")
        with tarfile.open(res["path"]) as tar:
            self.assertFalse([n for n in tar.getnames() if "cache/" in n], tar.getnames())

    def test_AC_SEC_11c_the_real_data_clone_gate_applies_before_a_qa_red_task_starts(self):
        db = {"engine": "mysql", "connection": {"env_file": ".env"}, "databases": []}
        self.boot_qa(qa={"db_clone": db}, policies={"human_required": ["real_data_clone"]})
        out = self.run_qa()
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertIn("QA needs a clone of real data (policy real_data_clone)", self.last_reason())
        self.assertIsNone(self.qa_tasks()[0]["started_at"])
        self.assertTrue(out.get("blocked"))

    def test_AC_SEC_11d_a_qa_red_task_cannot_call_engine_decisions(self):
        self.boot_qa()
        code = (f"out = {{}}\nfor cmd in ('verify', 'accept'):\n"
                f"    p = subprocess.run([sys.executable, {SENTINEL!r}, '--dir', ws, cmd, {SLUG!r}], capture_output=True, text=True)\n"
                "    out[cmd] = [p.returncode, p.stdout + p.stderr]\n"
                "pathlib.Path(ws, 'refused.json').write_text(json.dumps(out))\n" + SCRIPTS + "write_result()")
        self.agent_exec("qa_red", code)
        self.run_qa()
        out = json.loads((self.ws / "refused.json").read_text())
        for cmd in ("verify", "accept"):
            self.assertNotEqual(out[cmd][0], 0, cmd)
            self.assertIn("E_ACTOR", out[cmd][1], cmd)
        self.assertEqual(self.form()["state"], "RED_VERIFIED")

    def test_AC_SEC_11e_the_qa_command_comes_from_the_config_only(self):
        """Behavior, not the command string: a command the agent claims is never run, is flagged in the task report, and the
        driver is run with the folder of the cycle through the configured command."""
        self.boot_qa()
        pwned = self.ws / "pwned"
        self.agent_exec("qa_red", SCRIPTS + f"write_result(claimed_commands=[{{'command': 'touch {pwned}'}}])")
        self.prepare()
        tid = self.qid()
        self.run_qa()
        self.assertFalse(pwned.exists())
        flags = json.loads((self.tdir(tid) / "report.json").read_text())["claim_flags"]
        self.assertTrue([f for f in flags if "touch" in (f["claim"] or "") and "differs from the evidence" in f["flag"]], flags)
        starts = [e for e in self.driver_log() if e["event"] == "start"]
        self.assertEqual([e["scripts"] for e in starts], [str(self.scripts_dir())] * len(starts))
        self.assertGreaterEqual(len(starts), 1)
        cfg_tokens = [t for t in self.qa_cfg()["scenario_run"].split() if not t.startswith("{")]
        self.assertTrue(all(t in self.last_red()["command"] for t in cfg_tokens))


if __name__ == "__main__":
    unittest.main()
