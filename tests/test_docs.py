"""Phase H part C: documentation and SPEC.md checks (docs_spec.feature).

Markdown is parsed for sections, commands, links and version strings. Commands are run through `sentinel <sub> --help`.
"""
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = [sys.executable, str(ROOT / "sentinel" / "scripts" / "sentinel.py")]
DOC_FILES = [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md"))
SKILL_FILES = sorted((ROOT / "skills").rglob("*.md"))
# these two name removed commands and old versions on purpose
HISTORY = {"docs/migration-1.1.md", "CHANGELOG.md"}


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def sections(md):
    """[(level, heading, body)] for every Markdown heading outside code fences."""
    out, fence, cur = [], False, None
    for line in md.splitlines():
        if line.startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"(#{1,6})\s+(.*)", line)
        if m:
            cur = [len(m.group(1)), m.group(2).strip(), []]
            out.append(cur)
        elif cur is not None:
            cur[2].append(line)
    return [(lv, h, "\n".join(b)) for lv, h, b in out]


def body_of(md, heading_re):
    """Text of every section whose heading matches, with its subsections."""
    secs = sections(md)
    found = []
    for i, (lv, h, b) in enumerate(secs):
        if re.search(heading_re, h, re.I):
            text = [b]
            for lv2, _h2, b2 in secs[i + 1:]:
                if lv2 <= lv:
                    break
                text.append(b2)
            found.append("\n".join(text))
    return "\n".join(found)


def anchor(heading):
    s = re.sub(r"[^\w\s-]", "", heading.strip().lower().replace("`", ""))
    return re.sub(r"\s", "-", s)


class Guides(unittest.TestCase):
    def test_AC_OPS_04e_each_guide_covers_its_topics(self):
        rows = [
            ("docs/workflow.md", r"version 2 flow", ["run new", "triage", "specification", "gherkin", "approve", "tdd", "cycle", "verify", "accept", "report"]),
            ("docs/workflow.md", r"0\.1 runs|legacy", ["--legacy", "--tier", "--adhoc"]),
            ("docs/dashboard.md", r"start", ["sentinel dashboard", "session"]),
            ("docs/dashboard.md", r"screens", ["overview", "projects", "tasks", "approvals", "runs", "quality", "reports", "settings"]),
            ("docs/dashboard.md", r"read only", ["sentinel init", "sentinel.config.yaml", "sentinel sync-adapters", "G-1"]),
            ("docs/config.md", r"policies", ["max_parallel_tasks", "human_required"]),
            ("docs/config.md", r"^tdd", ["red_retries", "green_retries"]),
            ("docs/config.md", r"verification", ["mutation", "migration_check"]),
            ("docs/config.md", r"providers", ["fallback", "disabled"]),
            ("docs/config.md", r"agents", ["write_scope", "role"]),
            ("docs/config.md", r"notifications", ["desktop"]),
            ("docs/config.md", r"globs", ["test_globs", "production_globs"]),
            ("docs/operations.md", r"notifications", ["sentinel notifications", "user.db"]),
            ("docs/operations.md", r"stats|analytics", ["sentinel stats", "lead time", "acceptance rate"]),
            ("docs/operations.md", r"audit", ["sentinel audit export", "sentinel audit verify"]),
            ("docs/operations.md", r"backup", ["sentinel backup", "--verify", "restore"]),
            ("docs/migration-1.1.md", r"upgrad|install", ["0.1.0b7", "uv tool", "doctor"]),
            ("docs/migration-1.1.md", r"what changes|changed", ["sentinel run new"]),
            ("docs/migration-1.1.md", r"untouched|unchanged", [".sentinel/runs", "state.json"]),
            ("docs/migration-1.1.md", r"removed", ["sentinel submit", "task run", "task complete"]),
            ("docs/migration-1.1.md", r"roll ?back|downgrad", ["0.1.0b7"]),
            ("README.md", r"version 2|how it works|workflow", ["run new", "approve", "accept"]),
            ("README.md", r"dashboard", ["sentinel dashboard"]),
            ("README.md", r"documentation", ["docs/dashboard.md", "docs/operations.md", "docs/migration-1.1.md", "docs/workflow.md", "docs/config.md", "docs/security.md", "CHANGELOG.md"]),
        ]
        for f, heading, words in rows:
            with self.subTest(file=f, heading=heading):
                path = ROOT / f
                self.assertTrue(path.exists(), f)
                text = body_of(path.read_text(encoding="utf-8"), heading)
                self.assertTrue(text.strip(), f"{f} has no section matching {heading!r}")
                low = text.lower()
                for w in words:
                    self.assertIn(w.lower(), low, f"{f} section {heading!r} lacks {w!r}")


