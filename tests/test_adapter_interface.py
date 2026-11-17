"""Phase C part 1 (PC-01): adapter interface, capabilities, adapter selection. Engine level."""
import json
import os
import stat
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from errors import SentinelError  # noqa: E402
from pc_helpers import PC, SLUG  # noqa: E402


class Capabilities(PC):
    def test_AC_AGT_03a_capabilities_come_from_runner_definition(self):
        rows = [("claude", True, False, "signal", False, False), ("codex", True, False, "signal", False, False),
                ("gemini", True, False, "signal", False, False), ("agy", True, True, "signal", True, False),
                ("native", False, False, "cooperative", True, True)]
        for runner, ms, resume, cancel, js, native in rows:
            with self.subTest(runner):
                caps = self.eng.adapter_for(runner).capabilities()
                self.assertEqual((caps.model_select, caps.resume, caps.cancel, caps.json_output, caps.native),
                                 (ms, resume, cancel, js, native))

    def test_AC_AGT_03b_custom_runner_capabilities_follow_its_fields(self):
        self.use_config(runners={"local": {"command": "local-agent"}})
        caps = self.eng.adapter_for("local").capabilities()
        self.assertEqual((caps.model_select, caps.resume, caps.cancel), (False, False, "signal"))

    def test_unknown_runner_is_E_VALIDATION(self):
        with self.assertRaises(SentinelError) as c:
            self.eng.adapter_for("nope")
        self.assertEqual(c.exception.code, "E_VALIDATION")

    def test_adapters_are_registered_by_name(self):
        import adapters
        self.assertEqual(sorted(adapters.ADAPTERS), ["cli", "native"])
        for name in ("capabilities", "submit", "status", "result", "cancel", "resume"):
            self.assertTrue(callable(getattr(adapters.Adapter, name)), name)


class Resume(PC):
    def waiting(self, adapter, runner, session):
        script = self.ws / "fake-agent"
        script.write_text('#!/bin/sh\necho "$@" > argv.txt\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        self.use_config(single_model=False, runners={"agy": {"command": str(script)}, "codex": {"command": str(script)}})
        self.executing()
        tid = self.make("docs")
        self.eng.reg.update_row("tasks", tid, state="WAITING_FOR_INPUT", adapter=adapter, provider=runner,
                                session_id=session)
        return tid

    def test_AC_AGT_03c_resume_is_refused_when_unsupported(self):
        rows = [("cli", "agy", "conv-9", None), ("cli", "agy", None, "no session id"),
                ("cli", "codex", "x", "resume not supported"), ("native", "native", None, "resume not supported")]
        for i, (adapter, runner, session, refusal) in enumerate(rows):
            with self.subTest(runner=runner, session=session):
                if i:
                    self.tearDown()
                    self.setUp()
                tid = self.waiting(adapter, runner, session)
                if refusal:
                    with self.assertRaises(SentinelError) as c:
                        self.eng.resume_task(tid, "Use ISO dates")
                    self.assertEqual(c.exception.code, "E_PRECONDITION")
                    self.assertIn(refusal, str(c.exception))
                    self.assertEqual(self.task(tid)["state"], "WAITING_FOR_INPUT")
                else:
                    row = self.eng.resume_task(tid, "Use ISO dates")
                    self.assertEqual(row["state"], "RUNNING")
                    argv = self.ws / "backend" / "argv.txt"
                    end = time.time() + 5
                    while not argv.exists() and time.time() < end:
                        time.sleep(0.05)
                    time.sleep(0.1)
                    self.assertIn("--conversation conv-9", argv.read_text())


class Selection(PC):
    def test_AC_PRV_05a_adapter_selection_per_role(self):
        codex = {"runner": "codex"}
        rows = [({"single_model": True, "routing": {"reviewer": codex}}, "reviewer", "native", "native", None),
                ({"routing": {"reviewer": codex}}, "reviewer", "native", "native", None),
                ({"single_model": False, "routing": {"reviewer": {"runner": "codex", "model": "gpt-5"}}}, "reviewer", "cli", "codex", "gpt-5"),
                ({"single_model": False, "routing": {"backend-reviewer": {"runner": "gemini"}}}, "reviewer", "cli", "gemini", None),
                ({"single_model": False}, "reviewer", "native", "native", None),
                ({"single_model": False, "agents": {"docs": {"runner": "codex", "model": "gpt-5"}}}, "docs", "cli", "codex", "gpt-5"),
                ({"single_model": False, "agents": {"docs": {"runner": "codex"}}, "routing": {"docs": {"runner": "gemini"}}}, "docs", "cli", "codex", None)]
        for i, (cfg, role, adapter, provider, model) in enumerate(rows):
            with self.subTest(i):
                self.use_config(**cfg)
                slug = f"sel-{i}"
                self.mk(slug, "EXECUTING", 3)
                row = self.eng.create_task(slug, role, "x", repos=["backend"])
                self.assertEqual((row["adapter"], row["provider"], row["model"]), (adapter, provider, model))
                doc = json.loads((self.tdir(row["id"], slug) / "task.json").read_text())
                self.assertEqual(doc["provider"]["name"], provider)

    def test_AC_CFG_08a_config_change_does_not_change_adapter(self):
        self.use_config(single_model=False, agents={"docs": {"runner": "codex"}})
        self.mk(SLUG, "EXECUTING", 3)
        self.use_config(single_model=True)
        row = self.eng.create_task(SLUG, "docs", "x", repos=["backend"])
        self.assertEqual((row["adapter"], row["provider"]), ("cli", "codex"))

    def test_AC_VIS_03a_workflow_names_no_provider(self):
        graph = self.eng.workflow_graph(3)
        self.assertTrue(graph)
        for node in graph:
            self.assertNotIn("provider", node)
            self.assertNotIn("adapter", node)
        from run_stage import DEFAULT_RUNNERS
        text = json.dumps(graph)
        for name in list(DEFAULT_RUNNERS) + ["native"]:
            self.assertNotIn(f'"{name}"', text)


if __name__ == "__main__":
    unittest.main()
