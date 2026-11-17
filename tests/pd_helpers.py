"""Shared fixtures for Phase D tests: repos with the fake test tool, approved Gherkin, planned cycles, fake agents."""
import contextlib
import json
import sys
import textwrap
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from pb_helpers import SLUG, spec_text  # noqa: E402
from pc_helpers import BASE_CONFIG, PCX  # noqa: E402

REPORT = "build/test-results/test/*.xml"
PATTERNS = {"compile": ["error: cannot find symbol"], "environment": ["Connection refused"],
            "missing_dependency": ["Could not resolve"]}
SCENARIO_REF = '@Scenario\\("([^"]+)"\\)'
TEST_FILE = "backend/src/test/java/leave/RemainingBalanceTest.java"
REMAINING = ["features/balance.feature :: Employee sees remaining days", "features/balance.feature :: Balance never goes below zero"]
CARRY = "features/balance.feature :: Unused days carry over"
FORM = "features/request_form.feature :: Form shows the balance"
T1, T2 = "RemainingBalanceTest.employeeSeesRemainingDays", "RemainingBalanceTest.balanceNeverBelowZero"

FAKE_TOOL = """#!{py}
import json, os, pathlib, sys, time
here = pathlib.Path(__file__).resolve().parent
cfg = json.loads((here / "faketest.json").read_text())
mode, args = sys.argv[1], sys.argv[2:]
with open(here / "faketest.log", "a") as f:
    f.write(json.dumps({{"mode": mode, "args": args, "repo": os.path.basename(os.getcwd())}}) + "\\n")
sc = cfg.get(os.path.basename(os.getcwd()) + ":" + mode) or cfg.get(mode) or cfg.get("default") or {{}}
if sc.get("sleep"):
    time.sleep(sc["sleep"])
if sc.get("stdout"):
    print(sc["stdout"], flush=True)
if sc.get("stderr"):
    print(sc["stderr"], file=sys.stderr, flush=True)
cases = sc.get("report")
if cases is not None:
    given = [a[len("--report-dir="):] for a in args if a.startswith("--report-dir=")]
    out = pathlib.Path(given[0]) if given else pathlib.Path("build/test-results/test")
    out.mkdir(parents=True, exist_ok=True)
    body = []
    for i in range(sc.get("extra_passed", 0)):
        body.append('<testcase classname="leave.OtherTest" name="t%d"/>' % i)
    for klass, name, status in cases:
        inner = {{"pass": "", "failure": '<failure message="expected 1 got 2">AssertionError</failure>',
                 "error": '<error message="boom">AttributeError</error>', "skipped": "<skipped/>"}}[status]
        body.append('<testcase classname="leave.%s" name="%s">%s</testcase>' % (klass, name, inner))
    (out / "TEST-fake.xml").write_text('<testsuite name="fake">' + "".join(body) + "</testsuite>")
sys.exit(sc.get("exit", 0))
"""


def feature(tags, rules, scenarios_before=(), title="Leave balance"):
    """rules: [(rule tags, rule name, [(ac, scenario name), ...])] ; scenarios_before: [(ac, name)] before any Rule."""
    lines = [tags, f"Feature: {title}", ""]
    for ac, name in scenarios_before:
        lines += [f"  @{ac} @unit @P1", f"  Scenario: {name}", "    Given x", "    When y", "    Then z", ""]
    for rtags, rname, scenarios in rules:
        if rtags:
            lines.append(f"  {rtags}")
        lines += [f"  Rule: {rname}", ""]
        for ac, name in scenarios:
            lines += [f"    @{ac} @unit @P1", f"    Scenario: {name}", "      Given x", "      When y", "      Then z", ""]
    return "\n".join(lines) + "\n"


def default_features(backend_tag=True, form_tag=True):
    bal = feature("@REQ-1" + (" @repo-backend" if backend_tag else ""),
                  [("", "Remaining balance", [("AC-1", "Employee sees remaining days"), ("AC-2", "Balance never goes below zero")]),
                   ("", "Carry-over", [("AC-3", "Unused days carry over")])])
    form = feature("@REQ-2" + (" @repo-frontend" if form_tag else ""), [], [("AC-4", "Form shows the balance")], "Request form")
    return {"balance.feature": bal, "request_form.feature": form}


