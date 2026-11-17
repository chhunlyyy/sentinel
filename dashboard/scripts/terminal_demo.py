"""Runs a short real Sentinel session in a throwaway workspace and writes docs/images/.terminal.txt (the input of the
terminal picture in the README). Nothing is typed by hand: the lines are the commands and their real output.

    python3 scripts/terminal_demo.py     # then: node scripts/showcase.mjs
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = [sys.executable, str(ROOT / "sentinel" / "scripts" / "sentinel.py")]
OUT = ROOT / "docs" / "images" / ".terminal.txt"

tmp = Path(tempfile.mkdtemp(prefix="sentinel-demo-"))
env = {**os.environ, "HOME": str(tmp / "home"), "GIT_AUTHOR_NAME": "demo", "GIT_AUTHOR_EMAIL": "demo@example.com",
       "GIT_COMMITTER_NAME": "demo", "GIT_COMMITTER_EMAIL": "demo@example.com", "NO_COLOR": "1"}
(tmp / "home").mkdir()
ws = tmp / "ws"
subprocess.run(["git", "init", "-q", str(ws / "app")], check=True, env=env)
(ws / "app" / "build.gradle").write_text('plugins { id "java" }\n')
subprocess.run(["git", "-C", str(ws / "app"), "add", "-A"], check=True, env=env)
subprocess.run(["git", "-C", str(ws / "app"), "commit", "-qm", "init"], check=True, env=env)
subprocess.run(["git", "init", "-q", "--bare", str(tmp / "shared.git")], check=True, env=env)
subprocess.run(CLI + ["--dir", str(ws), "init", "--non-interactive", "--shape", "single", "--shared-repo", str(tmp / "shared.git")],
               capture_output=True, text=True, env=env)


def run(shown, args, keep=None, stdin=subprocess.DEVNULL):
    r = subprocess.run(CLI + ["--dir", str(ws), *args], capture_output=True, text=True, env=env, stdin=stdin, cwd=ws)
    text = (r.stdout + r.stderr)
    lines = [l for l in text.splitlines() if l.strip()]
    if keep:
        lines = [l.strip() for l in lines if re.search(keep, l)]
    return ["$ " + shown] + lines + [""]


lines = ["# a run, step by step: the engine decides, a human approves", ""]
lines += run("sentinel --version", ["--version"])
lines += run("sentinel run new leave-balance | grep -E '\"(state|execution_status|acceptance_status)\"'", ["run", "new", "leave-balance"], keep=r'"(state|execution_status|acceptance_status)"')
lines += run("sentinel triage leave-balance --factors repos=1,files=3 | grep -E '\"(state|tier)\"'", ["triage", "leave-balance", "--factors", "repos=1,files=3"], keep=r'"(state|tier)"')
lines += run("sentinel next leave-balance", ["next", "leave-balance"])
lines += ["# an agent has no terminal, so it cannot approve"]
lines += run("sentinel approve leave-balance spec < /dev/null", ["approve", "leave-balance", "spec"])
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(lines).rstrip() + "\n")
shutil.rmtree(tmp, ignore_errors=True)
print(OUT.read_text())
