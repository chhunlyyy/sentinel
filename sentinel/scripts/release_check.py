#!/usr/bin/env python3
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from render_stage import CLIENT_ROLES, load_profile, repo_commands  # noqa: E402
import scrub  # noqa: E402

DEBUG_PATTERNS = {
    ".java": r"System\.(out|err)\.print|printStackTrace\(",
    ".kt": r"\bprintln\(|printStackTrace\(",
    ".dart": r"\bprint\(|debugPrint\(",
    ".ts": r"\bconsole\.(log|debug|trace)\(|\bdebugger\b",
    ".tsx": r"\bconsole\.(log|debug|trace)\(|\bdebugger\b",
    ".js": r"\bconsole\.(log|debug|trace)\(|\bdebugger\b",
    ".mjs": r"\bconsole\.(log|debug|trace)\(|\bdebugger\b",
    ".py": r"^\s*print\(|\bbreakpoint\(\)|\bpdb\.set_trace\(",
}
COMMENT_PATTERNS = {
    ".java": r"^\s*(//|/\*|\*)",
    ".kt": r"^\s*(//|/\*|\*)",
    ".dart": r"^\s*(//|/\*|\*)",
    ".sql": r"^\s*--",
    ".ts": r"^\s*(//|/\*|\*)(?!.*(eslint-disable|@ts-expect-error))",
    ".tsx": r"^\s*(//|/\*|\*|\{/\*)(?!.*(eslint-disable|@ts-expect-error))",
    ".js": r"^\s*(//|/\*|\*)(?!.*eslint-disable)",
    ".mjs": r"^\s*(//|/\*|\*)(?!.*eslint-disable)",
    ".py": r"^\s*#(?!!)",
}
MANIFESTS = ("package.json", "pubspec.yaml", "build.gradle", "build.gradle.kts", "pom.xml", "requirements.txt", "pyproject.toml", "go.mod", "Cargo.toml")
TEST_INFRA = re.compile(
    r"(^|/)(e2e|reports|\.stryker-tmp|test-results|playwright-report|coverage)/"
    r"|(^|/)(vitest|stryker|playwright|jest)\.(config|setup)\."
    r"|\.(test|spec)\.(ts|tsx|js|mjs)$"
)
TEST_DEPS = re.compile(
    r'^\+.*"(vitest|@vitest/[^"]*|@stryker-mutator/[^"]*|@playwright/test|playwright|jest|@testing-library/[^"]*|jsdom|happy-dom)"'
    r'|^\+.*"test(:[a-z]+)?":'
)

DEFAULT_CHECKS = ["debug_output", "todo", "comments", "secrets", "new_dependencies", "test_infra", "commands"]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout


def has_changes(repo):
    return bool(git(repo, "status", "--porcelain").strip())


def added_lines(repo):
    lines = []
    current = None
    for raw in git(repo, "diff", "HEAD", "-U0", "--no-color").splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:]
        elif raw.startswith("+++ "):
            current = None
        elif raw.startswith("+") and current:
            lines.append((current, raw[1:]))
    for name in git(repo, "ls-files", "--others", "--exclude-standard").splitlines():
        path = Path(repo) / name
        try:
            for text in path.read_text(errors="ignore").splitlines():
                lines.append((name, text))
        except OSError:
            continue
    return lines


def scan(lines, pattern_for_ext):
    hits = []
    for name, text in lines:
        pattern = pattern_for_ext.get(Path(name).suffix)
        if pattern and re.search(pattern, text):
            hits.append(f"{name}: {text.strip()[:120]}")
    return hits


def scan_secrets(lines):
    hits = []
    for name, text in lines:
        for label in scrub.secret_labels(text):
            hits.append(f"{name}: {label}")
    return hits


