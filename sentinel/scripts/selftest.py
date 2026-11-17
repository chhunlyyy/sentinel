#!/usr/bin/env python3
import json
import os
import re
import hashlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CLI = [sys.executable, str(ROOT / "scripts" / "sentinel.py")]
ENV = {**os.environ, "GIT_AUTHOR_NAME": "selftest", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "selftest", "GIT_COMMITTER_EMAIL": "t@example.com"}
RESULTS = []
FAKE_JWT = "eyJ" + "hbGciOiJIUzI1NiJ9." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0." + "abcdefghijk"
FAKE_HOME = "/ho" + "me/someone"
FAKE_MAIL = "a@real-" + "domain.org"


def run(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=ENV)
    return result.returncode, result.stdout + result.stderr


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


def git_repo(path, marker):
    path.mkdir(parents=True)
    (path / marker).write_text("")
    run(["git", "init", "-q", "-b", "main"], cwd=path)
    run(["git", "add", "."], cwd=path)
    run(["git", "commit", "-q", "-m", "init"], cwd=path)


def write_config(ws, mutate):
    path = ws / "sentinel.config.yaml"
    config = yaml.safe_load(path.read_text())
    mutate(config)
    path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))


def db_set(ws, slug, **fields):
    """Test fixture: put a version 2 run into a state the CLI cannot reach yet."""
    conn = sqlite3.connect(ws / ".sentinel/sentinel.db")
    sets = ",".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE runs SET {sets} WHERE slug=?", [*fields.values(), slug])
    conn.commit()
    conn.close()


def db_row(ws, slug):
    conn = sqlite3.connect(ws / ".sentinel/sentinel.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM runs WHERE slug=?", (slug,)).fetchone()
    conn.close()
    return dict(row) if row else None


