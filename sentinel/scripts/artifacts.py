"""Spec and Gherkin artifacts: hashing, validators, coverage table, stored copies.

Pure functions plus small file helpers. Format rules: docs/contracts/configuration-schemas.md
sections 2 and 3, data-architecture section 4, plan/v1.1/phaseB/README.md open points 3 to 16.
"""
import hashlib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from errors import SentinelError

LITE = ["Problem statement", "Scope", "Out of scope", "Functional requirements",
        "Acceptance criteria", "Edge cases", "Security considerations", "Risks and assumptions"]
FULL = ["Problem statement", "Objectives", "Scope", "Out of scope", "Functional requirements",
        "Non-functional requirements", "Acceptance criteria", "Business rules", "Edge cases",
        "Validation rules", "Security considerations", "API or interface changes", "Database changes",
        "Dependencies", "Risks and assumptions", "Expected deliverables"]
DOCS_ONLY = ["Problem statement", "Scope", "Expected deliverables"]

CATEGORIES = ["happy-path", "invalid-input", "missing-fields", "boundary", "empty-null", "authn", "authz",
              "data-integrity", "duplicate", "concurrency", "errors", "external-failure", "db-failure",
              "regression", "perf-security"]
TYPE_TAGS = {"unit", "integration", "e2e", "contract", "security", "performance", "regression"}
PRIORITY_TAGS = {"P1", "P2", "P3"}


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    data: dict = field(default_factory=dict)

    @property
    def ok(self):
        return not self.errors


# ---------------------------------------------------------------- hashing

def _sha(data):
    return hashlib.sha256(data).hexdigest()


def spec_hash(path):
    """sha256 over the raw bytes of the spec file. No normalization."""
    p = Path(path)
    try:
        return _sha(p.read_bytes())
    except FileNotFoundError:
        raise SentinelError("E_NOT_FOUND", f"{p.name} not found", {"path": str(p)}) from None


def _feature_files(features_dir):
    d = Path(features_dir)
    if not d.is_dir():
        return []
    base = d.parent
    items = [(p.relative_to(base).as_posix(), p) for p in d.rglob("*.feature") if p.is_file()]
    return sorted(items, key=lambda x: x[0].encode("utf-8"))


def gherkin_set_hash(features_dir):
    """(hash, relative paths). Paths are relative to specs/<slug>/, in UTF-8 byte order."""
    h = hashlib.sha256()
    paths = []
    for rel, p in _feature_files(features_dir):
        h.update(rel.encode("utf-8") + b"\0" + p.read_bytes() + b"\0")
        paths.append(rel)
    return h.hexdigest(), paths


# ---------------------------------------------------------------- spec

_H2 = re.compile(r"^##(?!#)[ \t]+(.+?)[ \t]*$")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])?\s*\**\s*(REQ|AC)-([^\s(:*,]+)\**\s*(?:\(([^)]*)\))?")
_NA = re.compile(r"^\s*not applicable\b(.*)$", re.I | re.S)
_NA_LINE = re.compile(r"^\s*[-*+]\s*n/a\s+@cov-([\w-]+)\s*:?\s*(.*?)\s*$", re.I)


def _norm(name):
    return " ".join(name.lower().split())


def _split_front_matter(text):
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text, re.S)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def _sections(body):
    """Map normalized heading to (display name, text). First occurrence wins."""
    out = {}
    cur = None
    fence = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        m = None if fence else _H2.match(line)
        if m:
            cur = _norm(m.group(1))
            out.setdefault(cur, [])
            continue
        if cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def _load_front_matter(raw):
    """(mapping or None, error or None) for the raw front matter text."""
    if raw is None:
        return None, "missing front matter"
    try:
        fm = yaml.safe_load(raw)
    except yaml.YAMLError:
        fm = None
    return (fm, None) if isinstance(fm, dict) else (None, "front matter is not valid YAML")


