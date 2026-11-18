"""The user registry folder: server.json, server.lock and projects.json (plan/v1.1/phaseF/README.md points 8 and 9)."""
import fcntl
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECTS = "projects.json"
SERVER = "server.json"
LOCK = "server.lock"
REGISTRY_LOCK = "projects.lock"


class ProjectsFileError(Exception):
    """projects.json cannot be read; it is never overwritten."""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def config_dir(environ=None):
    env = os.environ if environ is None else environ
    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path(env.get("HOME") or Path.home()) / ".config"
    return base / "sentinel"


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def ensure_dir(path):
    """Create the folder with mode 0700 and tighten wider modes of it and of projects.json. Returns notices."""
    path = Path(path)
    notices = []
    path.mkdir(parents=True, exist_ok=True)
    if _mode(path) != 0o700:
        if _mode(path) & 0o077:
            notices.append(f"permissions of {path} were tightened to 0700")
        os.chmod(path, 0o700)
    pj = path / PROJECTS
    if pj.exists() and _mode(pj) != 0o600:
        if _mode(pj) & 0o077:
            notices.append(f"permissions of {pj} were tightened to 0600")
        os.chmod(pj, 0o600)
    return notices


def _atomic_write(path, text):
    """Write `text` to a 0600 temporary file in the same folder, then rename it over `path`."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---- projects.json
def load_projects(directory):
    path = Path(directory) / PROJECTS
    if not path.exists():
        return {"version": 1, "projects": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ProjectsFileError(f"{path} cannot be read: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        raise ProjectsFileError(f"{path} must hold an object with a projects list")
    data.setdefault("version", 1)
    return data


def save_projects(directory, data):
    _atomic_write(Path(directory) / PROJECTS, json.dumps(data, indent=2) + "\n")


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return slug or "project"


def register_workspace(directory, workspace, name=None):
    """Add the workspace to projects.json once (by resolved path). Returns (project entry, created)."""
    directory = Path(directory)
    resolved = str(Path(workspace).resolve())
    with open(directory / REGISTRY_LOCK, "a") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = load_projects(directory)
            for p in data["projects"]:
                if p.get("path") == resolved:
                    return p, False
            base = slugify(name or Path(resolved).name)
            taken = {p.get("id") for p in data["projects"]}
            pid, n = base, 1
            while pid in taken:
                n += 1
                pid = f"{base}-{n}"
            entry = {"id": pid, "name": name or Path(resolved).name, "path": resolved, "added_at": now()}
            data["projects"].append(entry)
            save_projects(directory, data)
            return entry, True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def unregister_project(directory, pid):
    """Drop the project from projects.json. Its folder and state stay on disk. True when it was listed."""
    directory = Path(directory)
    with open(directory / REGISTRY_LOCK, "a") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = load_projects(directory)
            kept = [p for p in data["projects"] if p.get("id") != pid]
            if len(kept) == len(data["projects"]):
                return False
            data["projects"] = kept
            save_projects(directory, data)
            return True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


# ---- server.json and the one-server lock
class ServerLock:
    """flock on server.lock, held for the life of the server process."""

    def __init__(self, directory):
        self.path = Path(directory) / LOCK
        self._f = None

    def acquire(self):
        f = open(self.path, "a")
        try:
            os.fchmod(f.fileno(), 0o600)
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._f = f
        return True

    def release(self):
        if self._f:
            try:
                fcntl.flock(self._f, fcntl.LOCK_UN)
            finally:
                self._f.close()
                self._f = None


def write_server_json(directory, info):
    _atomic_write(Path(directory) / SERVER, json.dumps(info, indent=2) + "\n")


def read_server_json(directory):
    try:
        data = json.loads((Path(directory) / SERVER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    need = {"pid": int, "port": int, "token": str}
    if not isinstance(data, dict) or any(not isinstance(data.get(k), t) for k, t in need.items()):
        return None
    return data


def remove_server_json(directory, pid):
    """Remove server.json only when it still names `pid`. Returns True when removed."""
    path = Path(directory) / SERVER
    data = read_server_json(directory)
    if data and data["pid"] == pid:
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False
