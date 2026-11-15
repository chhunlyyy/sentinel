"""The route table: the only operations the server offers (plan/v1.1/phaseF/README.md point 3)."""
import re
from dataclasses import dataclass, field
from urllib.parse import unquote

from errors import SentinelError
from paths import slug_problem

from . import ops, views
from .projects import scrub_obj
from .status import HttpError

API = "/api/v1/"


@dataclass
class Route:
    method: str
    name: str
    template: str
    handler: object
    calls: tuple = ()
    regex: object = field(default=None, repr=False)


class StreamRequest:
    """Returned by the events route: the server turns it into a text/event-stream response."""

    def __init__(self, project=None, run=None):
        self.project, self.run = project, run


class Ctx:
    """What a handler may use: the server, the query, the checked JSON body, the session user."""

    def __init__(self, api, query, body, csrf=None, headers=None):
        self.api, self.query, self.body, self.csrf, self.headers = api, query, body, csrf, headers
        self.project = None

    @property
    def projects(self):
        return self.api.projects

    @property
    def user(self):
        return self.api.user

    def locate(self, slug):
        self.project = views.locate_run(self.projects, slug, self.query.get("project"))
        return self.project

    def clean(self, project, obj):
        return scrub_obj(self.projects.scrubber(project), obj)


# ---- installation, runtime, session
def h_session(ctx):
    return 200, {"csrf": ctx.csrf, "user": {"name": ctx.user, "role": "admin"}}


def h_installation(ctx):
    return 200, views.installation()


def h_runtime(ctx):
    api = ctx.api
    return 200, {"pid": api.pid, "port": api.port, "started_at": api.started_at, "version": views.installation()["version"],
                 "user": {"name": api.user, "role": "admin"},
                 "projects": [{"id": p.id, "name": p.name} for p in ctx.projects.list()]}


# ---- projects
def h_projects(ctx):
    return 200, {"items": [views.project_item(ctx.projects, p) for p in ctx.projects.list()], "next": None}


def h_project(ctx, pid):
    return 200, views.project_item(ctx.projects, ctx.projects.get(pid))


def h_project_runs(ctx, pid):
    project = ctx.projects.get(pid)
    ctx.project = project
    return 200, ctx.clean(project, views.list_runs(ctx.projects, project, ctx.query))


def h_create_run(ctx, pid):
    project = ctx.projects.get(pid)
    ctx.project = project
    config = ctx.projects.require(project)
    with ctx.projects.engine(project, ctx.user, ops.CHANNEL) as eng:
        slug = ops.create_run(eng, project, config, ctx.body, ctx.user)
        return 201, ctx.clean(project, views.run_detail(eng, project, slug))


# ---- one run: reads
def run_read(read):
    """A handler that locates the run and reads it through the engine of its project."""
    def handler(ctx, slug, **params):
        project = ctx.locate(slug)
        with ctx.projects.engine(project) as eng:
            return 200, ctx.clean(project, read(ctx, eng, project, slug, **params))
    handler.__name__ = read.__name__
    return handler


@run_read
def h_run(ctx, eng, project, slug):
    return views.run_detail(eng, project, slug)


@run_read
def h_next(ctx, eng, project, slug):
    return views.next_step(eng, slug, eng._get_v2(slug))


@run_read
def h_specification(ctx, eng, project, slug):
    return views.specification(eng, slug)


@run_read
def h_spec_version(ctx, eng, project, slug, version):
    return views.specification_version(eng, slug, version)


@run_read
def h_gherkin(ctx, eng, project, slug):
    return views.gherkin(eng, slug)


@run_read
def h_workflow(ctx, eng, project, slug):
    return views.workflow(eng.reg, eng._get(slug))


@run_read
def h_tdd(ctx, eng, project, slug):
    return views.tdd(eng.reg, eng._get(slug))


@run_read
def h_verification(ctx, eng, project, slug):
    return views.verification(eng.reg, eng._get(slug))


@run_read
def h_trace(ctx, eng, project, slug):
    return views.trace(eng.reg, eng._get(slug))


@run_read
def h_report(ctx, eng, project, slug):
    return views.report(eng.state_dir, slug, ctx.query.get("format", "json"))


@run_read
def h_artifact(ctx, eng, project, slug, aid):
    return views.artifact(eng.reg, eng.state_dir, slug, eng._get(slug), aid)


@run_read
def h_log(ctx, eng, project, slug, task_id):
    return views.log_tail(eng.reg, eng.state_dir, slug, eng._get(slug), task_id, ctx.query)


# ---- one run: decisions and controls
def h_approvals(ctx, slug):
    project = ctx.locate(slug)
    with ctx.projects.engine(project, ctx.user, ops.CHANNEL) as eng:
        ops.decide(eng, slug, ctx.body, ctx.user, ctx.api.git_name)
        return 200, ctx.clean(project, views.run_detail(eng, project, slug))


def h_acceptance(ctx, slug):
    project = ctx.locate(slug)
    with ctx.projects.engine(project, ctx.user, ops.CHANNEL) as eng:
        ops.accept(eng, slug, ctx.body, ctx.user, ctx.api.git_name)
        return 200, ctx.clean(project, views.run_detail(eng, project, slug))


