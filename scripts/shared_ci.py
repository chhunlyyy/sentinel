#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scrub  # noqa: E402
import shared  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="CI gate for the Sentinel shared repo")
    parser.add_argument("--dir", default=".")
    parser.add_argument("--run-command", help="command that runs the regression suite, executed from the repo root")
    args = parser.parse_args()
    root = Path(args.dir).resolve()
    failed = False

    for problem in shared.check_shared(root):
        print(f"FAIL: {problem}")
        failed = True

    scrubber = scrub.Scrubber(root, [])
    for path, found in scrub.check_paths([root], scrubber).items():
        print(f"FAIL: {path}: {', '.join(found)}")
        failed = True

    if args.run_command:
        result = subprocess.run(args.run_command, shell=True, cwd=root)
        if result.returncode != 0:
            print("FAIL: regression suite")
            failed = True

    print("SHARED CHECK FAILED" if failed else "SHARED CHECK PASSED")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
