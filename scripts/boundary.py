import hashlib
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
