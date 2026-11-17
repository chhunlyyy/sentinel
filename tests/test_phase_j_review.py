"""Review of Phase J (TDD-09): the regression tests for the findings of the Sonnet review (items 1 to 9 of the review list).

Authority: plan/v1.1/phaseJ/features/*.feature and its README. Names carry the AC id where one applies.
"""
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import qa_scenarios as Q  # noqa: E402
import sentinel as cli  # noqa: E402
from engine import Engine  # noqa: E402
from errors import SentinelError  # noqa: E402
from pb_helpers import CLI, CLI_ENV, SLUG, run_tty  # noqa: E402
from pd_helpers import feature  # noqa: E402
from pj_helpers import DRIVER, PJ, features  # noqa: E402

RUNNER = Path(DRIVER)


def sha8(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8]


class Parked(PJ):
    """A run parked at R12 because the QA driver is not configured; `fix` writes a good config to the workspace file."""

    def parked(self):
        self.boot_qa(execute=False, qa={"scenario_run": None})
        with self.assertRaises(SentinelError):
            self.eng.advance(SLUG)
        self.assertEqual(self.state(), "NEEDS_HUMAN")

    def fix(self, **over):
        self.config = {**self.config, "shape": "custom", "qa": self.qa_cfg(), **over}
        self.write_config_file()
        return sha8(self.ws / "sentinel.config.yaml")

    def snapshot(self):
        return self.run_row()["config_snapshot_id"]

    def versions(self):
        return len(self.eng.reg._c.execute("SELECT id FROM config_versions").fetchall())