def _front_matter_errors(raw, run_slug, run_tier):
    fm, err = _load_front_matter(raw)
    if err:
        return [err]
    errs = []
    if "run" not in fm:
        errs.append("front matter run is missing")
    elif str(fm["run"]) != run_slug:
        errs.append(f'front matter run "{fm["run"]}" does not match "{run_slug}"')
    if "version" not in fm:
        errs.append("front matter version is missing")
    elif isinstance(fm["version"], bool) or not isinstance(fm["version"], int):
        errs.append("front matter version must be an integer")
    if "tier" not in fm:
        errs.append("front matter tier is missing")
    else:
        t = fm["tier"]
        if isinstance(t, bool) or not isinstance(t, int) or not 1 <= t <= 4:
            errs.append("front matter tier must be an integer from 1 to 4")
        elif t != run_tier:
            errs.append(f"front matter tier {t} does not match run tier {run_tier}")
    return errs


def required_sections(run_tier, run_type="feature"):
    if run_type == "docs":
        return DOCS_ONLY
    return FULL if run_tier >= 3 else LITE


def _items(text, kind):
    """Yield (id token, linked REQ tokens or None, raw line) for REQ or AC list lines."""
    for line in _COMMENT.sub("", text).splitlines():
        m = _ITEM.match(line)
        if m and m.group(1) == kind:
            links = None if m.group(3) is None else [x.strip() for x in m.group(3).split(",") if x.strip()]
            yield m.group(2), links


def parse_spec(text):
    """Requirement and criterion ids of a spec, tolerant of errors. Used by both validators."""
    raw, body = _split_front_matter(text)
    secs = _sections(body)
    reqs, acs = {}, {}
    for name in ("functional requirements", "non-functional requirements"):
        for tok, _ in _items(secs.get(name, ""), "REQ"):
            reqs.setdefault(f"REQ-{tok}", None)
    for tok, links in _items(secs.get("acceptance criteria", ""), "AC"):
        acs.setdefault(f"AC-{tok}", [x for x in (links or [])])
    na = {}
    for line in _COMMENT.sub("", secs.get("edge cases", "")).splitlines():
        m = _NA_LINE.match(line)
        if m:
            na[m.group(1).lower()] = m.group(2)
    version = (_load_front_matter(raw)[0] or {}).get("version")
    version = version if isinstance(version, int) and not isinstance(version, bool) else None
    return {"requirements": list(reqs), "criteria": acs, "na": na, "version": version}


def validate_spec(text, run_slug, run_tier, run_type="feature"):
    rep = Report()
    raw, body = _split_front_matter(text)
    rep.errors += _front_matter_errors(raw, run_slug, run_tier)
    secs = _sections(body)
    required = required_sections(run_tier, run_type)
    present = {}
    for name in required:
        key = _norm(name)
        if key not in secs:
            rep.errors.append(f"missing section: {name}")
            continue
        content = _COMMENT.sub("", secs[key]).strip()
        if not content:
            rep.errors.append(f"{name}: section is empty")
            continue
        m = _NA.match(content)
        if m and (":" not in m.group(1) or not m.group(1).split(":", 1)[1].strip()):
            rep.errors.append(f"{name}: not applicable needs a reason")
            continue
        present[name] = content
    if "Functional requirements" in required and "Acceptance criteria" in required:
        _check_ids(rep, secs, present, required)
    return rep


