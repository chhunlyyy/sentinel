"""Phase F: read endpoints (read_api.feature)."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

from sv_helpers import SV, SLUG, SENTINEL, Http, spec_text

SECRET = "hunter2-secret"


class ReadBase(SV):
    def setUp(self):
        super().setUp()
        (self.ws / ".env").write_text(f"DB_PASSWORD={SECRET}\n")

    @contextmanager
    def in_ws(self, ws, eng):
        saved = (self.ws, self.eng)
        self.ws, self.eng = ws, eng
        try:
            yield
        finally:
            self.ws, self.eng = saved

    def set_task(self, tid, **fields):
        with self.eng.reg.transaction():
            self.eng.reg.update_row("tasks", tid, **fields)

    def sql(self, sql, args=(), ws=None):
        conn = sqlite3.connect((ws or self.ws) / ".sentinel" / "sentinel.db")
        try:
            conn.execute(sql, args)
            conn.commit()
        finally:
            conn.close()

    def many_runs(self, n, ws=None, eng=None):
        eng = eng or self.eng
        with eng.reg.transaction():
            for i in range(n):
                eng.reg.insert_run({"slug": f"run-{i:03d}", "type": "feature", "tier": 1, "state": "CREATED",
                                    "workflow_version": "2", "execution_status": "running",
                                    "acceptance_status": "pending", "created_at": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}.000000Z",
                                    "updated_at": f"2026-01-01T{i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}.000000Z"})


class Projects(ReadBase):
    def test_AC_API_01o_listing_the_registered_projects(self):
        self.to_spec_review("run-a")
        self.mk("run-b", "EXECUTING", 1)
        d, eng = self.extra_workspace("payroll")
        self.serve()
        r = self.http.get("/api/v1/projects")
        self.assertEqual(r.status, 200)
        j = r.json
        self.assertIsNone(j["next"])
        by = {i["id"]: i for i in j["items"]}
        self.assertEqual(set(by), {"digital-hr", "payroll"})
        for i in by.values():
            self.assertTrue({"id", "name", "path", "status", "active_runs"} <= set(i))
            self.assertEqual(i["status"], "available")
        self.assertEqual((by["digital-hr"]["active_runs"], by["payroll"]["active_runs"]), (2, 0))

    def test_AC_API_01p_a_project_that_cannot_be_opened_is_unavailable(self):
        reasons = {"missing": "workspace missing", "badcfg": "invalid configuration", "newdb": "E_MIGRATION"}
        for pid, reason in reasons.items():
            d, eng = self.extra_workspace(pid)
            eng.close()
            if reason == "workspace missing":
                shutil.rmtree(d)
            elif reason == "invalid configuration":
                (d / "sentinel.config.yaml").write_text("repos: [unclosed\n")
            else:
                self.sql("UPDATE meta SET value='999' WHERE key='schema_version'", ws=d)
        self.add_project()
        self.serve(register=False)
        items = {i["id"]: i for i in self.http.get("/api/v1/projects").json["items"]}
        self.assertEqual(items["digital-hr"]["status"], "available")
        for pid, reason in reasons.items():
            self.assertEqual((items[pid]["status"], items[pid]["reason"]), ("unavailable", reason))
            r = self.http.get(f"/api/v1/projects/{pid}/tasks")
            self.assertEqual((r.status, r.code), (422, "E_PRECONDITION"))
            self.assertIn(reason, r.text)

    def test_AC_API_01q_no_project_registered(self):
        self.serve(register=False)
        r = self.http.get("/api/v1/projects")
        self.assertEqual((r.status, r.json), (200, {"items": [], "next": None}))

    def test_AC_API_01r_an_unknown_project_id(self):
        self.serve()
        r = self.http.get("/api/v1/projects/no-such-project")
        self.assertEqual((r.status, r.code), (404, "E_NOT_FOUND"))


class Runs(ReadBase):
    def test_AC_API_01s_listing_the_runs_of_a_project(self):
        self.executing(slug="leave-balance", tier=3) if False else None
        self.to_gherkin_approved("leave-balance", 3)
        self.eng.advance("leave-balance")
        self.mk("leave-form", "COMPLETED", 1)
        self.eng.reg.insert_run({"slug": "old-fix", "tier": 2, "state": "LEGACY", "workflow_version": "0.1",
                                 "execution_status": "completed", "acceptance_status": "accepted"})
        self.sql("UPDATE runs SET acceptance_status='accepted', execution_status='completed' WHERE slug='leave-form'")
        self.serve()
        r = self.http.get("/api/v1/projects/digital-hr/tasks")
        self.assertEqual(r.status, r.status and 200, r.text)
        items = r.json["items"]
        self.assertEqual({i["slug"] for i in items}, {"leave-balance", "leave-form", "old-fix"})
        for i in items:
            self.assertTrue({"slug", "type", "tier", "state", "execution_status", "acceptance_status",
                             "workflow_version", "updated_at"} <= set(i))
        by = {i["slug"]: i for i in items}
        self.assertEqual(by["leave-balance"]["state"], "EXECUTING")
        self.assertEqual(by["leave-balance"]["tier"], 3)
        self.assertEqual((by["leave-form"]["state"], by["leave-form"]["acceptance_status"]), ("COMPLETED", "accepted"))
        self.assertEqual((by["old-fix"]["workflow_version"], by["old-fix"]["state"]), ("0.1", "LEGACY"))
        stamps = [i["updated_at"] for i in items]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_AC_API_01t_paging_through_runs(self):
        self.many_runs(120)
        self.serve()
        rows = [("", 200, 50, True), ("?limit=200", 200, 120, False), ("?limit=1", 200, 1, True), ("?limit=0", 400, 0, 0),
                ("?limit=201", 400, 0, 0), ("?limit=abc", 400, 0, 0), ("?cursor=not-a-cursor", 400, 0, 0)]
        for query, status, count, more in rows:
            with self.subTest(query=query):
                r = self.http.get("/api/v1/projects/digital-hr/tasks" + query)
                self.assertEqual(r.status, status, r.text)
                if status == 200:
                    self.assertEqual(len(r.json["items"]), count)
                    self.assertEqual(r.json["next"] is not None, more)
                else:
                    self.assertEqual(r.code, "E_VALIDATION")

    def test_AC_API_01u_following_cursors_returns_every_run_once(self):
        self.many_runs(120)
        self.serve()
        seen, cursor, page = [], None, 0
        while True:
            q = "?limit=50" + (f"&cursor={cursor}" if cursor else "")
            r = self.http.get("/api/v1/projects/digital-hr/tasks" + q)
            self.assertEqual(r.status, 200, r.text)
            seen += [i["slug"] for i in r.json["items"]]
            page += 1
            if page == 1:
                self.mk("brand-new", "CREATED", 1)
            cursor = r.json["next"]
            if not cursor:
                break
        old = [s for s in seen if s.startswith("run-")]
        self.assertEqual(len(old), 120)
        self.assertEqual(len(set(seen)), len(seen))

    def test_AC_API_01v_run_detail(self):
        self.executing(tier=3)
        with self.eng.reg.transaction():
            self.eng.reg.add_run_repo(self.run_row()["id"], "frontend", "def")
        self.serve()
        r = self.http.get(f"/api/v1/tasks/{SLUG}")
        self.assertEqual(r.status, 200, r.text)
        j = r.json
        self.assertEqual((j["slug"], j["project"], j["tier"], j["initial_tier"], j["state"]),
                         (SLUG, "digital-hr", 3, 3, "EXECUTING"))
        self.assertIn("execution_status", j)
        self.assertIn("acceptance_status", j)
        self.assertEqual({x["repo_id"] for x in j["repos"]}, {"backend", "frontend"})
        for repo in j["repos"]:
            self.assertTrue({"baseline_sha", "branch", "final_sha"} <= set(repo))
            self.assertIsNone(repo["final_sha"])
        for gate in ("specification", "gherkin"):
            a = j["approvals"][gate]
            self.assertEqual(a["state"], "APPROVED")
            self.assertRegex(a["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(a["version"], 1)
        self.assertIn("task_counts", j)
        self.assertEqual(j["next"]["kind"], self.cli_next()["kind"])

    def cli_next(self, slug=SLUG):
        code, out, err = self.cli("next", slug, "--json")
        return json.loads(out)

    def test_AC_API_01w_bad_or_unknown_run_slugs(self):
        self.serve()
        for slug, status, code in (("no-such-run", 404, "E_NOT_FOUND"), ("Leave_Balance", 400, "E_VALIDATION"),
                                   ("a..b", 400, "E_VALIDATION"), ("x.lock", 400, "E_VALIDATION")):
            with self.subTest(slug=slug):
                r = self.http.get(f"/api/v1/tasks/{slug}")
                self.assertEqual((r.status, r.code), (status, code))

    def test_AC_API_01x_a_slug_in_two_projects_needs_the_project_parameter(self):
        self.mk(SLUG, "CREATED", 1)
        d, eng = self.extra_workspace("payroll")
        with self.in_ws(d, eng):
            self.mk(SLUG, "CREATED", 1)
        self.serve()
        r = self.http.get(f"/api/v1/tasks/{SLUG}")
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))
        self.assertEqual(sorted(r.json["error"]["details"]["projects"]), ["digital-hr", "payroll"])
        r = self.http.get(f"/api/v1/tasks/{SLUG}?project=payroll")
        self.assertEqual((r.status, r.json["project"]), (200, "payroll"))
        r = self.http.get(f"/api/v1/tasks/{SLUG}?project=nope")
        self.assertEqual((r.status, r.code), (404, "E_NOT_FOUND"))

    def test_AC_API_03a_the_next_endpoint_returns_what_the_cli_returns(self):
        self.executing(tier=3)
        self.make("docs", queue=False)
        self.eng.queue_task(self.make("docs"))
        self.serve()
        api = self.http.get(f"/api/v1/tasks/{SLUG}/next")
        self.assertEqual(api.status, 200, api.text)
        self.assertEqual(api.json, self.cli_next())


class Views(ReadBase):
    def setUp(self):
        super().setUp()
        self.executing(tier=3)

    def test_AC_MON_01a_the_workflow_graph_shows_the_real_tasks(self):
        spec = self.make("specifier", queue=False)
        green = self.make("tdd_green")
        retry = self.make("tdd_green", retry_of=green, attempt=2)
        qa = self.make("qa")
        self.set_task(spec, state="COMPLETED", seconds=3.5, started_at="2026-01-01T00:00:00.000000Z")
        self.set_task(green, state="FAILED", error_code="E_EXIT", attempt=1)
        self.set_task(retry, state="QUEUED")
        self.set_task(qa, state="WAITING_FOR_INPUT", adapter="native")
        with self.eng.reg.transaction():
            self.eng.reg.add_task_dep(green, spec)
        self.serve()
        r = self.http.get(f"/api/v1/tasks/{SLUG}/workflow")
        self.assertEqual(r.status, 200, r.text)
        j = r.json
        nodes = {n["id"]: n for n in j["nodes"]}
        for key in ("id", "role", "repo", "state", "adapter", "provider", "model", "attempt", "retry_of", "error_code",
                    "started_at", "finished_at", "seconds"):
            self.assertIn(key, nodes[green])
        self.assertEqual((nodes[green]["state"], nodes[green]["error_code"]), ("FAILED", "E_EXIT"))
        self.assertEqual(nodes[retry]["retry_of"], green)
        self.assertIn({"from": spec, "to": green}, j["edges"])
        self.assertEqual({g["gate"]: g["state"] for g in j["gates"]}, {"specification": "APPROVED", "gherkin": "APPROVED"})
        self.assertEqual(nodes[qa]["label"], "waiting for orchestrator")

    def test_AC_MON_01b_other_run_views(self):
        eng = self.eng
        run = self.run_row()
        with eng.reg.transaction():
            cid = eng.reg.insert_row("cycles", {"run_id": run["id"], "behavior": "balance shown", "state": "RED_RUNNING"})
            eng.reg.insert_row("evidence", {"run_id": run["id"], "cycle_id": cid, "kind": "test", "exit_code": 1,
                                            "passed": 0, "failed": 2, "classification": "valid_red"})
            eng.reg.add_trace_link(run["id"], "ac", "AC-1", "scenario", "balance.feature::a")
        rd = self.ws / ".sentinel" / "runs" / SLUG
        (rd / "report.json").write_text(json.dumps({"slug": SLUG, "result": "pending"}))
        self.serve()
        base = f"/api/v1/tasks/{SLUG}"
        r = self.http.get(f"{base}/tdd")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.json["cycles"][0]["behavior"], "balance shown")
        self.assertEqual(len(r.json["cycles"][0]["evidence_ids"]), 1)
        r = self.http.get(f"{base}/verification")
        self.assertEqual(r.status, 200)
        self.assertEqual(len(r.json["evidence"]), 1)
        self.assertIn("acceptance", r.json)
        r = self.http.get(f"{base}/trace")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.json["links"])
        self.assertIn("gaps", r.json)
        r = self.http.get(f"{base}/specification")
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json["version"], 1)
        self.assertRegex(r.json["sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("validation", r.json)
        self.assertIn("diff", r.json)
        r = self.http.get(f"{base}/specification/versions/1")
        self.assertEqual((r.status, r.json["version"]), (200, 1))
        self.assertEqual(self.http.get(f"{base}/specification/versions/9").status, 404)
        r = self.http.get(f"{base}/gherkin")
        self.assertEqual(r.status, 200, r.text)
        self.assertTrue(r.json["scenarios"] and r.json["files"])
        self.assertIn("coverage", r.json)
        self.assertRegex(r.json["sha256"], r"^[0-9a-f]{64}$")
        r = self.http.get(f"{base}/report")
        self.assertEqual((r.status, r.json["report"]["slug"]), (200, SLUG))
        self.assertRegex(r.json["sha256"], r"^[0-9a-f]{64}$")

    def test_AC_MON_01c_a_new_run_has_empty_views_not_errors(self):
        self.mk("leave-form", "CREATED", 1)
        self.serve()
        for view in ("workflow", "tdd", "verification", "trace"):
            with self.subTest(view=view):
                r = self.http.get(f"/api/v1/tasks/leave-form/{view}")
                self.assertEqual(r.status, 200, r.text)
        self.assertEqual(self.http.get("/api/v1/tasks/leave-form/workflow").json["nodes"], [])
        r = self.http.get("/api/v1/tasks/leave-form/report")
        self.assertEqual((r.status, r.code), (422, "E_PRECONDITION"))

    def test_AC_API_01y_listing_approvals_in_review_across_projects(self):
        self.eng.reg  # leave-balance of digital-hr is executing; add review runs
        self.to_spec_review("review-run", 3)
        d, eng = self.extra_workspace("payroll")
        with self.in_ws(d, eng):
            self.to_gherkin_review("tax-form", 3)
        self.serve()
        r = self.http.get("/api/v1/approvals?state=IN_REVIEW")
        self.assertEqual(r.status, 200, r.text)
        got = {(i["project"], i["slug"], i["gate"]) for i in r.json["items"]}
        self.assertEqual(got, {("digital-hr", "review-run", "specification"), ("payroll", "tax-form", "gherkin")})
        for i in r.json["items"]:
            self.assertTrue({"version", "sha256", "requested_at"} <= set(i))
            self.assertRegex(i["sha256"], r"^[0-9a-f]{64}$")

    def test_AC_API_01z_an_unknown_approval_state_filter(self):
        self.serve()
        r = self.http.get("/api/v1/approvals?state=MAYBE")
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))
        self.assertIn("IN_REVIEW", r.text)


class Scrubbing(ReadBase):
    def setUp(self):
        super().setUp()
        self.executing(tier=3)
        self.rd = self.ws / ".sentinel" / "runs" / SLUG

    def artifact(self, aid, text, kind="evidence_output", name=None):
        name = name or f"{aid}.txt"
        p = self.rd / "evidence" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        with self.eng.reg.transaction():
            self.eng.reg.insert_row("artifacts", {"id": aid, "run_id": self.run_row()["id"], "kind": kind, "version": 1,
                                                  "path": str(p.relative_to(self.ws / ".sentinel")), "sha256": sha,
                                                  "created_at": "2026-01-01T00:00:00Z"})
        return p, sha

    def test_AC_SEC_06c_served_content_is_scrubbed(self):
        line = f"password={SECRET}\n"
        self.artifact("a-out1", "ok\n" + line)
        self.artifact("a-res1", json.dumps({"summary": f"password={SECRET}"}), kind="result", name="result.json")
        tid = self.make("docs", queue=False)
        tdir = self.tdir(tid)
        (tdir / "output.log").write_text("start\n" + line)
        (self.rd / "report.md").write_text("# Report\n" + line)
        self.serve()
        for path in (f"/api/v1/tasks/{SLUG}/artifacts/a-out1", f"/api/v1/tasks/{SLUG}/logs/{tid}",
                     f"/api/v1/tasks/{SLUG}/report?format=md", f"/api/v1/tasks/{SLUG}/artifacts/a-res1"):
            with self.subTest(path=path):
                r = self.http.get(path)
                self.assertEqual(r.status, 200, r.text)
                self.assertNotIn(SECRET, r.text)
                self.assertIn("[REDACTED", r.text)

    def test_AC_SEC_06d_an_artifact_changed_on_disk_is_not_served_as_valid(self):
        art = self.artifacts("spec")[0]
        stored = self.rd / "artifacts" / "spec-v1.md"
        stored.write_text(stored.read_text() + "\nsneaky edit\n")
        self.serve()
        r = self.http.get(f"/api/v1/tasks/{SLUG}/artifacts/{art['id']}")
        self.assertEqual((r.status, r.code), (409, "E_INTEGRITY"))
        self.assertEqual(r.json["error"]["details"]["stored_sha256"], art["sha256"])
        self.assertNotIn("sneaky edit", r.text)

    def test_AC_SEC_06e_artifacts_and_logs_are_looked_up_by_id_within_the_run(self):
        d, eng = self.extra_workspace("payroll")
        with self.in_ws(d, eng):
            self.mk("other-run", "CREATED", 1)
            other_task = self.make("docs", slug="other-run", queue=False)
            self.artifact_other = None
        self.serve()
        base = f"/api/v1/tasks/{SLUG}"
        for path in (f"{base}/artifacts/a-unknown", f"{base}/logs/{other_task}", f"{base}/artifacts/ar-000000000000"):
            with self.subTest(path=path):
                r = self.http.get(path)
                self.assertEqual((r.status, r.code), (404, "E_NOT_FOUND"))

    def test_AC_SEC_06d_an_artifact_row_pointing_outside_the_run_folder_is_not_found(self):
        with self.eng.reg.transaction():
            self.eng.reg.insert_row("artifacts", {"id": "a-evil", "run_id": self.run_row()["id"], "kind": "x", "version": 1,
                                                  "path": "../../../etc/hostname", "sha256": "0" * 64})
        self.serve()
        r = self.http.get(f"/api/v1/tasks/{SLUG}/artifacts/a-evil")
        self.assertEqual(r.status, 404)

    def running_task(self, lines=3):
        tid = self.make("docs", queue=False)
        self.set_task(tid, state="RUNNING")
        log = self.tdir(tid) / "output.log"
        log.write_text("".join(f"{i}".ljust(39, "x") + "\n" for i in range(lines)))
        return tid, log

    def test_AC_MON_03a_tailing_a_live_log_by_offset(self):
        tid, log = self.running_task(3)
        self.serve()
        r = self.http.get(f"/api/v1/tasks/{SLUG}/logs/{tid}?offset=0")
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual((len(r.json["lines"]), r.json["next_offset"], r.json["running"]), (3, 120, True))
        with open(log, "a") as f:
            f.write("a".ljust(39, "x") + "\n" + "b".ljust(39, "x") + "\n")
        r = self.http.get(f"/api/v1/tasks/{SLUG}/logs/{tid}?offset=120")
        self.assertEqual(len(r.json["lines"]), 2)
        self.assertEqual(r.json["next_offset"], 200)

    def test_AC_MON_03b_log_offsets(self):
        tid, log = self.running_task(3)
        with open(log, "a") as f:
            f.write("x" * 14 + "y")
        self.serve()
        rows = [("120", 200), ("135", 400), ("9999", 400), ("-1", 400)]
        for offset, status in rows:
            with self.subTest(offset=offset):
                r = self.http.get(f"/api/v1/tasks/{SLUG}/logs/{tid}?offset={offset}")
                self.assertEqual(r.status, status, r.text)
                if status == 200:
                    self.assertEqual((r.json["lines"], r.json["next_offset"]), ([], 120))
                else:
                    self.assertEqual(r.code, "E_VALIDATION")

    def test_AC_MON_03c_a_task_that_has_not_started_has_an_empty_log(self):
        tid = self.make("qa")
        self.serve()
        r = self.http.get(f"/api/v1/tasks/{SLUG}/logs/{tid}")
        self.assertEqual((r.status, r.json["lines"], r.json["next_offset"], r.json["running"]), (200, [], 0, False))

    def test_AC_SEC_07a_reading_the_audit_log_of_a_project(self):
        self.eng.audit("dev", "tty", "approved", f"{SLUG}/specification")
        self.eng.audit("dev", "dashboard", "cancel", SLUG, reason="stop")
        self.serve()
        r = self.http.get("/api/v1/audit?project=digital-hr")
        self.assertEqual(r.status, 200, r.text)
        items = r.json["items"]
        for key in ("actor", "channel", "action", "target", "before_sha", "after_sha", "reason", "at"):
            self.assertIn(key, items[0])
        self.assertEqual(items[0]["channel"], "dashboard")
        self.assertEqual(items[0]["action"], "cancel")
        self.assertIn("approved", [i["action"] for i in items])

    def test_AC_SEC_02k_installation_and_runtime_information(self):
        self.serve()
        inst = self.http.get("/api/v1/installation")
        rt = self.http.get("/api/v1/runtime")
        self.assertEqual(inst.status, 200)
        for key in ("version", "install_path", "python", "method"):
            self.assertIn(key, inst.json)
        self.assertEqual(rt.json["port"], self.srv.port)
        self.assertTrue(rt.json["started_at"] and rt.json["projects"])
        for r in (inst, rt):
            self.assertNotIn(self.srv.token, r.text)
            self.assertNotIn(self.http.csrf, r.text)

    def test_AC_MON_01d_reads_stay_fast_on_a_large_run(self):
        self.mk("big-run", "EXECUTING", 3)
        run = self.eng.reg.get_run("big-run")
        conn = sqlite3.connect(self.ws / ".sentinel" / "sentinel.db")
        conn.executemany("INSERT INTO tasks(id, run_id, role, repo_id, state, adapter, provider, attempt) VALUES (?,?,?,?,?,?,?,?)",
                         [(f"t-{i:012x}", run["id"], "docs", "backend", "COMPLETED", "cli", "fake", 1) for i in range(500)])
        conn.executemany("INSERT INTO task_deps(task_id, depends_on) VALUES (?,?)",
                         [(f"t-{i:012x}", f"t-{i - 1:012x}") for i in range(1, 500)])
        conn.executemany("INSERT INTO evidence(id, run_id, kind, exit_code, passed, failed) VALUES (?,?,?,?,?,?)",
                         [(f"e-{i}", run["id"], "test", 0, 1, 0) for i in range(200)])
        conn.executemany("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)",
                         [(run["id"], "task.progress", "engine", "{}", "2026-01-01T00:00:00Z") for _ in range(10000)])
        conn.commit()
        conn.close()
        self.serve()
        for path in ("/api/v1/tasks/big-run", "/api/v1/tasks/big-run/workflow"):
            for _ in range(10):
                t0 = time.time()
                r = self.http.get(path)
                self.assertEqual(r.status, 200, r.text[:300])
                self.assertLess(time.time() - t0, 1.0, path)

    def test_AC_MON_01e_reads_during_cli_writes_do_not_fail(self):
        self.serve()
        script = ("import sys; sys.path.insert(0, %r)\nfrom registry import Registry\n"
                  "reg = Registry.open(%r)\nrun = reg.get_run(%r)\n"
                  "for i in range(200):\n    with reg.transaction():\n        reg.add_event(run['id'], 'task.progress', 'engine', {'i': i})\n"
                  % (str(Path(SENTINEL).parent), str(self.ws / ".sentinel"), SLUG))
        writer = subprocess.Popen([sys.executable, "-c", script])
        self.addCleanup(lambda: (writer.poll() is None and writer.kill(), writer.wait()))
        results = []

        def reader():
            c = self.client()
            for _ in range(50):
                r = c.get(f"/api/v1/tasks/{SLUG}")
                results.append((r.status, r.text))
        threads = [threading.Thread(target=reader) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        writer.wait(60)
        self.assertEqual(len(results), 400)
        bad = [x for x in results if x[0] != 200]
        self.assertEqual(bad[:2], [])


if __name__ == "__main__":
    unittest.main()
