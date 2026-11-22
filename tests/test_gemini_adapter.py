"""The built-in `gemini` runner against the real Gemini CLI 0.60.0 (v2.1 housekeeping).

Captured on a throwaway git repo with `gemini -p ...`: the account used was refused (IneligibleTierError, exit 55), so no
successful answer was ever captured; the checks below cover what the real CLI did show: its flags, its exit code, its
stderr (a stack trace after the reason, and the trusted-folder refusal that `--skip-trust` avoids)."""
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "sentinel" / "scripts"))

import run_stage  # noqa: E402
import sentinel  # noqa: E402

HELP = (HERE / "fixtures" / "gemini_0.60.0_help.txt").read_text()
STDERR = (HERE / "fixtures" / "gemini_0.60.0_headless_ineligible.stderr").read_text()


class GeminiRunner(unittest.TestCase):
    def runner(self):
        return run_stage.DEFAULT_RUNNERS["gemini"]

    def test_every_flag_the_runner_uses_exists_in_the_real_cli_help(self):
        r = self.runner()
        flags = [r["prompt_flag"], r["model_flag"], r["add_dir_flag"], *[a for a in r["args"] + r["unsafe_args"] if a.startswith("-")]]
        for flag in flags:
            with self.subTest(flag):
                self.assertRegex(HELP, r"(?m)^\s+(?:-\w, )?" + re.escape(flag) + r"\b")

    def test_the_headless_command_edits_files_and_trusts_the_folder(self):
        command, stdin = run_stage.build_command(self.runner(), "do it", "gemini-2.5-flash", None, [Path("/ws/.sentinel")])
        self.assertEqual(command, ["gemini", "--approval-mode", "auto_edit", "--skip-trust", "-m", "gemini-2.5-flash",
                                   "--include-directories", "/ws/.sentinel", "-p", "do it"])
        self.assertIsNone(stdin)
        self.assertIn("auto_edit", HELP)  # a documented --approval-mode choice

    def test_the_real_refusal_names_the_trusted_folder_flag_the_runner_passes(self):
        self.assertIn("--skip-trust", STDERR)

    def test_the_reason_of_a_failed_call_is_the_error_line_not_the_end_of_the_stack_trace(self):
        line = sentinel._failure_line(STDERR)
        self.assertTrue(line.startswith("Error authenticating: IneligibleTierError"), line)
        self.assertFalse(line.startswith("at "))
        self.assertEqual(sentinel._failure_line("plain\nlast words"), "last words")
        self.assertEqual(sentinel._failure_line(""), "failed")

    def test_a_model_check_reports_the_real_reason_and_passes_skip_trust(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "argv.txt").write_text("")
            stub = d / "gemini"
            stub.write_text(f"#!{sys.executable}\nimport sys\nopen({str(d / 'argv.txt')!r}, 'w').write(' '.join(sys.argv[1:]))\n"
                            f"sys.stderr.write(open({str(HERE / 'fixtures' / 'gemini_0.60.0_headless_ineligible.stderr')!r}).read())\nsys.exit(55)\n")
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
            old = os.environ["PATH"]
            os.environ["PATH"] = f"{d}{os.pathsep}{old}"
            try:
                config = {"single_model": False}
                problems = sentinel.model_problems(config, "qa", {"runner": "gemini", "model": "gemini-2.5-flash"}, self.runner(), True)
            finally:
                os.environ["PATH"] = old
            self.assertEqual(len(problems), 1)
            self.assertIn("IneligibleTierError", problems[0])
            self.assertNotIn("processTicksAndRejections", problems[0])
            self.assertIn("--skip-trust", (d / "argv.txt").read_text())


if __name__ == "__main__":
    unittest.main()
