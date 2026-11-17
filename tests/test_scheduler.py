"""Phase C part 2 (PC-02): scheduler. Dependencies, write-scope overlap, parallel limit, start refusal."""
import json
import sys
import unittest
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from errors import SentinelError  # noqa: E402
from pc_helpers import PCX, SLUG, BASE_CONFIG, wait_until  # noqa: E402

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "sentinel/core/schema/config.schema.json").read_text())


class Deps(PCX):
    def setUp(self):
        super().setUp()
        self.executing()

    def st(self, tid):
        return self.task(tid)["state"]

    def complete(self, tid):
        self.eng.queue_task(tid) if self.st(tid) == "CREATED" else None
        self.eng.start_task(tid)
        self.write_result(tid)
        self.eng.finish_task(tid, exit_code=0)

    def test_AC_AGT_07a_task_is_queued_when_its_last_dependency_completes(self):
        a, b = self.make(write=["backend/a/**"]), self.make(write=["backend/b/**"])
        c = self.make(write=["backend/c/**"], depends_on=[a, b])
        self.eng.schedule(SLUG)
        self.assertEqual((self.st(a), self.st(b), self.st(c)), ("QUEUED", "QUEUED", "CREATED"))
        self.complete(a)
        self.assertEqual(self.st(c), "CREATED")
        self.complete(b)
        self.assertEqual(self.st(c), "QUEUED")
        self.assertEqual(len(self.ev(c, "task.queued")), 1)

    def test_AC_AGT_07b_task_with_open_dependencies_cannot_be_run(self):
        a = self.make(write=["backend/a/**"])
        self.eng.queue_task(a)
        c = self.make(write=["backend/c/**"], depends_on=[a])
        code, out, err = self.cli("task", "run", c)
        self.assertEqual(code, 5, out + err)
        self.assertIn("E_TRANSITION", err)
        self.assertIn(a, err)
        self.assertEqual(self.st(c), "CREATED")

    def test_AC_AGT_07c_next_offers_tasks_in_dependency_order(self):
        a = self.make(write=["backend/a/**"])
        self.eng.queue_task(a)
        c = self.make(write=["backend/c/**"], depends_on=[a])
        code, step, err = self.next_json()
        self.assertEqual((step["kind"], step["task"]), ("task", a), err)
        self.complete(a)
        code, step, err = self.next_json()
        self.assertEqual((step["kind"], step["task"]), ("task", c), err)

    def test_AC_AGT_07d_dependency_satisfied_by_its_retry(self):
        a = self.running(write=["backend/a/**"])
        self.eng.finish_task(a, exit_code=1)
        retry = [t for t in self.states('docs') if t[0] != a][0][0]
        self.assertEqual(self.task(retry)["retry_of"], a)
        c = self.make(write=["backend/c/**"], depends_on=[a])
        self.eng.schedule(SLUG)
        self.assertEqual(self.st(c), "CREATED")
        self.eng.start_task(retry)
        self.write_result(retry)
        self.eng.finish_task(retry, exit_code=0)
        self.assertEqual(self.st(c), "QUEUED")

    def test_AC_AGT_07e_dependents_of_a_cancelled_task_are_cancelled(self):
        a = self.make(write=["backend/a/**"])
        self.eng.queue_task(a)
        c = self.make(write=["backend/c/**"], depends_on=[a])
        d = self.make(write=["backend/d/**"], depends_on=[c])
        self.eng.cancel_task(a, "human", reason="stop")
        for t in (c, d):
            self.assertEqual(self.st(t), "CANCELLED")
            fin = self.ev(t, "task.finished")[0]
            self.assertEqual(fin["actor"], "engine")
            self.assertEqual(fin["payload"]["reason"], f"dependency {a} cancelled")

    def test_AC_AGT_07f_invalid_dependency_graph_is_refused(self):
        other = "other-run"
        self.executing(other)
        foreign = self.make(slug=other)
        node = {"role": "docs", "repos": ["backend"]}
        rows = {
            "cycle": [{**node, "key": "A", "depends_on": ["B"]}, {**node, "key": "B", "depends_on": ["A"]}],
            "self": [{**node, "key": "A", "depends_on": ["A"]}],
            "unknown": [{**node, "key": "A", "depends_on": ["Z"]}],
            "other_run": [{**node, "key": "A", "depends_on": [foreign]}],
        }
        before = len(self.eng.reg.rows("tasks"))
        for name, graph in rows.items():
            with self.subTest(name):
                with self.assertRaises(SentinelError) as c:
                    self.eng.create_task_graph(SLUG, graph)
                self.assertEqual(c.exception.code, "E_VALIDATION")
                self.assertEqual(len(self.eng.reg.rows("tasks")), before)

    def test_task_graph_stores_tasks_with_dependencies(self):
        node = {"role": "docs", "repos": ["backend"]}
        ids = self.eng.create_task_graph(SLUG, [
            {**node, "key": "C", "depends_on": ["A", "B"], "write": ["backend/c/**"]},
            {**node, "key": "A", "write": ["backend/a/**"]}, {**node, "key": "B", "write": ["backend/b/**"]}])
        self.assertEqual(sorted(self.eng.reg.task_deps(ids["C"])), sorted([ids["A"], ids["B"]]))
        self.assertEqual(self.st(ids["C"]), "CREATED")


