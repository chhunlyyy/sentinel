"""The route table: the only operations the server offers (plan/v1.1/phaseF/README.md point 3)."""
import re
import threading
import uuid
from dataclasses import dataclass, field
from urllib.parse import unquote

from errors import SentinelError
from paths import slug_problem

import analytics
import chat
import factory
import notifications
import providers

from . import manage, ops, readroutes, views
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
        slug = ops.create_run(eng, project, config, ctx.body, ctx.user, scrubber=ctx.projects.scrubber(project))
        return 201, ctx.clean(project, views.run_detail(eng, project, slug))


def h_create_project(ctx):
    return 201, views.project_item(ctx.projects, manage.create_project(ctx, ctx.body))


def h_register_project(ctx):
    created, project = manage.register_project(ctx, ctx.body)
    return (201 if created else 200), views.project_item(ctx.projects, project)


def h_add_repository(ctx, pid):
    return 201, manage.add_repository(ctx, pid, ctx.body)


def h_delete_project(ctx, pid):
    return 200, manage.delete_project(ctx, pid)


def h_remove_repository(ctx, pid, rid):
    return 200, manage.remove_repository(ctx, pid, rid)


def h_providers(ctx):
    return 200, manage.providers_view(ctx)


def h_provider_test(ctx, rid):
    return 200, manage.probe(ctx, rid)


def h_agents(ctx):
    return 200, manage.agents_get(ctx)


def h_agents_put(ctx):
    return 200, manage.agents_put(ctx, ctx.body)


def h_fs_dirs(ctx):
    return 200, manage.fs_dirs(ctx.query)


def h_profiles(ctx):
    return 200, manage.profiles_view()


def h_orchestrator(ctx):
    return 200, manage.orchestrator_view(ctx)


def h_orchestrator_put(ctx):
    return 200, manage.set_orchestrator(ctx, ctx.body)


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
    return views.verification(eng, eng._get(slug))


@run_read
def h_trace(ctx, eng, project, slug):
    return views.trace(eng.reg, eng._get(slug))


@run_read
def h_report(ctx, eng, project, slug):
    return views.report(eng.reg, eng.state_dir, slug, eng._get(slug), ctx.query.get("format", "json"))


@run_read
def h_artifact(ctx, eng, project, slug, aid):
    return views.artifact(eng.reg, eng.state_dir, slug, eng._get(slug), aid)


@run_read
def h_log(ctx, eng, project, slug, task_id):
    run = eng._get(slug)
    return views.log_tail(eng.reg, eng.state_dir, slug, run, task_id, ctx.query,
                          scrubber=ctx.projects.scrubber(project), config=eng._run_config(run))


@run_read
def h_changes(ctx, eng, project, slug):
    return readroutes.changes(eng, project, slug)


@run_read
def h_changes_diff(ctx, eng, project, slug):
    return readroutes.changes_diff(eng, project, slug, ctx.query)


# ---- Phase G read routes
def h_health(ctx):
    return 200, readroutes.health_view(ctx.projects, ctx.api.cfgdir)


def _project_read(fn):
    def handler(ctx, pid):
        project = ctx.projects.get(pid)
        ctx.project = project
        return 200, ctx.clean(project, fn(ctx, project))
    handler.__name__ = fn.__name__
    return handler


@_project_read
def h_readiness(ctx, project):
    return readroutes.readiness(ctx.projects, project, ctx.query)


@_project_read
def h_repositories(ctx, project):
    return readroutes.repositories(ctx.projects, project)


@_project_read
def h_configuration(ctx, project):
    return readroutes.configuration(ctx.projects, project, ctx.api.cfgdir)


@_project_read
def h_config_history(ctx, project):
    return readroutes.configuration_history(ctx.projects, project)


@_project_read
def h_config_diff(ctx, project):
    return readroutes.configuration_diff(ctx.projects, project, ctx.query)


# ---- W3 Setup and Detection
def h_detect(ctx):
    return 200, manage.detect_paths(ctx.body)


