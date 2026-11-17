"""Phase H part A: local analytics (plan/v1.1/phaseH/features/analytics.feature)."""
import hashlib
import json
import sqlite3
import threading
import time
import unittest
from pathlib import Path

from sv_helpers import SV

QUERIES = Path(__file__).resolve().parent / "fixtures" / "analytics_queries.sql"
SMALL_RUNS = [  # id, type, state, created, finished, acceptance, spec versions, gherkin versions
    ("r-one", "feature", "COMPLETED", "2026-11-01T09:00:00.000000Z", "2026-11-01T13:00:00.000000Z", "accepted", 1, 2),
    ("r-two", "bug", "COMPLETED", "2026-11-02T09:00:00.000000Z", "2026-11-02T11:00:00.000000Z", "rejected", 2, 1),
    ("r-thr", "feature", "FAILED", "2026-11-03T09:00:00.000000Z", "2026-11-03T10:00:00.000000Z", "pending", 1, 1),
    ("r-fou", "feature", "EXECUTING", "2026-11-04T09:00:00.000000Z", None, "pending", 1, 1),
]


def at(day, hhmm):
    return f"2026-11-{day}T{hhmm}:00.000000Z"


def build_small(db_path):
    """The registry fixture "analytics-small": four version 2 runs, one 0.1 run, tasks, approvals, cycles, evidence, events."""
    c = sqlite3.connect(db_path, timeout=20)
    c.execute("PRAGMA busy_timeout=20000")
    try:
        for rid, typ, state, created, finished, acc, nspec, ngh in SMALL_RUNS:
            ex = {"COMPLETED": "completed", "FAILED": "failed", "EXECUTING": "running"}[state]
            c.execute("INSERT INTO runs(id, slug, type, state, execution_status, acceptance_status, workflow_version, created_at, "
                      "updated_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (rid, rid, typ, state, ex, acc, "2", created, created, finished))
            for v in range(1, nspec + 1):
                c.execute("INSERT INTO artifacts(id, run_id, kind, version) VALUES (?,?,?,?)", (f"{rid}-s{v}", rid, "spec", v))
            for v in range(1, ngh + 1):
                c.execute("INSERT INTO artifacts(id, run_id, kind, version) VALUES (?,?,?,?)", (f"{rid}-g{v}", rid, "gherkin", v))
        c.execute("INSERT INTO runs(id, slug, type, state, execution_status, acceptance_status, workflow_version, created_at, updated_at) "
                  "VALUES ('r-old','old-fix','feature','LEGACY','completed','accepted','0.1','2026-11-02T08:00:00.000000Z','2026-11-02T08:00:00.000000Z')")
        tasks = [  # id, run, role, provider, state, error, seconds, cost, retry_of
            ("t1", "r-one", "tdd_green", "codex", "COMPLETED", None, 100, 1.0, None),
            ("t2", "r-one", "tdd_green", "codex", "COMPLETED", None, 300, 2.0, None),
            ("t3", "r-one", "specifier", "claude", "COMPLETED", None, 60, 0.5, None),
            ("t4", "r-two", "tdd_green", "codex", "FAILED", "E_PROVIDER", 10, None, None),
            ("t5", "r-two", "tdd_green", "codex", "COMPLETED", None, 200, None, "t4"),
        ]
        for t in tasks:
            c.execute("INSERT INTO tasks(id, run_id, role, provider, state, error_code, seconds, cost, retry_of, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,'2026-11-01T09:00:00.000000Z')", t)
        approvals = [  # id, run, gate, version, requested, decided, decision
            ("a1", "r-one", "specification", 1, at("01", "09:10"), at("01", "09:40"), "approve"),
            ("a2", "r-one", "gherkin", 1, at("01", "10:00"), at("01", "10:20"), "approve"),
            ("a3", "r-two", "specification", 1, at("02", "09:10"), at("02", "09:20"), "changes_requested"),
            ("a4", "r-two", "specification", 2, at("02", "10:00"), at("02", "10:30"), "approve"),
        ]
        for aid, run, gate, ver, req, dec, decision in approvals:
            c.execute("INSERT INTO approvals(id, run_id, gate, version, state, decision, decided_at) VALUES (?,?,?,?,?,?,?)",
                      (aid, run, gate, ver, "APPROVED", decision, dec))
            c.execute("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)",
                      (run, "approval.requested", "engine", json.dumps({"gate": gate, "version": ver}), req))
            c.execute("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)",
                      (run, "approval.decided", "human", json.dumps({"gate": gate, "decision": decision}), dec))
        for rid, n in (("r-one", 2), ("r-two", 1)):
            for k in range(n):
                c.execute("INSERT INTO cycles(id, run_id, behavior, state) VALUES (?,?,?,?)",
                          (f"{rid}-c{k}", rid, f"b{k}", "CYCLE_ACCEPTED" if rid == "r-one" else "REJECTED"))
        for typ, run in (("green.rejected", "r-two"), ("finding.routed", "r-one"), ("finding.routed", "r-two")):
            c.execute("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)", (run, typ, "engine", "{}", at("02", "10:00")))
        ev = [("r-one", 1, "lint", "pass"), ("r-one", 1, "test", "fail"), ("r-one", 2, "lint", "pass"), ("r-one", 2, "test", "pass"),
              ("r-two", 1, "lint", "pass"), ("r-two", 1, "test", "pass"), ("r-two", 1, "scope", "not_configured")]
        for i, (run, rnd, kind, verdict) in enumerate(ev):
            c.execute("INSERT INTO evidence(id, run_id, kind, round, verdict) VALUES (?,?,?,?,?)", (f"e{i}", run, kind, rnd, verdict))
        c.commit()
    finally:
        c.close()


def query_file():
    """{name: sql} from tests/fixtures/analytics_queries.sql ('-- name: x' headers)."""
    out, name, buf = {}, None, []
    for line in QUERIES.read_text().splitlines():
        if line.startswith("-- name:"):
            if name:
                out[name] = "\n".join(buf)
            name, buf = line.split(":", 1)[1].strip(), []
        elif name:
            buf.append(line)
    if name:
        out[name] = "\n".join(buf)
    return out


class AN(SV):
    def setUp(self):
        super().setUp()
        self.eng.close()
        self.dbp = self.ws / ".sentinel" / "sentinel.db"
        build_small(self.dbp)

    def compute(self, start=None, end=None, **kw):
        import analytics
        return analytics.compute(self.dbp, start, end, **kw)

    def full(self, **kw):
        return self.compute("2026-11-01", "2026-11-30", **kw)

    def sql(self, sql, args=()):
        c = sqlite3.connect(self.dbp, timeout=20)
        try:
            c.execute(sql, args)
            c.commit()
        finally:
            c.close()

    def scalar(self, sql, args=()):
        c = sqlite3.connect(self.dbp)
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()

    def sha(self):
        return hashlib.sha256(self.dbp.read_bytes()).hexdigest()


class Metrics(AN):
    def test_AC_ANL_01a_each_metric_has_a_fixed_definition(self):
        a = self.full(providers=["codex", "gemini"])
        rows = {
            "runs.total": a["runs"]["total"] == 4,
            "runs.by_state.COMPLETED": a["runs"]["by_state"]["COMPLETED"] == 2,
            "runs.by_type.feature": a["runs"]["by_type"]["feature"] == 3,
            "lead_time_seconds": a["lead_time_seconds"] == {"count": 3, "median": 7200, "p90": 14400},
            "acceptance_rate": a["acceptance_rate"] == {"value": 0.5, "accepted": 1, "decided": 2},
            "approval_wait_seconds.specification": a["approval_wait_seconds"]["specification"] == {"count": 3, "median": 1800, "p90": 1800},
            "approval_wait_seconds.gherkin": a["approval_wait_seconds"]["gherkin"] == {"count": 1, "median": 1200, "p90": 1200},
            "tasks.by_role.tdd_green.count": a["tasks"]["by_role"]["tdd_green"]["count"] == 4,
            "tasks.by_role.tdd_green.median_seconds": a["tasks"]["by_role"]["tdd_green"]["median_seconds"] == 150,
            "retries.total": a["retries"]["total"] == 1,
            "provider_failure_rate.codex": a["provider_failure_rate"]["codex"] == {"value": 0.25, "failures": 1, "tasks": 4},
            "tdd.cycles": a["tdd"]["cycles"] == {"total": 3, "accepted": 2, "rejected": {"red": 0, "green": 1, "refactor": 0}},
            "verification.pass_rate": a["verification"]["pass_rate"]["lint"] == {"value": 1.0, "passed": 3, "total": 3}
            and a["verification"]["pass_rate"]["test"] == {"value": 2 / 3, "passed": 2, "total": 3}
            and "scope" not in a["verification"]["pass_rate"],
            "verification.first_attempt_pass_rate": a["verification"]["first_attempt_pass_rate"] == {"value": 0.5, "passed_first": 1, "verified": 2},
            "rework.spec_revisions": a["rework"]["spec_revisions"] == 1,
            "rework.gherkin_revisions": a["rework"]["gherkin_revisions"] == 1,
            "rework.changes_requested": a["rework"]["changes_requested"] == 1,
            "rework.findings_routed": a["rework"]["findings_routed"] == 2,
            "no 0.1 run": "old-fix" not in json.dumps(a) and a["runs"]["by_state"].get("LEGACY") is None,
        }
        for metric, ok in rows.items():
            with self.subTest(metric=metric):
                self.assertTrue(ok, f"{metric}: {a}")

    def test_AC_ANL_01b_metrics_are_recomputable_from_rows(self):
        first, second = self.full(), self.full()
        import analytics
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        queries = query_file()
        want = {
            "runs.total": first["runs"]["total"],
            "runs.finished": first["lead_time_seconds"]["count"],
            "lead_time.median": first["lead_time_seconds"]["median"],
            "acceptance.accepted": first["acceptance_rate"]["accepted"],
            "acceptance.decided": first["acceptance_rate"]["decided"],
            "tasks.total": sum(r["count"] for r in first["tasks"]["by_role"].values()),
            "retries.total": first["retries"]["total"],
            "provider.codex.failures": first["provider_failure_rate"]["codex"]["failures"],
            "provider.codex.finished": first["provider_failure_rate"]["codex"]["tasks"],
            "cost.total": first["cost"]["total"]["value"],
            "cost.reported": first["cost"]["total"]["reported_tasks"],
            "verification.lint.passed": first["verification"]["pass_rate"]["lint"]["passed"],
            "verification.test.total": first["verification"]["pass_rate"]["test"]["total"],
            "rework.spec_revisions": first["rework"]["spec_revisions"],
            "rework.findings_routed": first["rework"]["findings_routed"],
        }
        self.assertEqual(set(want), set(queries) & set(want))
        for name, expected in want.items():
            with self.subTest(query=name):
                got = self.scalar(queries[name])[0][0]
                self.assertAlmostEqual(float(got), float(expected), places=2)
        self.assertTrue(analytics.is_null(analytics.compute(self.ws / "none.db")))

    def test_AC_ANL_01c_cost_by_task_role_and_provider_when_every_task_reported_it(self):
        self.sql("UPDATE tasks SET cost = 4.0 WHERE cost IS NULL")
        c = self.full()["cost"]
        self.assertEqual(c["by_task"], {"t1": 1.0, "t2": 2.0, "t3": 0.5, "t4": 4.0, "t5": 4.0})
        self.assertEqual(c["by_role"], {"tdd_green": 11.0, "specifier": 0.5})
        self.assertEqual(c["by_provider"], {"codex": 11.0, "claude": 0.5})
        self.assertEqual(c["total"], {"value": 11.5, "partial": False, "reported_tasks": 5, "unreported_tasks": 0})
        self.assertFalse(c["partial"])

    def test_AC_ANL_02d_partly_reported_cost_is_marked_partial(self):
        self.sql("UPDATE tasks SET cost = NULL WHERE id IN ('t2')")
        self.sql("UPDATE tasks SET cost = 1.5 WHERE id IN ('t4','t5')")
        c = self.full()["cost"]
        self.assertEqual(c["total"], {"value": 4.5, "partial": True, "reported_tasks": 4, "unreported_tasks": 1})
        self.assertTrue(c["partial"])
        self.sql("UPDATE tasks SET tokens = 99999 WHERE cost IS NULL")
        self.assertEqual(self.full()["cost"]["total"]["value"], 4.5)  # nothing is derived from tokens

    def test_AC_ANL_02e_missing_metrics_are_null_with_a_reason(self):
        import analytics
        cases = []
        self.sql("UPDATE tasks SET cost = NULL")
        cases.append(("cost.total", lambda a: a["cost"]["total"], "not reported", self.full()))
        a = self.compute("2026-11-04", "2026-11-04")
        cases.append(("acceptance_rate", lambda a: a["acceptance_rate"], "no decided runs", a))
        cases.append(("lead_time_seconds", lambda a: a["lead_time_seconds"], "no finished runs", a))
        cases.append(("approval_wait_seconds", lambda a: a["approval_wait_seconds"], "no decided approvals", a))
        g = self.full(providers=["gemini"])
        cases.append(("provider_failure_rate.gemini", lambda a: a["provider_failure_rate"]["gemini"], "no tasks for this provider", g))
        for name, pick, reason, answer in cases:
            with self.subTest(metric=name):
                m = pick(answer)
                self.assertIsNone(m["value"])
                self.assertEqual(m["reason"], reason)
                self.assertTrue(analytics.is_null(m))

    def test_AC_ANL_02f_an_empty_range(self):
        a = self.compute("2025-01-01", "2025-01-31", providers=["codex"])
        self.assertEqual(a["runs"]["total"], 0)
        for name in ("lead_time_seconds", "acceptance_rate", "approval_wait_seconds"):
            self.assertEqual(a[name], {"value": None, "reason": "no runs in range"}, name)
        self.assertEqual(a["verification"]["pass_rate"]["reason"], "no runs in range")
        self.assertEqual(a["cost"]["total"]["reason"], "no runs in range")
        self.assertEqual(a["provider_failure_rate"]["codex"]["reason"], "no runs in range")

    def test_AC_ANL_01d_date_range_bounds(self):
        rows = [("2026-11-02", "2026-11-02", {"r-two"}), ("2026-11-01", "2026-11-03", {"r-one", "r-two", "r-thr"}),
                ("2026-11-04", None, {"r-fou"}), (None, "2026-11-01", {"r-one"})]
        for start, end, want in rows:
            with self.subTest(start=start, end=end):
                a = self.compute(start, end)
                self.assertEqual(a["runs"]["total"], len(want))
                ids = {r[0] for r in self.scalar(
                    "SELECT id FROM runs WHERE workflow_version='2' AND substr(created_at,1,10) >= ? AND substr(created_at,1,10) <= ?",
                    (start or "0000", end or "9999"))}
                self.assertEqual(ids, want)

    def test_AC_ANL_01e_unfinished_runs_count_but_give_no_lead_time(self):
        a = self.compute("2026-11-04", "2026-11-04")
        self.assertEqual(a["runs"]["total"], 1)
        self.assertEqual(a["runs"]["by_state"], {"EXECUTING": 1})
        for name in ("lead_time_seconds", "acceptance_rate"):
            self.assertIsNone(a[name]["value"])
        self.assertEqual(self.full()["lead_time_seconds"]["count"], 3)

    def test_AC_ANL_01l_analytics_never_write(self):
        before, cfg = self.sha(), (self.ws / "sentinel.config.yaml").read_bytes()
        self.full()
        self.cli("stats")
        self.cli("stats", "--format", "md")
        self.assertEqual(self.sha(), before)
        self.assertEqual((self.ws / "sentinel.config.yaml").read_bytes(), cfg)
        import analytics
        conn = analytics.open_readonly(self.dbp)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM tasks")
        finally:
            conn.close()

    def test_AC_ANL_01m_one_thousand_runs_within_two_seconds(self):
        c = sqlite3.connect(self.dbp)
        runs = [(f"p{i}", f"p{i}", "feature", "COMPLETED", "completed", "accepted", "2", f"2026-10-{i % 28 + 1:02d}T09:00:00.000000Z",
                 f"2026-10-{i % 28 + 1:02d}T11:00:00.000000Z") for i in range(1000)]
        c.executemany("INSERT INTO runs(id, slug, type, state, execution_status, acceptance_status, workflow_version, created_at, finished_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", runs)
        c.executemany("INSERT INTO tasks(id, run_id, role, provider, state, seconds, cost) VALUES (?,?,?,?,?,?,?)",
                      [(f"pt{i}", f"p{i % 1000}", "tdd_green", "codex", "COMPLETED", 10.0, 0.1) for i in range(20000)])
        c.executemany("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)",
                      [(f"p{i % 1000}", "task.progress", "engine", "{}", "2026-10-01T09:00:00.000000Z") for i in range(200000)])
        c.commit()
        c.close()
        t = time.time()
        a = self.compute()
        took = time.time() - t
        self.assertEqual(a["runs"]["total"], 1004)
        self.assertLess(took, 2.0, f"took {took:.2f}s")


class StatsCli(AN):
    def old_run(self, slug="old-fix"):
        d = self.ws / ".sentinel" / "runs" / slug
        d.mkdir(parents=True)
        (d / "state.json").write_text(json.dumps({
            "slug": slug, "tier": 2, "initial_tier": 1, "outcome": "passed", "started": "2026-11-02T08:00:00",
            "rounds": {"review": 2, "qa": 1}, "sessions": {"coder": "inline"}}))
        (d / "metrics.json").write_text(json.dumps({"stages": [{"stage": "coder", "tokens": 100, "seconds": 5}]}))

    def stats(self, *args):
        code, out, err = self.cli("stats", *args)
        return code, out, err

    def test_AC_ANL_01f_the_01_keys_are_unchanged(self):
        self.old_run()
        c, out, err = self.stats()
        self.assertEqual(c, 0, err)
        j = json.loads(out)
        self.assertEqual({k: j[k] for k in ("runs", "by_tier", "escalated_runs", "outcomes", "avg_rounds", "stage_isolation",
                                            "tokens_by_stage", "seconds_by_stage")},
                         {"runs": 1, "by_tier": {"2": 1}, "escalated_runs": 1, "outcomes": {"passed": 1},
                          "avg_rounds": {"review": 2, "qa": 1, "release_check": 0}, "stage_isolation": {"subagent": 0, "headless": 0, "inline": 1, "other": 0},
                          "tokens_by_stage": {"coder": 100}, "seconds_by_stage": {"coder": 5}})
        self.assertEqual(j["v2"]["runs"]["total"], 4)
        self.assertNotIn("old-fix", json.dumps(j["v2"]))

    def test_AC_ANL_01f_version_2_runs_do_not_break_the_01_part(self):
        self.old_run()
        v2 = self.ws / ".sentinel" / "runs" / "r-one"
        v2.mkdir(parents=True)
        (v2 / "state.json").write_text(json.dumps({"schema_version": 2, "slug": "r-one", "tier": None}))
        c, out, err = self.stats()
        self.assertEqual(c, 0, err)
        self.assertEqual(json.loads(out)["runs"], 1)

    def test_AC_ANL_01g_filters_and_markdown_output(self):
        c, out, err = self.stats("--from", "2026-11-01", "--to", "2026-11-02", "--format", "md")
        self.assertEqual(c, 0, err)
        self.assertIn("| Metric | Value |", out)
        self.assertIn("| runs.total | 2 |", out)
        j = json.loads(self.stats("--from", "2026-11-03")[1])
        self.assertEqual(j["v2"]["runs"]["total"], 2)
        self.assertEqual(j["v2"]["range"], {"from": "2026-11-03", "to": None})

    def test_AC_ANL_01g_null_values_read_not_reported_in_markdown(self):
        self.sql("UPDATE tasks SET cost = NULL")
        c, out, err = self.stats("--format", "md")
        self.assertEqual(c, 0, err)
        self.assertIn("| cost.total | not reported (not reported) |", out)

    def test_AC_ANL_01h_bad_arguments(self):
        rows = [(["--from", "2026-13-01"], "--from"), (["--from", "2026-11-05", "--to", "2026-11-01"], "--from"), (["--format", "xml"], "--format")]
        for args, name in rows:
            with self.subTest(args=args):
                c, out, err = self.stats(*args)
                self.assertEqual(c, 2, err)
                self.assertIn(name, err)

    def test_AC_ANL_01i_a_workspace_without_a_registry(self):
        self.dbp.unlink()
        for ext in ("-wal", "-shm"):
            Path(str(self.dbp) + ext).unlink(missing_ok=True)
        c, out, err = self.stats()
        self.assertEqual(c, 0, err)
        self.assertEqual(json.loads(out)["v2"], {"value": None, "reason": "no registry"})
        self.assertFalse(self.dbp.exists())

    def test_AC_ANL_01j_the_registry_cannot_be_read(self):
        for ext in ("-wal", "-shm"):
            Path(str(self.dbp) + ext).unlink(missing_ok=True)
        self.dbp.write_bytes(b"this is not a database" * 100)
        before = self.sha()
        c, out, err = self.stats()
        self.assertEqual(c, 1, out + err)
        self.assertTrue("E_INTEGRITY" in err or "E_MIGRATION" in err, err)
        self.assertIn(str(self.dbp), err)
        self.assertEqual(self.sha(), before)

    def test_AC_ANL_01k_stats_while_runs_write(self):
        stop = threading.Event()
        errors = []

        def writer():
            c = sqlite3.connect(self.dbp, timeout=30)
            n = 0
            try:
                while not stop.is_set():
                    for _ in range(20):
                        n += 1
                        c.execute("INSERT INTO tasks(id, run_id, role, provider, state, created_at) VALUES (?,?,?,?,?,?)",
                                  (f"w{n}", "r-one", "tdd_green", "codex", "QUEUED", "2026-11-01T09:00:00.000000Z"))
                        c.execute("INSERT INTO events(run_id, type, actor, payload, at) VALUES (?,?,?,?,?)",
                                  ("r-one", "task.progress", "engine", "{}", "2026-11-01T09:00:00.000000Z"))
                    c.commit()
                    time.sleep(0.1)
            except sqlite3.Error as e:
                errors.append(str(e))
            finally:
                c.close()
        th = threading.Thread(target=writer)
        th.start()
        try:
            for i in range(20):
                c, out, err = self.stats()
                self.assertEqual(c, 0, err)
                v2 = json.loads(out)["v2"]
                self.assertEqual(sum(r["count"] for r in v2["tasks"]["by_role"].values()),
                                 v2["cost"]["total"]["reported_tasks"] + v2["cost"]["total"]["unreported_tasks"])
        finally:
            stop.set()
            th.join()
        self.assertEqual(errors, [])


class Route(AN):
    def get(self, query):
        return self.http.get(f"/api/v1/reports/analytics?{query}")

    def test_AC_ANL_01n_the_analytics_route_returns_the_cli_answer(self):
        self.serve()
        r = self.get("project=digital-hr&from=2026-11-01&to=2026-11-30")
        self.assertEqual(r.status, 200, r.text)
        c, out, err = self.cli("stats", "--from", "2026-11-01", "--to", "2026-11-30")
        self.assertEqual(r.json, json.loads(out)["v2"])
        self.assertEqual(r.json["runs"]["total"], 4)

    def test_AC_ANL_01o_analytics_route_validation(self):
        self.serve()
        rows = [("project=nope", 404, "E_NOT_FOUND"), ("project=digital-hr&from=yesterday", 400, "E_VALIDATION"),
                ("project=digital-hr&from=2026-11-05&to=2026-11-01", 400, "E_VALIDATION"),
                ("project=digital-hr&sql=select", 400, "E_VALIDATION"), ("", 400, "E_VALIDATION")]
        for query, status, code in rows:
            with self.subTest(query=query):
                r = self.get(query)
                self.assertEqual((r.status, r.code), (status, code), r.text)

    def test_AC_ANL_01l_the_route_never_writes(self):
        self.serve()
        before = self.sha()
        self.assertEqual(self.get("project=digital-hr").status, 200)
        self.assertEqual(self.sha(), before)
        self.assertEqual(self.http.post("/api/v1/reports/analytics", {}).status, 405)


if __name__ == "__main__":
    unittest.main()
