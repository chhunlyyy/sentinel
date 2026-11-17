"""QA scenarios as Red evidence (TDD-09): method choice, driver precheck, script paths, the engine's driver run and its judgement.

With rules.no_permanent_frontend_tests on, a behavior group of a client repo (role frontend or mobile) has no test file. A qa_red
task writes one automated script per scenario under the QA cache folder; the engine runs them through qa.scenario_run, reads the
JUnit-style report qa.scenario_report and judges it. Pure helpers here; CycleOps (cycles.py) writes the evidence.

Report contract: one testcase per scenario, `name` is the scenario id (the @AC tag, else the key with other characters as `_`);
a failure message starts with the Gherkin keyword of the failing step ("Then the form shows 5 days: ..."); an <error> or a
message with another start is a script error. Source: plan/v1.1/phaseJ/README.md.
"""
import contextlib
import fcntl
import os
import re
import shlex
import signal
import socket
import stat
import subprocess
import threading
import time

import adapters
import classifier
import scopes
from errors import SentinelError
from hashlib import sha256
from render_stage import CLIENT_ROLES

RULE = "no_permanent_frontend_tests"
QA, TEST = "qa_scenario", "test_file"
PORT_WAIT = 30
LOCK_WAIT = 3600
TIMEOUT = 1800
OUTPUT_CAP = 5 * 1024 * 1024
CAP_MARK = "\n[output truncated at 5 MB]\n"
ENV_CLASSES = ("app_not_running", "driver_error")
HUMAN_CLASSES = ENV_CLASSES + ("unknown",)
APP_DOWN = re.compile(r"ECONNREFUSED|ERR_CONNECTION_REFUSED|Connection refused|app (is )?not (running|listening)", re.I)
DRIVER_DOWN = re.compile(r"command not found|No such file or directory|Executable doesn't exist|cannot (launch|start) .*browser|"
                         r"browser.*(failed|cannot).*(launch|start)|timed out after", re.I)
SCRIPT_SUFFIXES = (".py", ".js", ".mjs", ".ts", ".sh")


def method_for(cfg, repo_id):
    repo = scopes._repo(cfg, repo_id) or {}
    return QA if (cfg.get("rules") or {}).get(RULE) and repo.get("role") in CLIENT_ROLES else TEST


def exception_doc(repo_id):
    return {"rule": RULE, "replaced": TEST, "by": QA, "repo": repo_id}


def _script_tokens(command):
    try:
        parts = shlex.split(command)
    except ValueError:
        return []
    while parts and re.fullmatch(r"[A-Za-z_]\w*=.*", parts[0]):
        parts.pop(0)
    return [p for p in parts if "{" not in p and not p.startswith("-") and ("/" in p or p.endswith(SCRIPT_SUFFIXES))]


def _repo_dir(cfg, workspace, repo_id):
    repo = scopes._repo(cfg, repo_id) or {}
    return os.path.join(str(workspace), repo.get("path", repo_id))


def resolve_token(token, repo_dir, workspace):
    """The file a script token of qa.scenario_run names: the run's cwd (the repo) first, then the workspace; None when neither has it."""
    if os.path.isabs(token):
        return token if os.path.exists(token) else None
    for base in (repo_dir, str(workspace)):
        path = os.path.normpath(os.path.join(base, token))
        if os.path.exists(path):
            return path
    return None


def runner_files(cfg, workspace, repo_id):
    """Workspace-relative paths of the regular files named in qa.scenario_run that sit inside the workspace (the runner the
    engine trusts; files elsewhere, such as /usr/bin/node, are outside what Sentinel can protect)."""
    qa = cfg.get("qa") if isinstance(cfg.get("qa"), dict) else {}
    ws = os.path.realpath(str(workspace))
    repo_dir = _repo_dir(cfg, workspace, repo_id)
    out = []
    for tok in _script_tokens(qa.get("scenario_run") or ""):
        path = resolve_token(tok, repo_dir, workspace)
        if not path or not os.path.isfile(path):
            continue
        real = os.path.realpath(path)
        if real == ws or not real.startswith(ws + os.sep):
            continue
        rel = os.path.relpath(real, ws).replace(os.sep, "/")
        if rel not in out:
            out.append(rel)
    return out