def _check_ids(rep, secs, present, required):
    req_ids, ac_ids = [], []
    ac_links = {}
    req_sections = [n for n in ("Functional requirements", "Non-functional requirements") if n in required]
    if all(n in present for n in req_sections):
        seen = set()
        for n in req_sections:
            for line in _COMMENT.sub("", secs[_norm(n)]).splitlines():
                m = _ITEM.match(line)
                if not (m and m.group(1) == "REQ"):
                    continue
                tok = m.group(2)
                if not re.fullmatch(r"\d+", tok):
                    rep.errors.append(f'invalid requirement id "REQ-{tok}"')
                    continue
                rid = f"REQ-{tok}"
                if rid in seen:
                    rep.errors.append(f"duplicate id {rid}")
                else:
                    seen.add(rid)
                    req_ids.append(rid)
        if not req_ids and not any(e.startswith("invalid requirement id") for e in rep.errors):
            rep.errors.append("no requirements found")
    if "Acceptance criteria" in present:
        seen = set()
        for line in _COMMENT.sub("", secs["acceptance criteria"]).splitlines():
            m = _ITEM.match(line)
            if not (m and m.group(1) == "AC"):
                continue
            tok = m.group(2)
            if not re.fullmatch(r"\d+", tok):
                rep.errors.append(f'invalid criterion id "AC-{tok}"')
                continue
            aid = f"AC-{tok}"
            if aid in seen:
                rep.errors.append(f"duplicate id {aid}")
                continue
            seen.add(aid)
            ac_ids.append(aid)
            if m.group(3) is None or not m.group(3).strip():
                rep.errors.append(f"{aid} is not linked to a requirement")
                continue
            ac_links[aid] = [x.strip() for x in m.group(3).split(",") if x.strip()]
        if not ac_ids and not any(e.startswith("invalid criterion id") for e in rep.errors):
            rep.errors.append("no acceptance criteria found")
    if all(n in present for n in req_sections):
        for aid, links in ac_links.items():
            for r in links:
                if r not in req_ids:
                    rep.errors.append(f"{aid} links unknown {r}")
        linked = {r for ls in ac_links.values() for r in ls}
        for r in req_ids:
            if r not in linked and "Acceptance criteria" in present:
                rep.warnings.append(f"{r} has no acceptance criterion")
    rep.data["requirements"] = req_ids
    rep.data["criteria"] = ac_links
    rep.data["trace_links"] = [(r, a) for a, ls in ac_links.items() for r in ls if r in req_ids]


# ---------------------------------------------------------------- gherkin parser

@dataclass
class Scenario:
    name: str
    kind: str                      # "scenario" or "outline"
    tags: list                     # own tags, without "@"
    inherited_req: list            # REQ tags from Feature and Rule
    line: int
    path: str
    example_rows: int = 0


@dataclass
class ParsedFeature:
    path: str
    scenarios: list = field(default_factory=list)
    errors: list = field(default_factory=list)


_STEP = re.compile(r"^(Given|When|Then|And|But|\*)\s")
_UNSUPPORTED = ("Scenario Template", "Scenarios", "Example", "Business Need", "Ability")
_PLACEHOLDER = re.compile(r"<([^<>\s][^<>]*)>")


def parse_gherkin(text, path):
    """Minimal Gherkin parser for the supported subset. Never raises."""
    pf = ParsedFeature(path)
    err = lambda line, msg: pf.errors.append(f"{path}:{line}: {msg}")  # noqa: E731
    if not text.strip():
        pf.errors.append(f"{path}: file is empty")
        return pf
    feature_seen = False
    feature_tags, rule_tags, pending = [], [], []
    ctx = None                     # "background" | "scenario" | "outline" | "examples" | None
    cur = None
    in_doc = None
    outline_steps, columns, ex_line, ex_rows_seen, ex_header = [], set(), None, 0, False
    outline_line = 0

    def close_outline():
        nonlocal outline_steps, columns, ex_line, ex_header
        if cur is not None and cur.kind == "outline":
            if ex_line is None:
                err(outline_line, "Scenario Outline has no Examples")
            else:
                if cur.example_rows == 0:
                    err(ex_line, "Examples table has no rows")
                for ln, ph in outline_steps:
                    if ph not in columns:
                        err(ln, "placeholder has no Examples column")
        outline_steps, columns, ex_line, ex_header = [], set(), None, False

    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if in_doc:
            if line.startswith(in_doc):
                in_doc = None
            continue
        if line.startswith('"""') or line.startswith("```"):
            in_doc = line[:3]
            continue
        if not line:
            continue
        if line.startswith("#"):
            m = re.match(r"#\s*language\s*:\s*(\S+)", line)
            if m and m.group(1).lower() != "en":
                err(n, "only English Gherkin is supported")
            continue
        if line.startswith("@"):
            pending += [t[1:] for t in line.split() if t.startswith("@")]
            continue
        kw = re.match(r"^([A-Za-z][A-Za-z ]*?)\s*:", line)
        word = kw.group(1) if kw else None
        if word in _UNSUPPORTED:
            err(n, f'unsupported keyword "{word}"')
            pending = []
            continue
        if word == "Feature":
            if feature_seen:
                err(n, "more than one Feature in a file")
            else:
                feature_seen = True
                feature_tags = [t for t in pending if t.startswith("REQ-")]
            pending = []
            continue
        if word == "Rule":
            close_outline(); cur = None; ctx = None
            rule_tags = [t for t in pending if t.startswith("REQ-")]
            pending = []
            continue
        if word == "Background":
            close_outline(); cur = None
            ctx = "background"; pending = []
            continue
        if word in ("Scenario", "Scenario Outline"):
            close_outline()
            kind = "outline" if word == "Scenario Outline" else "scenario"
            cur = Scenario(line.split(":", 1)[1].strip(), kind, pending, feature_tags + rule_tags, n, path)
            pf.scenarios.append(cur)
            outline_line = n
            ctx = kind
            pending = []
            continue
        if word == "Examples":
            if cur is None or cur.kind != "outline":
                err(n, "Examples without a Scenario Outline")
            else:
                ex_line = ex_line or n
                ctx = "examples"; ex_header = False
            pending = []
            continue
        if line.startswith("|"):
            if ctx == "examples":
                cells = [c.strip() for c in line.strip("|").split("|")]
                if not ex_header:
                    ex_header = True
                    columns |= set(cells)
                else:
                    cur.example_rows += 1
            continue
        if _STEP.match(line + " "):
            if ctx is None:
                err(n, "step outside a scenario")
            elif ctx == "outline":
                outline_steps += [(n, ph) for ph in _PLACEHOLDER.findall(line)]
            continue
        # description text: ignored
    close_outline()
    if not feature_seen:
        pf.errors.append(f"{path}: no Feature found")
    elif not pf.scenarios and not any(e.startswith(path + ":") and "step outside" in e for e in pf.errors):
        pf.errors.append(f"{path}: Feature has no scenarios")
    return pf


