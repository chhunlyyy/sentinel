#!/usr/bin/env python3
"""Sentinel 1.3.0 release gate (release.feature, AC-TST-01k to AC-TST-04b).

    python3 tools/release_gate.py [--evidence FILE] [--wheel-env DIR] [--skip-dashboard] [--skip-wheel] [--allow-dirty]
    python3 tools/release_gate.py wheel-env DIR      build the release wheel and install it offline into DIR

The gate runs, in order: the phase set hashes, the dashboard npm scripts (lint, typecheck, build, vitest, playwright),
the release wheel and its offline install, the selftest, the unittest suite (with `-W default`) and the security suite;
then it checks that every AC id of phases A to I appears in the name of a passing test (or is recorded as manual with
evidence), that the 23 mandatory scenarios of SPEC_CORE section 14 and the 20 dashboard criteria are accounted for,
and writes the evidence file. It exits 1 and names the AC id when anything is missing. It never tags, publishes or pushes.

It refuses a dirty tree. `--allow-dirty` runs everything but can never report "release ready": the status is then "not releasable:
dirty tree". On a clean tree "release ready" needs every item of tests/release/manual.json to have `status: done` with a date and a
machine; otherwise the gate prints "release candidate: N manual checks pending owner" and lists them.
"""
import atexit
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.3.0"
PHASES = ["phaseA", "phaseB", "phaseC", "phaseD", "phaseE", "phaseF", "phaseG", "phaseH", "phaseI", "phaseJ"]
ID_RE = re.compile(r"AC[-_]([A-Z]+)[-_](\d+)([a-z]+)(?![A-Za-z0-9])")
FEATURE_ID_RE = re.compile(r"@(AC-[A-Z]+-\d+[a-z]+)\b")


# ---------------------------------------------------------------- approved acceptance criteria and phase hashes
def approved_ac_ids(root=ROOT):
    """{AC id: feature file} of every plan/v1.1/phase*/features/*.feature."""
    ids = {}
    for f in sorted(Path(root).glob("plan/v1.1/phase*/features/*.feature")):
        for m in FEATURE_ID_RE.finditer(f.read_text(encoding="utf-8")):
            ids.setdefault(m.group(1), str(f.relative_to(root)))
    return ids


def ids_in_name(name):
    """The AC ids a test name carries: `test_AC_SEC_01l_x`, `AC-DSH-01e title`."""
    return {f"AC-{m.group(1)}-{m.group(2)}{m.group(3)}" for m in ID_RE.finditer(name)}