def cli_tree():
    r = subprocess.run(CLI + ["--help"], capture_output=True, text=True, timeout=60)
    m = re.search(r"\{([a-z0-9,-]+)\}", r.stdout)
    return set(m.group(1).split(","))


_HELP = {}
_WS = []


def workspace():
    """A throwaway workspace with a config: `stage run --help` loads one before it prints."""
    if not _WS:
        import atexit
        import tempfile
        d = tempfile.mkdtemp(prefix="docs-ws-")
        atexit.register(shutil.rmtree, d, True)
        subprocess.run(CLI + ["--dir", d, "init", "--non-interactive", "--local-only", "--shape", "single"], capture_output=True, text=True, cwd=d, timeout=60)
        _WS.append(d)
    return _WS[0]


def help_text(args):
    key = tuple(args)
    if key not in _HELP:
        ws = workspace()
        r = subprocess.run(CLI + ["--dir", ws] + list(args) + ["--help"], capture_output=True, text=True, timeout=60, cwd=ws)
        _HELP[key] = (r.returncode, r.stdout)
    return _HELP[key]


def code_spans(md):
    """Text inside code fences and inline code, one string per line."""
    out, fence = [], False
    for line in md.splitlines():
        if line.startswith("```"):
            fence = not fence
            continue
        if fence:
            out.append(line)
        else:
            out.extend(re.findall(r"`([^`]+)`", line))
    return out


def commands_in(md, subs):
    found = []
    for line in code_spans(md):
        for m in re.finditer(r"(?<![\w./@-])sentinel[ \t]+([a-z][a-z0-9-]*)((?:[ \t]+[^\n`|;&<>$()]*)?)", line):
            if m.group(1) in subs:
                found.append((m.group(1), m.group(2).strip()))
    return found


class Commands(unittest.TestCase):
    def test_AC_OPS_04f_every_command_in_the_docs_exists(self):
        subs = cli_tree()
        checked = 0
        for path in DOC_FILES + SKILL_FILES:
            rel = str(path.relative_to(ROOT))
            md = path.read_text(encoding="utf-8")
            if rel not in HISTORY:
                self.assertIsNone(re.search(r"sentinel submit", md), f"{rel} names sentinel submit")
            for sub, rest in commands_in(md, subs):
                with self.subTest(file=rel, command=f"{sub} {rest}"[:80]):
                    code, text = help_text([sub])
                    self.assertEqual(code, 0)
                    words = [w for w in re.split(r"\s+", rest) if w]
                    if words and re.fullmatch(r"[a-z][a-z-]*", words[0]):
                        code2, text2 = help_text([sub, words[0]])
                        if code2 == 0:
                            text = text + text2
                    for flag in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", rest):
                        self.assertIn(flag, text, f"{rel}: sentinel {sub} has no {flag}")
                    checked += 1
        self.assertGreater(checked, 40)

    def test_AC_OPS_04f_a_word_that_is_not_a_subcommand_is_not_collected(self):
        self.assertEqual(commands_in("`sentinel skill file`", {"init"}), [])
        self.assertEqual(commands_in("`sentinel init --force`", {"init"}), [("init", "--force")])


class Links(unittest.TestCase):
    def test_AC_OPS_04g_every_relative_link_resolves(self):
        count = 0
        for path in [ROOT / "README.md", ROOT / "CHANGELOG.md"] + sorted((ROOT / "docs").glob("*.md")):
            if not path.exists():
                continue
            md = path.read_text(encoding="utf-8")
            plain = re.sub(r"```.*?```", "", md, flags=re.S)
            for m in re.finditer(r"!?\[[^\]]*\]\(([^)\s]+)\)", plain):
                target = m.group(1)
                if re.match(r"[a-z][a-z0-9+.-]*:", target):
                    continue
                with self.subTest(file=path.name, link=target):
                    ref, _, frag = target.partition("#")
                    dest = path if not ref else (path.parent / ref).resolve()
                    self.assertTrue(dest.exists(), f"{path.name} links to {target}")
                    if frag and dest.suffix == ".md":
                        anchors = {anchor(h) for _lv, h, _b in sections(dest.read_text(encoding="utf-8"))}
                        self.assertIn(frag, anchors, f"{path.name}: no heading {frag} in {dest.name}")
                    count += 1
        self.assertGreater(count, 15)