# ---------------------------------------------------------------- coverage table

def coverage_table(scenarios, spec_text):
    """Rows for the 15 categories. Missing categories are warnings, never errors."""
    counts = {c: 0 for c in CATEGORIES}
    warnings = []
    for s in scenarios:
        cov = [t[4:] for t in s.tags if t.startswith("cov-")]
        for c in cov:
            if c in counts:
                counts[c] += 1
            else:
                w = f"unknown coverage tag @cov-{c}"
                if w not in warnings:
                    warnings.append(w)
        if not cov:
            counts["happy-path"] += 1
        if "regression" in s.tags and "regression" not in cov:
            counts["regression"] += 1
    na = parse_spec(spec_text)["na"]
    rows = []
    for c in CATEGORIES:
        n = counts[c]
        if n:
            state, status = "covered", f"covered by {n} scenario" + ("" if n == 1 else "s")
            reason = ""
        elif na.get(c):
            state, status, reason = "not applicable", f"not applicable: {na[c]}", na[c]
        else:
            state, status, reason = "missing", "missing", ""
            warnings.append(f"{c}: missing")
            if c in na:
                warnings.append(f"n/a for {c} has no reason")
        rows.append({"category": c, "state": state, "status": status, "scenarios": n, "reason": reason})
    missing = sum(1 for r in rows if r["state"] == "missing")
    if missing:
        summary = f"coverage incomplete: {missing} categor{'y' if missing == 1 else 'ies'} missing"
    else:
        summary = "coverage: every category covered or not applicable"
    return {"rows": rows, "warnings": warnings, "summary": summary}


# ---------------------------------------------------------------- gherkin validation

