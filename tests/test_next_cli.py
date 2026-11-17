"""Phase C part 2 (PC-02): `sentinel next`, `task run`, `task complete`, `stage run` on version 2 runs."""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from pc_helpers import PCX, SLUG, SENTINEL, git  # noqa: E402
from pb_helpers import spec_text, GOOD  # noqa: E402


class NextSteps(PCX):
    def run_in(self, slug, state, tier=3, **fields):
        self.mk(slug, state, tier)
        if fields:
            self.eng.reg.update_run(slug, **fields)
        return slug

    def test_AC_ARC_03a_next_per_run_state(self):
        rows = [
            ("CREATED", None, 0, "orchestrator", lambda s, o: f"sentinel triage {s} --factors" in json.dumps(o)),
            ("TRIAGED", None, 0, "orchestrator", lambda s, o: f"write .sentinel/runs/{s}/decisions.md" in json.dumps(o)),
            ("PLANNED", "specifier", 0, "task", lambda s, o: o["role"] == "specifier" and o["adapter"] == "native"
             and o["command"] == f"sentinel task run {o['task']}"),
            ("SPECIFICATION_REVIEW", None, 6, "human", lambda s, o: f"sentinel review {s} spec" in json.dumps(o)
             and f"sentinel approve {s} spec" in json.dumps(o)),
            ("GHERKIN_REVIEW", None, 6, "human", lambda s, o: f"sentinel review {s} gherkin" in json.dumps(o)
             and f"sentinel approve {s} gherkin" in json.dumps(o)),
            ("EXECUTING", "running", 0, "wait", lambda s, o: o["tasks"] == [o["tasks"][0]] and o["tasks"][0].startswith("t-")),
            ("NEEDS_HUMAN", "reason", 6, "human", lambda s, o: "docs task failed after 2 retries" in o["reason"]),
            ("BLOCKED", "blocked", 6, "human", lambda s, o: "runner not installed: codex" in o["reason"] and o.get("fix")),
            ("COMPLETED", None, 0, "done", lambda s, o: (o["execution"], o["acceptance"]) == ("completed", "accepted")),
            ("CANCELLED", None, 0, "done", lambda s, o: o["execution"] == "cancelled"),
        ]
        for i, (state, extra, code, kind, check) in enumerate(rows):
            with self.subTest(state):
                slug = f"lb{i}"
                tier = None if state == "CREATED" else 3
                self.mk(slug, state, tier or 1)
                if state == "CREATED":
                    self.eng.reg.update_run(slug, tier=None)
                if state == "TRIAGED":
                    pass
                if state == "COMPLETED":
                    self.eng.reg.update_run(slug, execution_status="completed", acceptance_status="accepted")
                if state == "CANCELLED":
                    self.eng.reg.update_run(slug, execution_status="cancelled")
                if state in ("NEEDS_HUMAN", "BLOCKED"):
                    reason = "docs task failed after 2 retries" if state == "NEEDS_HUMAN" else "runner not installed: codex"
                    self.eng.reg.update_run(slug, previous_state="EXECUTING")
                    self.eng.reg.add_event(self.run_row(slug)["id"], "run.state_changed", "engine",
                                           {"from": "EXECUTING", "to": state, "transition": "R19", "reason": reason})
                if extra == "specifier":
                    self.make("specifier", slug=slug)
                    self.eng.queue_task(self.states(slug=slug)[0][0])
                if extra == "running":
                    self.running(slug=slug)
                c, out, err = self.next_json(slug)
                self.assertEqual((c, out["kind"] if out else None), (code, kind), err)
                self.assertTrue(check(slug, out), out)

    def test_AC_ARC_03b_next_plans_a_low_tier_run_and_offers_the_specifier_task(self):
        self.eng.create_run("fix-typo", "orchestrator", type="feature", baseline={"backend": "abc"})
        self.eng.triage("fix-typo", {"files": "1"}, "orchestrator")
        self.assertEqual(self.state("fix-typo"), "TRIAGED")
        code, step, err = self.next_json("fix-typo")
        self.assertEqual(self.state("fix-typo"), "PLANNED", err)
        ev = self.events("run.state_changed", "fix-typo")[-1]
        self.assertEqual((ev["payload"]["transition"], ev["actor"]), ("R3", "engine"))
        tasks = self.states("specifier", "fix-typo")
        self.assertEqual([s for _, s in tasks], ["QUEUED"])
        self.assertEqual((step["kind"], step["task"]), ("task", tasks[0][0]))

    def test_AC_ARC_03c_next_without_json_prints_the_step_for_a_person(self):
        self.mk(SLUG, "SPECIFICATION_REVIEW", 3)
        code, out, err = self.cli("next", SLUG)
        self.assertEqual(code, 6, out + err)
        self.assertIn("Human action: review and approve the specification", out)
        self.assertIn(f"sentinel approve {SLUG} spec", out)

    def test_AC_ARC_03d_next_never_starts_a_task(self):
        marker = self.ws / "started.txt"
        self.boot({"fake": (f"open({str(marker)!r}, 'a').write('x')\nwrite_result()\n", {})}, {"docs": "fake"})
        tid = self.docs_task()
        outs = [self.cli("next", SLUG, "--json") for _ in range(3)]
        self.assertEqual(self.task(tid)["state"], "QUEUED")
        self.assertFalse(marker.exists())
        self.assertEqual(len({o[1] for o in outs}), 1, outs)

    def test_AC_ARC_03h_bad_arguments_are_refused(self):
        self.executing()
        rows = [(("next", "no-such-run"), 5, "E_NOT_FOUND"), (("next", "../x"), 5, "E_VALIDATION"),
                (("task", "run"), 2, "usage"), (("task", "run", "../../etc/passwd"), 5, "E_VALIDATION"),
                (("task", "run", "t-000000000000"), 5, "E_NOT_FOUND"), (("task", "complete", "t-zzzz"), 5, "E_VALIDATION"),
                (("task", "complete"), 2, "usage")]
        for args, code, error in rows:
            with self.subTest(args):
                c, out, err = self.cli(*args)
                self.assertEqual(c, code, out + err)
                self.assertIn("usage" if error == "usage" else error, out + err)

    def test_AC_ARC_03i_run_with_no_tasks_and_nothing_to_do(self):
        self.executing()
        code, step, err = self.next_json()
        self.assertEqual(code, 6, err)
        self.assertEqual((step["kind"], step["reason"]), ("human", "no task planned for EXECUTING"))


