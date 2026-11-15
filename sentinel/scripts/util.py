"""Small helpers shared by the Phase E modules."""
import hashlib


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def cap_of(value, default, minimum=1):
    """A configured cap: an int (not a bool) of at least `minimum`, else `default`."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= minimum else default
