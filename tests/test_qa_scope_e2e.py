"""The end-to-end QA task writes its checks into cache/qa/tests/current/<slug>, the folder that also holds QA-Red's per-cycle
script folders (MEF-HR 2026-11-24: every QA run failed E_SCOPE for doing what its stage asked)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from qa_cycles import QaCycleOps  # noqa: E402


class QaWritesItsChecks(unittest.TestCase):
    def violations(self, role, changed, cycle_id=None):
        ops = mock.MagicMock()
        ops._scripts_rel.return_value = ".sentinel/cache/qa/tests/current/s"
        ops.live_cycles.return_value = [{"id": "c-ok", "red_method": "qa_scenario", "approved_scripts": "[]x"},
                                        {"id": "c-new", "red_method": "qa_scenario", "approved_scripts": None}]
        ops.cycle_rows.return_value = [{"id": "c-ok"}, {"id": "c-new"}, {"id": "c-file"}]
        was = {}
        now = {n: "sha" for n in changed}
        return QaCycleOps._qa_tree_violations(ops, {"slug": "s"}, {"role": role, "cycle_id": cycle_id}, was, now)

    def test_qa_may_write_its_checks_outside_the_cycle_folders(self):
        self.assertEqual(self.violations("qa", ["playwright.config.ts", "e2e/flow.spec.ts", "test-results/.last-run.json"]), [])

    def test_qa_may_not_touch_a_cycle_folder(self):
        got = self.violations("qa", ["c-ok/a.spec.ts", "c-new/b.spec.ts"])
        self.assertEqual([k for k, _ in got], ["outside_write_scope", "approved_test_changed"])

    def test_other_roles_still_may_not_write_there(self):
        self.assertEqual([k for k, _ in self.violations("tdd_green", ["playwright.config.ts"])], ["outside_write_scope"])
        self.assertEqual(self.violations("qa_red", ["c-new/b.spec.ts"], cycle_id="c-new"), [])


if __name__ == "__main__":
    unittest.main()