class Gates(PCX):
    def planned_with_waiting_specifier(self):
        self.eng.create_run(SLUG, "orchestrator", type="feature", baseline={"backend": "abc"})
        self.eng.triage(SLUG, {"files": "1"}, "orchestrator")
        self.eng.request_state(SLUG, "PLANNED", "engine")
        (tid,) = [t for t, _ in self.states("specifier")]
        code, out, err = self.run_json(tid)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.task(tid)["state"], "WAITING_FOR_INPUT")
        return tid

    def test_AC_ARC_03e_completed_specifier_task_opens_the_specification_review(self):
        tid = self.planned_with_waiting_specifier()
        self.write_spec(spec_text(tier=1))
        self.write_result(tid)
        code, out, err = self.cli("task", "complete", tid)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.task(tid)["state"], "COMPLETED")
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.assertEqual(self.events("run.state_changed")[-1]["payload"]["transition"], "R4")
        code, step, err = self.next_json()
        self.assertEqual((code, step["kind"]), (6, "human"))
        self.assertIn(f"sentinel approve {SLUG} spec", json.dumps(step))

    def test_AC_ARC_03f_invalid_specification_goes_back_to_the_specifier(self):
        tid = self.planned_with_waiting_specifier()
        text = spec_text(tier=1)
        self.write_spec(text.replace("## Edge cases", "## Edge"))
        self.write_result(tid)
        code, out, err = self.cli("task", "complete", tid)
        self.assertEqual(self.task(tid)["state"], "COMPLETED", out + err)
        self.assertEqual(self.state(), "PLANNED")
        new = [t for t in self.eng.reg.rows("tasks", run_id=self.run_row()["id"]) if t["id"] != tid]
        self.assertEqual([(t["role"], t["state"]) for t in new], [("specifier", "QUEUED")])
        self.assertIn("missing section: Edge cases", (self.tdir(new[0]["id"]) / "brief.md").read_text())

    def test_AC_ARC_03g_approving_the_specification_queues_the_test_designer_task(self):
        self.to_spec_review(SLUG, tier=1)
        self.approve("spec")
        (td,) = [t for t in self.eng.reg.rows("tasks", run_id=self.run_row()["id"]) if t["role"] == "test_designer"]
        self.assertEqual(td["state"], "QUEUED")
        doc = self.task_json(td["id"])
        approved = self.approvals("specification")[-1]
        self.assertEqual(doc["input"]["specification"]["sha256"], approved["sha256"])
        self.assertEqual(doc["permissions"]["write"], [f"specs/{SLUG}/features/**"])


