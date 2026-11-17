import hashlib
import os
import subprocess
from pathlib import Path


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout


def repo_state(repo):
    head = git(repo, "rev-parse", "HEAD").strip()
    digest = hashlib.sha256()
    digest.update(git(repo, "diff", "HEAD", "--binary").encode(errors="ignore"))
    for name in sorted(git(repo, "ls-files", "--others", "--exclude-standard").splitlines()):
        path = Path(repo) / name
        digest.update(name.encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
    status = git(repo, "status", "--porcelain", "--untracked-files=all")
    return {"head": head, "digest": digest.hexdigest(), "status": status}


def config_state(paths):
    digest = hashlib.sha256()
    for root in paths:
        root = Path(root)
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []
        for file in files:
            digest.update(str(file).encode())
            try:
                digest.update(file.read_bytes())
            except OSError:
                continue
    return digest.hexdigest()


class Snapshot:
    def __init__(self, repos, config_paths):
        self.repos = {repo_id: Path(path) for repo_id, path in repos.items()}
        self.config_paths = config_paths
        self.before = {repo_id: repo_state(path) for repo_id, path in self.repos.items()}
        self.config_before = config_state(config_paths)

    def violations(self, allowed_repo, concurrent=()):
        found = []
        for repo_id, path in self.repos.items():
            after = repo_state(path)
            before = self.before[repo_id]
            if after["head"] != before["head"]:
                found.append(f"{repo_id}: HEAD moved (the stage committed, reset, or switched branches)")
            if repo_id == allowed_repo or repo_id in concurrent:
                continue
            if after["digest"] != before["digest"]:
                changed = sorted(set(before["status"].splitlines()) ^ set(after["status"].splitlines()))
                names = " ".join(line[3:] for line in changed) or "content of already-changed files"
                found.append(f"{repo_id}: modified outside the stage's write boundary: {names}")
        if config_state(self.config_paths) != self.config_before:
            found.append("sentinel config, generated agents, or skills were modified")
        return found


HEAVY_DIRS = ("node_modules", ".venv", "venv", ".tox")
VOLATILE_DIRS = (".cache", "__pycache__", ".pytest_cache")  # tools rewrite these on every run
IGNORE_FILES = (".git/info/exclude", ".git/config")  # rules an agent could edit to hide new files


def _hash(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _tree_signature(root):
    """Cheap fingerprint of a big ignored directory (file count, names, sizes, mtimes), no content hashing."""
    digest = hashlib.sha256()
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in VOLATILE_DIRS)
        for name in sorted(files):
            try:
                st = os.lstat(os.path.join(base, name))
            except OSError:
                continue
            digest.update(f"{os.path.relpath(os.path.join(base, name), root)}:{st.st_size}:{st.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def _ignored_paths(repo, watch):
    """{path: sha256} of the ignored files `watch(path)` accepts, every ignored `.gitignore`, and a fingerprint (path
    ending in "/") for well-known heavy ignored directories."""
    out = {}
    listed = git(repo, "ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory").split("\0")
    for name in filter(None, listed):
        full = Path(repo) / name
        if name.endswith("/"):
            if name.rstrip("/").rsplit("/", 1)[-1] in HEAVY_DIRS:
                out[name] = _tree_signature(full)
                continue
            names = [os.path.relpath(os.path.join(b, f), repo).replace(os.sep, "/") for b, _, fs in os.walk(full) for f in fs]
        else:
            names = [name]
        for n in names:
            if n.rsplit("/", 1)[-1] == ".gitignore" or watch(n):
                out[n] = _hash(Path(repo) / n)
    return out


def changed_state(repo, watch=None):
    """{"head": sha, "paths": {path: sha256 or None}} for every changed or untracked path (None: deleted).
    A rename lists the new path and the old one as deleted. The rule files an agent could use to hide new files
    (`.git/info/exclude`, `.git/config`) are listed with their hash. With `watch`, a predicate over repo-relative paths,
    ignored files it accepts are listed too, and heavy ignored directories (node_modules, ...) by a fingerprint, so an
    ignore rule cannot hide a write."""
    head = git(repo, "rev-parse", "HEAD").strip()
    paths = {}
    tokens = git(repo, "status", "--porcelain", "--untracked-files=all", "-z").split("\0")
    i = 0
    while i < len(tokens):
        line = tokens[i]
        i += 1
        if len(line) < 4:
            continue
        name = line[3:]
        paths[name] = _hash(Path(repo) / name)
        if line[0] in "RC" or line[1] in "RC":
            if i < len(tokens) and tokens[i]:
                if "R" in line[:2]:
                    paths[tokens[i]] = None
            i += 1
    for rel in IGNORE_FILES:
        if (Path(repo) / rel).is_file():
            paths[rel] = _hash(Path(repo) / rel)
    if watch is not None:
        paths.update(_ignored_paths(repo, watch))
    return {"head": head, "paths": paths}


_ABSENT = object()


def changed_between(before, after):
    """Sorted paths whose content differs between two changed_state() results. A path missing from a result is
    unchanged from HEAD, so a deleted file counts as changed unless it was already deleted."""
    names = set(before["paths"]) | set(after["paths"])
    return sorted(n for n in names if before["paths"].get(n, _ABSENT) != after["paths"].get(n, _ABSENT))
