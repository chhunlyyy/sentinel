"""Phase E part 2 (PE-02): orchestrator skill rewritten around `sentinel next`, adapters regenerated."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "sentinel" / "scripts"
sys.path.insert(0, str(SCRIPTS))
CLI = [sys.executable, str(SCRIPTS / "sentinel.py")]

SKILL = (ROOT / "skills/sentinel/SKILL.md").read_text()
PIPELINE = (ROOT / "skills/sentinel/pipeline.md").read_text()


def section(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


def git_show(path, rev="HEAD"):
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{path}"], capture_output=True, text=True, check=True).stdout


def matrix(text):
    return "\n".join(l for l in text.splitlines() if l.startswith("|") and "---" not in l and
                     any(w in l for w in ("Factor", "Repos touched", "Files likely", "Schema migration", "Auth or",
                                          "Security surface", "Regression risk", "Business logic")))


V2 = section(SKILL, "Version 2 runs")
LEGACY = section(SKILL, "Legacy runs (0.1)")


class Skill(unittest.TestCase):
    def test_AC_ARC_03l_next_loop_per_kind(self):
        self.assertTrue(V2, "section 'Version 2 runs' missing")
        for needle in ("sentinel next <slug> --json", "sentinel task run <task-id>", '"cli"', '"native"',
                       "prompt", "sentinel task complete <task-id>", "sentinel triage", "decisions.md",
                       "sentinel verify", "exit code 6", "stop until", "wait", "sentinel report <slug>",
                       "sentinel accept"):
            with self.subTest(needle):
                self.assertIn(needle, V2)
        for kind in ("task", "orchestrator", "human", "wait", "done"):
            self.assertRegex(V2, rf"`{kind}`")

    def test_AC_ARC_03m_no_authority_over_state(self):
        self.assertTrue(V2)
        self.assertRegex(V2, r"never runs? `sentinel approve` or `sentinel accept`")
        self.assertRegex(V2, r"never retr")
        self.assertIn("reorder", V2)
        self.assertIn("skip", V2)
        self.assertIn(".sentinel/runs/", V2)
        self.assertIn("registry", V2)
        for banned in ("sentinel run update", "sentinel stage run", "sentinel release-check"):
            for line in V2.splitlines():
                if banned in line:
                    self.assertRegex(line.lower(), r"never|not|only 0\.1|legacy", line)
        self.assertRegex(V2, r"[Nn]ever verif\w+ a task's result yourself|in place of `sentinel verify`")

    def test_AC_ARC_03m_agents_never_run_human_commands(self):
        for cmd in ("approve", "accept", "resolve", "run export", "run import", "dashboard"):
            self.assertIn(f"`sentinel {cmd}`", V2)
        self.assertRegex(V2, r"never run[s]?[^\n]*`sentinel dashboard`|`sentinel dashboard`[^\n]*never")

    def test_AC_VIS_03d_no_provider_choice(self):
        self.assertTrue(V2)
        self.assertNotIn("--runner", V2)
        self.assertNotIn("sentinel routing", V2)
        self.assertRegex(V2, r"engine picks the adapter, provider and model")

    def test_AC_VIS_01b_isolation_stays(self):
        for w in ("Agent tool", "invoke_subagent", "Inline, only if neither exists"):
            self.assertIn(w, SKILL)
        self.assertRegex(SKILL, r"reviewer or qa task never runs in a context that wrote code for the run")

    def test_AC_VIS_05a_legacy_section(self):
        self.assertTrue(LEGACY, "section 'Legacy runs (0.1)' missing")
        for w in ("sentinel run new <slug> --tier N", "--adhoc", "--legacy", "sentinel run update", "sentinel resume",
                  "sentinel stage run", "sentinel release-check", "sentinel sync push", "sentinel run finish"):
            with self.subTest(w):
                self.assertIn(w, LEGACY)
        self.assertRegex(SKILL, r"created with --tier, --adhoc or --legacy is a 0\.1 run, any other run is version 2")
        self.assertRegex(SKILL, r'`"schema_version"` 2')
        self.assertIn("sentinel next", LEGACY + V2)
        self.assertRegex(SKILL, r"refus\w+ a 0\.1 run")

    def test_AC_VIS_05b_pipeline_matrix_and_stages(self):
        old = git_show("skills/sentinel/pipeline.md")
        self.assertTrue(matrix(old))
        self.assertEqual(matrix(PIPELINE), matrix(old))
        self.assertIn("## Pipeline by tier", PIPELINE)
        self.assertEqual(section(PIPELINE, "Pipeline by tier"), section(old, "Pipeline by tier"))
        for w in ("CREATED", "TRIAGED", "SPECIFICATION_REVIEW", "GHERKIN_REVIEW", "EXECUTING", "VERIFYING",
                  "NEEDS_HUMAN", "COMPLETED", "spec-lite", "security gate", "Version 2"):
            with self.subTest(w):
                self.assertIn(w, PIPELINE)

    def test_AC_VIS_05c_engine_matrix_matches_pipeline(self):
        import machines
        rows = {}
        for l in matrix(PIPELINE).splitlines()[1:]:
            c = [x.strip() for x in l.strip("|").split("|")]
            rows[c[0]] = c[1:]
        self.assertEqual(rows["Repos touched"][3], "2 or more")
        self.assertEqual(machines.compute_tier({"repos": "2", "files": "5", "migration": "additive"}), 4)
        self.assertEqual(machines.compute_tier({"files": "5", "migration": "additive"}), 3)
        self.assertEqual(rows["Schema migration"][2], "additive")

    def test_AC_VIS_05d_helper_skills(self):
        resume = (ROOT / "skills/sentinel-resume/SKILL.md").read_text()
        status = (ROOT / "skills/sentinel-status/SKILL.md").read_text()
        self.assertIn("sentinel next <slug> --json", resume)
        self.assertIn("sentinel report <slug>", status)
        for name, old in (("sentinel-resume", resume), ("sentinel-status", status)):
            before = git_show(f"skills/{name}/SKILL.md")
            for line in before.split("---\n", 2)[2].splitlines():
                if line.strip():
                    self.assertIn(line, old, f"{name}: 0.1 line dropped")


class Adapters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.ws = Path(cls._tmp.name) / "ws"
        cls.ws.mkdir()
        repo = cls.ws / "backend"
        repo.mkdir()
        (repo / "build.gradle").write_text("")
        for c in (["init", "-q", "-b", "main"], ["add", "."], ["-c", "user.email=a@b", "-c", "user.name=t", "commit", "-q", "-m", "i"]):
            subprocess.run(["git", *c], cwd=repo, check=True, capture_output=True)
        r = subprocess.run(CLI + ["--dir", str(cls.ws), "init", "--shape", "single", "--non-interactive", "--local-only"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr

    def sync(self, *args, ws=None):
        return subprocess.run(CLI + ["--dir", str(ws or self.ws), "sync-adapters", *args], capture_output=True, text=True)

    def snapshot(self, ws):
        return {str(p.relative_to(ws)): p.read_bytes() for d in (".claude", ".sentinel/generated") for p in (ws / d).rglob("*")
                if p.is_file()} | ({"AGENTS.md": (ws / "AGENTS.md").read_bytes()} if (ws / "AGENTS.md").exists() else {})

    def test_AC_OPS_04a_claude_outputs(self):
        r = self.sync()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for f in ("SKILL.md", "pipeline.md"):
            self.assertEqual((self.ws / ".claude/skills/sentinel" / f).read_bytes(), (ROOT / "skills/sentinel" / f).read_bytes())
        import json
        deny = json.loads((self.ws / ".claude/settings.json").read_text())["permissions"]["deny"]
        for rule in ("Bash(sentinel approve:*)", "Bash(sentinel accept:*)", "Bash(sentinel dashboard:*)"):
            self.assertIn(rule, deny)

    def test_AC_OPS_04a_agents_unchanged_vs_head(self):
        """Agent files do not depend on skills/ or the agents block: generate with HEAD sources and compare."""
        self.sync()
        head = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, head, True)
        subprocess.run(f"git -C {ROOT} archive HEAD sentinel skills | tar -x -C {head}", shell=True, check=True)
        ws2 = head / "ws"
        shutil.copytree(self.ws, ws2, ignore=shutil.ignore_patterns(".claude", ".sentinel"))
        r = subprocess.run([sys.executable, str(head / "sentinel/scripts/sentinel.py"), "--dir", str(ws2), "sync-adapters"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        new = sorted((self.ws / ".claude/agents").glob("*.md"))
        old = sorted((ws2 / ".claude/agents").glob("*.md"))
        self.assertTrue(new)
        self.assertEqual([p.name for p in new], [p.name for p in old])
        for a, b in zip(new, old):
            self.assertEqual(a.read_bytes(), b.read_bytes(), a.name)

    def test_AC_OPS_04b_other_tools(self):
        body = SKILL.split("---\n", 2)[2]
        for tool, extra in (("agents", None), ("codex", None), ("gemini", "GEMINI.md"), ("cursor", ".cursor/rules/sentinel.mdc")):
            with self.subTest(tool):
                ws = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, ws, True)
                shutil.copytree(self.ws, ws, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".claude", "AGENTS.md", "GEMINI.md", ".cursor"))
                r = self.sync("--tool", tool, ws=ws)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual((ws / ".sentinel/generated/orchestrator.md").read_text(), body)
                agents = (ws / "AGENTS.md").read_text()
                for w in ("sentinel next", "--json", "sentinel task run", "sentinel task complete", "sentinel stage run",
                          "never run `sentinel approve` or `sentinel accept`"):
                    self.assertIn(w, agents.replace("Agents never", "agents never"))
                if extra == "GEMINI.md":
                    self.assertIn("@./AGENTS.md", (ws / extra).read_text())
                if extra == ".cursor/rules/sentinel.mdc":
                    t = (ws / extra).read_text()
                    self.assertIn("AGENTS.md", t)
                    self.assertIn("orchestrator.md", t)
                if tool in ("agents", "codex"):
                    self.assertFalse((ws / "GEMINI.md").exists() or (ws / ".cursor").exists())

    def test_AC_OPS_04c_idempotent(self):
        ws = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, ws, True)
        shutil.copytree(self.ws, ws, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".claude", "AGENTS.md", ".sentinel"))
        subprocess.run(CLI + ["--dir", str(ws), "init", "--shape", "single", "--non-interactive", "--local-only"], capture_output=True)
        self.sync("--tool", "agents", ws=ws)
        self.sync(ws=ws)
        first = self.snapshot(ws)
        self.sync("--tool", "agents", ws=ws)
        self.sync(ws=ws)
        self.assertEqual(self.snapshot(ws), first)
        self.assertEqual((ws / "AGENTS.md").read_text().count("<!-- sentinel:begin -->"), 1)

    def test_AC_OPS_04d_no_machine_paths(self):
        self.sync()
        self.sync("--tool", "agents")
        for d in (".claude", ".sentinel/generated"):
            for p in (self.ws / d).rglob("*"):
                if p.is_file() and p.suffix in (".md", ".mdc", ".json"):
                    t = p.read_text()
                    for bad in ("/home/", "Desktop/", "{{"):
                        self.assertNotIn(bad, t, f"{p} {bad}")
        self.assertNotIn("{{", (self.ws / "AGENTS.md").read_text())


# ---------------------------------------------------------------- AC-ARC-03n / AC-ARC-03o: a scripted orchestrator
TOOL = """#!{py}
import json, os, pathlib, sys
mode, args = sys.argv[1], sys.argv[2:]
repo = pathlib.Path(os.getcwd())
PROD = {{"RemainingBalanceTest": "LeaveBalance", "CarryOverTest": "CarryOver"}}
out = pathlib.Path("build/test-results/test")
for a in args:
    if a.startswith("--report-dir="):
        out = pathlib.Path(a[len("--report-dir="):])