def h_shared_test(ctx):
    return 200, manage.test_shared(ctx.body)


def h_routing_suggest(ctx):
    return 200, manage.suggest_routing()


@_project_read
def h_routing_fix(ctx, project):
    """The "Fix routing" dialog: the roles that block engine runs, a suggested runner and model for each, and the config
    changes that apply the suggestion (saved through the config preview and save routes)."""
    if ctx.query:
        extra = sorted(ctx.query)[0]
        raise views.validation(f"unknown query parameter {extra}", extra)
    _, config = manage.read_project_config(project)
    return {"project": project.id, **factory.routing_fix(config, providers.suggest_routing(config))}


# ---- Config Form
@_project_read
def h_config_form(ctx, project):
    return manage.config_form(ctx.projects, project)


def h_config_preview(ctx, pid):
    project = ctx.projects.get(pid)
    ctx.project = project
    return 200, ctx.clean(project, manage.config_preview(ctx, project, ctx.body))


def h_config_save(ctx, pid):
    project = ctx.projects.get(pid)
    ctx.project = project
    return 200, ctx.clean(project, manage.config_save(ctx, project, ctx.body))


# ---- Knowledge
@_project_read
def h_knowledge_related(ctx, project):
    return readroutes.knowledge_related(ctx.projects, project, ctx.query)


@_project_read
def h_knowledge_status(ctx, project):
    return readroutes.knowledge_status(ctx.projects, project)


@_project_read
def h_knowledge_records(ctx, project):
    return readroutes.knowledge_records(ctx.projects, project, ctx.query)


def h_knowledge_record(ctx, pid, key):
    project = ctx.projects.get(pid)
    ctx.project = project
    return 200, ctx.clean(project, readroutes.knowledge_record(ctx.projects, project, key))


@_project_read
def h_knowledge_ci_template(ctx, project):
    return readroutes.knowledge_ci_template(ctx.projects, project, ctx.query)


def h_knowledge_ingest(ctx, pid):
    return 202, manage.knowledge_ingest(ctx, pid)


def h_knowledge_snapshot(ctx, pid):
    return 202, manage.knowledge_snapshot(ctx, pid)


def h_knowledge_backfill_estimate(ctx, pid):
    return 200, manage.knowledge_backfill_estimate(ctx, pid, ctx.body)


def h_knowledge_backfill(ctx, pid):
    return 200, manage.knowledge_backfill(ctx, pid, ctx.body)


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


def h_pause(ctx, slug):
    ops.parse_pause(ctx.body)
    project = ctx.locate(slug)
    with ctx.projects.engine(project, ctx.user, ops.CHANNEL) as eng:
        ops.pause(eng, slug, ctx.body, ctx.user)
        return 200, ctx.clean(project, views.run_detail(eng, project, slug))


def h_unpause(ctx, slug):
    ops.parse_pause(ctx.body)
    project = ctx.locate(slug)
    with ctx.projects.engine(project, ctx.user, ops.CHANNEL) as eng:
        ops.unpause(eng, slug, ctx.body, ctx.user)
        return 200, ctx.clean(project, views.run_detail(eng, project, slug))


def h_note(ctx, slug):
    ops.parse_note(ctx.body)
    project = ctx.locate(slug)
    with ctx.projects.engine(project, ctx.user, ops.CHANNEL) as eng:
        note_id = ops.note(eng, slug, ctx.body, ctx.user)
        return 201, ctx.clean(project, {"note": note_id, **views.run_detail(eng, project, slug)})


def h_retry_now(ctx, slug):
    project = ctx.locate(slug)
    with ctx.projects.engine(project, ctx.user, ops.CHANNEL) as eng:
        res = ops.retry_now(eng, slug, ctx.user)
        return 200, ctx.clean(project, {**res, **views.run_detail(eng, project, slug)})


