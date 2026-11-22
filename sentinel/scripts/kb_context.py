"""Knowledge base prompt context injection for Sentinel v2 tasks.

Adds a ## Project knowledge section to task prompts, listing relevant repository summaries,
module summaries, shared invariants, and recent change records overlapping the task's write scope.
Read-only, silently skipping missing files, and capped at 6000 characters total.
"""
from pathlib import Path
import yaml

import knowledge
from scheduler import globs_overlap

MAX_TOTAL_CHARS = 6000
MAX_EXCERPT_CHARS = 1000


def _module_overlaps_scope(repo, mod_path, write_scope):
    """Check if a module path in `repo` overlaps any glob in `write_scope`."""
    if not write_scope or not mod_path:
        return False
    candidates = [
        f"{repo}/{mod_path}",
        mod_path,
    ]
    if "-" in mod_path:
        mod_slashed = mod_path.replace("-", "/")
        candidates.extend([f"{repo}/{mod_slashed}", mod_slashed])
    for w in write_scope:
        for c in candidates:
            if globs_overlap(w, c):
                return True
    return False


def _read_file_excerpt(path, max_chars=MAX_EXCERPT_CHARS):
    """Read a file and return a short excerpt; returns None if file is missing or unreadable."""
    try:
        p = Path(path)
        if not p.is_file():
            return None
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    # Strip YAML front matter if present to focus on the human content
    if text.startswith("---\n"):
        idx = text.find("\n---\n", 4)
        if idx != -1:
            body = text[idx + 5:].strip()
            if body:
                text = body
    excerpt = text.strip()
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars - 3] + "..."
    return excerpt


def _latest_reached_at(entry):
    """Find the latest reached `at` timestamp string for a record in index.json."""
    reached = entry.get("reached") or []
    ats = [r.get("at", "") for r in reached if isinstance(r, dict) and r.get("at")]
    return max(ats) if ats else ""


def _change_record_overlaps_scope(entry, write_scope, shared_dir=None):
    """True if any module of this change record overlaps the task write scope."""
    if not write_scope:
        return False
    repo = entry.get("repo", "")
    modules = entry.get("modules")
    if not modules:
        modules = knowledge.top_modules(entry.get("files") or [])
    if not modules and shared_dir and entry.get("path"):
        rec_path = Path(shared_dir) / entry["path"]
        if rec_path.is_file():
            try:
                meta, _ = knowledge.read_record(rec_path)
                modules = meta.get("modules") or []
            except Exception:
                pass
    for m in modules or []:
        if _module_overlaps_scope(repo, m, write_scope):
            return True
    return False