class RefreshConfig(Parked):
    def refresh(self, prefix, **kw):
        return self.eng.resolve(SLUG, user="dev", channel="tty", comment=kw.pop("comment", "driver configured"), refresh_config=True,
                                config_sha_prefix=prefix, **kw)

    def test_refresh_needs_a_comment_M7b(self):
        self.parked()
        prefix = self.fix()
        before = self.snapshot()
        for comment in (None, "", "   "):
            with self.subTest(comment=comment):
                with self.assertRaises(SentinelError) as cm:
                    self.eng.resolve(SLUG, user="dev", channel="tty", comment=comment, refresh_config=True, config_sha_prefix=prefix)
                self.assertEqual(cm.exception.code, "E_VALIDATION")
                self.assertEqual(self.snapshot(), before)

    def test_refresh_is_allowed_on_a_blocked_run(self):
        self.parked()
        prefix = self.fix()
        self.eng.reg.update_run(SLUG, state="BLOCKED")
        before = self.snapshot()
        self.refresh(prefix)
        self.assertNotEqual(self.snapshot(), before)

    def test_refresh_refuses_other_states(self):
        self.boot_qa()
        prefix = self.fix()
        with self.assertRaises(SentinelError) as cm:
            self.refresh(prefix)
        self.assertEqual(cm.exception.code, "E_PRECONDITION")

    def test_refresh_stores_nothing_without_the_right_typed_prefix(self):
        self.parked()
        prefix = self.fix()
        before, count = self.snapshot(), self.versions()
        wrong = ["", "   ", None, "00000000", prefix[:7], prefix + "ab", ("0" if prefix[0] != "0" else "1") + prefix[1:]]
        for typed in wrong:
            with self.subTest(typed=typed):
                with self.assertRaises(SentinelError) as cm:
                    self.refresh(typed)
                self.assertEqual(cm.exception.code, "E_VALIDATION")
                self.assertEqual((self.snapshot(), self.versions()), (before, count))
        self.assertEqual(self.events("run.config_refreshed"), [])

    def test_refresh_records_the_changed_keys_in_event_and_audit(self):
        self.parked()
        prefix = self.fix()
        info = self.eng.refresh_config_preview(SLUG, comment="x")
        self.assertIn("qa.scenario_run", info["changed_keys"])
        self.assertTrue([ln for ln in info["diff"] if ln.startswith("qa.scenario_run: (not set) -> ")], info["diff"])
        self.refresh(prefix)
        event = self.events("run.config_refreshed")[-1]["payload"]
        self.assertEqual(event["changed_keys"], info["changed_keys"])
        self.assertEqual(event["sha256"], hashlib.sha256((self.ws / "sentinel.config.yaml").read_bytes()).hexdigest())
        row = [a for a in self.eng.reg.audit_rows() if a["action"] == "resolve_refresh_config"][-1]
        self.assertIn("changed keys:", row["reason"])
        self.assertIn("qa.scenario_run", row["reason"])

    def test_refresh_refuses_a_config_that_is_not_valid_yaml_or_schema(self):
        self.parked()
        before, count = self.snapshot(), self.versions()
        path = self.ws / "sentinel.config.yaml"
        good = path.read_text()
        bad = {"yaml": "version: 1\nrepos: [unclosed\n", "not a mapping": "- a\n- b\n",
               "schema": good.replace("version: 1", "version: 1\nunknown_top_key: true", 1)}
        for name, text in bad.items():
            with self.subTest(name):
                path.write_text(text)
                with self.assertRaises(SentinelError) as cm:
                    self.refresh(sha8(path))
                self.assertEqual(cm.exception.code, "E_VALIDATION")
                self.assertEqual((self.snapshot(), self.versions()), (before, count))

    def cli_refresh(self, typed=(), **kw):
        return run_tty(["--dir", str(self.ws), "resolve", SLUG, "--refresh-config", "-m", "fixed", "--no-resume"], list(typed), **kw)

    def test_the_cli_shows_the_diff_and_asks_for_the_typed_prefix(self):
        self.parked()
        prefix = self.fix()
        before = self.snapshot()
        code, out = self.cli_refresh(typed=["00000000"])
        self.assertEqual(code, 5, out)
        self.assertIn("E_VALIDATION", out)
        self.assertIn("qa.scenario_run", out)
        self.assertEqual(self.snapshot(), before)
        code, out = self.cli_refresh(eof=True)
        self.assertEqual(code, 1, out)
        self.assertEqual(self.snapshot(), before)
        code, out = self.cli_refresh(typed=[prefix])
        self.assertEqual(code, 0, out)
        self.assertNotEqual(self.snapshot(), before)

    def test_the_cli_refuses_a_task_process_and_a_pipe(self):
        self.parked()
        self.fix()
        before = self.snapshot()
        env = {**CLI_ENV, "SENTINEL_TASK_ID": "t-1"}
        for name, kw in (("task process", {"env": env}), ("no terminal", {"env": CLI_ENV})):
            with self.subTest(name):
                r = subprocess.run(CLI + ["--dir", str(self.ws), "resolve", SLUG, "--refresh-config", "-m", "x"], capture_output=True,
                                   text=True, stdin=subprocess.DEVNULL, **kw)
                self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
                self.assertRegex(r.stdout + r.stderr, "E_ACTOR|E_NOT_TTY")
                self.assertEqual(self.snapshot(), before)