def h_chat(ctx, slug):
    project = ctx.locate(slug)
    config = ctx.projects.require(project)
    runner, model = chat.orchestrator_target(config, ctx.api)
    with ctx.projects.engine(project) as eng:
        eng._open_run(slug)
        items = chat.read_chat(eng.run_dir(slug))
        return 200, ctx.clean(project, {"items": items, "orchestrator": {"runner": runner, "model": model}})


def h_chat_send(ctx, slug):
    ops.check_fields(ctx.body, ("text",), ("text",))
    text = ops.text_field(ctx.body, "text")
    if not text or not text.strip():
        raise SentinelError("E_VALIDATION", "a chat message needs text", {"field": "text"})
    text = text.strip()
    if len(text) > chat.USER_MAX:
        raise SentinelError("E_VALIDATION", f"chat message text exceeds {chat.USER_MAX} characters", {"field": "text"})

    project = ctx.locate(slug)
    config = ctx.projects.require(project)
    runner, model = chat.orchestrator_target(config, ctx.api)

    with ctx.projects.engine(project, ctx.user, ops.CHANNEL) as eng:
        eng._open_run(slug)
        rdir = eng.run_dir(slug)
        if chat.has_pending_reply(rdir):
            raise SentinelError("E_PRECONDITION", "another orchestrator reply is already pending for this run")

        user_id = f"u-{uuid.uuid4().hex[:12]}"
        orch_id = f"o-{uuid.uuid4().hex[:12]}"
        user_item = {"id": user_id, "role": "user", "text": text, "at": chat._now(), "status": "done"}
        orch_item = {"id": orch_id, "role": "orchestrator", "text": "", "at": chat._now(), "status": "pending"}

        chat.append_chat(rdir, user_item)
        chat.append_chat(rdir, orch_item)
        eng.audit(ctx.user, ops.CHANNEL, "chat", slug, reason=text[:64])

    t = threading.Thread(
        target=chat.reply_worker,
        args=(ctx.projects, project, slug, orch_id, runner, model, ctx.api),
        name=f"chat-worker-{slug}-{orch_id}",
        daemon=True,
    )
    t.start()

    return 202, ctx.clean(project, {"user": user_item, "orchestrator": orch_item, "items": [user_item, orch_item]})



def h_factory(ctx, pid):
    if ctx.query:
        extra = sorted(ctx.query)[0]
        raise views.validation(f"unknown query parameter {extra}", extra)
    project = ctx.projects.get(pid)
    ctx.project = project
    ctx.projects.require(project)
    total = views.running_total(ctx.projects)
    with ctx.projects.engine(project) as eng:
        return 200, ctx.clean(project, factory.snapshot(eng, project.id, total_running=total,
                                                        factory_paused=factory.pause_state(ctx.api.cfgdir)["paused"]))


def _factory_pause_body(ctx):
    return {**factory.pause_state(ctx.api.cfgdir), "running_total": views.running_total(ctx.projects),
            "max_agents": factory.max_agents_over(ctx.projects)}


def h_factory_get(ctx):
    if ctx.query:
        extra = sorted(ctx.query)[0]
        raise views.validation(f"unknown query parameter {extra}", extra)
    return 200, _factory_pause_body(ctx)


def h_factory_pause(ctx):
    ops.factory_pause(ctx.api.cfgdir, ctx.projects, True, ctx.body, ctx.user)
    return 200, _factory_pause_body(ctx)


def h_factory_resume(ctx):
    ops.factory_pause(ctx.api.cfgdir, ctx.projects, False, ctx.body, ctx.user)
    return 200, _factory_pause_body(ctx)


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


# ---- Phase H part A: notifications and analytics (read side; mark-read writes only ~/.config/sentinel/user.db)
def _notification_sources(ctx):
    return notifications.sources_from_projects(ctx.projects, ctx.projects.scrubber)


def _user_db(ctx):
    return ctx.api.cfgdir / notifications.USER_DB


