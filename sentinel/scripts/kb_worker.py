"""Knowledge base background harvest: the kb_jobs queue and the worker that turns a completed run into knowledge/.

complete_run enqueues a `kb_harvest` job and starts a detached `sentinel kb worker`. The worker holds one instance per
workspace (a pid lock file), takes the shared-repo knowledge lock for each job, writes the verified record of the run,
ingests the tracked branches, runs the scrub check and, when knowledge.auto_push is on, commits only knowledge/ and
proposals/knowledge-* and pushes. Source: plan/knowledge-base.md, "Background harvest after a v2 run".
"""
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import yaml

import adapters
import knowledge
import scrub
from registry import Registry, _now
from shared import Shared

KIND = "kb_harvest"
KIND_REFRESH = "refresh"
LOCK_NAME = "knowledge"
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (5, 30)  # waits after attempt 1 and attempt 2
PID_FILE = "kb-worker.lock"
LOG_FILE = "kb-worker.log"
PUBLISH_PATHS = ("knowledge",)
PUBLISH_GLOB = "proposals/knowledge-*"


class PermanentFailure(Exception):
    """A failure a retry cannot fix (the scrub check): the job fails at once."""


def _state_dir(workspace, config):
    return Path(workspace) / (config.get("state") or {}).get("dir", ".sentinel")


def _load_config(workspace):
    return yaml.safe_load((Path(workspace) / "sentinel.config.yaml").read_text()) or {}


def _log(message):
    print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {message}", flush=True)


# ---- queue
def enqueue_harvest(registry, run_slug):
    """Queue a harvest of `run_slug`; an already queued or running one for the run is reused. Returns the job id."""
    for job in registry.rows("kb_jobs", kind=KIND, run_slug=run_slug):
        if job["state"] in ("queued", "running"):
            return job["id"]
    now = _now()
    return registry.insert_row("kb_jobs", {"kind": KIND, "run_slug": run_slug, "state": "queued", "attempts": 0,
                                           "created_at": now, "updated_at": now})


def enqueue_refresh(registry):
    """Queue a refresh job; only one queued refresh job at a time (dedupe). Returns the job id."""
    for job in registry.rows("kb_jobs", kind=KIND_REFRESH):
        if job["state"] == "queued":
            return job["id"]
    now = _now()
    return registry.insert_row("kb_jobs", {"kind": KIND_REFRESH, "run_slug": None, "state": "queued", "attempts": 0,
                                           "created_at": now, "updated_at": now})


def _set(registry, job_id, **fields):
    with registry.transaction():
        registry.update_row("kb_jobs", job_id, updated_at=_now(), **fields)


def job_summary(registry):
    """{"queued", "last_success", "last_failure"} of the knowledge jobs; the last two are small dicts or None."""
    jobs = registry.rows("kb_jobs")
    return summarize_jobs(jobs)


def summarize_jobs(jobs):
    def last(state):
        found = [j for j in jobs if j["state"] == state]
        if not found:
            return None
        j = max(found, key=lambda j: j["updated_at"])
        return {"id": j["id"], "run": j["run_slug"], "at": j["updated_at"], "attempts": j["attempts"], "error": j["error"]}
    return {"queued": len([j for j in jobs if j["state"] in ("queued", "running")]),
            "last_success": last("done"), "last_failure": last("failed")}


def job_summary_from_db(db_path):
    """Same as job_summary for a registry file, read only; None when it has no kb_jobs table (an older registry)."""
    import sqlite3
    from util import connect_ro
    try:
        conn = connect_ro(db_path)
    except sqlite3.Error:
        return None
    try:
        conn.row_factory = sqlite3.Row
        return summarize_jobs([dict(r) for r in conn.execute("SELECT * FROM kb_jobs")])
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def knowledge_enabled(config):
    return bool(knowledge.kb_config(config)["enabled"])


# ---- spawn
def spawn_worker(workspace):
    """Start `sentinel kb worker` detached. Never raises: a failure is logged and the caller carries on."""
    try:
        if os.environ.get("SENTINEL_KB_NO_SPAWN"):
            return None
        config = _load_config(workspace)
        state = _state_dir(workspace, config)
        state.mkdir(parents=True, exist_ok=True)
        script = Path(__file__).resolve().parent / "sentinel.py"
        with open(state / LOG_FILE, "ab") as log:
            proc = subprocess.Popen([sys.executable, str(script), "--dir", str(workspace), "kb", "worker"],
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, cwd=str(workspace))
        return proc.pid
    except Exception as e:  # noqa: BLE001 - completing a run must never fail because of knowledge
        print(f"knowledge worker not started: {e}", file=sys.stderr)
        return None


