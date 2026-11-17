#!/usr/bin/env python3
"""Make tests/fixtures/ws-0.1.0b7.tar.gz: a workspace written by the 0.1.0b7 release (from the git tag v0.1.0b7),
with an open run "old-open" (tier 2) and a finished run "old-done" (tier 1). Also writes ws-0.1.0b7.expected.json
with what `sentinel resume old-open` printed. Run once; the result is checked in (AC-OPS-03b).
"""
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import release_gate as gate  # noqa: E402

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", "HOME": "/nonexistent"}


def sh(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"{cmd}: {r.stdout}{r.stderr}")
    return r.stdout


def main():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        cli = str(gate.legacy_cli(d / "b7"))
        shared = d / "shared.git"
        sh(["git", "init", "-q", "--bare", "-b", "main", str(shared)], d)
        ws = d / "ws"
        (ws / "app").mkdir(parents=True)
        sh(["git", "init", "-q", "-b", "main"], ws / "app")
        (ws / "app" / "a.txt").write_text("x\n")
        sh(["git", "add", "."], ws / "app")
        sh(["git", "commit", "-qm", "init"], ws / "app")
        s = [sys.executable, cli]
        sh(s + ["init", "--non-interactive", "--shape", "single", "--set", "app.path=./app", "--shared-repo", str(shared)], ws)
        sh(s + ["run", "new", "old-open", "--tier", "2"], ws)
        sh(s + ["run", "new", "old-done", "--tier", "1"], ws)
        sh(s + ["run", "update", "old-done", "--stage", "coder"], ws)
        sh(s + ["run", "finish", "old-done", "--outcome", "passed"], ws)
        resume = json.loads(sh(s + ["resume", "old-open"], ws))
        # make the shared repo location relative, so the fixture works wherever it is unpacked (ws/ and shared.git/ side by side)
        cfg = ws / "sentinel.config.yaml"
        cfg.write_text(cfg.read_text().replace(str(shared), "../shared.git"))
        sh(["git", "remote", "set-url", "origin", "../../../shared.git"], ws / ".sentinel" / "shared")
        out = ROOT / "tests" / "fixtures"
        with tarfile.open(out / "ws-0.1.0b7.tar.gz", "w:gz") as t:
            t.add(ws, arcname="ws")
            t.add(shared, arcname="shared.git")
        (out / "ws-0.1.0b7.expected.json").write_text(json.dumps({"resume_old_open": resume}, indent=2) + "\n")
        print("wrote", out / "ws-0.1.0b7.tar.gz")


if __name__ == "__main__":
    main()