def h_notifications(ctx):
    pid = ctx.query.get("project")
    if pid:
        ctx.projects.get(pid)
    limit = views.parse_limit(ctx.query)
    cursor = views.decode_cursor(ctx.query["cursor"], 3) if ctx.query.get("cursor") else None
    if cursor and not (isinstance(cursor[0], str) and isinstance(cursor[1], str) and isinstance(cursor[2], int)):
        raise views.validation("cursor is not valid", "cursor")
    unread = ctx.query.get("unread", "").lower() in ("1", "true", "yes")
    result = notifications.compute(_notification_sources(ctx), _user_db(ctx), project=pid, limit=limit, cursor=cursor, unread_only=unread)
    result["items"] = [notifications.public(n) for n in result["items"]]
    result["next"] = views.encode_cursor(*result["next"]) if result["next"] else None
    return 200, result


def h_notification_read(ctx, nid):
    try:
        n = notifications.mark_read(_notification_sources(ctx), _user_db(ctx), nid)
    except notifications.UserDbError as e:
        raise HttpError("E_INTERNAL", e.message, {"fix": e.fix})
    return 200, notifications.public(n)


def h_analytics(ctx):
    extra = sorted(set(ctx.query) - {"project", "from", "to"})
    if extra:
        raise views.validation(f"unknown query parameter {extra[0]}", extra[0])
    pid = ctx.query.get("project")
    if not pid:
        raise views.validation("project is required", "project")
    project = ctx.projects.get(pid)
    ctx.project = project
    start, end = analytics.check_range(ctx.query.get("from"), ctx.query.get("to"))
    config = ctx.projects.require(project)
    return 200, analytics.compute(ctx.projects.db_path(project, config), start, end, providers=analytics.runner_ids(config))


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
          ("Engine.cancel_run", "Engine.resume_run", "Engine.cancel_task_control", "Engine.retry_task", "Engine.back_to_red",
           "Engine.already_implemented")),
    Route("POST", "pause", "tasks/{slug}/pause", h_pause, ("Engine.pause_run",)),
    Route("POST", "unpause", "tasks/{slug}/unpause", h_unpause, ("Engine.unpause_run",)),
    Route("POST", "note", "tasks/{slug}/note", h_note, ("Engine.add_note",)),
    Route("POST", "retry_now", "tasks/{slug}/retry-now", h_retry_now, ("Engine.retry_limited_now",)),
    Route("GET", "chat", "runs/{slug}/chat", h_chat),
    Route("POST", "chat_send", "runs/{slug}/chat", h_chat_send, ("chat.append_chat", "chat.reply_worker")),
    Route("GET", "factory", "projects/{pid}/factory", h_factory),
    Route("GET", "factory_state", "factory", h_factory_get),
    Route("POST", "factory_pause", "factory/pause", h_factory_pause, ("factory.set_paused",)),
    Route("POST", "factory_resume", "factory/resume", h_factory_resume, ("factory.set_paused",)),
    Route("GET", "approval_list", "approvals", h_approval_list),
    Route("GET", "audit", "audit", h_audit),
    Route("GET", "events", "events", h_events),
    Route("GET", "health", "installation/health", h_health),
    Route("GET", "readiness", "projects/{pid}/readiness", h_readiness),
    Route("GET", "repositories", "projects/{pid}/repositories", h_repositories),
    Route("GET", "configuration", "projects/{pid}/configuration", h_configuration),
    Route("GET", "config_history", "projects/{pid}/configuration/history", h_config_history),
    Route("GET", "config_diff", "projects/{pid}/configuration/diff", h_config_diff),
    Route("GET", "changes", "tasks/{slug}/changes", h_changes),
    Route("GET", "changes_diff", "tasks/{slug}/changes/diff", h_changes_diff),
    Route("GET", "notifications", "notifications", h_notifications),
    Route("POST", "notification_read", "notifications/{nid}/read", h_notification_read, ()),
    Route("POST", "create_project", "projects", h_create_project),
    Route("POST", "register_project", "projects/register", h_register_project),
    Route("POST", "add_repository", "projects/{pid}/repositories", h_add_repository),
    Route("DELETE", "delete_project", "projects/{pid}", h_delete_project),
    Route("DELETE", "remove_repository", "projects/{pid}/repositories/{rid}", h_remove_repository),
    Route("GET", "providers", "providers", h_providers),
    Route("POST", "provider_test", "providers/{rid}/test", h_provider_test),
    Route("GET", "agents", "agents", h_agents),
    Route("PUT", "agents_put", "agents", h_agents_put),
    Route("GET", "fs_dirs", "fs/dirs", h_fs_dirs),
    Route("GET", "profiles", "profiles", h_profiles),
    Route("GET", "orchestrator", "orchestrator", h_orchestrator),
    Route("PUT", "orchestrator_put", "orchestrator", h_orchestrator_put),
    Route("GET", "analytics", "reports/analytics", h_analytics),
    Route("POST", "detect", "detect", h_detect),
    Route("POST", "shared_test", "shared/test", h_shared_test),
    Route("GET", "routing_suggest", "routing/suggest", h_routing_suggest),
    Route("GET", "routing_fix", "projects/{pid}/routing/fix", h_routing_fix),
    Route("GET", "config_form", "projects/{pid}/config/form", h_config_form),
    Route("POST", "config_preview", "projects/{pid}/config/preview", h_config_preview),
    Route("POST", "config_save", "projects/{pid}/config/save", h_config_save, ("manage.write_config",)),
    Route("GET", "knowledge_related", "projects/{pid}/knowledge/related", h_knowledge_related),
    Route("GET", "knowledge_status", "projects/{pid}/knowledge/status", h_knowledge_status),
    Route("GET", "knowledge_records", "projects/{pid}/knowledge/records", h_knowledge_records),
    Route("GET", "knowledge_record", "projects/{pid}/knowledge/records/{key}", h_knowledge_record),
    Route("GET", "knowledge_ci_template", "projects/{pid}/knowledge/ci-template", h_knowledge_ci_template),
    Route("POST", "knowledge_ingest", "projects/{pid}/knowledge/ingest", h_knowledge_ingest, ("kb_worker.enqueue_ingest",)),
    Route("POST", "knowledge_snapshot", "projects/{pid}/knowledge/snapshot", h_knowledge_snapshot, ("kb_worker.enqueue_snapshot",)),
    Route("POST", "knowledge_backfill_estimate", "projects/{pid}/knowledge/backfill/estimate", h_knowledge_backfill_estimate),
    Route("POST", "knowledge_backfill", "projects/{pid}/knowledge/backfill", h_knowledge_backfill, ("kb_worker.enqueue_ingest",)),
]

