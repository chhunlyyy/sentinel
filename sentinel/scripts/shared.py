import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

LOCK_REF = "refs/sentinel/locks"
ROOT = Path(__file__).resolve().parent.parent
URL_START = re.compile(r"^(https?://|ssh://|git://|file://|git@|/|\./|\.\./|~)")

README = """# Sentinel shared repo

This private repository holds what the team shares across Sentinel runs. It is cloned to `.sentinel/shared/` in each workspace by `sentinel sync pull`.

| Path | What it holds |
|---|---|
| `invariants.md` | project rules every increment must satisfy |
| `guidelines/` | extra instructions appended to stage prompts (referenced from `sentinel.config.yaml`) |
| `specs/` | one spec per increment, plus `index.md` and `index.json` |
| `regression/` | the accumulated regression suite, one file per increment |

Keep this repository private. Never commit real names, government or national ids, emails, tokens or passwords; `sentinel scrub --check` blocks a push when it recognizes them.
"""

GUIDELINES_README = """Put one markdown file per repo role or stage here, for example `backend.md` or `reviewer.md`, and point to it from `sentinel.config.yaml` with `repos[].guidelines` or `stage_guidelines`. Its text is appended to the stage prompts.
"""

GITIGNORE = "node_modules/\ntest-results/\nplaywright-report/\nqa-users.json\n"


def looks_like_git_url(url):
    return bool(url) and bool(URL_START.match(url.strip()))


