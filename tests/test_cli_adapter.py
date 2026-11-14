"""Phase C part 2 (PC-02): CLI adapter through `sentinel task run`, plus PC-01 leftovers AGT-03d/e, VIS-03b/c."""
import json
import os
import stat
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from pc_helpers import (FINISHED_KEYS, STARTED_KEYS, PCX, SENTINEL, SLUG, alive, git, wait_until)  # noqa: E402

GOOD = """
write("backend/docs/leave.md", "leave\\n")
write_result()
"""


class Headless(PCX):
    def setUp(self):
        super().setUp()
        self.boot({"fake": (GOOD, {})}, {"docs": "fake"})

    def test_AC_AGT_04a_headless_task_run(self):
        self.script("fake", GOOD + "\nprint('cwd=' + os.getcwd())\n")
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 0, out + err)
        row = self.task(tid)
        self.assertEqual(row["state"], "COMPLETED")
        d = self.tdir(tid)
        log = (d / "output.log").read_text()
        self.assertIn(f"cwd={self.ws / 'backend'}", log)
        prompt = (d / "prompt.md").read_text()
        self.assertIn("You write the documentation", prompt)  # docs stage template
        self.assertIn(self.task_json(tid)["objective"], prompt)  # rendered from task.json
        self.assertIn(f"Result file (absolute path): {d / 'result.json'}", prompt)
        for name in ("prompt.md", "output.log", "stderr.log", "task.json"):
            self.assertTrue((d / name).is_file(), name)
        self.assertEqual((row["provider"], row["adapter"]), ("fake", "cli"))
        self.assertTrue(row["started_at"] and row["finished_at"])
        self.assertIsNotNone(row["seconds"])
        doc = json.loads(out)
        self.assertEqual((doc["task_id"], doc["state"]), (tid, "COMPLETED"))
        self.assertEqual(doc["log"], str(d / "output.log"))

    def test_AC_AGT_04b_heartbeat_is_stored_as_progress_events(self):
        self.script("fake", """
        for i in range(3):
            write(f"backend/docs/part{i}.md")
            time.sleep(1)
        write_result()
        """)
        tid = self.docs_task()
        code, out, err = self.run_json(tid, SENTINEL_HEARTBEAT_SECONDS="1")
        self.assertEqual(code, 0, out + err)
        events = self.ev(tid, "task.progress")
        self.assertGreaterEqual(len(events), 2)
        for e in events:
            self.assertTrue({"elapsed_seconds", "output_bytes", "changed_files"} <= set(e["payload"]), e["payload"])
        self.assertIn("[backend-docs] running 0m01s", err)

    def test_AC_AGT_04c_output_log_is_readable_while_the_task_runs(self):
        self.script("fake", "say('step 1')\ntime.sleep(3)\nwrite_result()\n")
        tid = self.docs_task()
        p = self.popen("task", "run", tid)
        log = self.tdir(tid) / "output.log"
        self.assertTrue(wait_until(lambda: log.is_file() and "step 1" in log.read_text(), 2.5))
        self.assertEqual(self.task(tid)["state"], "RUNNING")
        self.finish(p)


class Failures(PCX):
    def boot_one(self, body, **kw):
        self.boot({"fake": (body, {})}, {"docs": "fake"}, **kw)

    def test_AC_AGT_05a_non_zero_exit_fails_the_task(self):
        self.boot_one("write_result()\nprint('boom line', file=sys.stderr)\nsys.exit(7)\n")
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 1, out + err)
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_EXIT"))
        self.assertEqual(self.ev(tid, "task.finished")[0]["payload"]["exit_code"], 7)
        self.assertIn("boom line", out + err)

    def test_AC_AGT_05b_timeout_kills_the_process_group(self):
        pids = str(self.ws / "pids.txt")
        self.boot_one(self.write_pids_script(pid_file=pids))
        tid = self.docs_task(timeout_seconds=2)
        started = time.time()
        code, out, err = self.run_json(tid, SENTINEL_HEARTBEAT_SECONDS="1")
        self.assertEqual(code, 1, out + err)
        self.assertLess(time.time() - started, 15)
        self.assertEqual(self.task(tid)["error_code"], "E_TIMEOUT")
        for pid in self.pids(pids):
            self.assertFalse(alive(pid), pid)
        self.assertTrue((self.tdir(tid) / "stderr.log").read_text().rstrip().endswith("timeout"))

    def test_AC_AGT_05c_finishing_just_before_the_timeout_completes(self):
        self.boot_one("time.sleep(2)\nwrite_result()\n")
        tid = self.docs_task(timeout_seconds=5)
        code, out, err = self.run_json(tid, SENTINEL_HEARTBEAT_SECONDS="1")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.task(tid)["state"], "COMPLETED")

    def test_AC_AGT_05d_missing_result_fails_the_task(self):
        self.boot_one("say('All done')\n")
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 1, out + err)
        self.assertEqual(self.task(tid)["error_code"], "E_RESULT_SCHEMA")
        self.assertIn("All done", (self.tdir(tid) / "output.log").read_text())