class Versions(unittest.TestCase):
    def test_AC_OPS_04h_old_versions_appear_only_in_the_history_files(self):
        for path in DOC_FILES + SKILL_FILES:
            rel = str(path.relative_to(ROOT))
            if rel in HISTORY:
                continue
            with self.subTest(file=rel):
                self.assertIsNone(re.search(r"0\.1\.0b7", path.read_text(encoding="utf-8")), f"{rel} names 0.1.0b7")
        for rel in HISTORY:
            self.assertTrue((ROOT / rel).exists(), rel)
        self.assertIn("0.1.0b7", read("docs/migration-1.1.md"))

    def test_AC_OPS_04h_install_pins_use_v1_1_0(self):
        pins = []
        for path in DOC_FILES + SKILL_FILES:
            if str(path.relative_to(ROOT)) in HISTORY:
                continue
            for m in re.finditer(r"@v(\d[\w.]*)", path.read_text(encoding="utf-8")):
                pins.append((path.name, m.group(1)))
        self.assertTrue(pins, "no install pin example found")
        for name, v in pins:
            self.assertEqual(v, "1.1.0", name)


class Migration(unittest.TestCase):
    def test_AC_OPS_03a_the_migration_guide_lists_each_behaviour_change(self):
        md = read("docs/migration-1.1.md")
        text = re.sub(r"\s+", " ", md).lower()
        rows = [
            ("sentinel run new creates a version 2 run unless --legacy, --tier or --adhoc", ["sentinel run new", "version 2", "--legacy", "--tier", "--adhoc"]),
            ("sentinel submit is removed (use task run and task complete)", ["sentinel submit", "removed", "task run", "task complete"]),
            ("run update and resume refuse version 2 runs", ["run update", "resume", "refuse"]),
            ("run finish on version 2 runs needs a terminal", ["run finish", "terminal"]),
            ("stage run is refused on version 2 runs", ["stage run", "refused"]),
            ("configs without auto_sync_push now mean off", ["auto_sync_push", "off"]),
            ("sync-adapters adds deny rules for approve, accept and the token file", ["sync-adapters", "deny", "approve", "accept", "server.json"]),
            ("a registry .sentinel/sentinel.db is created and 0.1 runs are indexed", [".sentinel/sentinel.db", "indexed"]),
        ]
        for change, words in rows:
            with self.subTest(change=change):
                for w in words:
                    self.assertIn(w.lower(), text, f"{change}: {w}")

    def test_AC_OPS_03a_each_change_says_what_to_do_instead(self):
        body = body_of(read("docs/migration-1.1.md"), r"what changes")
        items = [l for l in body.splitlines() if l.lstrip().startswith(("- ", "* "))]
        self.assertGreaterEqual(len(items), 8)
        for item in items:
            self.assertRegex(item, r"(?i)\b(instead|use|run|set|keep|add|ask|edit|nothing to do)\b", item)

    def test_AC_OPS_03e_the_guide_says_1_1_runs_are_not_visible_to_0_1(self):
        text = re.sub(r"\s+", " ", read("docs/migration-1.1.md"))
        self.assertIn("not visible to 0.1.0b7", text)