def validate_gherkin(features_dir, spec_text, spec_version=None):
    rep = Report()
    fdir = Path(features_dir)
    spec = parse_spec(spec_text)
    version = spec_version if spec_version is not None else spec["version"]
    vtext = f"approved specification version {version}" if version is not None else "the approved specification"
    files = _feature_files(fdir)
    if not files:
        rep.errors.append(f"no feature files in specs/{fdir.parent.name}/{fdir.name}")
        return rep
    scenarios = []
    for rel, p in files:
        pf = parse_gherkin(p.read_bytes().decode("utf-8", "replace"), rel)
        rep.errors += pf.errors
        scenarios += pf.scenarios
    criteria = spec["criteria"]
    covered, links, seen_err = set(), [], set()

    def once(msg):
        if msg not in seen_err:
            seen_err.add(msg)
            rep.errors.append(msg)

    for s in scenarios:
        where = f"{s.path}:{s.line}"
        acs = [t for t in s.tags if t.startswith("AC-")]
        reqs = [t for t in s.tags + s.inherited_req if t.startswith("REQ-")]
        if not acs:
            once(f"{where}: scenario has no @AC tag")
        if not any(t in TYPE_TAGS for t in s.tags):
            once(f"{where}: scenario has no type tag")
        prios = [t for t in s.tags if re.fullmatch(r"P\d+", t)]
        if not prios:
            once(f"{where}: scenario has no priority tag")
        elif len(prios) > 1:
            once(f"{where}: more than one priority tag")
        elif prios[0] not in PRIORITY_TAGS:
            once(f"{where}: unknown priority tag @{prios[0]}")
        for r in dict.fromkeys(reqs):
            if r not in spec["requirements"]:
                once(f"{r} is not in {vtext}")
        for a in acs:
            if a not in criteria:
                once(f"{a} is not in {vtext}")
                continue
            covered.add(a)
            links.append(("ac", a, "scenario", where))
            for r in dict.fromkeys(reqs):
                if r in spec["requirements"] and r not in criteria[a]:
                    w = f"{a} is not linked to {r} in the approved specification"
                    if w not in rep.warnings:
                        rep.warnings.append(w)
    for a in criteria:
        if a not in covered:
            once(f"{a} has no scenario")
    table = coverage_table(scenarios, spec_text)
    rep.warnings += table["warnings"]
    h, paths = gherkin_set_hash(fdir)
    rep.data = {"hash": h, "paths": paths, "trace_links": links, "coverage": table,
                "scenarios": [{"path": s.path, "line": s.line, "name": s.name, "tags": s.tags} for s in scenarios]}
    return rep


# ---------------------------------------------------------------- stored copies

def _artifact_dir(state_dir, slug):
    return Path(state_dir) / "runs" / slug / "artifacts"


def _stored_name(kind, version):
    return f"spec-v{version}.md" if kind == "spec" else f"gherkin-v{version}"


def store_version(state_dir, slug, kind, src, version):
    """Copy a validated version under runs/<slug>/artifacts/. Returns (version, sha256, stored_path).

    kind "spec": src is the spec file. kind "gherkin": src is the features dir; the copy keeps
    the `features/...` relative layout so the set hash can be recomputed from it. The caller (the
    engine) owns the version number and the registry row.
    """
    if kind not in ("spec", "gherkin"):
        raise ValueError(f"unknown artifact kind {kind!r}")
    adir = _artifact_dir(state_dir, slug)
    dest = adir / _stored_name(kind, version)
    if dest.exists():
        raise SentinelError("E_VALIDATION", f"{kind} version {version} is already stored", {"path": str(dest)})
    adir.mkdir(parents=True, exist_ok=True)
    if kind == "spec":
        data = Path(src).read_bytes()
        sha = _sha(data)
        dest.write_bytes(data)
    else:
        sha, paths = gherkin_set_hash(src)
        base = Path(src).parent
        for rel in paths:
            t = dest / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base / rel, t)
    return version, sha, str(dest)


def stored_hash(state_dir, slug, kind, version):
    dest = _artifact_dir(state_dir, slug) / _stored_name(kind, version)
    if kind == "spec":
        return spec_hash(dest)
    return gherkin_set_hash(dest / "features")[0]


def verify_stored(state_dir, slug, kind, version, sha256):
    """Raise E_INTEGRITY when the stored copy no longer matches its recorded hash."""
    try:
        actual = stored_hash(state_dir, slug, kind, version)
    except SentinelError:
        actual = None
    if actual != sha256:
        raise SentinelError("E_INTEGRITY", f"stored {kind} version {version} does not match its recorded hash",
                            {"kind": kind, "version": version, "expected": sha256, "actual": actual})
