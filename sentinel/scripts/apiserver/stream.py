"""The event hub: one poller reads the events tables of every registered project and feeds all stream clients.

Events are rows of the append-only `events` table, so CLI, task and AI-tool processes reach the stream through
the database (docs/contracts/event-contracts.md section 3). A stream starts at the current head; `Last-Event-ID`
(`<project>:<id>`) replays the rows a client missed; anything that cannot be replayed exactly becomes a `resync`
message that tells the client to re-fetch.
"""
import json
import queue
import sqlite3
import threading

from util import connect_ro

from .projects import scrub_obj

BATCH = 1000
LATE_PROJECT_BACKLOG = 200
KIND_CHANNEL = {"engine": "engine", "orchestrator": "cli", "human": "tty"}


def wire(event_type, data, event_id=None):
    head = f"id: {event_id}\n" if event_id else ""
    return f"{head}event: {event_type}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def resync(project, reason):
    return wire("resync", {"project": project, "reason": reason})


QUEUE_MAX = 10000


class Sub:
    def __init__(self, project, run, snapshot, session=None, queue_max=QUEUE_MAX):
        self.project, self.run, self.snapshot, self.session = project, run, snapshot, session
        self.q = queue.Queue(maxsize=queue_max)

    def close(self):
        try:
            self.q.put_nowait(None)
        except queue.Full:
            try:
                while True:
                    self.q.get_nowait()
            except queue.Empty:
                pass
            self.q.put_nowait(None)

    def push(self, text, project_id):
        """Queue a message. A client that falls too far behind loses its backlog and gets one resync instead."""
        try:
            self.q.put_nowait(text)
        except queue.Full:
            try:
                while True:
                    self.q.get_nowait()
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(resync(project_id, "client too slow"))
            except queue.Full:
                pass

    def wants(self, project, slug):
        return (self.project is None or self.project == project) and (self.run is None or slug == self.run)


def envelope(project, row, scrubber):
    keys = row.keys()
    kind = row["actor"]
    name = row["actor_name"] if "actor_name" in keys else None
    channel = (row["channel"] if "channel" in keys else None) or KIND_CHANNEL.get(kind, kind)
    payload = json.loads(row["payload"]) if row["payload"] else None
    return {"id": row["id"], "type": row["type"], "at": row["at"], "project": project.id, "run": row["run_slug"],
            "task": row["task_id"], "actor": {"kind": kind, "name": name, "channel": channel},
            "payload": scrub_obj(scrubber, payload) if payload is not None else None}


EVENT_SQL = ("SELECT e.*, r.slug AS run_slug FROM events e LEFT JOIN runs r ON r.id = e.run_id "
             "WHERE e.id > ? AND e.id <= ? ORDER BY e.id LIMIT ?")


class Hub:
    def __init__(self, projects, interval=0.5, log=None, queue_max=QUEUE_MAX):
        self.projects = projects
        self.queue_max = queue_max
        self.interval = interval
        self.log = log or (lambda msg: None)
        self.cursors, self.avail = {}, {}
        self.subs = set()
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    # ---- lifecycle
    def start(self):
        self._scan(initial=True)
        self._thread = threading.Thread(target=self._loop, name="sentinel-events", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(5)
        with self.lock:
            for sub in list(self.subs):
                sub.close()

    def count(self):
        with self.lock:
            return len(self.subs)

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self._scan()
            except Exception as e:  # a bad project must never stop the others
                self.log(f"event poller: {type(e).__name__}: {e}")

    # ---- subscribers
    def subscribe(self, project, run, session=None, max_per_session=None):
        with self.lock:
            if max_per_session and session is not None and sum(1 for s in self.subs if s.session == session) >= max_per_session:
                return None
            sub = Sub(project, run, dict(self.cursors), session, self.queue_max)
            self.subs.add(sub)
            return sub

    def unsubscribe(self, sub):
        with self.lock:
            self.subs.discard(sub)

    def _broadcast(self, project_id, slug, text):
        for sub in self.subs:
            if sub.wants(project_id, slug):
                sub.push(text, project_id)

    def _broadcast_resync(self, project_id, reason):
        with self.lock:
            for sub in self.subs:
                if sub.project in (None, project_id):
                    sub.push(resync(project_id, reason), project_id)

    # ---- reading
    def _open(self, project):
        """(connection or None) for a readable project; raises when the project cannot be read."""
        if not project.path.is_dir():
            raise OSError("workspace missing")
        config, reason = self.projects._load_config(project)
        if reason:
            raise OSError(reason)
        db = self.projects.db_path(project, config)
        if not db.exists():
            return None
        conn = connect_ro(db, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _head(self, conn):
        return conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0] if conn else 0

    def replay(self, project, after, upto, run=None):
        """Wire messages of the rows with after < id <= upto (resume of a client)."""
        scrubber = self.projects.scrubber(project)
        out = []
        conn = self._open(project)
        if conn is None:
            return out
        try:
            cur = after
            while cur < upto:
                rows = conn.execute(EVENT_SQL, (cur, upto, BATCH)).fetchall()
                if not rows:
                    break
                for r in rows:
                    if run is None or r["run_slug"] == run:
                        out.append(wire(r["type"], envelope(project, r, scrubber), f"{project.id}:{r['id']}"))
                cur = rows[-1]["id"]
        finally:
            conn.close()
        return out

    def has_event(self, project, event_id):
        if event_id == 0:
            return True
        conn = self._open(project)
        if conn is None:
            return False
        try:
            return conn.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone() is not None
        finally:
            conn.close()

    def _scan(self, initial=False):
        known = set()
        for project in self.projects.list():
            known.add(project.id)
            try:
                self._poll(project, initial)
            except Exception as e:
                self._down(project, initial, str(e))

    def _down(self, project, initial, why):
        was = self.avail.get(project.id)
        self.avail[project.id] = False
        if was is True or (was is None and not initial):
            self._broadcast_resync(project.id, "project unavailable")

    def _poll(self, project, initial):
        pid = project.id
        conn = None
        try:
            try:
                conn = self._open(project)
                head = self._head(conn)
            except (OSError, sqlite3.Error) as e:
                if isinstance(e, sqlite3.Error) and "no such table" in str(e):
                    head = 0
                else:
                    self._down(project, initial, str(e))
                    return
            was = self.avail.get(pid)
            self.avail[pid] = True
            if was is False:
                self._broadcast_resync(pid, "project available")
            cur = self.cursors.get(pid)
            if cur is None:
                with self.lock:
                    cur = self.cursors[pid] = head if initial else max(0, head - LATE_PROJECT_BACKLOG)
            if head < cur:
                with self.lock:
                    self.cursors[pid] = head
                self._broadcast_resync(pid, "database replaced")
                return
            scrubber = self.projects.scrubber(project)
            while head > cur and conn is not None:
                rows = conn.execute(EVENT_SQL, (cur, head, BATCH)).fetchall()
                if not rows:
                    break
                with self.lock:
                    for r in rows:
                        text = wire(r["type"], envelope(project, r, scrubber), f"{pid}:{r['id']}")
                        self._broadcast(pid, r["run_slug"], text)
                    self.cursors[pid] = cur = rows[-1]["id"]
        finally:
            if conn is not None:
                conn.close()
