"""Run export and import (PE-01, ART-03): one scrubbed bundle per run, checked in full before anything is written.

BundleOps is mixed into Engine. Format `sentinel-run-bundle-v1`: manifest.json (sha256 and size of every other file,
excluded paths), rows.json (the run's registry rows and its config snapshot), run/ (the run folder) and
shared/specs/<slug>/. The manifest is not signed: its hashes catch corruption and casual edits, not someone who rewrites a
file and the manifest together (residual risk, README point 18). Source: plan/v1.1/phaseE/README.md points 17 and 18.
"""
import getpass
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import zlib
from pathlib import Path

import auditlog
import machines
import scrub
from errors import SentinelError
from paths import ROOT
from registry import _now
from util import sha_bytes

FORMAT = "sentinel-run-bundle-v1"
TABLES = ("runs", "run_repos", "artifacts", "approvals", "tasks", "task_deps", "cycles", "evidence", "findings", "trace_links",
          "changed_files", "verification_rounds")
OPEN_TASKS = ("RUNNING", "WAITING_FOR_INPUT")
MAX_BYTES = 256 << 20  # declared size of all members together
MAX_MEMBERS = 10000
CHUNK = 1 << 20


def is_text(data):
    if b"\x00" in data[:4096]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def scrub_value(scrubber, value):
    if isinstance(value, str):
        return scrubber.scrub_text(value)
    if isinstance(value, list):
        return [scrub_value(scrubber, v) for v in value]
    if isinstance(value, dict):
        return {k: scrub_value(scrubber, v) for k, v in value.items()}
    return value


