"""Small helpers shared by the Phase E modules."""
import hashlib
import sqlite3
from pathlib import Path


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def cap_of(value, default, minimum=1):
    """A configured cap: an int (not a bool) of at least `minimum`, else `default`."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= minimum else default


def connect_ro(db, timeout=10, **kwargs):
    """A read-only SQLite connection. The path goes through a real file URI, so `#`, `?` and `%` in a folder name stay part of the path."""
    return sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True, timeout=timeout, **kwargs)
