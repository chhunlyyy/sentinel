"""Phase H part C: version 1.1.0, changelog, wheel contents, offline install and upgrade of a 0.1.0b7 workspace
(release.feature, Rules "Version and changelog", "Wheel contents and offline install", "Upgrading a 0.1 workspace").

The wheel is built once per run by tools/release_gate.py (`wheel_env`): in a throwaway virtual environment, with
SENTINEL_RELEASE=1, from the checkout; then installed offline from a wheelhouse into a second environment.
Set SENTINEL_WHEEL_ENV to a folder that `release_gate.py wheel-env <folder>` made to reuse it.
"""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "sentinel" / "scripts"))

import release_gate as gate  # noqa: E402
from sv_helpers import CONFIG, Http, TtyProc  # noqa: E402

VERSION = "1.2.0"
FIXTURE = ROOT / "tests" / "fixtures" / "ws-0.1.0b7.tar.gz"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def wheel_names(env):
    with zipfile.ZipFile(env.wheel) as z:
        return z.namelist()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Version(unittest.TestCase):
    def test_AC_OPS_02a_the_version_is_1_1_0_in_the_source(self):
        self.assertEqual((ROOT / "sentinel" / "VERSION").read_text().strip(), VERSION)
        r = subprocess.run([sys.executable, str(ROOT / "sentinel" / "scripts" / "sentinel.py"), "--version"], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, VERSION), r.stderr)
        self.assertIn("Development Status :: 4 - Beta", (ROOT / "pyproject.toml").read_text())
        self.assertEqual(json.loads((ROOT / "dashboard" / "package.json").read_text())["version"], VERSION)


class Changelog(unittest.TestCase):
    def test_AC_OPS_02b_the_changelog_has_a_1_1_0_entry(self):
        text = (ROOT / "CHANGELOG.md").read_text()
        m = re.search(r"^## 1\.1\.0\b.*?(?=^## |\Z)", text, re.S | re.M)
        self.assertIsNotNone(m, "no '## 1.1.0' heading")
        entry = m.group(0)
        for section in ("Added", "Changed", "Removed", "Security"):
            self.assertRegex(entry, rf"(?m)^### {section}\s*$", section)
        low = re.sub(r"\s+", " ", entry).lower()
        for item in ("version 2 runs with two approvals", "tdd cycles and independent verification", "local dashboard and api",
                     "notifications, stats, audit export, backup", "sentinel submit removed", "auto_sync_push off when not set",
                     "residual risks r1 and r3", "docs/migration-1.1.md"):
            with self.subTest(item=item):
                self.assertIn(item, low)
        self.assertRegex(entry, r"\]\(docs/migration-1\.1\.md\)")


