"""Path-level write scopes (PD-01): glob matching, profile and repo globs, path classes.

A write scope is a list of workspace-relative globs that start with a repo id ("backend/src/main/**"). Matching is
case-sensitive and segment-aware: "*" and "?" stay inside one path segment, "**" as a whole segment spans any number of
segments (also none), dotfiles are matched like any other file. Test and production globs are repo-relative
("src/test/**"); a repo entry overrides the profile key by key. The 0.1 stage boundary (boundary.py) never uses this.
Source: plan/v1.1/phaseD/README.md points 14, 15 and 18, docs/contracts/configuration-schemas.md.
"""
import re
from functools import lru_cache

from errors import SentinelError

GLOB_KEYS = ("test_globs", "production_globs")
INFRA_KEY = "test_infra_globs"  # test runner config and hooks: nobody but a human may change them during Green or Refactor


@lru_cache(maxsize=1024)
def _regex(glob):
    out, i, n = [], 0, len(glob)
    while i < n:
        c = glob[i]
        if c == "*":
            if glob[i:i + 2] == "**" and (i == 0 or glob[i - 1] == "/") and (i + 2 == n or glob[i + 2] == "/"):
                if i + 2 < n:
                    out.append("(?:.*/)?")
                    i += 3
                else:
                    out.append(".*")
                    i += 2
                continue
            while i + 1 < n and glob[i + 1] == "*":
                i += 1
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            end = glob.find("]", i + 2 if glob[i + 1:i + 2] in ("!", "]") else i + 1)
            if end == -1:
                out.append(re.escape(c))
            else:
                body = glob[i + 1:end]
                neg = body.startswith("!")
                body = body[1:] if neg else body
                out.append("[" + ("^" if neg else "") + body.replace("\\", "\\\\") + "]")
                i = end
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out), re.DOTALL)


def glob_match(glob, path):
    """True when `path` (no leading slash, "/" separators) matches the whole glob."""
    return _regex(glob).fullmatch(path) is not None


def path_allowed(scope, repo_id, path):
    """True when the repo-relative `path` of `repo_id` matches a glob of the workspace-relative `scope`. Empty scope: no."""
    full = f"{repo_id}/{path}"
    return any(glob_match(g, full) for g in scope or ())


def glob_problem(value):
    """Why a glob list is not valid, or None."""
    if not isinstance(value, list):
        return "must be a list of globs"
    for glob in value:
        if not isinstance(glob, str) or not glob:
            return "every glob must be a non-empty string"
        if glob.startswith("/"):
            return f"{glob!r} must be repo-relative, not absolute"
        if ".." in glob.split("/"):
            return f"{glob!r} must stay inside the repo"
    return None


def config_problems(config):
    """[(field, text)] for invalid repos[].test_globs and production_globs, field as "repos[backend].test_globs"."""
    found = []
    for i, repo in enumerate((config or {}).get("repos") or []):
        if not isinstance(repo, dict):
            continue
        name = repo.get("id") if isinstance(repo.get("id"), str) else i
        for key in GLOB_KEYS + (INFRA_KEY,):
            if key in repo:
                why = glob_problem(repo[key])
                if why:
                    found.append((f"repos[{name}].{key}", f"repos[{name}].{key}: {why}"))
    return found


def _repo(config, repo_id):
    return next((r for r in (config or {}).get("repos") or [] if isinstance(r, dict) and r.get("id") == repo_id), None)


def effective_globs(config, repo_id):
    """{"test_globs": [...], "production_globs": [...], "test_infra_globs": [...]}: the repo entry's key if it has one, else the
    profile's, else []. Only the first two are required (missing_globs)."""
    from render_stage import load_profile
    repo = _repo(config, repo_id) or {}
    profile = load_profile(repo["profile"]) if repo.get("profile") else {}
    return {key: list(repo[key]) if key in repo else list(profile.get(key) or []) for key in GLOB_KEYS + (INFRA_KEY,)}


def missing_globs(config, repo_id):
    """Name of the first of test_globs and production_globs that is empty for the repo, else None."""
    globs = effective_globs(config, repo_id)
    return next((key for key in GLOB_KEYS if not globs[key]), None)


def classify(config, repo_id, path):
    """"test", "production" or "other" for a repo-relative path. A path matching both lists is a test file."""
    globs = effective_globs(config, repo_id)
    if any(glob_match(g, path) for g in globs["test_globs"]):
        return "test"
    if any(glob_match(g, path) for g in globs["production_globs"]):
        return "production"
    return "other"


def is_test_infra(config, repo_id, path):
    """True when the repo-relative `path` is test runner configuration or a test hook (conftest.py, pytest.ini, ...)."""
    return any(glob_match(g, path) for g in effective_globs(config, repo_id)[INFRA_KEY])


def scope_globs(config, repo_id, kind):
    """Workspace-relative scope globs of a repo for "tests", "production" or "both"."""
    globs = effective_globs(config, repo_id)
    keys = {"tests": ("test_globs",), "production": ("production_globs",), "both": GLOB_KEYS}[kind]
    return [f"{repo_id}/{g}" for key in keys for g in globs[key]]


def check_widening(role, requested, allowed):
    """E_POLICY unless every requested glob is one of `allowed` or sits under an allowed "<prefix>/**" (TDD-08).
    No authorization exists yet, so a wider scope is always refused."""
    for glob in requested:
        under = ".." not in glob.split("/") and any(a.endswith("/**") and glob.startswith(a[:-2]) for a in allowed)
        if glob not in allowed and not under:
            raise SentinelError("E_POLICY", f"{role} task may not write {glob}", {"role": role, "glob": glob})


TOOL_KEYS = ("targeted_test", "selector", "selector_join", "test_report", "scenario_ref", "summary_patterns")


def test_tools(config, repo_id):
    """Test tooling of a repo (CFG-10): {"test": full command, "targeted_test", "selector", "selector_join",
    "test_report", "scenario_ref", "summary_patterns", "failure_patterns"}. A repo entry overrides the profile key by key; failure_patterns merge per class."""
    from render_stage import load_profile, repo_commands
    repo = _repo(config, repo_id) or {}
    profile = load_profile(repo["profile"]) if repo.get("profile") else {}
    out = {key: repo.get(key) if key in repo else profile.get(key) for key in TOOL_KEYS}
    out["test"] = repo_commands(repo, profile).get("test") or ""
    patterns = {}
    for source in (profile.get("failure_patterns"), repo.get("failure_patterns")):
        for klass, items in (source or {}).items():
            patterns[klass] = list(dict.fromkeys(patterns.get(klass, []) + list(items or [])))
    out["failure_patterns"] = patterns
    return out