for _r in ROUTES:
    _r.regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", _r.template) + "$")

# Contract routes that Phase G and H build. Until then they answer 404, so this module is the only allow-list.
UNBUILT = [(m, re.compile(p)) for m, p in [
    ("PATCH", r"projects/[^/]+"),
    ("POST", r"projects/[^/]+/archive"),
    ("PATCH|PUT", r"projects/[^/]+/repositories(/.*)?"),
    ("GET|POST|PUT|PATCH|DELETE", r"projects/[^/]+/configuration(/.*)?"), ("GET|PUT", r"configuration/global"),
    ("GET", r"workflows|policies"),
    ("POST", r"tasks/[^/]+/publish"),
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
            # A notification id is checked by its own validator (400 E_VALIDATION), so `%00` or `..%2F` in it reach the handler;
            # every other parameter that decodes to a slash, a backslash or a NUL is a route that does not exist.
            if route.name != "notification_read" and any(("/" in v or "\\" in v or "\0" in v) for v in params.values()):
                raise HttpError("E_NOT_FOUND", "no such route")
            return route, params
        allowed.append(route.method)
    if any(method in verbs.split("|") and rx.fullmatch(rel) for verbs, rx in UNBUILT):
        raise HttpError("E_NOT_FOUND", "no such route")
    if allowed:
        raise HttpError("E_METHOD", f"{method} is not allowed here", headers={"Allow": ", ".join(sorted(set(allowed)))})
    raise HttpError("E_NOT_FOUND", "no such route")
