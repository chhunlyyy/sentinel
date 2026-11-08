#!/usr/bin/env python3
"""Render the change map HTML from collect_changes.py output plus Claude's notes.

Usage:
  render_map.py --changes <changes.json> --notes <notes.json> --out <map.html> [--strict]

Prints which changed files still have no note, which note keys match no file,
and which flow steps point at unknown files. --strict exits 1 on any of these.
"""

import argparse
import datetime
import json
import os
import sys

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--changes", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-em-dashes", action="store_true")
    args = parser.parse_args()

    with open(args.changes, encoding="utf-8") as handle:
        data = json.load(handle)
    with open(args.notes, encoding="utf-8") as handle:
        notes = json.load(handle)

    ids = {n["id"] for n in data["nodes"]}
    changed = [n for n in data["nodes"] if n["status"] != "context"]
    files = notes.get("files", {})
    problems = []
    missing = [n["id"] for n in changed
               if n["lane"] != "tests" and not n.get("barrel") and not n.get("binary") and not files.get(n["id"], {}).get("summary")]
    if missing:
        problems.append("Changed files with no summary:\n  " + "\n  ".join(missing))
    stray = [key for key in files if key not in ids]
    if stray:
        problems.append("Note keys that match no file (typo or wrong repo prefix?):\n  " + "\n  ".join(stray))
    flows = notes.get("flows", [])
    if not 2 <= len(flows) <= 5:
        problems.append(f"Write 2-5 flows (found {len(flows)}).")
    for flow in flows:
        steps = flow.get("steps", [])
        bad = [s.get("node") for s in steps if s.get("node") not in ids]
        if bad:
            problems.append(f"Flow '{flow.get('name')}' has unknown steps:\n  " + "\n  ".join(map(str, bad)))
        if len(steps) < 2:
            problems.append(f"Flow '{flow.get('name')}' needs at least 2 steps.")
        if any(not (s.get("note") or "").strip() for s in steps):
            problems.append(f"Flow '{flow.get('name')}' has steps without a note.")
    for node in changed:
        indexes = files.get(node["id"], {}).get("key_hunks", [])
        for index in indexes:
            if not isinstance(index, int) or not 0 <= index < len(node["hunks"]):
                problems.append(f"{node['id']}: key_hunks index {index} out of range (0..{len(node['hunks']) - 1})")
        if len(set(map(str, indexes))) != len(indexes):
            problems.append(f"{node['id']}: key_hunks has repeats")
    if args.no_em_dashes and "\u2014" in json.dumps(notes, ensure_ascii=False):
        problems.append("Notes contain em dashes; use commas, colons or parentheses instead.")

    if problems and args.strict:
        for problem in problems:
            print("ERROR: " + problem)
        sys.exit("Strict check failed; the HTML was not written. Fix the notes and re-run.")

    data["notes"] = notes
    data["generated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    with open(TEMPLATE, encoding="utf-8") as handle:
        html = handle.read().replace("/*__DATA__*/null", payload, 1)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(html)

    print(f"Wrote {args.out} ({len(changed)} changed files, {len(data['edges'])} links)")
    for problem in problems:
        print("WARNING (page is incomplete): " + problem)


if __name__ == "__main__":
    main()
