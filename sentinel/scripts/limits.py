"""Usage and rate limits of the provider CLIs (Sentinel 2.1).

When a runner exits non-zero because the account hit a usage, quota or rate limit, the task is not failed: it goes back to
QUEUED with `retry_at` and a reason (the floor shows it as "Waiting for usage limit"). `classify` reads the runner output;
the patterns live in one table per runner (`TABLES`), the reset time formats in `RESET_FORMATS`. Nothing here touches the
registry or the network.
"""
import re
from datetime import datetime, timedelta, timezone

DEFAULT_BACKOFF_MINUTES = 30
MAX_WAIT = timedelta(days=8)   # a parsed reset further away than a week is treated as unparsed noise
MIN_WAIT = timedelta(seconds=5)
TAIL_CHARS = 8000

# A line that says the runner hit a limit. First match wins; the whole table is per runner id. `generic` applies to every
# runner after its own table.
TABLES = {
    "claude": [
        re.compile(r"usage limit reached", re.I),
        re.compile(r"(?:5-hour|five-hour|weekly|session|opus|sonnet) limit reached", re.I),
        re.compile(r"you(?:'|’)ve hit your (?:usage |session |weekly )?limit", re.I),
        re.compile(r"claude ai usage limit", re.I),
    ],
    "gemini": [
        re.compile(r"RESOURCE_EXHAUSTED"),
        re.compile(r"quota exceeded", re.I),
        re.compile(r"exhausted your capacity", re.I),
        re.compile(r"\"code\"\s*:\s*429"),
    ],
    "agy": [
        re.compile(r"RESOURCE_EXHAUSTED"),
        re.compile(r"quota (?:exceeded|exhausted|reached)", re.I),
        re.compile(r"exhausted your (?:capacity|quota)", re.I),
        re.compile(r"model_capacity_exhausted", re.I),
    ],
    "codex": [
        re.compile(r"you(?:'|’)ve hit your usage limit", re.I),
        re.compile(r"usage limit", re.I),
        re.compile(r"rate_limit_exceeded", re.I),
        re.compile(r"insufficient_quota", re.I),
    ],
    "generic": [
        re.compile(r"\b429\b[^\n]{0,40}(?:too many requests|rate)", re.I),
        re.compile(r"too many requests", re.I),
        re.compile(r"rate.?limit(?:ed| exceeded| reached)", re.I),
    ],
}

_TZ = r"(?:\s*\(([A-Za-z_]+(?:/[A-Za-z_+\-0-9]+)*|UTC|GMT)\))?"
_CLOCK = r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)?"
_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()
_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(d(?:ays?)?|h(?:ours?|rs?)?|m(?:inutes?|ins?)?|s(?:econds?|ecs?)?)(?![a-z])", re.I)


def _duration(text):
    """timedelta of '1h2m3s', '2 hours 5 minutes', '34.5s'; None when no unit is found."""
    total, found = 0.0, False
    for number, unit in _DURATION.findall(text):
        found = True
        total += float(number) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit[0].lower()]
    return timedelta(seconds=total) if found else None


def _zone(name):
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return timezone.utc if name in ("UTC", "GMT") else None


def _clock(hour, minute, ampm):
    hour, minute = int(hour), int(minute or 0)
    if ampm:
        hour = hour % 12 + (12 if ampm.lower() == "pm" else 0)
    return (hour, minute) if hour < 24 and minute < 60 else None


# Reset time formats, tried in order on the line(s) around the limit message. Each returns an aware datetime or None.
def _epoch(m, now, local):
    return datetime.fromtimestamp(int(m.group(1)), timezone.utc)


def _relative(m, now, local):
    delta = _duration(m.group(1))
    return now + delta if delta else None


RESET_FORMATS = [
    # Claude Code, older: "Claude AI usage limit reached|1760000000"
    (re.compile(r"limit reached\s*\|\s*(\d{9,11})\b", re.I), _epoch),
    # Gemini, agy, Codex: "reset after 3h12m5s", "retry in 34.5s", "try again in 2 hours 5 minutes", "resets in 2h 15m"
    (re.compile(r"(?:reset[s]?|retry|try again)(?:\s+\w+)?\s+(?:after|in)\s+((?:\d+(?:\.\d+)?\s*[a-z]+\s*(?:and\s+)?,?\s*)+)", re.I),
     _relative),
    (re.compile(r"retryDelay\"?\s*:\s*\"?(\d+(?:\.\d+)?s)", re.I), _relative),
]
_CLOCK_AT = re.compile(r"(?:resets?|try again|retry)(?:\s+at)?\s+" + _CLOCK + _TZ, re.I)
_DATE_AT = re.compile(r"(?:resets?|try again|retry)(?:\s+at|\s+on)?\s+(?:on\s+)?([A-Za-z]{3})[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(?:at\s+)?"
                      + _CLOCK + _TZ, re.I)


def _wall(now, local, tz, hour, minute, month=None, day=None):
    zone = tz or local
    here = now.astimezone(zone)
    if month:
        at = here.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
        if at < here - timedelta(days=1):
            at = at.replace(year=at.year + 1)
    else:
        at = here.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at <= here:
            at += timedelta(days=1)
    return at.astimezone(timezone.utc)


def parse_reset(text, now=None, local=None):
    """The moment the limit ends, as an aware UTC datetime, or None when the text names none (or one that is not plausible)."""
    now = now or datetime.now(timezone.utc)
    local = local or now.astimezone().tzinfo
    found = None
    for pattern, fn in RESET_FORMATS:
        m = pattern.search(text)
        if m:
            found = fn(m, now, local)
            if found:
                break
    if not found:
        m = _DATE_AT.search(text)
        if m and m.group(1).lower() in _MONTHS:
            wall = _clock(m.group(3), m.group(4), m.group(5))
            if wall:
                try:
                    found = _wall(now, local, _zone(m.group(6)), *wall, month=_MONTHS.index(m.group(1).lower()) + 1,
                                  day=int(m.group(2)))
                except ValueError:
                    found = None
    if not found:
        m = _CLOCK_AT.search(text)
        if m and (m.group(3) or m.group(2) or m.group(4)):
            wall = _clock(m.group(1), m.group(2), m.group(3))
            if wall:
                found = _wall(now, local, _zone(m.group(4)), *wall)
    if not found or found - now > MAX_WAIT:
        return None
    return max(found, now + MIN_WAIT)


def classify(runner_id, stdout, stderr, now=None, backoff_minutes=DEFAULT_BACKOFF_MINUTES, local=None):
    """None when the output shows no limit; else {"retry_at": iso, "parsed": bool, "reason": text}. `parsed` is false when the
    time is now + backoff because the message names no reset time."""
    now = now or datetime.now(timezone.utc)
    text = ((stdout or "")[-TAIL_CHARS:] + "\n" + (stderr or "")[-TAIL_CHARS:]).strip()
    if not text:
        return None
    lines = text.splitlines()
    for table in (TABLES.get(runner_id, []), TABLES["generic"]):
        for pattern in table:
            for i, line in enumerate(lines):
                if pattern.search(line):
                    near = "\n".join(lines[max(0, i - 1):i + 3])
                    reset = parse_reset(near, now, local) or parse_reset(text, now, local)
                    when = reset or now + timedelta(minutes=backoff_minutes)
                    return {"retry_at": when.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "parsed": reset is not None,
                            "reason": " ".join(line.split())[:300]}
    return None
