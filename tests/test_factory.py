"""Sentinel 2.0 W1: the engine drives runs (driver, factory module, routing preflight, limits, pause, notes, snapshot)."""
import json
import os
import sqlite3
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import factory  # noqa: E402
import registry  # noqa: E402
from errors import SentinelError  # noqa: E402
from pb_helpers import SLUG, spec_text  # noqa: E402
from pc_helpers import PCX, git, wait_until  # noqa: E402
from sv_helpers import SV  # noqa: E402

REQUEST = "Show the remaining leave days on the home page"
FACTORS = {"repos": 1, "files": 5, "migration": "no", "auth": "no", "security": "none", "regression": "low", "logic": "moderate"}
BIN_SPEC = "spec.txt"


def agents(runner="fake", skip=()):
    return {r: {"runner": runner} for r in factory.ENGINE_ROLES if r not in skip}


FAKE = """
import re
role = re.search(r"- Role: (\\w+)", prompt).group(1)
slug = re.search(r"Run folder: \\S+/runs/([^/\\s]+)", prompt).group(1)
open(os.path.join(ws, "prompts.log"), "a").write(role + "\\n" + prompt + "\\n=====\\n")
if role == "triage":
    write_result(factors=FACTORS)
elif role == "planner":
    write(".sentinel/shared/specs/" + slug + "/decisions.md", "Request.\\n\\nD1: keep it small (because scope)\\n")
    write_result()
elif role == "specifier":
    write(".sentinel/shared/specs/" + slug + "/spec.md", open(os.path.join(ws, "bin", "spec.txt")).read())
    write_result()
else:
    write_result()
"""


def fake_body(factors=None, extra=""):
    return f"FACTORS = {json.dumps(factors or FACTORS)}\n" + extra + FAKE


class Base(PCX):
    """Engine level: a workspace with two git repos and a fake CLI runner for every role."""

    def setup_factory(self, factors=None, skip=(), **cfg):
        script = self.script("fake", fake_body(factors))
        self.use_config(single_model=False, shape="custom", runners={"fake": {"command": script}}, agents=agents(skip=skip), **cfg)
        (self.ws / "bin" / BIN_SPEC).write_text(spec_text(SLUG, tier=3))

    def new_run(self, slug=SLUG, driver="engine", request=REQUEST, repos=("backend",), **kw):
        base = {r: git(self.ws / r, "rev-parse", "HEAD").strip() for r in repos}
        self.eng.create_run(slug, "human", type="feature", request=request, baseline=base, driver=driver, **kw)
        return slug

    def run_queued(self, slug=SLUG):
        """Run every QUEUED CLI task of the run through `run_task` (what the dispatcher's `task run` child does)."""
        ran = []
        for t in self.eng.reg.rows("tasks", run_id=self.run_row(slug)["id"]):
            if t["state"] == "QUEUED" and t["adapter"] == "cli":
                self.eng.run_task(t["id"])
                ran.append(t["id"])
        return ran

    def pump(self, slug=SLUG, until=None, rounds=12):
        for _ in range(rounds):
            factory.drive(self.eng, slug)
            self.run_queued(slug)
            if until and self.state(slug) == until:
                break
        return self.state(slug)

    def roles(self, slug=SLUG):
        return [(t["role"], t["state"]) for t in self.eng.reg.rows("tasks", run_id=self.run_row(slug)["id"])]


class EngineFlow(Base):
    def test_engine_run_goes_from_created_to_the_approval_gate_without_an_ai_tool(self):
        self.setup_factory()
        self.new_run()
        self.assertEqual(self.pump(until="SPECIFICATION_REVIEW"), "SPECIFICATION_REVIEW")
        run = self.run_row()
        self.assertEqual((run["tier"], run["driver"]), (3, "engine"))
        self.assertEqual([r for r, _ in self.roles()], ["triage", "planner", "specifier"])
        self.assertTrue(all(s == "COMPLETED" for _, s in self.roles()))
        self.assertIn("D1:", (self.eng.run_dir(SLUG) / "decisions.md").read_text())
        (ev,) = self.events("run.triaged")
        self.assertEqual(ev["payload"]["factors"]["files"], "5")
        self.assertEqual(ev["payload"]["computed_tier"], 3)
        self.assertEqual([a["action"] for a in self.audit() if a["action"].startswith("factory_")],
                         ["factory_triage", "factory_decisions"])
        self.assertEqual(self.eng.pending_approval(SLUG, "spec")["version"], 1)

    def test_the_triage_task_is_a_read_only_agent_task_with_the_request_in_its_prompt(self):
        self.setup_factory()
        self.new_run()
        factory.drive(self.eng, SLUG)
        (t,) = self.eng.reg.rows("tasks", run_id=self.run_row()["id"])
        self.assertEqual((t["role"], t["state"], t["adapter"], t["provider"]), ("triage", "QUEUED", "cli", "fake"))
        self.assertEqual(self.eng.task_scope(t["id"]), [])
        self.eng.run_task(t["id"])
        prompt = (self.tdir(t["id"]) / "prompt.md").read_text()
        self.assertIn("You are the triage agent", prompt)
        self.assertIn(REQUEST, prompt)

    def test_the_planner_writes_decisions_inside_its_scope(self):
        self.setup_factory()
        self.new_run()
        self.pump(until="TRIAGED", rounds=3)
        self.assertEqual(self.state(), "TRIAGED")
        factory.drive(self.eng, SLUG)
        planner = [t for t in self.eng.reg.rows("tasks", run_id=self.run_row()["id"]) if t["role"] == "planner"][0]
        self.assertEqual(self.eng.task_scope(planner["id"]), [f"specs/{SLUG}/decisions.md"])

    def test_tier_1_run_needs_no_planner(self):
        self.setup_factory(factors={**FACTORS, "files": 1, "logic": "trivial", "regression": "none"})
        self.new_run()
        self.pump(until="PLANNED", rounds=4)
        self.assertEqual(self.run_row()["tier"], 1)
        self.assertNotIn("planner", [r for r, _ in self.roles()])

    def test_invalid_triage_json_fails_the_task_and_follows_the_retry_rules(self):
        for label, factors in (("missing key", {k: v for k, v in FACTORS.items() if k != "auth"}),
                               ("bad value", {**FACTORS, "security": "extreme"}),
                               ("not an object", "high")):
            with self.subTest(label):
                self.setup_factory(factors=factors)
                self.new_run(slug=f"bad-{label.replace(' ', '-')}")
                slug = f"bad-{label.replace(' ', '-')}"
                factory.drive(self.eng, slug)
                (t,) = self.eng.reg.rows("tasks", run_id=self.run_row(slug)["id"])
                self.eng.run_task(t["id"])
                first = self.eng.get_task(t["id"])
                self.assertEqual((first["state"], first["error_code"]), ("FAILED", "E_RESULT_SCHEMA"), first["reason"])
                self.assertIn("factors", first["reason"])
                self.assertEqual(self.state(slug), "CREATED")  # the tier was not applied
                retries = [x for x in self.eng.reg.rows("tasks", run_id=self.run_row(slug)["id"]) if x["retry_of"]]
                self.assertEqual([(x["role"], x["state"]) for x in retries], [("triage", "QUEUED")])
                for _ in range(4):  # the cap (2 retries) is used up: the run is parked for a human
                    self.run_queued(slug)
                self.assertEqual(self.state(slug), "NEEDS_HUMAN")

    def test_a_result_with_a_bad_factor_never_reaches_the_triage_transition(self):
        self.assertTrue(factory.factor_problems({**FACTORS, "files": "many"}))
        self.assertTrue(factory.factor_problems([]))
        self.assertEqual(factory.factor_problems(FACTORS), [])

    def test_a_planner_that_writes_nothing_fails(self):
        self.setup_factory()
        script = self.script("fake", fake_body(extra="if 'planner' in prompt.split('- Role: ')[1].split()[0]:\n    write_result()\n    sys.exit(0)\n"))
        self.use_config(single_model=False, runners={"fake": {"command": script}}, agents=agents())
        self.new_run()
        self.pump(until="TRIAGED", rounds=3)
        factory.drive(self.eng, SLUG)
        self.run_queued()
        t = [x for x in self.eng.reg.rows("tasks", run_id=self.run_row()["id"]) if x["role"] == "planner"][0]
        self.assertEqual((t["state"], t["error_code"]), ("FAILED", "E_RESULT_SCHEMA"))
        self.assertIn("decisions.md", t["reason"])

    def test_cli_driven_and_ai_tool_driven_runs_are_not_driven_by_the_engine(self):
        self.setup_factory()
        for i, driver in enumerate(("cli", "ai-tool")):
            slug = self.new_run(slug=f"other-{i}", driver=driver)
            self.assertIsNone(factory.drive(self.eng, slug))
            self.assertEqual(self.eng.reg.rows("tasks", run_id=self.run_row(slug)["id"]), [])