def driver_problem(cfg, workspace, repo_id):
    """Why a QA-Red cycle of `repo_id` cannot run (text), or None."""
    qa = cfg.get("qa")
    if not isinstance(qa, dict):
        return "QA driver is not configured"
    if qa.get("driver") in (None, "none"):
        return "QA driver is none" if qa.get("driver") else "QA driver is not configured"
    if not qa.get("scenario_run"):
        return "qa.scenario_run is not configured"
    if not qa.get("scenario_report"):
        return "qa.scenario_report is not configured"
    if not (qa.get("start_commands") or {}).get(repo_id):
        return f"no QA start command for repo {repo_id}"
    repo_dir = _repo_dir(cfg, workspace, repo_id)
    for tok in _script_tokens(qa["scenario_run"]):
        if resolve_token(tok, repo_dir, workspace) is None:
            return "qa.scenario_run does not exist: " + tok
    return None


def scenario_id(key, text):
    m = re.search(r"@(AC-[A-Za-z0-9_-]+)", text or "")
    return m.group(1) if m else re.sub(r"[^A-Za-z0-9_-]+", "_", key).strip("_")


def scripts_rel(state_name, slug, cycle_id=None):
    base = f"{state_name}/cache/qa/tests/current/{slug}"
    return f"{base}/{cycle_id}" if cycle_id else base


def _hash_lstat(path):
    """sha256 of a regular file, None when it is gone, not a regular file (symlink, directory) or unreadable."""
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        with open(path, "rb") as f:
            return sha256(f.read()).hexdigest()
    except OSError:
        return None


def manifest(workspace, rel_dir):
    """[{"path", "sha256", "scenario"}] of every file of a cycle folder, subfolders included, sorted by path. "scenario" is the
    stem of a top-level file, None for a helper in a subfolder. A symlink anywhere in the tree is E_INTEGRITY (it could point
    out of the folder and be changed there unseen)."""
    base = os.path.join(str(workspace), rel_dir)
    out = []
    if os.path.islink(base):
        raise SentinelError("E_INTEGRITY", f"the QA script folder is a symlink: {rel_dir}", {"path": rel_dir})
    for root, dirs, names in os.walk(base, followlinks=False):
        dirs.sort()
        for name in sorted(names + [d for d in dirs if os.path.islink(os.path.join(root, d))]):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, str(workspace)).replace(os.sep, "/")
            mode = os.lstat(full).st_mode
            if stat.S_ISLNK(mode):
                raise SentinelError("E_INTEGRITY", f"a symlink in the QA script folder is not allowed: {rel}", {"path": rel})
            if not stat.S_ISREG(mode):
                continue
            top = os.path.dirname(full) == base
            out.append({"path": rel, "sha256": _hash_lstat(full), "scenario": name.split(".")[0] if top else None})
    return sorted(out, key=lambda x: x["path"])


def changed_scripts(workspace, items, rel_dir=None):
    """Paths of `items` ({"path","sha256"}) whose bytes differ now, that are gone or became symlinks; with `rel_dir`, also files
    now in that folder (subfolders included) that the items do not list."""
    out = [it["path"] for it in items if _hash_lstat(os.path.join(str(workspace), it["path"])) != it["sha256"]]
    if rel_dir:
        known = {it["path"] for it in items}
        try:
            now = manifest(workspace, rel_dir)
        except SentinelError as err:
            return out + [err.details.get("path", rel_dir)]
        out += [x["path"] for x in now if x["path"] not in known]
    return out


def tree_state(workspace, rel_dir):
    """{path relative to rel_dir: sha256, or "symlink"} of every entry of a folder tree (lstat, no following)."""
    base = os.path.join(str(workspace), rel_dir)
    out = {}
    for root, dirs, names in os.walk(base, followlinks=False):
        for name in names + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            out[rel] = _hash_lstat(full) if stat.S_ISREG(os.lstat(full).st_mode) else "symlink"
    return out


def steps_of(text):
    """[(keyword, step text)] of a scenario's Gherkin text; And, But and * inherit the keyword of the step before."""
    out, last = [], None
    for raw in (text or "").splitlines():
        m = re.match(r"\s*(Given|When|Then|And|But|\*)\s+(.*\S)\s*$", raw)
        if not m:
            continue
        kw = m.group(1)
        if kw in ("And", "But", "*"):
            kw = last
        else:
            last = kw
        out.append((kw, m.group(2), m.group(1)))
    return out