class InstallLimits(unittest.TestCase):
    def test_AC_OPS_04e_installation_states_that_a_git_install_has_no_dashboard_ui(self):
        text = re.sub(r"\s+", " ", read("docs/installation.md"))
        self.assertIn("uv tool install git+https://", text)
        for phrase in ("without the dashboard UI", "UI not installed", "sentinel_pipeline-1.1.0-py3-none-any.whl",
                       "uv tool install ./sentinel_pipeline-1.1.0-py3-none-any.whl", "cd dashboard && npm ci && npm run build", "uv tool install ."):
            self.assertIn(phrase, text)
        for rel in ("README.md", "docs/quickstart.md", "docs/migration-1.1.md", "docs/dashboard.md", "CHANGELOG.md"):
            with self.subTest(file=rel):
                low = re.sub(r"\s+", " ", read(rel)).lower()
                self.assertTrue("release wheel" in low or "sentinel_pipeline-1.1.0-py3-none-any.whl" in low or "uv tool install sentinel-pipeline" in low, rel)
                self.assertRegex(low, r"git install|git\+https|installation\.md#the-dashboard-ui")

    def test_AC_OPS_04e_the_operations_guide_has_a_release_checklist(self):
        body = re.sub(r"\s+", " ", body_of(read("docs/operations.md"), r"release checklist"))
        for phrase in ("npm ci && npm run build", "SENTINEL_RELEASE=1", "tools/release_gate.py", "clean checkout", "--allow-dirty",
                       "pending owner", "sentinel_pipeline-1.1.0-py3-none-any.whl", "status: done", "screen reader"):
            self.assertIn(phrase, body)

    def test_AC_OPS_04e_the_dashboard_guide_names_the_controls_the_dashboard_has(self):
        text = re.sub(r"\s+", " ", read("docs/dashboard.md"))
        self.assertIn("Cancel, resume and retry are engine transitions", text)
        self.assertIn("`resolve` is CLI only", text)
        self.assertNotIn("cancel, retry and resolve", text.lower())

    def test_AC_OPS_03a_the_run_types_in_the_docs_are_the_engines(self):
        sys.path.insert(0, str(ROOT / "sentinel" / "scripts"))
        from engine import RUN_TYPES
        for rel in ("docs/workflow.md", "docs/migration-1.1.md"):
            text = read(rel)
            for typ in RUN_TYPES:
                self.assertIn(typ, text, f"{rel} does not name run type {typ}")

    def test_AC_OPS_03a_the_guide_says_0_1_configs_keep_auto_push_on(self):
        for rel in ("docs/migration-1.1.md", "CHANGELOG.md"):
            with self.subTest(file=rel):
                text = re.sub(r"\s+", " ", read(rel)).replace("**", "")
                self.assertRegex(text, r"created by 0\.1 `sentinel init` contain `auto_sync_push: true`")
                self.assertRegex(text, r"stay(s)? on after the upgrade")
                self.assertRegex(text, r"`false`|auto_sync_push: false")
                self.assertRegex(text, r"(?i)only new 1\.1\.0 configs default to false")
        self.assertRegex(re.sub(r"\s+", " ", read("docs/migration-1.1.md")), r"Version 2 runs never auto-push")

    def test_AC_OPS_02b_the_changelog_does_not_claim_a_screen_reader_test(self):
        low = re.sub(r"\s+", " ", read("CHANGELOG.md")).lower()
        self.assertNotIn("screen reader tested", low)
        self.assertIn("manual screen-reader check not performed", low)
        self.assertIn("keyboard and automated accessibility (axe) tested", low)


class SecurityDoc(unittest.TestCase):
    def test_AC_SEC_08a_the_security_document_states_the_residual_risks(self):
        text = re.sub(r"\s+", " ", body_of(read("docs/security.md"), r"^Residual risks$")).lower()
        self.assertTrue(text, "docs/security.md has no section 'Residual risks'")
        rows = [
            ("R1 pty and token", ["r1", "same os user", "pseudo-terminal", "server.json", "approve"]),
            ("R1 deny rules advisory", ["deny rules", "advisory", "terminal check", "channel", "identity"]),
            ("R1 strong separation", ["another os user", "sandbox", "1.1.0 does not provide"]),
            ("R3", ["r3", "cannot stop a provider", "file and git effects", "does not undo"]),
            ("scrubber", ["safety net", "not a guarantee", "backups", "registry", "unscrubbed"]),
            ("audit chain", ["hash chain", "same-user", "rewrites the whole chain"]),
        ]
        for name, words in rows:
            with self.subTest(statement=name):
                for w in words:
                    self.assertIn(w, text, f"{name}: {w}")

    def test_AC_SEC_08b_the_security_document_matches_the_suite(self):
        manifest = json.loads((ROOT / "tests" / "security" / "manifest.json").read_text())
        doc = read("docs/security.md")
        low = doc.lower()
        for t in manifest["threats"]:
            if t["status"] == "not_applicable":
                continue
            with self.subTest(threat=t["threat"]):
                self.assertIn(t["threat"].lower(), low, "threat not named in docs/security.md")
        residual = [t["threat"] for t in manifest["threats"] if t["status"] == "residual"]
        named = set(re.findall(r"\bR\d+\b", body_of(doc, r"^Residual risks$")))
        self.assertTrue(named)
        for risk in sorted(named):
            with self.subTest(risk=risk):
                self.assertTrue(any(f"({risk})" in r for r in residual), f"{risk} has no check marked residual")
        for r in residual:
            m = re.search(r"\((R\d+)\)", r)
            self.assertTrue(m and m.group(1) in named, r)

    def test_AC_SEC_08c_the_old_auto_push_sentence_is_gone(self):
        text = re.sub(r"\s+", " ", read("docs/security.md"))
        self.assertNotRegex(text, r"auto_sync_push: true` \(the default\)")
        self.assertNotRegex(text, r"(?i)auto_sync_push[^.]*\bon by default")
        self.assertRegex(text, r"(?i)version 2 runs never push by themselves")
        for rel in ("docs/config.md", "docs/workflow.md"):
            self.assertNotRegex(re.sub(r"\s+", " ", read(rel)), r"auto_sync_push` \(default `true`\)|auto_sync_push` on \(the default\)", rel)


