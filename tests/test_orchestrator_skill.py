"""Phase E part 2 (PE-02): orchestrator skill rewritten around `sentinel next`, adapters regenerated."""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
