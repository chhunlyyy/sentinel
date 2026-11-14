"""Phase B part 2 (PB-02): approvals, hashing, invalidation. Engine level."""
import os
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

import artifacts as A  # noqa: E402
from engine import Engine  # noqa: E402
from errors import SentinelError  # noqa: E402
from pb_helpers import CONFIG, GOOD, PB, SLUG, spec_text  # noqa: E402
from test_artifacts import LITE, feat, make_spec  # noqa: E402


class Submit(PB):
    def test_AC_SPA_01a_valid_spec_opens_review(self):
        self.to_spec_review(tier=3)
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        sha = A.spec_hash(self.sdir() / "spec.md")
        art = self.artifacts("spec")
        self.assertEqual([(a["version"], a["sha256"]) for a in art], [(1, sha)])
        self.assertTrue((self.ws / ".sentinel/runs" / SLUG / "artifacts/spec-v1.md").is_file())
        ap = self.approvals("specification")
        self.assertEqual([(a["state"], a["version"], a["sha256"], a["artifact_id"]) for a in ap],
                         [("IN_REVIEW", 1, sha, art[0]["id"])])
        self.assertEqual(len(self.events("artifact.version_created")), 1)
        self.assertEqual(len(self.events("approval.requested")), 1)
        self.assertEqual(self.rules(), ["R4"])

    def test_AC_SPA_01b_spec_in_wrong_place_not_found(self):
        self.mk()
        p = self.ws / ".sentinel/runs" / SLUG / "spec.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(spec_text())
        res = self.eng.task_completed(SLUG, "specifier")
        self.assertFalse(res["accepted"])
        self.assertIn(f"specs/{SLUG}/spec.md not found", res["errors"])
        self.assertEqual(self.state(), "PLANNED")

    def test_docs_run_needs_docs_sections_only(self):
        self.to_spec_review(typ="docs")
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")

    def test_AC_SPA_03a_linked_ids_stored_as_trace_links(self):
        self.to_spec_review()
        rows = self.eng.reg.rows("trace_links", run_id=self.run_row()["id"])
        self.assertEqual(sorted((r["from_id"], r["to_id"]) for r in rows), [("REQ-1", "AC-1"), ("REQ-2", "AC-2")])

    def test_AC_SPA_03d_errors_go_into_next_brief(self):
        self.mk()
        self.write_spec(make_spec([s for s in LITE if s != "Edge cases"], tier=1))
        res = self.eng.task_completed(SLUG, "specifier")
        self.assertFalse(res["accepted"])
        self.assertEqual(self.state(), "PLANNED")
        self.assertEqual(self.approvals(), [])
        self.assertEqual(self.artifacts("spec"), [])
        self.assertIn("missing section: Edge cases", self.eng.brief_feedback(SLUG, "specifier"))

    def test_AC_SPA_03e_retry_cap_goes_to_needs_human(self):
        self.mk()
        self.write_spec("")
        for _ in range(2):
            self.eng.task_completed(SLUG, "specifier")
            self.assertEqual(self.state(), "PLANNED")
        res = self.eng.task_completed(SLUG, "specifier")
        self.assertFalse(res["accepted"])
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        ev = self.events("run.state_changed")[-1]["payload"]
        self.assertEqual((ev["transition"], ev["reason"]), ("R19", "specification invalid after 2 retries"))

    def test_retry_cap_is_configurable(self):
        self.eng.config = {**CONFIG, "limits": {"specifier_retries": 0}}
        self.mk()
        self.write_spec("")
        self.eng.task_completed(SLUG, "specifier")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertEqual(self.events("run.state_changed")[-1]["payload"]["reason"],
                         "specification invalid after 0 retries")

    def test_valid_submission_resets_the_failure_counter(self):
        self.mk()
        self.write_spec("")
        self.eng.task_completed(SLUG, "specifier")
        self.write_spec()
        self.assertTrue(self.eng.task_completed(SLUG, "specifier")["accepted"])
        self.assertEqual(self.eng.brief_feedback(SLUG, "specifier"), [])

    def test_specifier_needs_planned_state(self):
        self.mk(state="TRIAGED")
        self.write_spec()
        with self.assertRaises(SentinelError) as c:
            self.eng.task_completed(SLUG, "specifier")
        self.assertEqual(c.exception.code, "E_TRANSITION")

    def test_AC_GHA_01a_valid_gherkin_opens_review(self):
        self.to_gherkin_review()
        self.assertEqual(self.state(), "GHERKIN_REVIEW")
        h, paths = A.gherkin_set_hash(self.sdir() / "features")
        art = self.artifacts("gherkin")
        self.assertEqual([(a["version"], a["sha256"]) for a in art], [(1, h)])
        self.assertTrue((self.ws / ".sentinel/runs" / SLUG / "artifacts/gherkin-v1/features/balance.feature").is_file())
        self.assertEqual([(a["state"], a["sha256"]) for a in self.approvals("gherkin")], [("IN_REVIEW", h)])
        links = self.eng.reg.rows("trace_links", run_id=self.run_row()["id"], to_kind="scenario")
        self.assertEqual(sorted(r["from_id"] for r in links), ["AC-1", "AC-2"])
        self.assertTrue((self.ws / ".sentinel/runs" / SLUG / "artifacts/coverage-v1.json").is_file())
        self.assertEqual(self.rules()[-1], "R8")

    def test_AC_GHA_01b_gherkin_before_spec_approval_refused(self):
        self.to_spec_review()
        self.write_features()
        with self.assertRaises(SentinelError) as c:
            self.eng.task_completed(SLUG, "test_designer")
        self.assertEqual(c.exception.code, "E_TRANSITION")
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.assertEqual(self.artifacts("gherkin"), [])

    def test_AC_GHA_03e_gherkin_errors_into_brief_and_cap(self):
        self.to_spec_approved()
        self.write_features({"balance.feature": GOOD["balance.feature"]})
        res = self.eng.task_completed(SLUG, "test_designer")
        self.assertFalse(res["accepted"])
        self.assertEqual(self.state(), "SPECIFICATION_APPROVED")
        self.assertEqual(self.approvals("gherkin"), [])
        self.assertEqual(self.artifacts("gherkin"), [])
        self.assertIn("AC-2 has no scenario", self.eng.brief_feedback(SLUG, "test_designer"))
        self.eng.task_completed(SLUG, "test_designer")
        self.eng.task_completed(SLUG, "test_designer")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertEqual(self.events("run.state_changed")[-1]["payload"]["reason"],
                         "Gherkin invalid after 2 retries")

    def test_AC_GHA_07a_docs_run_skips_gherkin(self):
        self.to_spec_approved(typ="docs")
        self.assertEqual(self.state(), "SPECIFICATION_APPROVED")
        self.eng.advance(SLUG)
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(self.rules()[-1], "R12d")
        self.assertEqual(self.approvals("gherkin"), [])

    def test_AC_GHA_07b_gherkin_approval_on_docs_run_refused(self):
        self.to_spec_approved(typ="docs")
        with self.assertRaises(SentinelError) as c:
            self.eng.decide(SLUG, "gherkin", "approve", "human", prefix="00000000")
        self.assertEqual(c.exception.code, "E_PRECONDITION")
        self.assertIn("docs-only", c.exception.message)