OVERLAP_ROWS = [("backend/src/main/**", "backend/src/main/java/leave/**", False),
                ("backend/src/main/**", "backend/src/test/**", True),
                ("backend/**", "frontend/**", True),
                ("backend/**/*.java", "backend/src/test/**", False),
                ("backend/docs/*.md", "backend/src/**", True),
                ("backend/src/main/**", "backend/src/main/java/new/**", False),
                ("backend/docs/leave.md", "backend/docs/leave.md", False),
                ("backend/src/main/**", None, True),
                ("backend/*.md", "backend/*.txt", True),
                ("backend/docs/*.md", "backend/docs/*.txt", True),
                ("backend/a*", "backend/b*", True),
                ("backend/[ab]*.md", "backend/[!ab]*.md", True),
                ("backend/*.md", "backend/read*", False),
                ("backend/config.d", "backend/config.d/x.conf", False)]


class Globs(unittest.TestCase):
    def test_many_double_stars_stay_fast(self):
        import time
        import scheduler
        a = "backend/" + "/".join(["**", "x"] * 14)
        b = "backend/" + "/".join(["**", "y"] * 14) + "/**"
        t = time.monotonic()
        scheduler.globs_overlap(a, b)
        scheduler.globs_overlap("backend/" + "/".join(["**"] * 14), "backend/" + "/".join(["**"] * 14) + "/z")
        self.assertLess(time.monotonic() - t, 0.1)

    def test_literal_directory_with_dot_covers_what_is_below(self):
        import scheduler
        self.assertTrue(scheduler.globs_overlap("backend/config.d", "backend/config.d/x.conf"))

    def test_segment_patterns_intersect_exactly(self):
        import scheduler
        for a, b, want in (("*.md", "*.txt", False), ("a*", "b*", False), ("a*z", "*m*", True), ("?x", "[ab]x", True),
                           ("[!a]x", "ax", False), ("[a-c]", "[d-f]", False), ("*a*b*", "b*a", True)):
            self.assertEqual(scheduler._segments_compatible(a, b), want, (a, b))