class BundleOps:
    def bundle_name(self, slug):
        return f"{slug}.sentinel-run.tar.gz"

    # ---- export
    def export_run(self, slug, out_dir=None, user=None, channel="tty"):
        """Write <slug>.sentinel-run.tar.gz (mode 0600, never overwritten). Returns {"path", "sha256", "files", "excluded"}."""
        self._sync(slug)
        run = self._get_v2(slug)
        dest = Path(out_dir or self.workspace) / self.bundle_name(slug)
        if dest.exists():
            raise SentinelError("E_PRECONDITION", f"{dest.name} already exists; it is never overwritten", {"path": str(dest)})
        busy = [t for t in self.reg.rows("tasks", run_id=run["id"]) if t["state"] in OPEN_TASKS]
        if busy:
            raise SentinelError("E_PRECONDITION", f"task {busy[0]['id']} of the run is {busy[0]['state']}; export waits", {"task": busy[0]["id"]})
        if any(not r["finished_at"] and not r["interrupted"] and self._owner_alive(r, run) for r in self._vrounds(run)):
            raise SentinelError("E_PRECONDITION", "a verification of the run is in progress; export waits")
        scrubber = scrub.Scrubber(self.workspace, scrub.env_values(self.workspace))
        stage = Path(tempfile.mkdtemp(prefix="export-", dir=self._tmp()))
        try:
            files, excluded, originals = {}, [], {}
            self._collect(run, stage, scrubber, files, excluded, originals)
            rows = self._rows_doc(run, scrubber, originals)
            data = (json.dumps(rows, indent=2, sort_keys=True) + "\n").encode("utf-8")
            (stage / "rows.json").write_bytes(data)
            files["rows.json"] = {"sha256": sha_bytes(data), "size": len(data)}
            manifest = {"format": FORMAT, "sentinel_version": (ROOT / "VERSION").read_text().strip(),
                        "registry_schema_version": self.reg.schema_version(), "slug": slug, "files": files,
                        "excluded": sorted(excluded, key=lambda e: e["path"])}
            (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            problems = scrub.check_paths([stage], scrubber)
            if problems:
                raise SentinelError("E_POLICY", "the bundle still holds secrets or personal data: " + ", ".join(sorted(problems)),
                                    {"files": sorted(problems)})
            tmp = dest.with_name("." + dest.name + f".{os.getpid()}.tmp")
            with tarfile.open(tmp, "w:gz") as tar:
                for name in ["manifest.json"] + sorted(files):
                    info = tar.gettarinfo(str(stage / name), arcname=name)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with open(stage / name, "rb") as fh:
                        tar.addfile(info, fh)
            os.chmod(tmp, 0o600)
            try:
                os.link(tmp, dest)  # fails when the file appeared meanwhile: never overwritten
            except FileExistsError:
                raise SentinelError("E_PRECONDITION", f"{dest.name} already exists; it is never overwritten", {"path": str(dest)})
            finally:
                tmp.unlink(missing_ok=True)
            sha = sha_bytes(dest.read_bytes())
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        self.audit(user or getpass.getuser(), channel, "run_exported", slug, reason=sha)
        return {"path": str(dest), "sha256": sha, "files": len(files) + 1, "excluded": excluded}

    def _tmp(self):
        t = self.state_dir / "tmp"
        t.mkdir(parents=True, exist_ok=True)
        return t

    def _collect(self, run, stage, scrubber, files, excluded, originals):
        slug = run["slug"]
        sources = [("run", self.run_dir(slug)), (f"shared/specs/{slug}", self.state_dir / "shared" / "specs" / slug)]
        for prefix, base in sources:
            if not base.is_dir():
                continue
            for p in sorted(base.rglob("*")):
                rel = f"{prefix}/{p.relative_to(base).as_posix()}"
                if p.is_symlink():
                    excluded.append({"path": rel, "reason": "link"})
                    continue
                if not p.is_file():
                    continue
                if any(part.startswith(".env") for part in p.parts[-3:]) or p.name.startswith(".env") or p.name in ("sentinel.db", "server.json"):
                    excluded.append({"path": rel, "reason": "secret file"})
                    continue
                raw = p.read_bytes()
                if not is_text(raw):
                    excluded.append({"path": rel, "reason": "binary"})
                    continue
                text = raw.decode("utf-8")
                clean = scrubber.scrub_text(text)
                if clean != text:
                    if prefix.startswith("shared/specs") or rel.startswith(("run/artifacts/spec-", "run/artifacts/gherkin-")):
                        raise SentinelError("E_POLICY", f"scrubbing would change {rel.removeprefix('shared/')}: approval hash would change",
                                            {"path": rel})
                    originals[p.relative_to(self.state_dir).as_posix()] = sha_bytes(raw)
                data = clean.encode("utf-8")
                dst = stage / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                files[rel] = {"sha256": sha_bytes(data), "size": len(data)}

    def _rows_doc(self, run, scrubber, originals):
        reg = self.reg
        doc = {}
        for table in TABLES:
            if table == "runs":
                rows = [run]
            elif table in ("run_repos",):
                rows = reg.run_repos(run["id"])
            elif table == "task_deps":
                ids = {t["id"] for t in reg.rows("tasks", run_id=run["id"])}
                rows = [{"task_id": t, "depends_on": d} for t in ids for d in reg.task_deps(t)]
            else:
                rows = reg.rows(table, run_id=run["id"])
            doc[table] = [dict(r) for r in rows]
        for art in doc["artifacts"]:
            orig = originals.get(art["path"])
            if orig:
                data = (self.state_dir / art["path"]).read_bytes()
                clean = scrubber.scrub_text(data.decode("utf-8", "replace")).encode("utf-8")
                for e in doc["evidence"]:
                    if e["output_artifact_id"] == art["id"]:
                        e["output_sha256"] = sha_bytes(clean)
                art.update(sha256=sha_bytes(clean), scrubbed=1, original_sha256=orig)
        events = []
        for e in reg.list_events(run["id"]):
            events.append({**e, "payload": e["payload"]})
        doc["events"] = events
        doc["audit"] = [a for a in reg.audit_rows() if (a["target"] or "") == run["slug"] or (a["target"] or "").startswith(run["slug"] + "/")]
        snap = reg.get_config_version(run["config_snapshot_id"]) if run.get("config_snapshot_id") else None
        doc["config"] = dict(snap) if snap else None
        return scrub_value(scrubber, doc)

    # ---- import
    def import_run(self, bundle, user=None, channel="tty"):
        """Check every part of the bundle, then write its rows in one transaction and its files into place."""
        bundle = Path(bundle)
        if not bundle.is_file():
            raise SentinelError("E_NOT_FOUND", f"no bundle file {bundle}", {"path": str(bundle)})
        stage = Path(tempfile.mkdtemp(prefix="import-", dir=self._tmp()))
        try:
            try:
                bundle_sha = self._unpack(bundle, stage)
                manifest = self._check_manifest(stage)
                slug = manifest["slug"]
                doc = json.loads((stage / "rows.json").read_text(encoding="utf-8"))
            except OSError as err:
                raise SentinelError("E_VALIDATION", f"the bundle cannot be read: {err}") from err
            except ValueError as err:
                raise SentinelError("E_VALIDATION", f"rows.json is not valid JSON: {err}", {"path": "rows.json"}) from err
            self._check_slug_free(slug, doc)
            self._check_rows(doc, slug)
            run_row = doc["runs"][0]
            active = run_row["state"] not in machines.RUN_FINAL
            held = False
            if active:
                from shared import Shared
                try:
                    Shared(self.workspace, self.config).acquire(slug, user or getpass.getuser())
                    held = True
                except SystemExit as err:
                    raise SentinelError("E_LOCKED", str(err.code), {"slug": slug}) from err
            try:
                self._write_rows(doc, slug, bundle_sha, user or getpass.getuser(), channel)
            except sqlite3.IntegrityError as err:
                if held:
                    self._release(slug, {"adhoc": 0})
                raise SentinelError("E_VALIDATION", f"rows.json clashes with rows of this registry: {err}", {"error": str(err)}) from err
            except sqlite3.Error as err:
                if held:
                    self._release(slug, {"adhoc": 0})
                raise SentinelError("E_MIGRATION", f"database error during import: {err}", {"error": str(err)}, exit_code=1) from err
            except BaseException:
                if held:
                    self._release(slug, {"adhoc": 0})
                raise
            self._place_files(stage, slug)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        self.write_view(slug)
        return self._get(slug)

    def _unpack(self, bundle, stage):
        """Stream the archive into `stage`, member by member, within the caps. Returns the sha256 of the bundle file."""
        digest = hashlib.sha256()
        try:
            with open(bundle, "rb") as fh:
                for chunk in iter(lambda: fh.read(CHUNK), b""):
                    digest.update(chunk)
                fh.seek(0)
                self._extract(fh, stage)
        except (tarfile.TarError, EOFError, zlib.error) as err:
            raise SentinelError("E_VALIDATION", f"the bundle is not a readable archive: {err}") from err
        return digest.hexdigest()

    def _extract(self, fh, stage):
        total = count = 0
        with tarfile.open(fileobj=fh, mode="r|gz") as tar:
            for m in tar:
                count += 1
                if count > MAX_MEMBERS:
                    raise SentinelError("E_VALIDATION", f"the bundle holds more than {MAX_MEMBERS} entries")
                name = m.name
                parts = name.replace("\\", "/").split("/")
                if name.startswith(("/", "\\")) or ".." in parts or (len(name) > 1 and name[1] == ":"):
                    raise SentinelError("E_VALIDATION", f"unsafe archive entry {name!r}", {"entry": name})
                if m.issym() or m.islnk():
                    raise SentinelError("E_VALIDATION", f"unsafe archive entry {name!r}: links are not allowed", {"entry": name})
                if m.isdir():
                    continue
                if not m.isreg():
                    raise SentinelError("E_VALIDATION", f"unsafe archive entry {name!r}: not a regular file", {"entry": name})
                total += m.size
                if total > MAX_BYTES:
                    raise SentinelError("E_VALIDATION", f"the bundle declares more than {MAX_BYTES >> 20} MiB")
                dst = stage / name
                try:
                    dst.resolve().relative_to(stage.resolve())
                except ValueError:
                    raise SentinelError("E_VALIDATION", f"unsafe archive entry {name!r}", {"entry": name})
                dst.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(m)
                with open(dst, "wb") as out:
                    for chunk in iter(lambda: src.read(CHUNK), b""):
                        out.write(chunk)

    def _check_rows(self, doc, slug):
        """rows.json speaks for one run only: the slug of the manifest, rows that carry that run's id, links between its own
        tasks, audit rows about it, and artifact paths inside its own folders. Nothing of another run is touched."""
        def bad(message):
            raise SentinelError("E_VALIDATION", f"rows.json: {message}", {"file": "rows.json"})
        runs = doc.get("runs") if isinstance(doc, dict) else None
        if not (isinstance(runs, list) and len(runs) == 1 and isinstance(runs[0], dict)):
            bad("it must hold exactly one run")
        run_id = runs[0].get("id")
        if runs[0].get("slug") != slug:
            bad(f"the run is {runs[0].get('slug')!r}, the manifest says {slug!r}")
        rows = {t: doc.get(t, []) for t in (*TABLES[1:], "events", "audit")}
        for table, items in rows.items():
            if not isinstance(items, list) or not all(isinstance(r, dict) for r in items):
                bad(f"{table} must be a list of rows")
        refs = (("task_id", "tasks"), ("cycle_id", "cycles"))
        own = {col: {r.get("id") for r in rows[table]} for col, table in refs}

        def foreign(row):
            """A task or cycle this registry already holds that the bundle does not (so it belongs to another run)."""
            return next((f"{col} {row[col]!r}" for col, table in refs if row.get(col) is not None and row[col] not in own[col]
                         and self.reg.get_row(table, row[col])), None)
        for table in TABLES[1:]:
            for r in rows[table]:
                if table == "task_deps":
                    if r.get("task_id") not in own["task_id"] or r.get("depends_on") not in own["task_id"]:
                        bad("task_deps names a task that is not in the bundle")
                    continue
                if r.get("run_id") != run_id:
                    bad(f"a {table} row belongs to run {r.get('run_id')!r}, not to {run_id!r}")
                if foreign(r):
                    bad(f"a {table} row names {foreign(r)} of another run")
        for art in rows["artifacts"]:
            path = art.get("path")
            if not (isinstance(path, str) and path.startswith((f"runs/{slug}/", f"shared/specs/{slug}/")) and ".." not in path.split("/")):
                bad(f"artifact path {path!r} is outside the run")
        for e in rows["events"]:
            if foreign(e):
                bad(f"an event names {foreign(e)} of another run")
        for a in rows["audit"]:
            for field in auditlog.TEXT_FIELDS + ("at",):
                if a.get(field) is not None and not isinstance(a.get(field), str):
                    bad(f"an audit row has a {field} that is not text")
            target = a.get("target") or ""
            if target != slug and not target.startswith(slug + "/"):
                bad(f"an audit row is about {target!r}, not about the run")

    def _check_manifest(self, stage):
        mpath = stage / "manifest.json"
        if not mpath.is_file():
            raise SentinelError("E_VALIDATION", "the bundle has no manifest.json", {"path": "manifest.json"})
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except ValueError as err:
            raise SentinelError("E_VALIDATION", f"manifest.json is not valid JSON: {err}") from err
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise SentinelError("E_VALIDATION", f"manifest.json: unknown format {manifest.get('format') if isinstance(manifest, dict) else None!r}; "
                                f"expected {FORMAT}", {"field": "format"})
        if (manifest.get("registry_schema_version") or 0) > self.reg.schema_version():
            raise SentinelError("E_VALIDATION", f"the bundle needs registry schema {manifest['registry_schema_version']}, this Sentinel has "
                                f"{self.reg.schema_version()}; fix: upgrade Sentinel", {"fix": "upgrade Sentinel"})
        slug = manifest.get("slug")
        from paths import slug_problem
        if not isinstance(slug, str) or slug_problem(slug):
            raise SentinelError("E_VALIDATION", "manifest.json: invalid slug", {"field": "slug"})
        listed = manifest.get("files") or {}
        for rel, meta in sorted(listed.items()):
            f = stage / rel
            if not f.is_file():
                raise SentinelError("E_INTEGRITY", f"listed file is missing from the bundle: {rel}", {"path": rel})
            if sha_bytes(f.read_bytes()) != meta.get("sha256"):
                raise SentinelError("E_INTEGRITY", f"{rel} does not match its hash in manifest.json", {"path": rel})
        present = {p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()} - {"manifest.json"}
        extra = sorted(present - set(listed))
        if extra:
            raise SentinelError("E_INTEGRITY", f"file not listed in manifest.json: {extra[0]}", {"path": extra[0]})
        if "rows.json" not in listed:
            raise SentinelError("E_VALIDATION", "the bundle has no rows.json", {"path": "rows.json"})
        return manifest

    def _check_slug_free(self, slug, doc):
        found = []
        if self.reg.get_run(slug):
            found.append(f"a run row {slug}")
        if self.run_dir(slug).exists():
            found.append(f"a folder .sentinel/runs/{slug}/")
        if (self.state_dir / "shared" / "specs" / slug).exists():
            found.append(f"a folder .sentinel/shared/specs/{slug}/")
        if found:
            raise SentinelError("E_PRECONDITION", f"slug exists: {slug} already has " + ", ".join(found), {"slug": slug})

    def _insert_raw(self, table, row):
        cols = [c for c in row if c in self.reg._columns(table)]
        sql = f'INSERT INTO "{table}" ({",".join(chr(34) + c + chr(34) for c in cols)}) VALUES ({",".join("?" * len(cols))})'
        self.reg._c.execute(sql, [row[c] for c in cols])

    def _write_rows(self, doc, slug, bundle_sha, user, channel):
        run = dict(doc["runs"][0])
        with self.reg.transaction():
            if self.reg.get_run(slug):
                raise SentinelError("E_PRECONDITION", f"slug exists: {slug} already has a run row {slug}", {"slug": slug})
            cfg = doc.get("config")
            if cfg:
                cid = self.reg.store_config_version("workspace", cfg["content"], author=cfg.get("author"), channel=cfg.get("channel"),
                                                    comment=f"imported with run {slug}")
                run["config_snapshot_id"] = cid
            run["origin"] = "import"
            run["driver"], run["paused"] = "cli", 0  # an imported run is driven by hand until its owner chooses otherwise
            self._insert_raw("runs", run)
            for table in TABLES[1:]:
                for row in doc.get(table, []):
                    self._insert_raw(table, row)
            for e in doc.get("events", []):
                payload = e["payload"] if isinstance(e["payload"], dict) else {"value": e["payload"]} if e["payload"] is not None else {}
                payload = {**payload, "original_event_id": e["id"]}
                self.reg._c.execute("INSERT INTO events(run_id, task_id, type, actor, payload, at, actor_name, channel) VALUES (?,?,?,?,?,?,?,?)",
                                    (run["id"], e.get("task_id"), e["type"], e["actor"], json.dumps(payload), e["at"],
                                     e.get("actor_name"), e.get("channel")))
            for a in doc.get("audit", []):
                # an imported row is not a native one: it is written now, by the importer, on the channel `import`, and
                # keeps who and when it came with (and its own reason) as data, so the chain never vouches for them
                orig = {"actor": a.get("actor"), "channel": a.get("channel"), "at": a.get("at")}
                note = {"imported_from": bundle_sha, "orig": orig}
                if a.get("reason") is not None:
                    note["orig_reason"] = a["reason"]
                self.reg.add_audit(user, auditlog.IMPORT_CHANNEL, a["action"], a["target"], a.get("before_sha"), a.get("after_sha"),
                                   json.dumps(note, sort_keys=True))
            self.reg.add_event(run["id"], "run.imported", machines.ENGINE, {"bundle_sha256": bundle_sha, "imported_at": _now()})
            self.reg.add_audit(user, channel, "run_imported", slug, after_sha=bundle_sha)

    def _place_files(self, stage, slug):
        for src, dst in ((stage / "run", self.run_dir(slug)), (stage / "shared" / "specs" / slug, self.state_dir / "shared" / "specs" / slug)):
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.move(str(src), str(dst))
            else:
                dst.mkdir(parents=True, exist_ok=True)

    # ---- baseline of an imported run (ORC-07h)
    def check_imported_baseline(self, run):
        """R21: an imported active run whose baseline commit is missing in a repo is BLOCKED. Returns True when it moved."""
        import subprocess
        if run.get("origin") != "import" or run["state"] in machines.RUN_FINAL or run["state"] == "BLOCKED":
            return False
        cfg = self._run_config(run)
        for rr in self.reg.run_repos(run["id"]):
            path = self._repo_path(cfg, rr["repo_id"])
            ok = rr["baseline_sha"] and subprocess.run(["git", "-C", str(path), "cat-file", "-e", f"{rr['baseline_sha']}^{{commit}}"],
                                                       capture_output=True).returncode == 0
            if not ok:
                with self.reg.transaction():
                    run = self.reg.get_run_by_id(run["id"])
                    if run["state"] not in machines.RUN_FINAL and run["state"] != "BLOCKED":
                        self._move(run, "BLOCKED", machines.ENGINE,
                                   reason=f"baseline commit {str(rr['baseline_sha'])[:12]} is missing in repo {rr['repo_id']}")
                self._finish_up(run["slug"], run)
                return True
        return False