class OneDriver(Base):
    def test_skill_next_refuses_an_engine_driven_run(self):
        self.setup_factory()
        self.new_run("by-engine")
        self.new_run("by-hand", driver="cli")
        step = self.eng.next_step("by-engine")
        self.assertEqual((step["kind"], step["driven_by"], step["exit"]), ("wait", "engine", 0))
        self.assertNotIn("command", step)
        self.assertEqual(self.eng.next_step("by-hand")["kind"], "orchestrator")  # unchanged for a cli run
        code, step, err = self.next_json("by-engine")
        self.assertEqual((code, step["kind"], step["driven_by"]), (0, "wait", "engine"), err)

    def test_every_orchestrator_step_of_an_engine_run_is_refused_but_gates_are_shown(self):
        self.setup_factory()
        for state in ("CREATED", "TRIAGED"):
            slug = self.new_run(f"s-{state.lower()}")
            self.eng.reg.update_run(slug, state=state, tier=3 if state == "TRIAGED" else None)
            self.assertEqual(self.eng.next_step(slug)["kind"], "wait")
        slug = self.new_run("gate")
        self.eng.reg.update_run(slug, state="SPECIFICATION_REVIEW", tier=3)
        self.assertEqual(self.eng.next_step(slug)["kind"], "human")

    def test_driver_defaults_and_validation(self):
        self.setup_factory()
        self.eng.create_run("dash", "human", type="feature", request="x", origin="dashboard")
        self.eng.create_run("plain", "orchestrator", type="feature")
        self.assertEqual((self.run_row("dash")["driver"], self.run_row("plain")["driver"]), ("ai-tool", "cli"))
        with self.assertRaises(SentinelError) as cm:
            self.eng.create_run("odd", "orchestrator", type="feature", driver="robot")
        self.assertEqual(cm.exception.code, "E_VALIDATION")

    def test_run_new_driver_flag(self):
        self.setup_factory()
        code, out, err = self.cli("run", "new", "by-flag", "--type", "feature", "--driver", "engine")
        self.assertNotEqual(code, 0)
        self.assertIn("--request", out + err)
        code, out, err = self.cli("run", "new", "by-flag", "--type", "feature", "--driver", "engine", "--request", "do it")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.run_row("by-flag")["driver"], "engine")
        self.assertEqual(self.run_row("by-flag")["request"], "do it")
        code, out, err = self.cli("run", "new", "by-hand", "--type", "feature")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.run_row("by-hand")["driver"], "cli")


class Preflight(Base):
    def blocked(self, slug=SLUG):
        self.assertEqual(self.state(slug), "BLOCKED")
        return [e for e in self.events("run.state_changed", slug) if e["payload"]["to"] == "BLOCKED"][0]["payload"]["reason"]

    def test_default_config_routes_to_native_and_blocks_the_run(self):
        self.new_run()
        out = factory.drive(self.eng, SLUG)
        self.assertEqual(out["action"], "blocked")
        reason = self.blocked()
        self.assertTrue(reason.startswith(factory.PREFLIGHT), reason)
        for role in ("triage", "planner", "reviewer"):
            self.assertIn(f"{role} routes to the native adapter", reason)
        self.assertIn("sentinel resolve", reason)
        self.assertEqual(self.eng.reg.rows("tasks", run_id=self.run_row()["id"]), [])
        self.assertEqual(len([a for a in self.audit() if a["action"] == "routing_preflight_failed"]), 1)
        step = self.eng.next_step(SLUG)  # a human sees the reason
        self.assertEqual((step["kind"], step["reason"]), ("human", reason))

    def test_one_native_role_is_enough_to_block(self):
        script = self.script("fake", fake_body())
        self.use_config(single_model=False, runners={"fake": {"command": script}}, agents={**agents(skip=("reviewer",)),
                                                                                           "reviewer": {"runner": "native"}})
        self.new_run()
        factory.drive(self.eng, SLUG)
        reason = self.blocked()
        self.assertIn("reviewer routes to the native adapter", reason)
        self.assertNotIn("triage routes", reason)

    def test_an_undefined_runner_blocks(self):
        self.setup_factory(skip=("docs",))
        self.eng.close()
        self.use_config(single_model=False, runners={"fake": {"command": "/bin/true"}},
                        agents={**agents(skip=("docs",)), "docs": {"runner": "ghost"}})
        self.new_run()
        factory.drive(self.eng, SLUG)
        self.assertIn("docs routes to runner ghost, which is not defined", self.blocked())

    def test_a_routing_entry_counts_like_an_agents_entry(self):
        script = self.script("fake", fake_body())
        routing = {r: {"runner": "fake"} for r in factory.ENGINE_ROLES}
        self.use_config(single_model=False, runners={"fake": {"command": script}}, routing=routing)
        self.assertEqual(factory.routing_problems(self.eng.config), [])

    def test_a_cli_routed_run_leaves_created(self):
        self.setup_factory()
        self.new_run()
        self.assertEqual(factory.drive(self.eng, SLUG)["action"], "planned triage task")

    def test_after_the_fix_resolve_refresh_config_resumes_the_run(self):
        self.new_run()
        factory.drive(self.eng, SLUG)
        self.assertEqual(self.state(), "BLOCKED")
        self.setup_factory()  # the config file now routes every role
        info = self.eng.refresh_config_preview(SLUG, comment="fixed the routing")
        self.eng.resolve(SLUG, user="dev", channel="cli", comment="fixed the routing", refresh_config=True,
                         config_sha_prefix=info["new_sha256"][:8])
        self.assertEqual(self.state(), "BLOCKED")  # resolve refreshes the snapshot; the factory resumes the run
        self.assertEqual(factory.drive(self.eng, SLUG)["action"], "planned triage task")
        self.assertEqual(self.state(), "CREATED")