class Wheel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = gate.wheel_env()

    def test_AC_OPS_02a_the_wheel_is_named_and_labelled_1_1_0(self):
        self.assertEqual(self.env.wheel.name, f"sentinel_pipeline-{VERSION}-py3-none-any.whl")
        with zipfile.ZipFile(self.env.wheel) as z:
            meta = z.read(f"sentinel_pipeline-{VERSION}.dist-info/METADATA").decode()
        self.assertRegex(meta, rf"(?m)^Version: {re.escape(VERSION)}$")

    def test_AC_OPS_01g_the_wheel_holds_every_runtime_file(self):
        names = set(wheel_names(self.env))
        dist = ROOT / "sentinel" / "dashboard_dist"
        manifest = json.loads((dist / "manifest.json").read_text())
        rows = {
            "dashboard build": ["sentinel/dashboard_dist/index.html", "sentinel/dashboard_dist/manifest.json"] + [f"sentinel/dashboard_dist/{f}" for f in manifest["files"]],
            "registry migrations": [f"sentinel/scripts/migrations/{p.name}" for p in (ROOT / "sentinel/scripts/migrations").glob("*.sql")],
            "schemas": [f"sentinel/core/schema/{p.name}" for p in (ROOT / "sentinel/core/schema").glob("*.json")],
            "user.db schema (created by the notifications module)": ["sentinel/scripts/notifications.py"],
            "profiles": [f"sentinel/profiles/{p.name}" for p in (ROOT / "sentinel/profiles").glob("*.json")],
            "templates": [f"sentinel/templates/{p.relative_to(ROOT / 'sentinel/templates')}" for p in (ROOT / "sentinel/templates").rglob("*") if p.is_file() and "__pycache__" not in p.parts],
            "skills": [f"sentinel/skills/{p.relative_to(ROOT / 'skills')}" for p in (ROOT / "skills").rglob("*") if p.is_file()],
        }
        for name, files in rows.items():
            with self.subTest(files=name):
                self.assertTrue(files, name)
                self.assertEqual([f for f in files if f not in names], [])

    def test_AC_OPS_01h_the_wheel_holds_nothing_it_should_not(self):
        bad = re.compile(r"(^|/)(tests|plan|node_modules|__pycache__)/|^dashboard/|\.map$|(^|/)\.env($|\.)|\.pyc$")
        self.assertEqual([n for n in wheel_names(self.env) if bad.search(n)], [])
        self.assertTrue(all(n.startswith(("sentinel/", f"sentinel_pipeline-{VERSION}.dist-info/")) for n in wheel_names(self.env)))

    def test_AC_OPS_01k_runtime_dependencies_are_unchanged(self):
        with zipfile.ZipFile(self.env.wheel) as z:
            meta = z.read(f"sentinel_pipeline-{VERSION}.dist-info/METADATA").decode()
        reqs = sorted(re.findall(r"(?m)^Requires-Dist: (.+)$", meta))
        self.assertEqual(reqs, ["jsonschema>=4", "pyyaml>=6"])
        self.assertRegex(meta, r"(?m)^Requires-Python: >=3\.10$")

    def test_AC_OPS_01c_a_wheel_without_built_assets_serves_the_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            tree = Path(d) / "tree"
            gate.copy_build_tree(tree, with_dist=False)
            wheel = gate.build_wheel(self.env.buildenv, tree, Path(d) / "out", release=False)
            with zipfile.ZipFile(wheel) as z:
                self.assertEqual([n for n in z.namelist() if "dashboard_dist" in n], [])
                z.extractall(Path(d) / "unpacked")
            probe = (
                "import sys, tempfile, json\n"
                f"sys.path.insert(0, {str(Path(d) / 'unpacked' / 'sentinel' / 'scripts')!r})\n"
                "from apiserver.server import ApiServer\n"
                "from pathlib import Path\n"
                "import http.client\n"
                "cfg = Path(tempfile.mkdtemp()) / 'cfg'\n"
                "s = ApiServer(cfg, port=0, user='dev', git_name='Dev', dispatch=False)\n"
                "s.start()\n"
                "try:\n"
                "    c = http.client.HTTPConnection('127.0.0.1', s.port)\n"
                "    c.request('GET', f'/auth?t={s.token}', headers={'Host': f'127.0.0.1:{s.port}'})\n"
                "    r = c.getresponse(); r.read()\n"
                "    cookie = r.getheader('set-cookie').split(';')[0]\n"
                "    c = http.client.HTTPConnection('127.0.0.1', s.port)\n"
                "    c.request('GET', '/', headers={'Host': f'127.0.0.1:{s.port}', 'Cookie': cookie})\n"
                "    r = c.getresponse(); print(r.status, 'UI not installed' in r.read().decode())\n"
                "finally:\n"
                "    s.stop()\n"
            )
            r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env={**os.environ, "HOME": d, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(r.stdout.strip(), "200 True", r.stdout + r.stderr)

    def test_AC_OPS_01e_a_release_build_refuses_stale_or_missing_assets(self):
        with tempfile.TemporaryDirectory() as d:
            tree = Path(d) / "tree"
            gate.copy_build_tree(tree, with_dist=True)
            manifest = tree / "sentinel" / "dashboard_dist" / "manifest.json"
            m = json.loads(manifest.read_text())
            m["source_sha256"] = "0" * 64
            manifest.write_text(json.dumps(m))
            r = gate.try_build_wheel(self.env.buildenv, tree, Path(d) / "out", release=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("npm run build", r.stdout + r.stderr)
            shutil.rmtree(tree / "sentinel" / "dashboard_dist")
            r = gate.try_build_wheel(self.env.buildenv, tree, Path(d) / "out2", release=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("npm run build", r.stdout + r.stderr)

    def test_AC_OPS_01e_a_matching_manifest_builds(self):
        with tempfile.TemporaryDirectory() as d:
            tree = Path(d) / "tree"
            gate.copy_build_tree(tree, with_dist=True)
            r = gate.try_build_wheel(self.env.buildenv, tree, Path(d) / "out", release=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class InstalledDash(TtyProc):
    def __init__(self, test, exe, cwd, env):
        super().__init__(test, [exe, "dashboard", "--no-open"], env=env, cwd=cwd)

    def url(self, timeout=20):
        end = __import__("time").time() + timeout
        while __import__("time").time() < end:
            m = re.search(r"http://127\.0\.0\.1:(\d+)/auth\?t=([0-9a-f]{64})", self.text())
            if m:
                return int(m.group(1)), m.group(2)
            if not self.pump(0.1) and self.exited():
                break
        raise AssertionError("no auth URL in output: " + self.text())


class Installed(unittest.TestCase):
    """The wheel installed offline into a fresh virtual environment."""

    @classmethod
    def setUpClass(cls):
        cls.env = gate.wheel_env()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "git").symlink_to(shutil.which("git"))
        self.ws = self.root / "ws" / "digital-hr"
        self.ws.mkdir(parents=True)
        (self.ws / "sentinel.config.yaml").write_text(yaml.safe_dump(CONFIG, sort_keys=False))
        self.proc_env = {"HOME": str(self.home), "USER": "dev", "LOGNAME": "dev", "PATH": str(self.bin), "PYTHONDONTWRITEBYTECODE": "1", **GIT_ENV}

    def start(self):
        d = InstalledDash(self, str(self.env.sentinel), self.ws, self.proc_env)
        port, token = d.url()
        self.addCleanup(lambda: d.signal(15) if not d.exited() else None)
        return d, Http(port, token).login()

    def test_AC_OPS_01i_offline_install_runs_version_selftest_and_dashboard(self):
        self.assertNotIn("node", [p.name for p in self.bin.iterdir()])
        self.assertIsNone(shutil.which("node", path=str(self.bin)))
        r = subprocess.run([str(self.env.sentinel), "--version"], capture_output=True, text=True, env=self.proc_env)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, VERSION), r.stderr)
        # the install itself came from the wheelhouse with --no-index (inside a network namespace where allowed)
        self.assertTrue(self.env.offline_install_log.exists())
        log = self.env.offline_install_log.read_text()
        self.assertIn("--no-index", log)
        self.assertRegex(log, r"(?m)^installer: (uv tool install|pip)")
        r = subprocess.run([str(self.env.sentinel), "selftest"], capture_output=True, text=True, env={**self.proc_env, "PATH": os.environ["PATH"]}, timeout=900)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-800:])
        self.assertRegex(r.stdout, r"\d+ passed, 0 failed")
        d, http = self.start()
        page = http.get("/")
        self.assertEqual(page.status, 200)
        self.assertIn('<div id="root">', page.text)
        # the install must have run with only loopback: assert it when the machine allows a namespace, else record it as manual
        if not json.loads((self.env.base / "ready.json").read_text()).get("namespace"):
            self.skipTest("pending owner run on a machine that allows user namespaces (no CI exists): the offline install could not run in a "
                          "loopback-only network namespace here; AC-OPS-01i is listed in tests/release/manual.json")
        self.assertIn("network namespace: yes", log)

    def test_AC_OPS_01b_the_installed_wheel_serves_the_dashboard_without_node(self):
        if shutil.which("uv"):  # the documented install is `uv tool install`; pip is only the fallback where uv cannot install offline
            self.assertEqual(self.env.installer, "uv tool install", "uv is installed but the offline wheelhouse install used " + self.env.installer)
        d, http = self.start()
        pkg = self.env.site_packages / "sentinel" / "dashboard_dist"
        page = http.get("/")
        self.assertEqual(page.status, 200)
        self.assertEqual(page.body, (pkg / "index.html").read_bytes())
        assets = re.findall(r'(?:src|href)="\./(assets/[^"]+)"', page.text)
        self.assertGreaterEqual(len(assets), 2)
        for a in assets:
            with self.subTest(asset=a):
                r = http.get("/" + a)
                self.assertEqual(r.status, 200)
                self.assertEqual(r.body, (pkg / a).read_bytes())
        self.assertEqual(http.get("/api/v1/installation").status, 200)

    def test_AC_OPS_02a_the_installation_route_answers_1_1_0(self):
        d, http = self.start()
        r = http.get("/api/v1/installation")
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json["version"], VERSION)

    def test_AC_OPS_01f_static_files_come_only_from_the_package_folder(self):
        d, http = self.start()
        self.assertEqual(http.get("/assets/index-x.js").status, 404)
        for path in ("/assets/../../server.json", "/assets/%2e%2e/VERSION", "/assets/no-such-file.js", "/assets/..%2f..%2fVERSION", "/assets/%2e%2e%2f%2e%2e%2fserver.json"):
            with self.subTest(path=path):
                r = http.get(path)
                self.assertEqual(r.status, 404, r.text[:200])
                self.assertNotIn(VERSION, r.text)

    def test_AC_OPS_01j_uv_tool_install_from_the_wheel(self):
        uv = shutil.which("uv")
        self.assertIsNotNone(uv, "uv is not installed (install it with `pip install uv`; the release workflow does)")
        env = {**os.environ, "HOME": str(self.home), "UV_CACHE_DIR": str(self.root / "uvcache"), "UV_TOOL_DIR": str(self.root / "uvtools"),
               "UV_TOOL_BIN_DIR": str(self.root / "uvbin"), "UV_PYTHON_PREFERENCE": "system"}
        # fill the cache (needs the network once), then install again with UV_OFFLINE=1
        r = subprocess.run([uv, "tool", "install", str(self.env.wheel)], capture_output=True, text=True, env=env, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        subprocess.run([uv, "tool", "uninstall", "sentinel-pipeline"], capture_output=True, text=True, env=env)
        shutil.rmtree(self.root / "uvtools", ignore_errors=True)
        r = subprocess.run([uv, "tool", "install", str(self.env.wheel)], capture_output=True, text=True, env={**env, "UV_OFFLINE": "1"}, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([str(self.root / "uvbin" / "sentinel"), "--version"], capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, VERSION), r.stderr)


class Upgrade(unittest.TestCase):
    CLI = [sys.executable, str(ROOT / "sentinel" / "scripts" / "sentinel.py")]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        with tarfile.open(FIXTURE) as t:
            t.extractall(self.root / "fx", filter="data")
        self.ws = self.root / "fx" / "ws"
        self.expected = json.loads((ROOT / "tests" / "fixtures" / "ws-0.1.0b7.expected.json").read_text())
        self.env = {**os.environ, **GIT_ENV, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}

    def cli(self, *args, tty=False):
        r = subprocess.run(self.CLI + ["--dir", str(self.ws), *args], capture_output=True, text=True, env=self.env, cwd=self.ws, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout, r.stderr

    def legacy_hashes(self):
        files = sorted(p for p in (self.ws / ".sentinel" / "runs").rglob("*") if p.is_file() and p.relative_to(self.ws / ".sentinel" / "runs").parts[0] in ("old-open", "old-done")) + [self.ws / "sentinel.config.yaml"]
        return {str(p.relative_to(self.ws)): sha(p) for p in files}

    def test_AC_OPS_03b_a_0_1_0b7_workspace_keeps_working(self):
        before = self.legacy_hashes()
        self.assertTrue(any("old-open" in k for k in before) and any("old-done" in k for k in before))
        self.assertFalse((self.ws / ".sentinel" / "sentinel.db").exists())
        code, out, err = self.cli("doctor")
        self.assertEqual(code, 0, out + err)
        notes = [l for l in out.splitlines() if l.startswith("note: optional settings not set")]
        self.assertEqual(len(notes), 1, out)
        for setting in ("policies", "providers", "agents", "tdd", "verification", "notifications"):
            self.assertIn(f"`{setting}`", notes[0], f"doctor does not list the optional setting {setting}")
        import health
        have = {k: {} for k in ("policies", "providers", "agents", "tdd", "verification", "notifications")}
        self.assertEqual(health.optional_setting_notes(have), [])
        partial = health.optional_setting_notes({"policies": {}})
        self.assertEqual(len(partial), 1)
        self.assertNotIn("`policies`", partial[0])
        self.assertIn("`providers`", partial[0])
        code, out, err = self.cli("stats")
        self.assertEqual(code, 0, err)
        stats = json.loads(out)
        self.assertEqual(stats["runs"], 2)
        code, out, err = self.cli("resume", "old-open")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), self.expected["resume_old_open"])
        self.assertEqual(self.legacy_hashes(), before)
        db = sqlite3.connect(self.ws / ".sentinel" / "sentinel.db")
        self.addCleanup(db.close)
        rows = dict(db.execute("SELECT slug, workflow_version FROM runs").fetchall())
        self.assertEqual(rows, {"old-open": "0.1", "old-done": "0.1"})

    def test_AC_OPS_03d_a_new_version_2_run_in_an_upgraded_workspace(self):
        before = self.legacy_hashes()
        code, out, err = self.cli("run", "new", "new-feature", "--type", "feature")
        self.assertEqual(code, 0, out + err)
        code, out, err = self.cli("next", "new-feature", "--json")
        self.assertEqual(code, 0, out + err)
        nxt = json.loads(out)
        self.assertIn("triage", json.dumps(nxt).lower())
        self.assertEqual(self.legacy_hashes(), before)
        db = sqlite3.connect(self.ws / ".sentinel" / "sentinel.db")
        self.addCleanup(db.close)
        self.assertEqual(db.execute("SELECT workflow_version FROM runs WHERE slug='new-feature'").fetchone()[0], "2")

    def test_AC_OPS_03c_a_pre_release_registry_is_backed_up_before_it_is_migrated(self):
        from registry import Registry, _load_file_migrations
        migs = sorted(_load_file_migrations())
        state = self.root / "state"
        reg = Registry.open(state, migs[:3])
        reg.insert_run({"slug": "dev-run", "state": "CREATED"})
        reg.close()
        reg = Registry.open(state)
        self.addCleanup(reg.close)
        self.assertEqual(reg.schema_version(), Registry.LATEST)
        bak = state / "sentinel.db.bak-3"
        self.assertTrue(bak.exists())
        old = sqlite3.connect(bak)
        self.addCleanup(old.close)
        self.assertEqual(old.execute("SELECT slug FROM runs").fetchall(), [("dev-run",)])
        self.assertIsNotNone(reg.get_run("dev-run"))

    def test_AC_OPS_03e_zero_one_zero_b7_never_reads_the_registry(self):
        """Downgrading: 0.1.0b7 keeps working on state.json (its code never opens sentinel.db)."""
        self.cli("resume", "old-open")
        self.assertTrue((self.ws / ".sentinel" / "sentinel.db").exists())
        b7 = gate.legacy_cli(self.root / "b7")
        r = subprocess.run([sys.executable, str(b7), "--dir", str(self.ws), "resume", "old-open"], capture_output=True, text=True, env=self.env, cwd=self.ws)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), self.expected["resume_old_open"])
        self.assertIn("not visible to 0.1.0b7", re.sub(r"\s+", " ", (ROOT / "docs" / "migration-1.1.md").read_text()))


if __name__ == "__main__":
    unittest.main()
