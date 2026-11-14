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
                                                     "gone": {"command": "no-such-agent-cli"}}}))
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


def main():
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


if __name__ == "__main__":
    main()
