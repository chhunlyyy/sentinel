#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path

MAX_BYTES = 20 * 1024 * 1024
SKIP_DIRS = {"node_modules", ".git", ".next", "build", "dist", "__pycache__"}
EMAIL_ALLOWED = re.compile(r"@(example\.(com|org|net)|localhost|users\.noreply\.github\.com)$", re.I)

SECRET_PATTERNS = [
    ("jwt", r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----|-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("aws key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("bearer token", r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{24,}=*"),
    ("url credentials", r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"),
]
SECRET_NAME_VALUE = re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)([\"']?\s*[:=]\s*)([\"']?)(?!\[REDACTED)([^\s\"',;&]{6,})")
BARE_SECRET = re.compile(r"[A-Za-z0-9!@#$%^*_+=~/-]{6,}")


def is_secret_value(quote, value):
    if value.startswith(("${", "{{", "<", "$")):
        return False
    if quote:
        return True
    return bool(BARE_SECRET.fullmatch(value)) and bool(re.search(r"\d", value))


def secret_labels(text):
    labels = []
    for label, pattern in SECRET_PATTERNS:
        if re.search(pattern, text):
            labels.append(label)
    for match in SECRET_NAME_VALUE.finditer(text):
        if is_secret_value(match.group(3), match.group(4)):
            labels.append("password literal")
            break
    return labels


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOME_PATHS = [
    re.compile(r"/home/[A-Za-z0-9._-]+"),
    re.compile(r"/Users/[A-Za-z0-9._-]+"),
    re.compile(r"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+"),
]


SECRET_KEY = re.compile(r"(?i)(pass|secret|token|key|credential|private|auth|salt|dsn)")
PLAIN_WORD = re.compile(r"[a-z][a-z._-]*")
EXAMPLE_SUFFIXES = (".example", ".sample", ".template", ".dist")


def env_values(workspace):
    values = set()
    for env_file in Path(workspace).glob("**/.env*"):
        if any(part in SKIP_DIRS for part in env_file.parts) or env_file.name.endswith(EXAMPLE_SUFFIXES):
            continue
        try:
            for line in env_file.read_text(errors="ignore").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    value = value.strip().strip("'\"")
                    if len(value) >= 6 and SECRET_KEY.search(key) and not PLAIN_WORD.fullmatch(value):
                        values.add(value)
        except OSError:
            continue
    return sorted(values, key=len, reverse=True)


class Scrubber:
    def __init__(self, workspace, secrets):
        self.workspace = str(Path(workspace).resolve())
        self.secrets = secrets

    def scrub_text(self, text):
        for value in self.secrets:
            text = text.replace(value, "[REDACTED:env]")
        text = text.replace(self.workspace, "$WORKSPACE")
        for pattern in HOME_PATHS:
            text = pattern.sub("$HOME", text)
        for label, pattern in SECRET_PATTERNS:
            if label == "url credentials":
                text = re.sub(pattern, lambda m: f"{m.group(1)}[REDACTED:credentials]@", text)
            else:
                text = re.sub(pattern, f"[REDACTED:{label}]", text)
        text = SECRET_NAME_VALUE.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}[REDACTED:secret]" if is_secret_value(m.group(3), m.group(4)) else m.group(0),
            text,
        )
        return EMAIL.sub(lambda m: m.group(0) if EMAIL_ALLOWED.search(m.group(0)) else "[REDACTED:email]", text)

    def findings(self, text):
        found = []
        for value in self.secrets:
            if value in text:
                found.append("env value")
        if self.workspace in text:
            found.append("workspace path")
        for pattern in HOME_PATHS:
            if pattern.search(text):
                found.append("home path")
        for label, pattern in SECRET_PATTERNS:
            for match in re.finditer(pattern, text):
                if "[REDACTED" in match.group(0):
                    continue
                found.append(label)
        for match in SECRET_NAME_VALUE.finditer(text):
            if is_secret_value(match.group(3), match.group(4)):
                found.append("password literal")
        for match in EMAIL.finditer(text):
            if not EMAIL_ALLOWED.search(match.group(0)):
                found.append("email")
        return sorted(set(found))


def iter_files(paths):
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            yield path
            continue
        for item in path.rglob("*"):
            if item.is_file() and not any(part in SKIP_DIRS for part in item.parts):
                yield item


def read_text(path):
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    return data.decode("utf-8", errors="ignore")


def scrub_paths(paths, scrubber):
    changed = []
    for path in iter_files(paths):
        text = read_text(path)
        if text is None:
            continue
        cleaned = scrubber.scrub_text(text)
        if cleaned != text:
            path.write_text(cleaned)
            changed.append(path)
    return changed


def check_paths(paths, scrubber):
    problems = {}
    for path in iter_files(paths):
        text = read_text(path)
        if text is None:
            continue
        found = scrubber.findings(text)
        if found:
            problems[str(path)] = found
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--workspace", default=".")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    scrubber = Scrubber(args.workspace, env_values(args.workspace))
    if args.check:
        problems = check_paths(args.paths, scrubber)
        for path, found in problems.items():
            print(f"{path}: {', '.join(found)}")
        sys.exit(1 if problems else 0)
    changed = scrub_paths(args.paths, scrubber)
    print(f"scrubbed {len(changed)} file(s)")


if __name__ == "__main__":
    main()
