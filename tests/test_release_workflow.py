"""Phase I: the tag-triggered release workflow (release_automation.feature). Structure only; the workflow is never run here."""
import re
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import release_gate as gate  # noqa: E402

PATH = ROOT / ".github" / "workflows" / "release.yml"
TEXT = PATH.read_text(encoding="utf-8")
WF = yaml.safe_load(TEXT)
ON = WF.get("on", WF.get(True))  # PyYAML reads the bare key `on` as True
JOBS = WF["jobs"]


def steps(job):
    return JOBS[job]["steps"]


def runs(job):
    return "\n".join(s.get("run", "") for s in steps(job))


def uses(job):
    return [s["uses"] for s in steps(job) if "uses" in s]


def needs(job, seen=None):
    """Every job `job` waits for, directly or not."""
    out = set()
    n = JOBS[job].get("needs", [])
    for d in [n] if isinstance(n, str) else n:
        out |= {d} | needs(d)
    return out


class Workflow(unittest.TestCase):
    def test_AC_OPS_08a_only_a_version_tag_triggers_it(self):
        self.assertEqual(ON, {"push": {"tags": ["v*"]}})
        self.assertEqual(WF["permissions"], {"contents": "read"})

    def test_AC_OPS_08b_the_gate_runs_first_and_the_publish_jobs_depend_on_it(self):
        cmds = [l.strip() for l in runs("gate").splitlines()]
        self.assertIn("python tools/release_gate.py", cmds)
        self.assertNotRegex(runs("gate"), r"--allow-dirty|--skip-")
        for job in ("build", "publish-pypi", "publish-image"):
            with self.subTest(job=job):
                self.assertIn("gate", needs(job))
        self.assertEqual(needs("gate"), set())

    def test_AC_OPS_08c_a_pending_manual_check_fails_the_workflow_clearly(self):
        text = runs("gate")
        self.assertIn("release-evidence.json", text)
        self.assertIn("release_ready", text)
        self.assertIn("pending_owner", text)
        self.assertIn("sys.exit(1)", text)
        self.assertLess(text.index("tools/release_gate.py"), text.index("release_ready"))

    def test_AC_OPS_08d_the_tag_must_equal_the_version(self):
        text = runs("gate")
        self.assertIn("sentinel/VERSION", text)
        self.assertIn('"${GITHUB_REF_NAME}" != "v${version}"', text)
        self.assertIn("exit 1", text)

    def test_AC_OPS_08e_the_wheel_and_sdist_are_built_once_from_the_tested_tree(self):
        text = runs("build")
        self.assertLess(text.index("npm ci"), text.index("npm run build"))
        self.assertRegex(text, r"SENTINEL_RELEASE=1 python -m hatchling build -t sdist -t wheel")
        self.assertTrue(any(u.startswith("actions/upload-artifact@") for u in uses("build")))
        pypi = runs("publish-pypi")
        self.assertNotRegex(pypi, r"hatchling|pip install|python -m build|npm ")
        self.assertTrue(any(u.startswith("actions/download-artifact@") for u in uses("publish-pypi")))

    def test_AC_OPS_08f_trusted_publishing_with_the_narrowest_permissions(self):
        job = JOBS["publish-pypi"]
        pub = [s for s in job["steps"] if s.get("uses", "").startswith("pypa/gh-action-pypi-publish@")]
        self.assertEqual(len(pub), 1)
        self.assertEqual(set(pub[0].get("with", {})) - {"packages-dir"}, set())
        self.assertNotRegex(TEXT, r"(?i)pypi_api_token|pypi-token|PYPI_PASSWORD|secrets\.PYPI")
        self.assertEqual(job["permissions"]["id-token"], "write")
        self.assertEqual(job["environment"], "pypi")
        for name, j in JOBS.items():
            if name != "publish-pypi":
                self.assertNotIn("id-token", j.get("permissions", {}), name)

    def test_AC_OPS_08g_the_image_is_built_and_pushed_with_both_tags(self):
        names = {u.split("@")[0] for u in uses("publish-image")}
        self.assertTrue({"docker/build-push-action", "docker/login-action"} <= names)
        login = next(s for s in steps("publish-image") if s.get("uses", "").startswith("docker/login-action@"))
        self.assertEqual(login["with"]["registry"], "ghcr.io")
        self.assertEqual(login["with"]["password"], "${{ secrets.GITHUB_TOKEN }}")
        self.assertEqual(WF["env"]["IMAGE"], "ghcr.io/chhunlyyy/sentinel")
        text = runs("publish-image")
        self.assertIn('${IMAGE}:${version}', text)
        self.assertIn('${IMAGE}:latest', text)
        build = next(s for s in steps("publish-image") if s.get("uses", "").startswith("docker/build-push-action@"))
        self.assertIs(build["with"]["push"], True)
        for name, j in JOBS.items():
            self.assertEqual("packages" in j.get("permissions", {}), name == "publish-image", name)
        self.assertEqual(JOBS["publish-image"]["permissions"]["packages"], "write")

    def test_AC_OPS_08h_actions_are_pinned(self):
        found = re.findall(r"(?m)^\s*-?\s*uses:\s*(\S+)", TEXT)
        self.assertGreaterEqual(len(found), 10)
        for u in found:
            with self.subTest(uses=u):
                ref = u.split("@", 1)[1]
                self.assertTrue(re.fullmatch(r"v\d+\.\d+\.\d+|[0-9a-f]{40}", ref), u)
        self.assertNotRegex(TEXT, r"(?i)echo[^\n]*\$\{\{\s*secrets\.")
        self.assertNotRegex(TEXT, r"(?m)^\s*run:[^\n]*\$\{\{\s*secrets\.")

    def test_AC_OPS_08i_the_repository_settings_are_documented(self):
        text = re.sub(r"\s+", " ", (ROOT / "docs" / "operations.md").read_text())
        for phrase in ("Release workflow and repository settings", "trusted publisher", "sentinel-pipeline", "release.yml", "environment `pypi`",
                       "Workflow permissions", "packages", "public", "ghcr.io/chhunlyyy/sentinel"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        body = (ROOT / "docs" / "operations.md").read_text().split("## Release checklist", 1)[1]
        for phrase in ("git tag", "manual checks"):
            self.assertIn(phrase, body)

    def test_review_the_gate_job_installs_what_the_gate_imports(self):
        text = runs("gate")
        self.assertIn('python -m pip install "pyyaml>=6" "jsonschema>=4"', text)
        # AC-OPS-01j installs the wheel as a uv tool: the runner has no uv unless the gate job installs it
        self.assertRegex(text, r'pip install [^\n]*"uv>=')
        self.assertIn("npx playwright install --with-deps chromium", text)
        self.assertNotIn("install-deps", text)
        self.assertLess(text.index("pip install"), text.index("tools/release_gate.py"))
        self.assertLess(text.index("playwright install"), text.index("tools/release_gate.py"))

    def test_review_checkouts_keep_no_credentials(self):
        for name in JOBS:
            for s in steps(name):
                if s.get("uses", "").startswith("actions/checkout@"):
                    with self.subTest(job=name):
                        self.assertIs(s.get("with", {}).get("persist-credentials"), False)

    def test_review_one_release_run_per_ref(self):
        self.assertEqual(WF["concurrency"]["group"], "release-${{ github.ref }}")
        self.assertIs(WF["concurrency"]["cancel-in-progress"], False)

    def test_review_node_is_the_same_exact_version_everywhere(self):
        nvm = (ROOT / "dashboard" / ".nvmrc").read_text().strip()
        self.assertRegex(nvm, r"^22\.\d+\.\d+$")
        wanted = [s["with"]["node-version"] for j in JOBS for s in steps(j) if s.get("uses", "").startswith("actions/setup-node@")]
        self.assertGreaterEqual(len(wanted), 2)
        self.assertEqual(set(wanted), {nvm})
        self.assertIn(f"FROM node:{nvm}-slim ", (ROOT / "Dockerfile").read_text())

    def test_AC_OPS_08j_the_release_gate_covers_phase_i(self):
        self.assertIn("phaseI", gate.PHASES)
        status = (ROOT / "IMPLEMENTATION_STATUS.md").read_text()
        recorded = gate.recorded_hashes(status)
        self.assertEqual(recorded["phaseI"], gate.set_hash(ROOT / "plan" / "v1.1" / "phaseI" / "features"))
        import json
        pinned = json.loads((ROOT / "tests" / "release" / "phase_hashes.json").read_text())
        self.assertEqual(pinned["phaseI"], recorded["phaseI"])
        self.assertEqual(gate.phase_hash_problems(ROOT), [])


if __name__ == "__main__":
    unittest.main()