SPEC_ACS = ("AC-1 (REQ-1): a", "AC-2 (REQ-1): b", "AC-3 (REQ-1): c", "AC-4 (REQ-2): d")
RED_OK = f"""
write({TEST_FILE!r}, '''class RemainingBalanceTest {{
  @Scenario("{REMAINING[0]}")
  void employeeSeesRemainingDays() {{}}
  @Scenario("{REMAINING[1]}")
  void balanceNeverBelowZero() {{}}
}}
''')
write_result()
"""


def repo_entry(rid, py, tool, **over):
    return {"id": rid, "path": rid, "role": rid, "profile": "generic", "test_globs": ["src/test/**"],
            "production_globs": ["src/main/**"], "commands": {"test": f"{py} {tool} full"},
            "targeted_test": f"{py} {tool} targeted {{tests}}", "test_report": {"kind": "junit-xml", "path": REPORT},
            "failure_patterns": PATTERNS, "scenario_ref": SCENARIO_REF, **over}


class PD(PCX):
    """A workspace with repos backend and frontend that use the fake test tool."""

    def setUp(self):
        super().setUp()
        for rid in ("backend", "frontend"):
            (self.ws / rid / ".gitignore").write_text("build/\n")
            from pc_helpers import git
            git(self.ws / rid, "add", "-A")
            git(self.ws / rid, "commit", "-q", "-m", "ignore build")

    @contextlib.contextmanager
    def subTest(self, *args, **params):
        """A failing subtest still resets the workspace, so the next one does not boot on its leftovers."""
        with super().subTest(*args, **params):
            try:
                yield
            except BaseException:
                try:
                    self.reset_ws()
                except Exception:
                    pass
                raise

    def reset_ws(self):
        """Fresh registry and clean repos, same config (for subtests that boot several runs)."""
        import shutil
        from engine import Engine
        from pc_helpers import git
        self.eng.close()
        shutil.rmtree(self.ws / ".sentinel")
        self.eng = Engine(self.ws / ".sentinel", self.ws, self.config, release_lock=self.released.append)
        self.addCleanup(self.eng.close)
        for rid in ("backend", "frontend"):
            git(self.ws / rid, "checkout", "-q", "--", ".")
            git(self.ws / rid, "clean", "-fdq")
        (self.ws / self.BIN / "faketest.log").unlink(missing_ok=True)
        shutil.rmtree(self.ws / ".claude", ignore_errors=True)
        (self.ws / "AGENTS.md").unlink(missing_ok=True)

    def fake_tool(self, **modes):
        """Write the fake test tool and its scenario file; modes: {"full": {...}, "targeted": {...}, "default": {...}}."""
        path = self.ws / self.BIN / "faketest"
        path.write_text(FAKE_TOOL.format(py=sys.executable))
        path.chmod(0o755)
        self.tool_modes(**modes)
        return str(path)

    def tool_modes(self, **modes):
        (self.ws / self.BIN / "faketest.json").write_text(json.dumps(modes))

    def tool_log(self):
        p = self.ws / self.BIN / "faketest.log"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def boot_pd(self, features=None, repos=("backend",), tier=3, agent_body=RED_OK, tdd=None, limits=None, typ="feature",
                repo_over=None, tool=None, **cfg):
        tool = self.fake_tool(**(tool or {"full": {"exit": 0, "report": [], "extra_passed": 2},
                                       "targeted": {"exit": 1, "report": [["RemainingBalanceTest", "employeeSeesRemainingDays", "failure"],
                                                                         ["RemainingBalanceTest", "balanceNeverBelowZero", "failure"]]}}))
        entries = [repo_entry(r, sys.executable, tool, **(repo_over or {})) for r in repos]
        extra = {"single_model": False, "repos": entries,
                 "runners": {"fake": {"command": self.script("fake", agent_body)}},
                 "agents": {r: {"runner": "fake"} for r in ("tdd_red", "tdd_green", "tdd_refactor")}}
        if tdd:
            extra["tdd"] = tdd
        if limits:
            extra["limits"] = limits
        extra.update(cfg)
        self.use_config(**extra)
        slug = SLUG
        self.mk(slug, "PLANNED", tier, typ)
        # run repos: every repo of the config
        for rid in repos:
            if rid != "backend":
                self.eng.reg.add_run_repo(self.run_row(slug)["id"], rid, "abc")
        import re
        files = features or default_features(len(repos) > 1, len(repos) > 1)
        ids = sorted({a for t in files.values() for a in re.findall(r"@(AC-\d+)", t)}, key=lambda a: int(a[3:]))
        self.write_spec(spec_text(slug, tier=tier, acs=tuple(f"{a} ({'REQ-2' if a in ('AC-4', 'AC-5') else 'REQ-1'}): x" for a in ids), typ="feature"))
        assert self.submit("specifier", slug)["accepted"]
        self.approve("spec", slug)
        self.write_features(files, slug=slug)
        res = self.submit("test_designer", slug)
        assert res["accepted"], res
        self.approve("gherkin", slug)
        return slug

    def boot_exec(self, **kw):
        slug = self.boot_pd(**kw)
        self.eng.advance(slug)
        assert self.state(slug) == "EXECUTING", self.state(slug)
        return slug

    # ---- readers
    def cycles(self, slug=SLUG):
        return self.eng.reg.rows("cycles", run_id=self.run_row(slug)["id"])

    def cycle(self, label, slug=SLUG):
        """Cycle by a part of its behavior name ('Remaining', 'Carry', 'request_form')."""
        found = [c for c in self.cycles(slug) if label in c["behavior"]]
        assert found, (label, [c["behavior"] for c in self.cycles(slug)])
        return found[-1]

    def cstate(self, label, slug=SLUG):
        return self.cycle(label, slug)["state"]

    def tdd_tasks(self, role, label=None, slug=SLUG):
        rid = self.run_row(slug)["id"]
        cid = self.cycle(label, slug)["id"] if label else None
        return [t for t in self.eng.reg.rows("tasks", run_id=rid, role=role) if cid in (None, t["cycle_id"])]

    def evidence(self, kind=None, slug=SLUG, label=None):
        rid = self.run_row(slug)["id"]
        cid = self.cycle(label, slug)["id"] if label else None
        return [e for e in self.eng.reg.rows("evidence", run_id=rid)
                if kind in (None, e["kind"]) and cid in (None, e["cycle_id"])]

    def cycle_events(self, label=None, slug=SLUG):
        evs = [e for e in self.events("cycle.state_changed", slug)]
        if label:
            cid = self.cycle(label, slug)["id"]
            evs = [e for e in evs if e["payload"]["cycle"] == cid]
        return evs

    def moves(self, label, slug=SLUG):
        evs = self.cycle_events(label, slug)
        return ([evs[0]["payload"]["from"]] if evs else []) + [e["payload"]["to"] for e in evs]

    def links(self, from_kind=None, to_kind=None, slug=SLUG):
        rid = self.run_row(slug)["id"]
        return [r for r in self.eng.reg.rows("trace_links", run_id=rid)
                if from_kind in (None, r["from_kind"]) and to_kind in (None, r["to_kind"])]

    def next_red(self, label, slug=SLUG):
        return self.tdd_tasks("tdd_red", label, slug)[-1]["id"]

    def run_red(self, label="Remaining", slug=SLUG):
        """Run the newest tdd_red task of a cycle through the engine; returns the outcome dict."""
        return self.eng.run_task(self.next_red(label, slug))

    def prepare(self, slug=SLUG):
        """What `sentinel next` does first: create the cycle tasks."""
        self.eng.bookkeep(slug)
        return slug

    def last_reason(self):
        return [e for e in self.events("run.state_changed") if e["payload"]["to"] == "NEEDS_HUMAN"][-1]["payload"]["reason"]


