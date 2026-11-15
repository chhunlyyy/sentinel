"""Failure classifier for engine-run test commands (TDD-03, VER-02). Pure: no I/O besides reading a report file.

A test run is judged from three signals: the output text (profile `failure_patterns`), the structured report
(`test_report`, JUnit XML) and the exit code. Order of precedence (Phase D open point 4): compile, missing_dependency,
environment, then the report. Classes: assertion, compile, missing_dependency, environment, preexisting_failure,
unknown, pass (no failing test and exit 0).
Source: plan/v1.1/phaseD/README.md points 3 to 5, docs/contracts/configuration-schemas.md.
"""
import glob
import os
import re
import xml.etree.ElementTree as ET

CLASSES = ("assertion", "compile", "missing_dependency", "environment", "preexisting_failure", "unknown", "pass")
PATTERN_ORDER = ("compile", "missing_dependency", "environment")
RETRY_CLASSES = ("compile", "missing_dependency", "environment", "preexisting_failure")  # Red is retried for these


def _match(pattern, text):
    try:
        found = re.search(pattern, text)
    except re.error:
        found = None
    return found or (pattern in text)


def matches(klass, output, patterns):
    """True when any pattern of `klass` (regex, or plain text when it is not a valid regex) occurs in `output`."""
    return any(_match(p, output) for p in (patterns or {}).get(klass) or ())


def output_line(klass, output, patterns):
    """The first output line that shows why a run got `klass`: a matching line, else the last non-empty line."""
    lines = [line.rstrip() for line in (output or "").splitlines() if line.strip()]
    for line in lines:
        if any(_match(p, line) for p in (patterns or {}).get(klass) or ()):
            return line[:500]
    return lines[-1][:500] if lines else ""


def _test_class(classname):
    """The class part of a test id: the last segment of a class name, or the file name without extensions when the runner
    reports a file path (jest-junit `{filename}`, flutter)."""
    if "/" in classname:
        return classname.rsplit("/", 1)[-1].split(".", 1)[0]
    return classname.rsplit(".", 1)[-1]


def parse_junit_cases(text):
    """[(test id, status, message)] from JUnit XML, status in pass, failure, error, skipped; message is the text of the
    failure or error element (empty otherwise). None when it is not XML. A test id is `<class>.<name>`."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    cases = []
    for case in root.iter("testcase"):
        klass = _test_class(case.get("classname") or "")
        name = case.get("name") or ""
        status, node = "pass", None
        for tag, st in (("failure", "failure"), ("error", "error"), ("skipped", "skipped")):
            node = case.find(tag)
            if node is not None:
                status = st
                break
        message = ""
        if status in ("failure", "error"):
            message = "\n".join(x for x in ((node.get("message") or "").strip(), (node.text or "").strip()) if x)
        cases.append((f"{klass}.{name}" if klass else name, status, message))
    return cases


def parse_junit(text):
    """[(test id, status)] from JUnit XML, or None when it is not XML."""
    cases = parse_junit_cases(text)
    return None if cases is None else [(t, st) for t, st, _ in cases]


REPORT_DIR = "{report_dir}"


def _target(repo_path, report, report_dir=None):
    """(base directory, glob) of a test_report, or (None, None). A path starting with `{report_dir}` is read from the
    engine-owned directory; any other path is repo-relative. Absolute paths and `..` are refused."""
    pattern = (report or {}).get("path")
    if not isinstance(pattern, str) or not pattern:
        return None, None
    base = repo_path
    if pattern.startswith(REPORT_DIR):
        base, pattern = report_dir, pattern[len(REPORT_DIR):].lstrip("/")
    if not base or not pattern or os.path.isabs(pattern) or ".." in pattern.replace("\\", "/").split("/"):
        return None, None
    return str(base), pattern


def report_files(repo_path, report, report_dir=None):
    """Files a test_report glob matches under its base directory (real paths inside it; a link out of it is dropped)."""
    base, pattern = _target(repo_path, report, report_dir)
    if base is None:
        return []
    root = os.path.realpath(base)
    found = []
    for path in sorted(glob.glob(os.path.join(root, pattern), recursive=True)):
        real = os.path.realpath(path)
        if real.startswith(root + os.sep) and os.path.isfile(real):
            found.append(path)
    return found


def clear_report(repo_path, report, report_dir=None):
    """Delete stale report files before a run, so an absent report means the run produced none. Only files under the
    report's own base directory are touched."""
    for path in report_files(repo_path, report, report_dir):
        try:
            os.remove(path)
        except OSError:
            pass


