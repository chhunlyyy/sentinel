"""Who runs the process: OS user name and the optional approver display name (standard library only)."""
import getpass
import os


def os_user():
    """The OS user name; a container started with `--user N` can have a uid with no passwd entry, then `uid<N>`."""
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return f"uid{os.getuid()}"


def approver_name_env():
    """SENTINEL_APPROVER_NAME as the approver's display name, in the Sentinel container only (the OS user stays `sentinel`)."""
    if os.environ.get("SENTINEL_CONTAINER") != "1":
        return None
    name = "".join(c for c in os.environ.get("SENTINEL_APPROVER_NAME", "") if c.isprintable()).strip()
    return name[:100] or None