def dedent(text):
    return textwrap.dedent(text)


def write_config(ws, cfg):
    (Path(ws) / "sentinel.config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))


# ---------------------------------------------------------------- Phase D part 2b: full TDD flow fixtures
TESTS = {"Remaining": [("RemainingBalanceTest", "employeeSeesRemainingDays"), ("RemainingBalanceTest", "balanceNeverBelowZero")],
         "Carry": [("CarryOverTest", "unusedDaysCarryOver")], "request_form": [("FormTest", "formShowsTheBalance")]}
CARRY_TEST = "CarryOverTest.unusedDaysCarryOver"
FORM_TEST = "FormTest.formShowsTheBalance"
PROD = "backend/src/main/java/leave/LeaveBalance.java"
TWO_REPOS = ("backend", "frontend")
FULL_OK = {"exit": 0, "report": [], "extra_passed": 2}

# One fake agent for every TDD role. Behavior comes from <workspace>/agent.json: "sleep", "mark", and "exec": {role: code}.
AGENT = r'''
cfg = {}
if pathlib.Path(ws, "agent.json").exists():
    cfg = json.loads(pathlib.Path(ws, "agent.json").read_text())
role = re.search(r"- Role: (\w+)", prompt).group(1)
obj = re.search(r"- Objective: (.*)", prompt).group(1)
t0 = time.time()
if cfg.get("sleep"):
    time.sleep(cfg["sleep"])
repo = "frontend" if "request_form" in obj else "backend"
klass = "FormTest" if repo == "frontend" else ("CarryOverTest" if "Carry" in obj else "RemainingBalanceTest")
prod = {"FormTest": "FormView", "CarryOverTest": "CarryOver", "RemainingBalanceTest": "LeaveBalance"}[klass]
prod_path = repo + "/src/main/java/leave/" + prod + ".java"
test_path = repo + "/src/test/java/leave/" + klass + ".java"
def camel(name):
    if name == "Balance never goes below zero":
        return "balanceNeverBelowZero"
    words = re.findall(r"[A-Za-z]+", name)
    return words[0].lower() + "".join(w.capitalize() for w in words[1:])
code = (cfg.get("exec") or {}).get(role)
if code:
    exec(code)
elif role == "qa_red":
    for sid, rel in re.findall(r"^- `([^`]+)` -> `([^`]+)`$", prompt, re.M):
        write(rel, "scenario " + sid + "\n")
    write_result()
elif role == "tdd_red":
    keys = re.findall(r"^- `(features/[^`]+)`$", prompt, re.M)
    body = "".join('  @Scenario("%s")\n  void %s() {}\n' % (k, camel(k.split(" :: ")[1])) for k in keys)
    write(test_path, "class " + klass + " {\n" + body + "}\n")
    write_result()
elif role == "tdd_green":
    write(prod_path, "class " + prod + " {}\n")
    write_result()
else:
    p = pathlib.Path(ws, prod_path)
    p.write_text(p.read_text() + "// refactored\n")
    write_result()
if cfg.get("mark"):
    pathlib.Path(ws, "mark-" + task_id + ".json").write_text(json.dumps([t0, time.time()]))
'''


def report(label, status):
    return [[c, n, status] for c, n in TESTS[label]]


def all_pass():
    return [[c, n, "pass"] for cases in TESTS.values() for c, n in cases]


class PDX(PD):
    """PD with the full-flow agent, the fake test tool driven per phase, and helpers that run phases through the engine."""
    TDD = {"red_retries": 2, "green_retries": 3, "refactor_retries": 2}

    def boot_x(self, model=None, tdd=None, **kw):
        extra = {}
        if model:
            extra["runners"] = {"fake": {"command": self.script("fake", AGENT), "model_flag": "--model"}}
            extra["agents"] = {r: {"runner": "fake", "model": model} for r in ("tdd_red", "tdd_green", "tdd_refactor")}
        kw.setdefault("tool", {"full": FULL_OK, "targeted": {"exit": 1, "report": report("Remaining", "failure")}})
        self.modes = dict(kw["tool"])
        slug = self.boot_exec(agent_body=AGENT, tdd={**self.TDD, **(tdd or {})}, **extra, **kw)
        return slug

    def reset_ws(self):
        (self.ws / "agent.json").unlink(missing_ok=True)
        super().reset_ws()

    def agent(self, **cfg):
        path = self.ws / "agent.json"
        old = json.loads(path.read_text()) if path.exists() else {}
        path.write_text(json.dumps({**old, **cfg}))

    def agent_exec(self, role, code):
        path = self.ws / "agent.json"
        old = json.loads(path.read_text()) if path.exists() else {}
        old.setdefault("exec", {})[role] = code
        path.write_text(json.dumps(old))

    def targeted(self, cases, exit_code=None, repo=None, **more):
        """Script the fake test tool's targeted mode (cases [[class, name, status]])."""
        failing = any(c[2] != "pass" for c in cases)
        key = f"{repo}:targeted" if repo else "targeted"
        self.modes[key] = {"exit": (1 if failing else 0) if exit_code is None else exit_code, "report": cases, **more}
        self.tool_modes(**self.modes)

    def tid(self, role, label="Remaining"):
        return self.tdd_tasks(role, label)[-1]["id"]

    def to_red_verified(self, label="Remaining", **kw):
        self.boot_x(**kw)
        self.prepare()
        self.targeted(report(label, "failure"))
        self.eng.run_task(self.tid("tdd_red", label))
        assert self.cstate(label) == "RED_VERIFIED", self.cycle(label)
        return self.tid("tdd_green", label)

    def to_green_verified(self, label="Remaining", **kw):
        self.to_red_verified(label, **kw)
        self.targeted(all_pass())
        self.eng.run_task(self.tid("tdd_green", label))
        assert self.cstate(label) == "GREEN_VERIFIED", self.cycle(label)
        return self.tid("tdd_refactor", label)

    def to_accepted(self, label="Remaining", **kw):
        self.to_green_verified(label, **kw)
        self.eng.run_task(self.tid("tdd_refactor", label))
        assert self.cstate(label) == "CYCLE_ACCEPTED", self.cycle(label)

    def set_cycle(self, label, **fields):
        self.eng.reg.update_row("cycles", self.cycle(label)["id"], **{k: (json.dumps(v) if isinstance(v, list) else v) for k, v in fields.items()})

    def accepted_carry_over(self):
        """The fixture of 'cycle carry-over is CYCLE_ACCEPTED with the test CarryOverTest.unusedDaysCarryOver'."""
        self.set_cycle("Carry", state="CYCLE_ACCEPTED", tests=[CARRY_TEST])

    def sql(self, text, args=()):
        with self.eng.reg.transaction():
            return self.eng.reg._c.execute(text, args).fetchall()

    def mark_running(self, task_id):
        """A task row that is RUNNING right now (the recovery leaves a fresh RUNNING task without a pid alone)."""
        from registry import _now
        self.sql("UPDATE tasks SET state='RUNNING', started_at=? WHERE id=?", (_now(), task_id))

    def snapshot(self):
        import sqlite3
        mem = sqlite3.connect(":memory:")
        self.eng.reg._c.backup(mem)
        self.addCleanup(mem.close)
        return mem

    def restore(self, mem):
        mem.backup(self.eng.reg._c)

    def drive(self, fail_role=None, fail_cases=None, limit=40, until=None):
        """What the orchestrator does: loop `next`, run each task step. The fake tool is set per task: Red fails the
        cycle's tests, every other role passes everything, `fail_role` fails `fail_cases` (default: the first test)."""
        steps, outs = [], []
        for _ in range(limit):
            step = self.eng.next_step(SLUG)
            steps.append(step)
            if step["kind"] != "task":
                break
            task = self.task(step["task"])
            behavior = self.eng.reg.get_row("cycles", task["cycle_id"])["behavior"] if task["cycle_id"] else ""
            label = next((k for k in TESTS if k in behavior), "Remaining")
            if task["role"] == "tdd_red":
                self.targeted(report(label, "failure") + [x for x in all_pass() if x[:2] not in [c[:2] for c in report(label, "x")]])
            elif task["role"] == fail_role:
                bad = fail_cases or [[*TESTS["Remaining"][0], "failure"]]
                self.targeted(bad + [x for x in all_pass() if x[:2] not in [c[:2] for c in bad]])
            else:
                self.targeted(all_pass())
            outs.append(self.eng.run_task(step["task"]))
            if until and until():
                break
        return steps, outs