class Decide(PB):
    def test_AC_SPA_06a_human_approves_spec(self):
        self.to_spec_review(tier=3)
        sha = self.artifacts("spec")[0]["sha256"]
        self.eng.decide(SLUG, "spec", "approve", "human", prefix=sha[:8].upper(), comment="Looks right",
                        approver="dev", approver_name="Dev User")
        self.assertEqual(self.state(), "SPECIFICATION_APPROVED")
        ap = self.approvals("specification")[0]
        self.assertEqual((ap["state"], ap["version"], ap["sha256"], ap["decision"], ap["comment"],
                          ap["approver"], ap["channel"]),
                         ("APPROVED", 1, sha, "approve", "Looks right", "dev", "tty"))
        self.assertTrue(ap["decided_at"])
        dec = self.events("approval.decided")
        self.assertEqual(len(dec), 1)
        self.assertEqual(dec[0]["payload"], {"gate": "specification", "version": 1, "sha256": sha,
                                             "decision": "approve", "comment": "Looks right",
                                             "approver_name": "Dev User"})
        self.assertEqual(self.rules()[-1], "R5")
        rows = self.audit("approve")
        self.assertEqual([(r["actor"], r["channel"], r["target"], r["after_sha"]) for r in rows],
                         [("dev", "tty", f"{SLUG}/specification", sha)])

    def test_AC_GHA_05b_human_approves_gherkin(self):
        self.to_gherkin_approved()
        self.assertEqual(self.state(), "GHERKIN_APPROVED")
        self.assertEqual(self.approvals("gherkin")[0]["state"], "APPROVED")
        self.assertEqual(self.rules()[-1], "R9")

    def test_AC_SPA_06b_prefix_trimmed_and_case_insensitive(self):
        for typed in ("{p}", "{P}", "  {p} "):
            with self.subTest(typed=typed):
                slug = f"lb-{abs(hash(typed)) % 1000}"
                self.to_spec_review(slug)
                p = self.hash_prefix("spec", slug)
                self.eng.decide(slug, "spec", "approve", "human", prefix=typed.format(p=p, P=p.upper()))
                self.assertEqual(self.state(slug), "SPECIFICATION_APPROVED")

    def test_AC_SEC_03c_wrong_prefix_refused(self):
        self.to_spec_review()
        p = self.hash_prefix("spec")
        bad = ["00000000", p[:7], p[:7] + ("0" if p[7] != "0" else "1"), p + "ab", "", p + self.artifacts()[0]["sha256"][8:]]
        for typed in bad:
            with self.subTest(typed=typed):
                with self.assertRaises(SentinelError) as c:
                    self.eng.decide(SLUG, "spec", "approve", "human", prefix=typed)
                self.assertEqual(c.exception.code, "E_VALIDATION")
                self.assertEqual(self.approvals("specification")[0]["state"], "IN_REVIEW")
                self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.assertEqual(len(self.audit("approve_refused")), len(bad))
        self.assertEqual(self.audit("approve_refused")[0]["target"], f"{SLUG}/specification")

    def test_AC_SPA_07a_spec_approval_alone_never_executes(self):
        for tier in (1, 2, 3, 4):
            with self.subTest(tier=tier):
                slug = f"lb-{tier}"
                self.to_spec_approved(slug, tier)
                for who in ("engine",):
                    with self.assertRaises(SentinelError) as c:
                        self.eng.request_state(slug, "EXECUTING", who)
                    self.assertEqual(c.exception.code, "E_TRANSITION")
                self.assertEqual(self.state(slug), "SPECIFICATION_APPROVED")

    def test_AC_SPA_07b_empty_human_required_keeps_gates(self):
        self.eng.config = {**CONFIG, "policies": {"human_required": []}}
        self.to_spec_review()
        self.eng.advance(SLUG)
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.approve("spec")
        self.eng.advance(SLUG)
        self.assertEqual(self.state(), "SPECIFICATION_APPROVED")

    def test_AC_SPA_05a_request_changes_returns_to_specifier(self):
        self.to_spec_review()
        self.approve("spec", decision="changes", comment="Add the half-day case")
        self.assertEqual(self.state(), "PLANNED")
        ap = self.approvals("specification")[0]
        self.assertEqual((ap["state"], ap["comment"]), ("CHANGES_REQUESTED", "Add the half-day case"))
        self.assertIn("Add the half-day case", "\n".join(self.eng.brief_feedback(SLUG, "specifier")))
        self.assertEqual(self.rules()[-1], "R6")

    def test_AC_SPA_05b_request_changes_needs_comment(self):
        self.to_spec_review()
        for c in (None, "", "  "):
            with self.subTest(comment=c):
                with self.assertRaises(SentinelError) as cm:
                    self.approve("spec", decision="changes", comment=c)
                self.assertEqual(cm.exception.code, "E_VALIDATION")
                self.assertEqual(self.state(), "SPECIFICATION_REVIEW")

    def test_AC_SPA_05c_revised_spec_reviewed_again(self):
        self.to_spec_review()
        self.approve("spec", decision="changes", comment="more")
        self.write_spec(spec_text(version=2) + "\n<!-- v2 -->\n")
        self.assertTrue(self.eng.task_completed(SLUG, "specifier")["accepted"])
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        ap = self.approvals("specification")
        self.assertEqual([(a["version"], a["state"]) for a in ap], [(1, "CHANGES_REQUESTED"), (2, "IN_REVIEW")])
        info = self.eng.review(SLUG, "spec")
        self.assertIn("-", info["diff"])
        self.assertIn("v2", info["diff"])
        self.assertEqual(self.eng.brief_feedback(SLUG, "specifier"), [])

    def test_AC_SPA_05d_reject_cancels_run(self):
        for gate, builder, rule, name in (("spec", self.to_spec_review, "R7", "specification"),
                                          ("gherkin", self.to_gherkin_review, "R11", "gherkin")):
            with self.subTest(gate=gate):
                slug = f"lb-{gate}"
                builder(slug)
                self.approve(gate, slug, decision="reject", comment="Out of scope")
                row = self.run_row(slug)
                self.assertEqual((row["state"], row["execution_status"], row["acceptance_status"]),
                                 ("CANCELLED", "cancelled", "rejected"))
                self.assertEqual(self.approvals(name, slug)[0]["state"], "REJECTED")
                self.assertIn(slug, self.released)
                self.assertEqual(self.rules(slug)[-1], rule)

    def test_AC_GHA_05c_gherkin_changes_return_to_test_designer(self):
        self.to_gherkin_review()
        self.approve("gherkin", decision="changes", comment="Add a negative balance case")
        self.assertEqual(self.state(), "SPECIFICATION_APPROVED")
        self.assertEqual(self.approvals("gherkin")[0]["state"], "CHANGES_REQUESTED")
        self.assertEqual(self.approvals("specification")[0]["state"], "APPROVED")
        self.assertIn("Add a negative balance case", "\n".join(self.eng.brief_feedback(SLUG, "test_designer")))
        self.assertEqual(self.rules()[-1], "R10")

    def test_AC_VIS_01a_non_human_actor_refused(self):
        for builder, gate, actor in ((self.to_spec_review, "spec", "orchestrator"),
                                     (lambda s: self.to_spec_review(s), "spec", "engine"),
                                     (self.to_gherkin_review, "gherkin", "orchestrator")):
            with self.subTest(gate=gate, actor=actor):
                slug = f"lb-{gate}-{actor}"
                builder(slug)
                state = self.state(slug)
                full = self.eng.pending_approval(slug, gate)["sha256"]
                with self.assertRaises(SentinelError) as c:
                    self.eng.decide(slug, gate, "approve", actor, sha256=full)
                self.assertEqual(c.exception.code, "E_ACTOR")
                self.assertEqual(self.state(slug), state)

    def test_AC_SPA_06c_wrong_state_refused(self):
        self.to_spec_review()
        for state, gate in (("PLANNED", "spec"), ("SPECIFICATION_REVIEW", "gherkin"),
                            ("GHERKIN_APPROVED", "spec"), ("EXECUTING", "gherkin")):
            with self.subTest(state=state, gate=gate):
                self.eng.reg.update_run(SLUG, state=state)
                with self.assertRaises(SentinelError) as c:
                    self.eng.decide(SLUG, gate, "approve", "human", prefix="00000000")
                self.assertEqual(c.exception.code, "E_TRANSITION")
                self.assertEqual(self.state(), state)

    def test_AC_SPA_06d_second_approval_refused(self):
        self.to_spec_review()
        p = self.hash_prefix("spec")
        self.approve("spec")
        with self.assertRaises(SentinelError) as c:
            self.eng.decide(SLUG, "spec", "approve", "human", prefix=p)
        self.assertEqual(c.exception.code, "E_TRANSITION")
        self.assertEqual(len(self.events("approval.decided")), 1)

    def test_AC_SPA_06e_legacy_run_has_no_gates(self):
        self.eng.reg.insert_run({"slug": "old-run", "tier": 2, "state": "LEGACY", "workflow_version": "0.1",
                                 "execution_status": "running", "acceptance_status": "pending"})
        with self.assertRaises(SentinelError) as c:
            self.eng.decide("old-run", "spec", "approve", "human", prefix="00000000")
        self.assertEqual(c.exception.code, "E_TRANSITION")

    def test_AC_SPA_06h_failed_event_write_leaves_approval_undecided(self):
        self.to_spec_review()
        orig = self.eng.reg.add_event

        def boom(run_id, type, *a, **k):
            if type == "approval.decided":
                raise RuntimeError("event store down")
            return orig(run_id, type, *a, **k)
        self.eng.reg.add_event = boom
        with self.assertRaises(RuntimeError):
            self.approve("spec")
        self.eng.reg.add_event = orig
        self.assertEqual(self.approvals("specification")[0]["state"], "IN_REVIEW")
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.assertEqual(self.audit("approve"), [])

    def test_AC_SPA_06f_two_approvals_at_once_exactly_one_wins(self):
        self.to_spec_review()
        prefix = self.hash_prefix("spec")
        barrier = threading.Barrier(2)
        out = []

        def worker():
            e = Engine(self.ws / ".sentinel", self.ws, CONFIG, release_lock=lambda s: None)
            try:
                barrier.wait()
                e.decide(SLUG, "spec", "approve", "human", prefix=prefix, approver="dev")
                out.append("ok")
            except SentinelError as err:
                out.append(err.code)
            finally:
                e.close()
        ts = [threading.Thread(target=worker) for _ in range(2)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(out), ["E_TRANSITION", "ok"])
        self.assertEqual(len(self.events("approval.decided")), 1)
        self.assertEqual(len(self.audit("approve")), 1)

    def test_AC_SPA_06g_approve_and_request_changes_race(self):
        self.to_spec_review()
        prefix = self.hash_prefix("spec")
        barrier = threading.Barrier(2)
        out = []

        def worker(decision):
            e = Engine(self.ws / ".sentinel", self.ws, CONFIG, release_lock=lambda s: None)
            try:
                barrier.wait()
                e.decide(SLUG, "spec", decision, "human", prefix=prefix, comment="c", approver="dev")
                out.append(decision)
            except SentinelError as err:
                out.append(err.code)
            finally:
                e.close()
        ts = [threading.Thread(target=worker, args=(d,)) for d in ("approve", "changes")]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(self.events("approval.decided")), 1)
        winner = [o for o in out if o != "E_TRANSITION"]
        self.assertEqual(len(winner), 1)
        self.assertEqual(self.state(), {"approve": "SPECIFICATION_APPROVED", "changes": "PLANNED"}[winner[0]])