class Overlap(PCX):
    def test_AC_AGT_07g_write_scope_overlap_table(self):
        for i, (running, queued, answer) in enumerate(OVERLAP_ROWS):
            with self.subTest(running=running, queued=queued):
                self.eng.close()
                self.use_config(policies={"max_parallel_tasks": 4})
                slug = f"ov-{i}"
                self.executing(slug)
                a = self.running(write=[running], slug=slug)
                b = self.make(write=[queued] if queued else [], slug=slug)
                self.eng.queue_task(b)
                got = self.eng.check_start(b)
                self.assertEqual(got["ok"], answer, got)
                if answer:
                    self.assertEqual(self.eng.start_task(b)["state"], "RUNNING")
                else:
                    with self.assertRaises(SentinelError) as c:
                        self.eng.start_task(b)
                    self.assertEqual(c.exception.code, "E_PRECONDITION")
                    self.assertEqual(self.task(b)["state"], "QUEUED")

    def setUp(self):
        super().setUp()
        self.use_config(policies={"max_parallel_tasks": 2})
        self.executing()

    def test_AC_AGT_07h_overlapping_task_stays_queued_while_the_other_runs(self):
        a = self.running(write=["backend/src/main/**"])
        b = self.make(write=["backend/src/main/java/leave/**"])
        self.eng.queue_task(b)
        code, out, err = self.cli("task", "run", b)
        self.assertEqual(code, 5, out + err)
        self.assertIn("E_PRECONDITION", err)
        self.assertIn(a, err)
        self.assertIn("backend/src/main/**", err)
        self.assertEqual(self.task(b)["state"], "QUEUED")
        code, step, err = self.next_json()
        self.assertEqual((step["kind"], step["tasks"]), ("wait", [a]), err)

    def test_AC_AGT_07i_waiting_native_task_still_holds_its_write_scope(self):
        a = self.running(write=["backend/docs/**"])
        self.eng.wait_task(a, "orchestrator")
        b = self.make(write=["backend/docs/**"])
        self.eng.queue_task(b)
        code, out, err = self.cli("task", "run", b)
        self.assertEqual(code, 5, out + err)
        self.assertIn("E_PRECONDITION", err)
        self.assertEqual(self.task(b)["state"], "QUEUED")

    def test_AC_AGT_07j_two_processes_start_overlapping_tasks_at_the_same_moment(self):
        a = self.make(write=["backend/src/main/**"])
        b = self.make(write=["backend/src/main/**"])
        for t in (a, b):
            self.eng.queue_task(t)
        procs = [self.popen("task", "run", t) for t in (a, b)]
        results = [self.finish(p) for p in procs]
        codes = sorted(r[0] for r in results)
        self.assertEqual(codes, [0, 5], results)
        states = sorted(self.task(t)["state"] for t in (a, b))
        self.assertEqual(states, ["QUEUED", "WAITING_FOR_INPUT"])

    def test_AC_AGT_07l_parallel_limit(self):
        rows = [(None, 5, "QUEUED"), (1, 5, "QUEUED"), (2, 0, "WAITING_FOR_INPUT")]
        for i, (limit, code, state) in enumerate(rows):
            with self.subTest(limit=limit):
                self.eng.close()
                self.use_config(**({"policies": {"max_parallel_tasks": limit}} if limit else {}))
                slug = f"lim-{i}"
                self.executing(slug)
                self.running(write=["backend/src/main/**"], slug=slug)
                b = self.make(write=["frontend/src/**"], repos=("frontend",), slug=slug)
                self.eng.queue_task(b)
                c, out, err = self.cli("task", "run", b)
                self.assertEqual(c, code, out + err)
                self.assertEqual(self.task(b)["state"], state)
                if code == 5:
                    self.assertIn("E_PRECONDITION", err)
                    self.assertIn("max_parallel_tasks 1", err)

    def test_AC_AGT_07m_invalid_parallel_limit_fails_validation(self):
        base = {"version": 1, "shape": "single", "repos": [{"id": "a", "path": "./a", "role": "backend", "profile": "generic"}]}
        jsonschema.validate({**base, "policies": {"max_parallel_tasks": 2}}, SCHEMA)
        for value in (0, -1, "two"):
            with self.subTest(value=value):
                errors = list(jsonschema.Draft202012Validator(SCHEMA).iter_errors({**base, "policies": {"max_parallel_tasks": value}}))
                self.assertEqual([list(e.absolute_path) for e in errors], [["policies", "max_parallel_tasks"]])

    def test_documented_policy_provider_and_agent_keys_validate(self):
        base = {"version": 1, "shape": "single", "repos": [{"id": "a", "path": "./a", "role": "backend", "profile": "generic"}]}
        doc = {**base,
               "policies": {"human_required": ["security_gate", "publish"], "max_parallel_tasks": 1,
                            "task_timeout_seconds": 5400, "provider_retries": 1, "redact_env": ["DATABASE_URL"]},
               "providers": {"default": "claude", "fallback": ["codex"], "disabled": []},
               "agents": {"tdd_green": {"runner": "codex", "model": "gpt-5"}, "reviewer": {"model": "opus"},
                          "qa": {"max_retries": 1}}}
        self.assertEqual([e.message for e in jsonschema.Draft202012Validator(SCHEMA).iter_errors(doc)], [])
        bad = {**doc, "policies": {"provider_retries": -1}}
        self.assertTrue(list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(bad)))


class RunStates(PCX):
    def test_AC_AGT_07n_no_task_starts_while_the_run_is_parked_or_under_review(self):
        for state in ("NEEDS_HUMAN", "BLOCKED", "SPECIFICATION_REVIEW", "GHERKIN_REVIEW"):
            with self.subTest(state):
                slug = f"st-{state.lower().replace('_', '-')}"
                self.executing(slug)
                tid = self.make(slug=slug)
                self.eng.queue_task(tid)
                self.eng.reg.update_run(slug, state=state, previous_state="EXECUTING")
                code, out, err = self.cli("task", "run", tid)
                self.assertEqual(code, 5, out + err)
                self.assertIn("E_PRECONDITION", err)
                self.assertIn(state, err)
                self.assertEqual(self.task(tid)["state"], "QUEUED")

    def test_AC_AGT_07o_a_task_cannot_create_tasks(self):
        self.executing()
        tid = self.running()
        self.write_result(tid, out_of_lane=[{"note": "follow-up: add a migration"}])
        before = len(self.eng.reg.rows("tasks"))
        row = self.eng.finish_task(tid, exit_code=0)
        self.assertEqual(row["state"], "COMPLETED")
        self.assertEqual(len(self.eng.reg.rows("tasks")), before)
        report = json.loads((self.tdir(tid) / "report.json").read_text())
        self.assertEqual(report["out_of_lane"], [{"note": "follow-up: add a migration"}])


class Duplicates(PCX):
    def test_AC_AGT_07k_same_task_run_twice_at_once_starts_once(self):
        counter = self.ws / "started.txt"
        self.boot({"fake": (f"open({str(counter)!r}, 'a').write('x')\ntime.sleep(2)\nwrite_result()\n", {})}, {"docs": "fake"},
                  policies={"max_parallel_tasks": 2})
        tid = self.docs_task()
        procs = [self.popen("task", "run", tid) for _ in range(2)]
        results = [self.finish(p) for p in procs]
        self.assertEqual(sorted(r[0] for r in results), [0, 5], results)
        self.assertIn("E_TRANSITION", "".join(r[2] for r in results if r[0] == 5))
        self.assertEqual(counter.read_text(), "x")


if __name__ == "__main__":
    unittest.main()