def verify_remote(url, timeout=25):
    try:
        result = subprocess.run(["git", "ls-remote", url], capture_output=True, text=True, timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.TimeoutExpired:
        return False, "timed out", 0
    if result.returncode != 0:
        return False, (result.stderr.strip().splitlines() or ["unreachable"])[-1], 0
    return True, "", len([l for l in result.stdout.splitlines() if l.strip()])


def git(directory, *args, check=True):
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result


class Shared:
    def __init__(self, workspace, config):
        state = config.get("state") or {}
        self.dir = Path(workspace) / state.get("dir", ".sentinel") / "shared"
        self.url = state.get("shared_repo") or ""
        self.ref = state.get("shared_ref") or "main"
        self.local = state.get("shared_mode") == "local"

    def is_clone(self):
        if self.local:
            return (self.dir / "invariants.md").exists()
        return (self.dir / ".git").exists()

    def init_local(self):
        files = {
            "README.md": README.replace("This private repository holds what the team shares across Sentinel runs. It is cloned to `.sentinel/shared/` in each workspace by `sentinel sync pull`.", "This folder holds what Sentinel keeps across runs on this machine (local-only mode, no shared git repo)."),
            "invariants.md": (ROOT / "templates" / "invariants.md").read_text(),
            "guidelines/README.md": GUIDELINES_README,
            ".gitignore": GITIGNORE,
        }
        created = []
        for name, content in files.items():
            target = self.dir / name
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            created.append(name)
        (self.dir / "specs").mkdir(parents=True, exist_ok=True)
        if not (self.dir / "specs" / "index.json").exists():
            (self.dir / "specs" / "index.json").write_text("{}\n")
            self.render_index({})
        (self.dir / "regression").mkdir(exist_ok=True)
        print(f"local-only shared folder ready at {self.dir}" + (f" (created: {', '.join(created)})" if created else ""))

    def has_remote(self):
        return self.is_clone() and bool(git(self.dir, "remote", check=False).stdout.strip())

    def pull(self):
        if self.local:
            self.init_local()
            return
        if not self.url:
            sys.exit("state.shared_repo is empty; set it in sentinel.config.yaml")
        if self.is_clone() and self.merging():
            sys.exit("a merge is in progress in the shared repo; resolve it and run `sentinel sync push <slug> --continue`")
        if not self.is_clone():
            self.dir.parent.mkdir(parents=True, exist_ok=True)
            if self.dir.exists() and any(self.dir.iterdir()):
                seed = self.dir.parent / "shared.local-backup"
                if seed.exists():
                    sys.exit(f"{seed} already exists; move it away first")
                self.dir.rename(seed)
                print(f"existing local shared files kept in {seed}")
            result = subprocess.run(["git", "clone", self.url, str(self.dir)], capture_output=True, text=True)
            if result.returncode != 0:
                sys.exit(result.stderr.strip())
        else:
            git(self.dir, "fetch", "--tags", "origin")
        if git(self.dir, "rev-parse", "--verify", "HEAD", check=False).returncode != 0:
            self.scaffold()
            return
        git(self.dir, "checkout", self.ref)
        is_branch = git(self.dir, "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{self.ref}", check=False).returncode == 0
        if is_branch:
            git(self.dir, "merge", "--ff-only", f"origin/{self.ref}")
        head = git(self.dir, "rev-parse", "--short", "HEAD").stdout.strip()
        print(f"shared repo at {self.ref} ({head})")

    def write_ci(self):
        target = self.dir / ".github" / "workflows" / "sentinel-shared.yml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / "templates" / "ci" / "shared-repo.github.yml").read_text())
        return target

    def scaffold(self):
        git(self.dir, "checkout", "-B", self.ref)
        files = {
            "README.md": README,
            "invariants.md": (ROOT / "templates" / "invariants.md").read_text(),
            "guidelines/README.md": GUIDELINES_README,
            ".gitignore": GITIGNORE,
        }
        for name, content in files.items():
            target = self.dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        (self.dir / "specs").mkdir(exist_ok=True)
        (self.dir / "specs" / "index.json").write_text("{}\n")
        self.render_index({})
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "-m", "Initialize Sentinel shared repo")
        print(f"the shared repo was empty: starter files were committed locally on {self.ref}")
        print(f"publish them once with: git -C {self.dir} push -u origin {self.ref}")

    def push(self, slug, run_dir, scrubber_check):
        if self.local:
            if not self.is_clone():
                self.init_local()
            proposed = Path(run_dir) / "proposed-invariants.md"
            if proposed.exists() and "no new invariants" not in proposed.read_text().lower():
                (self.dir / "proposals").mkdir(exist_ok=True)
                (self.dir / "proposals" / f"{slug}.md").write_text(proposed.read_text())
            problems = scrubber_check()
            if problems:
                for path, found in problems.items():
                    print(f"{path}: {', '.join(found)}")
                sys.exit("scrub check failed")
            print("local-only mode: nothing to push, files stay in .sentinel/shared")
            return
        if not self.is_clone():
            sys.exit("shared repo is not cloned; run `sentinel sync pull` first")
        proposed = Path(run_dir) / "proposed-invariants.md"
        if proposed.exists() and "no new invariants" not in proposed.read_text().lower():
            target = self.dir / "proposals"
            target.mkdir(exist_ok=True)
            (target / f"{slug}.md").write_text(proposed.read_text())
        problems = scrubber_check()
        if problems:
            for path, found in problems.items():
                print(f"{path}: {', '.join(found)}")
            sys.exit("scrub check failed; nothing pushed")
        self.require_ref_branch()
        if self.merging():
            sys.exit("a merge is in progress in the shared repo; resolve the conflicts, then run `sentinel sync push <slug> --continue`")
        git(self.dir, "checkout", self.ref)
        self.commit_all(slug)
        if not self.ahead():
            print("nothing to push")
            return
        self.integrate()

    def require_ref_branch(self):
        if git(self.dir, "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{self.ref}", check=False).returncode != 0:
            sys.exit(f"state.shared_ref {self.ref} is not a branch on the shared remote; push needs a branch")

    def merging(self):
        return git(self.dir, "rev-parse", "--verify", "--quiet", "MERGE_HEAD", check=False).returncode == 0

    def ahead(self):
        out = git(self.dir, "rev-list", "--count", f"origin/{self.ref}..HEAD").stdout.strip()
        return int(out or 0) > 0

    def commit_all(self, slug):
        git(self.dir, "add", "-A", "--", ".", ":(exclude)locks")
        if git(self.dir, "status", "--porcelain").stdout.strip():
            git(self.dir, "commit", "-m", f"sentinel: {slug}")

    def conflicted(self):
        return [f for f in git(self.dir, "diff", "--name-only", "--diff-filter=U").stdout.split("\n") if f]

    def integrate(self):
        for _ in range(3):
            git(self.dir, "fetch", "origin", self.ref)
            merge = git(self.dir, "merge", "--no-edit", f"origin/{self.ref}", check=False)
            if merge.returncode != 0:
                files = self.conflicted()
                if not files:
                    sys.exit(merge.stderr.strip() or merge.stdout.strip())
                print("merge conflict in the shared repo. Resolve each file in .sentinel/shared, keeping the intent of both sides, then run `sentinel sync push <slug> --continue`:")
                for name in files:
                    print(f"  {name}")
                sys.exit(4)
            if git(self.dir, "push", "origin", f"HEAD:{self.ref}", check=False).returncode == 0:
                print(f"pushed to {self.ref}")
                return
        sys.exit("could not push to the shared repo after 3 attempts; run again")

    def continue_push(self, slug, scrubber_check):
        if self.local:
            sys.exit("local-only mode: there is no merge to continue")
        if not self.merging():
            sys.exit("no merge in progress; run `sentinel sync push <slug> --auto`")
        markers = ""
        for path in self.dir.rglob("*"):
            if ".git" in path.parts or not path.is_file():
                continue
            try:
                body = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            if any(line.startswith(("<<<<<<< ", ">>>>>>> ")) for line in body.splitlines()):
                markers += f"{path.relative_to(self.dir)}\n"
        if markers:
            sys.exit("conflicts are not resolved yet, markers remain in: " + ", ".join(sorted(set(markers.split()))))
        git(self.dir, "add", "-A", "--", ".", ":(exclude)locks")
        left = self.conflicted()
        if left:
            sys.exit("conflicts are not resolved yet: " + ", ".join(left))
        problems = scrubber_check()
        if problems:
            for path, found in problems.items():
                print(f"{path}: {', '.join(found)}")
            sys.exit("scrub check failed; nothing pushed")
        git(self.dir, "add", "-A", "--", ".", ":(exclude)locks")
        git(self.dir, "commit", "--no-edit")
        self.integrate()

    def lock_ref(self, slug):
        return f"{LOCK_REF}/{slug}"

    def acquire(self, slug, owner):
        if self.has_remote():
            tree = git(self.dir, "hash-object", "-t", "tree", "/dev/null").stdout.strip()
            message = f"lock {slug} by {owner} at {time.strftime('%Y-%m-%dT%H:%M:%S')} {uuid.uuid4().hex}"
            commit = git(self.dir, "-c", "user.name=sentinel", "-c", "user.email=sentinel@localhost", "commit-tree", tree, "-m", message).stdout.strip()
            result = git(self.dir, "push", "origin", f"{commit}:{self.lock_ref(slug)}", check=False)
            if result.returncode != 0:
                holder = git(self.dir, "ls-remote", "origin", self.lock_ref(slug), check=False).stdout.strip()
                sys.exit(f"slug {slug} is locked by another run ({holder or 'remote ref exists'})")
            return
        lock = self.dir / "locks" / slug
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            sys.exit(f"slug {slug} is locked by another run: {lock.read_text().strip()}")
        with os.fdopen(fd, "w") as f:
            f.write(f"{owner} {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")

    def release(self, slug):
        if self.has_remote():
            git(self.dir, "push", "origin", f":{self.lock_ref(slug)}", check=False)
        lock = self.dir / "locks" / slug
        if lock.exists():
            lock.unlink()

    def index_json(self):
        return self.dir / "specs" / "index.json"

    def set_spec(self, slug, status, pr, tests):
        from paths import valid_slug
        valid_slug(slug)
        for name in tests:
            if "/" in name or ".." in name or name.startswith("."):
                sys.exit(f"invalid test file name {name!r}: give plain file names under regression/")
        index = json.loads(self.index_json().read_text()) if self.index_json().exists() else {}
        entry = index.get(slug, {})
        entry["status"] = status or entry.get("status", "draft")
        entry["updated"] = time.strftime("%Y-%m-%d")
        if pr:
            entry["pr"] = pr
        if tests:
            entry["tests"] = sorted(set(entry.get("tests", [])) | set(tests))
        index[slug] = entry
        self.index_json().parent.mkdir(parents=True, exist_ok=True)
        self.index_json().write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
        self.render_index(index)

    def render_index(self, index):
        lines = ["# Spec index", "", "| Slug | Status | Updated | PR | Regression tests |", "|---|---|---|---|---|"]
        for slug in sorted(index):
            entry = index[slug]
            lines.append(f"| {slug} | {entry.get('status', '')} | {entry.get('updated', '')} | {entry.get('pr', '')} | {', '.join(entry.get('tests', []))} |")
        (self.dir / "specs" / "index.md").write_text("\n".join(lines) + "\n")


def check_shared(directory):
    base = Path(directory)
    problems = []
    index_path = base / "specs" / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    for slug, entry in sorted(index.items()):
        if entry.get("status") != "implemented":
            continue
        if not (base / "specs" / f"{slug}.md").exists():
            problems.append(f"{slug}: spec file specs/{slug}.md is missing")
        tests = entry.get("tests", [])
        if not tests:
            problems.append(f"{slug}: implemented but lists no regression tests")
        for test in tests:
            if not (base / "regression" / test).exists():
                problems.append(f"{slug}: regression/{test} does not exist")
    listed = {t for e in index.values() for t in e.get("tests", [])}
    for test in sorted((base / "regression").glob("*")) if (base / "regression").exists() else []:
        if test.is_file() and test.name not in listed:
            problems.append(f"regression/{test.name} is not listed in any spec")
    for spec in sorted((base / "specs").glob("*.md")) if (base / "specs").exists() else []:
        if spec.name != "index.md" and not re.search(r"\.(decisions|contract)", spec.name) and spec.stem not in index:
            problems.append(f"specs/{spec.name} is not in specs/index.json")
    return problems
