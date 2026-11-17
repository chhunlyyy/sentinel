#!/usr/bin/env python3
"""Start `sentinel dashboard --no-open` of an installed wheel on a pseudo-terminal, for the browser tests.

    python3 tools/serve_installed.py WHEEL_ENV_DIR

Prepares a throwaway HOME and a workspace with one repo and one run, runs the installed `sentinel` with a PATH that
holds git only (no node, no npm), prints one JSON line {"url": ..., "port": ..., "project": ...} and then keeps the
server up until its standard input closes or it gets SIGTERM. Used by dashboard/e2e/installed_wheel.spec.ts
(AC-OPS-01b, AC-DSH-06h).
"""
import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def main():
    env_dir = Path(sys.argv[1])
    ready = json.loads((env_dir / "ready.json").read_text())
    exe = ready["sentinel"]
    root = Path(tempfile.mkdtemp(prefix="installed-"))
    home, bindir, ws = root / "home", root / "bin", root / "ws" / "demo-ws"
    home.mkdir()
    bindir.mkdir()
    (bindir / "git").symlink_to(shutil.which("git"))
    (ws / "app").mkdir(parents=True)
    env = {"HOME": str(home), "USER": "dev", "LOGNAME": "dev", "PATH": str(bindir), "PYTHONDONTWRITEBYTECODE": "1", **GIT_ENV}

    def run(*args):
        r = subprocess.run([exe, *args], cwd=ws, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if r.returncode:
            raise SystemExit(f"{args}: {r.stdout}{r.stderr}")

    for cmd in (["init", "-q", "-b", "main"], ["add", "."], ["commit", "-qm", "init"]):
        if cmd[0] == "add":
            (ws / "app" / "a.txt").write_text("x\n")
        subprocess.run(["git", *cmd], cwd=ws / "app", env=env, capture_output=True, check=True)
    run("init", "--non-interactive", "--local-only", "--shape", "single", "--set", "app.path=./app")
    run("run", "new", "demo-run", "--type", "feature")
    master, slave = pty.openpty()
    proc = subprocess.Popen([exe, "dashboard", "--no-open"], cwd=ws, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True, close_fds=True)
    os.close(slave)

    def stop(*_):
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(root, ignore_errors=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    out, end = b"", time.time() + 30
    while time.time() < end:
        if select.select([master], [], [], 0.2)[0]:
            try:
                out += os.read(master, 4096)
            except OSError:
                break
        m = re.search(rb"(http://127\.0\.0\.1:(\d+)/auth\?t=[0-9a-f]{64})", out)
        if m:
            print(json.dumps({"url": m.group(1).decode(), "port": int(m.group(2)), "project": "demo-ws"}), flush=True)
            break
    else:
        print(json.dumps({"error": out.decode(errors="replace")}), flush=True)
        stop()
    try:
        while sys.stdin.read(1024):
            pass
    finally:
        stop()


if __name__ == "__main__":
    main()