class SnapshotIntegrity(Parked):
    def corrupt(self, content=None, sha=None):
        cid = self.snapshot()
        conn = sqlite3.connect(self.ws / ".sentinel" / "sentinel.db")
        conn.execute("DROP TRIGGER IF EXISTS config_versions_no_update")
        if content is not None:
            conn.execute("UPDATE config_versions SET content=? WHERE id=?", (content, cid))
        if sha is not None:
            conn.execute("UPDATE config_versions SET sha256=? WHERE id=?", (sha, cid))
        conn.commit()
        conn.close()

    def bad_yaml(self):
        text = "[unclosed\n"
        self.corrupt(content=text, sha=hashlib.sha256(text.encode()).hexdigest())

    def test_an_unreadable_snapshot_is_not_replaced_by_the_live_config(self):
        self.boot_qa()
        self.assertEqual(self.state(), "EXECUTING")
        self.bad_yaml()
        with self.assertRaises(SentinelError) as cm:
            self.eng._run_config(self.run_row())
        self.assertEqual(cm.exception.code, "E_INTEGRITY")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertTrue([a for a in self.eng.reg.audit_rows() if a["action"] == "integrity_failed" and a["target"].endswith("/config")])
        self.assertIn("--refresh-config", self.last_reason())

    def test_a_snapshot_that_no_longer_matches_its_hash_parks_the_run_at_next(self):
        self.boot_qa()
        self.corrupt(content="version: 1\n")
        step = self.eng.next_step(SLUG)
        self.assertEqual((step["kind"], step["state"]), ("human", "NEEDS_HUMAN"))
        self.assertIn("config snapshot", step["reason"])

    def test_a_snapshot_that_no_longer_matches_its_hash_is_refused(self):
        self.boot_qa()
        self.corrupt(sha="0" * 64)
        with self.assertRaises(SentinelError) as cm:
            self.eng._run_config(self.run_row())
        self.assertEqual(cm.exception.code, "E_INTEGRITY")

    def test_a_run_without_a_stored_snapshot_keeps_the_live_config(self):
        self.boot_qa()
        self.eng.reg.update_run(SLUG, config_snapshot_id=None)
        self.assertEqual(self.eng._run_config(self.run_row()), self.eng.config)

    def test_a_parked_run_with_a_broken_snapshot_can_be_refreshed(self):
        self.boot_qa()
        self.bad_yaml()
        with self.assertRaises(SentinelError):
            self.eng._run_config(self.run_row())
        self.fix()
        self.eng.resolve(SLUG, user="dev", channel="tty", comment="repaired", refresh_config=True,
                         config_sha_prefix=sha8(self.ws / "sentinel.config.yaml"), resume=False)
        self.assertIsInstance(self.eng._run_config(self.run_row()), dict)


class DenyRules(unittest.TestCase):
    def test_every_human_only_command_has_the_dir_equals_form(self):
        rules = cli.HUMAN_ONLY_COMMANDS
        spaced = [r for r in rules if r.startswith("Bash(sentinel --dir * ")]
        self.assertGreaterEqual(len(spaced), 9)
        for rule in spaced:
            self.assertIn(rule.replace("--dir * ", "--dir=* ", 1), rules)
        self.assertIn("Bash(sentinel --dir=* resolve *)", rules)
        self.assertIn("Bash(sentinel --dir=* approve *)", rules)

    def test_the_settings_merge_writes_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli.deny_human_commands(Path(tmp))
            deny = json.loads((Path(tmp) / ".claude" / "settings.json").read_text())["permissions"]["deny"]
        self.assertIn("Bash(sentinel --dir=* accept *)", deny)
        self.assertIn("Bash(sentinel --dir=* backup restore *)", deny)


