"""Write side of the API: body checks, then one call to the engine function the CLI uses."""
import contextlib
import io
import re
import subprocess

import engine as engine_mod
from errors import SentinelError
from paths import slug_problem
from shared import Shared

RUN_TYPES = engine_mod.RUN_TYPES
PRIORITIES = ("low", "normal", "high")
SHA256 = re.compile(r"[0-9a-f]{64}")
CHANNEL = "dashboard"
HUMAN = "human"


def bad(message, field=None, **details):
    if field:
        details["field"] = field
    return SentinelError("E_VALIDATION", message, details)


def check_fields(body, allowed, required=()):
    for field in body:
        if field not in allowed:
            raise bad(f"unknown field {field}", field)
    for field in required:
        if field not in body or body[field] is None:
            raise bad(f"missing field {field}", field)


def text_field(body, field, required=True):
    value = body.get(field)
    if value is None:
        if required:
            raise bad(f"missing field {field}", field)
        return None
    if not isinstance(value, str):
        raise bad(f"{field} must be a string", field)
    return value


# ---- create a run
def git_head(path):
    if not (path / ".git").exists():
        return None
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or None


def parse_create(body, config):
    check_fields(body, ("slug", "request", "type", "repos", "priority", "tier", "ticket"), ("slug", "request", "type"))
    slug = text_field(body, "slug")
    problem = slug_problem(slug)
    if problem:
        raise bad(problem, "slug")
    request = text_field(body, "request")
    if not request.strip():
        raise bad("request must not be empty", "request")
    typ = text_field(body, "type")
    if typ not in RUN_TYPES:
        raise bad(f"type must be one of {', '.join(RUN_TYPES)}", "type", allowed=list(RUN_TYPES))
    known = [r["id"] for r in config.get("repos") or [] if isinstance(r, dict) and r.get("id")]
    repos = body.get("repos")
    if repos is None:
        repos = known
    elif not isinstance(repos, list) or not repos or not all(isinstance(r, str) for r in repos):
        raise bad("repos must be a non-empty list of repo ids", "repos")
    unknown = [r for r in repos if r not in known]
    if unknown:
        raise bad(f"unknown repo(s): {', '.join(unknown)}", "repos", known=known)
    priority = body.get("priority", "normal")
    if priority not in PRIORITIES:
        raise bad(f"priority must be one of {', '.join(PRIORITIES)}", "priority", allowed=list(PRIORITIES))
    tier = body.get("tier")
    if tier is not None and (isinstance(tier, bool) or not isinstance(tier, int) or not 1 <= tier <= 4):
        raise bad("tier must be an integer from 1 to 4", "tier")
    ticket = text_field(body, "ticket", required=False)
    if ticket and ticket.strip():
        request = f"{request}\n\nTicket: {ticket.strip()}"
    return {"slug": slug, "request": request, "type": typ, "repos": list(dict.fromkeys(repos)),
            "priority": priority, "tier": tier}


def prepare_shared(shared):
    """The checks of `sentinel run new`: a local shared folder is set up on first use, a team repo must be cloned."""
    if shared.local:
        if not shared.is_clone():
            with contextlib.redirect_stdout(io.StringIO()):  # init_local reports on the terminal of the CLI
                shared.init_local()
    elif not shared.url:
        raise SentinelError("E_PRECONDITION", "state.shared_repo is required before a run can be created")
    elif not shared.is_clone():
        raise SentinelError("E_PRECONDITION", f"the shared repo ({shared.url}) is not cloned; run `sentinel sync pull`")


def create_run(eng, project, config, body, user):
    """Engine.create_run for a run created at the dashboard: it queues for the AI tool and authorizes nothing."""
    spec = parse_create(body, config)
    repo_paths = {r["id"]: project.path / r["path"] for r in config.get("repos") or [] if isinstance(r, dict) and r.get("id")}
    baseline = {}
    for repo in spec["repos"]:
        sha = git_head(repo_paths[repo])
        if not sha:
            raise SentinelError("E_PRECONDITION", f"repo {repo} is not a git repo with a commit", {"repo": repo})
        baseline[repo] = sha
    slug = spec["slug"]
    if eng.reg.get_run(slug):
        raise SentinelError("E_PRECONDITION", f"run {slug} already exists", {"slug": slug})
    shared = Shared(project.path, config)
    prepare_shared(shared)
    try:
        shared.acquire(slug, user)
    except SystemExit as e:
        raise SentinelError("E_LOCKED", str(e.code or f"slug {slug} is locked by another run"), {"slug": slug})
    try:
        eng.create_run(slug, HUMAN, type=spec["type"], baseline=baseline, request=spec["request"],
                       priority=spec["priority"], requested_tier=spec["tier"], origin=CHANNEL)
    except BaseException:
        if not eng.reg.get_run(slug):
            shared.release(slug)
        raise
    eng.audit(user, CHANNEL, "run_created", slug)
    return slug