BOUNDARY_ROWS = {
    "stray_repo": ('write("frontend/stray.txt")', "frontend/stray.txt", "repo_not_allowed"),
    "commit": ('subprocess.run(["git", "-c", "user.name=a", "-c", "user.email=a@b.c", "commit", "--allow-empty", "-m", "x"], check=True)',
               "backend: HEAD moved", "head_moved"),
    "config": ('open(ws + "/sentinel.config.yaml", "a").write("# edit\\n")', "sentinel.config.yaml", "config_changed"),
    "skills": ('write(".claude/skills/x.md")', ".claude/skills", "config_changed"),
    "state_in_repo": ('write("backend/.sentinel/runs/x.json", "{}")', "backend/.sentinel", "state_in_repo"),
}


def _boundary_case(action, listed, kind):
    def test(self):
        self.boot({"fake": (f"{action}\nwrite_result()\n", {})}, {"docs": "fake"})
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 3, out + err)
        row = self.task(tid)
        self.assertEqual((row["state"], row["error_code"]), ("FAILED", "E_SCOPE"))
        events = self.ev(tid, "task.scope_violation")
        self.assertEqual([e["payload"]["kind"] for e in events], [kind])
        self.assertIn(listed, events[0]["payload"]["paths"])
        self.assertEqual(len(self.states("docs")), 1)  # no retry
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        reason = [e for e in self.events("run.state_changed") if e["payload"]["to"] == "NEEDS_HUMAN"][-1]["payload"]["reason"]
        self.assertIn("scope violation", reason)
        self.assertIn(tid, reason)
    return test


for _key, (_a, _l, _k) in BOUNDARY_ROWS.items():
    setattr(Failures, f"test_AC_AGT_06b_{_key}_violation_fails_and_is_not_retried", _boundary_case(_a, _l, _k))


class Boundary(PCX):
    def test_AC_AGT_06b_changes_are_left_in_place(self):
        self.boot({"fake": ('write("frontend/stray.txt")\nwrite_result()\n', {})}, {"docs": "fake"})
        code, out, err = self.run_json(self.docs_task())
        self.assertEqual(code, 3)
        self.assertTrue((self.ws / "frontend/stray.txt").exists())

    def test_AC_AGT_06c_read_only_task_that_writes_anything_is_a_violation(self):
        self.boot({"fake": ('write("backend/notes.txt")\nwrite_result()\n', {})}, {"reviewer": "fake"})
        tid = self.make("reviewer", ["backend"], [])
        self.eng.queue_task(tid)
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 3, out + err)
        self.assertEqual((self.task(tid)["state"], self.task(tid)["error_code"]), ("FAILED", "E_SCOPE"))

    def test_AC_AGT_06d_scope_violation_wins_over_a_non_zero_exit(self):
        self.boot({"fake": ('write("frontend/stray.txt")\nsys.exit(1)\n', {})}, {"docs": "fake"})
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 3, out + err)
        self.assertEqual(self.task(tid)["error_code"], "E_SCOPE")


