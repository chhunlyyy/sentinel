"""Phase F: human decisions through the dashboard channel (approvals_api.feature)."""
import json
import os
import sqlite3
import threading
import time
import unittest
from contextlib import contextmanager
from unittest import mock

from sv_helpers import SV, SLUG, Http, spec_text, fail_next_write
PROMPT = "first 8 characters"


class Approvals(SV):
    def setUp(self):
        super().setUp()
        (self.ws / ".env").write_text("DB_PASSWORD=hunter2-secret\n")
        self.h = self.spec_review(SLUG, 3)

    def approvals_url(self, slug=SLUG):
        return f"/api/v1/tasks/{slug}/approvals"

    def post(self, body, slug=SLUG, **kw):
        return self.http.post(self.approvals_url(slug), body, **kw)

    def spec_state(self, slug=SLUG):
        return [a["state"] for a in self.approvals("specification", slug)]

    def two_versions(self):
        """Specification version 1 (hash H1) decided as changes, then version 2 in review (hash H2)."""
        h1 = self.h
        self.approve("spec", decision="changes", comment="more")
        self.write_spec(spec_text(version=2, tier=3) + "\nrevised\n")
        self.submit("specifier")
        h2 = self.eng.pending_approval(SLUG, "spec")["sha256"]
        self.assertNotEqual(h1, h2)
        return h1, h2

    def refused_rows(self, reason):
        return [r for r in self.audit_rows() if r["action"] == "approve_refused" and r["reason"] == reason
                and r["channel"] == "dashboard"]

    # ---- approve, request changes, reject
    def test_AC_SEC_03f_a_human_approves_the_specification_in_the_dashboard(self):
        self.serve()
        r = self.post(self.body(self.h, comment="Looks right"))
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(r.json["state"], "SPECIFICATION_APPROVED")
        ap = self.approvals("specification")[-1]
        self.assertEqual((ap["state"], ap["version"], ap["sha256"], ap["decision"], ap["comment"]),
                         ("APPROVED", 1, self.h, "approve", "Looks right"))
        self.assertEqual((ap["approver"], ap["channel"]), ("dev", "dashboard"))
        self.assertTrue(ap["decided_at"])
        ev = self.events_rows(type="approval.decided")[-1]
        self.assertEqual((ev["actor"], ev["actor_name"], ev["channel"]), ("human", "dev", "dashboard"))
        self.assertEqual(json.loads(ev["payload"])["approver_name"], "Dev User")
        row = [a for a in self.audit_rows() if a["action"] == "approve"][-1]
        self.assertEqual((row["actor"], row["channel"], row["target"], row["after_sha"]),
                         ("dev", "dashboard", f"{SLUG}/specification", self.h))

    def test_AC_SEC_03g_requesting_changes_and_rejecting(self):
        for decision, comment, state in (("changes", "Add the carry-over rule", "PLANNED"), ("reject", "Not needed", "CANCELLED")):
            with self.subTest(decision=decision):
                slug = f"run-{decision}"
                self.to_spec_review(slug, 3)
                h = self.eng.pending_approval(slug, "spec")["sha256"]
                self.serve() if self.srv is None else None
                r = self.post(self.body(h, decision=decision, comment=comment), slug=slug)
                self.assertEqual(r.status, 200, r.text)
                self.assertEqual(self.state(slug), state)
                ap = self.approvals("specification", slug)[-1]
                self.assertEqual((ap["decision"], ap["channel"]), (decision, "dashboard"))

    def test_AC_SEC_03h_approving_the_gherkin_set(self):
        self.serve()
        self.assertEqual(self.post(self.body(self.h)).status, 200)
        self.write_features()
        self.submit("test_designer")
        g1 = self.eng.pending_approval(SLUG, "gherkin")["sha256"]
        r = self.post(self.body(g1, gate="gherkin"))
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(self.state(), "GHERKIN_APPROVED")
        self.assertEqual(self.approvals("gherkin")[-1]["channel"], "dashboard")

    def test_AC_API_03b_the_dashboard_and_the_terminal_store_the_same_decision(self):
        self.to_spec_review("copy-a", 3)
        self.to_spec_review("copy-b", 3)
        ha = self.eng.pending_approval("copy-a", "spec")["sha256"]
        hb = self.eng.pending_approval("copy-b", "spec")["sha256"]
        p = self.tty("approve", "copy-a", "spec", "-m", "ok")
        self.assertTrue(p.wait_for(PROMPT, 15), p.out)
        p.send(ha[:8] + "\n")
        code, out = p.finish(30)
        self.assertEqual(code, 0, out)
        self.serve()
        r = self.post(self.body(hb, comment="ok"), slug="copy-b")
        self.assertEqual(r.status, 200, r.text)

        def project(slug):
            ap = self.approvals("specification", slug)[-1]
            evs = [(e["type"], e["payload"].get("to"), e["payload"].get("decision"), e["payload"].get("transition"))
                   for e in self.eng.reg.list_events(self.run_row(slug)["id"])
                   if e["type"] in ("approval.decided", "run.state_changed") and e["payload"].get("to") in (None, "SPECIFICATION_APPROVED")]
            return (ap["state"], ap["decision"], ap["comment"], ap["approver"], self.state(slug), evs[-2:])
        self.assertEqual(project("copy-a"), project("copy-b"))
        self.assertEqual(self.approvals("specification", "copy-a")[-1]["channel"], "tty")

    # ---- hash and confirmation
    def test_AC_SEC_03i_a_hash_from_an_older_version_is_stale(self):
        h1, h2 = self.two_versions()
        self.serve()
        r = self.post(self.body(h1))
        self.assertEqual((r.status, r.code), (409, "E_APPROVAL_STALE"), r.text)
        self.assertEqual(r.json["error"]["details"]["current_sha256"], h2)
        self.assertEqual(self.spec_state()[-1], "IN_REVIEW")
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.assertEqual(len(self.refused_rows("E_APPROVAL_STALE")), 1)

    def test_AC_SEC_03j_the_spec_changes_while_the_reviewer_looks_at_it(self):
        self.write_spec(spec_text(tier=3) + "\nchanged\n")
        self.eng.load_run(SLUG)
        h3 = self.eng.pending_approval(SLUG, "spec")["sha256"]
        self.assertNotEqual(h3, self.h)
        self.serve()
        r = self.post(self.body(self.h))
        self.assertEqual((r.status, r.code), (409, "E_APPROVAL_STALE"))
        self.assertEqual(r.json["error"]["details"]["current_sha256"], h3)
        self.assertNotIn("APPROVED", self.spec_state())

    def test_AC_SEC_03k_bad_hash_or_confirmation(self):
        self.serve()
        h = self.h
        other = "ab" * 32
        rows = [(h[:8], h[:8]), (h[:-1] + ("0" if h[-1] != "0" else "1"), h[:8]), (other, other[:8]),
                (h, h[:7] + ("0" if h[7] != "0" else "1")), (h, h[:7]), (h, "")]
        for sha, conf in rows:
            with self.subTest(sha=sha[:10], conf=conf):
                r = self.post(self.body(sha, confirmation=conf))
                self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)
                self.assertEqual(self.spec_state()[-1], "IN_REVIEW")
        self.assertEqual(len(self.refused_rows("E_VALIDATION")), len(rows))

    def test_AC_SEC_03l_missing_fields(self):
        self.serve()
        for field in ("gate", "sha256", "confirmation", "decision"):
            with self.subTest(field=field):
                b = self.body(self.h)
                del b[field]
                r = self.post(b)
                self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))
                self.assertIn(field, r.text)
                self.assertEqual(self.spec_state()[-1], "IN_REVIEW")

    def test_AC_SEC_03m_requesting_changes_needs_a_comment(self):
        self.serve()
        for comment in (None, "absent", "", "   "):
            with self.subTest(comment=comment):
                b = self.body(self.h, decision="changes")
                if comment != "absent":
                    b["comment"] = comment
                r = self.post(b)
                self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)
                self.assertEqual(r.json["error"]["message"], "requesting changes needs a comment")

    def test_AC_SEC_03n_gate_decision_and_state_refusals_use_the_engine_codes(self):
        self.serve()
        r = self.post(self.body(self.h, gate="tests"))
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))
        r = self.post(self.body(self.h, decision="maybe"))
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"))
        # EXECUTING run
        self.to_gherkin_approved("exec-run", 3)
        self.eng.advance("exec-run")
        hs = self.approvals("specification", "exec-run")[-1]["sha256"]
        r = self.post(self.body(hs), slug="exec-run")
        self.assertEqual((r.status, r.code), (409, "E_TRANSITION"), r.text)
        # docs run, gherkin gate
        self.to_spec_approved("docs-run", 1, "docs")
        hd = self.approvals("specification", "docs-run")[-1]["sha256"]
        r = self.post(self.body(hd, gate="gherkin"), slug="docs-run")
        self.assertEqual((r.status, r.code), (422, "E_PRECONDITION"), r.text)
        # 0.1 run
        self.eng.reg.insert_run({"slug": "old-fix", "tier": 2, "state": "LEGACY", "workflow_version": "0.1",
                                 "execution_status": "running", "acceptance_status": "pending"})
        r = self.post(self.body(self.h), slug="old-fix")
        self.assertEqual((r.status, r.code), (409, "E_TRANSITION"), r.text)

    def test_AC_SEC_03o_an_approved_artifact_is_rehashed_before_the_decision_is_stored(self):
        self.write_spec(spec_text(tier=3) + "\nchanged on disk\n")
        self.serve()
        r = self.post(self.body(self.h))
        self.assertEqual((r.status, r.code), (409, "E_APPROVAL_STALE"), r.text)
        arts = self.artifacts("spec")
        self.assertEqual(len(arts), 2)
        self.assertEqual(r.json["error"]["details"]["current_sha256"], arts[-1]["sha256"])
        self.assertNotIn("APPROVED", self.spec_state())

    # ---- only a human with a session
    def test_AC_SEC_03p_calls_without_a_full_session_cannot_decide(self):
        self.serve()
        rows = [("no cookie", dict(cookie=False, csrf=self.http.csrf), 401),
                ("no csrf", dict(csrf=False), 403),
                ("bad origin", dict(origin="http://evil.example"), 403)]
        for name, kw, status in rows:
            with self.subTest(case=name):
                r = self.post(self.body(self.h), **kw)
                self.assertEqual(r.status, status)
        self.assertEqual(self.spec_state()[-1], "IN_REVIEW")
        self.assertEqual(self.events_rows(type="approval.decided"), [])

    def test_AC_SEC_04c_generated_agent_configs_forbid_reading_the_dashboard_token(self):
        cfg = {**self.config, "agents": {}, "runners": {"claude": {"command": "claude", "prompt_flag": "-p"}}}
        self.config = cfg
        self.write_config_file()
        code, out, err = self.cli("sync-adapters")
        self.assertEqual(code, 0, out + err)
        settings = json.loads((self.ws / ".claude" / "settings.json").read_text())
        deny = settings["permissions"]["deny"]
        self.assertTrue(any("server.json" in rule and rule.startswith("Read") for rule in deny), deny)
        agents = sorted((self.ws / ".claude" / "agents").glob("*.md"))
        self.assertTrue(agents)
        text = agents[0].read_text()
        self.assertIn("never read the dashboard token", text.lower())
        self.assertIn("local API", text)

    # ---- final acceptance (Phase E)
    def completed(self, slug="leave-form", acceptance="accepted", state="COMPLETED"):
        """A COMPLETED run with approved specification and Gherkin and a written report; returns the report sha256."""
        self.to_gherkin_approved(slug, 3)
        with self.eng.reg.transaction():
            self.eng.reg._c.execute("UPDATE runs SET state=?, execution_status='completed', acceptance_status=? WHERE slug=?",
                                    (state, acceptance, slug))
        return self.eng.write_report(slug)["sha256"] if state == "COMPLETED" else "0" * 64

    def accept_body(self, sha, decision="accept", comment=None, **over):
        body = {"sha256_of_report": sha, "confirmation": sha[:8], "decision": decision}
        if comment is not None:
            body["comment"] = comment
        body.update(over)
        return body

    def test_AC_VER_04k_a_human_confirms_acceptance_in_the_dashboard(self):
        sha = self.completed()
        self.serve()
        r = self.http.post("/api/v1/tasks/leave-form/acceptance", self.accept_body(sha, comment="Shipped"))
        self.assertEqual(r.status, 200, r.text)
        ap = [a for a in self.approvals("acceptance", "leave-form")][-1]
        self.assertEqual((ap["decision"], ap["sha256"], ap["approver"], ap["channel"]), ("accept", sha, "dev", "dashboard"))
        row = [a for a in self.audit_rows() if a["action"] == "acceptance"][-1]
        self.assertEqual(row["channel"], "dashboard")
        r = self.http.get("/api/v1/tasks/leave-form/report")
        self.assertEqual(r.status, 200, r.text)
        self.assertEqual(set(r.json), {"sha256", "report"})

    def test_AC_VER_04l_the_dashboard_cannot_accept_what_the_engine_rejects(self):
        rows = [("rejected by engine", dict(acceptance="rejected"), 409, "E_TRANSITION"), ("human rejected", None, 409, "E_TRANSITION"),
                ("human confirmed", None, 409, "E_TRANSITION"), ("reviewing", dict(state="REVIEWING"), 409, "E_TRANSITION")]
        for name, kw, status, code in rows:
            with self.subTest(case=name):
                slug = "leave-form-" + name.split()[-1]
                sha = self.completed(slug, **(kw or {}))
                if name == "human rejected":
                    self.eng.accept(slug, "reject", "human", sha256=sha, comment="no", approver="dev")
                if name == "human confirmed":
                    self.eng.accept(slug, "accept", "human", sha256=sha, approver="dev")
                before = self.run_row(slug)["acceptance_status"]
                self.serve() if not getattr(self, "srv", None) else None
                r = self.http.post(f"/api/v1/tasks/{slug}/acceptance", self.accept_body(sha))
                self.assertEqual((r.status, r.code), (status, code), r.text)
                self.assertEqual(self.run_row(slug)["acceptance_status"], before)

    def test_AC_VER_04m_rejecting_in_the_dashboard_needs_a_comment(self):
        sha = self.completed()
        self.serve()
        r = self.http.post("/api/v1/tasks/leave-form/acceptance", self.accept_body(sha, "reject"))
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)

    # ---- two humans, one decision
    def test_AC_SEC_03r_dashboard_and_terminal_approve_at_the_same_moment(self):
        self.serve()
        p = self.tty("approve", SLUG, "spec")
        self.assertTrue(p.wait_for(PROMPT, 15), p.out)
        barrier = threading.Barrier(2)
        out = {}

        def api():
            barrier.wait()
            out["api"] = self.post(self.body(self.h))
        t = threading.Thread(target=api)
        t.start()
        barrier.wait()
        p.send(self.h[:8] + "\n")
        t.join(30)
        code, text = p.finish(30)
        api_ok = out["api"].status == 200
        tty_ok = code == 0
        self.assertEqual(api_ok + tty_ok, 1, (out["api"].text, code, text))
        if not api_ok:
            self.assertEqual((out["api"].status, out["api"].code), (409, "E_TRANSITION"))
        else:
            self.assertEqual(code, 5, text)
            self.assertIn("E_TRANSITION", text)
        self.assertEqual(len(self.events_rows(type="approval.decided")), 1)
        self.assertEqual([a["state"] for a in self.approvals("specification")], ["APPROVED"])
        self.assertEqual(self.approvals("specification")[0]["channel"], "dashboard" if api_ok else "tty")
        actions = [r["action"] for r in self.audit_rows()]
        self.assertEqual((actions.count("approve"), actions.count("approve_refused")), (1, 1))

    def test_AC_SEC_03s_the_same_dashboard_decision_sent_twice(self):
        self.serve()
        clients = [self.client(), self.client()]
        out = []
        barrier = threading.Barrier(2)

        def go(c):
            barrier.wait()
            out.append(c.post(self.approvals_url(), self.body(self.h)))
        ts = [threading.Thread(target=go, args=(c,)) for c in clients]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual(sorted(r.status for r in out), [200, 409], [r.text for r in out])
        self.assertEqual([r.code for r in out if r.status == 409], ["E_TRANSITION"])
        self.assertEqual(len(self.events_rows(type="approval.decided")), 1)

    def test_AC_SEC_03t_a_request_changes_and_an_approve_race(self):
        self.serve()
        p = self.tty("approve", SLUG, "spec")
        self.assertTrue(p.wait_for(PROMPT, 15), p.out)
        barrier = threading.Barrier(2)
        out = {}

        def api():
            barrier.wait()
            out["api"] = self.post(self.body(self.h, decision="changes", comment="more"))
        t = threading.Thread(target=api)
        t.start()
        barrier.wait()
        p.send(self.h[:8] + "\n")
        t.join(30)
        code, text = p.finish(30)
        self.assertEqual((out["api"].status == 200) + (code == 0), 1, (out["api"].text, code, text))
        decided = self.approvals("specification")[0]
        if out["api"].status == 200:
            self.assertEqual((decided["decision"], self.state()), ("changes", "PLANNED"))
            self.assertIn("E_TRANSITION", text)
        else:
            self.assertEqual((decided["decision"], self.state()), ("approve", "SPECIFICATION_APPROVED"))
            self.assertEqual(out["api"].code, "E_TRANSITION")

    # ---- failed write
    def test_AC_SEC_03u_the_registry_write_fails_during_a_dashboard_approval(self):
        self.serve()
        with fail_next_write():
            r = self.post(self.body(self.h))
            self.assertEqual((r.status, r.code), (500, "E_INTERNAL"), r.text)
            self.assertNotIn("Traceback", r.text)
        self.assertEqual(self.spec_state()[-1], "IN_REVIEW")
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.assertEqual(self.events_rows(type="approval.decided"), [])
        self.assertEqual(self.post(self.body(self.h)).status, 200)


if __name__ == "__main__":
    unittest.main()
