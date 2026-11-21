"""Knowledge base: deterministic ingest of change records from tracked branches.

Phase A — layout, cursor, keys, records, ingest walk, rebase/dropped handling, scrub.
The ``summarize_change`` hook returns None; Phase B fills it.
"""
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Defaults (applied in code, not schema)
# ---------------------------------------------------------------------------

DEFAULTS = {
    "enabled": True,
    "auto_push": True,
    "backfill_months": 3,
    "max_changes_per_ingest": 200,
    "summarize": True,
    "budget_usd": None,
}

# ---------------------------------------------------------------------------
# PR-key detection patterns
# ---------------------------------------------------------------------------

# GitHub merge commit: "Merge pull request #42 from ..."
_GH_MERGE = re.compile(r"Merge pull request #(\d+)\b")
# Azure DevOps: "Merged PR 42: ..."
_AZURE_MERGE = re.compile(r"Merged PR (\d+)\b")
# Gitea: "Merge pull request 'title' (#42) from ..."
_GITEA_MERGE = re.compile(r"Merge pull request '.*?' \(#(\d+)\)")
# GitLab: "Merge branch '...' into '...'" — no number in the standard message
# Squash commit ending with (#42)
_SQUASH_PR = re.compile(r"\(#(\d+)\)\s*$")

EMAIL_RE = re.compile(r"<[^>]+>")


def extract_pr_number(message):
    """Return the PR/MR number from a commit message, or None."""
    first_line = message.split("\n", 1)[0]
    for pattern in (_GH_MERGE, _AZURE_MERGE, _GITEA_MERGE, _SQUASH_PR):
        m = pattern.search(first_line)
        if m:
            return int(m.group(1))
    return None


def change_key_from_pr(pr_number):
    """Build a change-record key from a PR number."""
    return f"pr-{pr_number}"


def _git(repo_path, *args, check=True):
    """Run a git command in *repo_path*; return CompletedProcess."""
    result = subprocess.run(
        ["git", "-C", str(repo_path)] + list(args),
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo_path}: {result.stderr.strip()}")
    return result


def is_merge_commit(repo_path, sha):
    """Return True if *sha* has a second parent."""
    result = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--verify", "-q", f"{sha}^2"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def compute_patch_id(repo_path, sha):
    """Return the first 12 characters of ``git patch-id --stable`` for *sha*.

    If the commit has no diff (e.g. empty merge), return the sha itself truncated to 12 chars.
    """
    if is_merge_commit(repo_path, sha):
        diff = subprocess.run(
            ["git", "-C", str(repo_path), "diff", f"{sha}^1", sha],
            capture_output=True, text=True,
        )
    else:
        diff = subprocess.run(
            ["git", "-C", str(repo_path), "diff-tree", "-p", sha],
            capture_output=True, text=True,
        )
    if not diff.stdout.strip():
        return sha[:12]
    pid = subprocess.run(
        ["git", "patch-id", "--stable"],
        input=diff.stdout,
        capture_output=True, text=True,
    )
    if pid.returncode != 0 or not pid.stdout.strip():
        return sha[:12]
    return pid.stdout.split()[0][:12]


def change_key_from_patch(repo_path, sha):
    """Build a change-record key from the patch-id of *sha*."""
    return f"p-{compute_patch_id(repo_path, sha)}"


def change_key(repo_path, sha, message):
    """Determine the canonical key for a commit."""
    pr = extract_pr_number(message)
    if pr is not None:
        return change_key_from_pr(pr)
    return change_key_from_patch(repo_path, sha)


# ---------------------------------------------------------------------------
# Author names (never emails)
# ---------------------------------------------------------------------------

def clean_author(author_line):
    """Strip email from an author line, returning the name only."""
    return EMAIL_RE.sub("", author_line).strip()


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

KB_DIR = "knowledge"
CURSOR_FILE = "cursor.json"
INDEX_FILE = "index.json"


def kb_root(shared_dir):
    return Path(shared_dir) / KB_DIR


def cursor_path(shared_dir):
    return kb_root(shared_dir) / CURSOR_FILE


def index_path(shared_dir):
    return kb_root(shared_dir) / INDEX_FILE


def changes_dir(shared_dir, repo_id):
    return kb_root(shared_dir) / "changes" / repo_id


def record_path(shared_dir, repo_id, key, date_str):
    """Path for a change record.  *date_str* is ``YYYY-MM``."""
    return changes_dir(shared_dir, repo_id) / date_str / f"{key}.md"


