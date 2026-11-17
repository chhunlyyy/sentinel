"""Shared fixtures for Phase J tests (TDD-09): QA scenarios as Red evidence under no_permanent_frontend_tests."""
import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from pb_helpers import SLUG  # noqa: E402
from pd_helpers import AGENT, PDX, feature, default_features  # noqa: E402

DRIVER = str(Path(__file__).resolve().parent / "fixtures" / "qa" / "fake_qa_driver.py")
LISTENER = ("import socket,time;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
            "s.bind(('127.0.0.1',4173));s.listen(5);time.sleep(600)")
FORM_LABEL = "Request form"
IDS = ("AC-4", "AC-5")
ROLES = ("tdd_red", "qa_red", "tdd_green", "tdd_refactor")
RULE = "no_permanent_frontend_tests"


def features():
    files = default_features(True, True)
    files["request_form.feature"] = feature(
        "@REQ-2 @repo-frontend", [("", "Request form", [("AC-4", "Form shows the balance"), ("AC-5", "Form rejects too many days")])],
        title="Request form")
    return files


class PJ(PDX):
    FORM = FORM_LABEL

    def setUp(self):
        super().setUp()
        self.plan_path = self.ws / "qa_plan.json"
        p = mock.patch.dict(os.environ, {"FAKE_QA_PLAN": str(self.plan_path)})
        p.start()
        self.addCleanup(p.stop)

    def qa_cfg(self, **over):
        cfg = {"driver": "playwright", "ports": [4173], "start_commands": {"frontend": f'{sys.executable} -c "{LISTENER}"', "backend": "true"},
               "scenario_run": f"{sys.executable} {DRIVER} {{scripts}} {{report}} {{cycle}}", "scenario_report": "qa-report.xml"}
        cfg.update(over)
        return {k: v for k, v in cfg.items() if v is not None}

    def plan(self, **plan):
        """Write the fake driver plan and reset its run counter and log."""
        self.plan_path.write_text(json.dumps(plan))
        for suffix in (".count", ".log"):
            Path(str(self.plan_path) + suffix).unlink(missing_ok=True)

    def driver_log(self):
        p = Path(str(self.plan_path) + ".log")
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def driver_runs(self):
        return len([e for e in self.driver_log() if e["event"] == "start"])

    def boot_qa(self, rule=True, execute=True, qa=None, roles=("backend", "frontend"), tdd=None, policies=None, rules=None, **kw):
        """A run on backend and frontend with the QA driver configured. execute=False stops at GHERKIN_APPROVED."""
        extra = {"qa": self.qa_cfg(**(qa or {})) if qa is not False else None,
                 "rules": {RULE: rule, **(rules or {})},
                 "policies": {"test_timeout_seconds": 5, **(policies or {})},
                 "runners": {"fake": {"command": self.script("fake", AGENT)}},
                 "agents": {r: {"runner": "fake"} for r in ROLES}}
        extra = {k: v for k, v in extra.items() if v is not None}
        self.plan()
        kw.setdefault("features", features())
        kw.setdefault("repos", ("backend", "frontend"))
        kw.setdefault("tool", {"full": {"exit": 0, "report": [], "extra_passed": 2},
                               "targeted": {"exit": 1, "report": [["RemainingBalanceTest", "employeeSeesRemainingDays", "failure"],
                                                                  ["RemainingBalanceTest", "balanceNeverBelowZero", "failure"]]}})
        self.modes = dict(kw["tool"])
        fn = self.boot_exec if execute else self.boot_pd
        return fn(agent_body=AGENT, tdd={**self.TDD, **(tdd or {})}, **extra, **kw)

    # ---- helpers on the QA cycle
    def form(self, slug=SLUG):
        return self.cycle(self.FORM, slug)

    def qa_tasks(self, role="qa_red", slug=SLUG):
        return self.tdd_tasks(role, self.FORM, slug)

    def qid(self, role="qa_red"):
        return self.qa_tasks(role)[-1]["id"]

    def run_qa(self, role="qa_red"):
        self.eng.bookkeep(SLUG)
        return self.eng.run_task(self.qid(role))

    def scripts_dir(self, cycle=None):
        cycle = cycle or self.form()
        return self.ws / ".sentinel" / "cache" / "qa" / "tests" / "current" / SLUG / cycle["id"]

    def script_rel(self, sid, cycle=None):
        return f".sentinel/cache/qa/tests/current/{SLUG}/{(cycle or self.form())['id']}/{sid}.spec"

    def exc_events(self, kind, slug=SLUG):
        return self.events(f"tdd.exception_{kind}", slug)

    def to_qa_red_verified(self):
        self.boot_qa()
        self.plan()
        self.run_qa()
        assert self.form()["state"] == "RED_VERIFIED", self.form()

    def to_qa_accepted(self):
        self.to_qa_red_verified()
        self.plan(default={"*": "pass"})
        self.run_qa("tdd_green")
        self.run_qa("tdd_refactor")
        assert self.form()["state"] == "CYCLE_ACCEPTED", self.form()


def drive_qa(test, limit=60):
    """The orchestrator loop for a mixed run: backend phases use the fake test tool, frontend phases the fake QA driver
    (red fails every scenario, green and refactor pass)."""
    from pd_helpers import TESTS, report, all_pass
    steps = []
    for _ in range(limit):
        step = test.eng.next_step(SLUG)
        steps.append(step)
        if step["kind"] != "task":
            break
        task = test.task(step["task"])
        cyc = test.eng.reg.get_row("cycles", task["cycle_id"]) if task["cycle_id"] else None
        if task["role"] == "qa_red":
            test.plan()
        elif cyc and cyc["red_method"] == "qa_scenario":
            test.plan(default={"*": "pass"})
        elif task["role"] == "tdd_red":
            label = next(k for k in TESTS if k in cyc["behavior"])
            test.targeted(report(label, "failure") + [x for x in all_pass() if x[:2] not in [c[:2] for c in report(label, "x")]])
        else:
            test.targeted(all_pass())
        test.eng.run_task(step["task"])
    return steps


def delete_events(test, type):
    """Test-only tamper: the events table refuses deletes, so its trigger is dropped first."""
    test.sql("DROP TRIGGER IF EXISTS events_no_delete")
    test.sql("DELETE FROM events WHERE type=?", (type,))
