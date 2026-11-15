"""Phase D x Phase F merge: the dashboard run controls honour the cycle rules of the TDD tasks, and the registry
migrates databases that were created before 0008 existed."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from pd_helpers import PDX, SLUG, TEST_FILE  # noqa: E402
from sv_helpers import SV  # noqa: E402
from test_phase_d_review import EXTRA_TEST, green_body  # noqa: E402


class CycleControls(PDX, SV):
    def setUp(self):
        super().setUp()
        self.url = f"/api/v1/tasks/{SLUG}/control"

    def boot_api(self, **kw):
        self.boot_x(**kw)
        self.prepare()
        self.serve()

    def ctl(self, action, tid, **more):
        return self.http.post(self.url, {"action": action, "task_id": tid, **more})

    def fail(self, tid, code="E_EXIT", state="FAILED"):
        self.sql("UPDATE tasks SET state=?, error_code=? WHERE id=?", (state, code, tid))

    def test_a_retry_of_a_failed_red_goes_through_retry_cycle_task(self):
        self.boot_api()
        rid = self.tid("tdd_red")
        self.set_cycle("Remaining", state="RED_RUNNING")
        self.fail(rid)
        r = self.ctl("retry", rid)
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(self.cstate("Remaining"), "PLANNED")
        new = self.cycle("Remaining")["red_task"]
        self.assertNotEqual(new, rid)
        self.assertEqual((self.task(new)["retry_of"], self.task(new)["attempt"]), (rid, 2))
        self.assertTrue([a for a in self.audit_rows() if a["action"] == "cycle_task_retried"])

    def test_b_retry_of_a_cancelled_red_of_a_rejected_cycle_is_refused(self):
        self.boot_api()
        rid = self.tid("tdd_red")
        self.fail(rid, code=None, state="CANCELLED")
        self.set_cycle("Remaining", state="REJECTED")
        r = self.ctl("retry", rid)
        self.assertEqual(r.status, 422, r.text)
        self.assertEqual(r.json["error"]["code"], "E_PRECONDITION")
        self.assertEqual(len(self.tdd_tasks("tdd_red", "Remaining")), 1)

    def test_c_retry_over_the_cap_is_refused(self):
        self.boot_api(tdd={"red_retries": 0})
        rid = self.tid("tdd_red")
        self.set_cycle("Remaining", state="RED_RUNNING")
        self.sql("UPDATE tasks SET attempt=3, max_retries=NULL WHERE id=?", (rid,))
        self.fail(rid)
        r = self.ctl("retry", rid)
        self.assertEqual(r.status, 422, r.text)
        self.assertEqual(r.json["error"]["code"], "E_PRECONDITION")
        self.assertIn("cap", r.json["error"]["message"])
        self.assertEqual(len(self.tdd_tasks("tdd_red", "Remaining")), 1)

    def test_d_retry_after_a_scope_violation_lists_unreverted_paths(self):
        gid = self.to_red_verified()
        self.serve()
        self.agent_exec("tdd_green", green_body(f"write({EXTRA_TEST!r}, 'x')"))
        self.assertEqual(self.eng.run_task(gid)["exit"], 3)
        r = self.ctl("retry", gid)
        self.assertEqual(r.status, 422, r.text)
        self.assertEqual(r.json["error"]["code"], "E_PRECONDITION")
        self.assertIn(EXTRA_TEST, r.json["error"]["message"])
        self.assertEqual(len(self.tdd_tasks("tdd_green", "Remaining")), 1)
        (self.ws / EXTRA_TEST).unlink()
        r = self.ctl("retry", gid)
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(self.task(self.cycle("Remaining")["green_task"])["attempt"], 2)

    def test_e_cancel_of_a_running_green_moves_the_cycle_to_red_verified(self):
        gid = self.to_red_verified()
        self.serve()
        self.set_cycle("Remaining", state="GREEN_RUNNING")
        self.mark_running(gid)
        moves = lambda: len([e for e in self.cycle_events("Remaining") if e["payload"]["to"] == "RED_VERIFIED"])  # noqa: E731
        before = moves()
        r = self.ctl("cancel", gid)
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(self.task(gid)["state"], "CANCELLED")
        self.assertEqual(self.cstate("Remaining"), "RED_VERIFIED")
        self.assertEqual(moves(), before + 1)  # the hook runs once

    def test_non_cycle_task_retry_and_cancel_are_unchanged(self):
        self.boot_api()
        tid = self.make("docs")
        self.eng.queue_task(tid)
        r = self.ctl("cancel", tid)
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(self.task(tid)["state"], "CANCELLED")
        r = self.ctl("retry", tid)
        self.assertEqual(r.status, 200, r.text)
        retry = [t for t in self.eng.reg.rows("tasks", run_id=self.run_row()["id"], role="docs") if t["retry_of"] == tid]
        self.assertEqual(len(retry), 1)


class MigrationEight(SV):
    def test_a_database_at_version_7_gets_0008_applied_on_open(self):
        from registry import Registry, _load_file_migrations
        migs = sorted(_load_file_migrations())
        self.assertEqual([m[0] for m in migs], list(range(1, 10)))
        d = Path(self._home.name) / "state"
        Registry.open(d, [m for m in migs if m[0] <= 7]).close()
        c = sqlite3.connect(d / "sentinel.db")
        self.addCleanup(c.close)
        self.assertEqual(c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "7")
        before = {r[1] for r in c.execute("PRAGMA table_info(cycles)")}
        c.execute("DELETE FROM meta WHERE key='applied_migrations'")  # created before the record existed
        c.commit()
        r = Registry.open(d, migs)
        self.addCleanup(r.close)
        self.assertEqual(r.schema_version(), 9)
        after = {x[1] for x in r._c.execute("PRAGMA table_info(cycles)")}
        self.assertGreater(len(after), len(before), (before, after))
        self.assertEqual(json.loads(r._c.execute("SELECT value FROM meta WHERE key='applied_migrations'").fetchone()[0]),
                         list(range(1, 10)))