def ensure_layout(shared_dir):
    """Create the knowledge/ skeleton if it does not exist."""
    root = kb_root(shared_dir)
    root.mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Knowledge base\n\n"
            "Auto-generated by Sentinel. Each file under `changes/` documents one landed change.\n"
            "Provenance: `inferred` = reconstructed from git; `verified` = from a Sentinel run.\n"
        )
    (root / "patterns").mkdir(exist_ok=True)
    patterns_readme = root / "patterns" / "README.md"
    if not patterns_readme.exists():
        patterns_readme.write_text("Curated patterns go here.\n")
    cur = cursor_path(shared_dir)
    if not cur.exists():
        cur.write_text("{}\n")
    idx = index_path(shared_dir)
    if not idx.exists():
        idx.write_text("{}\n")


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------

def read_cursor(shared_dir):
    p = cursor_path(shared_dir)
    if p.exists():
        return json.loads(p.read_text())
    return {}


def write_cursor(shared_dir, cursor):
    p = cursor_path(shared_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cursor, indent=2, sort_keys=True) + "\n")


def cursor_key(repo_id, branch):
    return f"{repo_id}@{branch}"


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def read_index(shared_dir):
    p = index_path(shared_dir)
    if p.exists():
        return json.loads(p.read_text())
    return {}


