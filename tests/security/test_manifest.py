"""Phase H part B: the threat manifest (security_suite.feature, AC-TST-05a and AC-TST-05b).

tests/security/manifest.json maps each threat to unittest ids. This module fails when a threat has no check, a check
does not exist, or a check does not pass. Run the whole suite with:
    python3 -m unittest discover -s tests/security
"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE, HERE.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

MANIFEST = HERE / "manifest.json"
REQUIRED = [
    "wrong Host (DNS rebinding)", "wrong Origin", "missing session cookie", "missing or wrong CSRF value",
    "token left in the URL after /auth", "path traversal in artifact, log and static routes",
    "path traversal in notification and backup arguments", "oversized body", "non-TTY approval and acceptance",
    "stale-hash approval", "agent environment holds the token or secrets", "secrets in logs, evidence, reports and bundles",
    "secrets in prompts and task files", "untrusted content rendered as HTML (XSS)",
    "approval forgery by a same-user agent (R1)", "commands run by a provider during a task (R3)",
]
_cache = {}


def load(check):
    """The test for a unittest id, or None when it does not exist."""
    suite = unittest.defaultTestLoader.loadTestsFromName(check)
    tests = list(_flatten(suite))
    if len(tests) != 1 or type(tests[0]).__name__ == "_FailedTest":
        return None
    return tests[0]


def _flatten(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _flatten(t)
        else:
            yield t


def passes(check):
    if check not in _cache:
        test = load(check)
        result = unittest.TestResult()
        unittest.TestSuite([test]).run(result)  # a suite runs setUpClass
        _cache[check] = result.wasSuccessful() and not result.skipped
    return _cache[check]


def problems(manifest, threats=None, run=True):
    """What is wrong with a manifest: a list of 'threat: reason' strings."""
    found = []
    entries = {t["threat"]: t for t in manifest.get("threats", [])}
    for name in threats if threats is not None else entries:
        entry = entries.get(name)
        if not entry or not entry.get("checks"):
            found.append(f"{name}: no check listed")
            continue
        if entry.get("status") not in ("blocking", "residual"):
            found.append(f"{name}: status must be blocking or residual")
        for check in entry["checks"]:
            if load(check) is None:
                found.append(f"{name}: check {check} does not exist")
            elif run and not passes(check):
                found.append(f"{name}: check {check} does not pass (or was skipped)")
    return found


class Manifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text())

    def test_AC_TST_05a_every_threat_has_at_least_one_passing_check(self):
        for threat in REQUIRED:
            with self.subTest(threat=threat):
                self.assertEqual(problems(self.manifest, [threat]), [])

    def test_AC_TST_05a_no_unknown_threat_and_no_duplicate(self):
        names = [t["threat"] for t in self.manifest["threats"]]
        self.assertEqual(sorted(names), sorted(REQUIRED))

    def test_AC_TST_05b_a_threat_without_a_check_fails_the_suite(self):
        empty = {"threats": [{"threat": "x", "status": "blocking", "checks": []}]}
        self.assertEqual(problems(empty, run=False), ["x: no check listed"])
        missing = {"threats": [{"threat": "y", "status": "blocking", "checks": ["test_threats.Nope.test_nothing"]}]}
        self.assertIn("y: check test_threats.Nope.test_nothing does not exist", problems(missing, run=False))
        self.assertEqual(problems({"threats": []}, ["z"], run=False), ["z: no check listed"])


if __name__ == "__main__":
    unittest.main()