class Legacy(PCX):
    def setUp(self):
        super().setUp()
        self.use_config(runners={n: {"command": self.script(n, b)} for n, b in (
            ("fake", 'write("backend/ok.txt")\n'), ("stray", 'write("frontend/stray.txt")\n'),
            ("commit", 'subprocess.run(["git", "-c", "user.name=a", "-c", "user.email=a@b.c", "commit", "--allow-empty", "-m", "x"], check=True)\n'),
            ("broken", "sys.exit(1)\n"))})

    def legacy_run(self, slug="demo"):
        self.eng.reg.insert_run({"slug": slug, "state": "LEGACY", "workflow_version": "0.1", "tier": 2,
                                 "execution_status": "running", "acceptance_status": "pending"})
        d = self.ws / ".sentinel/runs" / slug
        d.mkdir(parents=True)
        (d / "state.json").write_text(json.dumps({"slug": slug, "tier": 2, "initial_tier": 2, "stages": ["coder"],
                                                  "completed": [], "sessions": {}, "rounds": {}, "baseline": {}}))

    def stage_run(self, slug, runner):
        return self.run_stage(["--slug", slug, "--stage", "coder", "--repo", "backend", "--runner", runner])

    def run_stage(self, args):
        import subprocess
        p = subprocess.run([sys.executable, str(Path(SENTINEL).with_name("run_stage.py")), "--config",
                            str(self.ws / "sentinel.config.yaml"), *args], capture_output=True, text=True, cwd=self.ws,
                           env=self.env())
        return p.returncode, p.stdout + p.stderr

    def test_AC_ORC_08e_stage_run_keeps_its_exit_codes(self):
        self.legacy_run()
        for runner, code in (("fake", 0), ("stray", 3), ("commit", 3), ("broken", 1)):
            with self.subTest(runner):
                got, out = self.stage_run("demo", runner)
                self.assertEqual(got, code, out)
                git(self.ws / "frontend", "clean", "-fdq")
        db = sqlite3.connect(self.ws / ".sentinel/sentinel.db")
        run_id = db.execute("SELECT id FROM runs WHERE slug='demo'").fetchone()[0]
        self.assertEqual(db.execute("SELECT count(*) FROM tasks WHERE run_id=?", (run_id,)).fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT count(*) FROM events WHERE type LIKE 'task.%'").fetchone()[0], 0)
        db.close()

    def test_AC_ORC_08f_new_commands_refuse_0_1_runs(self):
        self.legacy_run("old-run")
        before = (self.ws / ".sentinel/runs/old-run/state.json").read_bytes()
        for args in (("next", "old-run"), ("next", "old-run", "--json")):
            with self.subTest(args):
                code, out, err = self.cli(*args)
                self.assertEqual(code, 5, out + err)
                self.assertIn("E_TRANSITION", err)
                self.assertEqual((self.ws / ".sentinel/runs/old-run/state.json").read_bytes(), before)

    def test_AC_ORC_08g_stage_run_is_refused_on_a_version_2_run(self):
        marker = self.ws / "started.txt"
        self.use_config(runners={"fake": {"command": self.script("fake", f"open({str(marker)!r}, 'w').write('x')\n")}})
        self.executing()
        got, out = self.stage_run(SLUG, "fake")
        self.assertEqual(got, 5, out)
        self.assertIn("E_TRANSITION", out)
        self.assertIn("sentinel task run", out)
        self.assertFalse(marker.exists())

    def test_AC_ORC_08h_stage_run_with_an_adhoc_slug_keeps_working(self):
        got, out = self.stage_run("scratch", "fake")
        self.assertEqual(got, 0, out)


if __name__ == "__main__":
    unittest.main()
