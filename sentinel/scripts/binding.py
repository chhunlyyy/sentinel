"""Binding of tests to approved scenarios (TDD-02, Phase D open point 7). Pure text functions.

A test refers to its scenario with the profile's `scenario_ref` regex (group 1 is the scenario key
"<feature path> :: <scenario name>"). The test is the first method declared after the reference; its id is
`<class>.<method>` with the nearest `class` declaration above it, or the file name without extensions when the file
has none (pytest functions, JUnit class names are matched by their last segment).
"""
import re

_METHOD = re.compile(r"\b(?:def|void|fun|func|function)\s+([A-Za-z_]\w*)|\b(?:it|test)\(\s*['\"]([^'\"]+)['\"]")
_CLASS = re.compile(r"\bclass\s+([A-Za-z_]\w*)")


def file_class(path):
    return path.rsplit("/", 1)[-1].split(".", 1)[0]


def references(text, pattern, path=""):
    """[(scenario key, test id or None)] in file order for every reference the regex finds in `text`."""
    return [(key, tid) for key, tid, _ in _scan(text, pattern, path)]


def test_info(text, pattern, path=""):
    """{test id: {"file", "class", "method"}} of the referenced tests: what a profile's selector template needs.
    `class` is None when the file declares no class above the test (the id then starts with the file name)."""
    return {tid: {"file": path, "class": klass, "method": name} for _, tid, (klass, name) in _scan(text, pattern, path) if tid}


def _scan(text, pattern, path):
    try:
        rx = re.compile(pattern)
    except (re.error, TypeError):
        return []
    found = list(rx.finditer(text))
    out = []
    for i, m in enumerate(found):
        stop = found[i + 1].start() if i + 1 < len(found) else len(text)
        method = _METHOD.search(text, m.end(), stop)
        klass = None
        for c in _CLASS.finditer(text, 0, m.start()):
            klass = c.group(1)
        name = (method.group(1) or method.group(2)) if method else None
        out.append((m.group(1), f"{klass or file_class(path)}.{name}" if name else None, (klass, name)))
    return out


def bind(refs, cycle_keys, other_keys, shared_keys=()):
    """(problem, pairs): the first binding problem as a reason text, else None, and [(scenario key, test id)].
    `cycle_keys` are the scenarios of the cycle, `other_keys` the scenarios of every other cycle of the run, and
    `shared_keys` those of other cycles that already own tests (tests often share a file, so they are not an error)."""
    if not refs:
        return "no scenario reference found", []
    pairs = []
    for key, test in refs:
        if key in cycle_keys:
            pairs.append((key, test))
        elif key in shared_keys:
            continue
        elif key in other_keys:
            return f"scenario of another cycle: {key}", []
        else:
            return f"unknown scenario: {key}", []
    for key in cycle_keys:
        if key not in {k for k, _ in pairs}:
            return f"scenario without test: {key}", []
    for key, test in pairs:
        if test is None:
            return f"no test found for the reference to {key}", []
    return None, pairs