@contextlib.contextmanager
def driver_lock(path, wait=None):
    """One QA driver run at a time in the workspace (the QA ports are shared). flock: a killed process frees it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.time() + (LOCK_WAIT if wait is None else wait)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() > deadline:
                    raise SentinelError("E_LOCKED", "the QA driver is busy", {"lock": str(path)})
                time.sleep(0.1)
        yield
    finally:
        os.close(fd)


def listening(port):
    """True when something accepts a connection on the port, on 127.0.0.1 or on ::1 (an app may bind either)."""
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect((host, int(port)))
                return True
        except OSError:
            continue
    return False


def _kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_command(cmd, cwd, env, timeout, cap=OUTPUT_CAP):
    """Run a shell command in its own process group; (exit code, output text, timed_out). One path for the engine's test runs and
    the QA driver: stdout and stderr together, a timeout kills the whole group (code 124), output beyond `cap` bytes is dropped
    while the process keeps running and the text ends with a marker."""
    proc = subprocess.Popen(cmd, shell=True, cwd=str(cwd), env=env, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    chunks, size, cut = [], [0], [False]

    def pump():
        for chunk in iter(lambda: proc.stdout.read(65536), b""):
            room = cap - size[0]
            if room > 0:
                chunks.append(chunk[:room])
                size[0] += len(chunk[:room])
            if len(chunk) > max(room, 0):
                cut[0] = True
    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    timed_out = False
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(proc)
        proc.wait()
        code, timed_out = 124, True
    reader.join(5)
    if reader.is_alive():  # a daemon that kept the pipe open: stop it so the reader ends
        _kill(proc)
        reader.join(5)
    proc.stdout.close()
    text = b"".join(chunks).decode("utf-8", errors="replace")
    if cut[0]:
        text += CAP_MARK
    if timed_out:
        text += f"\ntimed out after {timeout} seconds\n"
    return code, text, timed_out


def report_path(qa_dir, rel):
    """The report file inside the QA folder; E_VALIDATION for an absolute path or one that leaves the folder."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/"):
        raise SentinelError("E_VALIDATION", f"qa.scenario_report must be a relative path inside the QA folder: {rel!r}", {"path": rel})
    full = os.path.normpath(os.path.join(qa_dir, rel))
    if not (full + os.sep).startswith(os.path.normpath(qa_dir) + os.sep):
        raise SentinelError("E_VALIDATION", f"qa.scenario_report leaves the QA folder: {rel!r}", {"path": rel})
    return full