class Isolation(PCX):
    def test_AC_SEC_02a_secrets_and_dashboard_token_are_not_passed(self):
        self.boot({"fake": ("print('\\n'.join(f'{k}={v}' for k, v in os.environ.items()))\nwrite_result()\n", {})},
                  {"docs": "fake"}, policies={"redact_env": ["DATABASE_URL"]})
        tid = self.docs_task()
        code, out, err = self.run_json(tid, SENTINEL_DASHBOARD_TOKEN="tok", DATABASE_URL="postgres://x")
        self.assertEqual(code, 0, out + err)
        log = (self.tdir(tid) / "output.log").read_text()
        self.assertIn("HOME=", log)
        self.assertIn(f"SENTINEL_TASK_ID={tid}", log)
        self.assertNotIn("SENTINEL_DASHBOARD_TOKEN", log)
        self.assertNotIn("DATABASE_URL", log)

    def test_AC_AGT_06e_task_process_cannot_start_or_complete_tasks(self):
        # one workspace: the qa task stays queued, the docs task runs the fake
        self.boot({"fake": ("pass", {})}, {"docs": "fake"})
        for command in ("run", "complete"):
            with self.subTest(command):
                rec = self.ws / f"rec-{command}.txt"
                qa = self.make("qa", ["backend"], [])
                self.eng.queue_task(qa)
                self.script("fake", f"""
                r = subprocess.run([sys.executable, {SENTINEL!r}, "--dir", {str(self.ws)!r}, "task", {command!r}, {qa!r}],
                                   capture_output=True, text=True)
                open({str(rec)!r}, "w").write(f"{{r.returncode}}\\n{{r.stdout}}{{r.stderr}}")
                write_result()
                """)
                tid = self.docs_task(write=[f"backend/docs/{command}/**"])
                code, out, err = self.run_json(tid)
                self.assertEqual(code, 0, out + err)
                code_s, text = rec.read_text().split("\n", 1)
                self.assertEqual(code_s, "5")
                self.assertIn("E_ACTOR", text)
                self.assertEqual(self.task(qa)["state"], "QUEUED")
                rows = [r for r in self.audit("task_refused") if tid in (r["reason"] or "")]
                self.assertEqual(len(rows), 1)


def _runner_cli(ws_bin, name="no-such-agent-cli"):
    path = Path(ws_bin) / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


MISSING = {"command": "no-such-agent-cli"}


class MissingRunner(PCX):
    def boot_missing(self, **cfg):
        self.boot({"fake": ("pass", MISSING)}, {"docs": "fake"}, **cfg)
        self.good = self.script("fake2", GOOD)
        return self.docs_task()

    def test_AC_AGT_05e_missing_runner_blocks_the_run(self):
        tid = self.boot_missing()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 6, out + err)
        self.assertEqual(self.task(tid)["state"], "QUEUED")
        self.assertEqual(len(self.states("docs")), 1)
        self.assertEqual(self.state(), "BLOCKED")
        changed = self.events("run.state_changed")[-1]["payload"]
        self.assertEqual((changed["transition"], changed["reason"]), ("R21", "runner not installed: no-such-agent-cli"))
        self.assertIn("install no-such-agent-cli or change agents.docs", out + err)

    def test_AC_AGT_05f_run_resumes_once_the_runner_is_installed(self):
        tid = self.boot_missing()
        self.run_json(tid)
        self.assertEqual(self.state(), "BLOCKED")
        _runner_cli(self.ws / self.BIN)
        code, step, err = self.next_json(PATH=f"{self.ws / self.BIN}{os.pathsep}{os.environ['PATH']}")
        self.assertEqual(self.state(), "EXECUTING", err)
        self.assertEqual(self.events("run.state_changed")[-1]["payload"]["transition"], "R22")
        self.assertEqual((step["kind"], step["task"]), ("task", tid))

    def test_AC_AGT_05g_fallback_provider_runs_the_task(self):
        self.boot({"fake": ("pass", MISSING), "fake2": (GOOD, {})}, {"docs": "fake"},
                  providers={"fallback": ["fake2"]})
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 0, out + err)
        self.assertEqual((self.task(tid)["state"], self.task(tid)["provider"]), ("COMPLETED", "fake2"))
        started = self.ev(tid, "task.started")[0]["payload"]
        self.assertEqual(started["fallback"], {"from": "fake", "to": "fake2"})

    def test_AC_AGT_05h_disabled_or_missing_fallback_is_skipped(self):
        rows = [(["fake2"], ["fake2"], 6, "BLOCKED", None), (["gone", "fake2"], [], 0, "EXECUTING", "fake2"),
                ([], [], 6, "BLOCKED", None)]
        for i, (fallback, disabled, code, state, provider) in enumerate(rows):
            with self.subTest(fallback=fallback, disabled=disabled):
                got = self._fallback_case(i, fallback, disabled)
                self.assertEqual(got[0], code, got[2])
                self.assertEqual(got[1], state)
                self.assertEqual(got[3], provider)

    def _fallback_case(self, i, fallback, disabled):
        slug = f"fb-{i}"
        self.use_config(single_model=False, runners={"fake": {"command": "no-such-agent-cli"},
                                                      "fake2": {"command": self.script("fake2", GOOD)}},
                        agents={"docs": {"runner": "fake"}}, providers={"fallback": fallback, "disabled": disabled})
        self.executing(slug)
        tid = self.make("docs", ["backend"], ["backend/docs/**"], slug=slug)
        self.eng.queue_task(tid)
        code, out, err = self.cli("task", "run", tid)
        done = self.task(tid)
        return code, self.state(slug), out + err, done["provider"] if done["state"] == "COMPLETED" else None