def on_run_completed(registry, workspace, config, run_slug):
    """The complete_run hook: queue the harvest and start the worker. Never raises."""
    try:
        if not knowledge_enabled(config):
            return None
        shared = Shared(workspace, config)
        if not shared.local and not shared.url:
            return None  # no shared repo to hold the knowledge
        job = enqueue_harvest(registry, run_slug)
        spawn_worker(workspace)
        return job
    except Exception as e:  # noqa: BLE001
        print(f"knowledge harvest not queued for {run_slug}: {e}", file=sys.stderr)
        return None


def on_pull(workspace, config=None):
    """Queue a refresh job and spawn the worker after a successful pull. Never raises."""
    try:
        if config is None:
            config = _load_config(workspace)
        if not knowledge_enabled(config):
            return None
        shared = Shared(workspace, config)
        if not shared.local and not shared.url:
            return None
        state = _state_dir(workspace, config)
        registry = Registry.open(state)
        try:
            job = enqueue_refresh(registry)
        finally:
            registry.close()
        spawn_worker(workspace)
        return job
    except Exception as e:  # noqa: BLE001 - pull must never fail because of knowledge
        print(f"knowledge refresh not queued: {e}", file=sys.stderr)
        return None


on_pull_completed = on_pull


# ---- single instance
def _read_pid_file(path):
    try:
        pid, started = Path(path).read_text().split()
        return int(pid), started
    except (OSError, ValueError):
        return None, None


def acquire_instance(state_dir):
    """Create the pid lock file. False when a live worker holds it; a file of a dead process is replaced."""
    path = Path(state_dir) / PID_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid, started = _read_pid_file(path)
            if pid and adapters.process_alive(pid, started):
                return False
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid()} {adapters.process_start_time(os.getpid())}\n")
        return True
    return False


def release_instance(state_dir):
    path = Path(state_dir) / PID_FILE
    pid, _ = _read_pid_file(path)
    if pid == os.getpid():
        try:
            path.unlink()
        except FileNotFoundError:
            pass


# ---- the record of a run
def _git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)


def _current_branch(repo_path):
    out = _git(repo_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return out if out and out != "HEAD" else (knowledge.resolve_default_branch(repo_path) or "HEAD")


def _files_between(repo_path, base, final):
    if not base or not final:
        return []
    out = _git(repo_path, "diff", "--name-only", f"{base}..{final}")
    return [l for l in out.stdout.splitlines() if l.strip()] if out.returncode == 0 else []


def write_run_record(registry, workspace, config, shared_dir, slug, scrubber=None):
    """Write the verified record `run-<slug>`; returns its path relative to the shared dir."""
    run = registry.get_run(slug)
    if not run:
        raise PermanentFailure(f"no run named {slug}")
    shared_dir = Path(shared_dir)
    specs = shared_dir / "specs" / slug
    spec_path = f"specs/{slug}/spec.md" if (specs / "spec.md").is_file() else None
    features = sorted(p.relative_to(shared_dir).as_posix() for p in (specs / "features").rglob("*.feature")) if (specs / "features").is_dir() else []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    repo_cfgs = {r.get("id"): r for r in config.get("repos") or [] if isinstance(r, dict)}
    reached, shas, files = [], {}, []
    for rr in registry.run_repos(run["id"]):
        rid = rr["repo_id"]
        path = (Path(workspace) / (repo_cfgs.get(rid) or {}).get("path", rid)).resolve()
        if not path.is_dir():
            continue
        shas[rid] = rr["final_sha"]
        if rr["final_sha"]:
            reached.append({"repo": rid, "branch": _current_branch(path), "sha": rr["final_sha"], "at": now})
        files += [f"{rid}/{f}" for f in _files_between(path, rr["baseline_sha"], rr["final_sha"])]
    repo_ids = list(shas)
    primary = repo_ids[0] if repo_ids else (next(iter(repo_cfgs), None) or "workspace")
    key = f"run-{slug}"
    index = knowledge.read_index(shared_dir)
    old = index.get(key)
    rel = old["path"] if old and old.get("path") else str(knowledge.record_path(shared_dir, primary, key, now[:7]).relative_to(shared_dir))
    meta = {"key": key, "repo": primary, "repos": repo_ids, "provenance": "verified", "status": "active",
            "reached": reached, "authors": [], "title": (run["request"] or slug).split("\n", 1)[0][:200],
            "files": sorted(set(files)), "modules": knowledge.top_modules(sorted(set(files))),
            "run": slug, "spec": spec_path, "features": features, "final_shas": shas}
    body = ["\n## What changed\n", f"Sentinel run `{slug}`: {run['request'] or slug}\n"]
    if spec_path:
        body.append(f"\nSpec: `{spec_path}`\n")
    if features:
        body.append("\nGherkin:\n" + "".join(f"- `{f}`\n" for f in features))
    try:
        trace = json.loads((_state_dir(workspace, config) / "runs" / slug / "report.json").read_text()).get("trace") or {}
        body.append(f"\n## Trace\n{len(trace.get('gaps') or [])} gap(s), {len(trace.get('failures') or [])} failure(s), "
                    f"{trace.get('links', 0)} link(s)\n")
    except (OSError, ValueError, AttributeError):
        pass
    knowledge.write_record(shared_dir / rel, meta, "\n".join(body), scrubber=scrubber)
    index[key] = {"path": rel, "repo": primary, "reached": reached, "provenance": "verified", "status": "active",
                  "files": meta["files"]}
    knowledge.write_index(shared_dir, index)
    return rel


# ---- publish
def _proposal_paths(shared_dir):
    return sorted(p.relative_to(shared_dir).as_posix() for p in (Path(shared_dir) / "proposals").glob("knowledge-*")) \
        if (Path(shared_dir) / "proposals").is_dir() else []


def _publish_paths(shared_dir):
    return [*PUBLISH_PATHS, *_proposal_paths(shared_dir)]


def _discard_local_knowledge(shared_dir):
    """Drop uncommitted knowledge/ changes of the shared clone (derived data, rebuilt by the next attempt)."""
    paths = _publish_paths(shared_dir)
    _git(shared_dir, "checkout", "HEAD", "--", *paths)
    _git(shared_dir, "clean", "-fdq", "--", *paths)


def _commit_knowledge(shared, message):
    """Stage and commit only the knowledge paths. Returns False when there was nothing to commit."""
    paths = _publish_paths(shared.dir)
    existing = [p for p in paths if (shared.dir / p).exists()]
    if not existing:
        return False
    add = _git(shared.dir, "add", "--", *existing)
    if add.returncode != 0:
        raise RuntimeError(f"git add failed: {add.stderr.strip()}")
    if _git(shared.dir, "diff", "--cached", "--quiet", "--", *existing).returncode == 0:
        return False
    ident = [] if _git(shared.dir, "config", "user.email").stdout.strip() else ["-c", "user.name=sentinel", "-c", "user.email=sentinel@localhost"]
    commit = _git(shared.dir, *ident, "commit", "-q", "-m", message, "--", *existing)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}")
    return True