class Runner(PJ):
    """The runner files named in qa.scenario_run are hashed at Red and protected like the scripts."""

    def setUp(self):
        super().setUp()
        (self.ws / "frontend" / "qa").mkdir()
        self.runner = self.ws / "frontend" / "qa" / "driver.py"
        shutil.copy(RUNNER, self.runner)

    def boot_runner(self):
        self.boot_qa(qa={"scenario_run": f"{sys.executable} qa/driver.py {{scripts}} {{report}} {{cycle}}"})

    def runner_rel(self):
        return "frontend/qa/driver.py"

    def to_green_ready(self):
        self.boot_runner()
        self.plan()
        self.run_qa()
        self.assertEqual(self.form()["state"], "RED_VERIFIED")

    def test_the_runner_is_hashed_when_red_is_accepted(self):
        self.to_green_ready()
        stored = json.loads(self.form()["approved_runner"])
        self.assertEqual(stored, [{"path": self.runner_rel(), "sha256": hashlib.sha256(self.runner.read_bytes()).hexdigest()}])

    def test_a_runner_changed_before_green_stops_the_run(self):
        self.to_green_ready()
        runs = self.driver_runs()
        self.runner.write_text(self.runner.read_text() + "\n# tampered\n")
        self.plan(default={"*": "pass"})
        self.run_qa("tdd_green")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        rows = [a for a in self.eng.reg.audit_rows() if a["action"] == "integrity_failed"]
        self.assertTrue(rows)
        self.assertIn("driver.py", rows[-1]["reason"])
        self.assertEqual(self.driver_runs(), 0)  # plan() reset the log: the driver did not run for Green
        del runs
        self.assertEqual(self.evidence("green", label=self.FORM), [])

    def test_a_runner_changed_after_green_stops_refactor_and_the_report(self):
        self.to_green_ready()
        self.plan(default={"*": "pass"})
        self.run_qa("tdd_green")
        self.assertEqual(self.form()["state"], "GREEN_VERIFIED")
        self.runner.write_text("# replaced\n")
        self.run_qa("tdd_refactor")
        self.assertEqual(self.state(), "NEEDS_HUMAN")

    def test_the_report_finds_a_runner_changed_after_acceptance(self):
        self.boot_runner()
        self.plan()
        self.run_qa()
        self.plan(default={"*": "pass"})
        self.run_qa("tdd_green")
        self.run_qa("tdd_refactor")
        self.assertEqual(self.form()["state"], "CYCLE_ACCEPTED")
        run = self.eng.reg.get_run_by_id(self.run_row()["id"])
        self.assertEqual(self.eng._exception_gaps(run), [])
        self.runner.write_text("# replaced\n")
        self.assertEqual([c["id"] for c in self.eng._exception_gaps(run)], [self.form()["id"]])

    def test_a_green_agent_that_edits_the_runner_is_a_scope_violation(self):
        self.to_green_ready()
        self.agent_exec("tdd_green", f"write({self.runner_rel()!r}, '# edited\\n')\nwrite_result()")
        self.plan(default={"*": "pass"})
        tid = self.qid("tdd_green")
        self.run_qa("tdd_green")
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
        self.assertIn("outside_write_scope", json.dumps(self.eng.get_task(tid).get("error_details") or {}) + row["reason"] +
                      json.dumps([e["payload"] for e in self.events("task.finished")]))