class ModelCheck(PCX):
    def test_AC_AGT_03d_model_on_runner_without_model_flag_is_refused(self):
        self.boot({"local": ("pass", {})}, {"docs": {"runner": "local", "model": "big"}})
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 5, out + err)
        self.assertIn("E_VALIDATION", err)
        self.assertIn("runners.local has no model_flag", err)
        self.assertEqual(self.task(tid)["state"], "QUEUED")


class Templates(PCX):
    def test_role_without_a_stage_template_cannot_run_on_a_cli_runner(self):
        self.boot({"fake": (GOOD, {})}, {"test_designer": "fake"})
        tid = self.make("test_designer", ["backend"], [f"specs/{SLUG}/features/**"])
        self.eng.queue_task(tid)
        self.eng.reg.update_run(SLUG, state="SPECIFICATION_APPROVED")
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 5, out + err)
        self.assertIn("E_PRECONDITION", err)
        self.assertEqual(self.task(tid)["state"], "QUEUED")


SHAPES = {
    "fakec": ({"prompt_flag": "-p", "model_flag": "--model"}, False, ""),
    "fakex": ({}, False, ""),
    "fakes": ({"input": "stdin"}, True, ""),
    "fakea": ({"output": "json_response", "resume_flag": "--conversation"}, False,
              "print(json.dumps({'response': 'ok', 'conversation_id': 'conv-42', 'status': 'SUCCESS'}))"),
}


def _shape_case(runner, fields, stdin, tail):
    def test(self):
        self.boot({runner: (GOOD + tail + "\n", fields)}, {"docs": runner})
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.task(tid)["state"], "COMPLETED")
        doc = self.task_json(tid)
        self.assertEqual(doc["provider"], {"name": runner, "model": None, "adapter": "cli"})
        self.assertEqual(doc["permissions"]["write"], ["backend/docs/**"])
        types = [e["type"] for e in self.task_events(tid) if e["type"] != "task.created"]
        self.assertEqual(types, ["task.queued", "task.started", "task.finished"])
        started = self.ev(tid, "task.started")[0]["payload"]
        self.assertEqual((started["provider"], started["adapter"]), (runner, "cli"))
        self.assertEqual(json.loads(self.task(tid)["changed_files"]), ["backend/docs/leave.md"])
        self.assertTrue(FINISHED_KEYS <= set(self.ev(tid, "task.finished")[0]["payload"]))
        if runner == "fakea":
            self.assertEqual(self.task(tid)["session_id"], "conv-42")  # AC-AGT-03e
    return test


class Shapes(PCX):
    def test_AC_AGT_03e_session_id_of_a_json_runner_is_stored_on_the_task(self):
        runner, fields, stdin, tail = "fakea", *SHAPES["fakea"]
        self.boot({runner: (GOOD + tail + "\n", fields)}, {"docs": runner})
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.task(tid)["state"], "COMPLETED")
        self.assertEqual(self.task(tid)["session_id"], "conv-42")


for _r, (_f, _s, _t) in SHAPES.items():
    setattr(Shapes, f"test_AC_VIS_03b_same_task_completes_on_{_r}", _shape_case(_r, _f, _s, _t))


class NativeSameEnd(PCX):
    def test_AC_VIS_03c_native_adapter_reaches_the_same_end_state(self):
        self.use_config(single_model=True)
        self.executing()
        tid = self.docs_task()
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 0, out + err)
        (self.ws / "backend/docs").mkdir(exist_ok=True)
        (self.ws / "backend/docs/leave.md").write_text("leave\n")
        self.write_result(tid)
        code, out, err = self.cli("task", "complete", tid)
        self.assertEqual(code, 0, out + err)
        row = self.task(tid)
        self.assertEqual(row["state"], "COMPLETED")
        self.assertEqual(json.loads(row["changed_files"]), ["backend/docs/leave.md"])
        self.assertTrue(FINISHED_KEYS <= set(self.ev(tid, "task.finished")[0]["payload"]))
        started = self.ev(tid, "task.started")[0]["payload"]
        self.assertEqual((started["provider"], started["adapter"]), ("native", "native"))


if __name__ == "__main__":
    unittest.main()