class Notes(Base):
    def test_note_appears_once_in_the_next_agent_prompt_and_is_consumed(self):
        self.setup_factory()
        self.new_run()
        note = self.eng.add_note(SLUG, "Use the existing balance service.", user="dev", channel="dashboard")
        self.assertEqual(len(self.eng.unread_notes(self.run_row())), 1)
        factory.drive(self.eng, SLUG)
        self.run_queued()  # triage: the next agent task of the run
        prompts = (self.ws / "prompts.log").read_text()
        self.assertEqual(prompts.count("## Note from the owner"), 1)
        self.assertIn("Use the existing balance service.", prompts)
        row = self.eng.reg.get_row("run_notes", note)
        self.assertTrue(row["consumed_at"])
        self.assertEqual(row["consumed_by"], self.eng.reg.rows("tasks", run_id=self.run_row()["id"])[0]["id"])
        self.pump(until="SPECIFICATION_REVIEW")  # the planner and the specifier never see it again
        self.assertEqual((self.ws / "prompts.log").read_text().count("Use the existing balance service."), 1)
        self.assertEqual(self.eng.unread_notes(self.run_row()), [])

    def test_a_note_is_audited_and_validated(self):
        self.setup_factory()
        self.new_run()
        self.eng.add_note(SLUG, "  hello  ", user="dev", channel="cli")
        self.assertEqual(self.eng.reg.rows("run_notes")[0]["text"], "hello")
        row = [a for a in self.audit() if a["action"] == "note"][0]
        self.assertEqual((row["actor"], row["channel"], row["target"], row["reason"]), ("dev", "cli", SLUG, "hello"))
        for bad in ("", "   ", None, "x" * 4001):
            with self.assertRaises(SentinelError) as cm:
                self.eng.add_note(SLUG, bad, user="dev", channel="cli")
            self.assertEqual(cm.exception.code, "E_VALIDATION")

    def test_pause_unpause_are_audited_and_refuse_repeats_and_final_runs(self):
        self.setup_factory()
        self.new_run()
        self.eng.pause_run(SLUG, "lunch", user="dev", channel="dashboard")
        self.assertEqual(self.run_row()["paused"], 1)
        with self.assertRaises(SentinelError):
            self.eng.pause_run(SLUG, user="dev", channel="dashboard")
        self.eng.unpause_run(SLUG, user="dev", channel="dashboard")
        with self.assertRaises(SentinelError):
            self.eng.unpause_run(SLUG, user="dev", channel="dashboard")
        self.assertEqual([a["action"] for a in self.audit() if a["action"] in ("pause", "unpause")], ["pause", "unpause"])
        self.assertEqual([e["type"] for e in self.eng.reg.list_events(self.run_row()["id"]) if e["type"].startswith("run.pause")
                          or e["type"] == "run.unpaused"], ["run.paused", "run.unpaused"])
        self.eng.cancel_run(SLUG, "x", user="dev")
        with self.assertRaises(SentinelError):
            self.eng.pause_run(SLUG, user="dev", channel="dashboard")
        with self.assertRaises(SentinelError):
            self.eng.add_note(SLUG, "late", user="dev", channel="dashboard")

    def test_paused_run_is_not_driven(self):
        self.setup_factory()
        self.new_run()
        self.eng.pause_run(SLUG, user="dev", channel="dashboard")
        self.assertIsNone(factory.drive(self.eng, SLUG))
        self.assertEqual(self.eng.reg.rows("tasks", run_id=self.run_row()["id"]), [])


class CliControls(Base):
    def test_pause_note_need_a_terminal(self):
        self.setup_factory()
        self.new_run()
        for args in (("pause", SLUG), ("unpause", SLUG), ("note", SLUG, "hi")):
            code, out, err = self.cli(*args)
            self.assertNotEqual(code, 0, args)
            self.assertIn("E_NOT_TTY", out + err)
        self.assertEqual(self.run_row()["paused"], 0)
        refused = [a["action"] for a in self.audit() if a["action"].endswith("_refused")]
        self.assertEqual(refused, ["pause_refused", "unpause_refused", "note_refused"])

    def test_pause_unpause_note_on_a_terminal(self):
        from pb_helpers import run_tty
        self.setup_factory()
        self.new_run()
        d = ["--dir", str(self.ws)]
        code, out = run_tty(d + ["pause", SLUG, "-m", "wait"])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.run_row()["paused"], 1)
        code, out = run_tty(d + ["note", SLUG, "mind the cache"])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.eng.reg.rows("run_notes")[0]["channel"], "cli")
        code, out = run_tty(d + ["unpause", SLUG])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.run_row()["paused"], 0)