class Stale(PB):
    def test_AC_SPA_08a_spec_edited_after_review_is_stale(self):
        self.to_spec_review()
        old = self.hash_prefix("spec")
        p = self.sdir() / "spec.md"
        p.write_text(p.read_text() + "\nmore\n")
        with self.assertRaises(SentinelError) as c:
            self.eng.decide(SLUG, "spec", "approve", "human", prefix=old)
        self.assertEqual(c.exception.code, "E_APPROVAL_STALE")
        new = A.spec_hash(p)
        self.assertEqual(c.exception.details["current_sha256"], new)
        ap = self.approvals("specification")
        self.assertEqual([(a["version"], a["state"]) for a in ap], [(1, "INVALIDATED"), (2, "IN_REVIEW")])
        self.assertEqual(ap[1]["sha256"], new)
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.assertEqual(len(self.audit("approve_refused")), 1)

    def test_AC_GHA_05g_gherkin_edited_after_review_is_stale(self):
        self.to_gherkin_review()
        old = self.hash_prefix("gherkin")
        p = self.sdir() / "features/balance.feature"
        p.write_text(p.read_text() + "\n  @AC-1 @unit @P1\n  Scenario: more\n    Given x\n    When y\n    Then z\n")
        with self.assertRaises(SentinelError) as c:
            self.eng.decide(SLUG, "gherkin", "approve", "human", prefix=old)
        self.assertEqual(c.exception.code, "E_APPROVAL_STALE")
        self.assertEqual([(a["version"], a["state"]) for a in self.approvals("gherkin")],
                         [(1, "INVALIDATED"), (2, "IN_REVIEW")])
        self.assertEqual(self.state(), "GHERKIN_REVIEW")

    def test_AC_GHA_05h_full_hash_of_older_version_is_stale(self):
        self.to_gherkin_review()
        v1 = self.artifacts("gherkin")[0]["sha256"]
        p = self.sdir() / "features/balance.feature"
        p.write_text(p.read_text() + "\n")
        self.eng.load_run(SLUG)
        with self.assertRaises(SentinelError) as c:
            self.eng.decide(SLUG, "gherkin", "approve", "human", sha256=v1)
        self.assertEqual(c.exception.code, "E_APPROVAL_STALE")
        self.assertEqual(self.state(), "GHERKIN_REVIEW")

    def test_full_hash_of_current_version_is_accepted(self):
        self.to_spec_review()
        self.eng.decide(SLUG, "spec", "approve", "human", sha256=self.eng.pending_approval(SLUG, "spec")["sha256"])
        self.assertEqual(self.state(), "SPECIFICATION_APPROVED")

    def test_AC_SPA_08b_edit_between_prompt_and_typing(self):
        self.to_spec_review()
        shown = self.eng.pending_approval(SLUG, "spec")["sha256"]
        p = self.sdir() / "spec.md"
        p.write_text(p.read_text() + "x")
        with self.assertRaises(SentinelError) as c:
            self.eng.decide(SLUG, "spec", "approve", "human", prefix=shown[:8])
        self.assertEqual(c.exception.code, "E_APPROVAL_STALE")
        self.assertFalse([a for a in self.approvals() if a["state"] == "APPROVED"])