def set_hash(features_dir):
    """The set hash of a phase: the documented `find | sort | cat` command, in Python."""
    features_dir = Path(features_dir)
    files = sorted(("features/" + p.relative_to(features_dir).as_posix(), p) for p in features_dir.rglob("*.feature"))
    h = hashlib.sha256()
    for rel, p in sorted(files, key=lambda x: x[0].encode()):
        h.update(rel.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def recorded_hashes(status_text):
    out = {}
    for m in re.finditer(r"\|\s*P([A-J])-00\s*\|[^\n]*?hash `([0-9a-f]{64})`", status_text):
        out[f"phase{m.group(1)}"] = m.group(2)
    return out


def phase_hash_problems(root=ROOT, phases=None):
    """The Gherkin set hash of each phase against two recorded sources that must agree: IMPLEMENTATION_STATUS.md and
    tests/release/phase_hashes.json."""
    root = Path(root)
    recorded = recorded_hashes((root / "IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8"))
    pinned_file = root / "tests" / "release" / "phase_hashes.json"
    pinned = json.loads(pinned_file.read_text(encoding="utf-8")) if pinned_file.exists() else {}
    problems = []
    for phase in phases or PHASES:
        want = recorded.get(phase)
        if pinned.get(phase) != want:
            problems.append(f"{phase}: IMPLEMENTATION_STATUS.md records {want} and tests/release/phase_hashes.json pins {pinned.get(phase)}; they must agree")
            continue
        have = set_hash(root / "plan" / "v1.1" / phase / "features") if (root / "plan" / "v1.1" / phase / "features").is_dir() else None
        if not want:
            problems.append(f"{phase}: no approved hash recorded in IMPLEMENTATION_STATUS.md")
        elif have != want:
            problems.append(f"{phase}: the Gherkin set hash is {have}, the approved hash is {want}")
    return problems


# ---------------------------------------------------------------- manual items
def normalize_manual(raw):
    """{key: {"evidence", "status", "date", "machine"}}. A plain string is evidence of a check still pending. An item is
    `done` only when its status says so and it records a date and a machine; anything else is pending the owner."""
    out = {}
    for key, v in (raw or {}).items():
        v = {"evidence": v} if isinstance(v, str) else dict(v or {})
        done = v.get("status") == "done" and bool(v.get("date")) and bool(v.get("machine"))
        out[key] = {"evidence": v.get("evidence") or "", "status": "done" if done else "pending", "date": v.get("date"), "machine": v.get("machine")}
    return out


def pending_manual(manual, results=()):
    """The manual items the owner still has to do. An AC item that a passing test now carries (no failed or skipped test) is
    satisfied by that test."""
    by = {}
    for r in results:
        for i in ids_in_name(r["name"]):
            by.setdefault(i, []).append(r["status"])
    out = []
    for key, v in sorted(normalize_manual(manual).items()):
        states = by.get(key, [])
        if v["status"] == "done" or ("passed" in states and "skipped" not in states and "failed" not in states):
            continue
        out.append({"id": key, "evidence": v["evidence"]})
    return out


def final_status(ok, pending, dirty):
    """(status text, release_ready). Only a clean tree with no problem and no pending manual item is ready."""
    if not ok:
        return "not ready", False
    if dirty:
        return "not releasable: dirty tree", False
    if pending:
        return f"release candidate: {len(pending)} manual checks pending owner", False
    return "release ready", True


def tree_check(dirty, allow_dirty):
    """(proceed, message). A dirty tree is refused unless --allow-dirty, which only lets the gate run."""
    if not dirty:
        return True, None
    if allow_dirty:
        return True, "dirty tree: running because of --allow-dirty; the result is never releasable"
    return False, "refusing to run on a dirty tree (git status shows changes); commit or stash them, or pass --allow-dirty (the result is then never releasable)"


# ---------------------------------------------------------------- AC to test check
def ac_problems(ids, results, manual):
    """(problems, covered). Each AC id needs a test whose name carries it and that passed; a skipped or failed test
    that carries the id is a problem. `manual` maps an id to the recorded evidence that stands in for a test."""
    manual = {k: v["evidence"] for k, v in normalize_manual(manual).items()}
    by = {}
    for r in results:
        for i in ids_in_name(r["name"]):
            by.setdefault(i, []).append(r)
    problems, covered = [], {}
    for i in sorted(ids):
        rs = by.get(i, [])
        failed = [r for r in rs if r["status"] == "failed"]
        skipped = [r for r in rs if r["status"] == "skipped"]
        passed = [r for r in rs if r["status"] == "passed"]
        evidence = manual.get(i)
        if failed:
            problems.append({"id": i, "reason": f"a test that carries it failed: {failed[0]['name']}" + (f" ({failed[0]['reason']})" if failed[0].get("reason") else "")})
        elif skipped and not (evidence and not passed):
            problems.append({"id": i, "reason": f"a test that carries it was skipped ({skipped[0].get('reason') or 'no reason'}): {skipped[0]['name']}"})
        elif passed:
            covered[i] = {"tests": len(passed)}
        elif evidence:
            covered[i] = {"manual": evidence, "tests": 0}
        elif i in manual:
            problems.append({"id": i, "reason": "marked manual without recorded evidence"})
        else:
            problems.append({"id": i, "reason": "no test name carries this id"})
    return problems, covered


def _ac_state(ids, results):
    by = {}
    for r in results:
        for i in ids_in_name(r["name"]):
            by.setdefault(i, []).append(r["status"])
    bad = [i for i in ids if "failed" in by.get(i, []) or "skipped" in by.get(i, []) or "passed" not in by.get(i, [])]
    return not bad, bad


def core_problems(core, results):
    problems = []
    for name, ids in core["scenarios"].items():
        ok, bad = _ac_state(ids, results)
        if not ids or not ok:
            problems.append({"id": name, "reason": "no passing test for " + ", ".join(bad or ["(no AC id mapped)"])})
    return problems


def dashboard_problems(data, results):
    problems, listing = [], []
    for c in data["criteria"]:
        row = {"n": c["n"], "text": c["text"], "status": c["status"]}
        if c["status"] == "automated":
            ok, bad = _ac_state(c.get("acs", []), results)
            row.update(acs=c.get("acs", []), passed=bool(c.get("acs")) and ok)
            if not row["passed"]:
                problems.append({"id": f"criterion {c['n']}", "reason": "no passing test for " + ", ".join(bad or ["(no AC id mapped)"])})
        elif c["status"] == "manual":
            row.update(evidence=c.get("evidence"), passed=bool(c.get("evidence")))
            if not row["passed"]:
                problems.append({"id": f"criterion {c['n']}", "reason": "manual without recorded evidence"})
        elif c["status"] == "LATER":
            row.update(reference=c.get("reference"), passed="G-1" in (c.get("reference") or ""))
            if not row["passed"]:
                problems.append({"id": f"criterion {c['n']}", "reason": "LATER without the G-1 reference"})
        else:
            problems.append({"id": f"criterion {c['n']}", "reason": f"unknown status {c['status']}"})
        listing.append(row)
    return problems, listing


# ---------------------------------------------------------------- SPEC.md MUST rows (AC-OPS-04l)
REQ_RE = re.compile(r"(?<![A-Za-z0-9])REQ[_-]([A-Z]+)[_-](\d+)(?![A-Za-z0-9])")


def req_ids_in_name(name):
    """The requirement ids a test name carries: `test_AC_X_01a_REQ_ARC_01_x`, `AC-PRJ-02a REQ-PRJ-01 title`. The family and
    the number must match exactly (REQ_ARC_01 is not REQ_ARC_010)."""
    return {f"{m.group(1)}-{m.group(2)}" for m in REQ_RE.finditer(name)}


def spec_rows(root=ROOT):
    rows, section = {}, None
    for line in (Path(root) / "SPEC.md").read_text(encoding="utf-8").splitlines():
        h = re.match(r"#{2,3}\s+(.*)", line)
        if h:
            section = h.group(1).strip()
        m = re.match(r"\|\s*([A-Z]+-\d+)\s*\|(.*)\|\s*$", line)
        if m:
            rows[m.group(1)] = (section, m.group(2).strip())
    return rows


def req_problems(root, results):
    """(problems, used). A MUST row of SPEC.md is met when an approved scenario carries its id, when a passing test (any
    suite) names it with REQ_<ID>, or when it is marked LATER with a G-1 or decision reference."""
    root = Path(root)
    tagged = set()
    for f in root.glob("plan/v1.1/phase*/features/*.feature"):
        text = f.read_text(encoding="utf-8")
        tagged.update(re.findall(r"@REQ-([A-Z]+-\d+)\b", text))
        tagged.update(re.findall(r"@AC-([A-Z]+-\d+)[a-z]+\b", text))
    named = set()
    for r in results:
        if r["status"] == "passed":
            named |= req_ids_in_name(r["name"])
    problems, used = [], []
    for rid, (_sec, text) in sorted(spec_rows(root).items()):
        if "MUST" not in text.split("|")[0]:
            continue
        if rid in named:
            used.append(f"{rid} tested")
        elif rid in tagged:
            used.append(f"{rid} scenario")
        elif "LATER" in text and re.search(r"G-1|decision", text):
            used.append(f"{rid} LATER")
        else:
            problems.append({"id": rid, "reason": "MUST row with no passing REQ_ test, no scenario and no LATER mark with a reference"})
    return problems, used


# ---------------------------------------------------------------- reading suite results
def parse_selftest(text):
    names = {}
    for m in re.finditer(r"^  (PASS|FAIL)  (.*?)(?:  \(.*\))?$", text, re.M):
        names[m.group(2)] = m.group(1) == "PASS"
    s = re.search(r"(\d+) passed, (\d+) failed", text)
    return {"passed": int(s.group(1)) if s else 0, "failed": int(s.group(2)) if s else -1, "names": names}


def selftest_problems(parsed, baseline, superseded=None):
    problems = [f"selftest failed: {n}" for n, ok in parsed["names"].items() if not ok]
    if parsed["failed"] != 0 and not problems:
        problems.append("selftest did not report 0 failed")
    for name in baseline:
        if name in parsed["names"]:
            continue
        new = (superseded or {}).get(name)
        if new and new in parsed["names"]:
            continue
        problems.append(f"selftest baseline check missing: {name}")
    return problems


class _Result(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows = {}

    def _set(self, test, status, reason=None):
        row = self.rows.setdefault(test.id(), {"suite": "unittest", "name": test.id(), "status": status})
        if status == "failed" or row["status"] == "passed":
            row["status"] = status
        if reason and not row.get("reason"):
            row["reason"] = reason

    def addSuccess(self, test):
        self._set(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._set(test, "failed", str(err[1])[:600])

    def addError(self, test, err):
        super().addError(test, err)
        self._set(test, "failed", f"{type(err[1]).__name__}: {err[1]}"[:600])

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._set(test, "skipped", reason)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._set(test, "failed", f"subtest {subtest._subDescription()}: {err[1]}"[:200])

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._set(test, "skipped", "expected failure")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._set(test, "failed", "unexpected success")


def collect_unittest(start, top=None):
    """Run `unittest discover -s start` in this process. {results, ran, leaked}."""
    suite = unittest.defaultTestLoader.discover(str(start), top_level_dir=str(top or start))
    result = _Result()
    suite.run(result)
    return {"results": list(result.rows.values()), "ran": result.testsRun, "leaked": child_processes()}


def child_processes():
    me, out = os.getpid(), []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            stat = (p / "stat").read_text()
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
            state = stat.rsplit(")", 1)[1].split()[0]
            cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            if ppid == me and state != "Z" and "multiprocessing.resource_tracker" not in cmd:  # the interpreter's own helper
                out.append(f"{p.name}: {cmd[:100]}")
        except (OSError, ValueError, IndexError):
            continue
    return out


def read_vitest(report):
    rows = []
    for f in report.get("testResults", []):
        for t in f.get("assertionResults", []):
            status = {"passed": "passed", "failed": "failed"}.get(t.get("status"), "skipped")
            rows.append({"suite": "vitest", "name": t.get("fullName") or t.get("title", ""), "status": status})
    return rows


def read_playwright(report):
    rows = []

    def walk(suite):
        for spec in suite.get("specs", []):
            tests = spec.get("tests", [])
            states = [t.get("status") for t in tests]
            annotated_fail = any(t.get("expectedStatus") == "failed" or any(a.get("type") == "fail" for a in t.get("annotations", [])) for t in tests)
            if any(s in ("unexpected", "flaky") for s in states):
                status = "failed"
            elif not tests or all(s == "skipped" for s in states) or annotated_fail:
                status = "skipped"  # an empty spec or a test marked test.fail proves nothing
            else:
                status = "passed"
            rows.append({"suite": "playwright", "name": spec.get("title", ""), "status": status})
        for s in suite.get("suites", []):
            walk(s)

    for s in report.get("suites", []):
        walk(s)
    return rows


# ---------------------------------------------------------------- evidence and decision
def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def new_evidence():
    return {"version": (ROOT / "sentinel" / "VERSION").read_text().strip(), "commit": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain")), "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "stages": {}}


def record_stage(evidence, name, ok, seconds, counts=None, notes=None):
    evidence["stages"][name] = {"ok": ok, "seconds": round(seconds, 1), "counts": counts or {}, "notes": notes or []}


def decide(problems_by_stage):
    lines = []
    for stage, items in problems_by_stage.items():
        for p in items:
            lines.append(f"{stage}: {p['id']}: {p['reason']}" if isinstance(p, dict) else f"{stage}: {p}")
    return (not lines), lines


def exit_code(ok):
    return 0 if ok else 1


def write_evidence(path, evidence, ok, pending=(), allow_dirty=False):
    status, ready = final_status(ok, list(pending), bool(evidence.get("dirty")))
    evidence = {**evidence, "release_ready": ready, "status": status, "pending_owner": list(pending), "allow_dirty": bool(allow_dirty)}
    Path(path).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- wheel build and offline install
def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def namespaces_allowed():
    return shutil.which("unshare") is not None and run(["unshare", "-rn", "true"]).returncode == 0


def create_buildenv(base):
    venv = Path(base) / "buildenv"
    if not (venv / "bin" / "hatchling").exists():
        r = run([sys.executable, "-m", "venv", str(venv)])
        if r.returncode:
            raise RuntimeError("venv failed: " + r.stderr)
        r = run([str(venv / "bin" / "pip"), "install", "--quiet", "hatchling>=1.25"])
        if r.returncode:
            raise RuntimeError("could not install hatchling: " + r.stdout + r.stderr)
    return venv


def copy_build_tree(dst, with_dist=True):
    """The files a wheel build reads, in a scratch folder."""
    dst = Path(dst)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", *([] if with_dist else ["dashboard_dist"]))
    shutil.copytree(ROOT / "sentinel", dst / "sentinel", ignore=ignore)
    shutil.copytree(ROOT / "skills", dst / "skills", ignore=ignore)
    for name in ("pyproject.toml", "hatch_build.py", "README.md", "LICENSE"):
        shutil.copy2(ROOT / name, dst / name)
    (dst / "dashboard").mkdir()
    shutil.copytree(ROOT / "dashboard" / "src", dst / "dashboard" / "src")
    for name in ("index.html", "package.json", "package-lock.json", "vite.config.ts", "vitest.config.ts", "eslint.config.js", "tsconfig.json"):
        shutil.copy2(ROOT / "dashboard" / name, dst / "dashboard" / name)
    return dst


def try_build_wheel(buildenv, tree, outdir, release):
    env = {k: v for k, v in os.environ.items() if k != "SENTINEL_RELEASE"}
    if release:
        env["SENTINEL_RELEASE"] = "1"
    return run([str(Path(buildenv) / "bin" / "hatchling"), "build", "-t", "wheel", "-d", str(outdir)], cwd=tree, env=env)


def build_wheel(buildenv, tree, outdir, release):
    r = try_build_wheel(buildenv, tree, outdir, release)
    if r.returncode:
        raise RuntimeError("wheel build failed: " + r.stdout + r.stderr)
    wheels = sorted(Path(outdir).glob("sentinel_pipeline-*.whl"))
    if not wheels:
        raise RuntimeError("no wheel was built: " + r.stdout)
    return wheels[-1]


class WheelEnv:
    def __init__(self, base):
        base = Path(base)
        self.base = base
        self.buildenv = base / "buildenv"
        self.wheelhouse = base / "wheelhouse"
        self.venv = base / "venv"
        self.wheel = sorted(self.wheelhouse.glob("sentinel_pipeline-*.whl"))[-1]
        ready = json.loads((base / "ready.json").read_text()) if (base / "ready.json").exists() else {}
        self.sentinel = Path(ready.get("sentinel") or self.venv / "bin" / "sentinel")
        root = Path(ready["tool_dir"]) if ready.get("tool_dir") else self.venv
        self.site_packages = next((root / "lib").glob("python*/site-packages"))
        self.installer = ready.get("installer", "pip")
        self.offline_install_log = base / "offline-install.log"


def prepare_wheel_env(base, release=True):
    """Build the wheel from the checkout (SENTINEL_RELEASE=1 needs `npm run build` done), fill a wheelhouse with it
    and the wheels of its dependencies, and install it into a fresh venv with --no-index (in a network namespace with
    only loopback when the machine allows it). Writes BASE/ready.json."""
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    buildenv = create_buildenv(base)
    wheelhouse = base / "wheelhouse"
    shutil.rmtree(wheelhouse, ignore_errors=True)
    wheelhouse.mkdir()
    build_wheel(buildenv, ROOT, wheelhouse, release)
    r = run([str(buildenv / "bin" / "pip"), "download", "--quiet", "--only-binary=:all:", "-d", str(wheelhouse), "pyyaml>=6", "jsonschema>=4"])
    if r.returncode:
        raise RuntimeError("could not fill the wheelhouse: " + r.stdout + r.stderr)
    venv = base / "venv"
    shutil.rmtree(venv, ignore_errors=True)
    ns = namespaces_allowed()
    wrap = ["unshare", "-rn", "sh", "-c", 'ip link set lo up 2>/dev/null; exec "$@"', "sh"] if ns else []
    log, installer, ready = [], None, {}
    uv = shutil.which("uv")
    if uv:  # the documented install path first: `uv tool install` from the wheelhouse, offline
        tools, tbin = base / "uvtools", base / "uvbin"
        shutil.rmtree(tools, ignore_errors=True)
        shutil.rmtree(tbin, ignore_errors=True)
        uv_env = {**os.environ, "UV_TOOL_DIR": str(tools), "UV_TOOL_BIN_DIR": str(tbin), "UV_CACHE_DIR": str(base / "uvcache"), "UV_PYTHON_PREFERENCE": "system", "UV_OFFLINE": "1"}
        cmd = [uv, "tool", "install", "--offline", "--no-index", "--find-links", str(wheelhouse), "sentinel-pipeline"]
        r = run(wrap + cmd, env=uv_env)
        log.append(" ".join(cmd) + f"\nnetwork namespace: {'yes' if ns else 'no (user namespaces are not allowed here)'}\n" + r.stdout + r.stderr)
        if r.returncode == 0 and (tbin / "sentinel").exists():
            installer = "uv tool install"
            ready = {"sentinel": str(tbin / "sentinel"), "tool_dir": str(tools / "sentinel-pipeline")}
        else:
            log.append("uv tool install failed offline; falling back to pip\n")
    if installer is None:
        r = run([sys.executable, "-m", "venv", str(venv)])
        if r.returncode:
            raise RuntimeError("venv failed: " + r.stderr)
        cmd = [str(venv / "bin" / "pip"), "install", "--no-index", "--find-links", str(wheelhouse), "sentinel-pipeline"]
        r = run(wrap + cmd)
        log.insert(0, " ".join(cmd) + f"\nnetwork namespace: {'yes' if ns else 'no (user namespaces are not allowed here)'}\n" + r.stdout + r.stderr)
        installer = "pip" + (" (uv is not installed)" if not uv else " (uv tool install did not work offline from the wheelhouse)")
        ready = {"sentinel": str(venv / "bin" / "sentinel")}
        if r.returncode:
            (base / "offline-install.log").write_text("\n".join(log))
            raise RuntimeError("offline install failed: " + r.stdout + r.stderr)
    (base / "offline-install.log").write_text(f"installer: {installer}\n" + "\n".join(log))
    ready.update(wheel=str(sorted(wheelhouse.glob("sentinel_pipeline-*.whl"))[-1]), namespace=ns, installer=installer)
    (base / "ready.json").write_text(json.dumps(ready))
    return WheelEnv(base)


_ENV = []


def wheel_env():
    """The shared wheel environment: SENTINEL_WHEEL_ENV, or one built once into a temp folder for this process."""
    if _ENV:
        return _ENV[0]
    given = os.environ.get("SENTINEL_WHEEL_ENV")
    if given and (Path(given) / "ready.json").exists():
        _ENV.append(WheelEnv(given))
        return _ENV[0]
    base = Path(given) if given else Path(tempfile.mkdtemp(prefix="sentinel-wheel-env-"))
    if not given:
        atexit.register(shutil.rmtree, base, True)
    if not (ROOT / "sentinel" / "dashboard_dist" / "index.html").exists():
        run(["npm", "run", "build"], cwd=ROOT / "dashboard")
    _ENV.append(prepare_wheel_env(base))
    return _ENV[0]


def legacy_cli(dest):
    """sentinel.py of the 0.1.0b7 release, from the git tag."""
    dest = Path(dest)
    cli = dest / "sentinel" / "scripts" / "sentinel.py"
    if not cli.exists():
        dest.mkdir(parents=True, exist_ok=True)
        archive = subprocess.run(["git", "archive", "v0.1.0b7"], cwd=ROOT, capture_output=True)
        if archive.returncode:
            raise RuntimeError("tag v0.1.0b7 is not available: " + archive.stderr.decode())
        subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True)
    return cli


# ---------------------------------------------------------------- the gate
def timed(fn):
    t = time.time()
    value = fn()
    return value, time.time() - t


def npm(*args, env=None):
    return subprocess.run(["npm", *args], cwd=ROOT / "dashboard", capture_output=True, text=True, env={**os.environ, **(env or {})})


def stage_dashboard_build(evidence, problems):
    for name in ("lint", "typecheck", "build"):
        r, secs = timed(lambda n=name: npm("run", n))
        record_stage(evidence, f"npm {name}", r.returncode == 0, secs)
        if r.returncode:
            problems[f"npm {name}"] = [(r.stdout + r.stderr)[-600:]]


def stage_dashboard_tests(evidence, results, problems, tmp, env):
    out = tmp / "vitest.json"
    r, secs = timed(lambda: npm("exec", "--", "vitest", "run", "--reporter=json", f"--outputFile={out}"))
    rows = read_vitest(json.loads(out.read_text())) if out.exists() else []
    results.extend(rows)
    counts = {s: sum(1 for x in rows if x["status"] == s) for s in ("passed", "failed", "skipped")}
    record_stage(evidence, "vitest", r.returncode == 0, secs, counts)
    if r.returncode:
        problems["vitest"] = [f"{counts['failed']} failed"]
    out = tmp / "playwright.json"
    r, secs = timed(lambda: npm("exec", "--", "playwright", "test", "--reporter=json", env={"PLAYWRIGHT_JSON_OUTPUT_NAME": str(out), **env}))
    rows = read_playwright(json.loads(out.read_text())) if out.exists() else []
    results.extend(rows)
    counts = {s: sum(1 for x in rows if x["status"] == s) for s in ("passed", "failed", "skipped")}
    record_stage(evidence, "playwright", r.returncode == 0, secs, counts)
    if r.returncode:
        problems["playwright"] = [f"{counts['failed']} failed (exit {r.returncode})"]


def stage_unittest(name, start, top, evidence, results, problems, env, tmp):
    out = tmp / f"{name}.json"
    cmd = [sys.executable, "-W", "default", str(Path(__file__).resolve()), "worker-unittest", str(start), str(top), str(out)]
    r, secs = timed(lambda: subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env={**os.environ, **env}))
    if not out.exists():
        record_stage(evidence, name, False, secs)
        problems[name] = ["the unittest worker produced no result: " + (r.stderr or r.stdout)[-500:]]
        return
    data = json.loads(out.read_text())
    results.extend(data["results"])
    counts = {s: sum(1 for x in data["results"] if x["status"] == s) for s in ("passed", "failed", "skipped")}
    warns = len(re.findall(r"ResourceWarning", r.stderr))
    counts.update(ran=data["ran"], resource_warnings=warns, leaked_processes=len(data["leaked"]))
    failed_rows = [x for x in data["results"] if x["status"] == "failed"]
    bad = [x["name"] for x in failed_rows]
    notes = []
    if bad:
        notes.append(f"{len(bad)} failed: " + ", ".join(bad[:5]))
        for x in failed_rows[:5]:  # the reason is what makes a failure on a remote runner debuggable
            notes.append(f"  {x['name']}: {(x.get('reason') or 'no reason recorded').replace(chr(10), ' ')[:400]}")
    if warns:
        notes.append(f"{warns} ResourceWarning lines")
    if data["leaked"]:
        notes.append("leaked processes: " + "; ".join(data["leaked"][:3]))
    record_stage(evidence, name, not notes, secs, counts, notes)
    if notes:
        problems[name] = notes


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["worker-unittest"]:
        start, top, out = argv[1:4]
        sys.path.insert(0, str(top))
        Path(out).write_text(json.dumps(collect_unittest(Path(start), Path(top))))
        return 0
    if argv[:1] == ["wheel-env"]:
        env = prepare_wheel_env(argv[1])
        print(f"wheel {env.wheel}\ninstalled {env.sentinel}")
        return 0
    opts = {"evidence": ROOT / "release-evidence.json", "wheel_env": None, "dashboard": True, "wheel": True, "allow_dirty": False}
    it = iter(argv)
    for a in it:
        if a == "--evidence":
            opts["evidence"] = Path(next(it))
        elif a == "--wheel-env":
            opts["wheel_env"] = Path(next(it))
        elif a == "--skip-dashboard":
            opts["dashboard"] = False
        elif a == "--skip-wheel":
            opts["wheel"] = False
        elif a == "--allow-dirty":
            opts["allow_dirty"] = True
        else:
            print(f"unknown argument {a}", file=sys.stderr)
            return 2
    evidence, results, problems = new_evidence(), [], {}
    proceed, message = tree_check(evidence["dirty"], opts["allow_dirty"])
    if message:
        print(message, file=sys.stderr if not proceed else sys.stdout)
    if not proceed:
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="release-gate-"))
    atexit.register(shutil.rmtree, tmp, True)
    print("release gate", evidence["version"], evidence["commit"][:12])

    ph = phase_hash_problems(ROOT)
    record_stage(evidence, "phase hashes", not ph, 0, {"phases": len(PHASES)})
    if ph:
        problems["phase hashes"] = ph
    if evidence["version"] != VERSION:
        problems["version"] = [f"sentinel/VERSION is {evidence['version']}, expected {VERSION}"]
    print("phase hashes:", "ok" if not ph else "FAILED")

    if opts["dashboard"]:
        stage_dashboard_build(evidence, problems)
        print("dashboard lint, typecheck and build done")
    env = {}
    if opts["wheel"]:
        try:
            base = opts["wheel_env"] or tmp / "wheel-env"
            we, secs = timed(lambda: prepare_wheel_env(base))
            env["SENTINEL_WHEEL_ENV"] = str(base)
            record_stage(evidence, "wheel", True, secs, {"wheel": we.wheel.name}, [l for l in (base / "offline-install.log").read_text().splitlines() if l.startswith(("installer:", "network namespace:"))])
        except Exception as e:  # noqa: BLE001
            record_stage(evidence, "wheel", False, 0)
            problems["wheel"] = [str(e)[-600:]]
        print("wheel done")
    if opts["dashboard"]:
        stage_dashboard_tests(evidence, results, problems, tmp, env)
        print("vitest and playwright done")

    r, secs = timed(lambda: run([sys.executable, str(ROOT / "sentinel" / "scripts" / "selftest.py")]))
    parsed = parse_selftest(r.stdout + r.stderr)
    baseline = json.loads((ROOT / "tests" / "release" / "selftest_baseline.json").read_text())
    sp = selftest_problems(parsed, baseline["checks"], baseline.get("superseded", {}))
    record_stage(evidence, "selftest", not sp and r.returncode == 0, secs, {"passed": parsed["passed"], "failed": parsed["failed"], "baseline_checks": len(baseline["checks"])})
    results.extend({"suite": "selftest", "name": n, "status": "passed" if ok else "failed"} for n, ok in parsed["names"].items())
    if sp or r.returncode:
        problems["selftest"] = sp or ["selftest exited " + str(r.returncode)]
    print(f"selftest: {parsed['passed']} passed, {parsed['failed']} failed")

    stage_unittest("unittest", ROOT / "tests", ROOT / "tests", evidence, results, problems, env, tmp)
    stage_unittest("security suite", ROOT / "tests" / "security", ROOT / "tests" / "security", evidence, results, problems, env, tmp)
    print("unittest and security suite done")

    ids = approved_ac_ids(ROOT)
    manual = normalize_manual(json.loads((ROOT / "tests" / "release" / "manual.json").read_text()))
    ap, covered = ac_problems(ids, results, manual)
    pending = pending_manual(manual, results)
    record_stage(evidence, "ac to test", not ap, 0, {"approved_ids": len(ids), "covered": len(covered), "manual": sum(1 for c in covered.values() if c.get("manual"))})
    evidence["manual"] = {k: v for k, v in manual.items()}
    if ap:
        problems["ac to test"] = ap
    rp, used = req_problems(ROOT, results)
    record_stage(evidence, "requirements", not rp, 0, {"must_rows_met": len(used)})
    if rp:
        problems["requirements"] = rp
    core = json.loads((ROOT / "tests" / "release" / "core14.json").read_text())
    cp = core_problems(core, results)
    record_stage(evidence, "core scenarios", not cp, 0, {"scenarios": len(core["scenarios"])})
    if cp:
        problems["core scenarios"] = cp
    dash = json.loads((ROOT / "tests" / "release" / "dashboard22.json").read_text())
    dp, listing = dashboard_problems(dash, results)
    evidence["dashboard_criteria"] = listing
    record_stage(evidence, "dashboard criteria", not dp, 0, {"criteria": len(listing)})
    if dp:
        problems["dashboard criteria"] = dp

    ok, lines = decide(problems)
    write_evidence(opts["evidence"], evidence, ok, pending, opts["allow_dirty"])
    for line in lines[:60]:
        print("  " + line)
    if pending:
        print(f"\nPENDING OWNER: {len(pending)} manual checks are not evidence yet (tests/release/manual.json)")
        for item in pending:
            print(f"  PENDING OWNER  {item['id']}: {item['evidence']}")
        print()
    status, _ready = final_status(ok, pending, evidence["dirty"])
    print(status if ok else f"NOT READY ({len(lines)} problems); evidence: {opts['evidence']}")
    return exit_code(ok)


if __name__ == "__main__":
    sys.exit(main())
