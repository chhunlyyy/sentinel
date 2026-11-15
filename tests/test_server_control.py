"""Phase F: creating runs and controlling them from the dashboard (control_tasks_api.feature)."""
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from sv_helpers import SV, SLUG, Http, fail_next_write, spec_text, wait_until
from pc_helpers import alive

NEW = "leave-balance"
VALID = {"slug": NEW, "request": "Show the remaining leave balance", "type": "feature", "repos": ["backend", "frontend"],
         "priority": "high"}


class Create(SV):
    def setUp(self):
        super().setUp()
        self.serve()
        self.url = "/api/v1/projects/digital-hr/tasks"

    def create(self, body=None, **over):
        b = dict(VALID if body is None else body)
        b.update(over)
        return self.http.post(self.url, b)

    def row(self, slug=NEW):
        return self.eng.reg.get_run(slug)

    def test_AC_TSK_01a_creating_a_run_from_the_dashboard(self):
        r = self.create()
        self.assertEqual(r.status, 201, r.text)
        self.assertEqual((r.json["slug"], r.json["state"], r.json["workflow_version"]), (NEW, "CREATED", "2"))
        run = self.row()
        repos = {x["repo_id"]: x["baseline_sha"] for x in self.eng.reg.run_repos(run["id"])}
        self.assertEqual(set(repos), {"backend", "frontend"})
        self.assertTrue(all(len(s) == 40 for s in repos.values()))
        self.assertTrue(run["config_snapshot_id"])
        self.assertTrue((self.ws / ".sentinel" / "shared" / "locks" / NEW).exists())
        self.assertEqual((run["priority"], run["origin"]), ("high", "dashboard"))
        ev = self.events_rows(type="run.created")[0]
        self.assertEqual((ev["actor"], ev["actor_name"], ev["channel"]), ("human", "dev", "dashboard"))
        row = [a for a in self.audit_rows() if a["action"] == "run_created"][0]
        self.assertEqual((row["channel"], row["target"]), ("dashboard", NEW))

    def test_AC_TSK_03b_the_new_run_waits_for_the_ai_tool(self):
        self.assertEqual(self.create().status, 201)
        r = self.http.get(f"/api/v1/tasks/{NEW}/next")
        self.assertEqual(r.status, 200, r.text)
        step = r.json
        self.assertEqual((step["kind"], step["label"]), ("orchestrator", "waiting for AI tool"))
        self.assertIn("triage", step["action"])
        self.assertEqual(step["resume_command"], f"/sentinel resume {NEW}")
        self.assertEqual(self.eng.reg.rows("tasks", run_id=self.row()["id"]), [])

    def test_AC_TSK_02a_creating_a_run_authorizes_nothing(self):
        self.assertEqual(self.create(tier=4).status, 201)
        run = self.row()
        self.assertEqual(self.eng.reg.rows("approvals", run_id=run["id"]), [])
        self.assertEqual(self.eng.reg.rows("tasks", run_id=run["id"]), [])
        self.assertIsNone(run["tier"])
        self.assertEqual(run["requested_tier"], 4)
        for repo in ("backend", "frontend"):
            self.assertEqual(subprocess.run(["git", "-C", str(self.ws / repo), "status", "--porcelain"],
                                            capture_output=True, text=True).stdout, "")

    def test_AC_TSK_01b_invalid_run_bodies(self):
        rows = [({"slug": "Bad Slug"}, "slug"), ({"slug": "a..b"}, "slug"), ({"type": "party"}, "type"),
                ({"repos": ["mobile"]}, "repos"), ({"repos": ["../etc"]}, "repos"), ({"tier": 7}, "tier"),
                ({"priority": "now"}, "priority")]
        for over, field in rows:
            with self.subTest(over=over):
                r = self.http.post(self.url, {"slug": "lb", "request": "x", "type": "feature", "repos": ["backend"], **over})
                self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)
                self.assertIn(field, r.text)
                slug = over.get("slug", "lb")
                self.assertIsNone(self.row(slug))
                self.assertFalse((self.ws / ".sentinel" / "runs" / slug).exists())

    def test_AC_TSK_01c_required_run_fields(self):
        for field in ("slug", "request", "type"):
            with self.subTest(field=field):
                b = dict(VALID)
                del b[field]
                r = self.http.post(self.url, b)
                self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))
                self.assertIn(field, r.text)

    def test_AC_TSK_01d_empty_values(self):
        for field, value in (("request", ""), ("request", "   "), ("repos", []), ("slug", None)):
            with self.subTest(field=field, value=value):
                r = self.create(**{field: value})
                self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)
                self.assertIn(field, r.text)

    def test_AC_TSK_01e_repos_may_be_left_out(self):
        r = self.http.post(self.url, {"slug": "lb", "request": "x", "type": "feature"})
        self.assertEqual(r.status, 201, r.text)
        run = self.row("lb")
        self.assertEqual({x["repo_id"] for x in self.eng.reg.run_repos(run["id"])}, {"backend", "frontend"})

    def test_AC_TSK_01f_a_slug_that_is_taken(self):
        rows = ["v2", "legacy", "lock"]
        for kind in rows:
            with self.subTest(existing=kind):
                slug = f"taken-{kind}"
                if kind == "v2":
                    self.mk(slug, "CREATED", 1)
                    status, code = 422, "E_PRECONDITION"
                elif kind == "legacy":
                    self.eng.reg.insert_run({"slug": slug, "tier": 2, "state": "LEGACY", "workflow_version": "0.1",
                                             "execution_status": "running", "acceptance_status": "pending"})
                    status, code = 422, "E_PRECONDITION"
                else:
                    lock = self.ws / ".sentinel" / "shared" / "locks" / slug
                    lock.parent.mkdir(parents=True, exist_ok=True)
                    lock.write_text("someone\n")
                    status, code = 409, "E_LOCKED"
                before = self.row(slug)
                r = self.create(slug=slug)
                self.assertEqual((r.status, r.code), (status, code), r.text)
                self.assertEqual(self.row(slug), before)

    def test_AC_TSK_01g_two_creations_of_the_same_slug_at_the_same_moment(self):
        out = []
        barrier = threading.Barrier(2)

        def go():
            c = self.client()
            barrier.wait()
            out.append(c.post(self.url, dict(VALID)))
        ts = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in ts]
        [t.join(60) for t in ts]
        statuses = sorted(r.status for r in out)
        self.assertEqual(statuses[0], 201, [r.text for r in out])
        self.assertIn(statuses[1], (409, 422))
        self.assertEqual(len(self.events_rows(type="run.created")), 1)

    def test_AC_TSK_01h_a_repo_that_is_no_longer_a_git_repo(self):
        shutil.rmtree(self.ws / "frontend" / ".git")
        r = self.create()
        self.assertEqual((r.status, r.code), (422, "E_PRECONDITION"), r.text)
        self.assertIn("frontend", r.text)
        self.assertIsNone(self.row())
        self.assertFalse((self.ws / ".sentinel" / "shared" / "locks" / NEW).exists())