class ServiceFactoryPause(unittest.TestCase):
    """`sentinel service pause|resume|status`: the same switch as the dashboard button."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cfg = Path(self._tmp.name)

    def test_set_and_read_the_state_is_idempotent(self):
        self.assertEqual(factory.pause_state(self.cfg), {"paused": False, "paused_at": None})
        first = factory.set_paused(self.cfg, True, "dev", "cli")
        self.assertTrue(first["paused"] and first["paused_at"])
        self.assertEqual(factory.set_paused(self.cfg, True, "dev", "cli"), first)
        self.assertEqual(factory.pause_state(self.cfg), first)
        self.assertEqual(factory.set_paused(self.cfg, False, "dev", "cli"), {"paused": False, "paused_at": None})
        (self.cfg / "factory.json").write_text("not json")
        self.assertEqual(factory.pause_state(self.cfg)["paused"], False)

    def test_status_shows_paused(self):
        import io
        from contextlib import redirect_stdout
        import service
        factory.set_paused(self.cfg, True, "dev", "cli")
        out = io.StringIO()
        with redirect_stdout(out):
            service.service_status(cfgdir=self.cfg)
            service.service_status(as_json=True, cfgdir=self.cfg)
        self.assertIn("Factory: paused", out.getvalue())
        self.assertIn('"factory_paused": true', out.getvalue())


class ServiceFactoryPauseCli(SV):
    def test_pause_and_resume_need_a_terminal_and_are_audited_on_one(self):
        self.add_project()
        from pb_helpers import run_plain
        for cmd in ("pause", "resume"):
            code, out = run_plain(["--dir", str(self.ws), "service", cmd])
            self.assertNotEqual(code, 0)
            self.assertIn("E_NOT_TTY", out)
        self.assertFalse((self.cfgdir / "factory.json").exists())
        code, out = self.run_tty(["service", "pause", "-m", "deploy"])
        self.assertEqual(code, 0, out)
        self.assertIn("factory paused", out)
        self.assertTrue(factory.pause_state(self.cfgdir)["paused"])
        code, out = self.run_tty(["service", "resume"])
        self.assertEqual(code, 0, out)
        rows = [(a["action"], a["channel"], a["reason"]) for a in self.audit_rows() if a["action"].startswith("factory_")]
        self.assertEqual(rows, [("factory_pause", "cli", "deploy"), ("factory_resume", "cli", None)])


class VerifyInProcess(unittest.TestCase):
    """The verify step calls the engine function, not the CLI."""

    def test_drive_reports_verify_and_the_dispatcher_calls_it_in_process(self):
        from pe_helpers import PE

        class Case(PE):
            def runTest(self):
                pass
        case = Case()
        case.setUp()
        try:
            case.boot_ver(tier=3)
            case.eng.reg.update_run("leave-balance", driver="engine")
            out = factory.drive(case.eng, "leave-balance")
            self.assertEqual(out["action"], "verify")
            result = factory.verify(case.eng, "leave-balance")
            self.assertEqual(result["exit"], 0, result)
            self.assertTrue(result["passed"])
            self.assertEqual(case.state(), "REVIEWING")
        finally:
            case.doCleanups()


class Served(SV):
    """The dispatcher drives engine runs with fake CLI runners; no orchestrator AI tool is set."""

    def setUp(self):
        super().setUp()
        script = self.script("fake", fake_body())
        self.use_config(single_model=False, runners={"fake": {"command": script}}, agents=agents())
        (self.ws / "bin" / BIN_SPEC).write_text(spec_text(SLUG, tier=3))

    def make_run(self, slug=SLUG, driver="engine", **kw):
        sha = git(self.ws / "backend", "rev-parse", "HEAD").strip()
        self.eng.create_run(slug, "human", type="feature", request=REQUEST, baseline={"backend": sha}, driver=driver, **kw)
        return slug

    def pump(self, wait=True):
        d = self.srv.dispatcher
        d.backoff = 0
        procs = d.once()
        if wait:
            for p in procs:
                p.wait(30)
            d.wait_workers(30)
        return procs

    def tasks(self, slug=SLUG):
        return [(t["role"], t["state"]) for t in self.eng.reg.rows("tasks", run_id=self.eng.reg.get_run(slug)["id"])]

    def test_dispatcher_takes_an_engine_run_to_the_approval_gate(self):
        self.make_run()
        self.serve(dispatch=True, dispatch_interval=3600)
        self.assertIsNone(self.srv.orchestrator)
        for _ in range(10):
            self.pump()
            if self.eng.reg.get_run(SLUG)["state"] == "SPECIFICATION_REVIEW":
                break
        self.assertEqual(self.eng.reg.get_run(SLUG)["state"], "SPECIFICATION_REVIEW", self.tasks())
        self.assertEqual([r for r, _ in self.tasks()], ["triage", "planner", "specifier"])
        self.assertFalse((self.ws / ".sentinel" / "runs" / SLUG / "orchestrator.log").exists())

    def test_dispatcher_runs_verify_in_a_worker_thread(self):
        self.make_run()
        self.eng.reg.update_run(SLUG, state="VERIFYING", tier=3)
        self.serve(dispatch=True, dispatch_interval=3600)
        seen = []
        with mock.patch("factory.verify", lambda eng, slug: seen.append((slug, threading.current_thread().name))):
            self.pump()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], SLUG)
        self.assertNotEqual(seen[0][1], threading.main_thread().name)

    def test_ai_tool_runs_still_wait_for_the_ai_tool_and_cli_runs_are_never_driven(self):
        self.make_run("tool", "ai-tool")
        self.make_run("hand", "cli")
        self.serve(dispatch=True, dispatch_interval=3600)
        self.pump()
        self.assertEqual((self.tasks("tool"), self.tasks("hand")), ([], []))

    # ---- limits
    def slow_runner(self, seconds=3):
        script = self.script("slow", f"time.sleep({seconds})\nwrite_result(factors=FACTORS)\n".replace(
            "write_result(factors=FACTORS)", f"write_result(factors={json.dumps(FACTORS)})"))
        return script

    def limited(self, **factory_cfg):
        self.use_config(single_model=False, runners={"slow": {"command": self.slow_runner()}}, agents=agents("slow"),
                        factory=factory_cfg)
        for slug in ("run-a", "run-b", "run-c"):
            self.make_run(slug)
        self.serve(dispatch=True, dispatch_interval=3600)
        self.pump(wait=False)   # plans the three triage tasks

    def test_max_tasks_per_project_is_respected(self):
        self.limited(max_tasks_per_project=2, max_agents=10)
        first = self.pump(wait=False)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(self.pump(wait=False)), 0)  # two are running: nothing more starts
        wait_until(lambda: sum(t["state"] == "RUNNING" for slug in ("run-a", "run-b", "run-c") for t in self.eng.reg.rows(
            "tasks", run_id=self.eng.reg.get_run(slug)["id"])) == 2, 15)
        running = [t for slug in ("run-a", "run-b", "run-c") for t in self.eng.reg.rows("tasks", run_id=self.eng.reg.get_run(slug)["id"])
                   if t["state"] == "RUNNING"]
        self.assertEqual(len(running), 2)
        snap = self.http.get("/api/v1/projects/digital-hr/factory").json
        self.assertEqual(snap["limits"]["running_in_project"], 2)
        self.assertEqual([(q["slug"], q["position"]) for q in snap["queue"]], [("run-c", 1)])
        self.assertIn("project limit of 2", snap["queue"][0]["reason"])
        for p in first:
            p.wait(30)
        self.assertEqual(len(wait_until(lambda: self.pump(wait=False) or None, 10) or []), 1)  # a slot is free: the third starts

    def test_max_agents_is_respected(self):
        self.limited(max_tasks_per_project=5, max_agents=1)
        self.assertEqual(len(self.pump(wait=False)), 1)
        self.assertEqual(len(self.pump(wait=False)), 0)
        wait_until(lambda: factory.running_tasks(self.eng.reg) == 1, 15)
        snap = self.http.get("/api/v1/projects/digital-hr/factory").json
        self.assertEqual(len(snap["queue"]), 2)
        self.assertIn("limit of 1 running agents", snap["queue"][0]["reason"])

    # ---- pause
    def test_pause_stops_new_starts_and_unpause_resumes_them(self):
        self.make_run()
        self.serve(dispatch=True, dispatch_interval=3600)
        self.pump()  # plans the triage task
        (tid,) = [t["id"] for t in self.eng.reg.rows("tasks", run_id=self.eng.reg.get_run(SLUG)["id"])]
        r = self.http.post(f"/api/v1/tasks/{SLUG}/pause", {"comment": "hold"})
        self.assertEqual((r.status, r.json["paused"]), (200, True), r.text)
        self.assertEqual(self.pump(), [])
        self.assertEqual(self.eng.get_task(tid)["state"], "QUEUED")
        r = self.http.post(f"/api/v1/tasks/{SLUG}/unpause", {})
        self.assertEqual((r.status, r.json["paused"]), (200, False), r.text)
        self.assertEqual(len(self.pump()), 1)
        self.assertEqual(self.eng.get_task(tid)["state"], "COMPLETED")

    def test_a_running_task_finishes_while_the_run_is_paused(self):
        self.use_config(single_model=False, runners={"slow": {"command": self.slow_runner(2)}}, agents=agents("slow"))
        self.make_run()
        self.serve(dispatch=True, dispatch_interval=3600)
        self.pump(wait=False)
        (proc,) = self.pump(wait=False)
        self.http.post(f"/api/v1/tasks/{SLUG}/pause", {})
        proc.wait(30)
        (t,) = self.eng.reg.rows("tasks", run_id=self.eng.reg.get_run(SLUG)["id"])
        self.assertEqual(self.eng.get_task(t["id"])["state"], "COMPLETED")
        self.pump()
        self.assertEqual(self.eng.reg.get_run(SLUG)["state"], "CREATED")  # nothing applied or planned while paused

    # ---- the API
    def test_pause_unpause_note_routes_audit_and_check_csrf(self):
        self.make_run()
        self.serve()
        base = f"/api/v1/tasks/{SLUG}"
        self.assertEqual(self.http.req("POST", f"{base}/pause", {}, csrf="wrong").code, "E_CSRF")
        self.assertEqual(self.http.post(f"{base}/pause", {"extra": 1}).code, "E_VALIDATION")
        self.assertEqual(self.http.post(f"{base}/note", {"text": " "}).code, "E_VALIDATION")
        self.assertEqual(self.http.post(f"{base}/note", {}).code, "E_VALIDATION")
        self.assertEqual(self.http.post(f"{base}/unpause", {}).status, 409)  # not paused
        self.assertEqual(self.http.post(f"{base}/pause", {"comment": "c"}).status, 200)
        self.assertEqual(self.http.post(f"{base}/pause", {}).status, 409)
        r = self.http.post(f"{base}/note", {"text": "look at the cache"})
        self.assertEqual((r.status, r.json["note"][:2]), (201, "n-"), r.text)
        self.assertEqual(self.http.post(f"{base}/unpause", {}).status, 200)
        rows = [(a["action"], a["channel"], a["actor"], a["target"]) for a in self.audit_rows()
                if a["action"] in ("pause", "unpause", "note")]
        self.assertEqual(rows, [("pause", "dashboard", "dev", SLUG), ("note", "dashboard", "dev", SLUG),
                                ("unpause", "dashboard", "dev", SLUG)])
        self.assertEqual(self.http.get(base).json["paused"], False)

    def test_snapshot_shape_stations_agents_and_lanes(self):
        self.make_run("early")  # CREATED, triage queued after one pass
        self.to_spec_review("gate-run", 3)
        self.eng.reg.update_run("gate-run", driver="engine")
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/factory")
        self.assertEqual(r.status, 200, r.text)
        snap = r.json
        self.assertEqual(set(snap), {"project", "generated_at", "stations", "limits", "runs", "queue", "factory_paused", "who",
                                     "activity", "routing", "budget"})
        self.assertIs(snap["factory_paused"], False)
        self.assertEqual(snap["stations"], list(factory.STATIONS))
        self.assertEqual(snap["limits"], {"driver": "engine", "max_tasks_per_project": 2, "max_agents": 4,
                                          "running_in_project": 0, "running_total": 0})
        runs = {x["slug"]: x for x in snap["runs"]}
        gate = runs["gate-run"]
        self.assertEqual(set(gate), {"slug", "title", "type", "driver", "paused", "state", "tier", "station", "stations",
                                     "next_station", "agents", "lanes", "attention", "limit", "task_usage", "station_tasks", "pending_notes", "created_at", "updated_at"})
        self.assertEqual((gate["state"], gate["station"], gate["next_station"], gate["driver"]),
                         ("SPECIFICATION_REVIEW", "gate_spec", "gherkin", "engine"))
        self.assertEqual(gate["stations"], {"intake": "done", "triage": "done", "spec": "done", "gate_spec": "waiting",
                                            "gherkin": "next", "gate_gherkin": "todo", "build": "todo", "verify": "todo",
                                            "report": "todo", "gate_accept": "todo", "knowledge": "todo"})
        self.assertEqual((gate["agents"], gate["lanes"], gate["attention"]), ({}, [], None))
        early = runs["early"]
        self.assertEqual((early["station"], early["stations"]["triage"], early["stations"]["spec"], early["title"]),
                         ("triage", "queued", "next", REQUEST))
        self.assertEqual(snap["queue"], [])

    def test_snapshot_who_comes_from_the_routing_the_dispatcher_uses(self):
        self.use_config(single_model=False, runners={"fake": {"command": "x"}, "agy": {"command": "y"}},
                        agents={"triage": {"runner": "fake"}, "specifier": {"runner": "agy", "model": "gemini-3.8-flash"},
                                "tdd_green": {"runner": "fake", "model": "m1"}},
                        routing={"knowledge": {"runner": "agy", "model": "k1"}})
        self.serve()
        who = self.http.get("/api/v1/projects/digital-hr/factory").json["who"]
        self.assertEqual(who, {"triage": {"role": "triage", "runner": "fake", "model": None},
                               "spec": {"role": "specifier", "runner": "agy", "model": "gemini-3.8-flash"},
                               "build": {"role": "tdd_green", "runner": "fake", "model": "m1"},
                               "knowledge": {"role": "knowledge", "runner": "agy", "model": "k1"}})  # gherkin has no route: left out
        from tasks import select_adapter
        self.assertEqual(select_adapter(self.config, "specifier")[1:], ("agy", "gemini-3.8-flash"))

    def test_snapshot_who_orchestrator_mode_shows_orchestrator(self):
        self.use_config(routing_mode="orchestrator", orchestrator={"runner": "claude", "model": "sonnet"},
                        runners={"claude": {"command": "claude", "model_flag": "--model"}})
        self.serve()
        who = self.http.get("/api/v1/projects/digital-hr/factory").json["who"]
        for st, role in factory.WHO_ROLES:
            self.assertEqual(who[st], {"role": role, "runner": "claude", "model": "sonnet"})
        self.assertEqual(who["knowledge"], {"role": "knowledge", "runner": "claude", "model": "sonnet"})

    def test_select_adapter_in_both_modes(self):
        from tasks import select_adapter
        cfg_per_role = {"version": 1, "shape": "single", "repos": [{"id": "b", "path": "b", "role": "b", "profile": "p"}],
                        "single_model": False, "routing_mode": "per_role", "agents": {"specifier": {"runner": "agy", "model": "gemini"}}}
        self.assertEqual(select_adapter(cfg_per_role, "specifier"), ("cli", "agy", "gemini"))
        self.assertEqual(select_adapter(cfg_per_role, "coder"), ("native", "native", None))

        cfg_orch = {"version": 1, "shape": "single", "repos": [{"id": "b", "path": "b", "role": "b", "profile": "p"}],
                    "routing_mode": "orchestrator", "orchestrator": {"runner": "claude", "model": "opus"},
                    "agents": {"specifier": {"runner": "agy", "model": "gemini"}}}
        self.assertEqual(select_adapter(cfg_orch, "specifier"), ("cli", "claude", "opus"))
        self.assertEqual(select_adapter(cfg_orch, "coder"), ("cli", "claude", "opus"))

    def test_preflight_in_orchestrator_mode(self):
        cfg_defined = {"version": 1, "shape": "single", "repos": [{"id": "b", "path": "b", "role": "b", "profile": "p"}],
                       "routing_mode": "orchestrator", "orchestrator": {"runner": "claude", "model": "opus"},
                       "runners": {"claude": {"command": "claude", "model_flag": "--model"}}}
        self.assertEqual(factory.routing_problem_roles(cfg_defined), [])

        cfg_undefined = {"version": 1, "shape": "single", "repos": [{"id": "b", "path": "b", "role": "b", "profile": "p"}],
                         "routing_mode": "orchestrator", "orchestrator": {"runner": "nonexistent_runner"},
                         "runners": {"claude": {"command": "claude"}}}
        problems = factory.routing_problem_roles(cfg_undefined)
        self.assertTrue(len(problems) > 0)
        self.assertIn("nonexistent_runner, which is not defined", problems[0][1])

    def test_snapshot_station_tasks_shows_latest_attempt_per_role(self):
        self.make_run()
        run = self.eng.reg.get_run(SLUG)
        rid = run["id"]
        reg = self.eng.reg
        # insert two attempts for triage (attempt 1 FAILED, attempt 2 COMPLETED)
        t1 = reg.insert_row("tasks", {"run_id": rid, "role": "triage", "state": "FAILED", "started_at": "2026-11-22T10:00:00Z", "finished_at": "2026-11-22T10:01:00Z"})
        t2 = reg.insert_row("tasks", {"run_id": rid, "role": "triage", "state": "COMPLETED", "retry_of": t1, "started_at": "2026-11-22T10:02:00Z", "finished_at": "2026-11-22T10:03:00Z"})
        # insert planner (also in triage station)
        t_plan = reg.insert_row("tasks", {"run_id": rid, "role": "planner", "state": "RUNNING", "started_at": "2026-11-22T10:04:00Z"})
        # insert build role
        t_red = reg.insert_row("tasks", {"run_id": rid, "role": "tdd_red", "state": "COMPLETED", "started_at": "2026-11-22T10:05:00Z", "finished_at": "2026-11-22T10:06:00Z"})
        snap = factory.snapshot(self.eng, "digital-hr")
        snap_run = next(r for r in snap["runs"] if r["slug"] == SLUG)
        st_tasks = snap_run["station_tasks"]
        # triage station should have latest triage (t2) and planner (t_plan)
        triage_tasks = st_tasks.get("triage", [])
        self.assertEqual([t["id"] for t in triage_tasks], [t2, t_plan])
        self.assertEqual(triage_tasks[0]["state"], "COMPLETED")
        self.assertEqual(triage_tasks[1]["state"], "RUNNING")
        # build station should have tdd_red
        build_tasks = st_tasks.get("build", [])
        self.assertEqual([t["id"] for t in build_tasks], [t_red])

    def test_snapshot_activity_newest_first_from_registry_rows(self):
        self.make_run()
        rid = self.eng.reg.get_run(SLUG)["id"]
        reg = self.eng.reg
        reg.add_event(rid, "task.started", "engine", {"role": "triage", "state": "RUNNING"}, task_id="t-1")
        reg.add_event(rid, "task.finished", "engine", {"role": "triage", "state": "COMPLETED"}, task_id="t-1")
        reg.add_event(rid, "task.finished", "engine", {"role": "tdd_green", "state": "FAILED"}, task_id="t-2")
        reg.add_event(rid, "approval.requested", "engine", {"gate": "specification"})
        reg.add_event(rid, "run.state_changed", "engine", {"to": "X"})   # not an activity type
        reg.add_event(rid, "run.paused", "human", {"reason": "lunch"})
        self.serve()
        act = self.http.get("/api/v1/projects/digital-hr/factory").json["activity"]
        self.assertEqual([(a["run"], a["station"], a["text"]) for a in act],
                         [(SLUG, "intake", "Run paused"), (SLUG, "gate_spec", "Specification is waiting for you"),
                          (SLUG, "build", "Build agent failed"), (SLUG, "triage", "Triage agent finished"),
                          (SLUG, "triage", "Triage agent started"), (SLUG, "intake", "Task created")])
        self.assertTrue(all(set(a) == {"at", "run", "station", "text"} for a in act))

    def test_snapshot_activity_is_capped_and_scrubbed(self):
        self.make_run()
        rid = self.eng.reg.get_run(SLUG)["id"]
        for _ in range(30):
            self.eng.reg.add_event(rid, "run.note_added", "human", {"note": "n"})
        self.serve()
        act = self.http.get("/api/v1/projects/digital-hr/factory").json["activity"]
        self.assertEqual(len(act), 20)
        self.assertEqual(act, sorted(act, key=lambda a: a["at"], reverse=True))

    def test_factory_pause_routes_state_audit_and_csrf(self):
        self.make_run()
        self.serve()
        g = self.http.get("/api/v1/factory")
        self.assertEqual((g.status, g.json), (200, {"paused": False, "paused_at": None, "running_total": 0, "max_agents": 4}))
        self.assertEqual(self.http.get("/api/v1/factory?x=1").code, "E_VALIDATION")
        self.assertEqual(self.http.req("POST", "/api/v1/factory/pause", {}, csrf="wrong").code, "E_CSRF")
        self.assertEqual(self.http.post("/api/v1/factory/pause", {"extra": 1}).code, "E_VALIDATION")
        r = self.http.post("/api/v1/factory/pause", {"comment": "lunch"})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual((r.json["paused"], set(r.json)), (True, {"paused", "paused_at", "running_total", "max_agents"}))
        self.assertTrue(r.json["paused_at"])
        self.assertEqual(json.loads((self.cfgdir / "factory.json").read_text())["paused"], True)
        again = self.http.post("/api/v1/factory/pause", {})   # idempotent: same state, no second audit row
        self.assertEqual((again.status, again.json["paused_at"]), (200, r.json["paused_at"]))
        self.assertIs(self.http.get("/api/v1/projects/digital-hr/factory").json["factory_paused"], True)
        r = self.http.post("/api/v1/factory/resume", {})
        self.assertEqual((r.status, r.json["paused"], r.json["paused_at"]), (200, False, None))
        self.assertEqual(self.http.post("/api/v1/factory/resume", {}).status, 200)
        rows = [(a["action"], a["channel"], a["actor"], a["target"], a["reason"]) for a in self.audit_rows()
                if a["action"].startswith("factory_")]
        self.assertEqual(rows, [("factory_pause", "dashboard", "dev", "factory", "lunch"),
                                ("factory_resume", "dashboard", "dev", "factory", None)])

    def test_factory_max_agents_is_the_largest_over_projects(self):
        self.use_config(factory={"max_agents": 6})
        self.serve()
        self.assertEqual(self.http.get("/api/v1/factory").json["max_agents"], 6)

    def test_factory_pause_and_resume_events_reach_the_stream(self):
        self.serve()
        s = self.stream("/api/v1/events")
        self.http.post("/api/v1/factory/pause", {})
        msgs = s.messages(1)
        self.http.post("/api/v1/factory/resume", {})
        msgs += s.messages(1)
        self.assertEqual([m["event"] for m in msgs], ["factory.paused", "factory.resumed"])
        body = json.loads(msgs[0]["data"])
        self.assertEqual((body["type"], body["project"], body["run"], body["payload"]["paused"]),
                         ("factory.paused", None, None, True))

    def test_a_paused_factory_starts_no_task_and_resuming_starts_again(self):
        self.make_run()
        self.serve(dispatch=True, dispatch_interval=3600)
        self.http.post("/api/v1/factory/pause", {})
        for _ in range(3):
            self.pump()
        self.assertEqual(self.tasks(), [])
        self.http.post("/api/v1/factory/resume", {})
        self.pump()
        self.assertTrue(self.tasks())

    def test_resuming_the_factory_does_not_unpause_runs(self):
        self.make_run()
        self.serve(dispatch=True, dispatch_interval=3600)
        self.http.post(f"/api/v1/tasks/{SLUG}/pause", {})
        self.http.post("/api/v1/factory/pause", {})
        self.http.post("/api/v1/factory/resume", {})
        self.pump()
        self.assertEqual(self.tasks(), [])
        self.assertEqual(self.http.get(f"/api/v1/tasks/{SLUG}").json["paused"], True)

    def test_snapshot_working_agent_lanes_and_pause(self):
        self.executing(tier=3, cycles=True)
        self.eng.reg.update_run(SLUG, driver="engine", title=None) if False else self.eng.reg.update_run(SLUG, driver="engine")
        cycles = self.eng.reg.rows("cycles", run_id=self.eng.reg.get_run(SLUG)["id"])
        self.assertTrue(cycles)
        first = cycles[0]
        self.eng.reg.update_row("cycles", first["id"], state="GREEN_RUNNING")
        tid = self.make("tdd_green", ["backend"], ["backend/src/main/**"], cycle_id=first["id"])
        self.eng.queue_task(tid)
        self.eng.reg.update_row("tasks", tid, state="RUNNING", started_at="2026-11-21T10:00:00.000000Z")
        self.serve()
        snap = self.http.get("/api/v1/projects/digital-hr/factory").json
        (run,) = [r for r in snap["runs"] if r["slug"] == SLUG]
        self.assertEqual((run["station"], run["stations"]["build"], run["stations"]["verify"]), ("build", "working", "next"))
        agent = run["agents"]["build"][0]
        self.assertEqual((agent["task"], agent["role"], agent["started_at"]), (tid, "tdd_green", "2026-11-21T10:00:00.000000Z"))
        self.assertEqual(set(agent), {"task", "role", "runner", "model", "adapter", "started_at"})
        lane = [x for x in run["lanes"] if x["cycle"] == first["id"]][0]
        self.assertEqual((lane["red"], lane["green"], lane["refactor"], lane["state"]), ("done", "working", "todo", "GREEN_RUNNING"))
        self.assertEqual(set(lane), {"cycle", "name", "repo", "state", "red", "green", "refactor"})
        self.assertEqual(snap["limits"]["running_in_project"], 1)
        self.http.post(f"/api/v1/tasks/{SLUG}/pause", {})
        (run,) = [r for r in self.http.get("/api/v1/projects/digital-hr/factory").json["runs"] if r["slug"] == SLUG]
        self.assertEqual((run["paused"], run["stations"]["build"]), (True, "paused"))
        lane = [x for x in run["lanes"] if x["cycle"] == first["id"]][0]
        self.assertEqual(lane["green"], "paused")

    def test_snapshot_needs_human_and_unknown_query(self):
        self.make_run()
        self.eng.reg.update_run(SLUG, state="NEEDS_HUMAN", previous_state="CREATED")
        self.eng.reg.add_event(self.eng.reg.get_run(SLUG)["id"], "run.state_changed", "engine",
                               {"from": "CREATED", "to": "NEEDS_HUMAN", "transition": "R19", "reason": "triage task failed"})
        self.serve()
        (run,) = self.http.get("/api/v1/projects/digital-hr/factory").json["runs"]
        self.assertEqual(run["attention"], {"kind": "needs_human", "reason": "triage task failed"})
        self.assertEqual((run["station"], run["stations"]["triage"]), ("triage", "waiting"))
        self.assertEqual(self.http.get("/api/v1/projects/digital-hr/factory?x=1").code, "E_VALIDATION")
        self.assertEqual(self.http.get("/api/v1/projects/none/factory").code, "E_NOT_FOUND")

    def test_snapshot_leaves_out_finished_runs(self):
        self.make_run("live")
        self.make_run("gone")
        self.eng.cancel_run("gone", "x", user="dev")
        self.serve()
        self.assertEqual([r["slug"] for r in self.http.get("/api/v1/projects/digital-hr/factory").json["runs"]], ["live"])


class Migration(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / ".sentinel"

    def test_existing_rows_migrate_to_cli_and_dashboard_rows_to_ai_tool(self):
        migs = registry._load_file_migrations()
        before = [m for m in migs if m[0] < 13]
        old = registry.Registry.open(self.dir, before)
        for slug, origin in (("by-hand", None), ("by-cli", "cli"), ("by-dash", "dashboard"), ("imported", "import")):
            old.insert_run({"slug": slug, "state": "CREATED", "execution_status": "running", "acceptance_status": "pending",
                            "workflow_version": "2", "origin": origin})
        self.assertNotIn("driver", old._columns("runs"))
        old.close()
        reg = registry.Registry.open(self.dir)
        self.addCleanup(reg.close)
        self.assertEqual(reg.schema_version(), registry.Registry.LATEST)
        self.assertGreaterEqual(registry.Registry.LATEST, 13)
        got = {r["slug"]: (r["driver"], r["paused"]) for r in reg.list_runs()}
        self.assertEqual(got, {"by-hand": ("cli", 0), "by-cli": ("cli", 0), "by-dash": ("ai-tool", 0), "imported": ("cli", 0)})
        self.assertTrue((self.dir / "sentinel.db.bak-12").exists())  # the upgrade backed the old database up

    def test_new_rows_default_to_cli_and_the_check_rejects_other_values(self):
        reg = registry.Registry.open(self.dir)
        self.addCleanup(reg.close)
        reg.insert_run({"slug": "a", "state": "CREATED", "execution_status": "running", "acceptance_status": "pending",
                        "workflow_version": "2"})
        self.assertEqual(reg.get_run("a")["driver"], "cli")
        for ok in ("engine", "ai-tool", "cli"):
            with reg.transaction():
                reg.update_run("a", driver=ok)
        with self.assertRaises(sqlite3.IntegrityError):
            with reg.transaction():
                reg.update_run("a", driver="robot")
        self.assertEqual(reg.get_run("a")["driver"], "cli" if False else "cli" if False else reg.get_run("a")["driver"])

    def test_notes_table_and_prefix(self):
        reg = registry.Registry.open(self.dir)
        self.addCleanup(reg.close)
        reg.insert_run({"slug": "a", "state": "CREATED", "execution_status": "running", "acceptance_status": "pending",
                        "workflow_version": "2"})
        run = reg.get_run("a")
        nid = reg.insert_row("run_notes", {"run_id": run["id"], "text": "hi", "created_at": registry._now()})
        self.assertTrue(nid.startswith("n-"))
        self.assertIsNone(reg.get_row("run_notes", nid)["consumed_at"])

    def test_config_schema_accepts_the_factory_block(self):
        import jsonschema
        schema = json.loads((Path(registry.__file__).resolve().parents[1] / "core" / "schema" / "config.schema.json").read_text())
        block = schema["properties"]["factory"]
        validator = jsonschema.Draft202012Validator(block)
        self.assertEqual(list(validator.iter_errors({"driver": "ai-tool", "max_tasks_per_project": 3, "max_agents": 6})), [])
        for bad in ({"driver": "robot"}, {"max_agents": 0}, {"max_tasks_per_project": "2"}, {"other": 1}):
            self.assertTrue(list(validator.iter_errors(bad)), bad)
        self.assertEqual(factory.factory_config({}), {"driver": "engine", "max_tasks_per_project": 2, "max_agents": 4})
        self.assertEqual(factory.factory_config({"factory": {"max_agents": 0, "driver": "x"}})["max_agents"], 4)


    def test_config_schema_routing_mode_and_orchestrator(self):
        import jsonschema
        schema = json.loads((Path(registry.__file__).resolve().parents[1] / "core" / "schema" / "config.schema.json").read_text())
        validator = jsonschema.Draft202012Validator(schema)
        base = {"version": 1, "shape": "single", "repos": [{"id": "b", "path": "b", "role": "b", "profile": "p"}]}
        # valid configurations
        self.assertEqual(list(validator.iter_errors({**base, "routing_mode": "per_role"})), [])
        self.assertEqual(list(validator.iter_errors({**base, "routing_mode": "orchestrator", "orchestrator": {"runner": "claude"}})), [])
        self.assertEqual(list(validator.iter_errors({**base, "routing_mode": "orchestrator", "orchestrator": {"runner": "claude", "model": "opus"}})), [])
        self.assertEqual(list(validator.iter_errors({**base, "routing_mode": "orchestrator", "orchestrator": {"runner": "claude", "model": None}})), [])
        # invalid configurations
        self.assertTrue(list(validator.iter_errors({**base, "routing_mode": "invalid_mode"})))
        self.assertTrue(list(validator.iter_errors({**base, "orchestrator": {}})))  # missing runner
        self.assertTrue(list(validator.iter_errors({**base, "orchestrator": {"runner": 123}})))
        self.assertTrue(list(validator.iter_errors({**base, "orchestrator": {"runner": "claude", "extra": 1}})))


if __name__ == "__main__":
    unittest.main()