def read_report(repo_path, report, report_dir=None, since=None):
    """Cases of every report file the run left, or None when there is none or none parses. A repo-relative report file
    older than `since` (epoch seconds) is stale and ignored."""
    if not report or report.get("kind") != "junit-xml":
        return None
    in_repo = not str(report.get("path") or "").startswith(REPORT_DIR)
    cases, found = [], False
    for path in report_files(repo_path, report, report_dir):
        try:
            if in_repo and since is not None and os.path.getmtime(path) < since:
                continue
            with open(path, encoding="utf-8", errors="replace") as handle:
                parsed = parse_junit_cases(handle.read())
        except OSError:
            continue
        if parsed is not None:
            found = True
            cases += parsed
    return cases if found else None


def summary_counts(output, patterns):
    """{passed, failed, skipped} counts the runner printed (profile `summary_patterns`: regexes with named groups
    passed, failed or skipped; the last match of each counts), or None when nothing matched."""
    counts, hit = {"passed": 0, "failed": 0, "skipped": 0}, set()
    for pattern in patterns or ():
        try:
            matches_ = list(re.finditer(pattern, output or ""))
        except re.error:
            continue
        if matches_:
            for name, value in matches_[-1].groupdict().items():
                if name in counts and value is not None:
                    counts[name] += int(value)
                    hit.add(name)
    return {k: counts[k] for k in hit} or None


def classify(exit_code, output, report, patterns, new_tests=(), baseline_failing=(), related_tests=(), summary_patterns=None):
    """Judge a run. `report` is [(id, status[, message])] or None; `new_tests` are the tests Red wrote (empty: baseline
    mode), `related_tests` those of earlier accepted cycles. An `<error>` counts as an assertion when the assertion pattern
    matches its own message (no message given: the output). Returns a dict: classification, passed, failed, skipped (whole
    report), failing (ids with a failure or error), status (id -> status), new_failing, new_passing, new_skipped, new_absent,
    related_absent, related_skipped, related_failing, outside (failing tests that are neither new nor failed at baseline)."""
    output = output or ""
    cases = [c if len(c) > 2 else (c[0], c[1], None) for c in report or []]
    status, msgs = {}, {}
    for tid, st, msg in cases:
        if status.get(tid) in (None, "pass", "skipped"):
            status[tid], msgs[tid] = st, msg
    new = list(dict.fromkeys(new_tests))
    related = [t for t in dict.fromkeys(related_tests) if t not in new]
    base = set(baseline_failing)
    failing = [t for t, st in status.items() if st in ("failure", "error")]

    def asserted(tid):
        return matches("assertion", output if msgs.get(tid) is None else msgs[tid], patterns)
    out = {"passed": sum(1 for _, st, _m in cases if st == "pass"), "failed": sum(1 for _, st, _m in cases if st in ("failure", "error")),
           "skipped": sum(1 for _, st, _m in cases if st == "skipped"), "failing": failing, "status": status,
           "new_failing": [], "new_passing": [], "new_skipped": [], "new_absent": [t for t in new if t not in status],
           "related_absent": [t for t in related if t not in status],
           "related_skipped": [t for t in related if status.get(t) == "skipped"],
           "related_failing": [t for t in related if status.get(t) in ("failure", "error") and t not in base],
           "outside": [t for t in failing if t not in new and t not in base and t not in related]}
    for t in new:
        st = status.get(t)
        if st == "failure" or (st == "error" and asserted(t)):
            out["new_failing"].append(t)
        elif st in ("pass", "skipped"):
            out["new_passing"].append(t)
            if st == "skipped":
                out["new_skipped"].append(t)
    klass = next((k for k in PATTERN_ORDER if matches(k, output, patterns)), None)
    if klass is None:
        errored = [t for t in new if status.get(t) == "error" and t not in out["new_failing"]]
        if report is None:
            klass = "pass" if exit_code == 0 else "unknown"
        elif not new:
            if any(st == "error" and not asserted(t) for t, st in status.items()):
                klass = "unknown"
            elif failing:
                klass = "assertion"
            else:
                klass = "pass" if exit_code == 0 else "unknown"
        elif errored:
            klass = "unknown"
        elif out["new_failing"]:
            klass = "assertion"
        elif out["new_absent"] and failing and all(t in base for t in failing):
            klass = "preexisting_failure"
        elif failing:
            klass = "assertion"
        else:
            klass = "pass" if exit_code == 0 else "unknown"
        printed = summary_counts(output, summary_patterns) if report is not None else None
        if printed and any(printed[k] != out[k] for k in printed):
            out["summary_mismatch"] = {k: [printed[k], out[k]] for k in printed if printed[k] != out[k]}
            klass = "unknown"
    out["classification"] = klass
    return out