def collect_project_knowledge(workspace, config, repos, write_scope, shared_dir):
    """Collect structured project knowledge (records, summaries, invariants) relevant to the task."""
    try:
        kc = knowledge.kb_config(config)
        if not kc.get("enabled", True):
            return {"invariants": [], "records": [], "summaries": []}
        shared_dir = Path(shared_dir)
        if not shared_dir.is_dir():
            return {"invariants": [], "records": [], "summaries": []}

        summaries = []
        # 1. Repo summary
        for repo in repos or []:
            sum_path = shared_dir / "knowledge" / "repos" / repo / "summary.md"
            excerpt = _read_file_excerpt(sum_path)
            if excerpt:
                summaries.append({
                    "module": None,
                    "path": str(sum_path.resolve()),
                    "repo": repo,
                    "text": excerpt,
                })

        # 2. Module summaries overlapping write_scope
        for repo in repos or []:
            modules_dir = shared_dir / "knowledge" / "repos" / repo / "modules"
            if not modules_dir.is_dir():
                continue
            for p in sorted(modules_dir.rglob("*.md")):
                if not p.is_file():
                    continue
                meta = {}
                try:
                    content = p.read_text(encoding="utf-8")
                    if content.startswith("---\n"):
                        idx = content.find("\n---\n", 4)
                        if idx != -1:
                            meta = yaml.safe_load(content[4:idx]) or {}
                except Exception:
                    pass
                mod_path = meta.get("module") or meta.get("path")
                if not mod_path:
                    mod_path = str(p.relative_to(modules_dir).with_suffix("")).replace("\\", "/")
                if _module_overlaps_scope(repo, mod_path, write_scope):
                    excerpt = _read_file_excerpt(p)
                    if excerpt:
                        summaries.append({
                            "module": mod_path,
                            "path": str(p.resolve()),
                            "repo": repo,
                            "text": excerpt,
                        })

        # 3. invariants.md
        inv_path = shared_dir / "invariants.md"
        invariants = []
        inv_excerpt = _read_file_excerpt(inv_path)
        if inv_excerpt:
            parsed = knowledge.parse_invariants(shared_dir)
            if parsed:
                invariants.extend(parsed)
            else:
                invariants.append({
                    "id": "INV-1",
                    "path": "invariants.md",
                    "rule": inv_excerpt[:200],
                    "text": inv_excerpt,
                })

        # 4. 5 newest change records whose modules overlap write_scope
        index = {}
        try:
            index = knowledge.read_index(shared_dir)
        except Exception:
            pass

        matching_records = []
        for key, entry in index.items():
            if not isinstance(entry, dict):
                continue
            if _change_record_overlaps_scope(entry, write_scope, shared_dir):
                matching_records.append((key, entry, _latest_reached_at(entry)))

        matching_records.sort(key=lambda item: item[2], reverse=True)

        records = []
        for key, entry, reached_at in matching_records[:5]:
            rp = entry.get("path")
            if not rp:
                continue
            rec_path = shared_dir / rp
            excerpt = _read_file_excerpt(rec_path)
            meta = {}
            if rec_path.is_file():
                try:
                    meta, _ = knowledge.read_record(rec_path)
                except Exception:
                    pass
            date_str = meta.get("date") or entry.get("date") or reached_at
            records.append({
                "date": date_str,
                "key": key,
                "path": str(rec_path.resolve()),
                "repo": entry.get("repo", ""),
                "summary": meta.get("summary") or entry.get("summary", ""),
                "text": excerpt or "",
                "title": meta.get("title") or entry.get("title", ""),
            })

        return {
            "invariants": invariants,
            "records": records,
            "summaries": summaries,
        }
    except Exception:
        return {"invariants": [], "records": [], "summaries": []}


def format_project_knowledge(k_data, shared_dir=None):
    """Format structured knowledge items into the ## Project knowledge prompt markdown."""
    blocks = []
    for s in k_data.get("summaries") or []:
        if s.get("text") and s.get("path"):
            blocks.append(f"### {Path(s['path']).resolve()}\n\n{s['text']}")
    if k_data.get("invariants") and shared_dir:
        inv_path = Path(shared_dir) / "invariants.md"
        inv_excerpt = _read_file_excerpt(inv_path)
        if inv_excerpt:
            blocks.append(f"### {inv_path.resolve()}\n\n{inv_excerpt}")
    for r in k_data.get("records") or []:
        if r.get("text") and r.get("path"):
            blocks.append(f"### {Path(r['path']).resolve()}\n\n{r['text']}")

    if not blocks:
        return ""
    text = "## Project knowledge\n\n" + "\n\n".join(blocks)
    if len(text) > MAX_TOTAL_CHARS:
        text = text[:MAX_TOTAL_CHARS - 3] + "..."
    return text


def render_project_knowledge(workspace, config, repos, write_scope, shared_dir):
    """Build the ## Project knowledge prompt section. Returns '' if disabled, missing, or empty."""
    try:
        shared_dir = Path(shared_dir)
        k_data = collect_project_knowledge(workspace, config, repos, write_scope, shared_dir)
        return format_project_knowledge(k_data, shared_dir=shared_dir)
    except Exception:  # Read-only: missing files are skipped silently, never raise
        return ""


kb_context = render_project_knowledge