class Invalidation(PB):
    def test_AC_SPA_08c_spec_edit_triggers_R17(self):
        reason = "upstream specification approval invalidated"
        cases = [("SPECIFICATION_APPROVED", None), ("GHERKIN_REVIEW", reason), ("GHERKIN_APPROVED", reason),
                 ("EXECUTING", reason), ("VERIFYING", reason), ("REVIEWING", reason), ("NEEDS_HUMAN", reason)]
        for i, (state, gh_after) in enumerate(cases):
            with self.subTest(state=state):
                slug = f"lb-{i}"
                if state == "SPECIFICATION_APPROVED":
                    self.to_spec_approved(slug)
                elif state == "GHERKIN_REVIEW":
                    self.to_gherkin_review(slug)
                else:
                    self.to_gherkin_approved(slug)
                    self.eng.reg.update_run(slug, state=state, previous_state="EXECUTING" if state == "NEEDS_HUMAN" else None)
                p = self.sdir(slug) / "spec.md"
                p.write_text(p.read_text() + "\nedit\n")
                self.eng.load_run(slug)
                self.assertEqual(self.state(slug), "SPECIFICATION_REVIEW")
                self.assertEqual(self.rules(slug)[-1], "R17")
                sp = self.approvals("specification", slug)
                self.assertEqual([(a["version"], a["state"]) for a in sp],
                                 [(1, "INVALIDATED"), (2, "IN_REVIEW")])
                self.assertEqual(sp[0]["invalidated_reason"], "spec hash changed")
                gh = self.approvals("gherkin", slug)
                if gh_after is None:
                    self.assertEqual(gh, [])
                else:
                    self.assertEqual((gh[0]["state"], gh[0]["invalidated_reason"]), ("INVALIDATED", gh_after))
                inv = self.events("approval.invalidated", slug)
                self.assertEqual(len(inv), 1 if gh_after is None else 2)
                self.assertEqual(self.events("artifact.version_created", slug)[-1]["payload"]["kind"], "spec")

    def test_AC_SPA_08d_both_gates_again_after_spec_change(self):
        self.to_gherkin_approved()
        p = self.sdir() / "spec.md"
        p.write_text(p.read_text() + "\nedit\n")
        self.eng.load_run(SLUG)
        self.approve("spec")
        self.assertEqual(self.state(), "SPECIFICATION_APPROVED")
        self.assertEqual(self.approvals("gherkin")[0]["state"], "INVALIDATED")
        with self.assertRaises(SentinelError) as c:
            self.eng.request_state(SLUG, "EXECUTING", "engine")
        self.assertEqual(c.exception.code, "E_TRANSITION")
        self.assertTrue(self.eng.task_completed(SLUG, "test_designer")["accepted"])
        self.assertEqual([(a["version"], a["state"]) for a in self.approvals("gherkin")],
                         [(1, "INVALIDATED"), (2, "IN_REVIEW")])

    def test_AC_SPA_08e_only_a_byte_change_invalidates(self):
        def mtime(p):
            os.utime(p, (time.time() + 100, time.time() + 100))

        def rewrite(p):
            p.write_bytes(p.read_bytes())

        def trailing(p):
            p.write_bytes(p.read_bytes() + b" ")

        def crlf(p):
            p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        for i, (name, fn, state) in enumerate((("mtime", mtime, "GHERKIN_APPROVED"), ("rewrite", rewrite, "GHERKIN_APPROVED"),
                                              ("space", trailing, "SPECIFICATION_REVIEW"), ("crlf", crlf, "SPECIFICATION_REVIEW"))):
            with self.subTest(change=name):
                slug = f"lb-{i}"
                self.to_gherkin_approved(slug)
                fn(self.sdir(slug) / "spec.md")
                self.eng.load_run(slug)
                self.assertEqual(self.state(slug), state)

    def test_AC_SPA_08f_deleted_spec_invalidates_and_blocks(self):
        self.to_gherkin_approved()
        (self.sdir() / "spec.md").unlink()
        self.eng.load_run(SLUG)
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.assertTrue(all(a["state"] == "INVALIDATED" for a in self.approvals()))
        info = self.eng.review(SLUG, "spec")
        self.assertIn(f"specs/{SLUG}/spec.md not found", info["errors"])
        with self.assertRaises(SentinelError) as c:
            self.eng.pending_approval(SLUG, "spec")
        self.assertEqual(c.exception.code, "E_VALIDATION")
        # restoring the file opens a fresh review
        self.write_spec(spec_text(version=3))
        self.eng.load_run(SLUG)
        self.assertEqual(self.approvals("specification")[-1]["state"], "IN_REVIEW")

    def test_AC_SPA_08g_invalid_changed_spec_cannot_be_approved(self):
        self.to_gherkin_approved()
        p = self.sdir() / "spec.md"
        p.write_text(p.read_text().replace("## Acceptance criteria", "## Something else"))
        self.eng.load_run(SLUG)
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        with self.assertRaises(SentinelError) as c:
            self.approve("spec")
        self.assertEqual(c.exception.code, "E_VALIDATION")
        self.assertIn("missing section: Acceptance criteria", c.exception.details["errors"])

    def test_AC_GHA_05i_gherkin_edit_triggers_R18(self):
        def add(p):
            p.write_text(p.read_text() + "\n  @AC-1 @unit @P1\n  Scenario: more\n    Given x\n    When y\n    Then z\n")

        def reword(p):
            p.write_text(p.read_text().replace("Then z", "Then zz"))

        def delete(p):
            p.unlink()

        def rename(p):
            p.rename(p.parent / "leave.feature")
        for i, (state, target, fn) in enumerate((("GHERKIN_APPROVED", "balance.feature", add),
                                                 ("EXECUTING", "balance.feature", reword),
                                                 ("VERIFYING", "request_form.feature", delete),
                                                 ("REVIEWING", "balance.feature", rename))):
            with self.subTest(state=state):
                slug = f"lb-{i}"
                self.to_gherkin_approved(slug)
                self.eng.reg.update_run(slug, state=state)
                fn(self.sdir(slug) / "features" / target)
                self.eng.load_run(slug)
                self.assertEqual(self.state(slug), "GHERKIN_REVIEW")
                self.assertEqual(self.rules(slug)[-1], "R18")
                gh = self.approvals("gherkin", slug)
                self.assertEqual([(a["version"], a["state"]) for a in gh], [(1, "INVALIDATED"), (2, "IN_REVIEW")])
                self.assertEqual(gh[0]["invalidated_reason"], "Gherkin hash changed")
                self.assertEqual(self.approvals("specification", slug)[0]["state"], "APPROVED")

    def test_AC_GHA_05j_non_feature_file_changes_nothing(self):
        self.to_gherkin_approved()
        self.eng.reg.update_run(SLUG, state="EXECUTING")
        (self.sdir() / "features/notes.md").write_text("hello")
        self.eng.load_run(SLUG)
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(self.events("approval.invalidated"), [])