class Checker:
    def __init__(self, config, quick, only_repos=None, skip=()):
        self.config = config
        self.quick = quick
        self.only_repos = set(only_repos) if only_repos else None
        self.skip = set(skip)
        self.failed = []
        self.enabled = config.get("release_checks") or DEFAULT_CHECKS
        self.rules = config.get("rules") or {}

    def fail(self, label, details):
        self.failed.append(label)
        print(f"FAIL: {label}")
        for line in details[:20]:
            print(f"  {line}")

    def on(self, name):
        return name in self.enabled

    def hygiene(self, repo_conf, path):
        lines = added_lines(path)
        source = [(n, t) for n, t in lines if not re.search(r"(^|/)(test|tests|spec|__tests__)/|\.(test|spec)\.", n)]
        if self.on("debug_output"):
            hits = scan(source, DEBUG_PATTERNS)
            if hits:
                self.fail(f"{repo_conf['id']}: debug output added", hits)
        if self.on("todo"):
            hits = [f"{n}: {t.strip()[:120]}" for n, t in source if re.search(r"\b(TODO|FIXME|XXX)\b", t)]
            if hits:
                self.fail(f"{repo_conf['id']}: TODO/FIXME added", hits)
        if self.on("comments") and self.rules.get("no_code_comments"):
            hits = scan(lines, COMMENT_PATTERNS)
            if hits:
                self.fail(f"{repo_conf['id']}: code comment added", hits)
        if self.on("secrets"):
            hits = scan_secrets(lines)
            if hits:
                self.fail(f"{repo_conf['id']}: possible secret in diff", hits)
            if shutil.which("gitleaks"):
                result = subprocess.run(
                    ["gitleaks", "detect", "--no-banner", "--source", str(path), "--no-git"],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    self.fail(f"{repo_conf['id']}: gitleaks findings", result.stdout.splitlines())

    def dependencies(self, repo_conf, path):
        if not self.on("new_dependencies"):
            return
        changed = [m for m in MANIFESTS if (Path(path) / m).exists() and git(path, "diff", "HEAD", "--", m).strip()]
        if changed:
            print(f"NOTICE: {repo_conf['id']}: dependency manifest changed ({', '.join(changed)}); a human must approve new dependencies")

    def extra_checks(self, repo_conf, path, lines):
        for rule in self.config.get("extra_checks") or []:
            if rule.get("repo") not in (None, repo_conf["id"]):
                continue
            path_re = re.compile(rule["path_regex"]) if rule.get("path_regex") else None
            if rule["type"] == "added_lines":
                skip_path = re.compile(rule["exclude_path_regex"]) if rule.get("exclude_path_regex") else None
                skip_lines = [re.compile(p) for p in rule.get("exclude_line_regex") or []]
                pattern = re.compile(rule["pattern"])
                hits = []
                for name, text in lines:
                    if path_re and not path_re.search(name):
                        continue
                    if skip_path and skip_path.search(name):
                        continue
                    if any(s.search(text) for s in skip_lines) or not pattern.search(text):
                        continue
                    hits.append(f"{name}: {text.strip()[:120]}")
                if hits:
                    self.fail(f"{repo_conf['id']}: {rule['name']}", hits)
            elif rule["type"] == "changed_paths":
                status = git(path, "status", "--porcelain", "--untracked-files=all").splitlines()
                hits = []
                for entry in status:
                    code, name = entry[:2], entry[3:]
                    if path_re and not path_re.search(name):
                        continue
                    wanted = rule.get("status", "any")
                    modified = code.strip() in ("M", "MM", "AM", "RM") or "M" in code
                    if wanted == "modified" and not modified:
                        continue
                    if wanted == "added" and code.strip() not in ("??", "A"):
                        continue
                    if rule.get("must_match") and re.search(rule["must_match"], name):
                        continue
                    hits.append(name)
                if hits:
                    self.fail(f"{repo_conf['id']}: {rule['name']}", hits)

    def test_infra(self, repo_conf, path):
        if not (self.on("test_infra") and self.rules.get("no_permanent_frontend_tests")):
            return
        if repo_conf["role"] not in CLIENT_ROLES:
            return
        status = git(path, "status", "--porcelain", "--untracked-files=all").splitlines()
        infra = [s[3:] for s in status if TEST_INFRA.search(s[3:])]
        if infra:
            self.fail(f"{repo_conf['id']}: test infrastructure left behind", infra)
        manifest = git(path, "diff", "HEAD", "--", "package.json")
        deps = [line for line in manifest.splitlines() if TEST_DEPS.search(line)]
        if deps:
            self.fail(f"{repo_conf['id']}: test-only dependencies or scripts added", deps)

    def commands(self, repo_conf, path):
        if self.quick or not self.on("commands"):
            return
        profile = load_profile(repo_conf["profile"])
        commands = repo_commands(repo_conf, profile)
        for key in ("build", "lint", "typecheck", "test"):
            command = commands.get(key)
            if not command or key in self.skip:
                continue
            print(f"== {repo_conf['id']}: {key}: {command}")
            result = subprocess.run(command, shell=True, cwd=path)
            if result.returncode != 0:
                self.fail(f"{repo_conf['id']}: {key}", [command])

    def shared_clean(self, workspace):
        if not self.on("secrets"):
            return
        shared = workspace / (self.config.get("state") or {}).get("dir", ".sentinel") / "shared"
        if not shared.exists():
            return
        print("== shared repo: scrub check")
        scrubber = scrub.Scrubber(workspace, scrub.env_values(workspace))
        problems = scrub.check_paths([shared], scrubber)
        if problems:
            self.fail("shared repo contains secrets or personal data", [f"{p}: {', '.join(f)}" for p, f in problems.items()])

    def rebuild_after_qa(self, workspace):
        if self.quick:
            return
        state = (self.config.get("state") or {}).get("dir", ".sentinel")
        for marker in sorted((workspace / state / "cache" / "qa").glob("rebuild-*")):
            repo_id = marker.name[len("rebuild-"):]
            repo_conf = next((r for r in self.config["repos"] if r["id"] == repo_id), None)
            if not repo_conf:
                continue
            command = repo_commands(repo_conf, load_profile(repo_conf["profile"])).get("build")
            if not command:
                marker.unlink()
                continue
            print(f"== {repo_id}: rebuild after QA: {command}")
            if subprocess.run(command, shell=True, cwd=(workspace / repo_conf["path"]).resolve()).returncode != 0:
                self.fail(f"{repo_id}: rebuild after QA", [command])
            else:
                marker.unlink()

    def run(self, workspace):
        self.shared_clean(workspace)
        for repo_conf in self.config["repos"]:
            if self.only_repos and repo_conf["id"] not in self.only_repos:
                continue
            path = (workspace / repo_conf["path"]).resolve()
            if not path.exists():
                self.fail(f"{repo_conf['id']}: path not found", [str(path)])
                continue
            if not has_changes(path):
                print(f"{repo_conf['id']}: no changes, skipped")
                continue
            print(f"== {repo_conf['id']}: diff hygiene")
            self.hygiene(repo_conf, path)
            self.extra_checks(repo_conf, path, added_lines(path))
            self.dependencies(repo_conf, path)
            self.test_infra(repo_conf, path)
            self.commands(repo_conf, path)
        self.rebuild_after_qa(workspace)
        print()
        if self.failed:
            print(f"RELEASE CHECK FAILED ({len(self.failed)}):")
            for label in self.failed:
                print(f"  - {label}")
            return 1
        print("RELEASE CHECK PASSED")
        return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--repo", action="append", help="check only this repo id (repeatable); default is every repo with changes")
    parser.add_argument("--skip", default="", help="comma-separated command keys to skip, for example build when a dev server is running")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text())
    sys.exit(Checker(config, args.quick, args.repo, [k for k in args.skip.split(",") if k]).run(Path(args.workspace).resolve()))


if __name__ == "__main__":
    main()