FAKE_SPEC = "write('.sentinel/shared/specs/{slug}/spec.md', {text!r})\nwrite_result()\n"


class Dispatch(SV):
    """Q2: the server starts ready CLI tasks of dashboard runs; everything else waits."""
    DISPATCH = 0.1

    def serve_dispatch(self, **kw):
        return self.serve(dispatch=True, dispatch_interval=self.DISPATCH, **kw)

    def dashboard_run(self, slug=NEW, tier=1):
        """Create through the API, then triage and plan as the orchestrator would."""
        r = self.http.post("/api/v1/projects/digital-hr/tasks", {"slug": slug, "request": "x", "type": "feature",
                                                                  "repos": ["backend"]})
        self.assertEqual(r.status, 201, r.text)
        self.eng.triage(slug, {"files": "1"}, "orchestrator")
        self.eng.request_state(slug, "PLANNED", "engine")
        return slug

    def test_AC_TSK_03c_the_server_starts_a_ready_cli_task_of_a_dashboard_run(self):
        text = spec_text(NEW, tier=1)
        self.use_config(single_model=False, runners={"fake": {"command": self.script("fake", FAKE_SPEC.format(slug=NEW, text=text))}},
                        agents={"specifier": {"runner": "fake"}})
        self.serve_dispatch()
        self.dashboard_run()
        (tid, _), = self.states("specifier", NEW)
        self.assertTrue(wait_until(lambda: self.state(NEW) == "SPECIFICATION_REVIEW", 20), (self.states(None, NEW), self.state(NEW)))
        row = self.task(tid)
        self.assertEqual((row["state"], row["adapter"]), ("COMPLETED", "cli"))
        started = [e for e in self.ev(tid, "task.started")]
        self.assertEqual(started[0]["actor"], "engine")
        self.assertEqual([e["payload"]["transition"] for e in self.events("run.state_changed", NEW)][-1], "R4")

    def test_AC_TSK_03d_a_native_task_of_a_dashboard_run_waits_for_the_ai_tool(self):
        self.serve_dispatch()
        self.dashboard_run()
        (tid, state), = self.states("specifier", NEW)
        time.sleep(1.0)
        self.assertEqual(self.task(tid)["state"], "QUEUED")
        r = self.http.get(f"/api/v1/tasks/{NEW}/next")
        self.assertEqual((r.json["task"], r.json["label"]), (tid, "waiting for orchestrator"))

    def test_AC_TSK_03e_runs_created_at_the_cli_are_not_dispatched_by_the_server(self):
        marker = self.ws / "launched.txt"
        self.use_config(single_model=False, runners={"fake": {"command": self.script(
            "fake", f"open({str(marker)!r}, 'a').write('x')\nwrite_result()\n")}}, agents={"specifier": {"runner": "fake"}})
        self.serve_dispatch()
        code, out, err = self.cli("run", "new", "cli-run", "--type", "feature")
        self.assertEqual(code, 0, out + err)
        self.eng.triage("cli-run", {"files": "1"}, "orchestrator")
        self.eng.request_state("cli-run", "PLANNED", "engine")
        (tid, _), = self.states("specifier", "cli-run")
        time.sleep(2.0)
        self.assertEqual(self.task(tid)["state"], "QUEUED")
        self.assertFalse(marker.exists())

    def boot_dashboard(self, body, n=3, write=None, policies=None, **kw):
        self.boot({"fake": (body, {})}, {"docs": "fake"}, policies=policies)
        with self.eng.reg.transaction():
            self.eng.reg.update_run(SLUG, origin="dashboard")
        ids = []
        for i in range(n):
            w = [write[i]] if write else [f"backend/docs{i}/**"]
            ids.append(self.docs_task(write=w, queue=True))
        return ids

    def test_AC_TSK_03f_the_server_and_the_orchestrator_start_the_same_task_at_the_same_moment(self):
        marker = self.ws / "launched.txt"
        (ids) = self.boot_dashboard(f"open({str(marker)!r}, 'a').write('x\\n')\ntime.sleep(1)\nwrite_result()\n", n=1)
        self.serve(dispatch=True, dispatch_interval=3600)
        barrier = threading.Barrier(2)
        out = {}

        def server():
            barrier.wait()
            out["spawned"] = self.srv.dispatch_once()
        t = threading.Thread(target=server)
        t.start()
        p = self.popen("task", "run", ids[0])
        barrier.wait()
        t.join(30)
        code, o, e = self.finish(p)
        for proc in out["spawned"]:
            proc.wait(30)
        self.assertTrue(wait_until(lambda: self.task(ids[0])["state"] in ("COMPLETED", "FAILED"), 20))
        self.assertEqual(self.task(ids[0])["state"], "COMPLETED")
        self.assertEqual(len(marker.read_text().split()), 1)

    def test_AC_TSK_03g_server_dispatch_respects_the_scheduler(self):
        log = self.ws / "spans.txt"
        body = (f"t0 = time.time()\ntime.sleep(1.2)\nopen({str(log)!r}, 'a').write(f'{{task_id}} {{t0}} {{time.time()}}\\n')\nwrite_result()\n")
        ids = self.boot_dashboard(body, n=3, write=["backend/docs/**", "backend/docs/**", "backend/other/**"],
                                  policies={"max_parallel_tasks": 2})
        self.serve_dispatch()
        self.assertTrue(wait_until(lambda: len(log.read_text().splitlines()) == 3 if log.exists() else False, 60), self.states())
        spans = {l.split()[0]: (float(l.split()[1]), float(l.split()[2])) for l in log.read_text().splitlines()}
        overlap = lambda a, b: a[0] < b[1] and b[0] < a[1]
        self.assertFalse(overlap(spans[ids[0]], spans[ids[1]]), spans)
        events = sorted([(s, 1) for s, e in spans.values()] + [(e, -1) for s, e in spans.values()])
        running = peak = 0
        for _, d in events:
            running += d
            peak = max(peak, running)
        self.assertLessEqual(peak, 2)

    def test_AC_TSK_03h_a_missing_runner_blocks_the_run_as_at_the_cli(self):
        self.use_config(single_model=False, runners={"fake": {"command": "/nonexistent/fake-runner"}}, agents={"docs": {"runner": "fake"}})
        self.executing(tier=3)
        with self.eng.reg.transaction():
            self.eng.reg.update_run(SLUG, origin="dashboard")
        tid = self.docs_task()
        self.serve_dispatch()
        self.assertTrue(wait_until(lambda: self.state() == "BLOCKED", 20), self.state())
        self.assertEqual(self.task(tid)["state"], "QUEUED")
        reason = [e for e in self.events("run.state_changed") if e["payload"]["to"] == "BLOCKED"][0]["payload"]["reason"]
        self.assertIn("fake-runner", reason)
        time.sleep(1.5)
        self.assertEqual(len([e for e in self.events("run.state_changed") if e["payload"]["to"] == "BLOCKED"]), 1)
        self.assertEqual(self.task(tid)["state"], "QUEUED")

    def test_AC_TSK_03i_stopping_the_server_does_not_kill_a_running_task(self):
        ids = self.boot_dashboard("time.sleep(3)\nwrite_result()\n", n=1)
        self.serve_dispatch()
        self.assertTrue(wait_until(lambda: self.task(ids[0])["state"] == "RUNNING", 20))
        self.srv.stop()
        pid = self.task(ids[0])["pid"]
        self.assertTrue(wait_until(lambda: self.task(ids[0])["pid"], 10))
        self.assertTrue(alive(self.task(ids[0])["pid"]))
        self.assertTrue(wait_until(lambda: self.task(ids[0])["state"] == "COMPLETED", 30), self.task(ids[0]))

    def test_AC_SEC_03q_an_agent_launched_by_sentinel_has_no_way_to_the_token(self):
        dump = self.ws / "dump.json"
        body = (f"r = subprocess.run([sys.executable, {SENTINEL_PATH!r}, '--dir', ws, 'dashboard', '--no-open'], capture_output=True, text=True)\n"
                f"open({str(dump)!r}, 'w').write(json.dumps({{'env': dict(os.environ), 'argv': sys.argv, 'prompt': prompt, "
                "'dash_code': r.returncode, 'dash_out': r.stdout + r.stderr}))\nwrite_result()\n")
        ids = self.boot_dashboard(body, n=1)
        self.serve_dispatch()
        self.assertTrue(wait_until(lambda: self.task(ids[0])["state"] == "COMPLETED", 30), self.task(ids[0]))
        data = json.loads(dump.read_text())
        token = self.srv.token
        self.assertNotIn("SENTINEL_DASHBOARD_TOKEN", data["env"])
        self.assertNotIn(token, json.dumps(data["env"]))
        self.assertNotIn(token, json.dumps(data["argv"]))
        self.assertNotIn(token, data["prompt"])
        self.assertEqual(data["dash_code"], 5)
        self.assertIn("E_ACTOR", data["dash_out"])


