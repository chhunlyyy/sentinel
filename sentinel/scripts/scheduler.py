"""Pure scheduling helpers (PC-02): do two write scopes overlap? No I/O.

Globs are workspace-relative and start with the repo id ("backend/src/main/**"). Two globs overlap when some path
could match both. The test works on path segments: "**" matches any number of segments (also none), two segment
patterns ("*", "?", classes, literals) are intersected character by character (memoised, so cost stays
polynomial in the number of segments). An empty write scope overlaps nothing (README open point 14).
"""
WILD = "*?["


def _wild(segment):
    return any(ch in segment for ch in WILD)


def _tokens(seg):
    """Segment pattern to tokens: "*", "?", ("set", chars, negated) or a literal character."""
    out, i = [], 0
    while i < len(seg):
        ch = seg[i]
        if ch == "*":
            if not out or out[-1] != "*":
                out.append("*")
        elif ch == "?":
            out.append("?")
        elif ch == "[":
            j = i + 1
            neg = j < len(seg) and seg[j] == "!"
            j += neg
            k = j + 1 if j < len(seg) and seg[j] == "]" else j
            while k < len(seg) and seg[k] != "]":
                k += 1
            if k >= len(seg):
                out.append("[")
            else:
                body, chars, x = seg[j:k], set(), 0
                while x < len(body):
                    if x + 2 < len(body) and body[x + 1] == "-":
                        chars.update(chr(c) for c in range(ord(body[x]), ord(body[x + 2]) + 1))
                        x += 3
                    else:
                        chars.add(body[x])
                        x += 1
                out.append(("set", frozenset(chars), neg))
                i = k
        else:
            out.append(ch)
        i += 1
    return out


def _char_sets(t):
    """(chars, negated) for a one-character token; ("?") is the empty negated set (any character)."""
    if t == "?":
        return frozenset(), True
    if isinstance(t, tuple):
        return t[1], t[2]
    return frozenset(t), False


def _chars_meet(x, y):
    (ca, na), (cb, nb) = _char_sets(x), _char_sets(y)
    if na and nb:
        return True
    if na:
        return bool(cb - ca)
    if nb:
        return bool(ca - cb)
    return bool(ca & cb)


def _segments_compatible(a, b):
    """True when some one segment name matches both patterns (exact, character level)."""
    if a == b:
        return True
    ta, tb = _tokens(a), _tokens(b)
    n, m, memo = len(ta), len(tb), {}

    def f(i, j):
        key = (i, j)
        if key not in memo:
            if i == n and j == m:
                r = True
            elif i < n and ta[i] == "*":
                r = f(i + 1, j) or (j < m and f(i, j + 1))
            elif j < m and tb[j] == "*":
                r = f(i, j + 1) or (i < n and f(i + 1, j))
            else:
                r = i < n and j < m and _chars_meet(ta[i], tb[j]) and f(i + 1, j + 1)
            memo[key] = r
        return memo[key]
    return f(0, 0)


def _overlap(a, b):
    n, m, memo = len(a), len(b), {}

    def f(i, j):
        key = (i, j)
        if key in memo:
            return memo[key]
        if i == n and j == m:
            r = True
        elif i == n:
            r = all(s == "**" for s in b[j:])
        elif j == m:
            r = all(s == "**" for s in a[i:])
        elif a[i] == "**":
            r = f(i + 1, j) or f(i, j + 1) or (b[j] == "**" and f(i + 1, j + 1))
        elif b[j] == "**":
            r = f(i, j + 1) or f(i + 1, j)
        else:
            r = _segments_compatible(a[i], b[j]) and f(i + 1, j + 1)
        memo[key] = r
        return r
    return f(0, 0)


def globs_overlap(glob_a, glob_b):
    """True when one path could match both globs."""
    sa = [s for s in glob_a.strip("/").split("/") if s]
    sb = [s for s in glob_b.strip("/").split("/") if s]
    if not sa or not sb:
        return False
    # a literal glob names a file or a directory; it covers what is below it
    if not any(_wild(s) for s in sa):
        sa = sa + ["**"]
    if not any(_wild(s) for s in sb):
        sb = sb + ["**"]
    return _overlap(sa, sb)


def scopes_overlap(scope_a, scope_b):
    """The first (glob, glob) pair of two write scopes that overlap, or None."""
    for ga in scope_a or []:
        for gb in scope_b or []:
            if globs_overlap(ga, gb):
                return ga, gb
    return None