def write_index(shared_dir, index):
    p = index_path(shared_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Record read / write (YAML front matter + markdown sections)
# ---------------------------------------------------------------------------

def parse_record(text):
    """Parse a change record (YAML front matter + body). Returns (meta, body)."""
    if text.startswith("---\n"):
        end = text.index("\n---\n", 4)
        front = text[4:end]
        body = text[end + 5:]
        return yaml.safe_load(front), body
    return {}, text


def render_record(meta, body):
    """Render a record to text."""
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{front}---\n{body}"


def read_record(path):
    """Read and parse a record file."""
    return parse_record(Path(path).read_text())


def write_record(path, meta, body, scrubber=None):
    """Write a record file, optionally scrubbing the text."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_record(meta, body)
    if scrubber is not None:
        text = scrubber.scrub_text(text)
    path.write_text(text)


# ---------------------------------------------------------------------------
# Diffstat
# ---------------------------------------------------------------------------

def diffstat(repo_path, sha):
    """Return a compact diffstat string for *sha*."""
    if is_merge_commit(repo_path, sha):
        result = _git(repo_path, "diff", "--stat", f"{sha}^1", sha, check=False)
    else:
        result = _git(repo_path, "diff-tree", "--stat", "--no-commit-id", sha, check=False)
    return result.stdout.strip()


def changed_files(repo_path, sha):
    """Return the list of files changed in *sha*."""
    if is_merge_commit(repo_path, sha):
        result = _git(repo_path, "diff", "--name-only", f"{sha}^1", sha, check=False)
    else:
        result = _git(repo_path, "diff-tree", "--no-commit-id", "-r", "--name-only", sha, check=False)
    return [f for f in result.stdout.strip().split("\n") if f]


def top_modules(files):
    """Derive top-level modules from a list of file paths."""
    modules = set()
    for f in files:
        parts = f.split("/")
        if len(parts) >= 2:
            modules.add(parts[0] + "/" + parts[1] if len(parts) >= 3 else parts[0])
        elif parts:
            modules.add(parts[0])
    return sorted(modules)


# ---------------------------------------------------------------------------
# Commit info
# ---------------------------------------------------------------------------

def commit_info(repo_path, sha):
    """Return a dict with message, author, date for *sha*."""
    fmt = "%H%n%an%n%cI%n%B"
    result = _git(repo_path, "log", "-1", f"--format={fmt}", sha)
    lines = result.stdout.split("\n", 3)
    return {
        "sha": lines[0].strip(),
        "author": clean_author(lines[1].strip()),
        "date": lines[2].strip(),
        "message": lines[3].strip() if len(lines) > 3 else "",
    }


# ---------------------------------------------------------------------------
# Summarizer helper and hooks (Phase B)
# ---------------------------------------------------------------------------

def _run_summarizer(config, workspace, prompt, cwd):
    """Run an agent summarizer using the routed runner.

    Uses routing role knowledge -> coder -> default (claude).
    Timeout 300s.
    Returns generated summary text or None on failure/timeout/disabled.
    Never raises.
    """
    kc = kb_config(config or {})
    if not kc.get("summarize", True):
        return None
    if os.environ.get("SENTINEL_KB_NO_AGENT") == "1":
        return None

    if cwd is None:
        with tempfile.TemporaryDirectory() as tmp:
            return _run_summarizer(config, workspace, prompt, tmp)

    try:
        try:
            import run_stage
            import adapters
        except ImportError:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import run_stage
            import adapters

        find_route = run_stage.find_route
        parse_output = run_stage.parse_output

        # Route fallback: knowledge -> coder -> default ("claude")
        route = find_route(config or {}, "knowledge") or find_route(config or {}, "coder")
        if not route:
            routing = (config or {}).get("routing") or {}
            route = routing.get("knowledge") or routing.get("coder")
        runner_id = (route or {}).get("runner") or "claude"
        model = (route or {}).get("model")

        adapter = adapters.get_adapter("cli", config or {}, runner_id=runner_id)
        tdir = Path(cwd) / "task"
        tdir.mkdir(parents=True, exist_ok=True)
        job = adapters.Job(
            task_id=f"kb-summarize-{int(time.time() * 1000)}",
            task_dir=str(tdir),
            workdir=str(cwd),
            prompt=prompt,
            model=model,
        )

        handle = adapter.submit(job)
        if not adapter.wait(handle, timeout=300):
            adapter.cancel(handle)
            adapter.result(handle, timed_out=True)
            return None

        code, stdout, stderr = adapter.result(handle)
        if code != 0:
            return None
        text, _, _ = parse_output(adapter.runner, stdout)
        res = text.strip() if text else None
        return res if res else None
    except Exception:
        return None


def summarize_change(repo_path, sha, files, message, diffstat_text, config=None, workspace=None, scrubber=None):
    """Return an agent-written summary of *sha*, or None when summarization is disabled or fails."""
    kc = kb_config(config or {})
    if not kc.get("summarize", True) or os.environ.get("SENTINEL_KB_NO_AGENT") == "1":
        return None

    if is_merge_commit(repo_path, sha):
        diff_res = _git(repo_path, "diff", f"{sha}^1", sha, check=False)
    else:
        diff_res = _git(repo_path, "diff-tree", "-p", sha, check=False)
    diff = diff_res.stdout if diff_res.returncode == 0 else ""

    # Scrub before truncating, so a secret cut at the limit cannot slip past the patterns
    if scrubber is not None:
        diff = scrubber.scrub_text(diff)

    # Truncate diffs sent to the agent to 20k chars
    if len(diff) > 20000:
        diff = diff[:20000] + "\n... [diff truncated to 20k characters]"

    safe_files = []
    for f in files:
        if scrubber is not None and scrubber.findings(f):
            continue
        safe_files.append(f)

    prompt = (
        "You are a technical documentation assistant summarizing a landed change.\n"
        "READ-ONLY INTENT: Do not edit, create, or delete any files. Inspect the code only.\n\n"
        f"Repository path (read-only): {repo_path}\n"
        f"Commit: {sha}\n"
        f"Files changed: {', '.join(safe_files[:50])}\n"
        f"Message:\n{message}\n\n"
        f"Diffstat:\n{diffstat_text}\n\n"
        f"Diff:\n{diff}\n\n"
        "Provide a concise summary explaining: what behavior changed, why, and any potential risks."
    )
    if scrubber is not None:
        prompt = scrubber.scrub_text(prompt)

    with tempfile.TemporaryDirectory() as tmp_cwd:
        return _run_summarizer(config, workspace, prompt, tmp_cwd)


def summarize_module(repo_path, module_path, files, config=None, workspace=None, scrubber=None, tip=None):
    """Return an agent-written summary of a module or repo, or None when summarization is disabled or fails."""
    kc = kb_config(config or {})
    if not kc.get("summarize", True) or os.environ.get("SENTINEL_KB_NO_AGENT") == "1":
        return None

    safe_files = []
    for f in files:
        path = f["path"] if isinstance(f, dict) else str(f)
        if scrubber is not None and scrubber.findings(path):
            continue
        safe_files.append(path)

    label = f"module `{module_path}`" if module_path else "repository"
    prompt = (
        f"You are a technical documentation assistant summarizing the {label}.\n"
        "READ-ONLY INTENT: Do not edit, create, or delete any files. Inspect the code only.\n\n"
        f"Repository path (read-only): {repo_path}\n"
        f"Target: {module_path or '(root)'}\n"
        f"Files ({len(safe_files)} total):\n" +
        "\n".join(f"- {p}" for p in safe_files[:60]) +
        ("\n... [additional files omitted]" if len(safe_files) > 60 else "") +
        "\n\nProvide a concise summary (2-4 paragraphs) explaining the responsibility of this component, "
        "key files or entry points, and architectural patterns."
    )
    if scrubber is not None:
        prompt = scrubber.scrub_text(prompt)

    with tempfile.TemporaryDirectory() as tmp_cwd:
        return _run_summarizer(config, workspace, prompt, tmp_cwd)


# ---------------------------------------------------------------------------
# Default branch resolution
# ---------------------------------------------------------------------------

def resolve_default_branch(repo_path):
    """Resolve the default branch of *repo_path*: origin/HEAD symbolic ref, else the current HEAD branch."""
    # Try origin/HEAD
    result = _git(repo_path, "symbolic-ref", "refs/remotes/origin/HEAD", check=False)
    if result.returncode == 0 and result.stdout.strip():
        ref = result.stdout.strip()
        # e.g. refs/remotes/origin/main -> main
        return ref.replace("refs/remotes/origin/", "")
    # Fall back to current HEAD branch
    result = _git(repo_path, "rev-parse", "--abbrev-ref", "HEAD", check=False)
    if result.returncode == 0 and result.stdout.strip() and result.stdout.strip() != "HEAD":
        return result.stdout.strip()
    return "main"


def resolve_branch_tip(repo_path, branch):
    """Resolve origin/<branch> (preferred) or local <branch>.  Returns sha or None."""
    for ref in [f"origin/{branch}", branch]:
        result = _git(repo_path, "rev-parse", "--verify", ref, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


# ---------------------------------------------------------------------------
# Reachability check for force-push / rebase handling
# ---------------------------------------------------------------------------

def is_ancestor(repo_path, ancestor, descendant):
    """True when *ancestor* is an ancestor of *descendant*."""
    result = _git(repo_path, "merge-base", "--is-ancestor", ancestor, descendant, check=False)
    return result.returncode == 0


def merge_base(repo_path, a, b):
    """Return the merge-base of *a* and *b*, or None."""
    result = _git(repo_path, "merge-base", a, b, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


# ---------------------------------------------------------------------------
# Mark records as dropped when their reached SHAs are no longer reachable
# ---------------------------------------------------------------------------

def mark_dropped(shared_dir, repo_id, branch, tracked_branches, repo_path):
    """Find records whose reached SHA for *branch* is no longer on any tracked branch; set status=dropped."""
    index = read_index(shared_dir)
    for key, entry in index.items():
        if entry.get("repo") != repo_id:
            continue
        rec_path = entry.get("path")
        if not rec_path:
            continue
        full_path = Path(shared_dir) / rec_path
        if not full_path.exists():
            continue
        meta, body = read_record(full_path)
        if meta.get("status") == "dropped":
            continue
        reached = meta.get("reached", [])
        # Find the reached entry for this branch
        branch_entries = [r for r in reached if r.get("branch") == branch]
        if not branch_entries:
            continue
        sha = branch_entries[0].get("sha", "")
        if not sha:
            continue
        # Check if this SHA is reachable from ANY tracked branch
        reachable = False
        for tb in tracked_branches:
            tip = resolve_branch_tip(repo_path, tb)
            if tip and is_ancestor(repo_path, sha, tip):
                reachable = True
                break
        if not reachable:
            meta["status"] = "dropped"
            write_record(full_path, meta, body)
            entry["status"] = "dropped"
    write_index(shared_dir, index)


# ---------------------------------------------------------------------------
# Upsert a record
# ---------------------------------------------------------------------------

def upsert_record(shared_dir, repo_id, key, branch, sha, info, repo_path, scrubber=None, index=None,
                  config=None, workspace=None):
    """Create or update a change record.

    *info* is a dict from ``commit_info``.  When the record already exists and the branch
    is new for it, ``reached`` gets a second entry.  Returns the record path relative to
    the knowledge root.
    """
    date_str = info["date"][:7]  # YYYY-MM
    if index is None:
        index = read_index(shared_dir)
    files = changed_files(repo_path, sha)
    modules = top_modules(files)
    ds = diffstat(repo_path, sha)
    commit_date = info.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    existing_entry = index.get(key)
    if existing_entry and existing_entry.get("path"):
        full = Path(shared_dir) / existing_entry["path"]
        if full.exists():
            meta, body = read_record(full)
            # Merge reached
            reached = meta.get("reached", [])
            existing_branches = {r.get("branch") for r in reached}
            if branch not in existing_branches:
                reached.append({"branch": branch, "sha": sha, "at": commit_date})
                meta["reached"] = reached
                # Un-drop if it had been dropped and is now on a new branch
                if meta.get("status") == "dropped":
                    meta["status"] = "active"
            else:
                # Update the sha for this branch
                for r in reached:
                    if r.get("branch") == branch:
                        r["sha"] = sha
                        r["at"] = commit_date
                        break
            # Merge files
            existing_files = set(meta.get("files", []))
            existing_files.update(files)
            meta["files"] = sorted(existing_files)
            meta["modules"] = sorted(set(meta.get("modules", [])) | set(modules))
            # Merge authors
            author = clean_author(info.get("author", ""))
            if author:
                existing_authors = meta.get("authors", [])
                if author not in existing_authors:
                    existing_authors.append(author)
                meta["authors"] = existing_authors
            write_record(full, meta, body, scrubber=scrubber)
            # Update index
            entry = existing_entry
            entry["reached"] = meta["reached"]
            entry["shas"] = list(dict.fromkeys(r["sha"] for r in meta["reached"] if r.get("sha")))
            entry["files"] = meta["files"]
            entry["status"] = meta.get("status", "active")
            index[key] = entry
            write_index(shared_dir, index)
            return existing_entry["path"]

    # New record
    rp = str(record_path(shared_dir, repo_id, key, date_str).relative_to(Path(shared_dir)))
    author = clean_author(info.get("author", ""))
    title = info["message"].split("\n", 1)[0][:200]
    meta = {
        "key": key,
        "repo": repo_id,
        "provenance": "inferred",
        "status": "active",
        "reached": [{"branch": branch, "sha": sha, "at": commit_date}],
        "authors": [author] if author else [],
        "title": title,
        "files": sorted(files),
        "modules": modules,
        "run": None,
        "spec": None,
    }
    # Build body
    body_parts = ["\n## What changed\n"]
    body_parts.append(f"{info['message']}\n")
    if ds:
        body_parts.append(f"\n```\n{ds}\n```\n")
    # Summarize hook
    summary = summarize_change(repo_path, sha, files, info["message"], ds,
                               config=config, workspace=workspace, scrubber=scrubber)
    if summary:
        body_parts.append(f"\n## Summary\n{summary}\n")
    body = "\n".join(body_parts)

    write_record(Path(shared_dir) / rp, meta, body, scrubber=scrubber)

    # Update index
    index[key] = {
        "path": rp,
        "repo": repo_id,
        "reached": meta["reached"],
        "shas": [sha],
        "provenance": "inferred",
        "status": "active",
        "files": sorted(files),
    }
    write_index(shared_dir, index)
    return rp


# ---------------------------------------------------------------------------
# First-parent walk
# ---------------------------------------------------------------------------

def first_parent_commits(repo_path, since_sha, until_sha):
    """Yield (sha, message) of first-parent commits from *since_sha* (exclusive) to *until_sha* (inclusive), oldest first."""
    if since_sha:
        rev_range = f"{since_sha}..{until_sha}"
    else:
        rev_range = until_sha
    result = _git(
        repo_path, "log", "--first-parent", "--reverse",
        "--format=%H%n%B%n---END---",
        rev_range,
        check=False,
    )
    if result.returncode != 0:
        return
    entries = result.stdout.split("\n---END---\n")
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        lines = entry.split("\n", 1)
        sha = lines[0].strip()
        message = lines[1].strip() if len(lines) > 1 else ""
        if sha and len(sha) >= 7:
            yield sha, message


def backfill_start_sha(repo_path, branch_tip, months):
    """Find the first commit newer than now - *months* months on the first-parent chain."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
    result = _git(
        repo_path, "log", "--first-parent", "--reverse",
        f"--since={cutoff_str}",
        "--format=%H",
        branch_tip,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    first = result.stdout.strip().split("\n")[0].strip()
    # Return the parent of the first commit in range so the walk is exclusive of this sha
    parent = _git(repo_path, "rev-parse", f"{first}^", check=False)
    if parent.returncode == 0 and parent.stdout.strip():
        return parent.stdout.strip()
    return None


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def kb_config(config):
    """Return merged knowledge config with defaults."""
    raw = config.get("knowledge") or {}
    merged = dict(DEFAULTS)
    for k, v in raw.items():
        if v is not None:
            merged[k] = v
    return merged


def repo_branches(repo_cfg, repo_path):
    """Return the list of tracked branches for a repo config entry."""
    kb = repo_cfg.get("knowledge") or {}
    branches = kb.get("branches")
    if branches:
        return list(branches)
    return [resolve_default_branch(repo_path)]


# ---------------------------------------------------------------------------
# Ingest one repo, one branch
# ---------------------------------------------------------------------------

def ingest_branch(shared_dir, repo_id, repo_path, branch, config, scrubber=None,
                  tracked_branches=None, workspace=None):
    """Walk the first-parent chain of *branch* and upsert change records.

    Returns the number of changes processed.
    """
    kc = kb_config(config)
    cap = kc["max_changes_per_ingest"]
    backfill_months = kc["backfill_months"]

    tip = resolve_branch_tip(repo_path, branch)
    if tip is None:
        return 0

    cursor = read_cursor(shared_dir)
    ck = cursor_key(repo_id, branch)
    cursor_sha = (cursor.get(ck) or {}).get("sha")

    # Rebase / force-push detection
    if cursor_sha:
        if not is_ancestor(repo_path, cursor_sha, tip):
            # Cursor SHA not an ancestor of tip — force-push/rebase
            mb = merge_base(repo_path, cursor_sha, tip)
            # Mark dropped
            if tracked_branches:
                mark_dropped(shared_dir, repo_id, branch, tracked_branches, repo_path)
            cursor_sha = mb  # Restart from merge-base

    # Backfill if no cursor
    if not cursor_sha:
        cursor_sha = backfill_start_sha(repo_path, tip, backfill_months)

    index = read_index(shared_dir)
    sha_to_keys = {}
    for k, entry in index.items():
        if entry.get("repo") == repo_id:
            for s in (entry.get("shas") or []):
                sha_to_keys.setdefault(s, []).append(k)

    count = 0
    for sha, message in first_parent_commits(repo_path, cursor_sha, tip):
        if count >= cap:
            break
        info = commit_info(repo_path, sha)

        is_promotion = False
        if is_merge_commit(repo_path, sha):
            rev_res = _git(repo_path, "rev-list", f"{sha}^1..{sha}^2", check=False)
            brought_in = [s for s in rev_res.stdout.strip().split("\n") if s.strip()] if rev_res.returncode == 0 else []
            matched_keys = set()
            for s in brought_in:
                if s in sha_to_keys:
                    for k in sha_to_keys[s]:
                        matched_keys.add(k)
            if matched_keys:
                is_promotion = True
                commit_date = info.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                for k in sorted(matched_keys):
                    entry = index.get(k)
                    if not entry or not entry.get("path"):
                        continue
                    full = Path(shared_dir) / entry["path"]
                    if not full.exists():
                        continue
                    meta, body = read_record(full)
                    reached = meta.get("reached", [])
                    if not any(r.get("branch") == branch for r in reached):
                        reached.append({"branch": branch, "sha": sha, "at": commit_date})
                        meta["reached"] = reached
                        if meta.get("status") == "dropped":
                            meta["status"] = "active"
                        write_record(full, meta, body, scrubber=scrubber)
                        entry["reached"] = meta["reached"]
                        entry["status"] = meta.get("status", "active")
                        shas_list = list(dict.fromkeys(r["sha"] for r in meta["reached"] if r.get("sha")))
                        entry["shas"] = shas_list
                        if k not in sha_to_keys.setdefault(sha, []):
                            sha_to_keys[sha].append(k)
                write_index(shared_dir, index)

        if not is_promotion:
            key = change_key(repo_path, sha, message)
            upsert_record(shared_dir, repo_id, key, branch, sha, info, repo_path,
                          scrubber=scrubber, index=index, config=config, workspace=workspace)
            if key in index:
                for s in index[key].get("shas", []):
                    if key not in sha_to_keys.setdefault(s, []):
                        sha_to_keys[s].append(key)

        # Advance cursor after each change
        cursor = read_cursor(shared_dir)
        cursor[ck] = {"sha": sha, "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        write_cursor(shared_dir, cursor)
        count += 1

    return count


# ---------------------------------------------------------------------------
# Ingest all repos
# ---------------------------------------------------------------------------

def ingest(shared_dir, workspace, config, scrubber=None, only_repo=None, only_branch=None,
           no_summarize=False):
    """Run ingest for all configured repos (or a subset).

    Returns ``{repo_id: {branch: count}}``.
    """
    ensure_layout(shared_dir)
    if no_summarize:
        config = dict(config)
        kc = dict(config.get("knowledge") or {})
        kc["summarize"] = False
        config["knowledge"] = kc
    results = {}
    for repo_cfg in config.get("repos", []):
        repo_id = repo_cfg["id"]
        if only_repo and repo_id != only_repo:
            continue
        repo_path = (Path(workspace) / repo_cfg["path"]).resolve()
        if not repo_path.exists():
            continue
        branches = repo_branches(repo_cfg, repo_path)
        repo_results = {}
        for branch in branches:
            if only_branch and branch != only_branch:
                continue
            count = ingest_branch(
                shared_dir, repo_id, repo_path, branch, config,
                scrubber=scrubber, tracked_branches=branches,
                workspace=workspace,
            )
            repo_results[branch] = count
        results[repo_id] = repo_results
    return results


# ---------------------------------------------------------------------------
# Backfill estimate
# ---------------------------------------------------------------------------

def estimate_backfill(shared_dir, workspace, config, since=None, only_repo=None):
    """Estimate the number of changes that backfill would process.

    Returns ``{repo_id: {branch: count}}``.
    """
    kc = kb_config(config)
    if since:
        cutoff_str = since
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=kc["backfill_months"] * 30)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

    results = {}
    for repo_cfg in config.get("repos", []):
        repo_id = repo_cfg["id"]
        if only_repo and repo_id != only_repo:
            continue
        repo_path = (Path(workspace) / repo_cfg["path"]).resolve()
        if not repo_path.exists():
            continue
        branches = repo_branches(repo_cfg, repo_path)
        repo_results = {}
        for branch in branches:
            tip = resolve_branch_tip(repo_path, branch)
            if not tip:
                continue
            result = _git(
                repo_path, "log", "--first-parent", "--oneline",
                f"--since={cutoff_str}",
                tip,
                check=False,
            )
            count = len([l for l in result.stdout.strip().split("\n") if l.strip()]) if result.stdout.strip() else 0
            repo_results[branch] = count
        results[repo_id] = repo_results
    return results


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def status(shared_dir, config):
    """Return a dict with cursor state, record counts, etc."""
    cursor = read_cursor(shared_dir)
    index = read_index(shared_dir)
    total = len(index)
    active = sum(1 for e in index.values() if e.get("status") != "dropped")
    dropped = total - active
    repos = {}
    for entry in index.values():
        repo = entry.get("repo", "unknown")
        repos[repo] = repos.get(repo, 0) + 1
    return {
        "cursors": cursor,
        "records": {"total": total, "active": active, "dropped": dropped},
        "by_repo": repos,
    }


# ---------------------------------------------------------------------------
# Module discovery and snapshot summaries (Phase B)
# ---------------------------------------------------------------------------

COMMON_SOURCE_ROOTS = {"src", "app", "lib", "packages"}

ENTRY_POINT_NAMES = {
    "main.py", "app.py", "cli.py", "server.py", "run.py", "index.js", "index.ts",
    "main.go", "main.rs", "Main.java", "Application.java", "manage.py",
    "Dockerfile", "setup.py", "pyproject.toml", "package.json", "Makefile",
    "CMakeLists.txt", "pom.xml", "build.gradle",
}


def _git_tree_entries(repo_path, tip, subpath=None):
    """Return list of (mode, type, sha, name) for a tree ref."""
    ref = f"{tip}:{subpath}" if subpath else tip
    res = _git(repo_path, "ls-tree", ref, check=False)
    if res.returncode != 0 or not res.stdout.strip():
        return []
    entries = []
    for line in res.stdout.strip().split("\n"):
        if not line.strip() or "\t" not in line:
            continue
        meta_part, name = line.split("\t", 1)
        tokens = meta_part.split()
        if len(tokens) >= 3:
            entries.append((tokens[0], tokens[1], tokens[2], name))
    return entries


def _git_subdirs(repo_path, tip, subpath=None):
    """Return list of subdirectory names under *subpath* at *tip*."""
    entries = _git_tree_entries(repo_path, tip, subpath)
    return [e[3] for e in entries if e[1] == "tree"]


def find_modules_at_tip(repo_path, tip):
    """Discover module paths at *tip* of *repo_path*.

    Modules are top-level directories in the repository. For common source roots
    ('src', 'app', 'lib', 'packages', and common nested roots like 'src/main/java'),
    the module boundary walks down the single-child directory chain until reaching
    the first directory level below the root that has more than one child (or reaches
    a leaf directory), and uses those children as modules.
    """
    top_dirs = [d for d in _git_subdirs(repo_path, tip) if not d.startswith(".")]
    modules = []
    for d in sorted(top_dirs):
        if d in COMMON_SOURCE_ROOTS:
            curr = d
            while True:
                children = _git_subdirs(repo_path, tip, curr)
                if len(children) > 1:
                    for child in sorted(children):
                        modules.append(f"{curr}/{child}")
                    break
                elif len(children) == 1:
                    curr = f"{curr}/{children[0]}"
                else:
                    modules.append(curr)
                    break
        else:
            modules.append(d)
    return sorted(modules)


def _git_tree_files(repo_path, tip, subpath=None):
    """Return list of dicts for blob files: [{'path': str, 'size': int, 'sha': str}]."""
    cmd = ["ls-tree", "-r", "-l", tip]
    if subpath:
        cmd += ["--", subpath]
    res = _git(repo_path, *cmd, check=False)
    if res.returncode != 0 or not res.stdout.strip():
        return []
    files = []
    for line in res.stdout.strip().split("\n"):
        if not line.strip() or "\t" not in line:
            continue
        meta_part, path = line.split("\t", 1)
        tokens = meta_part.split()
        if len(tokens) >= 4 and tokens[1] == "blob":
            size = int(tokens[3]) if tokens[3].isdigit() else 0
            files.append({"path": path, "size": size, "sha": tokens[2]})
    return files


def _render_deterministic_body(files, label, modules=None):
    """Build markdown overview of files: count, languages, entry points, test dirs, largest files."""
    file_count = len(files)
    ext_counts = {}
    entry_points = []
    test_dirs = set()

    for f in files:
        p = Path(f["path"])
        ext = p.suffix.lower() if p.suffix else "(no extension)"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

        name = p.name
        stem = p.stem.lower()
        if (name in ENTRY_POINT_NAMES or
            (len(p.parts) > 1 and p.parts[0] in ("bin", "cmd")) or
            stem in ("main", "app", "cli", "server", "index", "run")):
            entry_points.append(f["path"])

        parts = p.parts
        for i, part in enumerate(parts[:-1]):
            if any(term in part.lower() for term in ("test", "spec")):
                test_dirs.add("/".join(parts[:i + 1]))

    sorted_exts = sorted(ext_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ext_str = ", ".join(f"{ext}: {cnt}" for ext, cnt in sorted_exts[:10]) if sorted_exts else "none"
    entry_str = ", ".join(f"`{ep}`" for ep in sorted(set(entry_points))[:10]) if entry_points else "none"
    test_str = ", ".join(f"`{td}`" for td in sorted(test_dirs)) if test_dirs else "none"

    largest = sorted(files, key=lambda f: f["size"], reverse=True)[:5]
    largest_lines = "\n".join(f"- `{f['path']}` ({f['size']} bytes)" for f in largest) if largest else "- none"

    lines = [
        "\n## Overview\n",
        f"- **Files**: {file_count}",
        f"- **Languages**: {ext_str}",
        f"- **Entry points**: {entry_str}",
        f"- **Test directories**: {test_str}",
    ]
    if modules:
        mod_str = ", ".join(f"`{m}`" for m in sorted(modules))
        lines.append(f"- **Modules**: {mod_str}")

    lines.append(f"\n### Largest files\n{largest_lines}\n")
    return "\n".join(lines)


def snapshot_repo(shared_dir, workspace, repo_cfg, config, scrubber=None, force=False):
    """Build knowledge/repos/<repo>/summary.md and modules/<module-path>.md from summary branch tip."""
    repo_id = repo_cfg["id"]
    repo_path = (Path(workspace) / repo_cfg["path"]).resolve()
    if not repo_path.exists():
        return {}

    branches = repo_branches(repo_cfg, repo_path)
    summary_branch = branches[0] if branches else resolve_default_branch(repo_path)
    tip = resolve_branch_tip(repo_path, summary_branch)
    if not tip:
        return {}

    root_tree_res = _git(repo_path, "rev-parse", f"{tip}^{{tree}}", check=False)
    if root_tree_res.returncode != 0:
        return {}
    root_tree = root_tree_res.stdout.strip()

    repo_kb_dir = Path(shared_dir) / KB_DIR / "repos" / repo_id
    modules_dir = repo_kb_dir / "modules"
    repo_kb_dir.mkdir(parents=True, exist_ok=True)
    modules_dir.mkdir(parents=True, exist_ok=True)

    current_modules = find_modules_at_tip(repo_path, tip)
    current_module_set = set(current_modules)

    # Delete module files whose directory no longer exists
    if modules_dir.exists():
        for existing in list(modules_dir.rglob("*.md")):
            rel = existing.relative_to(modules_dir)
            mod_path = str(rel.with_suffix("")).replace("\\", "/")
            if mod_path not in current_module_set:
                existing.unlink()
        for p in sorted(modules_dir.rglob("*"), reverse=True):
            if p.is_dir() and not any(p.iterdir()):
                try:
                    p.rmdir()
                except OSError:
                    pass

    # Snapshot each module
    generated_modules = []
    for mod_path in current_modules:
        mod_file = modules_dir / f"{mod_path}.md"
        tree_res = _git(repo_path, "rev-parse", f"{tip}:{mod_path}", check=False)
        if tree_res.returncode != 0:
            continue
        mod_tree = tree_res.stdout.strip()

        if mod_file.exists() and not force:
            meta, _ = parse_record(mod_file.read_text())
            if meta.get("source_tree") == mod_tree:
                # Unchanged module skipped
                continue

        files = _git_tree_files(repo_path, tip, subpath=mod_path)
        body = _render_deterministic_body(files, mod_path)
        meta = {
            "module": mod_path,
            "repo": repo_id,
            "branch": summary_branch,
            "tip": tip,
            "source_tree": mod_tree,
        }
        summary = summarize_module(repo_path, mod_path, files, config=config,
                                   workspace=workspace, scrubber=scrubber, tip=tip)
        if summary:
            body += f"\n\n## Summary\n{summary}\n"

        write_record(mod_file, meta, body, scrubber=scrubber)
        generated_modules.append(mod_path)

    # Snapshot summary.md
    summary_file = repo_kb_dir / "summary.md"
    regenerate_summary = True
    if summary_file.exists() and not force:
        meta, _ = parse_record(summary_file.read_text())
        if meta.get("source_tree") == root_tree:
            regenerate_summary = False

    if regenerate_summary:
        all_files = _git_tree_files(repo_path, tip)
        body = _render_deterministic_body(all_files, repo_id, modules=current_modules)
        meta = {
            "repo": repo_id,
            "branch": summary_branch,
            "tip": tip,
            "source_tree": root_tree,
        }
        summary = summarize_module(repo_path, "", all_files, config=config,
                                   workspace=workspace, scrubber=scrubber, tip=tip)
        if summary:
            body += f"\n\n## Summary\n{summary}\n"

        write_record(summary_file, meta, body, scrubber=scrubber)

    return {
        "repo": repo_id,
        "branch": summary_branch,
        "tip": tip,
        "modules": current_modules,
        "generated": generated_modules,
    }


def refresh_summaries(shared_dir, workspace, config, scrubber=None):
    """Snapshot every configured repo (non-forced)."""
    results = {}
    for repo_cfg in (config.get("repos") or []):
        res = snapshot_repo(shared_dir, workspace, repo_cfg, config, scrubber=scrubber, force=False)
        if res:
            results[repo_cfg["id"]] = res
    return results