def run_driver(cfg, repo_path, repo_id, scripts_dir, cycle_id, qa_dir, timeout, now):
    """Start the repo's app (when its ports are not open), run qa.scenario_run, stop what was started. Returns a dict like
    _run_tests plus "report" (cases or None), "timed_out", "app_down", "app_started", "artifacts" (paths under the QA folder)."""
    qa = cfg["qa"]
    report = report_path(qa_dir, qa["scenario_report"])
    os.makedirs(os.path.dirname(report), exist_ok=True)
    try:
        os.remove(report)
    except OSError:
        pass
    cmd = qa["scenario_run"].replace("{scripts}", shlex.quote(str(scripts_dir))).replace("{report}", shlex.quote(report)) \
        .replace("{cycle}", shlex.quote(cycle_id))
    env = adapters.child_env(cfg)
    env.pop(adapters.TASK_ENV, None)
    started, began = now(), time.time()
    app = None
    ports = [p for p in qa.get("ports") or [] if isinstance(p, int)]
    ran = {"command": cmd, "exit_code": None, "output": "", "started_at": started, "cwd": repo_id, "report": None,
           "timed_out": False, "app_down": False, "app_started": False, "artifacts": []}
    with driver_lock(os.path.join(qa_dir, "driver.lock")):
        try:
            if ports and not all(listening(p) for p in ports):
                app = subprocess.Popen(qa["start_commands"][repo_id], shell=True, cwd=str(repo_path), env=env, start_new_session=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                ran["app_started"] = True
                end = time.time() + PORT_WAIT
                while time.time() < end and not all(listening(p) for p in ports):
                    time.sleep(0.1)
            if ports and not all(listening(p) for p in ports):
                ran.update(app_down=True, exit_code=1, output="app not running: nothing listens on port " +
                           ", ".join(str(p) for p in ports if not listening(p)) + "\n")
            else:
                ran["exit_code"], ran["output"], ran["timed_out"] = run_command(cmd, repo_path, env, timeout)
        finally:
            if app is not None:
                _kill(app)
                app.wait()
    try:
        with open(report, encoding="utf-8", errors="replace") as f:
            ran["report"] = classifier.parse_junit_cases(f.read()) if os.path.getmtime(report) >= began - 2 else None
    except OSError:
        pass
    for sub in ("screenshots", "traces"):
        base = os.path.join(qa_dir, sub)
        for root, _, names in os.walk(base):
            for n in sorted(names):
                full = os.path.join(root, n)
                if os.path.getmtime(full) >= began - 2:
                    ran["artifacts"].append(os.path.relpath(full, os.path.dirname(os.path.dirname(qa_dir))).replace(os.sep, "/"))
    ran["finished_at"] = now()
    return ran


def _step(message):
    return (message or "").split(":", 1)[0].strip()


def effective_step(message, steps):
    """The Gherkin keyword the failing step counts as. The message starts with the step as written ("And the form shows ...:").
    And and But take the keyword of the step before, found in the scenario's `steps` ([(effective, text, written)] from
    steps_of); without a match the answer is "And" or "But" itself, which judge treats as not a Then step (a Red is never
    accepted on a guess)."""
    step = _step(message)
    word = step.split(None, 1)[0] if step else ""
    if word not in ("And", "But", "*"):
        return word
    rest = step[len(word):].strip()
    for eff, text, written in steps or ():
        if written == word and text.strip() == rest:
            return eff or word
    return word


def judge(ran, ids, steps=None):
    """Judge one driver run against the scenario ids of the cycle; `steps` maps a scenario id to steps_of(text) so a failure at an
    And or But step is judged by the keyword it inherits. A scenario reported twice is a script_error (the script is not
    consistent; flaky is a rerun result). Returns {"class", "results", "failing", "passing", "missing",
    "extra", "skipped", "line"}; class is pass, assertion (every scenario failed at a Then step), partial_pass (some failed at a Then
    step, some passed), setup_failure, script_error, unbound_scenario, app_not_running, driver_error or unknown."""
    out = {"class": None, "results": [], "failing": [], "passing": [], "missing": [], "extra": [], "skipped": [], "line": ""}
    text = ran.get("output") or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out["line"] = (lines[-1] if lines else "")[:500]
    cases = ran.get("report") or []
    if ran.get("timed_out"):
        out["class"] = "driver_error"
        return out
    if ran.get("app_down"):
        out["class"] = "app_not_running"
        return out
    if not cases:
        hit = next((ln for ln in lines if APP_DOWN.search(ln)), None)
        if hit:
            out.update({"class": "app_not_running", "line": hit[:500]})
        elif ran.get("exit_code") in (126, 127) or next((ln for ln in lines if DRIVER_DOWN.search(ln)), None):
            hit = next((ln for ln in lines if DRIVER_DOWN.search(ln)), out["line"])
            out.update({"class": "driver_error", "line": hit[:500]})
        else:
            out["class"] = "unknown"
        return out
    seen, dupes = {}, []
    for name, status, message in cases:
        sid = name.split(".", 1)[-1] if "." in name and name not in ids else name
        if sid in seen and sid not in dupes:
            dupes.append(sid)
        seen[sid] = (status, message or "")
    thens, setups, errors = [], [], []
    for sid in ids:
        if sid not in seen:
            out["missing"].append(sid)
            continue
        status, message = seen[sid]
        step = _step(message)
        word = effective_step(message, (steps or {}).get(sid))
        row = {"id": sid, "status": status, "step": step, "message": message[:500]}
        if sid in dupes:
            row["message"] = f"duplicate result for scenario {sid}"
            errors.append(sid)
            out["results"].append(row)
            out["failing"].append(sid)
            continue
        out["results"].append(row)
        if status == "pass":
            out["passing"].append(sid)
        elif status == "skipped":
            out["skipped"].append(sid)
        elif status == "error" or not step:
            errors.append(sid)
        elif word == "Then":
            thens.append(sid)
        elif word in ("Given", "When", "And", "But", "*"):
            setups.append(sid)  # And and But that cannot be placed count as setup: a Red is never accepted on a guess
        else:
            errors.append(sid)
        if status in ("failure", "error"):
            out["failing"].append(sid)
    out["extra"] = [s for s in seen if s not in ids]
    first = next((r for r in out["results"] if r["id"] in errors + setups + thens), None)
    if first:
        out["line"] = first["message"] or out["line"]
    if errors:
        out["class"] = "script_error"
    elif out["missing"] or out["extra"] or out["skipped"]:
        out["class"] = "unbound_scenario"
    elif setups:
        out["class"] = "setup_failure"
    elif thens and out["passing"]:
        out["class"] = "partial_pass"
    elif thens:
        out["class"] = "assertion"
    else:
        out["class"] = "pass"
    return out
