"""Phase I: one-command install from PyPI (pypi_install.feature).

The wheel is built by tools/release_gate.py (`wheel_env`) with SENTINEL_RELEASE=1 from a fresh dashboard build. PyPI is
replaced by a local wheelhouse (`--no-index --find-links`); the command line is the documented one with the distribution name.
"""
import json
import os
import re
import shutil
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

import release_gate as gate  # noqa: E402
from sv_helpers import CONFIG, Http, TtyProc, free_port  # noqa: E402

VERSION = "1.2.1"
DIST = "sentinel-pipeline"
WHEEL = f"sentinel_pipeline-{VERSION}-py3-none-any.whl"
DI = f"sentinel_pipeline-{VERSION}.dist-info"


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def flat(rel):
    return re.sub(r"\s+", " ", read(rel))


class Names(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = gate.wheel_env()
        with zipfile.ZipFile(cls.env.wheel) as z:
            cls.names = z.namelist()
            cls.meta = z.read(f"{DI}/METADATA").decode()
            cls.entry = z.read(f"{DI}/entry_points.txt").decode()

    def test_AC_OPS_06a_distribution_console_script_and_import_package_names(self):
        self.assertRegex(read("pyproject.toml"), rf'(?m)^name = "{DIST}"$')
        self.assertEqual(self.env.wheel.name, WHEEL)
        self.assertRegex(self.meta, rf"(?m)^Name: {DIST}$")
        self.assertRegex(self.meta, rf"(?m)^Version: {VERSION}$")
        self.assertEqual(re.findall(r"(?m)^(\S+) = ", self.entry.split("[console_scripts]")[1]), ["sentinel"])
        self.assertEqual({n.split("/")[0] for n in self.names} - {DI}, {"sentinel"})

    def test_AC_OPS_06b_runtime_dependencies_and_metadata_are_unchanged_by_the_rename(self):
        self.assertEqual(sorted(re.findall(r"(?m)^Requires-Dist: (.+)$", self.meta)), ["jsonschema>=4", "pyyaml>=6"])
        self.assertRegex(self.meta, r"(?m)^Requires-Python: >=3\.10$")
        self.assertRegex(self.meta, r"(?m)^License-Expression: MIT$")
        self.assertIn("Project-URL: Homepage, https://github.com/chhunlyyy/sentinel", self.meta)
        self.assertIn("Project-URL: Issues, https://github.com/chhunlyyy/sentinel/issues", self.meta)

    def test_AC_OPS_06c_the_wheel_carries_the_dashboard_build(self):
        self.assertIn("sentinel/dashboard_dist/index.html", self.names)
        self.assertTrue([n for n in self.names if n.startswith("sentinel/dashboard_dist/assets/")])
        self.assertIn("sentinel/dashboard_dist/manifest.json", self.names)
        import hashlib
        with zipfile.ZipFile(self.env.wheel) as z:
            files = json.loads(z.read("sentinel/dashboard_dist/manifest.json"))["files"]
            self.assertTrue(files)
            for rel, want in files.items():
                with self.subTest(file=rel):
                    self.assertEqual(hashlib.sha256(z.read("sentinel/dashboard_dist/" + rel)).hexdigest(), want)

    def test_AC_OPS_06d_a_release_build_with_a_missing_or_stale_dashboard_stops(self):
        with tempfile.TemporaryDirectory() as d:
            tree = Path(d) / "tree"
            gate.copy_build_tree(tree, with_dist=True)
            manifest = tree / "sentinel" / "dashboard_dist" / "manifest.json"
            m = json.loads(manifest.read_text())
            m["source_sha256"] = "0" * 64
            manifest.write_text(json.dumps(m))
            for label in ("stale", "missing"):
                with self.subTest(label=label):
                    r = gate.try_build_wheel(self.env.buildenv, tree, Path(d) / label, release=True)
                    self.assertNotEqual(r.returncode, 0)
                    self.assertIn("npm run build", r.stdout + r.stderr)
                    shutil.rmtree(tree / "sentinel" / "dashboard_dist", ignore_errors=True)

    def test_AC_OPS_06e_the_sdist_holds_what_is_needed_to_rebuild(self):
        with tempfile.TemporaryDirectory() as d:
            tree = Path(d) / "tree"
            gate.copy_build_tree(tree, with_dist=True)
            shutil.copytree(ROOT / "docs", tree / "docs")
            shutil.copy2(ROOT / "CHANGELOG.md", tree / "CHANGELOG.md")
            env = {**os.environ, "SENTINEL_RELEASE": "1"}
            r = subprocess.run([str(self.env.buildenv / "bin" / "hatchling"), "build", "-t", "sdist", "-d", str(Path(d) / "out")], cwd=tree, env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            sd = next((Path(d) / "out").glob("*.tar.gz"))
            self.assertEqual(sd.name, f"sentinel_pipeline-{VERSION}.tar.gz")
            with tarfile.open(sd) as t:
                names = [n.split("/", 1)[1] for n in t.getnames() if "/" in n]
        for want in ("sentinel/VERSION", "skills", "docs/installation.md", "README.md", "CHANGELOG.md", "LICENSE", "pyproject.toml", "hatch_build.py",
                     "sentinel/dashboard_dist/index.html", "sentinel/dashboard_dist/manifest.json"):
            with self.subTest(member=want):
                self.assertTrue(any(n == want or n.startswith(want + "/") for n in names), want)


class Quiet(TtyProc):
    def __init__(self, test, cmd, cwd, env):
        super().__init__(test, cmd, env=env, cwd=cwd)

    def url(self, timeout=20):
        import time
        end = time.time() + timeout
        while time.time() < end:
            m = re.search(r"http://127\.0\.0\.1:(\d+)/auth\?t=([0-9a-f]{64})", self.text())
            if m:
                return int(m.group(1)), m.group(2)
            if not self.pump(0.1) and self.exited():
                break
        raise AssertionError("no auth URL in output: " + self.text())


class Install(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = gate.wheel_env()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.penv = {"HOME": str(self.home), "USER": "dev", "LOGNAME": "dev", "PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}

    def check_installed(self, exe):
        r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, env=self.penv)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, VERSION), r.stderr)
        r = subprocess.run([str(exe), "--help"], capture_output=True, text=True, env=self.penv)
        self.assertEqual(r.returncode, 0)
        self.assertIn("dashboard", r.stdout)

    def test_AC_OPS_06f_installing_by_the_distribution_name_gives_the_sentinel_command(self):
        rows = []
        uv = shutil.which("uv")
        if uv:
            env = {**self.penv, "UV_TOOL_DIR": str(self.root / "uvtools"), "UV_TOOL_BIN_DIR": str(self.root / "uvbin"),
                   "UV_CACHE_DIR": str(self.root / "uvcache"), "UV_PYTHON_PREFERENCE": "system"}
            r = subprocess.run([uv, "tool", "install", "--offline", "--no-index", "--find-links", str(self.env.wheelhouse), DIST],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            rows.append(("uv tool install", self.root / "uvbin" / "sentinel"))
        venv = self.root / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
        r = subprocess.run([str(venv / "bin" / "pip"), "install", "--no-index", "--find-links", str(self.env.wheelhouse), DIST],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows.append(("pip install", venv / "bin" / "sentinel"))
        self.assertTrue(rows)
        for label, exe in rows:
            with self.subTest(install=label):
                self.check_installed(exe)

    def test_AC_OPS_06g_the_installed_command_serves_the_dashboard(self):
        ws = self.root / "ws" / "digital-hr"
        ws.mkdir(parents=True)
        (ws / "sentinel.config.yaml").write_text(yaml.safe_dump(CONFIG, sort_keys=False))
        port = free_port()
        d = Quiet(self, [str(self.env.sentinel), "dashboard", "--no-open", "--port", str(port)], ws, {**self.penv, "SENTINEL_ORCHESTRATOR": "none"})
        got, token = d.url()
        self.addCleanup(lambda: d.signal(15) if not d.exited() else None)
        self.assertEqual(got, port)
        http = Http(port, token).login()
        page = http.get("/")
        self.assertEqual(page.status, 200)
        self.assertNotIn("UI not installed", page.text)
        pkg = self.env.site_packages / "sentinel" / "dashboard_dist"
        self.assertEqual(page.body, (pkg / "index.html").read_bytes())
        assets = re.findall(r'(?:src|href)="\./(assets/[^"]+)"', page.text)
        self.assertTrue(assets)
        for a in assets:
            with self.subTest(asset=a):
                self.assertEqual(http.get("/" + a).body, (pkg / a).read_bytes())


class Docs(unittest.TestCase):
    def test_AC_OPS_06h_upgrade_and_removal_use_the_distribution_name(self):
        text = "\n".join(flat(f) for f in ("docs/installation.md", "README.md", "docs/quickstart.md"))
        for cmd in ("uv tool upgrade sentinel-pipeline", "uv tool uninstall sentinel-pipeline", "pipx upgrade sentinel-pipeline",
                    "pipx uninstall sentinel-pipeline"):
            with self.subTest(command=cmd):
                self.assertIn(cmd, text)

    def test_AC_OPS_06i_the_readme_quick_start_is_two_one_liners(self):
        text = read("README.md")
        self.assertIn("uv tool install sentinel-pipeline", text)
        self.assertIn("docker run --rm -it --init -p 127.0.0.1:8765:8765", text)
        self.assertIn("ghcr.io/chhunlyyy/sentinel", text)
        for rel in ("README.md", "docs/installation.md", "docs/quickstart.md", "docs/dashboard.md", "docs/migration-1.1.md"):
            for line in read(rel).splitlines():
                with self.subTest(file=rel, line=line[:60]):
                    self.assertIsNone(re.search(r"(uv tool|pipx|pip) (install|upgrade)(?: --force)? sentinel(?![-\w./@])", line), line)

    def test_AC_OPS_06j_a_git_install_is_documented_as_the_developer_path(self):
        text = flat("docs/installation.md")
        self.assertRegex(text, r"uv tool install git\+https://github\.com/chhunlyyy/sentinel[^.]*(without|no|not)[^.]*dashboard")
        self.assertIn("cd dashboard && npm ci && npm run build", text)
        self.assertIn("uv tool install .", text)

    def test_AC_OPS_06k_the_host_keeps_the_dashboard_port_rule(self):
        text = flat("docs/dashboard.md")
        self.assertRegex(text, r"(?i)free port")
        self.assertIn("sentinel dashboard --port 8765", text)
        self.assertIn("1024 to 65535", text)


if __name__ == "__main__":
    unittest.main()