class ReviewFindings(PB):
    """Regression tests for the Opus review findings (detection, resume, feedback)."""

    def tamper_and_edit(self):
        stored = self.ws / ".sentinel/runs" / SLUG / "artifacts/spec-v1.md"
        stored.write_text(stored.read_text() + "x")
        f = self.sdir() / "features/balance.feature"
        f.write_text(f.read_text() + "\n")

    def test_integrity_failure_in_detection_parks_run_and_audits(self):
        self.to_gherkin_approved()
        self.tamper_and_edit()
        run = self.eng.load_run(SLUG)
        self.assertEqual(run["state"], "NEEDS_HUMAN")
        self.assertEqual(run["previous_state"], "GHERKIN_APPROVED")
        self.assertEqual(self.rules()[-1], "R19")
        rows = self.audit("integrity_failed")
        self.assertEqual([r["reason"] for r in rows], ["E_INTEGRITY"])
        self.eng.advance(SLUG)  # no longer bricked
        self.eng.load_run(SLUG)
        self.assertEqual(len(self.audit("integrity_failed")), 1)

    def test_human_cancel_works_after_integrity_failure_in_detection(self):
        self.to_gherkin_approved()
        self.tamper_and_edit()
        self.eng.request_state(SLUG, "CANCELLED", "human")
        self.assertEqual(self.state(), "CANCELLED")

    def test_human_finish_works_after_integrity_failure_in_detection(self):
        self.to_gherkin_approved()
        self.tamper_and_edit()
        self.eng.finish(SLUG, "abandoned", "human")
        self.assertEqual(self.state(), "CANCELLED")

    def test_resume_re_detects_feature_edit_made_while_parked(self):
        self.to_gherkin_approved()
        self.eng.advance(SLUG)
        self.assertEqual(self.state(), "EXECUTING")
        self.eng.request_state(SLUG, "NEEDS_HUMAN", "engine", reason="x")
        f = self.sdir() / "features/balance.feature"
        f.write_text(f.read_text() + "\n")
        self.eng.request_state(SLUG, "EXECUTING", "human")
        self.assertEqual(self.state(), "GHERKIN_REVIEW")
        self.assertEqual(self.rules()[-1], "R18")
        self.assertEqual(self.approvals("gherkin")[0]["state"], "INVALIDATED")

    def test_resume_from_blocked_re_detects_too(self):
        self.to_gherkin_approved()
        self.eng.request_state(SLUG, "BLOCKED", "engine")
        f = self.sdir() / "features/balance.feature"
        f.write_text(f.read_text() + "\n")
        self.eng.request_state(SLUG, "GHERKIN_APPROVED", "human")
        self.assertEqual(self.state(), "GHERKIN_REVIEW")

    def test_resume_to_execution_without_approval_parks_the_run(self):
        self.to_gherkin_approved()
        self.eng.advance(SLUG)
        self.eng.request_state(SLUG, "NEEDS_HUMAN", "engine", reason="x")
        self.eng.reg.update_row("approvals", self.approvals("gherkin")[0]["id"], state="INVALIDATED")
        with self.assertRaises(SentinelError) as c:
            self.eng.request_state(SLUG, "EXECUTING", "human")
        self.assertEqual(c.exception.code, "E_APPROVAL_MISSING")
        self.assertEqual(self.state(), "NEEDS_HUMAN")

    def test_detection_is_kept_when_the_command_then_fails(self):
        self.to_gherkin_review()
        p = self.sdir() / "spec.md"
        p.write_text(p.read_text() + "\nedit\n")
        with self.assertRaises(SentinelError):
            self.eng.pending_approval(SLUG, "gherkin")
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.assertEqual([a["version"] for a in self.artifacts("spec")], [1, 2])
        self.assertTrue((self.ws / ".sentinel/runs" / SLUG / "artifacts/spec-v2.md").is_file())
        self.assertEqual(self.rules()[-1], "R17")

    def test_invalid_edited_spec_is_not_stored_and_cannot_be_approved(self):
        self.to_gherkin_approved()
        (self.sdir() / "spec.md").write_text("garbage\n")
        self.eng.load_run(SLUG)
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.assertEqual([a["version"] for a in self.artifacts("spec")], [1])
        self.assertFalse((self.ws / ".sentinel/runs" / SLUG / "artifacts/spec-v2.md").exists())
        self.assertEqual([a["state"] for a in self.approvals("specification")], ["INVALIDATED"])
        with self.assertRaises(SentinelError) as c:
            self.approve("spec")
        self.assertEqual(c.exception.code, "E_VALIDATION")
        self.write_spec(version=2)  # fixed: stored and open again
        self.eng.load_run(SLUG)
        self.assertEqual([(a["version"], a["state"]) for a in self.approvals("specification")],
                         [(1, "INVALIDATED"), (2, "IN_REVIEW")])

    def test_feedback_not_written_when_the_commit_fails(self):
        self.to_spec_review()
        prefix = self.hash_prefix("spec")
        real = self.eng.reg._c

        class FailingCommit:
            def __getattr__(self, name):
                return getattr(real, name)

            def execute(self, sql, *a):
                if sql == "COMMIT":
                    real.execute("ROLLBACK")
                    raise RuntimeError("commit failed")
                return real.execute(sql, *a)
        self.eng.reg._c = FailingCommit()
        with self.assertRaises(RuntimeError):
            self.eng.decide(SLUG, "spec", "changes", "human", prefix=prefix, comment="fix it", approver="dev")
        self.eng.reg._c = real
        self.assertEqual(self.eng.brief_feedback(SLUG, "specifier"), [])
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")

    def test_gherkin_check_needs_an_approved_spec(self):
        self.to_gherkin_review()
        sp = self.approvals("specification")[0]
        self.eng.reg.update_row("approvals", sp["id"], state="INVALIDATED")
        with self.assertRaises(SentinelError) as c:
            self.eng.review(SLUG, "gherkin")
        self.assertEqual(c.exception.code, "E_APPROVAL_MISSING")