def phase_a_checks(tmp, remote):
    print("registry, engine and publish default (phase A)")
    sys.path.insert(0, str(ROOT / "scripts"))
    from registry import Registry
    w = tmp / "ws-a"
    w.mkdir()
    git_repo(w / "backend", "build.gradle")
    git_repo(w / "frontend", "next.config.ts")
    code, out = run(CLI + ["--dir", str(w), "init", "--shape", "fullstack", "--non-interactive", "--local-only"])
    check("AC-C-35a init --local-only writes auto_sync_push false", code == 0 and yaml.safe_load((w / "sentinel.config.yaml").read_text())["state"]["auto_sync_push"] is False, out[-200:])
    check("AC-PER-01a no registry before the first run command", not (w / ".sentinel/sentinel.db").exists())
    code, out = run(CLI + ["--dir", str(w), "run", "new", "leave-balance"])
    db = w / ".sentinel/sentinel.db"
    conn = sqlite3.connect(db) if db.exists() else None
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0] if conn else None
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] if conn else None
    check("AC-PER-01a the first run command creates the registry (WAL, latest schema)", code == 0 and mode == "wal" and int(version) == Registry.LATEST, out[-200:])
    row = db_row(w, "leave-balance") or {}
    check("AC-SM-02a run new makes a version 2 run, running and pending", row.get("workflow_version") == "2" and row.get("state") == "CREATED" and row.get("execution_status") == "running" and row.get("acceptance_status") == "pending", str(row))
    shas = {r: subprocess.run(["git", "-C", str(w / r), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() for r in ("backend", "frontend")}
    stored = dict(conn.execute("SELECT repo_id, baseline_sha FROM run_repos WHERE run_id=?", (row.get("id"),)).fetchall()) if conn else {}
    snap = conn.execute("SELECT sha256 FROM config_versions WHERE id=?", (row.get("config_snapshot_id"),)).fetchone() if conn else None
    cfg_hash = hashlib.sha256((w / "sentinel.config.yaml").read_bytes()).hexdigest()
    check("AC-PER-02a the registry stores both baseline commits and the config snapshot", stored == shas and snap is not None and snap[0] == cfg_hash, f"{stored} {snap}")
    if conn:
        conn.close()
    code, out = run(CLI + ["--dir", str(w), "triage", "leave-balance", "--factors", "repos=1,files=2"])
    view = json.loads((w / ".sentinel/runs/leave-balance/state.json").read_text())
    row = db_row(w, "leave-balance")
    check("AC-PER-04a triage rewrites the state.json view", code == 0 and view.get("schema_version") == 2 and view["state"] == "TRIAGED" and view["tier"] == 2 and view["baseline"] == shas and bool(view["stages"]) and view["execution_status"] == row["execution_status"] and view["acceptance_status"] == row["acceptance_status"], out[-200:])
    code, out = run(CLI + ["--dir", str(w), "run", "update", "leave-balance", "--stage", "coder"])
    check("AC-ORC-08c run update is refused on a version 2 run", code == 5 and "E_TRANSITION" in out, out[-200:])

    # legacy runs
    legacy = w / ".sentinel/runs/old-run"
    legacy.mkdir(parents=True)
    legacy_state = json.dumps({"slug": "old-run", "tier": 2, "initial_tier": 2, "adhoc": True, "stages": ["repro", "coder"], "completed": [], "sessions": {}, "rounds": {"review": 0, "qa": 0, "release_check": 0}, "baseline": {}, "started": "2026-01-01T00:00:00"}, indent=2)
    (legacy / "state.json").write_text(legacy_state)
    code, out = run(CLI + ["--dir", str(w), "resume", "old-run"])
    legacy_row = db_row(w, "old-run") or {}
    check("AC-ORC-08a a 0.1 run is indexed on first open and its state.json is untouched", legacy_row.get("workflow_version") == "0.1" and (legacy / "state.json").read_text() == legacy_state, str(legacy_row))
    run(CLI + ["--dir", str(w), "run", "update", "old-run", "--stage", "repro"])
    code, out = run(CLI + ["--dir", str(w), "resume", "old-run"])
    check("AC-ORC-08b a legacy run keeps run update and resume", code == 0 and json.loads(out)["next"] == "coder", out[-200:])
    code, out = run(CLI + ["--dir", str(w), "run", "new", "fresh-legacy", "--tier", "2"])
    check("a --tier run is a 0.1 run with a registry row", code == 0 and (db_row(w, "fresh-legacy") or {}).get("workflow_version") == "0.1", out[-200:])
    code, out = run(CLI + ["--dir", str(w), "run", "finish", "fresh-legacy"])
    row = db_row(w, "fresh-legacy") or {}
    check("run finish on a 0.1 run updates its registry row", code == 0 and (row.get("execution_status"), row.get("acceptance_status")) == ("completed", "accepted"), f"{out[-120:]} {row}")
    code, out = run(CLI + ["--dir", str(w), "resume", "leave-balance"])
    check("resume on a version 2 run is refused with E_TRANSITION", code == 5 and "E_TRANSITION" in out and "driven by the engine" in out, out[-200:])

    # run finish mapping
    for slug, state, outcome, execution, acceptance in (
            ("fin-stop", "EXECUTING", "stopped", "cancelled", "rejected"),
            ("fin-abandon", "EXECUTING", "abandoned", "cancelled", "rejected"),
            ("fin-passed", "COMPLETED", "passed", "completed", "pending")):
        run(CLI + ["--dir", str(w), "run", "new", slug])
        db_set(w, slug, state=state, **({"execution_status": "completed"} if state == "COMPLETED" else {}))
        code, out = run_tty(CLI + ["--dir", str(w), "run", "finish", slug, "--outcome", outcome])
        row = db_row(w, slug) or {}
        check(f"AC-SM-02e run finish --outcome {outcome} on {state}", code == 0 and row.get("execution_status") == execution and row.get("acceptance_status") == acceptance, f"{out[-160:]} {row}")
    run(CLI + ["--dir", str(w), "run", "new", "fin-unfinished"])
    db_set(w, "fin-unfinished", state="EXECUTING")
    code, out = run_tty(CLI + ["--dir", str(w), "run", "finish", "fin-unfinished", "--outcome", "passed"])
    check("AC-SM-02f run finish passed on an unfinished version 2 run is refused", code == 5 and "E_PRECONDITION" in out, out[-200:])

    # concurrency
    run(CLI + ["--dir", str(w), "run", "new", "race"])
    procs = [subprocess.Popen(CLI + ["--dir", str(w), "triage", "race", "--factors", "files=2"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=ENV) for _ in range(2)]
    outs = [(p.wait(), "".join(p.communicate())) for p in procs]
    codes = sorted(c for c, _ in outs)
    conn = sqlite3.connect(db)
    events = conn.execute("SELECT COUNT(*) FROM events WHERE run_id=? AND type='run.state_changed'", ((db_row(w, "race") or {})["id"],)).fetchone()[0]
    conn.close()
    check("AC-C-36a two CLI processes triage one run: one wins, the other gets E_TRANSITION", codes == [0, 5] and any("E_TRANSITION" in o for c, o in outs if c == 5) and events == 1, f"{codes} events={events}")

    # publish default
    pw = tmp / "ws-pub"
    pw.mkdir()
    git_repo(pw / "app", "package.json")
    code, out = run(CLI + ["--dir", str(pw), "init", "--shape", "single", "--non-interactive", "--shared-repo", str(remote)])
    cfg_path = pw / "sentinel.config.yaml"
    check("AC-C-35a init with a shared repo writes auto_sync_push false", code == 0 and yaml.safe_load(cfg_path.read_text())["state"]["auto_sync_push"] is False, out[-200:])
    run(CLI + ["--dir", str(pw), "run", "new", "leave-balance", "--adhoc"])
    run(CLI + ["--dir", str(pw), "run", "finish", "leave-balance"])
    code, out = run(CLI + ["--dir", str(pw), "sync", "push", "leave-balance", "--auto"])
    check("AC-C-35c sync push --auto does nothing under the new default", code == 0 and "auto_sync_push is off" in out and "refs/heads/sentinel/" not in run(["git", "ls-remote", str(remote)])[1], out[-200:])
    text = cfg_path.read_text().replace("auto_sync_push: false", "auto_sync_push: true")
    cfg_path.write_text(text)
    code, out = run(CLI + ["--dir", str(pw), "doctor"])
    check("AC-C-35b doctor notes automatic publishing is on and keeps the setting", "auto_sync_push is on" in out and cfg_path.read_text() == text, out[-200:])


def run_tty(cmd, typed=(), eof=False, on_prompt=None, cwd=None):
    """Run a command with a pseudo-terminal as stdin and stdout; answer the hash prompt with `typed`."""
    import pty
    pid, fd = pty.fork()
    if pid == 0:
        if cwd:
            os.chdir(cwd)
        os.execvpe(cmd[0], cmd, ENV)
    return tty_finish(pid, fd, typed, eof, on_prompt)


def tty_finish(pid, fd, typed=(), eof=False, on_prompt=None, wait_only=False):
    import select
    out, sent = b"", wait_only
    end = time.time() + 40
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if not data:
                break
            out += data
        if not sent and b"first 8 characters" in out:
            sent = True
            if on_prompt:
                on_prompt()
            if eof:
                os.write(fd, b"\x04")
            else:
                for t in typed:
                    os.write(fd, (t + "\n").encode())
    _, status = os.waitpid(pid, 0)
    os.close(fd)
    return os.waitstatus_to_exitcode(status), out.decode(errors="replace").replace("\r\n", "\n")


def db_all(ws, sql, args=()):
    conn = sqlite3.connect(ws / ".sentinel/sentinel.db")
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(sql, args)]
    conn.close()
    return rows


def lite_spec(slug, version=1, extra=""):
    secs = ["Problem statement", "Scope", "Out of scope", "Functional requirements", "Acceptance criteria",
            "Edge cases", "Security considerations", "Risks and assumptions"]
    body = {"Functional requirements": "- REQ-1: first\n- REQ-2: second", "Acceptance criteria": "- AC-1 (REQ-1): a\n- AC-2 (REQ-2): b"}
    parts = [f"---\nrun: {slug}\nversion: {version}\ntier: 1\n---\n"]
    parts += [f"## {n}\n{body.get(n, 'Text for ' + n + '.')}\n" for n in secs]
    return "\n".join(parts) + extra


FEATURES = {"balance.feature": "@REQ-1\nFeature: F\n\n  @AC-1 @unit @P1\n  Scenario: a\n    Given x\n    When y\n    Then z\n",
            "form.feature": "@REQ-2\nFeature: G\n\n  @AC-2 @integration @P1\n  Scenario: b\n    Given x\n    When y\n    Then z\n"}


def phase_b_checks(tmp):
    print("approval gates (phase B)")
    w = tmp / "ws-b"
    w.mkdir()
    git_repo(w / "backend", "build.gradle")
    code, out = run(CLI + ["--dir", str(w), "init", "--shape", "fullstack", "--non-interactive", "--local-only"])
    d = ["--dir", str(w)]
    specs = w / ".sentinel/shared/specs"

    def new_run(slug, state="PLANNED"):
        run(CLI + d + ["run", "new", slug])
        db_set(w, slug, state=state, tier=1, initial_tier=1)
        (specs / slug / "features").mkdir(parents=True, exist_ok=True)
        (specs / slug / "spec.md").write_text(lite_spec(slug))

    def submit(slug, role):
        """The orchestrator path of Phase C: a native task for the role goes through `task run` and `task complete`."""
        sys.path.insert(0, str(ROOT / "scripts"))
        from engine import Engine
        cfg = yaml.safe_load((w / "sentinel.config.yaml").read_text())
        eng = Engine(w / ".sentinel", w, cfg)
        try:
            tid = eng.create_task(slug, role, f"{role} work", [cfg["repos"][0]["id"]])["id"]
            eng.queue_task(tid)
        finally:
            eng.close()
        code, out = run(CLI + d + ["task", "run", tid])
        (w / ".sentinel/runs" / slug / "tasks" / tid / "result.json").write_text(json.dumps(
            {"schema": "agent-result-v1", "task_id": tid, "status": "completed", "summary": "done"}))
        return run(CLI + d + ["task", "complete", tid])

    def features(slug):
        for n, t in FEATURES.items():
            (specs / slug / "features" / n).write_text(t)

    def prefix(slug, kind):
        return db_all(w, "SELECT sha256 FROM approvals WHERE run_id=(SELECT id FROM runs WHERE slug=?) AND gate=? AND state='IN_REVIEW'", (slug, kind))[0]["sha256"][:8]

    def state(slug):
        return db_row(w, slug)["state"]

    def aps(slug, gate):
        return [r["state"] for r in db_all(w, "SELECT state FROM approvals WHERE run_id=(SELECT id FROM runs WHERE slug=?) AND gate=? ORDER BY rowid", (slug, gate))]

    new_run("lb")
    code, out = submit("lb", "specifier")
    check("AC-SPA-01a a valid specification opens the review with an IN_REVIEW approval", code == 0 and state("lb") == "SPECIFICATION_REVIEW" and aps("lb", "specification") == ["IN_REVIEW"], out[-200:])
    code, out = run(CLI + d + ["review", "lb", "spec"])
    check("AC-SPA-04b review of a first version says there is no previous reviewed version", code == 0 and "no previous reviewed version" in out and db_all(w, "SELECT sha256 FROM artifacts WHERE kind='spec'")[0]["sha256"] in out, out[-200:])
    code, out = run(CLI + d + ["review", "lb", "tests"])
    check("AC-SPA-04c review refuses an unknown gate with usage exit 2", code == 2, out[-200:])
    code, out = run(CLI + d + ["approve", "lb", "spec"])
    refused = db_all(w, "SELECT * FROM audit WHERE action='approve_refused'")
    check("AC-SEC-03a approve without a terminal is refused with E_NOT_TTY and audited", code == 5 and "E_NOT_TTY" in out and aps("lb", "specification") == ["IN_REVIEW"] and len(refused) == 1 and refused[0]["reason"] == "E_NOT_TTY", out[-200:])
    code, out = run_tty(CLI + d + ["approve", "lb", "spec"], typed=["00000000"])
    check("AC-SEC-03c a wrong hash prefix is refused with E_VALIDATION", code == 5 and "E_VALIDATION" in out and aps("lb", "specification") == ["IN_REVIEW"], out[-200:])
    code, out = run_tty(CLI + d + ["approve", "lb", "spec"], eof=True)
    check("AC-SEC-03d closing the prompt exits 1 and stores nothing", code == 1 and aps("lb", "specification") == ["IN_REVIEW"] and not db_all(w, "SELECT 1 FROM events WHERE type='approval.decided'"), out[-200:])
    code, out = run_tty(CLI + d + ["approve", "lb", "spec", "-m", "Looks right"], typed=[f"  {prefix('lb', 'specification').upper()} "])
    row = db_all(w, "SELECT * FROM approvals WHERE gate='specification'")[0]
    check("AC-SPA-06a a human at a terminal approves the specification (R5)", code == 0 and state("lb") == "SPECIFICATION_APPROVED" and row["state"] == "APPROVED" and row["channel"] == "tty" and row["comment"] == "Looks right" and len(db_all(w, "SELECT 1 FROM audit WHERE action='approve'")) == 1, out[-200:])
    code, out = run_tty(CLI + d + ["approve", "lb", "spec"], typed=["00000000"])
    check("AC-SPA-06d a second approval of the same version is refused with E_TRANSITION", code == 5 and "E_TRANSITION" in out, out[-200:])
    features("lb")
    code, out = submit("lb", "test_designer")
    check("AC-GHA-01a valid feature files open the Gherkin review", code == 0 and state("lb") == "GHERKIN_REVIEW" and aps("lb", "gherkin") == ["IN_REVIEW"], out[-200:])
    code, out = run(CLI + d + ["review", "lb", "gherkin"])
    check("AC-GHA-05a review lists the feature files, scenarios and coverage table", code == 0 and "features/balance.feature" in out and "@AC-1" in out and "concurrency" in out and "coverage incomplete" in out, out[-300:])
    code, out = run_tty(CLI + d + ["approve", "lb", "gherkin"], typed=[prefix("lb", "gherkin")])
    check("AC-GHA-05b a human approves the Gherkin set (R9)", code == 0 and state("lb") == "GHERKIN_APPROVED" and aps("lb", "gherkin") == ["APPROVED"], out[-200:])
    (specs / "lb/features/balance.feature").write_text(FEATURES["balance.feature"] + "\n  @AC-1 @unit @P1\n  Scenario: more\n    Given x\n    When y\n    Then z\n")
    code, out = run(CLI + d + ["review", "lb", "gherkin"])
    check("AC-GHA-05i a Gherkin edit after approval returns the run to GHERKIN_REVIEW (R18)", state("lb") == "GHERKIN_REVIEW" and aps("lb", "gherkin") == ["INVALIDATED", "IN_REVIEW"] and aps("lb", "specification") == ["APPROVED"], out[-200:])
    p = specs / "lb/spec.md"
    p.write_text(p.read_text() + "\nedit\n")
    code, out = run(CLI + d + ["review", "lb", "spec"])
    check("AC-SPA-08c a spec edit after approval returns the run to SPECIFICATION_REVIEW (R17)", state("lb") == "SPECIFICATION_REVIEW" and aps("lb", "specification") == ["INVALIDATED", "IN_REVIEW"] and aps("lb", "gherkin") == ["INVALIDATED", "INVALIDATED"], f"{aps('lb', 'specification')} {aps('lb', 'gherkin')} {out[-150:]}")

    new_run("stale")
    submit("stale", "specifier")
    old = prefix("stale", "specification")
    sp = specs / "stale/spec.md"
    sp.write_text(sp.read_text() + "\nmore\n")
    code, out = run_tty(CLI + d + ["approve", "stale", "spec"], typed=[old])
    check("AC-SPA-08a a spec edited after review is refused with E_APPROVAL_STALE and a new version is opened", code == 5 and "E_APPROVAL_STALE" in out and aps("stale", "specification") == ["INVALIDATED", "IN_REVIEW"], out[-250:])
    new_run("edit-race")
    submit("edit-race", "specifier")
    shown = prefix("edit-race", "specification")
    er = specs / "edit-race/spec.md"
    code, out = run_tty(CLI + d + ["approve", "edit-race", "spec"], typed=[shown], on_prompt=lambda: er.write_text(er.read_text() + "\nrace\n"))
    check("AC-SPA-08b a file edited between the prompt and the typed prefix is refused as stale", code == 5 and "E_APPROVAL_STALE" in out and "APPROVED" not in aps("edit-race", "specification"), out[-250:])

    new_run("chg")
    submit("chg", "specifier")
    code, out = run_tty(CLI + d + ["approve", "chg", "spec", "--request-changes"])
    check("AC-SPA-05b requesting changes without a comment is refused before the prompt", code == 5 and "E_VALIDATION" in out and "first 8 characters" not in out, out[-200:])
    code, out = run_tty(CLI + d + ["approve", "chg", "spec", "--request-changes", "-m", "Add the half-day case"], typed=[prefix("chg", "specification")])
    check("AC-SPA-05a requesting changes returns the run to PLANNED (R6)", code == 0 and state("chg") == "PLANNED" and aps("chg", "specification") == ["CHANGES_REQUESTED"], out[-200:])
    new_run("rej")
    submit("rej", "specifier")
    code, out = run_tty(CLI + d + ["approve", "rej", "spec", "--reject", "-m", "Out of scope"], typed=[prefix("rej", "specification")])
    check("AC-SPA-05d rejecting cancels the run (R7)", code == 0 and state("rej") == "CANCELLED" and aps("rej", "specification") == ["REJECTED"], out[-200:])

    new_run("race")
    submit("race", "specifier")
    pfx = prefix("race", "specification")
    import pty
    procs = []
    for _ in range(2):
        pid, fd = pty.fork()
        if pid == 0:
            os.execvpe(CLI[0], CLI + d + ["approve", "race", "spec"], ENV)
        procs.append((pid, fd))
    results = []
    threads = [threading.Thread(target=lambda a=a: results.append(tty_finish(a[0], a[1], typed=[pfx]))) for a in procs]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check("AC-SPA-06f two terminals approve at once: exactly one wins", sorted(c for c, _ in results) == [0, 5] and len(db_all(w, "SELECT 1 FROM events WHERE type='approval.decided' AND run_id=(SELECT id FROM runs WHERE slug='race')")) == 1, str(results)[-300:])

    new_run("tamper")
    submit("tamper", "specifier")
    pfx = prefix("tamper", "specification")
    stored = w / ".sentinel/runs/tamper/artifacts/spec-v1.md"
    stored.write_text(stored.read_text() + "x")
    code, out = run_tty(CLI + d + ["approve", "tamper", "spec"], typed=[pfx])
    check("AC-ART-01b a modified stored copy is refused with E_INTEGRITY and audited", code == 5 and "E_INTEGRITY" in out and len(db_all(w, "SELECT 1 FROM audit WHERE action='integrity_failed'")) == 1, out[-200:])
    code, out = run(CLI + d + ["review", "tamper", "spec"])
    check("AC-ART-01d review of a modified stored copy fails with E_INTEGRITY", code == 5 and "E_INTEGRITY" in out, out[-200:])

    run(CLI + d + ["run", "new", "old-run", "--tier", "2"])
    before = (w / ".sentinel/runs/old-run/state.json").read_bytes()
    code, out = run_tty(CLI + d + ["approve", "old-run", "spec"], typed=["00000000"])
    check("AC-SPA-06e a 0.1 run has no approval gates (E_TRANSITION, state.json untouched)", code == 5 and "E_TRANSITION" in out and (w / ".sentinel/runs/old-run/state.json").read_bytes() == before, out[-200:])

    new_run("fin", state="EXECUTING")
    code, out = run(CLI + d + ["run", "finish", "fin", "--outcome", "stopped"])
    check("run finish on a version 2 run without a terminal is refused with E_NOT_TTY", code == 5 and "E_NOT_TTY" in out and state("fin") == "EXECUTING", out[-200:])
    code, out = run_tty(CLI + d + ["run", "finish", "fin", "--outcome", "stopped"])
    check("run finish on a version 2 run at a terminal cancels it", code == 0 and state("fin") == "CANCELLED", out[-200:])

    code, out = run(CLI + d + ["sync-adapters"])
    settings = json.loads((w / ".claude/settings.json").read_text()) if (w / ".claude/settings.json").exists() else {}
    deny = settings.get("permissions", {}).get("deny", [])
    agent_text = "".join(p.read_text() for p in (w / ".claude/agents").glob("*.md"))
    check("AC-SEC-04a generated Claude settings deny sentinel approve and accept, and agents are told never to run them", "Bash(sentinel approve:*)" in deny and "Bash(sentinel accept:*)" in deny and "Never run `sentinel approve` or `sentinel accept`" in agent_text, out[-200:])


def phase_c_checks(tmp):
    print("task runtime (phase C)")
    w = tmp / "ws-c"
    w.mkdir()
    git_repo(w / "backend", "build.gradle")
    git_repo(w / "frontend", "next.config.ts")
    run(CLI + ["--dir", str(w), "init", "--shape", "fullstack", "--non-interactive", "--local-only"])
    d = ["--dir", str(w)]
    bin_dir = w / "bin"
    bin_dir.mkdir()

    def runner(name, body):
        path = bin_dir / name
        path.write_text(f"#!{sys.executable}\nimport json, os, re, pathlib, sys\nprompt = sys.argv[-1]\n"
                        "result = re.search(r'Result file \\(absolute path\\): (\\S+)', prompt).group(1)\n"
                        "def done(status='completed'):\n"
                        "    pathlib.Path(result).write_text(json.dumps({'schema': 'agent-result-v1', 'task_id': os.environ['SENTINEL_TASK_ID'], 'status': status, 'summary': 's'}))\n" + body)
        path.chmod(0o755)
        return str(path)

    write_config(w, lambda c: c.update({"single_model": False, "agents": {"docs": {"runner": "fake"}, "qa": {"runner": "stray"}, "reviewer": {"runner": "gone"}},
                                         "runners": {"fake": {"command": runner("fake", "pathlib.Path(os.getcwd(), 'docs').mkdir(exist_ok=True)\npathlib.Path(os.getcwd(), 'docs/leave.md').write_text('x')\ndone()\n")},
                                                     "stray": {"command": runner("stray", "pathlib.Path(os.getcwd()).parent.joinpath('frontend/stray.txt').write_text('x')\ndone()\n")},
                                                     "gone": {"command": "no-such-agent-cli"},
                                                     "inrepo": {"command": runner("inrepo", "pathlib.Path(os.getcwd(), 'build.gradle').write_text('changed')\ndone()\n")}}}))
    sys.path.insert(0, str(ROOT / "scripts"))
    from engine import Engine

    def new_run(slug):
        run(CLI + d + ["run", "new", slug])
        db_set(w, slug, state="EXECUTING", tier=3, initial_tier=3)

    def task(slug, role, write, queue=True):
        cfg = yaml.safe_load((w / "sentinel.config.yaml").read_text())
        eng = Engine(w / ".sentinel", w, cfg)
        try:
            tid = eng.create_task(slug, role, f"{role} work", ["backend"], write=write)["id"]
            if queue:
                eng.queue_task(tid)
        finally:
            eng.close()
        return tid

    def row(tid):
        return db_all(w, "SELECT * FROM tasks WHERE id=?", (tid,))[0]

    new_run("rt")
    tid = task("rt", "docs", ["backend/docs/**"])
    code, out = run(CLI + d + ["task", "run", tid])
    r = row(tid)
    check("AC-AGT-04a a headless task runs through the fake runner and completes", code == 0 and r["state"] == "COMPLETED" and r["adapter"] == "cli" and r["provider"] == "fake", out[-250:])
    stray = task("rt", "qa", [])
    code, out = run(CLI + d + ["task", "run", stray])
    r = row(stray)
    check("AC-AGT-06b a write outside the task's repo fails it with exit 3 and E_SCOPE", code == 3 and r["state"] == "FAILED" and r["error_code"] == "E_SCOPE", out[-250:])
    (w / "frontend/stray.txt").unlink(missing_ok=True)
    write_config(w, lambda c: c["agents"].update({"qa": {"runner": "inrepo"}}))
    new_run("rt-scope")
    scoped = task("rt-scope", "qa", ["backend/docs/**"])
    code, out = run(CLI + d + ["task", "run", scoped])
    kinds = [json.loads(e["payload"])["kind"] for e in db_all(w, "SELECT payload FROM events WHERE type='task.scope_violation' AND task_id=?", (scoped,))]
    check("AC-AGT-06g a write in the task's repo but outside its write globs is E_SCOPE (exit 3, outside_write_scope)", code == 3 and row(scoped)["error_code"] == "E_SCOPE" and kinds == ["outside_write_scope"], out[-250:])
    check("AC-CFG-10a shipped code profiles carry test and production globs, generic none", all(json.loads((ROOT / "profiles" / f"{n}.json").read_text()).get("test_globs") for n in ("spring-gradle", "python", "node", "nextjs", "flutter")) and "test_globs" not in json.loads((ROOT / "profiles/generic.json").read_text()))
    run(["git", "checkout", "-q", "--", "."], cwd=w / "backend")
    write_config(w, lambda c: c.update({"single_model": True}))  # the run keeps the config it starts with (CFG-08)
    new_run("rt-native")
    nat = task("rt-native", "docs", ["backend/docs/**"])
    code, out = run(CLI + d + ["task", "run", nat])
    waiting = row(nat)["state"] == "WAITING_FOR_INPUT"
    tdir = w / ".sentinel/runs/rt-native/tasks" / nat
    (w / "backend/docs").mkdir(exist_ok=True)
    (w / "backend/docs/native.md").write_text("x")
    (tdir / "result.json").write_text(json.dumps({"schema": "agent-result-v1", "task_id": nat, "status": "completed", "summary": "s"}))
    code2, out2 = run(CLI + d + ["task", "complete", nat])
    check("AC-AGT-04d and AC-AGT-04e a native task waits for the orchestrator, then task complete finishes it", waiting and code == 0 and code2 == 0 and row(nat)["state"] == "COMPLETED", out[-150:] + out2[-150:])
    code, out = run(CLI + d + ["task", "complete", nat])
    check("AC-ORC-02h a second task complete is refused with E_TRANSITION", code == 5 and "E_TRANSITION" in out, out[-200:])
    write_config(w, lambda c: c.update({"single_model": False}))
    new_run("rt-blocked")
    rev = task("rt-blocked", "reviewer", [])
    code, out = run(CLI + d + ["task", "run", rev])
    check("AC-AGT-05e a missing runner leaves the task QUEUED and blocks the run (exit 6, R21)", code == 6 and row(rev)["state"] == "QUEUED" and db_row(w, "rt-blocked")["state"] == "BLOCKED" and "install no-such-agent-cli" in out, out[-250:])
    code, out = run(CLI + d + ["next", "rt-blocked", "--json"])
    check("AC-ARC-03a next on a blocked run is a human step with exit 6", code == 6 and json.loads(out)["kind"] == "human", out[-200:])
    for args, want, name in ((["next", "../x"], "E_VALIDATION", "next with a bad slug"), (["task", "run", "t-000000000000"], "E_NOT_FOUND", "task run with an unknown id"), (["task", "complete", "t-zzzz"], "E_VALIDATION", "task complete with a bad id")):
        code, out = run(CLI + d + args)
        check(f"AC-ARC-03h {name} is refused with {want}", code == 5 and want in out, out[-200:])
    code, out = run(CLI + d + ["stage", "run", "--slug", "rt", "--stage", "coder", "--repo", "backend", "--runner", "fake"])
    check("AC-ORC-08g stage run is refused on a version 2 run and names task run", code == 5 and "sentinel task run" in out, out[-200:])
    code, out = run(CLI + d + ["submit", "rt", "--role", "specifier"])
    check("the Phase B submit command is gone", code == 2, out[-200:])


def phase_d_checks(tmp):
    print("TDD engine (phase D part 2a)")
    w = tmp / "ws-d"
    w.mkdir()
    git_repo(w / "backend", "build.gradle")
    (w / "backend/.gitignore").write_text("build/\n")
    run(["git", "add", "."], cwd=w / "backend")
    run(["git", "commit", "-q", "-m", "ignore"], cwd=w / "backend")
    run(CLI + ["--dir", str(w), "init", "--shape", "fullstack", "--non-interactive", "--local-only"])
    d = ["--dir", str(w)]
    bin_dir = w / "bin"
    bin_dir.mkdir()
    tool = bin_dir / "faketest"
    tool.write_text(f"""#!{sys.executable}
import json, os, pathlib, sys
here = pathlib.Path(__file__).resolve().parent
sc = json.loads((here / "faketest.json").read_text()).get(sys.argv[1], {{}})
print(sc.get("stdout", ""))
if sc.get("report") is not None:
    out = pathlib.Path("build/test-results/test")
    out.mkdir(parents=True, exist_ok=True)
    cases = "".join('<testcase classname="x.%s" name="%s">%s</testcase>' % (c, n, '<failure message="m"/>' if st == "failure" else "") for c, n, st in sc["report"])
    (out / "TEST-fake.xml").write_text("<testsuite>" + cases + "</testsuite>")
sys.exit(sc.get("exit", 0))
""")
    tool.chmod(0o755)

    def tool_says(**modes):
        (bin_dir / "faketest.json").write_text(json.dumps(modes))
    agent = bin_dir / "redagent"
    agent.write_text(f"""#!{sys.executable}
import json, os, pathlib, re, sys
prompt = sys.argv[-1]
result = re.search(r'Result file \\(absolute path\\): (\\S+)', prompt).group(1)
keys = re.findall(r'^- `(features/[^`]+)`$', prompt, re.M)
body = "class LeaveTest {{\\n" + "".join('  @Scenario("%s")\\n  void t%d() {{}}\\n' % (k, i) for i, k in enumerate(keys)) + "}}\\n"
p = pathlib.Path(os.getcwd(), "src/test/java/LeaveTest.java")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(body)
pathlib.Path(result).write_text(json.dumps({{"schema": "agent-result-v1", "task_id": os.environ["SENTINEL_TASK_ID"], "status": "completed", "summary": "s"}}))
""")
    agent.chmod(0o755)
    prod_agent = bin_dir / "prodagent"
    prod_agent.write_text(f"""#!{sys.executable}
import json, os, pathlib, re, sys
prompt = sys.argv[-1]
result = re.search(r'Result file \\(absolute path\\): (\\S+)', prompt).group(1)
p = pathlib.Path(os.getcwd(), "src/main/java/LeaveBalance.java")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text((p.read_text() if p.exists() else "") + "class LeaveBalance {{}}\\n")
pathlib.Path(result).write_text(json.dumps({{"schema": "agent-result-v1", "task_id": os.environ["SENTINEL_TASK_ID"], "status": "completed", "summary": "s"}}))
""")
    prod_agent.chmod(0o755)
    py = sys.executable

    def configure():
        def mutate(c):
            c["repos"] = [r for r in c["repos"] if r["id"] == "backend"]
            for repo in c["repos"]:
                if repo["id"] == "backend":
                    repo.update({"profile": "generic", "test_globs": ["src/test/**"], "production_globs": ["src/main/**"],
                                 "commands": {"test": f"{py} {tool} full"}, "targeted_test": f"{py} {tool} targeted {{tests}}",
                                 "test_report": {"kind": "junit-xml", "path": "build/test-results/test/*.xml"},
                                 "scenario_ref": '@Scenario\\("([^"]+)"\\)', "failure_patterns": {"compile": ["error: cannot find symbol"]}})
            c.update({"single_model": False, "runners": {"red": {"command": str(agent)}, "prod": {"command": str(prod_agent)}},
                      "agents": {"tdd_red": {"runner": "red"}, "tdd_green": {"runner": "prod"}, "tdd_refactor": {"runner": "prod"}}})
        write_config(w, mutate)
    configure()
    sys.path.insert(0, str(ROOT / "scripts"))
    from engine import Engine

    def new_run(slug):
        run(CLI + d + ["run", "new", slug])
        db_set(w, slug, state="PLANNED", tier=1, initial_tier=1)
        sd = w / ".sentinel/shared/specs" / slug
        (sd / "features").mkdir(parents=True, exist_ok=True)
        (sd / "spec.md").write_text(lite_spec(slug))
        cfg = yaml.safe_load((w / "sentinel.config.yaml").read_text())
        eng = Engine(w / ".sentinel", w, cfg)
        try:
            def submit(role, feats=None):
                for n, t in (feats or {}).items():
                    (sd / "features" / n).write_text(t)
                tid = eng.create_task(slug, role, f"{role} work", ["backend"], queue=True)["id"]
                eng.start_task(tid, schedule=False)
                (w / ".sentinel/runs" / slug / "tasks" / tid / "result.json").write_text(json.dumps(
                    {"schema": "agent-result-v1", "task_id": tid, "status": "completed", "summary": "done"}))
                return eng.finish_task(tid)["completion"]

            def approve(gate):
                info = eng.pending_approval(slug, gate)
                eng.decide(slug, gate, "approve", "human", prefix=info["sha256"][:8], approver="dev")
            assert submit("specifier")["accepted"]
            approve("spec")
            assert submit("test_designer", FEATURES)["accepted"]
            approve("gherkin")
            eng.advance(slug)
        finally:
            eng.close()

    def rows(sql, args=()):
        return db_all(w, sql, args)

    def cycles(slug):
        return rows("SELECT behavior, state, reason, repo_id FROM cycles WHERE run_id=(SELECT id FROM runs WHERE slug=?) ORDER BY ordinal", (slug,))

    new_run("tdd")
    cs = cycles("tdd")
    check("AC-TDD-01a R12 plans one PLANNED cycle per behavior group, one cycle.planned event each", [c["state"] for c in cs] == ["PLANNED", "PLANNED"] and [c["behavior"] for c in cs] == ["features/balance.feature", "features/form.feature"] and len(rows("SELECT 1 FROM events WHERE type='cycle.planned'")) == 2, str(cs))
    code, out = run(CLI + d + ["next", "tdd", "--json"])
    step = json.loads(out)
    check("AC-TDD-01e next creates the Red task of the first cycle and queues it; the second cycle's Red waits for it", step.get("role") == "tdd_red" and [r["state"] for r in rows("SELECT state FROM tasks WHERE role='tdd_red' ORDER BY rowid")] == ["QUEUED", "CREATED"], out[-250:])
    check("AC-AGT-01a the TDD stage templates exist with their write class", all((ROOT / "core/stages" / f"{n}.md").read_text().split("---\n")[1].count(f"writes: {k}") == 1 for n, k in (("tdd_red", "tests"), ("tdd_green", "production"), ("tdd_refactor", "production"), ("test_designer", "gherkin"))))
    tool_says(full={"exit": 0, "report": []}, targeted={"exit": 1, "stdout": "error: cannot find symbol", "report": None})
    code, out = run(CLI + d + ["task", "run", step["task"]])
    ev = rows("SELECT kind, classification, verdict FROM evidence ORDER BY rowid")
    check("AC-TDD-03a the baseline is stored once, before the first Red starts", [e["kind"] for e in ev][:1] == ["baseline"] and ev[0]["classification"] == "pass", str(ev))
    check("AC-TDD-03d a compile error is classified by the engine, Red goes back to PLANNED with a retry (exit 1)", code == 1 and ev[-1]["classification"] == "compile" and cycles("tdd")[0]["state"] == "PLANNED" and len(rows("SELECT 1 FROM tasks WHERE role='tdd_red'")) == 3, out[-250:])
    retry = rows("SELECT id FROM tasks WHERE role='tdd_red' AND retry_of IS NOT NULL")[0]["id"]
    tool_says(full={"exit": 0, "report": []}, targeted={"exit": 1, "report": [["LeaveTest", "t0", "failure"]]})
    code, out = run(CLI + d + ["task", "run", retry])
    cyc = rows("SELECT * FROM cycles WHERE behavior='features/balance.feature'")[0]
    check("AC-TDD-03c Red produces the expected assertion failure: exit 0, RED_VERIFIED, approved test file with sha256, Green task queued", code == 0 and cyc["state"] == "RED_VERIFIED" and json.loads(cyc["approved_tests"])[0]["path"] == "backend/src/test/java/LeaveTest.java" and [t["state"] for t in rows("SELECT state FROM tasks WHERE role='tdd_green'")] == ["QUEUED"], out[-250:])
    check("AC-TDD-02a the scenario to test and cycle to test_file trace links are stored", rows("SELECT to_id FROM trace_links WHERE from_kind='scenario' AND to_kind='test'") == [{"to_id": "LeaveTest.t0"}] and rows("SELECT to_id FROM trace_links WHERE from_kind='cycle' AND to_kind='test_file'") == [{"to_id": "backend/src/test/java/LeaveTest.java"}])
    green = rows("SELECT id FROM tasks WHERE role='tdd_green'")[0]["id"]
    tool_says(full={"exit": 0, "report": []}, targeted={"exit": 0, "report": [["LeaveTest", "t0", "pass"]]})
    code, out = run(CLI + d + ["task", "run", green])
    cyc = rows("SELECT * FROM cycles WHERE behavior='features/balance.feature'")[0]
    check("AC-TDD-04a Green is verified by the engine's own run: exit 0, GREEN_VERIFIED, green evidence, Refactor task queued", code == 0 and cyc["state"] == "GREEN_VERIFIED" and rows("SELECT verdict FROM evidence WHERE kind='green'") == [{"verdict": "accepted"}] and [t["state"] for t in rows("SELECT state FROM tasks WHERE role='tdd_refactor'")] == ["QUEUED"], out[-250:])
    code, out = run(CLI + d + ["task", "run", rows("SELECT id FROM tasks WHERE role='tdd_refactor'")[0]["id"]])
    cyc = rows("SELECT * FROM cycles WHERE behavior='features/balance.feature'")[0]
    check("AC-TDD-05a a refactor that keeps the tests green is accepted: REFACTOR_VERIFIED to CYCLE_ACCEPTED with full evidence", code == 0 and cyc["state"] == "CYCLE_ACCEPTED" and cyc["accepted_at"] and len(rows("SELECT 1 FROM trace_links WHERE from_kind='cycle' AND to_kind='evidence'")) == 3, out[-250:])
    check("AC-TRC-01a the chain links the AC to its scenario key and the cycle to its production file", rows("SELECT 1 FROM trace_links WHERE from_kind='ac' AND to_kind='scenario' AND to_id LIKE '% :: %'") != [] and rows("SELECT to_id FROM trace_links WHERE from_kind='cycle' AND to_kind='file'") == [{"to_id": "backend/src/main/java/LeaveBalance.java"}])
    check("AC-TDD-06a Red evidence holds the targeted command, exit code, output file and its sha256", all(rows("SELECT command, exit_code, output_sha256, repo_sha FROM evidence WHERE kind='red' AND verdict='accepted'")[0].values()))

def phase_e_checks(tmp):
    print("verification, acceptance, reports, export and import (phase E)")
    w = tmp / "ws-e"
    w.mkdir()
    git_repo(w / "backend", "build.gradle")
    git_repo(w / "frontend", "next.config.ts")
    run(CLI + ["--dir", str(w), "init", "--shape", "fullstack", "--non-interactive", "--local-only"])
    d = ["--dir", str(w)]
    run(CLI + d + ["run", "new", "old-fix", "--tier", "2"])

    def refused(args, code, text, env=None):
        r = subprocess.run(CLI + d + args, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env or ENV)
        return r.returncode == code and text in r.stdout + r.stderr, (r.stdout + r.stderr)[-200:]
    ok, why = refused(["verify", "old-fix"], 5, "release-check")
    check("AC-VER-01n verify on a 0.1 run points to the release check", ok, why)
    ok, why = refused(["report", "old-fix"], 5, "E_TRANSITION")
    check("AC-ART-01i report is refused for a 0.1 run", ok, why)
    ok, why = refused(["report", "no-such-run"], 5, "E_NOT_FOUND")
    check("AC-ART-01i report of an unknown run is E_NOT_FOUND", ok, why)
    ok, why = refused(["accept", "old-fix"], 5, "E_NOT_TTY")
    check("AC-VER-04d accept without a terminal is refused (E_NOT_TTY)", ok, why)
    ok, why = refused(["accept", "old-fix"], 5, "E_ACTOR", {**ENV, "SENTINEL_TASK_ID": "t-000000000000"})
    check("AC-VER-04d accept inside a task process is refused (E_ACTOR)", ok, why)
    ok, why = refused(["run", "export", "old-fix", "--yes"], 5, "E_NOT_TTY")
    check("AC-ART-03g export without a terminal is refused (E_NOT_TTY)", ok, why)
    ok, why = refused(["resolve", "old-fix", "-m", "x"], 5, "E_NOT_TTY")
    check("resolve without a terminal is refused (E_NOT_TTY)", ok, why)
    write_config(w, lambda c: c.update({"verification": {"disabled": ["test"], "mutation": "sometimes"}}))
    code, out = run(CLI + d + ["doctor"])
    check("AC-CFG-11e config that disables the test check or sets a bad mutation value is invalid",
          code == 1 and "verification.disabled" in out and "verification.mutation" in out, out[-200:])
    settings = json.loads((w / ".claude/settings.json").read_text()) if (w / ".claude/settings.json").exists() else {}
    run(CLI + d + ["sync-adapters"])
    deny = json.loads((w / ".claude/settings.json").read_text())["permissions"]["deny"]
    check("AC-SEC-04b sync-adapters denies the accept command", "Bash(sentinel accept:*)" in deny and "Bash(sentinel --dir * accept *)" in deny, str(deny))


def phase_f_checks(tmp):
    print("local api server (phase F)")
    import http.client
    import pty
    import re
    import select
    import signal
    import stat
    home = tmp / "home-f"
    home.mkdir()
    w = tmp / "ws-f"
    w.mkdir()
    git_repo(w / "backend", "build.gradle")
    git_repo(w / "frontend", "next.config.ts")
    run(CLI + ["--dir", str(w), "init", "--shape", "fullstack", "--non-interactive", "--local-only"])
    env = {k: v for k, v in ENV.items() if k not in ("XDG_CONFIG_HOME", "SENTINEL_TASK_ID")}
    env.update({"HOME": str(home), "USER": "dev", "LOGNAME": "dev"})
    cfg = home / ".config" / "sentinel"
    base = CLI + ["--dir", str(w)]
    r = subprocess.run(base + ["dashboard", "--no-open"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env)
    check("AC-SEC-02c dashboard without a terminal is refused with E_NOT_TTY and prints no token", r.returncode == 5 and "E_NOT_TTY" in r.stdout + r.stderr and "auth?t=" not in r.stdout + r.stderr, r.stderr[-200:])
    r = subprocess.run(base + ["dashboard", "--no-open"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env={**env, "SENTINEL_TASK_ID": "t-abc123"})
    check("AC-SEC-02b a task process cannot start the server (E_ACTOR)", r.returncode == 5 and "E_ACTOR" in r.stdout + r.stderr, r.stderr[-200:])
    r = subprocess.run(base + ["dashboard", "--host", "0.0.0.0"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env)
    check("AC-SEC-01c no option chooses another bind address", r.returncode == 2 and not cfg.exists(), r.stderr[-200:])

    def tty_proc(args):
        master, slave = pty.openpty()
        proc = subprocess.Popen(CLI + args, stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True)
        os.close(slave)
        return proc, master

    def read_until(proc, fd, pattern, timeout=20):
        out = b""
        end = time.time() + timeout
        while time.time() < end:
            if re.search(pattern, out.decode(errors="replace")):
                break
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                out += data
            elif proc.poll() is not None:
                break
        return out.decode(errors="replace").replace("\r\n", "\n")

    proc, fd = tty_proc(["--dir", str(w), "dashboard", "--no-open"])
    try:
        out = read_until(proc, fd, r"auth\?t=[0-9a-f]{64}")
        m = re.search(r"http://127\.0\.0\.1:(\d+)/auth\?t=([0-9a-f]{64})", out)
        check("AC-SEC-01a dashboard starts at a terminal and prints the auth URL", bool(m), out[-200:])
        port, token = int(m.group(1)), m.group(2)
        sj = cfg / "server.json"
        check("AC-SEC-02e server.json is 0600 in a 0700 folder and holds the printed token", stat.S_IMODE(sj.stat().st_mode) == 0o600 and stat.S_IMODE(cfg.stat().st_mode) == 0o700 and json.loads(sj.read_text())["token"] == token)

        def call(method, path, body=None, cookie=None, csrf=None, host=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", host or f"127.0.0.1:{port}")
            if cookie:
                conn.putheader("Cookie", f"sentinel_session={cookie}")
            if csrf:
                conn.putheader("X-Sentinel-CSRF", csrf)
            data = json.dumps(body).encode() if body is not None else None
            if data is not None:
                conn.putheader("Content-Type", "application/json")
                conn.putheader("Content-Length", str(len(data)))
            conn.endheaders(data)
            resp = conn.getresponse()
            payload = resp.read()
            headers = dict(resp.getheaders())
            conn.close()
            return resp.status, headers, payload

        status, headers, _ = call("GET", f"/auth?t={token}")
        cookie = headers["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
        check("AC-SEC-01p the token is exchanged for an HttpOnly SameSite=Strict cookie", status == 302 and "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"], str(headers))
        status, _, payload = call("GET", "/api/v1/runtime", cookie=cookie)
        runtime = json.loads(payload)
        check("AC-SEC-01a the runtime endpoint names the pid, port and project", status == 200 and runtime["port"] == port and [p["id"] for p in runtime["projects"]] == ["ws-f"] and runtime["user"]["role"] == "admin", payload[:200])
        check("AC-SEC-01s an API route without the cookie answers 401", call("GET", "/api/v1/projects")[0] == 401)
        check("AC-SEC-01l a foreign Host header answers 403", call("GET", "/api/v1/projects", cookie=cookie, host=f"attacker.example:{port}")[0] == 403)
        csrf = json.loads(call("GET", "/api/v1/session", cookie=cookie)[2])["csrf"]
        check("AC-SEC-01u a POST without the CSRF header answers 403", call("POST", "/api/v1/projects/ws-f/tasks", {"slug": "api-run", "request": "x", "type": "feature"}, cookie=cookie)[0] == 403)
        status, _, payload = call("POST", "/api/v1/projects/ws-f/tasks", {"slug": "api-run", "request": "Show the balance", "type": "feature", "repos": ["backend"]}, cookie=cookie, csrf=csrf)
        check("AC-TSK-01a a run created through the API starts CREATED with version 2", status == 201 and json.loads(payload)["state"] == "CREATED" and json.loads(payload)["workflow_version"] == "2", payload[:200].decode())
        status, _, payload = call("GET", "/api/v1/tasks/api-run/next", cookie=cookie)
        step = json.loads(payload)
        code, out = run(CLI + ["--dir", str(w), "next", "api-run", "--json"])
        check("AC-TSK-03b the new run waits for the AI tool and the CLI sees the same run", step.get("label") == "waiting for AI tool" and step["resume_command"] == "/sentinel resume api-run" and json.loads(out)["kind"] == "orchestrator", payload[:200].decode() + out[-100:])
        status, _, payload = call("POST", "/api/v1/tasks/api-run/control", {"action": "cancel", "comment": "selftest"}, cookie=cookie, csrf=csrf)
        row = db_row(w, "api-run")
        check("AC-MON-02a a dashboard cancel moves the run to CANCELLED and is audited with channel dashboard", status == 200 and row["state"] == "CANCELLED" and db_all(w, "SELECT 1 FROM audit WHERE channel='dashboard' AND action='cancel' AND target='api-run'"), payload[:200])
        proc2, fd2 = tty_proc(["--dir", str(w), "dashboard", "--no-open"])
        out2 = read_until(proc2, fd2, r"auth\?t=[0-9a-f]{64}")
        proc2.wait(timeout=20)
        os.close(fd2)
        check("AC-SEC-01e a second call attaches to the running server and exits 0", proc2.returncode == 0 and f"http://127.0.0.1:{port}/auth?t={token}" in out2, out2[-200:])
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
        check("AC-SEC-01i stopping the server exits 0 and removes server.json", proc.returncode == 0 and not sj.exists())
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(fd)
    code, out = run(CLI + ["--dir", str(w), "next", "api-run", "--json"])
    check("AC-TST-01g CLI commands work after the server stopped", code == 0)


USAGE = """usage: sentinel selftest

Builds a throwaway workspace and runs the engine, CLI and server checks against it (about a minute).
It takes no options and changes nothing outside a temporary folder; the exit code is 1 if any check fails.
"""


def main():
    # --help must print this, not start 200+ checks (the docs test asks every documented command for --help)
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(USAGE, end="")
        return
    tmp = Path(tempfile.mkdtemp(prefix="sentinel-selftest-"))
    try:
        ws = tmp / "ws"
        ws.mkdir()
        git_repo(ws / "backend", "build.gradle")
        git_repo(ws / "frontend", "next.config.ts")
        remote = tmp / "shared.git"
        run(["git", "init", "-q", "--bare", "-b", "main", str(remote)])
        seed = tmp / "seed"
        run(["git", "clone", "-q", str(remote), str(seed)])
        (seed / "README.md").write_text("shared\n")
        run(["git", "add", "."], cwd=seed)
        run(["git", "commit", "-q", "-m", "init"], cwd=seed)
        run(["git", "push", "-q", "origin", "main"], cwd=seed)

        print("init and config")
        code, out = run(CLI + ["--dir", str(ws), "init", "--shape", "fullstack", "--non-interactive", "--shared-repo", str(remote)])
        check("init writes sentinel.config.yaml", code == 0 and (ws / "sentinel.config.yaml").exists(), out[-200:])
        config = yaml.safe_load((ws / "sentinel.config.yaml").read_text())
        profiles = [r["profile"] for r in config["repos"]]
        check("init detects stack profiles", profiles == ["spring-gradle", "nextjs"], str(profiles))
        try:
            import jsonschema
            jsonschema.validate(config, json.loads((ROOT / "core/schema/config.schema.json").read_text()))
            check("config validates against the schema", True)
        except ImportError:
            check("config validates against the schema (skipped, jsonschema not installed)", True)
        write_config(ws, lambda c: c["state"].update({"shared_repo": str(remote)}))
        code, out = run(CLI + ["--dir", str(ws), "doctor"])
        problems = [l for l in out.splitlines() if l.startswith("- ") and "runner CLI not installed" not in l and "command not found" not in l]
        check("doctor reports no config problems", not problems, "; ".join(problems))

        print("local-only shared mode")
        ws3 = tmp / "ws3"
        ws3.mkdir()
        git_repo(ws3 / "backend", "build.gradle")
        git_repo(ws3 / "frontend", "next.config.ts")
        code, out = run(CLI + ["--dir", str(ws3), "init", "--shape", "fullstack", "--non-interactive", "--local-only"])
        cfg3 = yaml.safe_load((ws3 / "sentinel.config.yaml").read_text()) if code == 0 else {}
        check("init --local-only needs no shared repo", code == 0 and cfg3["state"].get("shared_mode") == "local" and "shared_repo" not in cfg3["state"], out[-200:])
        check("local-only creates the shared folder without git", (ws3 / ".sentinel/shared/invariants.md").exists() and not (ws3 / ".sentinel/shared/.git").exists())
        code, out = run(CLI + ["--dir", str(ws3), "run", "new", "localdemo", "--tier", "2"])
        check("local-only run new takes a file lock", code == 0 and (ws3 / ".sentinel/shared/locks/localdemo").exists(), out[-200:])
        run(CLI + ["--dir", str(ws3), "run", "finish", "localdemo"])
        code, out = run(CLI + ["--dir", str(ws3), "sync", "push", "localdemo", "--yes"])
        check("local-only sync push is a no-op that still scrubs", code == 0 and "local-only" in out, out[-200:])
        code, out = run(CLI + ["--dir", str(ws3), "doctor"])
        check("local-only doctor does not ask for a shared repo", "shared repo" not in out, out[-200:])
        code, out = run(CLI + ["--dir", str(ws3), "shared", "set", str(remote)])
        cfg3 = yaml.safe_load((ws3 / "sentinel.config.yaml").read_text())
        check("shared set switches a local-only workspace to git mode", cfg3["state"].get("shared_mode") == "git" and cfg3["state"].get("shared_repo") == str(remote), out[-200:])

        print("shared repo is required")
        bare = tmp / "no-shared"
        bare.mkdir()
        git_repo(bare / "app", "package.json")
        code, out = run(CLI + ["--dir", str(bare), "init", "--shape", "single", "--non-interactive"])
        check("init refuses to run without a shared repo", code != 0 and "shared repo is required" in out and not (bare / "sentinel.config.yaml").exists(), out[-160:])
        code, out = run(CLI + ["--dir", str(bare), "init", "--shape", "single", "--non-interactive", "--shared-repo", "not a url"])
        check("init rejects a value that is not a git URL", code != 0 and not (bare / "sentinel.config.yaml").exists(), out[-160:])
        empty = tmp / "empty.git"
        run(["git", "init", "-q", "--bare", "-b", "main", str(empty)])
        ews = tmp / "ws-empty"
        ews.mkdir()
        git_repo(ews / "app", "package.json")
        code, out = run(CLI + ["--dir", str(ews), "init", "--shape", "single", "--non-interactive", "--shared-repo", str(empty)])
        shared_dir = ews / ".sentinel/shared"
        committed = run(["git", "log", "--oneline"], cwd=shared_dir)[1].strip() if shared_dir.exists() else ""
        check("an empty shared repo is scaffolded with starter files", code == 0 and (shared_dir / "invariants.md").exists() and (shared_dir / "specs/index.json").exists() and bool(committed), out[-200:])
        check("the scaffold is not pushed without being asked", run(["git", "ls-remote", str(empty)])[1].strip() == "")
        check("the scaffold contains no workflow file (pushing one needs extra token scope)", not (shared_dir / ".github").exists())
        code, out = run(CLI + ["--dir", str(ews), "shared", "ci"])
        check("shared ci writes the optional workflow", code == 0 and (shared_dir / ".github/workflows/sentinel-shared.yml").exists() and "sentinel shared-check" in (shared_dir / ".github/workflows/sentinel-shared.yml").read_text(), out[-160:])
        uws = tmp / "ws-unreachable"
        uws.mkdir()
        git_repo(uws / "app", "package.json")
        code, out = run(CLI + ["--dir", str(uws), "init", "--shape", "single", "--non-interactive", "--shared-repo", str(tmp / "missing.git")])
        check("init still saves the config when the shared repo is unreachable, with a warning", code == 0 and "could not reach" in out and (uws / "sentinel.config.yaml").exists(), out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "doctor"])
        check("doctor fails until the shared repo is cloned", code != 0 and "not cloned" in out, out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "run", "new", "blocked", "--tier", "2"])
        check("run new refuses until the shared repo is cloned", code != 0 and "sync pull" in out, out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "run", "new", "solo", "--adhoc"])
        check("an adhoc run needs no shared repo and no tier", code == 0 and (uws / ".sentinel/runs/solo/state.json").exists(), out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "stage", "render", "--stage", "reviewer", "--slug", "solo"])
        check("stage render fills in the run slug", code == 0 and ".sentinel/runs/solo" in out and "<slug>" not in out, out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "run", "finish", "solo", "--outcome", "passed"])
        check("finishing an adhoc run releases no lock", code == 0 and "lock released" not in out, out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "shared", "set", str(remote)])
        check("shared set connects the workspace", code == 0 and (uws / ".sentinel/shared/.git").exists(), out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "run", "new", "unblocked", "--tier", "2"])
        check("run new works once the shared repo is cloned", code == 0, out[-200:])
        cfg_path = uws / "sentinel.config.yaml"
        cfg_text = cfg_path.read_text()
        check("the default config turns auto sync push off", "auto_sync_push: false" in cfg_text)
        code, out = run(CLI + ["--dir", str(uws), "sync", "push", "unblocked", "--auto"])
        check("sync push --auto does nothing when auto_sync_push is off", code == 0 and "auto_sync_push is off" in out, out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "sync", "push", "unblocked"])
        check("sync push without --yes or --auto is refused", code != 0 and "--auto" in out, out[-200:])
        cfg_path.write_text(cfg_text)
        run(CLI + ["--dir", str(uws), "run", "finish", "unblocked"])

        phase_a_checks(tmp, remote)
        phase_b_checks(tmp)
        phase_c_checks(tmp)
        phase_d_checks(tmp)
        phase_f_checks(tmp)
        phase_g_checks(tmp)
        phase_h_b_checks(tmp)
        phase_e_checks(tmp)
        phase_h_a_checks(tmp)
        phase_j_checks(tmp)

        print("skills")
        sys.path.insert(0, str(ROOT / "scripts"))
        from paths import skills_dir
        skill_folders = sorted(p for p in skills_dir().iterdir() if p.is_dir())
        names = [p.name for p in skill_folders]
        check("the expected skills exist", {"sentinel", "sentinel-setup", "sentinel-resume", "sentinel-status", "sentinel-sync", "sentinel-change-map", "sentinel-repro", "sentinel-spec", "sentinel-code", "sentinel-clean", "sentinel-harden", "sentinel-review", "sentinel-qa", "sentinel-promote", "sentinel-docs", "sentinel-rollout", "sentinel-retro", "sentinel-release-check"} <= set(names), ", ".join(names))
        frontmatter_bad, path_bad, tool_bad, command_bad = [], [], [], []
        seen = set()
        for folder in skill_folders:
            text = (folder / "SKILL.md").read_text()
            m = re.match(r"---\nname: (\S+)\ndescription: (.+)\n---\n", text)
            if not m or m.group(1) != folder.name or ": " in m.group(2):
                frontmatter_bad.append(folder.name)
            if "/home/" in text or "Desktop/" in text or "{{" in text:
                path_bad.append(folder.name)
            if any(word in text for word in ("AskUserQuestion", "SendMessage", "subagent_type", "headroom")):
                tool_bad.append(folder.name)
            for first, second in re.findall(r"`sentinel ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?", text):
                key = (first, second if first in ("run", "sync", "spec", "metrics", "shared", "stage", "change-map") else "")
                if key in seen:
                    continue
                seen.add(key)
                args = [key[0]] + ([key[1]] if key[1] else []) + ["--help"]
                code, out = run(CLI + ["--dir", str(ws)] + args)
                if code != 0:
                    command_bad.append(" ".join(args))
        check("every skill has valid frontmatter (name matches the folder, description present)", not frontmatter_bad, ", ".join(frontmatter_bad))
        check("no skill contains a machine path or an unrendered placeholder", not path_bad, ", ".join(path_bad))
        check("no skill depends on one tool's private mechanics", not tool_bad, ", ".join(tool_bad))
        check("every sentinel command a skill mentions exists", not command_bad, "; ".join(command_bad))
        standalone_bad = []
        for stage_file in sorted((ROOT / "core" / "stages").glob("*.md")):
            stage_name = stage_file.stem
            if (yaml.safe_load(stage_file.read_text().split("---\n")[1]) or {}).get("writes") in ("tests", "production", "gherkin", "qa_scripts"):
                continue  # Phase D roles are driven by the engine, they have no standalone skill
            owners = [n for n in names if n != "sentinel" and f"--stage {stage_name}" in (skills_dir() / n / "SKILL.md").read_text()]
            if len(owners) != 1:
                standalone_bad.append(f"{stage_name}:{owners}")
        check("every stage has exactly one standalone skill", not standalone_bad, ", ".join(standalone_bad))
        iso_bad = [n for n in names if (skills_dir() / n / "SKILL.md").read_text().count("--adhoc") and not all(w in (skills_dir() / n / "SKILL.md").read_text() for w in ("invoke_subagent", "sentinel stage run", "--session"))]
        check("standalone stage skills carry the isolation rule", not iso_bad, ", ".join(iso_bad))
        check("the pipeline contract ships with the main skill", (skills_dir() / "sentinel" / "pipeline.md").exists())
        main_skill = (skills_dir() / "sentinel" / "SKILL.md").read_text()
        check("the main skill makes isolated stages the rule and names how each tool does it", all(w in main_skill for w in ("invoke_subagent", "Agent tool", "sentinel stage run", "--runner", "--session S=subagent", "Inline, only if neither exists")), "")
        from run_stage import DEFAULT_RUNNERS
        check("the built-in agy runner can edit headlessly without the dangerous flag", "accept-edits" in DEFAULT_RUNNERS["agy"]["args"] and not DEFAULT_RUNNERS["agy"].get("unsafe_skip_permissions"), str(DEFAULT_RUNNERS["agy"]))
        code, out = run(CLI + ["--dir", str(ws), "doctor"])
        check("a config without routing or runners passes doctor", "runner" not in out or code == 0, out[-200:])

        print("prompts and adapters")
        shapes = {"single": 1, "fullstack": 2, "fullstack-mobile": 3}
        for shape, count in shapes.items():
            sws = tmp / f"shape-{shape}"
            sws.mkdir()
            for i in range(count):
                git_repo(sws / f"r{i}", "package.json")
            sets = []
            ids = {"single": ["app"], "fullstack": ["backend", "frontend"], "fullstack-mobile": ["backend", "frontend", "mobile"]}[shape]
            for i, rid in enumerate(ids):
                sets += ["--set", f"{rid}.path=./r{i}"]
            run(CLI + ["--dir", str(sws), "init", "--shape", shape, "--non-interactive", "--shared-repo", str(remote)] + sets)
            bad = []
            for stage in (ROOT / "core" / "stages").glob("*.md"):
                meta = yaml.safe_load(stage.read_text().split("---\n")[1])
                repos = ids if meta.get("per_repo") else [None]
                for rid in repos:
                    cmd = CLI + ["--dir", str(sws), "stage", "render", "--stage", stage.stem]
                    if rid:
                        cmd += ["--repo", rid]
                    c, o = run(cmd)
                    if c != 0 or "{{" in o:
                        bad.append(f"{stage.stem}/{rid}")
            check(f"all stage prompts render for shape {shape}", not bad, ", ".join(bad[:4]))
        for tool in ("claude", "agents", "gemini", "cursor"):
            code, out = run(CLI + ["--dir", str(ws), "sync-adapters", "--tool", tool])
            check(f"sync-adapters --tool {tool}", code == 0, out[-200:])
        agents = list((ws / ".claude" / "agents").glob("*.md"))
        ok = bool(agents) and all(re.match(r"---\nname: \S+\ndescription: .+\ntools: .+\nmodel: \S+\n---\n", a.read_text()) for a in agents)
        check("generated Claude agents have valid frontmatter", ok, f"{len(agents)} agents")
        skill = (ws / ".claude/skills/sentinel/SKILL.md").read_text()
        check("generated skill has no machine path or unrendered placeholder", "/home/" not in skill and "{{" not in skill and (ws / ".claude/skills/sentinel/pipeline.md").exists())
        check("generated skill uses the sentinel command, not file paths", "sentinel stage run" in skill and "sentinel release-check" in skill and ".py" not in skill)
        code, out = run(CLI + ["--version"])
        check("--version prints the packaged version", code == 0 and out.strip() == (ROOT / "VERSION").read_text().strip(), out.strip())
        before = (ws / "AGENTS.md").read_text()
        run(CLI + ["--dir", str(ws), "sync-adapters", "--tool", "agents"])
        check("AGENTS.md block is idempotent", (ws / "AGENTS.md").read_text() == before)
        check("AGENTS.md block does not depend on a checkout path", "SENTINEL_HOME" not in before and "sentinel stage run" in before)

        print("runs, locks and shared repo")
        code, out = run(CLI + ["--dir", str(ws), "sync", "pull"])
        check("sync pull clones the shared repo", code == 0 and (ws / ".sentinel/shared/.git").exists(), out[-200:])
        code, _ = run(CLI + ["--dir", str(ws), "run", "new", "demo", "--tier", "2"])
        check("run new takes a lock", code == 0)
        code, out = run(CLI + ["--dir", str(ws), "run", "new", "demo", "--tier", "2"])
        check("a second run with the same slug is refused", code != 0)
        run(CLI + ["--dir", str(ws), "run", "update", "demo", "--stage", "repro"])
        code, out = run(CLI + ["--dir", str(ws), "resume", "demo"])
        check("resume points at the next stage", code == 0 and json.loads(out)["next"] == "coder", out[-150:])
        code, out = run(CLI + ["--dir", str(ws), "run", "update", "demo", "--tier", "1"])
        check("a tier can only be raised", code != 0)
        run(CLI + ["--dir", str(ws), "run", "update", "demo", "--session", "reviewer=inline"])
        run(CLI + ["--dir", str(ws), "run", "update", "demo", "--session", "coder=subagent"])
        code, out = run(CLI + ["--dir", str(ws), "stats"])
        try:
            isolation = json.loads(out)["stage_isolation"]
        except Exception:
            isolation = {}
        check("stats shows how many stages ran inline, headless or as subagents", code == 0 and isolation.get("inline") == 1 and isolation.get("subagent") == 1, str(isolation))
        ws2 = tmp / "ws2"
        ws2.mkdir()
        git_repo(ws2 / "backend", "build.gradle")
        git_repo(ws2 / "frontend", "next.config.ts")
        run(CLI + ["--dir", str(ws2), "init", "--shape", "fullstack", "--non-interactive", "--shared-repo", str(remote)])
        write_config(ws2, lambda c: c["state"].update({"shared_repo": str(remote)}))
        run(CLI + ["--dir", str(ws2), "sync", "pull"])
        code, _ = run(CLI + ["--dir", str(ws), "run", "new", "lockdemo", "--tier", "2"])
        code2, out2 = run(CLI + ["--dir", str(ws2), "run", "new", "lockdemo", "--tier", "2"])
        check("a teammate's workspace cannot take a slug that is locked", code == 0 and code2 != 0 and "locked" in out2, out2[-160:])
        run(CLI + ["--dir", str(ws), "run", "finish", "lockdemo"])
        code3, out3 = run(CLI + ["--dir", str(ws2), "run", "new", "lockdemo", "--tier", "2"])
        check("the teammate can take the slug after it is released", code3 == 0, out3[-160:])
        run(CLI + ["--dir", str(ws2), "run", "finish", "lockdemo"])

        print("runner and write boundary")
        fake = tmp / "fake.sh"
        fake.write_text("#!/usr/bin/env bash\necho made > ok.txt\necho done\n")
        stray = tmp / "stray.sh"
        stray.write_text("#!/usr/bin/env bash\necho x > ../frontend/stray.txt\necho wrote elsewhere\n")
        committer = tmp / "commit.sh"
        committer.write_text("#!/usr/bin/env bash\ngit commit -q --allow-empty -m sneaky\necho committed\n")
        for f in (fake, stray, committer):
            f.chmod(0o755)
        write_config(ws, lambda c: c.setdefault("runners", {}).update({"fake": {"command": str(fake)}, "stray": {"command": str(stray)}, "commit": {"command": str(committer)}}))
        stage_cmd = CLI + ["--dir", str(ws), "stage", "run", "--slug", "demo", "--stage", "coder", "--repo", "backend"]
        code, out = run(stage_cmd + ["--runner", "fake"])
        check("a well-behaved stage passes", code == 0 and (ws / "backend/ok.txt").exists(), out[-200:])
        code, out = run(stage_cmd + ["--runner", "stray"])
        check("writing into another repo is caught (exit 3)", code == 3, f"exit {code}")
        (ws / "frontend/stray.txt").unlink(missing_ok=True)
        code, out = run(stage_cmd + ["--runner", "commit"])
        check("a commit by a stage is caught (exit 3)", code == 3, f"exit {code}")
        (ws / "backend/ok.txt").unlink(missing_ok=True)
        code, out = run(CLI + ["--dir", str(ws), "run", "finish", "demo"])
        locks = run(["git", "ls-remote", str(remote)])[1]
        check("run finish releases the lock", code == 0 and "refs/sentinel/locks/demo" not in locks, locks[-200:])
        print("input validation")
        for bad in ("../escape", "a/b", "Up", "x..y", "-lead", "a.lock", "", "a b"):
            code, out = run(CLI + ["--dir", str(ws), "run", "new", bad, "--adhoc"])
            check(f"run new rejects the slug {bad!r}", code != 0 and not (ws / ".sentinel/runs" / bad).exists() if bad else code != 0, out[-120:])
        check("nothing was written outside the runs folder", not (ws / ".sentinel/escape").exists() and not (ws / "escape").exists())
        code, out = run(CLI + ["--dir", str(ws), "spec", "set", "ok-slug", "--status", "draft", "--tests", "../../x.ts"])
        check("spec set rejects a test name with a path", code != 0 and "invalid test file name" in out, out[-160:])
        code, out = run(CLI + ["--dir", str(ws), "stage", "render", "--stage", "reviewer", "--slug", "../x"])
        check("stage render rejects a bad slug", code != 0 and "invalid slug" in out, out[-160:])
        print("per-stage runner and model")
        write_config(ws, lambda c: c.update({"single_model": False, "routing": {"coder": {"runner": "claude", "model": "opus"}, "backend-coder": {"runner": "claude", "model": "sonnet"}, "hardener": {"runner": "agy", "model": "gemini-flash"}, "qa": {"runner": "claude", "model": "sonnet"}}, "runners": {"claude": {"command": "claude", "prompt_flag": "-p"}}}))
        code, out = run(CLI + ["--dir", str(ws), "routing", "--json"])
        table = {(r["repo"], r["stage"]): r for r in json.loads(out)} if code == 0 else {}
        check("routing lists each stage with its runner and model", table.get(("frontend", "coder"), {}).get("model") == "opus" and table.get((None, "qa"), {}).get("runner") == "claude" and table.get((None, "reviewer"), {}).get("mode") == "this session", out[-200:])
        check("a repo-specific route beats the stage route", table.get(("backend", "coder"), {}).get("model") == "sonnet")
        check("a different provider can be routed per stage", table.get(("backend", "hardener"), {}).get("runner") == "agy" and table[("backend", "hardener")]["model"] == "gemini-flash")
        sys.path.insert(0, str(ROOT / "scripts"))
        import run_stage
        cfg = yaml.safe_load((ws / "sentinel.config.yaml").read_text())
        rid, runner, model = run_stage.pick_runner(cfg, "coder", None, "frontend")
        command, _ = run_stage.build_command(runner, "go", model, None, [])
        check("the model flag reaches the command even when the runner is redefined", "--model" in command and command[command.index("--model") + 1] == "opus", " ".join(command))
        rid, runner, model = run_stage.pick_runner(cfg, "hardener", None, "backend")
        command, _ = run_stage.build_command(runner, "go", model, None, [])
        check("another provider gets its own command and model", command[0] == "agy" and "gemini-flash" in command, " ".join(command))
        write_config(ws, lambda c: c.update({"single_model": False, "routing": {"coder": {"runner": "mine", "model": "x"}}, "runners": {"mine": {"command": "echo"}}}))
        code, out = run(CLI + ["--dir", str(ws), "doctor"])
        check("doctor flags a model on a runner that cannot take one", "no model_flag" in out, out[-200:])
        write_config(ws, lambda c: c.update({"single_model": True}))
        code, out = run(CLI + ["--dir", str(ws), "doctor"])
        check("single_model ignores a model on a runner that cannot take one", "no model_flag" not in out, out[-200:])
        cfg = yaml.safe_load((ws / "sentinel.config.yaml").read_text())
        cfg["runners"] = {"claude": {"command": "claude", "prompt_flag": "-p"}}
        cfg["routing"] = {"coder": {"runner": "agy", "model": "gemini-flash"}}
        rid, runner, model = run_stage.pick_runner(cfg, "coder", None, "backend")
        check("single_model ignores routing, so every stage runs in the current tool", run_stage.find_route(cfg, "coder", "backend") is None and model is None)
        write_config(ws, lambda c: c.update({"single_model": True, "routing": {"coder": {"runner": "agy"}}}))
        code, out = run(CLI + ["--dir", str(ws), "routing", "--json"])
        check("routing shows every stage in this session under single_model", code == 0 and all(r["mode"] == "this session" for r in json.loads(out)), out[-200:])
        rid, runner, model = run_stage.pick_runner(cfg, "coder", None, "backend", "other")
        check("an explicit --model still wins under single_model", model == "other")
        check("single_model is on when the key is absent", run_stage.single_model({}) is True and run_stage.single_model({"single_model": False}) is False)
        write_config(ws, lambda c: (c.pop("routing", None), c.pop("runners", None), c.pop("single_model", None)))
        print("direct push and conflicts")
        for w in (ws, ws2):
            write_config(w, lambda c: c["state"].update({"auto_sync_push": True}))
            run(CLI + ["--dir", str(w), "sync", "pull"])
        (ws / ".sentinel/shared/specs").mkdir(parents=True, exist_ok=True)
        (ws2 / ".sentinel/shared/specs").mkdir(parents=True, exist_ok=True)
        (ws / ".sentinel/shared/specs/shared-note.md").write_text("from ws\n")
        code, out = run(CLI + ["--dir", str(ws), "sync", "push", "p1", "--auto"])
        check("sync push --auto merges straight into main", code == 0 and "pushed to main" in out, out[-200:])
        check("no pull request branch is created", "refs/heads/sentinel/" not in run(["git", "ls-remote", str(remote)])[1])
        (ws2 / ".sentinel/shared/specs/shared-note.md").write_text("from ws2\n")
        code, out = run(CLI + ["--dir", str(ws2), "sync", "push", "p2", "--auto"])
        check("a conflicting push exits 4 and lists the file", code == 4 and "specs/shared-note.md" in out, out[-200:])
        code, out = run(CLI + ["--dir", str(ws2), "sync", "push", "p2", "--continue"])
        check("continue refuses while markers remain", code != 0 and "not resolved" in out, out[-200:])
        (ws2 / ".sentinel/shared/specs/shared-note.md").write_text("from ws\nfrom ws2\n")
        code, out = run(CLI + ["--dir", str(ws2), "sync", "push", "p2", "--continue"])
        check("continue pushes after the agent resolves the conflict", code == 0 and "pushed to main" in out, out[-200:])
        run(CLI + ["--dir", str(ws), "sync", "pull"])
        check("the other workspace sees the merged file", (ws / ".sentinel/shared/specs/shared-note.md").read_text() == "from ws\nfrom ws2\n")

        print("release check and scrubber")
        rc = CLI + ["--dir", str(ws), "release-check", "--quick", "--repo", "frontend"]
        (ws / "frontend/app.ts").write_text("export const a = 1;\n")
        code, out = run(rc)
        check("release check passes on a clean change", code == 0, out[-200:])
        (ws / "frontend/app.ts").write_text('console.log("debug");\nexport const t = "' + FAKE_JWT + '";\n')
        code, out = run(rc)
        check("release check fails on debug output and a token", code == 1 and "debug output" in out and "secret" in out, out[-250:])
        sample = tmp / "log.txt"
        sample.write_text(f"token {FAKE_JWT} at {FAKE_HOME}/x\nmail {FAKE_MAIL}\n")
        run([sys.executable, str(ROOT / "scripts/scrub.py"), str(sample), "--workspace", str(ws)])
        cleaned = sample.read_text()
        check("scrubber removes tokens, home paths and emails", "eyJ" not in cleaned and FAKE_HOME not in cleaned and "real-domain" not in cleaned, cleaned)

        print("change map")
        code, out = run(CLI + ["--dir", str(ws), "change-map", "collect", "--out", str(tmp / "changes.json")])
        check("change map collects the changed files", code == 0 and json.loads((tmp / "changes.json").read_text())["nodes"], out[-200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


def phase_g_checks(tmp):
    print("dashboard read routes (phase G)")
    import http.client
    sys.path.insert(0, str(ROOT / "scripts"))
    from apiserver import userdir
    from apiserver.server import ApiServer
    home = tmp / "home-g"
    home.mkdir()
    w = tmp / "ws-g"
    w.mkdir()
    git_repo(w / "backend", "build.gradle")
    git_repo(w / "frontend", "next.config.ts")
    run(CLI + ["--dir", str(w), "init", "--shape", "fullstack", "--non-interactive", "--local-only"])
    cfgdir = home / ".config" / "sentinel"
    userdir.ensure_dir(cfgdir)
    data = userdir.load_projects(cfgdir)
    data["projects"].append({"id": "ws-g", "name": "ws-g", "path": str(w.resolve()), "added_at": "2026-11-14T00:00:00Z"})
    userdir.save_projects(cfgdir, data)
    srv = ApiServer(cfgdir, port=0, user="dev", git_name="Dev User", dispatch=False)
    srv.start()
    try:
        def call(path, cookie=None, method="GET"):
            conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=20)
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", f"127.0.0.1:{srv.port}")
            if cookie:
                conn.putheader("Cookie", f"sentinel_session={cookie}")
            conn.endheaders()
            resp = conn.getresponse()
            body = resp.read()
            headers = dict(resp.getheaders())
            conn.close()
            return resp.status, headers, body
        status, headers, _ = call(f"/auth?t={srv.token}")
        cookie = headers["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
        check("AC-INS-06b a new read route needs the session cookie", call("/api/v1/installation/health")[0] == 401)
        status, _, body = call("/api/v1/installation/health", cookie)
        health = json.loads(body)
        names = [i["name"] for i in health["items"]]
        check("AC-INS-03e the health answer lists the ten checks", status == 200 and names == ["installation", "version", "git", "python", "pyyaml", "jsonschema", "registry_writable", "provider", "storage", "repo_access"], body[:200].decode())
        code, out = run(CLI + ["--dir", str(w), "doctor"])
        doctor_fails = code != 0
        api_fails = any(i["status"] == "failed" for i in health["items"] if i["name"] in ("storage", "repo_access"))
        check("AC-INS-07a doctor and the health answer agree on whether the workspace has problems", doctor_fails == api_fails or (doctor_fails and "command not found" in out), out[-200:])
        status, _, body = call("/api/v1/projects/ws-g/repositories", cookie)
        repos = json.loads(body)
        check("AC-REP-03a the repository list follows the config order", status == 200 and [r["id"] for r in repos["items"]] == [r["id"] for r in yaml.safe_load((w / "sentinel.config.yaml").read_text())["repos"]], body[:200].decode())
        status, _, body = call("/api/v1/projects/ws-g/readiness", cookie)
        ready = json.loads(body)
        check("AC-DSH-03d readiness answers a state and items that carry checked_at", status == 200 and ready["state"] in ("ready", "ready_with_warnings", "needs_configuration", "invalid_configuration", "connection_unavailable") and all("checked_at" in i for i in ready["items"]), body[:200].decode())
        status, _, body = call("/api/v1/projects/ws-g/configuration", cookie)
        conf = json.loads(body)
        check("AC-CFG-06a the configuration answer carries the sha256 of the file and sourced values", status == 200 and len(conf["sha256"]) == 64 and all("source" in i for i in conf["items"]), body[:200].decode())
        check("AC-INS-06a a mutating contract route is still not offered", call("/api/v1/projects/ws-g/configuration/import", cookie, "POST")[0] in (403, 404))
    finally:
        srv.stop()


def phase_h_a_checks(tmp):
    print("notifications and analytics (phase H part A)")
    import http.client
    import stat as stat_mod
    sys.path.insert(0, str(ROOT / "scripts"))
    from apiserver import userdir
    from apiserver.server import ApiServer
    home = tmp / "home-h"
    home.mkdir()
    env = {**ENV, "HOME": str(home), "XDG_CONFIG_HOME": ""}

    def sh(args, cwd=None):
        r = subprocess.run(CLI + args, cwd=cwd, capture_output=True, text=True, env=env)
        return r.returncode, r.stdout, r.stderr
    w = tmp / "ws-h"
    w.mkdir()
    git_repo(w / "backend", "build.gradle")
    git_repo(w / "frontend", "next.config.ts")
    sh(["--dir", str(w), "init", "--shape", "fullstack", "--non-interactive", "--local-only"])
    fresh = tmp / "ws-h-fresh"
    fresh.mkdir()
    git_repo(fresh / "backend", "build.gradle")
    git_repo(fresh / "frontend", "next.config.ts")
    sh(["--dir", str(fresh), "init", "--shape", "fullstack", "--non-interactive", "--local-only"])
    cfgdir = home / ".config" / "sentinel"
    code, out, err = sh(["--dir", str(w), "run", "new", "h-run", "--type", "feature"])
    check("a version 2 run is created for the notification checks", code == 0, err[-200:])
    check("sentinel notifications creates nothing when no project is registered", sh(["notifications", "--json"])[0] == 0 and not cfgdir.exists())
    userdir.ensure_dir(cfgdir)
    data = userdir.load_projects(cfgdir)
    data["projects"].append({"id": "ws-h", "name": "ws-h", "path": str(w.resolve()), "added_at": "2026-11-14T00:00:00Z"})
    userdir.save_projects(cfgdir, data)
    code, out, err = sh(["notifications", "--json"])
    listing = json.loads(out) if code == 0 else {}
    texts = [n["text"] for n in listing.get("items", [])]
    check("AC-NOT-01a a new run gives the notification Run started, computed from the events table", code == 0 and "Run started" in texts and listing.get("unread", 0) >= 1, out[-200:] + err[-200:])
    check("AC-NOT-01d reading notifications does not create user.db", not (cfgdir / "user.db").exists())
    code, out, err = sh(["notifications", "read", "--all"])
    db = cfgdir / "user.db"
    check("AC-NOT-01o user.db is created 0600 by the first mark read", code == 0 and db.exists() and stat_mod.S_IMODE(db.stat().st_mode) == 0o600, err[-200:])
    code, out, err = sh(["notifications", "--unread"])
    check("AC-NOT-01i notifications --unread prints nothing after read --all", code == 0 and out.strip() == "", out[-200:])
    code, out, err = sh(["notifications", "read", "ws-h:abc"])
    check("AC-NOT-01k a malformed notification id is refused", code != 0 and "E_VALIDATION" in err, err[-200:])
    code, out, err = sh(["--dir", str(w), "stats"])
    stats = json.loads(out) if code == 0 else {}
    check("AC-ANL-01f stats keeps its 0.1 keys and adds v2", all(k in stats for k in ("runs", "by_tier", "escalated_runs", "outcomes", "avg_rounds", "stage_isolation", "tokens_by_stage", "seconds_by_stage")) and stats.get("v2", {}).get("runs", {}).get("total") == 1, out[-200:] + err[-200:])
    code, out, err = sh(["--dir", str(w), "stats", "--format", "md", "--from", "2000-01-01"])
    check("AC-ANL-01g stats --format md prints a Markdown table", code == 0 and "| Metric | Value |" in out and "| runs.total | 1 |" in out, out[-200:])
    code, out, err = sh(["--dir", str(w), "stats", "--from", "2026-13-01"])
    check("AC-ANL-01h a bad date exits 2 naming the argument", code == 2 and "--from" in err, err[-200:])
    registry = fresh / ".sentinel" / "sentinel.db"
    existed = registry.exists()
    code, out, err = sh(["--dir", str(fresh), "stats"])
    check("AC-ANL-01i stats opens no registry that does not exist and creates none", code == 0 and json.loads(out)["v2"] == {"value": None, "reason": "no registry"} and registry.exists() == existed, out[-200:] + err[-200:])
    before = hashlib.sha256((w / ".sentinel" / "sentinel.db").read_bytes()).hexdigest()
    sh(["--dir", str(w), "stats"])
    check("AC-ANL-01l analytics never write to the registry", hashlib.sha256((w / ".sentinel" / "sentinel.db").read_bytes()).hexdigest() == before)

    srv = ApiServer(cfgdir, port=0, user="dev", git_name="Dev User", dispatch=False)
    srv.start()
    try:
        def call(path, cookie=None, method="GET", csrf=None):
            conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=20)
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", f"127.0.0.1:{srv.port}")
            if cookie:
                conn.putheader("Cookie", f"sentinel_session={cookie}")
            if csrf:
                conn.putheader("X-Sentinel-CSRF", csrf)
            if method == "POST":
                conn.putheader("Content-Type", "application/json")
                conn.putheader("Content-Length", "2")
            conn.endheaders()
            if method == "POST":
                conn.send(b"{}")
            resp = conn.getresponse()
            body = resp.read()
            headers = dict(resp.getheaders())
            conn.close()
            return resp.status, headers, body
        status, headers, _ = call(f"/auth?t={srv.token}")
        cookie = headers["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]
        check("AC-NOT-01j the notification routes need the session cookie", call("/api/v1/notifications")[0] == 401)
        status, _, body = call("/api/v1/notifications", cookie)
        answer = json.loads(body)
        check("AC-NOT-03c the API serves notifications with only id, project, run, level, text, link, at and read_at", status == 200 and answer["items"] and all(set(n) == {"id", "project", "run", "level", "text", "link", "at", "read_at"} for n in answer["items"]), body[:200].decode())
        nid = answer["items"][0]["id"]
        status, _, body = call(f"/api/v1/notifications/{nid}/read", cookie, "POST")
        check("AC-NOT-01j marking read without the CSRF value is refused", status == 403 and b"E_CSRF" in body, body[:200].decode())
        status, _, body = call("/api/v1/reports/analytics?project=ws-h", cookie)
        check("AC-ANL-01n the analytics route answers the v2 section", status == 200 and json.loads(body)["runs"]["total"] == 1, body[:200].decode())
        check("AC-ANL-01o an unknown analytics query parameter is refused", call("/api/v1/reports/analytics?project=ws-h&sql=select", cookie)[0] == 400)
    finally:
        srv.stop()


def phase_j_checks(tmp):
    print("QA scenarios as Red evidence (phase J, TDD-09)")
    sys.path.insert(0, str(ROOT / "scripts"))
    import jsonschema
    import qa_scenarios as Q
    from registry import Registry
    schema = json.loads((ROOT / "core/schema/config.schema.json").read_text())
    base = {"driver": "playwright", "ports": [4173], "start_commands": {"frontend": "true"}}

    def qa_valid(**extra):
        errors = jsonschema.Draft202012Validator(schema["properties"]["qa"]).iter_errors({**base, **extra})
        return not list(errors)
    check("AC-CFG-12d the qa.scenario_run and qa.scenario_report keys are validated",
          qa_valid(scenario_run="node qa/run.js {scripts}", scenario_report="qa-report.xml") and not qa_valid(scenario_run="")
          and not qa_valid(scenario_run=5) and not qa_valid(scenario_report="../outside.xml") and not qa_valid(unknown_key="x"))
    check("AC-CFG-12e a qa section without the new keys stays valid", qa_valid(db_clone="none", fixtures="sanitized"))
    cfg = {"rules": {Q.RULE: True}, "repos": [{"id": "web", "role": "frontend"}, {"id": "api", "role": "backend"}, {"id": "app", "role": "mobile"}]}
    check("AC-TDD-09b the method follows the rule and the repo role",
          [Q.method_for(cfg, r) for r in ("web", "api", "app")] == [Q.QA, Q.TEST, Q.QA]
          and Q.method_for({**cfg, "rules": {Q.RULE: False}}, "web") == Q.TEST)
    w = tmp / "ws-hj"
    w.mkdir()
    fake = w / "driver.py"
    fake.write_text("import sys, os\nopen(sys.argv[2], 'w').write('<testsuite><testcase name=\"AC-1\"><failure message=\"Then x: nope\"/></testcase>'"
                    "'<testcase name=\"AC-2\"/></testsuite>')\nsys.exit(1)\n")
    good = {"qa": {"driver": "playwright", "scenario_run": f"{sys.executable} {fake} {{scripts}} {{report}} {{cycle}}", "scenario_report": "r.xml",
                   "start_commands": {"web": "true"}}}
    check("AC-CFG-12a a missing QA driver piece is named at R12", Q.driver_problem(good, w, "web") is None
          and Q.driver_problem({"qa": {"driver": "none"}}, w, "web") == "QA driver is none"
          and Q.driver_problem({}, w, "web") == "QA driver is not configured"
          and Q.driver_problem({"qa": {**good["qa"], "scenario_run": "python3 /nonexistent/x.py"}}, w, "web").startswith("qa.scenario_run does not exist")
          and Q.driver_problem({"qa": {**good["qa"], "start_commands": {}}}, w, "web") == "no QA start command for repo web")
    ran = Q.run_driver(good, w, "web", w / "scripts", "c-1", w / "qa", 30, lambda: "now")
    judged = Q.judge(ran, ["AC-1", "AC-2"])
    check("AC-TDD-09n the engine runs the driver and judges per scenario (a pass before Green is unexpected)",
          judged["class"] == "partial_pass" and judged["failing"] == ["AC-1"] and judged["passing"] == ["AC-2"], str(judged["class"]))
    check("AC-TDD-09n a failure at a Then step on every scenario is the right reason",
          Q.judge({"report": [("AC-1", "failure", "Then x: nope"), ("AC-2", "failure", "Then y: nope")], "output": ""}, ["AC-1", "AC-2"])["class"] == "assertion"
          and Q.judge({"report": [("AC-1", "failure", "Given x: nope")], "output": ""}, ["AC-1"])["class"] == "setup_failure"
          and Q.judge({"report": None, "output": "net::ERR_CONNECTION_REFUSED"}, ["AC-1"])["class"] == "app_not_running")
    reg = Registry.open(w / ".sentinel")
    cols = {r[1] for r in reg._c.execute("PRAGMA table_info(cycles)")}
    ecols = {r[1] for r in reg._c.execute("PRAGMA table_info(evidence)")}
    reg.close()
    check("AC-SM-06a the registry keeps the cycle table and adds red_method and the evidence exception fields",
          {"red_method", "approved_scripts"} <= cols and {"method", "exception", "scripts"} <= ecols)
    schema_task = json.loads((ROOT / "core/schema/task-v1.schema.json").read_text())
    check("AC-TDD-09i the qa_red role has a stage template and a task schema entry",
          "qa_red" in schema_task["properties"]["role"]["enum"] and (ROOT / "core/stages/qa_red.md").is_file())
    qa_red_end_to_end(tmp)


def qa_red_end_to_end(tmp):
    """A QA-Red cycle through the real CLI and engine with a fake agent and a fake QA driver: Red, Green, Refactor, exception record."""
    w = tmp / "ws-hj-e2e"
    w.mkdir()
    git_repo(w / "frontend", "package.json")
    run(CLI + ["--dir", str(w), "init", "--shape", "fullstack", "--non-interactive", "--local-only"])
    d = ["--dir", str(w)]
    bin_dir = w / "bin"
    bin_dir.mkdir()
    driver = bin_dir / "qadriver"
    driver.write_text(f"""#!{sys.executable}
import os, pathlib, sys
scripts, report = sys.argv[1], sys.argv[2]
mode = (pathlib.Path(__file__).resolve().parent / "mode.txt").read_text().strip()
ids = sorted(f.split(".")[0] for f in os.listdir(scripts) if os.path.isfile(os.path.join(scripts, f)))
body = "".join('<testcase name="%s">%s</testcase>' % (i, '<failure message="Then the form shows 5 days: got 0"/>' if mode == "red" else "") for i in ids)
os.makedirs(os.path.dirname(report), exist_ok=True)
pathlib.Path(report).write_text("<testsuite>" + body + "</testsuite>")
sys.exit(1 if mode == "red" else 0)
""")
    driver.chmod(0o755)
    agent = bin_dir / "qaagent"
    agent.write_text(f"""#!{sys.executable}
import json, os, pathlib, re, sys
prompt = sys.argv[-1]
result = re.search(r'Result file \\(absolute path\\): (\\S+)', prompt).group(1)
ws = os.path.dirname(os.getcwd())
role = re.search(r'- Role: (\\w+)', prompt).group(1)
if role == "qa_red":
    for sid, rel in re.findall(r'^- `([^`]+)` -> `([^`]+)`$', prompt, re.M):
        p = pathlib.Path(ws, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("scenario " + sid + "\\n")
else:
    p = pathlib.Path(os.getcwd(), "src/main/Form.js")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text((p.read_text() if p.exists() else "") + "// form\\n")
pathlib.Path(result).write_text(json.dumps({{"schema": "agent-result-v1", "task_id": os.environ["SENTINEL_TASK_ID"], "status": "completed", "summary": "s"}}))
""")
    agent.chmod(0o755)
    (bin_dir / "mode.txt").write_text("red")
    py = sys.executable

    def mutate(c):
        c["repos"] = [{"id": "frontend", "path": "frontend", "role": "frontend", "profile": "generic", "test_globs": ["src/test/**"],
                       "production_globs": ["src/main/**"], "commands": {"test": "true"}}]
        c.update({"single_model": False, "rules": {"no_permanent_frontend_tests": True},
                  "runners": {"qa": {"command": str(agent)}}, "agents": {r: {"runner": "qa"} for r in ("qa_red", "tdd_green", "tdd_refactor")},
                  "qa": {"driver": "playwright", "start_commands": {"frontend": "true"}, "scenario_run": f"{py} {driver} {{scripts}} {{report}} {{cycle}}",
                         "scenario_report": "qa-report.xml"}})
    write_config(w, mutate)
    sys.path.insert(0, str(ROOT / "scripts"))
    from engine import Engine
    slug = "qa-e2e"
    run(CLI + d + ["run", "new", slug])
    db_set(w, slug, state="PLANNED", tier=1, initial_tier=1)
    sd = w / ".sentinel/shared/specs" / slug
    (sd / "features").mkdir(parents=True, exist_ok=True)
    (sd / "spec.md").write_text(lite_spec(slug))
    eng = Engine(w / ".sentinel", w, yaml.safe_load((w / "sentinel.config.yaml").read_text()))
    try:
        def submit(role, feats=None):
            for n, t in (feats or {}).items():
                (sd / "features" / n).write_text(t)
            tid = eng.create_task(slug, role, f"{role} work", ["frontend"], queue=True)["id"]
            eng.start_task(tid, schedule=False)
            (w / ".sentinel/runs" / slug / "tasks" / tid / "result.json").write_text(json.dumps(
                {"schema": "agent-result-v1", "task_id": tid, "status": "completed", "summary": "done"}))
            return eng.finish_task(tid)["completion"]

        def approve(gate):
            info = eng.pending_approval(slug, gate)
            eng.decide(slug, gate, "approve", "human", prefix=info["sha256"][:8], approver="dev")
        assert submit("specifier")["accepted"]
        approve("spec")
        assert submit("test_designer", FEATURES)["accepted"]
        approve("gherkin")
        eng.advance(slug)
    finally:
        eng.close()

    def cycle():  # the first cycle; the second one waits for it
        return db_all(w, "SELECT * FROM cycles ORDER BY ordinal")[0]

    def task_run(mode):
        (bin_dir / "mode.txt").write_text(mode)
        step = json.loads(run(CLI + d + ["next", slug, "--json"])[1])
        return run(CLI + d + ["task", "run", step["task"]]), step
    (code, out), step = task_run("red")
    c = cycle()
    red = db_all(w, "SELECT * FROM evidence WHERE kind='red'")
    check("AC-TDD-09m a QA-Red task writes the scripts, the engine runs the driver and accepts a failure at a Then step",
          step.get("role") == "qa_red" and code == 0 and c["state"] == "RED_VERIFIED" and c["red_method"] == "qa_scenario"
          and len(red) == 1 and red[0]["classification"] == "assertion" and red[0]["method"] == "qa_scenario"
          and len(json.loads(c["approved_scripts"])) == 1 and db_all(w, "SELECT 1 FROM events WHERE type='tdd.exception_recorded'"), out[-300:])
    (code, out), _ = task_run("green")
    (code2, out2), _ = task_run("green")
    c = cycle()
    check("AC-TDD-09s Green and Refactor pass the same scripts through the driver and the cycle is accepted with the exception recorded",
          code == 0 and code2 == 0 and c["state"] == "CYCLE_ACCEPTED" and len(db_all(w, "SELECT 1 FROM evidence WHERE method='qa_scenario' AND verdict='accepted'")) == 3
          and len(db_all(w, "SELECT 1 FROM events WHERE type='tdd.exception_recorded'")) == 1, (out + out2)[-300:])


def phase_h_b_checks(tmp):
    print("audit chain, export, backup (phase H part B)")
    sys.path.insert(0, str(ROOT / "scripts"))
    from registry import Registry
    w = tmp / "ws-hb"
    w.mkdir()
    git_repo(w / "backend", "build.gradle")
    run(CLI + ["--dir", str(w), "init", "--shape", "single", "--non-interactive", "--local-only"])
    reg = Registry.open(w / ".sentinel")
    with reg.transaction():
        for i in range(5):
            reg.add_audit("dev", "tty", "approve", f"run-{i}", reason="token=abcd1234efgh5678" if i == 2 else None)
    reg.close()
    code, out = run(CLI + ["--dir", str(w), "audit", "verify"])
    check("AC-SEC-07g audit verify passes on an untouched registry", code == 0 and "5 rows" in out, out[-200:])
    code, out = run(CLI + ["--dir", str(w), "audit", "export", "--out", str(w / "audit.jsonl")])
    text = (w / "audit.jsonl").read_text() if (w / "audit.jsonl").exists() else ""
    check("AC-SEC-07h audit export writes a 0600 scrubbed file that verifies", code == 0 and oct((w / "audit.jsonl").stat().st_mode & 0o777) == "0o600"
          and "abcd1234efgh5678" not in text and run(CLI + ["--dir", str(w), "audit", "verify", "--file", str(w / "audit.jsonl")])[0] == 0, out[-200:])
    code2 = subprocess.run(CLI + ["--dir", str(w), "audit", "export", "--out", str(w / "t2.jsonl")], capture_output=True, text=True,
                           env={**ENV, "SENTINEL_TASK_ID": "t-1"}).returncode
    check("AC-SEC-07o a task process cannot export the audit", code2 == 5 and not (w / "t2.jsonl").exists())
    code, out = run(CLI + ["--dir", str(w), "backup"])
    info = json.loads(out) if code == 0 else {}
    check("AC-OPS-05a backup writes a checked copy", code == 0 and info.get("counts", {}).get("audit", 0) >= 5 and Path(info["path"]).exists(), out[-200:])
    check("AC-OPS-05h backup --verify accepts the copy", run(CLI + ["--dir", str(w), "backup", "--verify", info.get("path", "")])[0] == 0)
    bad = Path(info["path"]).with_name("bad.db")
    bad.write_bytes(b"not a database" * 50)
    check("AC-OPS-05h backup --verify refuses a file that is not SQLite", run(CLI + ["--dir", str(w), "backup", "--verify", str(bad)])[0] == 1)
    code, out = run(CLI + ["--dir", str(w), "backup", "restore", info["path"]])
    check("AC-OPS-05j restore without a terminal is refused", code == 5 and "E_NOT_TTY" in out, out[-200:])
    conn = sqlite3.connect(w / ".sentinel/sentinel.db")
    conn.execute("DROP TRIGGER audit_no_update")
    conn.execute("UPDATE audit SET actor='agent' WHERE id=2")
    conn.commit()
    conn.close()
    code, out = run(CLI + ["--dir", str(w), "audit", "verify"])
    check("AC-SEC-07f audit verify names the first tampered row", code == 1 and "row 2" in out, out[-200:])


if __name__ == "__main__":
    main()