def _unpushed_non_knowledge(shared):
    """Files changed by unpushed commits on the shared ref that are outside the knowledge paths."""
    upstream = _git(shared.dir, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    base = upstream.stdout.strip() if upstream.returncode == 0 else f"origin/{shared.ref}"
    names = _git(shared.dir, "diff", "--name-only", f"{base}...HEAD").stdout.split()
    return [n for n in names if not (n.startswith("knowledge/") or n.startswith("proposals/knowledge-"))]


def publish(shared, config, scrubber, message):
    """Scrub check, then commit and push the knowledge paths as the config says. Never force-pushes."""
    problems = scrub.check_paths([knowledge.kb_root(shared.dir)], scrubber)
    if problems:
        if not shared.local:
            _discard_local_knowledge(shared.dir)
        names = "; ".join(f"{Path(p).relative_to(shared.dir).as_posix()}: {', '.join(f)}" for p, f in sorted(problems.items()))
        raise PermanentFailure(f"scrub check failed, nothing pushed: {names}")
    if shared.local:
        return "local"
    shared.require_ref_branch()
    if shared.merging():
        raise RuntimeError("a merge is in progress in the shared repo; resolve it first")
    _git(shared.dir, "checkout", shared.ref)
    committed = _commit_knowledge(shared, message)
    if not knowledge.kb_config(config)["auto_push"]:
        return "committed locally" if committed else "unchanged"
    if not shared.ahead():
        return "unchanged"
    others = _unpushed_non_knowledge(shared)
    if others:
        # Never publish a teammate's or a run's unpushed shared-repo commits; those keep their human gate.
        return "committed locally (other unpushed changes wait for sentinel sync push: " + ", ".join(others[:5]) + ")"
    try:
        shared.integrate()
    except SystemExit as stop:
        if shared.merging():
            _git(shared.dir, "merge", "--abort")
            if committed:
                _git(shared.dir, "reset", "-q", "--mixed", "HEAD~1")
                _discard_local_knowledge(shared.dir)
        raise RuntimeError(f"could not integrate with the shared remote: {stop}") from None
    return "pushed"


def publish_under_lock(workspace, config, scrubber, message):
    """Publish knowledge under the knowledge lock. Used by CI and CLI."""
    shared = Shared(workspace, config)
    if not shared.local and not shared.is_clone():
        try:
            shared.pull(refresh=False)
        except SystemExit as stop:
            raise RuntimeError(f"cannot pull the shared repo: {stop}") from None
    try:
        shared.acquire(LOCK_NAME, f"kb-publish-{os.getpid()}")
    except SystemExit as stop:
        raise RuntimeError(str(stop)) from None
    try:
        return publish(shared, config, scrubber, message)
    finally:
        try:
            shared.release(LOCK_NAME)
        except SystemExit:
            pass


# ---- one job
def process_job(registry, workspace, config, job):
    """One attempt of a harvest or refresh job; raises on failure."""
    kind = job.get("kind") or KIND
    slug = job.get("run_slug")
    shared = Shared(workspace, config)
    shared_dir = shared.dir
    scrubber = scrub.Scrubber(workspace, scrub.env_values(workspace))
    if not shared.local and not shared.is_clone():
        try:
            shared.pull(refresh=False)  # a lock needs the clone's remote
        except SystemExit as stop:
            raise RuntimeError(f"cannot pull the shared repo: {stop}") from None
    try:
        shared.acquire(LOCK_NAME, f"kb-worker-{os.getpid()}")
    except SystemExit as stop:
        raise RuntimeError(str(stop)) from None
    try:
        try:
            shared.pull(refresh=False)
        except SystemExit as stop:
            raise RuntimeError(f"cannot pull the shared repo: {stop}") from None
        knowledge.ensure_layout(shared_dir)
        if kind == KIND_REFRESH:
            knowledge.ingest(str(shared_dir), str(workspace), config, scrubber=scrubber)
            refresh = getattr(knowledge, "refresh_summaries", None)
            if refresh:
                refresh(str(shared_dir), str(workspace), config, scrubber=scrubber)
            return publish(shared, config, scrubber, "sentinel: knowledge refresh")
        else:
            write_run_record(registry, workspace, config, shared_dir, slug, scrubber)
            knowledge.ingest(str(shared_dir), str(workspace), config, scrubber=scrubber)
            refresh = getattr(knowledge, "refresh_summaries", None)
            if refresh:
                refresh(str(shared_dir), str(workspace), config, scrubber=scrubber)
            return publish(shared, config, scrubber, f"sentinel: knowledge for {slug}")
    finally:
        try:
            shared.release(LOCK_NAME)
        except SystemExit:
            pass


def _fail(registry, job, error):
    run = registry.get_run(job["run_slug"]) if job["run_slug"] else None
    with registry.transaction():
        registry.update_row("kb_jobs", job["id"], state="failed", error=error[:500], updated_at=_now())
        if run:
            registry.add_event(run["id"], "knowledge.failed", "engine", {"job": job["id"], "error": error[:200]})


def run_job(registry, workspace, config, job, sleep=time.sleep):
    """Run a job to done, or to failed after MAX_ATTEMPTS attempts (a scrub failure fails at once)."""
    attempts = job["attempts"]
    while True:
        attempts += 1
        _set(registry, job["id"], state="running", attempts=attempts)
        try:
            outcome = process_job(registry, workspace, config, job)
        except PermanentFailure as e:
            _fail(registry, job, str(e))
            _log(f"job {job['id']} failed: {e}")
            return False
        except Exception as e:  # noqa: BLE001
            _log(f"job {job['id']} attempt {attempts} failed: {e}\n{traceback.format_exc()}")
            if attempts >= MAX_ATTEMPTS:
                _fail(registry, job, str(e))
                return False
            _set(registry, job["id"], state="queued", error=str(e)[:500])
            sleep(BACKOFF_SECONDS[min(attempts, len(BACKOFF_SECONDS)) - 1])
            continue
        _set(registry, job["id"], state="done", error=None)
        _log(f"job {job['id']} done ({outcome})")
        return True


def run_worker(workspace, sleep=time.sleep):
    """Process queued jobs until none is left. Returns the number of jobs handled, or None when another worker is live."""
    workspace = Path(workspace)
    config = _load_config(workspace)
    state = _state_dir(workspace, config)
    if not acquire_instance(state):
        _log("another knowledge worker is running")
        return None
    registry = Registry.open(state)
    handled = 0
    try:
        with registry.transaction():  # a job left running belongs to a worker that died
            for job in registry.rows("kb_jobs", state="running"):
                registry.update_row("kb_jobs", job["id"], state="queued", updated_at=_now())
        while True:
            queued = registry.rows("kb_jobs", state="queued")
            if not queued:
                break
            run_job(registry, workspace, config, queued[0], sleep=sleep)
            handled += 1
    finally:
        registry.close()
        release_instance(state)
    return handled
