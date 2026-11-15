"""Test selectors (Phase D review item 4): turns test ids (`Class.method`) into the command a profile's test tool needs.

A profile has `targeted_test`, a command template with these placeholders, replaced in one pass:
  {tests}       the ids, shell-quoted, space separated (a tool that takes ids as they are)
  {selectors}   one selector per id (the profile's `selector` template), joined with `selector_join` (default " ")
  {files}       the distinct test files of the ids, shell-quoted
  {report_dir}  the engine-owned directory for the JUnit report
`selector` is a template over {test} (id), {file} (repo-relative), {class} (empty when the id has no class declaration),
{method}, {node} (pytest node id) and {method_re} (regex-escaped method). Values are put in raw, so a template quotes them
itself (`'{node}'`) and a value that holds a quote, a backslash or a control character is refused (ValueError).
"""
import re
import shlex

_BAD = re.compile(r"['\"`\\\x00-\x1f\x7f]")
_OUTER = re.compile(r"\{(tests|selectors|files|report_dir)\}")
_INNER = re.compile(r"\{(test|file|class|method|node|method_re)\}")


def _safe(value):
    value = "" if value is None else str(value)
    if _BAD.search(value):
        raise ValueError(f"test name or path {value!r} has characters a test selector cannot carry")
    return value


def selector(template, test, info):
    file = _safe((info or {}).get("file"))
    klass = _safe((info or {}).get("class"))
    method = _safe((info or {}).get("method") or test.rsplit(".", 1)[-1])
    values = {"test": _safe(test), "file": file, "class": klass, "method": method,
              "node": "::".join(p for p in (file, klass, method) if p), "method_re": re.escape(method)}
    return _INNER.sub(lambda m: values[m.group(1)], template)


def render(tools, tests, info, report_dir=""):
    """The command of a targeted run over `tests`. `info` maps an id to {"file", "class", "method"}."""
    template = tools.get("targeted_test") or ""
    sel = tools.get("selector") or "{test}"
    join = tools.get("selector_join")
    join = " " if join is None else join
    tests = list(tests)

    def fill(m):
        key = m.group(1)
        if key == "tests":
            return " ".join(shlex.quote(t) for t in tests)
        if key == "selectors":
            return join.join(selector(sel, t, (info or {}).get(t)) for t in tests)
        if key == "files":
            files = list(dict.fromkeys(_safe((info or {}).get(t, {}).get("file")) for t in tests if (info or {}).get(t, {}).get("file")))
            return " ".join(shlex.quote(f) for f in files)
        return shlex.quote(report_dir) if report_dir else ""
    return _OUTER.sub(fill, template)
