#!/usr/bin/env python3
"""Print the changed files' diffs from changes.json as readable text, to write notes from.

Usage: dump_diffs.py <changes.json> [--lane <lane>] [--repo <repo>] [--max-lines 200]
Each block is numbered with the index to use in key_hunks.
"""

import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("changes")
    parser.add_argument("--lane")
    parser.add_argument("--repo")
    parser.add_argument("--max-lines", type=int, default=200)
    args = parser.parse_args()
    with open(args.changes, encoding="utf-8") as handle:
        data = json.load(handle)
    for node in data["nodes"]:
        if node["status"] == "context" or (args.lane and node["lane"] != args.lane) or (args.repo and node["repo"] != args.repo):
            continue
        flags = " barrel" if node.get("barrel") else " binary" if node.get("binary") else ""
        print(f"\n===== {node['id']} [{node['lane']}, {node['status']}, +{node['added']} -{node['removed']}{flags}]")
        printed = 0
        for index, hunk in enumerate(node["hunks"]):
            if printed >= args.max_lines:
                print(f"  ... {len(node['hunks']) - index} more block(s) not shown")
                break
            print(f"--- block {index}: {hunk['header']}")
            for kind, text in hunk["lines"]:
                if printed >= args.max_lines:
                    break
                print({"add": "+", "del": "-"}.get(kind, " ") + text)
                printed += 1


if __name__ == "__main__":
    main()