cases, failing = [], False
if mode == "targeted":
    # a test passes once the production class it is about exists, so Red fails and Green passes
    for a in args:
        if "." not in a or a.startswith("-"):
            continue
        klass, name = a.rsplit(".", 1)
        ok = (repo / "src/main/java/leave" / (PROD.get(klass, klass) + ".java")).exists()
        failing = failing or not ok
        cases.append('<testcase classname="leave.%s" name="%s">%s</testcase>' % (klass, name, "" if ok else '<failure message="expected 1 got 2">AssertionError</failure>'))
elif mode == "test":
    cases = ['<testcase classname="leave.OtherTest" name="t%d"/>' % i for i in range(2)]
if cases:
    out.mkdir(parents=True, exist_ok=True)
    (out / "TEST-fake.xml").write_text('<testsuite name="fake">' + "".join(cases) + "</testsuite>")
sys.exit(1 if failing else 0)
"""

# Every role of the run in one fake CLI: the specifier and test designer copy canned files, the TDD roles are the
# Phase D agent, every other role finishes with no findings.
FAKE_AGENT = r"""
role0 = re.search(r"- Role: (\w+)", prompt).group(1)
canned = pathlib.Path(ws, "canned")
shared = pathlib.Path(re.search(r"- Shared specs: (\S+)", prompt).group(1))
if role0 == "specifier":
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "spec.md").write_text((canned / "spec.md").read_text())
    write_result()
    sys.exit(0)
