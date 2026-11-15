"""The registered projects: availability, engine access and read-only database access."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import yaml

import scrub
from engine import Engine
from errors import SentinelError
from paths import ROOT
from registry import Registry

from . import userdir

CONFIG_NAME = "sentinel.config.yaml"
SCRUBBER_TTL = 5.0


class Project:
    def __init__(self, entry):
        self.id = entry.get("id")
        self.name = entry.get("name") or self.id
        self.path = Path(entry.get("path") or "")
        self.added_at = entry.get("added_at")

    def public(self):
        return {"id": self.id, "name": self.name, "path": str(self.path), "added_at": self.added_at}


class ProjectSet:
    def __init__(self, cfgdir):
        self.cfgdir = Path(cfgdir)
        self._lock = threading.Lock()
        self._stamp = None
        self._projects = []
        self._cfg_cache = {}
        self._locks = {}
        self._migrated = set()
        self._scrubbers = {}
        self._schema = None

    # ---- the list
    def list(self):
        """The registered projects; projects.json is re-read when it changed (a bad file keeps the last good list)."""
        path = self.cfgdir / userdir.PROJECTS
        try:
            st = path.stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = None
        with self._lock:
            if stamp != self._stamp:
                try:
                    data = userdir.load_projects(self.cfgdir)
                    self._projects = [Project(p) for p in data["projects"] if isinstance(p, dict) and p.get("id")]
                    self._stamp = stamp
                except userdir.ProjectsFileError:
                    pass
            return list(self._projects)

    def get(self, pid):
        for p in self.list():
            if p.id == pid:
                return p
        raise SentinelError("E_NOT_FOUND", f"no project {pid}", {"project": pid})

    # ---- configuration and availability
    def _config_schema(self):
        if self._schema is None:
            self._schema = json.loads((ROOT / "core" / "schema" / "config.schema.json").read_text())
        return self._schema

    def _load_config(self, project):
        """(config, None) or (None, reason)."""
        cfg_file = project.path / CONFIG_NAME
        try:
            st = cfg_file.stat()
        except OSError:
            return None, "invalid configuration"
        key = (str(cfg_file), st.st_mtime_ns, st.st_size)
        cached = self._cfg_cache.get(project.id)
        if cached and cached[0] == key:
            return cached[1], cached[2]
        config, reason = None, None
        try:
            config = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError("not a mapping")
            try:
                import jsonschema
                if next(iter(jsonschema.Draft202012Validator(self._config_schema()).iter_errors(config)), None):
                    raise ValueError("schema")
            except ImportError:
                pass
        except (OSError, ValueError, yaml.YAMLError):
            config, reason = None, "invalid configuration"
        self._cfg_cache[project.id] = (key, config, reason)
        return config, reason

    def state_dir(self, project, config):
        return project.path / (config.get("state") or {}).get("dir", ".sentinel")

    def db_path(self, project, config=None):
        config = config if config is not None else (self._load_config(project)[0] or {})
        return self.state_dir(project, config) / "sentinel.db"

    def probe(self, project):
        """(status, reason). status is "available" or "unavailable"."""
        if not project.path.is_dir():
            return "unavailable", "workspace missing"
        config, reason = self._load_config(project)
        if reason:
            return "unavailable", reason
        db = self.db_path(project, config)
        if db.exists():
            try:
                with self.ro(project, config=config) as conn:
                    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                    if row and int(row[0]) > Registry.LATEST:
                        return "unavailable", "E_MIGRATION"
            except (sqlite3.Error, ValueError):
                return "unavailable", "database unreadable"
        return "available", None

    def require(self, project):
        """The parsed config of an available project; E_PRECONDITION with the reason otherwise."""
        status, reason = self.probe(project)
        if status != "available":
            raise SentinelError("E_PRECONDITION", f"project {project.id} is unavailable: {reason}",
                                {"project": project.id, "reason": reason})
        return self._load_config(project)[0]

    # ---- database access
    @contextmanager
    def ro(self, project, config=None):
        """A read-only connection to the project's registry. Yields None when the database does not exist yet."""
        db = self.db_path(project, config)
        if not db.exists():
            yield None
            return
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _lock_for(self, pid):
        with self._lock:
            return self._locks.setdefault(pid, threading.RLock())

    @contextmanager
    def engine(self, project, user=None, channel=None):
        """An Engine for the project, used by one request at a time per project. The first use also migrates the registry."""
        config = self.require(project)
        with self._lock_for(project.id):
            eng = Engine(self.state_dir(project, config), project.path, config)
            if channel:
                eng.channel, eng.actor_name = channel, user
            try:
                yield eng
            finally:
                eng.close()
            self._migrated.add(project.id)

    @contextmanager
    def reader(self, project):
        """A read-only connection after making sure the registry has the current schema."""
        if project.id not in self._migrated:
            with self.engine(project):
                pass
        config = self.require(project)
        with self.ro(project, config=config) as conn:
            yield conn

    # ---- scrubbing
    def scrubber(self, project):
        entry = self._scrubbers.get(project.id)
        if entry and time.time() - entry[0] < SCRUBBER_TTL:
            return entry[1]
        try:
            s = scrub.Scrubber(project.path, scrub.env_values(project.path) if project.path.is_dir() else [])
        except OSError:
            s = scrub.Scrubber(project.path, [])
        self._scrubbers[project.id] = (time.time(), s)
        return s

    def plain_scrubber(self):
        return scrub.Scrubber("/nonexistent-workspace", [])


def scrub_obj(scrubber, obj):
    """A copy of a JSON value with every string passed through the scrubber."""
    if isinstance(obj, str):
        return scrubber.scrub_text(obj)
    if isinstance(obj, list):
        return [scrub_obj(scrubber, x) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub_obj(scrubber, v) for k, v in obj.items()}
    return obj