def _related_problem(result, base=()):
    """The first reason a run of the related tests (earlier accepted cycles) is not clean, else None."""
    for key, text in (("related_absent", "related tests did not run"), ("related_skipped", "related tests skipped"),
                      ("related_failing", "related tests fail")):
        if result.get(key):
            return f"{text}: " + ", ".join(result[key])
    return None


def verify_red(result, new_tests):
    """(verdict, reason) of a classified Red run: accepted only when every new test fails by assertion and every related
    test (earlier accepted cycles) still ran and passed, and nothing else failed that passed at baseline. Rejections carry
    the reason the retry brief shows."""
    klass = result["classification"]
    if klass == "unknown":
        return "needs_human", "the failure could not be classified"
    if klass in RETRY_CLASSES:
        return "rejected", f"{klass.replace('_', ' ')}: the new tests did not fail by assertion"
    if result["new_passing"]:
        return "rejected", "new tests pass before Green: " + ", ".join(result["new_passing"])
    if result["new_absent"]:
        return "rejected", "new tests did not run: " + ", ".join(result["new_absent"])
    problem = _related_problem(result)
    if problem:
        return "rejected", problem
    if result["outside"]:
        return "rejected", "new failure outside the new tests: " + ", ".join(result["outside"])
    if klass == "pass":
        return "rejected", "new tests pass before Green: " + ", ".join(new_tests)
    return "accepted", None


def verify_green(result, tests):
    """(verdict, reason) of a classified Green or Refactor run of the cycle's own tests and the related ones (TDD-04,
    TDD-05): accepted only when every one of them ran and passed; a skipped test is not a pass. Compile, dependency and
    environment problems and failures are rejections the retry brief shows; a run that cannot be classified goes to a human."""
    klass = result["classification"]
    if klass in ("compile", "missing_dependency", "environment"):
        return "rejected", f"{klass.replace('_', ' ')}: the tests did not run"
    bad = [t for t in tests if t in result["failing"]]
    if bad:
        return "rejected", "targeted tests fail: " + ", ".join(bad)
    if result.get("related_failing"):
        return "rejected", "related tests fail: " + ", ".join(result["related_failing"])
    if klass == "unknown":
        return "needs_human", "the result could not be classified"
    if result["new_absent"]:
        return "rejected", "targeted tests did not run: " + ", ".join(result["new_absent"])
    if result.get("new_skipped"):
        return "rejected", "targeted tests skipped: " + ", ".join(result["new_skipped"])
    return _related_problem(result) and ("rejected", _related_problem(result)) or ("accepted", None)
