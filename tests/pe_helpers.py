"""Shared fixtures for Phase E tests: a VERIFYING run with accepted cycles, the fake check tool, and readers."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import yaml  # noqa: E402

from pb_helpers import SLUG, spec_text  # noqa: E402
from pc_helpers import git  # noqa: E402
from pd_helpers import PDX, AGENT, REPORT, PATTERNS, SCENARIO_REF, default_features  # noqa: E402

DEFAULT_MODES = {"test": {"exit": 0, "report": [], "extra_passed": 2}}
T_REMAIN = "RemainingBalanceTest.employeeSeesRemainingDays"
T_CARRY = "CarryOverTest.unusedDaysCarryOver"
T_FORM = "FormTest.formShowsTheBalance"
ROLES = ("tdd_red", "tdd_green", "tdd_refactor", "hardener", "reviewer", "qa", "promotion", "docs", "rollout", "retrospective")


def entry(rid, py, tool, **over):
    cmds = {m: f"{py} {tool} {m}" for m in ("test", "build", "lint", "typecheck", "mutate", "audit", "docs")}
    e = {"id": rid, "path": rid, "role": rid, "profile": "generic", "test_globs": ["src/test/**"],
         "production_globs": ["src/main/**"], "commands": cmds, "targeted_test": f"{py} {tool} targeted {{tests}}",
         "test_report": {"kind": "junit-xml", "path": REPORT}, "failure_patterns": PATTERNS,
         "scenario_ref": SCENARIO_REF, "migration_lane": "(^|/)db/migration/"}
    e.update(over)
    return e


class PE(PDX):
    """A version 2 run in VERIFYING: cycles accepted with tests, completed tasks with write scopes."""

    def boot_ver(self, tier=3, repos=("backend", "frontend"), modes=None, limits=None, verification=None, typ="feature",
                 repo_over=None, agent_body=AGENT, **cfg):
        self.modes = {**DEFAULT_MODES, **(modes or {})}
        tool = self.fake_tool(**self.modes)
        entries = [entry(r, sys.executable, tool, **(repo_over or {})) for r in repos]
        extra = {"single_model": False, "repos": entries,
                 "runners": {"fake": {"command": self.script("fake", agent_body)}},
                 "agents": {r: {"runner": "fake"} for r in ROLES}}
        if limits:
            extra["limits"] = limits
        if verification is not None:
            extra["verification"] = verification
        extra.update(cfg)
        self.use_config(**extra)
        self.mk(SLUG, "PLANNED", tier, typ)
        run = self.run_row()
        for rid in repos:
            if rid != "backend":
                self.eng.reg.add_run_repo(run["id"], rid, "abc")
        if typ == "docs":
            self.write_spec(spec_text(SLUG, tier=tier, typ="docs"))
            assert self.submit("specifier")["accepted"]
            self.approve("spec")
            self.set_state("EXECUTING")
        else:
            files = default_features(len(repos) > 1, len(repos) > 1)
            ids = sorted({a for t in files.values() for a in re.findall(r"@(AC-\d+)", t)}, key=lambda a: int(a[3:]))
            self.write_spec(spec_text(SLUG, tier=tier, acs=tuple(f"{a} ({'REQ-2' if a == 'AC-4' else 'REQ-1'}): x" for a in ids),
                                      typ="feature"))
            assert self.submit("specifier")["accepted"]
            self.approve("spec")
            self.write_features(files)
            assert self.submit("test_designer")["accepted"]
            self.approve("gherkin")
            self.eng.advance(SLUG)
            assert self.state() == "EXECUTING", self.state()
        self.fix_baseline(repos)
        if typ != "docs":
            self.accept_cycles()
        else:
            tid = self.eng.create_task(SLUG, "docs", "docs", repos=["backend"], write=["backend/docs/**"])["id"]
            self.eng.reg.update_row("tasks", tid, state="COMPLETED")
        self.set_state("VERIFYING")
        return SLUG

    def fix_baseline(self, repos):
        run = self.run_row()
        with self.eng.reg.transaction():
            for rid in repos:
                sha = git(self.ws / rid, "rev-parse", "HEAD").strip()
                self.eng.reg._c.execute("UPDATE run_repos SET baseline_sha=? WHERE run_id=? AND repo_id=?", (sha, run["id"], rid))

    def set_state(self, state, slug=SLUG):
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("UPDATE runs SET state=?, previous_state=NULL WHERE slug=?", (state, slug))

    def set_snapshot_config(self, mutate):
        cfg = self.eng._run_config(self.run_row())
        mutate(cfg)
        with self.eng.reg.transaction():
            text = yaml.safe_dump(cfg)
            cid = self.eng.reg.store_config_version("workspace", text, author="t")
            self.eng.reg._c.execute("UPDATE runs SET config_snapshot_id=?", (cid,))
        (self.ws / "sentinel.config.yaml").write_text(text)

    def accept_cycles(self):
        """Every live cycle CYCLE_ACCEPTED with its tests, one completed task per repo with production and test scope."""
        tests = {"Remaining": [T_REMAIN], "Carry": [T_CARRY], "request_form": [T_FORM]}
        for c in self.cycles():
            label = next(k for k in tests if k in c["behavior"])
            self.eng.reg.update_row("cycles", c["id"], state="CYCLE_ACCEPTED", tests=json.dumps(tests[label]))
        for rid in dict.fromkeys(c["repo_id"] for c in self.cycles()):
            tid = self.eng.create_task(SLUG, "hardener", "work", repos=[rid], write=[f"{rid}/src/main/**", f"{rid}/src/test/**", f"{rid}/db/migration/**"])["id"]
            self.eng.reg.update_row("tasks", tid, state="COMPLETED")
        self.fixture_ids = [t["id"] for t in self.tasks_of()]
        self.pass_targeted()

    def pass_targeted(self):
        cases = [[t.split(".")[0], t.split(".")[1], "pass"] for t in (T_REMAIN, T_CARRY, T_FORM)]
        self.modes["targeted"] = {"exit": 0, "report": cases}
        self.tool_modes(**self.modes)

    def mode(self, name, repo=None, **sc):
        self.modes[f"{repo}:{name}" if repo else name] = sc
        self.tool_modes(**self.modes)

    def write_file(self, path, text):
        p = self.ws / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def change(self, repos=("backend", "frontend")):
        for r in repos:
            self.write_file(f"{r}/src/main/A.java", "class A {}\n")

    def verify(self, slug=SLUG):
        return self.eng.verify(slug)

    def vrows(self, kind=None, repo=None, round=None, slug=SLUG):
        rid = self.run_row(slug)["id"]
        return [e for e in self.eng.reg.rows("evidence", run_id=rid)
                if e["round"] is not None and kind in (None, e["kind"]) and repo in (None, e["repo_id"])
                and round in (None, e["round"])]

    def vkinds(self, repo, round=1):
        return {e["kind"] for e in self.vrows(repo=repo, round=round)}

    def rounds(self, slug=SLUG):
        return self.eng.reg.rows("verification_rounds", run_id=self.run_row(slug)["id"])

    def tool_calls(self, mode=None):
        return [c for c in self.tool_log() if mode in (None, c["mode"])]

    def tasks_of(self, role=None, state=None, slug=SLUG):
        return [t for t in self.eng.reg.rows("tasks", run_id=self.run_row(slug)["id"])
                if role in (None, t["role"]) and state in (None, t["state"])]

    def new_tasks(self, role=None, slug=SLUG):
        """Tasks created after the fixture."""
        return [t for t in self.tasks_of(role, slug=slug) if t["id"] not in getattr(self, "fixture_ids", [])]

    BAL = "backend/src/main/java/leave/Balance.java"

    def approve_security(self):
        """The human's decision through the normal command (R20 `resolve --approve-security`)."""
        self.eng.resolve(SLUG, user="dev", channel="tty", comment="security reviewed", approve_security=True)

    def to_ready(self, tier=3, **kw):
        """REVIEWING with every review task COMPLETED, ready for R15."""
        self.boot_ver(tier=tier, **kw)
        self.change()
        for c in self.cycles():
            self.eng.reg.add_trace_link(self.run_row()["id"], "cycle", c["id"], "file", self.BAL)
        assert self.verify()["exit"] == 0
        if tier >= 3:
            for t in self.new_tasks():
                self.eng.reg.update_row("tasks", t["id"], state="COMPLETED")

    def to_completed(self, tier=3, **kw):
        self.to_ready(tier, **kw)
        step = self.eng.next_step(SLUG)
        assert self.state() == "COMPLETED", (self.state(), step)

    def prefix(self):
        return self.eng.report_info(SLUG)["sha256"][:8]