if role0 == "test_designer":
    (shared / "features").mkdir(parents=True, exist_ok=True)
    for f in (canned / "features").glob("*.feature"):
        (shared / "features" / f.name).write_text(f.read_text())
    write_result()
    sys.exit(0)
if role0 not in ("tdd_red", "tdd_green", "tdd_refactor"):
    write_result()
    sys.exit(0)
""" + __import__("pd_helpers").AGENT

SIX = ("run new", "triage", "next", "task run", "task complete", "verify", "report")


class Scripted(unittest.TestCase):
    """AC-ARC-03n and AC-ARC-03o: a script plays the orchestrator by mapping each `next` step kind to the one action the
    skill table names; a scripted human approves at a pseudo-terminal. Every command the script runs is recorded."""

    def setUp(self):
        from pb_helpers import CLI_ENV
        from pc_helpers import GIT_ENV
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.env = {**os.environ, **GIT_ENV, "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop("SENTINEL_TASK_ID", None)
        self.cli_env = {**CLI_ENV, "PYTHONDONTWRITEBYTECODE": "1"}
        self.calls, self.approvals = [], []
        (self.ws / "bin").mkdir()
        repo = self.ws / "backend"
        repo.mkdir()
        for c in (["init", "-q", "-b", "main"], ["add", "."], ["commit", "-q", "-m", "init"]):
            if c[0] == "add":
                (repo / ".gitignore").write_text("build/\n")
                (repo / "README.md").write_text("hello\n")
            subprocess.run(["git", *c], cwd=repo, check=True, capture_output=True, env=self.env)

    def workspace(self, slug, single_model):
        import pd_helpers
        from pb_helpers import spec_text
        from pe_helpers import ROLES, entry
        tool = self.ws / "bin" / "faketest"
        tool.write_text(TOOL.format(py=sys.executable))
        tool.chmod(0o755)
        fake = self.ws / "bin" / "fake"
        from pc_helpers import PREAMBLE
        fake.write_text(PREAMBLE.format(py=sys.executable, stdin=False) + FAKE_AGENT)
        fake.chmod(0o755)
        ids = ("AC-1", "AC-2", "AC-3")
        canned = self.ws / "canned"
        (canned / "features").mkdir(parents=True)
        (canned / "spec.md").write_text(spec_text(slug, tier=2, acs=tuple(f"{a} (REQ-1): x" for a in ids)))
        (canned / "features" / "balance.feature").write_text(pd_helpers.feature(
            "@REQ-1 @repo-backend", [("", "Remaining balance", [("AC-1", "Employee sees remaining days"), ("AC-2", "Balance never goes below zero")]),
                                     ("", "Carry-over", [("AC-3", "Unused days carry over")])]))
        cfg = {"version": 1, "state": {"dir": ".sentinel", "shared_mode": "local"}, "single_model": single_model,
               "repos": [entry("backend", sys.executable, str(tool))],
               "runners": {"fake": {"command": str(fake)}},
               "agents": {r: {"runner": "fake"} for r in (*ROLES, "specifier", "test_designer")}}
        (self.ws / "sentinel.config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))

    def sentinel(self, *args, timeout=120):
        r = subprocess.run(CLI + ["--dir", str(self.ws), *args], capture_output=True, text=True, env=self.env,
                           stdin=subprocess.DEVNULL, timeout=timeout)
        self.calls.append(" ".join(args[:2]) if args[0] in ("run", "task") else args[0])
        return r

    def human(self, step):
        """The scripted human: runs the approve command the step names at a pseudo-terminal and types the hash prefix."""
        from pb_helpers import PROMPT, PtyProc
        commands = step.get("commands") or [step.get("command")]
        cmd = next(c for c in commands if c and " approve " in c).split()
        self.assertEqual(cmd[:2], ["sentinel", "approve"], step)
        proc = PtyProc(["--dir", str(self.ws), *cmd[1:]], env=self.cli_env)
        self.assertTrue(proc.wait_for(PROMPT, 30), proc.out)
        sha = re.search(r"sha256: ([0-9a-f]{64})", proc.out.decode()).group(1)
        proc.send(sha[:8] + "\n")
        code, out = proc.finish(30)
        self.assertEqual(code, 0, out)
        self.approvals.append(cmd[3])
        self.calls.append("[human]")

    def native(self, step):
        """What a fresh subagent does: its whole task is the prompt file; it runs in the repo and writes the result file."""
        prompt = Path(step["prompt"]).read_text()
        r = subprocess.run([str(self.ws / "bin" / "fake"), prompt], cwd=self.ws / "backend", capture_output=True, text=True,
                           env={**self.env, "SENTINEL_TASK_ID": step["task"]}, stdin=subprocess.DEVNULL, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def orchestrate(self, slug):
        new = self.sentinel("run", "new", slug, "--type", "feature")
        self.assertEqual(new.returncode, 0, new.stdout + new.stderr)
        for _ in range(200):
            r = self.sentinel("next", slug, "--json")
            self.assertIn(r.returncode, (0, 6), r.stdout + r.stderr)
            step = json.loads(r.stdout)
            kind = step["kind"]
            if kind == "human":
                self.assertEqual(r.returncode, 6)
                self.human(step)
            elif kind == "task":
                if step["adapter"] == "native" and "prompt" in step:
                    self.native(step)
                    out = self.sentinel("task", "complete", step["task"])
                else:
                    # a cli task runs to the end; a queued native task is handed to the orchestrator and `next` then names its prompt
                    out = self.sentinel("task", "run", step["task"])
                self.assertIn(out.returncode, (0, 6), out.stdout + out.stderr)
            elif kind == "orchestrator":
                if step.get("command", "").startswith("sentinel triage"):
                    out = self.sentinel("triage", slug, "--factors", "repos=1,files=3,migration=no,auth=no,security=none,regression=low,logic=simple")
                elif step.get("command", "").startswith("sentinel verify"):
                    out = self.sentinel("verify", slug)
                else:
                    self.fail(f"an orchestrator step this loop cannot do: {step}")
                self.assertIn(out.returncode, (0, 1), out.stdout + out.stderr)
            elif kind == "wait":
                time.sleep(0.2)
            elif kind == "done":
                out = self.sentinel("report", slug)
                self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
                return
            else:
                self.fail(f"unknown step: {step}")
        self.fail("the loop did not finish in 200 steps: " + json.dumps(step))

    def run_row(self, slug):
        import sqlite3
        c = sqlite3.connect(self.ws / ".sentinel" / "sentinel.db")
        c.row_factory = sqlite3.Row
        self.addCleanup(c.close)
        run = dict(c.execute("SELECT * FROM runs WHERE slug=?", (slug,)).fetchone())
        run["tasks"] = [dict(t) for t in c.execute("SELECT * FROM tasks WHERE run_id=?", (run["id"],))]
        return run

    def test_AC_ARC_03n_a_scripted_orchestrator_that_follows_the_skill_completes_a_run(self):
        self.workspace("leave-balance", single_model=False)
        self.orchestrate("leave-balance")
        run = self.run_row("leave-balance")
        self.assertEqual((run["state"], run["acceptance_status"]), ("COMPLETED", "accepted"))
        names = ("run new", "triage", "next", "task run", "task complete", "verify", "report")
        self.assertLessEqual(set(self.calls) - {"[human]"}, set(names), self.calls)
        # nothing was called between a human step and the human's decision
        marks = [i for i, c in enumerate(self.calls) if c == "[human]"]
        self.assertEqual(len(marks), 2, self.calls)
        for i in marks:
            self.assertEqual(self.calls[i - 1], "next", self.calls)
            self.assertEqual(self.calls[i + 1], "next", self.calls)
        self.assertEqual(self.approvals, ["spec", "gherkin"])
        self.assertEqual({t["adapter"] for t in run["tasks"]}, {"cli"})
        self.assertLessEqual({"specifier", "test_designer", "tdd_red", "tdd_green", "tdd_refactor"}, {t["role"] for t in run["tasks"]})
        for call in ("run new", "triage", "task run", "verify", "report"):
            self.assertIn(call, self.calls)

    def test_AC_ARC_03o_the_same_loop_works_with_native_subagents(self):
        self.workspace("leave-native", single_model=True)
        self.orchestrate("leave-native")
        run = self.run_row("leave-native")
        self.assertEqual((run["state"], run["acceptance_status"]), ("COMPLETED", "accepted"))
        self.assertTrue(run["tasks"])
        self.assertEqual({t["adapter"] for t in run["tasks"]}, {"native"})
        self.assertIn("task complete", self.calls)
        self.assertEqual(self.calls.count("task complete"), len(run["tasks"]), self.calls)


if __name__ == "__main__":
    unittest.main()