class Start(PB):
    def test_AC_GHA_06a_both_approvals_start_execution(self):
        self.to_gherkin_approved()
        self.eng.advance(SLUG)
        self.assertEqual(self.state(), "EXECUTING")
        self.assertEqual(self.rules()[-1], "R12")

    def test_AC_GHA_06b_feature_edited_before_execution_blocks_it(self):
        self.to_gherkin_approved()
        p = self.sdir() / "features/balance.feature"
        p.write_text(p.read_text() + "\n")
        self.eng.advance(SLUG)
        self.assertEqual(self.state(), "GHERKIN_REVIEW")
        self.assertNotIn("R12", self.rules())

    def test_AC_GHA_06c_missing_approval_record_goes_to_needs_human(self):
        self.to_gherkin_approved()
        ap = self.approvals("gherkin")[0]
        self.eng.reg._c.execute("DELETE FROM approvals WHERE id=?", (ap["id"],))
        with self.assertRaises(SentinelError) as c:
            self.eng.advance(SLUG)
        self.assertEqual(c.exception.code, "E_APPROVAL_MISSING")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertEqual(self.events("run.state_changed")[-1]["payload"]["reason"], "Gherkin approval missing")

    def test_AC_ART_01c_approval_record_hash_mismatch(self):
        self.to_gherkin_approved()
        ap = self.approvals("gherkin")[0]
        self.eng.reg._c.execute("UPDATE approvals SET sha256=? WHERE id=?", ("0" * 64, ap["id"]))
        with self.assertRaises(SentinelError) as c:
            self.eng.advance(SLUG)
        self.assertEqual(c.exception.code, "E_INTEGRITY")
        self.assertEqual(self.state(), "NEEDS_HUMAN")
        self.assertEqual(self.events("run.state_changed")[-1]["payload"]["reason"],
                         "approval record does not match artifact")
        self.assertEqual(len(self.audit("integrity_failed")), 1)

    def test_AC_ART_01b_tampered_stored_copy_refuses_decision(self):
        self.to_spec_review()
        prefix = self.hash_prefix("spec")
        stored = self.ws / ".sentinel/runs" / SLUG / "artifacts/spec-v1.md"
        stored.write_text(stored.read_text() + "tampered")
        with self.assertRaises(SentinelError) as c:
            self.eng.decide(SLUG, "spec", "approve", "human", prefix=prefix)
        self.assertEqual(c.exception.code, "E_INTEGRITY")
        self.assertEqual(self.approvals("specification")[0]["state"], "IN_REVIEW")
        rows = self.audit("integrity_failed")
        self.assertEqual([r["target"] for r in rows], [f"{SLUG}/specification"])

    def test_AC_ART_01d_review_checks_stored_hash(self):
        self.to_spec_review()
        stored = self.ws / ".sentinel/runs" / SLUG / "artifacts/spec-v1.md"
        stored.write_text(stored.read_text() + "tampered")
        with self.assertRaises(SentinelError) as c:
            self.eng.review(SLUG, "spec")
        self.assertEqual(c.exception.code, "E_INTEGRITY")