class ScriptTree(PJ):
    def test_the_manifest_hashes_subfolders_and_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "scripts"
            (d / "helpers").mkdir(parents=True)
            (d / "AC-1.spec").write_text("a")
            (d / "helpers" / "login.js").write_text("b")
            items = Q.manifest(tmp, "scripts")
            self.assertEqual([(x["path"], x["scenario"]) for x in items], [("scripts/AC-1.spec", "AC-1"), ("scripts/helpers/login.js", None)])
            (d / "helpers" / "login.js").write_text("changed")
            self.assertEqual(Q.changed_scripts(tmp, items, "scripts"), ["scripts/helpers/login.js"])
            (d / "helpers" / "new.js").write_text("c")
            self.assertEqual(Q.changed_scripts(tmp, items, "scripts"), ["scripts/helpers/login.js", "scripts/helpers/new.js"])
            for link in (d / "helpers" / "link", d / "linkdir"):
                link.symlink_to("/etc")
                with self.assertRaises(SentinelError) as cm:
                    Q.manifest(tmp, "scripts")
                self.assertEqual(cm.exception.code, "E_INTEGRITY")
                self.assertIn(link.name, cm.exception.details["path"])
                link.unlink()

    def test_a_symlink_written_by_qa_red_parks_the_run_with_the_path(self):
        self.boot_qa()
        rel = self.script_rel("AC-4")
        self.agent_exec("qa_red", f"import os\nd = os.path.join(ws, {rel!r})\nos.makedirs(os.path.dirname(d), exist_ok=True)\nos.symlink('/etc/hostname', d)\nwrite_result()")
        self.run_qa()
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        rows = [a for a in self.eng.reg.audit_rows() if a["action"] == "integrity_failed"]
        self.assertTrue(rows and "AC-4.spec" in rows[-1]["reason"], rows)
        self.assertEqual(self.evidence("red", label=self.FORM), [])

    def test_a_helper_in_a_subfolder_is_part_of_the_approved_set(self):
        self.boot_qa()
        code = ("for sid, rel in re.findall(r'^- `([^`]+)` -> `([^`]+)`$', prompt, re.M):\n    write(rel, 'scenario ' + sid + '\\n')\n"
                f"write({self.script_rel('x')[:-6] + 'helpers/login.js'!r}, 'helper\\n')\nwrite_result()")
        self.agent_exec("qa_red", code)
        self.run_qa()
        paths = [x["path"] for x in json.loads(self.form()["approved_scripts"])]
        self.assertTrue([p for p in paths if p.endswith("helpers/login.js")], paths)
        (self.ws / [p for p in paths if p.endswith("helpers/login.js")][0]).write_text("tampered\n")
        run = self.eng.reg.get_run_by_id(self.run_row()["id"])
        self.assertTrue(self.eng.qa_changed(run, "frontend"))

    def test_qa_red_may_write_only_its_own_cycle_folder(self):
        self.boot_qa()
        other = f".sentinel/cache/qa/tests/current/{SLUG}/some-other-folder/AC-9.spec"
        self.agent_exec("qa_red", f"write({other!r}, 'x\\n')\nwrite_result()")
        self.prepare()
        tid = self.qid()
        self.run_qa()
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
        self.assertIn("some-other-folder", row["reason"])

    def test_green_may_not_write_into_the_qa_tree(self):
        self.to_qa_red_verified()
        new = f".sentinel/cache/qa/tests/current/{SLUG}/some-new-folder/x.spec"
        self.agent_exec("tdd_green", f"write({new!r}, 'x\\n')\nwrite_result()")
        self.plan(default={"*": "pass"})
        tid = self.qid("tdd_green")
        self.run_qa("tdd_green")
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))

    def test_the_scripts_folder_follows_a_nested_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            eng = Engine(ws / "build" / ".sentinel", ws, {"version": 1, "repos": []})
            try:
                self.assertEqual(eng._scripts_rel({"slug": "x"}), "build/.sentinel/cache/qa/tests/current/x")
                self.assertEqual(eng._qa_red_scope({"slug": "x"}, None), ["build/.sentinel/cache/qa/tests/current/x/**"])
            finally:
                eng.close()


