#!/usr/bin/env python3
"""Fake QA driver for the Phase J tests (TDD-09).

Usage: fake_qa_driver.py <scripts folder> <report path> <cycle id>

The plan is a JSON file named by FAKE_QA_PLAN:
  {"default": {"*": "fail_then", "AC-1": "pass"},        # scenario id -> mode, "*" for any
   "runs": {"2": {"AC-1": "pass"}},                       # per run number (1 based), same shape
   "run_modes": {"1": "app_down"},                        # whole-run mode for one run number
   "all": "driver_missing",                               # whole-run mode for every run
   "print": "password=Pw-9f3kq2", "artifacts": true, "sleep": 0.5, "extra": ["AC-99"],
   "dump_env": "/path/env.json"}                          # write the driver's environment as JSON (M13)
Scenario modes: pass, fail_then, fail_given, fail_when, skip, missing, script_error.
Whole-run modes: app_down, driver_missing, timeout, garbage, nothing.
Every scenario id is the stem (text before the first dot) of a file directly in the scripts folder (helpers in subfolders are not scenarios).
The run number counts in <plan>.count; start and end times and the pid go to <plan>.log.
"""
import json
import os
import sys
import time
from xml.sax.saxutils import quoteattr

STEPS = {"fail_then": 'Then the form shows 5 days: expected "5" but got "0"',
         "fail_given": "Given the employee has 5 days left: no such row in the table",
         "fail_when": "When I click Submit: selector #submit not found",
         "script_error": "SyntaxError: unexpected token near line 3"}


def main():
    scripts, report, cycle = sys.argv[1], sys.argv[2], sys.argv[3]
    plan_path = os.environ.get("FAKE_QA_PLAN")
    plan = json.loads(open(plan_path).read()) if plan_path and os.path.exists(plan_path) else {}
    count_path = (plan_path or "fake_qa") + ".count"
    n = (int(open(count_path).read()) if os.path.exists(count_path) else 0) + 1
    open(count_path, "w").write(str(n))
    log = open((plan_path or "fake_qa") + ".log", "a")
    log.write(json.dumps({"event": "start", "pid": os.getpid(), "run": n, "cycle": cycle, "scripts": scripts, "at": time.time()}) + "\n")
    log.flush()
    try:
        run(plan, n, scripts, report)
    finally:
        log.write(json.dumps({"event": "end", "pid": os.getpid(), "run": n, "cycle": cycle, "at": time.time()}) + "\n")
        log.flush()


def mode_of(plan, n, sid):
    for table in ((plan.get("runs") or {}).get(str(n)) or {}, plan.get("default") or {}):
        for key in (sid, "*"):
            if key in table:
                return table[key]
    return "fail_then"


def run(plan, n, scripts, report):
    if plan.get("dump_env"):
        open(plan["dump_env"], "w").write(json.dumps(dict(os.environ)))
    if plan.get("sleep"):
        time.sleep(plan["sleep"])
    if plan.get("print"):
        print(plan["print"], flush=True)
    whole = (plan.get("run_modes") or {}).get(str(n)) or plan.get("all")
    if whole == "app_down":
        print("Error: page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:4173/ (ECONNREFUSED)", flush=True)
        sys.exit(1)
    if whole == "driver_missing":
        print("sh: 1: playwright: command not found", flush=True)
        sys.exit(127)
    if whole == "timeout":
        time.sleep(3600)
    if whole == "garbage":
        os.makedirs(os.path.dirname(report), exist_ok=True)
        open(report, "w").write("this is not xml")
        sys.exit(1)
    if whole == "nothing":
        print("something odd happened", flush=True)
        sys.exit(1)
    ids = sorted({f.split(".")[0] for f in os.listdir(scripts) if os.path.isfile(os.path.join(scripts, f))}) if os.path.isdir(scripts) else []
    ids += [x for x in plan.get("extra") or [] if x not in ids]
    cases, failed = [], 0
    extra = (" " + plan["print"]) if plan.get("print") else ""
    for sid in ids:
        mode = mode_of(plan, n, sid)
        if mode == "missing":
            continue
        body = ""
        if mode == "skip":
            body = "<skipped/>"
        elif mode == "script_error":
            body = f"<error message={quoteattr(STEPS[mode] + extra)}>trace</error>"
            failed += 1
        elif mode in STEPS:
            body = f"<failure message={quoteattr(STEPS[mode] + extra)}>trace</failure>"
            failed += 1
            if plan.get("artifacts"):
                base = os.path.dirname(report)
                for sub, ext in (("screenshots", "png"), ("traces", "zip")):
                    os.makedirs(os.path.join(base, sub), exist_ok=True)
                    open(os.path.join(base, sub, f"{sid}.{ext}"), "wb").write(b"\x89PNG fake")
        cases.append(f'<testcase classname="qa" name={quoteattr(sid)}>{body}</testcase>')
        print(f"{sid}: {mode}", flush=True)
    os.makedirs(os.path.dirname(report), exist_ok=True)
    open(report, "w").write("<testsuite name=\"qa\">" + "".join(cases) + "</testsuite>")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