# ---- approvals and acceptance
def _hash_pair(body, hash_field):
    sha = text_field(body, hash_field)
    conf = text_field(body, "confirmation")
    if not SHA256.fullmatch(sha):
        raise bad(f"{hash_field} must be 64 lowercase hex characters", hash_field)
    if conf != sha[:8]:
        raise bad("confirmation must be the first 8 characters of the hash", "confirmation")
    return sha


def decide(eng, slug, body, user, git_name):
    """POST approvals: Engine.decide with actor human on the dashboard channel. Refusals before the call are audited."""
    gate = body.get("gate")
    refused = None
    try:
        check_fields(body, ("gate", "sha256", "confirmation", "decision", "comment"),
                     ("gate", "sha256", "confirmation", "decision"))
        gate = text_field(body, "gate")
        decision = text_field(body, "decision")
        comment = text_field(body, "comment", required=False)
        if gate not in engine_mod.GATES:
            raise bad(f"unknown gate {gate!r}", "gate", allowed=["specification", "gherkin"])
        if decision not in engine_mod.DECISIONS:
            raise bad(f"unknown decision {decision!r}", "decision", allowed=sorted(engine_mod.DECISIONS))
        sha = _hash_pair(body, "sha256")
    except SentinelError as err:
        if isinstance(gate, str) and gate in engine_mod.GATES and slug:
            eng.audit_refused(slug, gate, err.code, user, CHANNEL)
        raise
    return eng.decide(slug, gate, decision, HUMAN, sha256=sha, comment=comment, approver=user,
                      approver_name=git_name, channel=CHANNEL)


def accept(eng, slug, body, user, git_name):
    """POST acceptance: the Phase E acceptance function, as the dashboard channel of the human."""
    check_fields(body, ("sha256_of_report", "confirmation", "decision", "comment"),
                 ("sha256_of_report", "confirmation", "decision"))
    decision = text_field(body, "decision")
    if decision not in ("accept", "reject"):
        raise bad("decision must be accept or reject", "decision", allowed=["accept", "reject"])
    comment = text_field(body, "comment", required=False)
    if decision == "reject" and not (comment or "").strip():
        raise bad("rejecting needs a comment", "comment")
    sha = _hash_pair(body, "sha256_of_report")
    fn = getattr(eng, "accept", None)
    if fn is None:
        raise SentinelError("E_PRECONDITION", "final acceptance needs the Phase E engine functions, which are not installed")
    try:
        return fn(slug, decision, HUMAN, sha256=sha, comment=comment, approver=user, approver_name=git_name, channel=CHANNEL)
    except SentinelError as err:
        if err.code == "E_PRECONDITION" and err.details.get("acceptance") in ("rejected", "confirmed"):
            # a rejected or already confirmed run: the API reports it as a transition (Phase F contract); other refusals keep their code
            raise SentinelError("E_TRANSITION", err.message, err.details) from err
        raise


# ---- controls
CONTROL_ACTIONS = ("cancel", "resume", "retry")


def parse_control(body):
    check_fields(body, ("action", "task_id", "comment"), ("action",))
    action = text_field(body, "action")
    if action not in CONTROL_ACTIONS:
        raise bad(f"action must be one of {', '.join(CONTROL_ACTIONS)}", "action", allowed=list(CONTROL_ACTIONS))
    task_id = text_field(body, "task_id", required=False)
    comment = text_field(body, "comment", required=False)
    comment = comment.strip() if comment and comment.strip() else None
    if action == "resume" and not comment:
        raise bad("resuming needs a comment", "comment")
    if action == "retry" and not task_id:
        raise bad("retry needs a task_id", "task_id")
    if action == "resume" and task_id:
        raise bad("resume applies to the run, not to a task", "task_id")
    return action, task_id, comment


def control(eng, slug, body, user):
    """POST control: the run cancel, R20 resume, task cancel and task retry functions."""
    action, task_id, comment = parse_control(body)
    if action == "cancel" and task_id:
        return eng.cancel_task_control(slug, task_id, comment, user=user, channel=CHANNEL)
    if action == "cancel":
        return eng.cancel_run(slug, comment, user=user, channel=CHANNEL)
    if action == "resume":
        return eng.resume_run(slug, comment, user=user, channel=CHANNEL)
    return eng.retry_task(slug, task_id, user=user, channel=CHANNEL)