class TwoCycles(PJ):
    """Two QA cycles of one repo: the scripts of an earlier accepted cycle are approved files for every later QA task."""

    def two_features(self):
        files = features()
        files["request_form_history.feature"] = feature("@REQ-2 @repo-frontend", [("", "Request history", [("AC-6", "History lists requests")])],
                                                    title="Request history")
        return files

    def boot_two(self):
        self.boot_qa(features=self.two_features())
        self.assertEqual({c["behavior"].split("::")[0].strip() for c in self.eng.reg.rows("cycles")} >= {"features/request_form.feature"}, True)
        self.HIST = "Request history"

    def accept_form(self):
        self.plan()
        self.run_qa()
        self.plan(default={"*": "pass"})
        self.run_qa("tdd_green")
        self.run_qa("tdd_refactor")
        self.assertEqual(self.form()["state"], "CYCLE_ACCEPTED")

    def hist(self):
        return self.cycle(self.HIST)

    def hist_tasks(self, role):
        return self.tdd_tasks(role, self.HIST)

    def test_a_later_qa_red_cannot_overwrite_an_accepted_script(self):
        self.boot_two()
        self.accept_form()
        earlier = self.script_rel("AC-4")
        self.eng.bookkeep(SLUG)
        self.agent_exec("qa_red", f"write({earlier!r}, 'overwritten\\n')\nwrite_result()")
        tid = self.hist_tasks("qa_red")[-1]["id"]
        self.plan()
        self.eng.run_task(tid)
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
        self.assertIn("AC-4.spec", row["reason"])
        self.assertEqual(self.eng.qa_changed(self.eng.reg.get_run_by_id(self.run_row()["id"]), "frontend") != [], True)

    def test_an_earlier_cycle_that_regresses_is_caught_at_the_later_green(self):
        self.boot_two()
        self.accept_form()
        self.eng.bookkeep(SLUG)
        self.plan()
        self.eng.run_task(self.hist_tasks("qa_red")[-1]["id"])
        self.assertEqual(self.hist()["state"], "RED_VERIFIED")
        self.plan(default={"*": "pass", "AC-4": "fail_then"})
        green = self.hist_tasks("tdd_green")[-1]["id"]
        self.eng.run_task(green)
        e = self.evidence("green", label=self.HIST)[-1]
        self.assertEqual(e["verdict"], "rejected")
        self.assertIn("regression", e["reason"])
        self.assertIn("AC-4", e["reason"])
        self.assertEqual(self.hist()["state"], "GREEN_RUNNING")

    def test_a_script_of_an_earlier_cycle_changed_by_hand_stops_the_later_green(self):
        self.boot_two()
        self.accept_form()
        self.eng.bookkeep(SLUG)
        self.plan()
        self.eng.run_task(self.hist_tasks("qa_red")[-1]["id"])
        (self.ws / self.script_rel("AC-5")).write_text("edited by hand\n")
        self.plan(default={"*": "pass"})
        self.eng.run_task(self.hist_tasks("tdd_green")[-1]["id"])
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertTrue([a for a in self.eng.reg.audit_rows() if a["action"] == "integrity_failed"])


class Paths(unittest.TestCase):
    def test_a_relative_runner_token_is_looked_up_in_the_repo_first_then_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "web" / "qa").mkdir(parents=True)
            (ws / "tools").mkdir()
            cfg = {"repos": [{"id": "web", "path": "web", "role": "frontend"}],
                   "qa": {"driver": "playwright", "scenario_report": "r.xml", "start_commands": {"web": "true"},
                          "scenario_run": "node qa/run.js {scripts}"}}
            self.assertEqual(Q.driver_problem(cfg, ws, "web"), "qa.scenario_run does not exist: qa/run.js")
            (ws / "web" / "qa" / "run.js").write_text("x")  # in the repo only
            self.assertIsNone(Q.driver_problem(cfg, ws, "web"))
            (ws / "web" / "qa" / "run.js").unlink()
            (ws / "qa").mkdir()
            (ws / "qa" / "run.js").write_text("x")  # in the workspace only
            self.assertIsNone(Q.driver_problem(cfg, ws, "web"))
            self.assertEqual(Q.runner_files(cfg, ws, "web"), ["qa/run.js"])
            (ws / "web" / "qa" / "run.js").write_text("y")  # both: the repo wins
            self.assertEqual(Q.runner_files(cfg, ws, "web"), ["web/qa/run.js"])


def driver_cfg(report="r.xml", run="true", ports=None, start="true"):
    return {"qa": {"driver": "playwright", "scenario_run": run, "scenario_report": report, "start_commands": {"web": start},
                   "ports": ports or []}}