SENTINEL_PATH = str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts" / "sentinel.py")


class Control(SV):
    def setUp(self):
        super().setUp()
        self.executing(tier=3)
        self.serve()
        self.url = f"/api/v1/tasks/{SLUG}/control"

    def ctl(self, body, **kw):
        return self.http.post(self.url, body, **kw)

    def test_AC_MON_02a_cancelling_a_run_with_a_running_task(self):
        tid = self.make("docs", ["backend"], ["backend/docs/**"])
        # a task running under its own process group, recorded as a CLI task
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(lambda: (proc.poll() is None and (os.killpg(proc.pid, signal.SIGKILL), proc.wait())))
        from adapters import process_start_time
        self.eng.queue_task(tid)
        self.eng.start_task(tid, pid=proc.pid, pid_started_at=process_start_time(proc.pid), schedule=False)
        self.set_row(tid, adapter="cli")
        lock = self.ws / ".sentinel" / "shared" / "locks" / SLUG
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("dev\n")
        r = self.ctl({"action": "cancel", "comment": "wrong ticket"})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json["state"], "CANCELLED")
        self.assertEqual(self.task(tid)["state"], "CANCELLED")
        self.assertTrue(wait_until(lambda: proc.poll() is not None, 15))
        self.assertEqual(proc.returncode, -signal.SIGTERM)
        self.assertFalse(lock.exists())
        ev = [e for e in self.events_rows(type="run.state_changed") if json.loads(e["payload"])["transition"] == "R23"][0]
        self.assertEqual((ev["actor"], ev["channel"]), ("human", "dashboard"))
        row = [a for a in self.audit_rows() if a["action"] == "cancel"][0]
        self.assertEqual((row["channel"], row["target"], row["reason"]), ("dashboard", SLUG, "wrong ticket"))

    def set_row(self, tid, **fields):
        with self.eng.reg.transaction():
            self.eng.reg.update_row("tasks", tid, **fields)

    def test_AC_MON_02b_cancelling_one_task(self):
        red = self.make("tdd_red")
        green = self.make("tdd_green")
        with self.eng.reg.transaction():
            self.eng.reg.add_task_dep(green, red)
        self.eng.queue_task(red)
        r = self.ctl({"action": "cancel", "task_id": red})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual((self.task(red)["state"], self.task(green)["state"]), ("CANCELLED", "CANCELLED"))
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(self.ev(red, "task.finished")[-1]["actor"], "human")
        row = [a for a in self.audit_rows() if a["action"] == "cancel"][0]
        self.assertEqual((row["channel"], row["target"]), ("dashboard", f"{SLUG}/{red}"))

    def test_AC_MON_02c_resuming_a_run_that_needs_a_human(self):
        with self.eng.reg.transaction():
            self.eng._move(self.run_row(), "NEEDS_HUMAN", "engine", reason="red retry cap reached")
        r = self.ctl({"action": "resume", "comment": "test data fixed"})
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(self.state(), "EXECUTING")
        ev = self.events_rows(type="run.state_changed")[-1]
        p = json.loads(ev["payload"])
        self.assertEqual((ev["actor"], ev["channel"], p["transition"], p["reason"]), ("human", "dashboard", "R20", "test data fixed"))

    def test_AC_MON_02d_retrying_a_failed_task(self):
        tid = self.make("docs")
        self.eng.queue_task(tid)
        self.eng.start_task(tid, schedule=False)
        self.write_result(tid, "garbage")
        self.set_row(tid, state="FAILED", error_code="E_EXIT", attempt=3)
        r = self.ctl({"action": "retry", "task_id": tid})
        self.assertEqual(r.status, 200, r.text)
        retries = [t for t in self.eng.reg.rows("tasks", run_id=self.run_row()["id"]) if t["retry_of"] == tid]
        self.assertEqual([t["state"] for t in retries], ["QUEUED"])
        self.assertEqual(self.state(), "EXECUTING")
        row = [a for a in self.audit_rows() if a["action"] == "retry"][0]
        self.assertEqual(row["channel"], "dashboard")

    def test_AC_MON_02e_controls_refused_by_the_engine(self):
        done = self.make("docs")
        self.set_row(done, state="COMPLETED")
        before = [(t["id"], t["state"]) for t in self.eng.reg.rows("tasks")]
        rows = [({"action": "resume", "comment": "go"}, 409, "E_TRANSITION"),
                ({"action": "retry", "task_id": done}, 409, "E_TRANSITION"),
                ({"action": "cancel", "task_id": done}, 409, "E_TRANSITION"),
                ({"action": "cancel", "task_id": "t-other"}, 404, "E_NOT_FOUND")]
        for body, status, code in rows:
            with self.subTest(body=body):
                r = self.ctl(body)
                self.assertEqual((r.status, r.code), (status, code), r.text)
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(before, [(t["id"], t["state"]) for t in self.eng.reg.rows("tasks")])
        for state in ("COMPLETED", "CANCELLED"):
            with self.subTest(state=state):
                self.mk(f"run-{state.lower()}", state, 1)
                r = self.http.post(f"/api/v1/tasks/run-{state.lower()}/control", {"action": "cancel"})
                self.assertEqual((r.status, r.code), (409, "E_TRANSITION"))
        self.eng.reg.insert_run({"slug": "old-fix", "tier": 2, "state": "LEGACY", "workflow_version": "0.1",
                                 "execution_status": "running", "acceptance_status": "pending"})
        r = self.http.post("/api/v1/tasks/old-fix/control", {"action": "cancel"})
        self.assertEqual((r.status, r.code), (409, "E_TRANSITION"))

    def test_AC_MON_02f_unknown_or_incomplete_control_bodies(self):
        with self.eng.reg.transaction():
            self.eng._move(self.run_row(), "NEEDS_HUMAN", "engine", reason="x")
        for body in ({"action": "pause"}, {"action": "delete"}, {}, {"action": "resume"}, {"action": "resume", "comment": ""},
                     {"action": "retry"}, {"action": "intervene"}):
            with self.subTest(body=body):
                r = self.ctl(body)
                self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)
        self.assertEqual(self.state(), "NEEDS_HUMAN")

    def test_AC_MON_02h_dashboard_cancel_and_terminal_finish_at_the_same_moment(self):
        p = self.tty("run", "finish", SLUG, "--outcome", "stopped")
        r = self.http.post(self.url, {"action": "cancel"})
        code, out = p.finish(30)
        self.assertEqual(self.state(), "CANCELLED")
        self.assertEqual((r.status == 200) + (code == 0), 1, (r.text, code, out))
        r23 = [e for e in self.eng.reg.list_events(self.run_row()["id"], "run.state_changed") if e["payload"]["transition"] == "R23"]
        self.assertEqual(len(r23), 1)
        if r.status != 200:
            self.assertEqual(r.code, "E_TRANSITION")
        else:
            self.assertEqual(code, 5, out)

    def test_AC_MON_02i_the_registry_write_fails_during_a_cancel(self):
        proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(lambda: (proc.poll() is None and (os.killpg(proc.pid, signal.SIGKILL), proc.wait())))
        from adapters import process_start_time
        tid = self.make("docs")
        self.eng.queue_task(tid)
        self.eng.start_task(tid, pid=proc.pid, pid_started_at=process_start_time(proc.pid), schedule=False)
        self.set_row(tid, adapter="cli")
        events = len(self.events_rows())
        with fail_next_write():
            r = self.ctl({"action": "cancel"})
        self.assertEqual((r.status, r.code), (500, "E_INTERNAL"), r.text)
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(len(self.events_rows()), events)
        self.assertIsNone(proc.poll())

    def test_dashboard_dropped_controls_are_refused(self):
        for action in ("pause", "request_intervention", "request intervention"):
            r = self.ctl({"action": action})
            self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))
        self.assertEqual(self.state(), "EXECUTING")


class Race(SV):
    def test_AC_MON_02g_cancel_races_with_a_task_that_finishes(self):
        self.boot({"fake": ("time.sleep(1)\nwrite_result()\n", {})}, {"docs": "fake"})
        self.serve()
        tid = self.docs_task()
        p = self.popen("task", "run", tid)
        self.assertTrue(wait_until(lambda: self.task(tid)["state"] == "RUNNING", 20))
        time.sleep(0.8)
        r = self.http.post(f"/api/v1/tasks/{SLUG}/control", {"action": "cancel"})
        code, o, e = self.finish(p)
        self.assertIn(r.status, (200, 409), r.text)
        final = self.state()
        if r.status == 200:
            self.assertEqual((final, self.task(tid)["state"]), ("CANCELLED", "CANCELLED"))
        else:
            self.assertEqual(r.code, "E_TRANSITION")
        evs = self.eng.reg.list_events(self.run_row()["id"], "run.state_changed")
        self.assertEqual(evs[-1]["payload"]["to"], final)


if __name__ == "__main__":
    unittest.main()