class Review(PB):
    def test_AC_SPA_04b_first_version_has_no_diff(self):
        self.to_spec_review()
        info = self.eng.review(SLUG, "spec")
        self.assertIsNone(info["diff"])
        self.assertEqual(info["version"], 1)
        self.assertEqual(info["sha256"], A.spec_hash(self.sdir() / "spec.md"))
        self.assertIn("Problem statement", info["text"])

    def test_AC_GHA_05a_review_gherkin_lists_files_and_coverage(self):
        self.to_gherkin_review()
        info = self.eng.review(SLUG, "gherkin")
        self.assertEqual(info["paths"], ["features/balance.feature", "features/request_form.feature"])
        self.assertEqual(len(info["scenarios"]), 2)
        self.assertEqual(len(info["coverage"]["rows"]), 15)
        self.assertIn("concurrency: missing", info["warnings"])
        self.assertEqual(info["sha256"], A.gherkin_set_hash(self.sdir() / "features")[0])

    def test_review_without_artifact_is_refused(self):
        self.mk()
        with self.assertRaises(SentinelError) as c:
            self.eng.review(SLUG, "spec")
        self.assertEqual(c.exception.code, "E_PRECONDITION")

    def test_review_unknown_run(self):
        with self.assertRaises(SentinelError) as c:
            self.eng.review("nope", "spec")
        self.assertEqual(c.exception.code, "E_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