def h_control(ctx, slug):
    ops.parse_control(ctx.body)
    project = ctx.locate(slug)
    with ctx.projects.engine(project, ctx.user, ops.CHANNEL) as eng:
        ops.control(eng, slug, ctx.body, ctx.user)
        return 200, ctx.clean(project, views.run_detail(eng, project, slug))


# ---- across projects
def h_approval_list(ctx):
    return 200, views.approvals_in(ctx.projects, ctx.query.get("state", "IN_REVIEW"))


def h_audit(ctx):
    pid = ctx.query.get("project")
    return 200, views.audit_rows(ctx.projects, pid, ctx.query)


def h_events(ctx):
    pid, run = ctx.query.get("project"), ctx.query.get("run")
    project = ctx.projects.get(pid) if pid else None
    if run:
        problem = slug_problem(run)
        if problem:
            raise views.validation(problem, "run")
        views.locate_run(ctx.projects, run, pid)
    return 200, StreamRequest(project.id if project else None, run)


ROUTES = [
    Route("GET", "session", "session", h_session),
    Route("GET", "installation", "installation", h_installation),
    Route("GET", "runtime", "runtime", h_runtime),
    Route("GET", "projects", "projects", h_projects),
    Route("GET", "project", "projects/{pid}", h_project),
    Route("GET", "project_runs", "projects/{pid}/tasks", h_project_runs),
    Route("POST", "create_run", "projects/{pid}/tasks", h_create_run, ("Engine.create_run",)),
    Route("GET", "run", "tasks/{slug}", h_run),
    Route("GET", "next", "tasks/{slug}/next", h_next),
    Route("GET", "specification", "tasks/{slug}/specification", h_specification),
    Route("GET", "specification_version", "tasks/{slug}/specification/versions/{version}", h_spec_version),
    Route("GET", "gherkin", "tasks/{slug}/gherkin", h_gherkin),
    Route("GET", "workflow", "tasks/{slug}/workflow", h_workflow),
    Route("GET", "tdd", "tasks/{slug}/tdd", h_tdd),
    Route("GET", "verification", "tasks/{slug}/verification", h_verification),
    Route("GET", "trace", "tasks/{slug}/trace", h_trace),
    Route("GET", "report", "tasks/{slug}/report", h_report),
    Route("GET", "artifact", "tasks/{slug}/artifacts/{aid}", h_artifact),
    Route("GET", "log", "tasks/{slug}/logs/{task_id}", h_log),
    Route("POST", "approvals", "tasks/{slug}/approvals", h_approvals, ("Engine.decide",)),
    Route("POST", "acceptance", "tasks/{slug}/acceptance", h_acceptance, ("Engine.accept",)),
    Route("POST", "control", "tasks/{slug}/control", h_control,
          ("Engine.cancel_run", "Engine.resume_run", "Engine.cancel_task_control", "Engine.retry_task")),
    Route("GET", "approval_list", "approvals", h_approval_list),
    Route("GET", "audit", "audit", h_audit),
    Route("GET", "events", "events", h_events),
]

for _r in ROUTES:
    _r.regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", _r.template) + "$")

# Contract routes that Phase G and H build. Until then they answer 404, so this module is the only allow-list.
UNBUILT = [(m, re.compile(p)) for m, p in [
    ("POST", r"projects"), ("POST", r"projects/register"), ("PATCH|DELETE", r"projects/[^/]+"),
    ("POST", r"projects/[^/]+/archive"), ("GET", r"projects/[^/]+/readiness"),
    ("GET|POST|PATCH|DELETE|PUT", r"projects/[^/]+/repositories(/.*)?"),
    ("GET|POST|PUT|PATCH|DELETE", r"projects/[^/]+/configuration(/.*)?"), ("GET|PUT", r"configuration/global"),
    ("GET", r"fs/dirs"), ("GET", r"providers"), ("POST", r"providers/[^/]+/test"), ("GET", r"agents"),
    ("GET", r"workflows|policies|profiles"), ("GET", r"installation/health"),
    ("GET", r"tasks/[^/]+/changes(/diff)?"), ("POST", r"tasks/[^/]+/publish"),
    ("GET|POST", r"notifications(/[^/]+/read)?"), ("GET", r"reports/analytics"),
]]


def match(method, path):
    """(route, params) for a built route. Raises HttpError 404 for unknown and unbuilt routes, 405 for a wrong method."""
    if not path.startswith(API):
        raise HttpError("E_NOT_FOUND", "no such route")
    rel = path[len(API):]
    allowed = []
    for route in ROUTES:
        m = route.regex.match(rel)
        if not m:
            continue
        if route.method == method:
            params = {k: unquote(v) for k, v in m.groupdict().items()}
            if any(("/" in v or "\\" in v or "\0" in v) for v in params.values()):
                raise HttpError("E_NOT_FOUND", "no such route")
            return route, params
        allowed.append(route.method)
    if any(method in verbs.split("|") and rx.fullmatch(rel) for verbs, rx in UNBUILT):
        raise HttpError("E_NOT_FOUND", "no such route")
    if allowed:
        raise HttpError("E_METHOD", f"{method} is not allowed here", headers={"Allow": ", ".join(sorted(set(allowed)))})
    raise HttpError("E_NOT_FOUND", "no such route")
