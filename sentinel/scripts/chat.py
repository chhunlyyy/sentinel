"""Chat with the orchestrator: storage, prompt construction, and background worker."""
import json
import os
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from errors import SentinelError
import machines
import run_stage
import scrub

USER_MAX = 4000
REPLY_MAX = 20000
SPEC_PROMPT_MAX = 12000
DEFAULT_TIMEOUT = 180.0

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "orchestrator_chat.txt"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_chat(run_dir):
    """Read chat.jsonl in run_dir. Deduplicates by item id keeping the last line per id, preserving insertion order."""
    path = Path(run_dir) / "chat.jsonl"
    if not path.is_file():
        return []
    items_by_id = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict) and "id" in item:
                    items_by_id[item["id"]] = item
            except Exception:
                continue
    return list(items_by_id.values())


def append_chat(run_dir, item):
    """Append a single JSON item line to chat.jsonl."""
    path = Path(run_dir) / "chat.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, separators=(",", ":")) + "\n")


STALE_AFTER = DEFAULT_TIMEOUT + 60   # a pending reply older than this was lost (server restart): it no longer blocks


def _age_seconds(at):
    try:
        return (datetime.now(timezone.utc) - datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def has_pending_reply(run_dir):
    """True if an orchestrator reply is pending and not stale (see STALE_AFTER)."""
    items = read_chat(run_dir)
    return any(it.get("status") == "pending" and _age_seconds(it.get("at")) < STALE_AFTER for it in items)


FENCE_TOKENS = ("<<<RUN_DATA_BEGIN>>>", "<<<RUN_DATA_END>>>")


def _defang(value):
    """Run data may not contain the fence markers, so it cannot close the data block early."""
    text = str(value)
    for token in FENCE_TOKENS:
        text = text.replace(token, token.replace("<<<", "<< <"))
    return text


def orchestrator_target(config, api=None):
    """(runner, model) for the orchestrator per brief:

    run_stage.orchestrator_route(config) if set, else the server orchestrator id (ctx.api.orchestrator),
    else the claude runner with no model.
    """
    orch = run_stage.orchestrator_route(config)
    if orch and orch.get("runner"):
        return orch["runner"], orch.get("model")
    if api and getattr(api, "orchestrator", None):
        return api.orchestrator, None
    return "claude", None


def build_chat_prompt(eng, slug, user_question, scrubber=None, config=None, previous_messages=None):
    """Assemble the prompt for the orchestrator runner with clear delimiters and run context."""
    run = eng._get(slug)
    state = run.get("state", "UNKNOWN")
    prev_state = run.get("previous_state") or "none"
    try:
        attention_reason = eng._state_reason(run, state) or "none"
    except Exception:
        attention_reason = "none"
    tier = run.get("tier") if run.get("tier") is not None else "none"
    request_text = run.get("request") or "(none)"

    # Spec text (first 12000 chars)
    spec_text = ""
    try:
        spec_info = eng.review(slug, "spec")
        spec_text = spec_info.get("text") or ""
    except Exception:
        try:
            artifacts = [a for a in eng.reg.rows("artifacts", run_id=run["id"], kind="spec")]
            if artifacts:
                latest = max(artifacts, key=lambda a: a.get("version", 0))
                v = latest["version"]
                art_file = eng.run_dir(slug) / "artifacts" / f"spec-v{v}.md"
                if art_file.is_file():
                    spec_text = art_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if not spec_text:
        spec_text = "(no specification text available)"
    else:
        spec_text = spec_text[:SPEC_PROMPT_MAX]

    # Task list (role, state, attempts)
    tasks = eng.reg.rows("tasks", run_id=run["id"])
    if tasks:
        t_lines = []
        for t in tasks:
            att = t.get("attempt")
            if not att:
                att = 1 + len([x for x in tasks if x["role"] == t["role"] and x["id"] < t["id"]])
            t_lines.append(f"- {t['role']}: {t['state']} (attempt {att})")
        task_list_str = "\n".join(t_lines)
    else:
        task_list_str = "(no tasks)"

    # Last 40 scrubbed log lines of latest failed or running task
    from apiserver.views import clean_log_lines
    cand = [t for t in tasks if t["state"] in ("FAILED", "RUNNING")]
    if not cand:
        cand = tasks
    task_log_str = "(no task logs)"
    if cand:
        target = cand[-1]
        log_file = eng.run_dir(slug) / "tasks" / target["id"] / "output.log"
        if log_file.is_file():
            try:
                raw_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = raw_lines[-40:]
                clean = clean_log_lines(tail, scrubber, config)
                if clean:
                    task_log_str = "\n".join(clean)
            except Exception:
                pass

    # Unread notes
    try:
        notes = eng.unread_notes(run)
    except Exception:
        notes = []
    unread_notes_str = "\n".join(f"- {n}" for n in notes) if notes else "(none)"

    # Last 10 chat messages
    if previous_messages:
        hist = [f"{m['role']}: {m['text']}" for m in previous_messages[-10:] if m.get("text")]
        chat_hist_str = "\n".join(hist) if hist else "(none)"
    else:
        chat_hist_str = "(none)"

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    values = dict(slug=slug, state=state, previous_state=prev_state, attention_reason=attention_reason, tier=tier,
                  request=request_text, spec_text=spec_text, task_list=task_list_str, task_log=task_log_str,
                  unread_notes=unread_notes_str, chat_history=chat_hist_str, user_question=user_question)
    return template.format(**{k: _defang(v) for k, v in values.items()})


def reply_worker(projects, project, slug, orch_id, runner_id, model, api=None, timeout=None):
    """Background worker that builds the prompt, executes the runner, scrubs the reply,

    stores the outcome in chat.jsonl, and emits the chat.message event.
    """
    try:
        with projects.engine(project) as eng:
            run = eng._get(slug)
            config = projects.require(project)
            scrubber = projects.scrubber(project)
            all_items = read_chat(eng.run_dir(slug))
            prev = [it for it in all_items if it["id"] != orch_id]
            user_question = prev[-1]["text"] if prev and prev[-1]["role"] == "user" else ""
            prompt = build_chat_prompt(
                eng,
                slug,
                user_question,
                scrubber=scrubber,
                config=config,
                previous_messages=prev[:-1],
            )
            runners = run_stage.all_runners(config)
            runner = runners.get(runner_id)

        if not runner:
            final_item = {
                "id": orch_id,
                "role": "orchestrator",
                "text": "",
                "at": _now(),
                "status": "failed",
                "error": f"runner {runner_id} not defined",
            }
            with projects.engine(project) as eng:
                append_chat(eng.run_dir(slug), final_item)
                with eng.reg.transaction():
                    eng.reg.add_event(
                        run["id"],
                        "chat.message",
                        machines.ORCHESTRATOR,
                        {"slug": slug, "id": orch_id, "role": "orchestrator", "status": "failed"},
                    )
            return

        # chat is read-only: never pass a runner's permission-skipping flags
        safe_runner = {**runner, "unsafe_skip_permissions": False}
        cmd, stdin_text = run_stage.build_command(safe_runner, prompt, model, resume=None, extra_dirs=[])
        env_timeout = os.environ.get("SENTINEL_CHAT_TIMEOUT")
        call_timeout = float(timeout if timeout is not None else env_timeout or getattr(api, "chat_timeout", DEFAULT_TIMEOUT))

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=tmpdir,
                    stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                out, err = proc.communicate(input=stdin_text, timeout=call_timeout)
                if proc.returncode != 0:
                    status = "failed"
                    error = (err or out or f"exit code {proc.returncode}").strip()[:500]
                    text = ""
                else:
                    raw_reply, _, _ = run_stage.parse_output(runner, out)
                    raw_reply = raw_reply[:REPLY_MAX]
                    reply_text = scrub.clean_text(scrubber, raw_reply, config)
                    status = "done"
                    error = None
                    text = reply_text
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                status = "failed"
                error = f"timeout after {int(call_timeout)}s"
                text = ""
            except Exception as e:
                status = "failed"
                error = str(e)[:500]
                text = ""

        final_item = {
            "id": orch_id,
            "role": "orchestrator",
            "text": text,
            "at": _now(),
            "status": status,
        }
        if error:
            final_item["error"] = error

        with projects.engine(project) as eng:
            append_chat(eng.run_dir(slug), final_item)
            with eng.reg.transaction():
                eng.reg.add_event(
                    run["id"],
                    "chat.message",
                    machines.ORCHESTRATOR,
                    {"slug": slug, "id": orch_id, "role": "orchestrator", "status": status},
                )
    except Exception as e:
        # Emergency catch-all to never leave pending item unhandled
        try:
            with projects.engine(project) as eng:
                run = eng._get(slug)
                final_item = {
                    "id": orch_id,
                    "role": "orchestrator",
                    "text": "",
                    "at": _now(),
                    "status": "failed",
                    "error": str(e)[:500],
                }
                append_chat(eng.run_dir(slug), final_item)
                with eng.reg.transaction():
                    eng.reg.add_event(
                        run["id"],
                        "chat.message",
                        machines.ORCHESTRATOR,
                        {"slug": slug, "id": orch_id, "role": "orchestrator", "status": "failed"},
                    )
        except Exception:
            pass
