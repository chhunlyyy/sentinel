"""AC-DSH-06i: the dashboard fixtures equal the answers of the real server.

The test starts the real Phase F + G server on a seeded workspace, records the JSON answer of every route the UI
uses into dashboard/fixtures/recorded/*.json and then runs dashboard/fixtures/check.ts (Node), which compares the keys
and value types of each recorded answer with the answer the fake API serves for the same route. Volatile values
(ids, hashes, times, paths) are not compared, only shapes. Skipped with a reason when Node is not installed.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from pd_helpers import PD
from pc_helpers import git
from sv_helpers import SV

DASH = Path(__file__).resolve().parents[1] / "dashboard"
OUT = DASH / "fixtures" / "recorded"
NODE = shutil.which("node")


class Recorder(SV, PD):
    def setUp(self):
        super().setUp()
        (self.ws / ".env").write_text("DB_PASSWORD=hunter2-secret\n")

    def tidy(self, text):
        text = text.replace(str(self.ws.resolve()), "/ws/digital-hr").replace(str(self.ws), "/ws/digital-hr")
        text = text.replace(str(self.home), "/home/dev")
        return re.sub(r"/tmp/[A-Za-z0-9_./-]+", "/tmp/x", text)

    def save(self, name, resp, status=200):
        self.assertEqual(resp.status, status, f"{name}: {resp.text[:300]}")
        OUT.mkdir(parents=True, exist_ok=True)
        data = json.loads(self.tidy(resp.text))
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        return data

    def test_AC_DSH_06i_fixtures_are_recorded_from_the_real_server(self):
        shutil.rmtree(OUT, ignore_errors=True)
        slug = self.boot_exec(repos=("backend", "frontend"))
        base_sha = git(self.ws / "backend", "rev-parse", "HEAD").strip()
        self.sql_run(f"UPDATE run_repos SET baseline_sha='{base_sha}' WHERE repo_id='backend'")
        self.sql_run(f"UPDATE run_repos SET baseline_sha='{git(self.ws / 'frontend', 'rev-parse', 'HEAD').strip()}' WHERE repo_id='frontend'")
        self.prepare(slug)
        run = self.run_row(slug)
        with self.eng.reg.transaction():
            cyc = self.cycles(slug)[0]
            self.eng.reg.insert_row("evidence", {"run_id": run["id"], "cycle_id": cyc["id"], "kind": "test", "exit_code": 1,
                                                 "passed": 0, "failed": 2, "classification": "valid_red",
                                                 "command": "faketest targeted", "started_at": "2026-11-14T09:00:00.000000Z",
                                                 "finished_at": "2026-11-14T09:00:05.000000Z"})
        (self.ws / "backend" / "src").mkdir(exist_ok=True)
        (self.ws / "backend" / "src" / "Leave.java").write_text("class Leave {}\n")
        task = self.eng.reg.rows("tasks", run_id=run["id"])[0]
        tdir = self.ws / ".sentinel" / "runs" / slug / "tasks" / task["id"]
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "output.log").write_text("starting\nrunning tests\n")
        # a run waiting for the specification decision, one for Gherkin, and a legacy run
        self.to_spec_review("spec-run", 3)
        self.to_gherkin_review("gherkin-run", 3)
        self.eng.reg.insert_run({"slug": "old-fix", "tier": 2, "state": "LEGACY", "workflow_version": "0.1",
                                 "execution_status": "completed", "acceptance_status": "accepted"})
        (self.ws / ".sentinel" / "runs" / slug / "report.json").write_text(json.dumps({"slug": slug, "result": "pending"}))
        self.eng.close()
        self.serve()
        h = self.http
        P = "/api/v1/projects/digital-hr"
        T = f"/api/v1/tasks/{slug}"
        self.save("session", h.get("/api/v1/session"))
        self.save("installation", h.get("/api/v1/installation"))
        self.save("runtime", h.get("/api/v1/runtime"))
        self.save("health", h.get("/api/v1/installation/health"))
        self.save("projects", h.get("/api/v1/projects"))
        self.save("runs", h.get(f"{P}/tasks"))
        self.save("run", h.get(f"{T}"))
        self.save("run_review", h.get("/api/v1/tasks/spec-run"))
        self.save("run_legacy", h.get("/api/v1/tasks/old-fix"))
        self.save("next", h.get(f"{T}/next"))
        self.save("specification", h.get("/api/v1/tasks/spec-run/specification"))
        self.save("specification_version", h.get("/api/v1/tasks/spec-run/specification/versions/1"))
        self.save("gherkin", h.get("/api/v1/tasks/gherkin-run/gherkin"))
        self.save("workflow", h.get(f"{T}/workflow"))
        self.save("tdd", h.get(f"{T}/tdd"))
        self.save("verification", h.get(f"{T}/verification"))
        self.save("trace", h.get(f"{T}/trace"))
        self.save("report", h.get(f"{T}/report"))
        self.save("approvals", h.get("/api/v1/approvals?state=IN_REVIEW"))
        self.save("audit", h.get(f"/api/v1/audit?project=digital-hr"))
        self.save("readiness", h.get(f"{P}/readiness"))
        self.save("repositories", h.get(f"{P}/repositories"))
        self.save("configuration", h.get(f"{P}/configuration"))
        history = self.save("config_history", h.get(f"{P}/configuration/history"))
        v = history["items"][0]["id"]
        self.save("config_diff", h.get(f"{P}/configuration/diff?a={v}&b=current"))
        changes = self.save("changes", h.get(f"{T}/changes"))
        self.assertTrue(any(r["files"] for r in changes["repos"]), changes)
        self.save("changes_diff", h.get(f"{T}/changes/diff?repo=backend&path=src/Leave.java&mode=inline"))
        task = self.save("workflow", h.get(f"{T}/workflow"))["nodes"][0]["id"]
        self.save("log", h.get(f"{T}/logs/{task}?offset=0"))
        info = self.eng_review_hash("spec-run")
        body = {"gate": "specification", "sha256": info, "confirmation": info[:8], "decision": "approve"}
        self.save("decision", h.post("/api/v1/tasks/spec-run/approvals", body))
        names = sorted(p.stem for p in OUT.glob("*.json"))
        self.assertGreaterEqual(len(names), 27, names)
        self.compare_with_fake()

    def eng_review_hash(self, slug):
        from engine import Engine
        eng = Engine(self.ws / ".sentinel", self.ws, self.config)
        try:
            return eng.pending_approval(slug, "spec")["sha256"]
        finally:
            eng.close()

    def sql_run(self, sql):
        import sqlite3
        c = sqlite3.connect(self.ws / ".sentinel" / "sentinel.db")
        try:
            c.execute(sql)
            c.commit()
        finally:
            c.close()

    def compare_with_fake(self):
        if not NODE:
            self.skipTest("node is not installed: the fixture shape check runs in the release job")
        r = subprocess.run([NODE, "fixtures/check.ts"], cwd=DASH, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-3000:])


if __name__ == "__main__":
    unittest.main()
