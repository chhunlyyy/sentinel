"""Phase B part 2 (PB-02): `sentinel review` and `sentinel approve` through the real CLI and a pty."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sentinel" / "scripts"))

from pb_helpers import CLIBase, GOOD, PtyProc, PROMPT, SLUG, spec_text  # noqa: E402
import pb_helpers  # noqa: E402


class Review(CLIBase):
    def test_AC_SPA_04a_review_shows_text_hash_diff_and_warnings(self):
        self.to_spec_review(text=spec_text(reqs=("REQ-1: a", "REQ-2: b"), acs=("AC-1 (REQ-1): a",)))
        self.approve("spec", decision="changes", comment="more")
        self.write_spec(spec_text(version=2, reqs=("REQ-1: a", "REQ-2: b"), acs=("AC-1 (REQ-1): a",)) + "\nrevised\n")
        self.eng.task_completed(SLUG, "specifier")
        code, out = self.cli("review", SLUG, "spec")
        self.assertEqual(code, 0, out)
        self.assertIn("revised", out)
        sha = self.artifacts("spec")[-1]["sha256"]
        self.assertIn(sha, out)
        self.assertIn("+revised", out)
        self.assertIn("REQ-2 has no acceptance criterion", out)

    def test_AC_SPA_04b_first_version_has_no_diff(self):
        self.to_spec_review()
        code, out = self.cli("review", SLUG, "spec")
        self.assertEqual(code, 0, out)
        self.assertIn("no previous reviewed version", out)

    def test_review_needs_no_tty(self):
        self.to_spec_review()
        code, out = self.cli("review", SLUG, "spec")
        self.assertEqual(code, 0, out)

    def test_AC_GHA_05a_review_gherkin(self):
        self.to_gherkin_review()
        code, out = self.cli("review", SLUG, "gherkin")
        self.assertEqual(code, 0, out)
        self.assertIn("features/balance.feature", out)
        self.assertIn("features/request_form.feature", out)
        self.assertIn("@AC-1", out)
        self.assertIn("concurrency: missing", out)
        self.assertIn(self.artifacts("gherkin")[0]["sha256"], out)
        self.assertIn("coverage incomplete", out)

    def test_AC_SPA_04c_bad_arguments(self):
        self.to_spec_review()
        code, out = self.cli("review", SLUG, "tests")
        self.assertEqual(code, 2)
        code, out = self.cli("review", "no-such-run", "spec")
        self.assertEqual(code, 5)
        self.assertIn("E_NOT_FOUND", out)

    def test_AC_ART_01d_review_tampered_copy(self):
        self.to_spec_review()
        stored = self.ws / ".sentinel/runs" / SLUG / "artifacts/spec-v1.md"
        stored.write_text("x")
        code, out = self.cli("review", SLUG, "spec")
        self.assertEqual(code, 5)
        self.assertIn("E_INTEGRITY", out)

    def test_AC_SPA_08f_review_deleted_spec_shows_error(self):
        self.to_gherkin_approved()
        (self.sdir() / "spec.md").unlink()
        code, out = self.cli("review", SLUG, "spec")
        self.assertIn(f"specs/{SLUG}/spec.md not found", out)

    def test_review_on_legacy_run_is_refused(self):
        self.eng.reg.insert_run({"slug": "old-run", "tier": 2, "state": "LEGACY", "workflow_version": "0.1",
                                 "execution_status": "running", "acceptance_status": "pending"})
        code, out = self.cli("review", "old-run", "spec")
        self.assertEqual(code, 5)
        self.assertIn("E_TRANSITION", out)


class ApproveTty(CLIBase):
    def decided(self):
        return self.eng.reg.list_events(self.run_row()["id"], "approval.decided")

    def test_AC_SPA_06a_approve_at_terminal(self):
        self.to_spec_review()
        sha = self.artifacts("spec")[0]["sha256"]
        code, out = self.tty("approve", SLUG, "spec", "-m", "Looks right", typed=[sha[:8]])
        self.assertEqual(code, 0, out)
        self.assertIn(sha, out)
        self.assertEqual(self.state(), "SPECIFICATION_APPROVED")
        ap = self.approvals("specification")[0]
        self.assertEqual((ap["state"], ap["comment"], ap["channel"]), ("APPROVED", "Looks right", "tty"))
        self.assertEqual(ap["approver"], os.environ.get("USER") or __import__("getpass").getuser())
        self.assertEqual(self.decided()[0]["payload"]["approver_name"], "Dev User")
        self.assertEqual(self.audit("approve")[0]["target"], f"{SLUG}/specification")

    def test_conflicting_decision_flags_and_removed_aliases_are_refused(self):
        self.to_spec_review()
        code, out = self.cli("approve", SLUG, "spec", "--reject", "--request-changes", "-m", "x")
        self.assertEqual(code, 1, out)
        self.assertIn("choose one of", out)
        for extra in (["--gate", "spec"], ["--decision", "approve"]):
            code, out = self.cli("approve", SLUG, "spec", *extra)
            self.assertEqual(code, 2, out)
        self.assertEqual(self.approvals("specification")[0]["state"], "IN_REVIEW")

    def test_AC_GHA_05b_approve_gherkin(self):
        self.to_gherkin_review()
        p = self.hash_prefix("gherkin")
        code, out = self.tty("approve", SLUG, "gherkin", typed=[p])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state(), "GHERKIN_APPROVED")

    def test_AC_SPA_06b_prefix_variants(self):
        for i, fmt in enumerate(("{p}", "{P}", "  {p} ")):
            with self.subTest(fmt=fmt):
                slug = f"lb-{i}"
                self.to_spec_review(slug)
                p = self.hash_prefix("spec", slug)
                code, out = self.tty("approve", slug, "spec", typed=[fmt.format(p=p, P=p.upper())])
                self.assertEqual(code, 0, out)

    def test_AC_SPA_05a_request_changes(self):
        self.to_spec_review()
        p = self.hash_prefix("spec")
        code, out = self.tty("approve", SLUG, "spec", "--request-changes", "-m", "Add the half-day case", typed=[p])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state(), "PLANNED")
        self.assertEqual(self.approvals("specification")[0]["state"], "CHANGES_REQUESTED")

    def test_AC_SPA_05b_request_changes_needs_comment(self):
        self.to_spec_review()
        for flags in (["--request-changes"], ["--request-changes", "-m", ""], ["--request-changes", "-m", "  "]):
            with self.subTest(flags=flags):
                code, out = self.tty("approve", SLUG, "spec", *flags)
                self.assertEqual(code, 5, out)
                self.assertIn("E_VALIDATION", out)
                self.assertNotIn(PROMPT, out)
                self.assertEqual(self.state(), "SPECIFICATION_REVIEW")

    def test_AC_SPA_05d_reject_cancels(self):
        self.to_spec_review()
        p = self.hash_prefix("spec")
        code, out = self.tty("approve", SLUG, "spec", "--reject", "-m", "Out of scope", typed=[p])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state(), "CANCELLED")
        self.assertEqual(self.approvals("specification")[0]["state"], "REJECTED")

    def test_AC_SEC_03a_non_tty_refused_and_audited(self):
        self.to_spec_review()
        for flags in ([], ["--request-changes", "-m", "x"], ["--reject", "-m", "x"]):
            with self.subTest(flags=flags):
                code, out = self.cli("approve", SLUG, "spec", *flags)
                self.assertEqual(code, 5, out)
                self.assertIn("E_NOT_TTY", out)
                self.assertNotIn(PROMPT, out)
                self.assertEqual(self.approvals("specification")[0]["state"], "IN_REVIEW")
                self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        rows = self.audit("approve_refused")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["target"], f"{SLUG}/specification")

    def test_AC_SEC_03a_stdin_tty_but_stdout_piped_refused(self):
        import pty
        import subprocess
        self.to_spec_review()
        master, slave = pty.openpty()
        r = subprocess.run(pb_helpers.CLI + self.d + ["approve", SLUG, "spec"], stdin=slave,
                           capture_output=True, text=True, env=pb_helpers.CLI_ENV)
        os.close(master)
        os.close(slave)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("E_NOT_TTY", r.stdout + r.stderr)

    def test_AC_SEC_03c_wrong_prefix(self):
        self.to_spec_review()
        p = self.hash_prefix("spec")
        for typed in ("00000000", p[:7], p[:7] + ("0" if p[7] != "0" else "1"), p + "ab", ""):
            with self.subTest(typed=typed):
                code, out = self.tty("approve", SLUG, "spec", typed=[typed])
                self.assertEqual(code, 5, out)
                self.assertIn("E_VALIDATION", out)
                self.assertEqual(self.approvals("specification")[0]["state"], "IN_REVIEW")

    def test_AC_SEC_03d_closed_prompt_stores_nothing(self):
        self.to_spec_review()
        code, out = self.tty("approve", SLUG, "spec", eof=True)
        self.assertEqual(code, 1, out)
        self.assertEqual(self.approvals("specification")[0]["state"], "IN_REVIEW")
        self.assertEqual(self.decided(), [])

    def test_AC_SPA_06c_wrong_state(self):
        self.to_spec_review()
        code, out = self.tty("approve", SLUG, "gherkin", typed=["00000000"])
        self.assertEqual(code, 5, out)
        self.assertIn("E_TRANSITION", out)
        self.assertNotIn(PROMPT, out)

    def test_AC_SPA_06d_second_approval(self):
        self.to_spec_review()
        p = self.hash_prefix("spec")
        self.assertEqual(self.tty("approve", SLUG, "spec", typed=[p])[0], 0)
        code, out = self.tty("approve", SLUG, "spec", typed=[p])
        self.assertEqual(code, 5)
        self.assertIn("E_TRANSITION", out)
        self.assertEqual(len(self.decided()), 1)

    def test_AC_SPA_06e_legacy_run(self):
        self.eng.reg.insert_run({"slug": "old-run", "tier": 2, "state": "LEGACY", "workflow_version": "0.1",
                                 "execution_status": "running", "acceptance_status": "pending"})
        code, out = self.tty("approve", "old-run", "spec", typed=["00000000"])
        self.assertEqual(code, 5, out)
        self.assertIn("E_TRANSITION", out)

    def test_AC_GHA_07b_docs_run_gherkin_refused(self):
        self.to_spec_approved(typ="docs")
        code, out = self.tty("approve", SLUG, "gherkin", typed=["00000000"])
        self.assertEqual(code, 5, out)
        self.assertIn("E_PRECONDITION", out)
        self.assertIn("docs-only", out)

    def test_AC_SPA_08a_edit_before_approve_is_stale(self):
        self.to_spec_review()
        old = self.hash_prefix("spec")
        p = self.sdir() / "spec.md"
        p.write_text(p.read_text() + "\nmore\n")
        code, out = self.tty("approve", SLUG, "spec", typed=[old])
        self.assertEqual(code, 5, out)
        self.assertIn("E_APPROVAL_STALE", out)
        new = self.artifacts("spec")[-1]["sha256"]
        self.assertIn(new, out)
        self.assertEqual(self.approvals("specification")[-1]["state"], "IN_REVIEW")
        self.assertEqual(len(self.artifacts("spec")), 2)

    def test_AC_SPA_08b_edit_between_prompt_and_typing(self):
        self.to_spec_review()
        shown = self.hash_prefix("spec")
        p = self.sdir() / "spec.md"
        code, out = self.tty("approve", SLUG, "spec", typed=[shown],
                             on_prompt=lambda: p.write_text(p.read_text() + "\nrace\n"))
        self.assertEqual(code, 5, out)
        self.assertIn("E_APPROVAL_STALE", out)
        self.assertFalse([a for a in self.approvals() if a["state"] == "APPROVED"])

    def test_AC_SPA_06f_two_terminals_one_wins(self):
        self.to_spec_review()
        p = self.hash_prefix("spec")
        procs = [PtyProc(self.d + ["approve", SLUG, "spec"]) for _ in range(2)]
        for pr in procs:
            self.assertTrue(pr.wait_for(PROMPT))
        for pr in procs:
            pr.send(p + "\n")
        res = [pr.finish() for pr in procs]
        self.assertEqual(sorted(c for c, _ in res), [0, 5], res)
        self.assertTrue(any("E_TRANSITION" in o for c, o in res if c == 5))
        self.assertEqual(len(self.decided()), 1)
        self.assertEqual(len(self.audit("approve")), 1)

    def test_AC_SPA_06g_approve_vs_request_changes(self):
        self.to_spec_review()
        p = self.hash_prefix("spec")
        procs = [PtyProc(self.d + ["approve", SLUG, "spec"] + fl) for fl in ([], ["--request-changes", "-m", "c"])]
        for pr in procs:
            self.assertTrue(pr.wait_for(PROMPT))
        for pr in procs:
            pr.send(p + "\n")
        res = [pr.finish() for pr in procs]
        self.assertEqual(len(self.decided()), 1, res)
        self.assertIn(self.state(), ("SPECIFICATION_APPROVED", "PLANNED"))


class Tamper(CLIBase):
    def test_AC_ART_01b_tampered_copy_refused(self):
        self.to_spec_review()
        p = self.hash_prefix("spec")
        stored = self.ws / ".sentinel/runs" / SLUG / "artifacts/spec-v1.md"
        stored.write_text(stored.read_text() + "x")
        code, out = self.tty("approve", SLUG, "spec", typed=[p])
        self.assertEqual(code, 5, out)
        self.assertIn("E_INTEGRITY", out)
        self.assertEqual(len(self.audit("integrity_failed")), 1)


class SubmitHook(CLIBase):
    def test_submit_hook_runs_task_completion(self):
        self.mk()
        self.write_spec()
        code, out = self.cli("submit", SLUG, "--role", "specifier")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state(), "SPECIFICATION_REVIEW")
        self.mk("other")
        self.write_spec("", slug="other")
        code, out = self.cli("submit", "other", "--role", "specifier")
        self.assertEqual(code, 1, out)
        self.assertIn("missing front matter", out)


class RunFinishTty(CLIBase):
    def test_run_finish_on_v2_needs_tty(self):
        self.mk(state="EXECUTING")
        code, out = self.cli("run", "finish", SLUG, "--outcome", "stopped")
        self.assertEqual(code, 5, out)
        self.assertIn("E_NOT_TTY", out)
        self.assertEqual(self.state(), "EXECUTING")

    def test_run_finish_on_v2_with_tty(self):
        self.mk(state="EXECUTING")
        code, out = run_tty_plain(self.d + ["run", "finish", SLUG, "--outcome", "stopped"])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.state(), "CANCELLED")


class LegacyRun(CLIBase):
    """0.1 runs keep their free-form spec flow (AC-SPA-01c, AC-ORC-08d)."""

    def legacy(self):
        code, out = self.cli("run", "new", "old-run", "--tier", "2")
        self.assertEqual(code, 0, out)
        spec = self.ws / ".sentinel/shared/specs/old-run/spec.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text("just some notes, no front matter and none of the required sections\n")
        return spec

    def registry_rows(self):
        reg = self.eng.reg
        return {t: reg.rows(t) for t in ("artifacts", "approvals")} | {
            "invalidated": [e for e in reg._c.execute("SELECT * FROM events WHERE type = 'approval.invalidated'")]}

    def test_AC_SPA_01c_legacy_spec_set_is_not_validated(self):
        self.legacy()
        code, out = self.cli("spec", "set", "old-run", "--status", "draft")
        self.assertEqual(code, 0, out)
        index = json.loads((self.ws / ".sentinel/shared/specs/index.json").read_text())
        self.assertEqual(index["old-run"]["status"], "draft")
        self.assertEqual(self.registry_rows(), {"artifacts": [], "approvals": [], "invalidated": []})
        state = json.loads((self.ws / ".sentinel/runs/old-run/state.json").read_text())
        self.assertNotIn("schema_version", state)

    def test_AC_ORC_08d_editing_a_legacy_spec_changes_nothing(self):
        spec = self.legacy()
        code, out = self.cli("run", "update", "old-run", "--stage", "repro")
        self.assertEqual(code, 0, out)
        state_file = self.ws / ".sentinel/runs/old-run/state.json"
        before = state_file.read_bytes()
        spec.write_text(spec.read_text() + "edited\n")
        code, out = self.cli("resume", "old-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["next"], "coder")
        self.assertEqual(state_file.read_bytes(), before)
        self.assertEqual(self.registry_rows(), {"artifacts": [], "approvals": [], "invalidated": []})
        self.assertEqual(sorted(p.name for p in state_file.parent.iterdir()), ["state.json"])


class AgentLaunch(CLIBase):
    def test_AC_SEC_03b_stage_launched_process_cannot_approve(self):
        self.to_gherkin_review()
        script = self.ws / "agent.py"
        out_file = self.ws / "agent.out"
        script.write_text(
            "import subprocess, sys\n"
            f"r = subprocess.run({pb_helpers.CLI + self.d + ['approve', SLUG, 'gherkin']!r}, capture_output=True, text=True)\n"
            f"open({str(out_file)!r}, 'w').write(f'{{r.returncode}}\\n{{r.stdout}}{{r.stderr}}')\n")
        cfg = self.ws / "sentinel.config.yaml"
        cfg.write_text(cfg.read_text() + f"runners:\n  agent:\n    command: {sys.executable} {script}\n")
        code, out = self.cli("stage", "run", "--stage", "docs", "--slug", SLUG, "--runner", "agent")
        self.assertEqual(code, 0, out)
        status, _, text = out_file.read_text().partition("\n")
        self.assertEqual(status, "5", text)
        self.assertIn("E_NOT_TTY", text)
        self.assertNotIn(PROMPT, text)
        self.assertEqual(self.state(), "GHERKIN_REVIEW")
        self.assertEqual(self.approvals("gherkin")[0]["state"], "IN_REVIEW")


def run_tty_plain(args):
    return PtyProc(args).finish()


if __name__ == "__main__":
    unittest.main()