class Minor(unittest.TestCase):
    def test_captured_output_is_capped_with_a_marker(self):
        code, text, timed = Q.run_command(f"{sys.executable} -c \"import sys; sys.stdout.write('x' * (6 * 1024 * 1024))\"", ".", os.environ, 60)
        self.assertEqual((code, timed), (0, False))
        self.assertLess(len(text), Q.OUTPUT_CAP + 100)
        self.assertTrue(text.endswith(Q.CAP_MARK))

    def test_a_timeout_kills_the_group_and_reports_124(self):
        code, text, timed = Q.run_command("sleep 30 & sleep 30", ".", os.environ, 1)
        self.assertEqual((code, timed), (124, True))
        self.assertIn("timed out after 1 seconds", text)

    def test_the_readiness_probe_accepts_ipv4_or_ipv6(self):
        for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            s = socket.socket(family)
            try:
                s.bind((host, 0))
            except OSError:
                s.close()
                continue
            s.listen(1)
            try:
                self.assertTrue(Q.listening(s.getsockname()[1]), host)
            finally:
                s.close()
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.assertFalse(Q.listening(port))

    def test_app_started_is_false_when_the_ports_were_already_listening(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            s.listen(5)
            port = s.getsockname()[1]
            try:
                cfg = driver_cfg(ports=[port], run="true")
                ran = Q.run_driver(cfg, tmp, "web", tmp, "c-1", Path(tmp) / "qa", 20, lambda: "now")
                self.assertFalse(ran["app_started"])
            finally:
                s.close()
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            free = probe.getsockname()[1]
            probe.close()
            listener = f"{sys.executable} -c \"import socket,time;s=socket.socket();s.setsockopt(1,2,1);s.bind(('127.0.0.1',{free}));s.listen(5);time.sleep(60)\""
            ran = Q.run_driver(driver_cfg(ports=[free], start=listener), tmp, "web", tmp, "c-2", Path(tmp) / "qa", 20, lambda: "now")
            self.assertTrue(ran["app_started"])
            for _ in range(50):  # the killed app closes its port a moment later
                if not Q.listening(free):
                    break
                time.sleep(0.1)
            self.assertFalse(Q.listening(free))

    def test_a_report_path_that_leaves_the_qa_folder_is_refused_before_anything_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            victim = Path(tmp) / "victim.xml"
            victim.write_text("keep")
            for bad in ("../victim.xml", str(victim), "a/../../victim.xml"):
                with self.subTest(bad):
                    with self.assertRaises(SentinelError) as cm:
                        Q.run_driver(driver_cfg(report=bad), tmp, "web", tmp, "c-1", Path(tmp) / "qa", 5, lambda: "now")
                    self.assertEqual(cm.exception.code, "E_VALIDATION")
                    self.assertEqual(victim.read_text(), "keep")

    def test_a_scenario_reported_twice_is_a_script_error_not_the_last_result(self):
        cases = [("AC-1", "failure", "Then x: nope"), ("AC-1", "pass", ""), ("AC-2", "failure", "Then y: nope")]
        j = Q.judge({"report": cases, "output": ""}, ["AC-1", "AC-2"])
        self.assertEqual(j["class"], "script_error")
        self.assertIn("duplicate result for scenario AC-1", j["line"])

    def test_and_and_but_take_the_keyword_of_the_step_before(self):
        text = "Given a form\nWhen I submit\nThen I see a\nAnd I see b\nBut not c\n"
        steps = {"AC-1": Q.steps_of(text)}
        then = ("AC-1", "failure", "And I see b: expected 5")
        self.assertEqual(Q.judge({"report": [then], "output": ""}, ["AC-1"], steps)["class"], "assertion")
        but = ("AC-1", "failure", "But not c: it is there")
        self.assertEqual(Q.judge({"report": [but], "output": ""}, ["AC-1"], steps)["class"], "assertion")
        when = {"AC-1": Q.steps_of("Given a\nWhen I click\nAnd I type\nThen ok\n")}
        self.assertEqual(Q.judge({"report": [("AC-1", "failure", "And I type: no field")], "output": ""}, ["AC-1"], when)["class"],
                         "setup_failure")
        # without the scenario steps an And or But is never taken for a Then step
        self.assertEqual(Q.judge({"report": [then], "output": ""}, ["AC-1"])["class"], "setup_failure")


class EngineMinor(PJ):
    def test_the_verify_lock_file_is_removed(self):
        self.to_qa_red_verified()
        self.assertEqual(list((self.ws / ".sentinel" / "tmp").glob("verify-*.lock")), [])

    def test_a_busy_driver_parks_the_run_with_a_reason(self):
        self.boot_qa()
        qa_dir = self.ws / ".sentinel" / "cache" / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        import fcntl
        fd = os.open(str(qa_dir / "driver.lock"), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with mock.patch.object(Q, "LOCK_WAIT", 0.3):
                self.run_qa()
        finally:
            os.close(fd)
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertIn("QA driver could not run", self.last_reason())
        self.assertIn("E_LOCKED", self.last_reason())

    def test_the_red_evidence_records_that_the_engine_started_the_app(self):
        self.to_qa_red_verified()
        runs = json.loads(self.evidence("red", label=self.FORM)[-1]["runs"])
        self.assertTrue(runs and all(r["app_started"] is True for r in runs), runs)

    def test_the_driver_environment_is_scrubbed_like_a_test_run_M13(self):
        env_file = self.ws / "driver_env.json"
        self.boot_qa(policies={"redact_env": ["MY_QA_SECRET"]})
        self.plan(dump_env=str(env_file))
        with mock.patch.dict(os.environ, {"SENTINEL_DASHBOARD_TOKEN": "tok-123", "MY_QA_SECRET": "s3cret", "SENTINEL_TASK_ID": "t-x",
                                          "PLAIN_VAR": "kept"}):
            self.run_qa()
        seen = json.loads(env_file.read_text())
        for name in ("SENTINEL_DASHBOARD_TOKEN", "MY_QA_SECRET", "SENTINEL_TASK_ID"):
            self.assertNotIn(name, seen)
        self.assertEqual(seen.get("PLAIN_VAR"), "kept")

    def test_a_stale_report_is_ignored_M5(self):
        self.boot_qa()
        qa_dir = self.ws / ".sentinel" / "cache" / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        passing = '<testsuite name="qa"><testcase name="AC-4"/><testcase name="AC-5"/></testsuite>'
        stale = qa_dir / "qa-report.xml"
        stale.write_text(passing)
        old = stale.stat().st_mtime - 3600
        os.utime(stale, (old, old))
        (qa_dir / "driver.lock").touch()
        self.scripts_dir().mkdir(parents=True, exist_ok=True)  # the agent's folder exists before the report folder is made read-only
        self.plan(all="nothing")
        locked = os.geteuid() != 0  # a read-only folder keeps the engine from removing the file: only the age guard is left
        if locked:
            os.chmod(qa_dir, stat.S_IRUSR | stat.S_IXUSR)
        try:
            self.run_qa()
        finally:
            os.chmod(qa_dir, 0o755)
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertEqual(self.evidence("red", label=self.FORM)[-1]["classification"], "unknown")

    def test_a_report_written_just_before_the_run_is_removed_first_M5(self):
        self.boot_qa()
        qa_dir = self.ws / ".sentinel" / "cache" / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        (qa_dir / "qa-report.xml").write_text('<testsuite name="qa"><testcase name="AC-4"/><testcase name="AC-5"/></testsuite>')
        self.plan(all="nothing")
        self.run_qa()
        self.assertEqual(self.evidence("red", label=self.FORM)[-1]["classification"], "unknown")

    def test_a_report_the_agent_wrote_into_the_scripts_folder_is_not_evidence_M5(self):
        self.boot_qa()
        rel = f".sentinel/cache/qa/tests/current/{SLUG}"
        code = ("for sid, r in re.findall(r'^- `([^`]+)` -> `([^`]+)`$', prompt, re.M):\n    write(r, 'scenario ' + sid + '\\n')\n"
                "cyc = os.path.dirname(r)\n"
                "write(cyc + '/qa-report.xml', '<testsuite><testcase name=\"AC-4\"/><testcase name=\"AC-5\"/></testsuite>')\n"
                "write_result()")
        self.agent_exec("qa_red", code)
        self.plan(all="nothing")
        self.run_qa()
        self.assertEqual(self.evidence("red", label=self.FORM)[-1]["classification"], "unknown")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        del rel


if __name__ == "__main__":
    unittest.main()