def spec_rows():
    rows = {}
    section = None
    for line in read("SPEC.md").splitlines():
        h = re.match(r"#{2,3}\s+(.*)", line)
        if h:
            section = h.group(1).strip()
        m = re.match(r"\|\s*([A-Z]+-\d+)\s*\|(.*)\|\s*$", line)
        if m:
            rows[m.group(1)] = (section, m.group(2).strip())
    return rows


LATER_G1 = {
    "VIS-07": "creating a project, adding repos and configuring without editing files",
    "DSH-02": "the create project, add repos and configure steps of the first-run wizard",
    "PRJ-03": "creating a project from the dashboard",
    "PRJ-04": "registering, editing, archiving and removing from the dashboard",
    "PRJ-05": "guided setup and advanced view",
    "REP-02": "adding a repo or cloning a remote from the dashboard",
    "REP-05": "adding, editing, removing and reordering repos from the dashboard",
    "CFG-01": "dashboard forms for settings",
    "CFG-03": "validation of a dashboard save",
    "CFG-04": "saving YAML from the dashboard",
    "CFG-05": "restore from the dashboard",
    "CFG-07": "import and export of a project config",
    "INS-08": "the directory picker",
    "PRV-01": "the providers screen",
    "PRV-02": "changing providers from the dashboard",
    "PRV-03": "the connectivity test from the dashboard",
    "AGT-08": "role assignment from the dashboard",
    "GIT-02": "publishing from the dashboard",
    "ART-02": "viewing and editing knowledge in the dashboard",
}


class SpecScope(unittest.TestCase):
    def test_AC_OPS_04i_deferred_dashboard_writes_are_marked_later_per_g1(self):
        rows = spec_rows()
        for rid, part in LATER_G1.items():
            with self.subTest(row=rid):
                self.assertIn(rid, rows)
                text = rows[rid][1]
                self.assertIn("LATER", text)
                self.assertIn("G-1", text)
                self.assertIn(part.lower(), text.lower())

    def test_AC_OPS_04j_other_scope_decisions_are_recorded(self):
        rows = spec_rows()
        wanted = {
            "MON-02": "pause and request intervention are LATER (no paused state in 1.1.0)",
            "TSK-01": "attachments and provider preference are LATER",
            "TSK-04": "LATER",
            "NOT-02": "desktop notifications use the browser Notification API only",
        }
        for rid, text in wanted.items():
            with self.subTest(row=rid):
                self.assertIn(rid, rows)
                self.assertIn(text.lower(), rows[rid][1].lower())

    def test_AC_OPS_04k_new_requirement_rows(self):
        rows = spec_rows()
        wanted = {
            "DSH-07": ("Dashboard", "MUST: every screen meets WCAG 2.1 AA, works with the keyboard alone and labels every control"),
            "SEC-09": ("Security and permissions", "MUST: content from runs, users and agents is rendered as text, never as HTML, and links in it are not followed"),
        }
        for rid, (section, text) in wanted.items():
            with self.subTest(row=rid):
                self.assertIn(rid, rows)
                self.assertIn(section.lower(), rows[rid][0].lower())
                self.assertIn(text, rows[rid][1])

    def test_AC_OPS_04l_every_must_row_is_met_or_explained(self):
        """A row is met by a scenario tag, a test named REQ_<ID>, or a LATER mark with G-1 or a decision. The names are those of the
        test functions and Playwright titles (exact family and number); tools/release_gate.py repeats the check against the names of
        the tests that passed in its run."""
        sys.path.insert(0, str(ROOT / "tools"))
        import ast
        import release_gate as gate
        names = []
        for f in (ROOT / "tests").rglob("*.py"):
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                    names.append(node.name)
        for f in list((ROOT / "dashboard" / "e2e").glob("*.ts")) + list((ROOT / "dashboard" / "tests").rglob("*.ts*")):
            names += re.findall(r"\b(?:test|it)\(\s*[`'\"]([^`'\"]+)", f.read_text(encoding="utf-8"))
        problems, used = gate.req_problems(ROOT, [{"name": n, "status": "passed"} for n in names])
        print(f"AC-OPS-04l MUST rows used: {', '.join(used)}", file=sys.stderr)
        self.assertEqual([p["id"] for p in problems], [], "MUST rows with no scenario, no REQ_ test and no LATER mark with a reference")
        self.assertGreater(len(used), 20)
        for rid in ("ARC-01", "PRJ-01", "REP-07", "PRV-04"):
            self.assertIn(f"{rid} tested", used)


if __name__ == "__main__":
    unittest.main()
