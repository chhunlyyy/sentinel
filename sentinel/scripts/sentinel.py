#!/usr/bin/env python3
import argparse
import difflib
import getpass
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CONFIG_NAME = "sentinel.config.yaml"

from engine import TIER_STAGES  # noqa: E402
from errors import SentinelError  # noqa: E402
import initws  # noqa: E402
from initws import detect_profile, load_profile_driver, update_gitignore  # noqa: E402,F401
from registry import legacy_statuses  # noqa: E402


def load_json(name):
    return json.loads((ROOT / name).read_text())


def find_config(start):
    current = Path(start).resolve()
    for folder in [current, *current.parents]:
        candidate = folder / CONFIG_NAME
        if candidate.exists():
            return candidate
    sys.exit(f"{CONFIG_NAME} not found; run `sentinel init`")


def load_config(start):
    path = find_config(start)
    return path, yaml.safe_load(path.read_text())


def ask(prompt, default=None, choices=None):
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"{prompt}{suffix}: ").strip() or (default or "")
        if answer and (not choices or answer in choices):
            return answer
        print(f"choose one of: {', '.join(choices)}" if choices else "required")


def build_repos(shape, workspace, interactive, overrides):
    shapes = load_json("templates/shapes.json")
    entries = shapes[shape]["repos"]
    if shape == "custom":
        count = int(overrides.get("count") or ask("how many repos", "2"))
        entries = [{"id": ask(f"repo {i + 1} id"), "role": ask(f"repo {i + 1} role")} for i in range(count)]
    repos = []
    for entry in entries:
        default_path = f"./{entry['id']}"
        path = overrides.get(f"{entry['id']}.path") or (ask(f"path of {entry['id']}", default_path) if interactive else default_path)
        detected = detect_profile((workspace / path).resolve())
        profile = overrides.get(f"{entry['id']}.profile") or (ask(f"stack profile of {entry['id']}", detected) if interactive else detected)
        repos.append({"id": entry["id"], "path": path, "role": entry["role"], "profile": profile})
    return repos


SHARED_HELP = """
Sentinel keeps what your team shares (project rules, specs, the regression suite) in a private
git repository that your team owns. Create an empty private repository on your git server
(GitHub, Gitea, GitLab, ...) and paste its clone URL. For a quick local trial you can use a
bare repo on disk: git init --bare ~/sentinel-shared.git
"""


def ask_shared_url():
    from shared import looks_like_git_url
    print(SHARED_HELP)
    while True:
        url = input("shared repo URL (leave empty for local-only, no shared repo): ").strip()
        if not url:
            return ""
        if looks_like_git_url(url):
            return url
        print("that does not look like a git URL (https://..., git@host:..., ssh://..., or a path)")


def connect_shared(config_path, config):
    from shared import Shared, verify_remote
    shared = Shared(config_path.parent, config)
    if shared.local:
        shared.init_local()
        return True
    ok, detail, _ = verify_remote(shared.url)
    if not ok:
        print(f"warning: could not reach {shared.url}: {detail}")
        print("the config was saved; get access to the repo, then run `sentinel sync pull`")
        return False
    try:
        shared.pull()
    except SystemExit as failure:
        print(f"warning: could not set up the shared repo: {failure}")
        return False
    return True


def require_shared(config_path, config):
    from shared import Shared
    shared = Shared(config_path.parent, config)
    if shared.local:
        if not shared.is_clone():
            shared.init_local()
        return
    if not shared.url:
        sys.exit("state.shared_repo is required. Ask your team for the URL of its private shared repo and run `sentinel shared set <url>`.")
    if not shared.is_clone():
        sys.exit(f"the shared repo ({shared.url}) is not cloned yet. Run `sentinel sync pull` first.")


def cmd_shared_ci(args):
    from shared import Shared
    config_path, config = load_config(args.dir)
    require_shared(config_path, config)
    target = Shared(config_path.parent, config).write_ci()
    print(f"wrote {target}")
    print("commit and push it from .sentinel/shared when you want CI. On GitHub, a personal access token needs the `workflow` scope (classic) or the Workflows permission (fine-grained) to push files under .github/workflows.")


def cmd_shared_set(args):
    from shared import looks_like_git_url
    import re as _re
    config_path, config = load_config(args.dir)
    if not looks_like_git_url(args.url):
        sys.exit("that does not look like a git URL (https://..., git@host:..., ssh://..., or a path)")
    text = config_path.read_text()
    if _re.search(r"^\s*shared_repo:", text, _re.M):
        text = _re.sub(r"^(\s*shared_repo:\s*).*$", lambda m: f'{m.group(1)}"{args.url}"', text, count=1, flags=_re.M)
    else:
        config.setdefault("state", {})["shared_repo"] = args.url
        text = yaml.safe_dump(config, sort_keys=False)
    if _re.search(r"^\s*shared_mode:", text, _re.M):
        text = _re.sub(r"^(\s*shared_mode:\s*).*$", lambda m: f"{m.group(1)}git", text, count=1, flags=_re.M)
    config_path.write_text(text)
    config_path, config = load_config(args.dir)
    connect_shared(config_path, config)
    print(f"state.shared_repo set to {args.url}")


def cmd_init(args):
    workspace = Path(args.dir).resolve()
    target = workspace / CONFIG_NAME
    if target.exists() and not args.force:
        sys.exit(f"{CONFIG_NAME} already exists; pass --force to overwrite")
    shapes = load_json("templates/shapes.json")
    interactive = not args.non_interactive
    shape = args.shape or ask("project shape (single, fullstack, fullstack-mobile, custom)", "fullstack", list(shapes))
    from shared import looks_like_git_url
    shared_url = (args.shared_repo or "").strip()
    local_only = args.local_only
    if not shared_url and not local_only and interactive:
        shared_url = ask_shared_url()
        local_only = not shared_url
    if not shared_url and not local_only:
        sys.exit("a shared repo is required: pass --shared-repo <url> (an empty private git repository your team owns), or --local-only")
    if shared_url and local_only:
        sys.exit("pass either --shared-repo or --local-only, not both")
    if shared_url and not looks_like_git_url(shared_url):
        sys.exit(f"--shared-repo does not look like a git URL: {shared_url}")
    overrides = dict(item.split("=", 1) for item in (args.set or []))
    repos = build_repos(shape, workspace, interactive, overrides)
    config = initws.build_config(shape, repos, shared_url, local_only)
    initws.write_workspace(workspace, config)
    print(f"wrote {target}")
    connected = connect_shared(target, config)
    print("next: `sentinel doctor`" if connected else "next: fix access to the shared repo, `sentinel sync pull`, then `sentinel doctor`")
    print("then install the Sentinel skills into your AI tool: npx skills@latest add chhunlyyy/sentinel -a <agent>   (claude-code, antigravity-cli, codex, cursor, opencode, devin, windsurf, amp, pi, ...; leave -a off to choose)")


def cmd_routing(args):
    from run_stage import all_runners, find_route, single_model
    import render_stage
    config_path, config = load_config(args.dir)
    runners = all_runners(config)
    rows = []
    for stage_file in sorted((ROOT / "core" / "stages").glob("*.md")):
        stage = stage_file.stem
        front = yaml.safe_load(render_stage.FRONT.match(stage_file.read_text()).group(1))
        targets = [r["id"] for r in config["repos"]] if front.get("per_repo") else [None]
        for repo in targets:
            route = find_route(config, stage, repo)
            if args.stage and args.stage != stage:
                continue
            if args.repo and repo and args.repo != repo:
                continue
            row = {"stage": stage, "repo": repo, "mode": "this session", "runner": None, "model": None, "installed": True}
            if route:
                runner = runners.get(route["runner"], {})
                row.update(mode="headless", runner=route["runner"], model=None if single_model(config) else route.get("model"), installed=bool(runner) and bool(shutil.which(runner["command"].split()[0])))
            rows.append(row)
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    for row in rows:
        name = f"{row['repo']}-{row['stage']}" if row["repo"] else row["stage"]
        detail = f"{row['runner']}" + (f" ({row['model']})" if row["model"] else "") + ("" if row["installed"] else " NOT INSTALLED") if row["runner"] else "your current AI tool, in a subagent"
        print(f"{name:<24}{row['mode']:<14}{detail}")


def model_problems(config, stage, route, runner, live):
    from run_stage import single_model
    model = route.get("model")
    if not model or single_model(config) or not runner.get("model_flag"):
        return []
    if model.startswith("-") or " " in model.strip():
        return [f"routing {stage}: model {model!r} must be the model name only, without the flag (for example `sonnet`, not `--model sonnet`)"]
    if not live or not shutil.which(runner["command"].split()[0]):
        return []
    known = []
    if route["runner"] == "agy":
        listing = subprocess.run(["agy", "models"], capture_output=True, text=True, timeout=60).stdout
        known = [line.split("\t")[0] for line in listing.splitlines() if "\t" in line]
        if known and model not in known:
            close = difflib.get_close_matches(model, known, n=3, cutoff=0.4)
            return [f"routing {stage}: agy does not know model {model!r}; " + (f"did you mean {', '.join(close)}?" if close else "") + f" known: {', '.join(known)}"]
        return []
    command = shlex.split(runner["command"]) + [runner["model_flag"], model]
    command += ([runner["prompt_flag"]] if runner.get("prompt_flag") else []) + ["Reply with ok."]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return [f"routing {stage}: model check for {model!r} timed out"]
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["failed"]
        return [f"routing {stage}: {route['runner']} rejected model {model!r}: {tail[0]}"]
    return []


def fix_routing(config_path, config):
    """`sentinel doctor --fix-routing`: print the roles that block engine runs with a suggested runner and model for each and the
    change to sentinel.config.yaml; write it after a typed yes (human, interactive terminal only)."""
    import copy
    import difflib
    import factory
    from apiserver import manage
    fix = factory.routing_fix(config)
    if not fix["applies"] or not fix["problems"]:
        print("routing: nothing to fix" if fix["applies"] else "routing: the factory driver is not `engine`, nothing to fix")
        return
    print("These roles cannot run in an engine-driven run:")
    for row in fix["problems"]:
        sug = row["suggested"]
        print(f"  {row['role']:<14}{row['text']}\n  {'':<14}suggested: {sug['runner']}" + (f" ({sug['model']})" if sug["model"] else ""))
    new = copy.deepcopy(config)
    for change in fix["changes"]:
        manage._set_path(new, change["path"], change["value"])
    import jsonschema
    validator = jsonschema.Draft202012Validator(json.loads((ROOT / "core" / "schema" / "config.schema.json").read_text()))
    known = {e.message for e in validator.iter_errors(config)}   # problems the file already had are not ours
    err = next((e for e in validator.iter_errors(new) if e.message not in known), None)
    if err:
        raise SentinelError("E_VALIDATION", f"the suggested routing is not valid: {err.message}")
    old_text, new_text = config_path.read_text(), manage.dump(new)
    print("\nChange to sentinel.config.yaml:")
    sys.stdout.writelines(difflib.unified_diff(old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                                               fromfile="sentinel.config.yaml", tofile="sentinel.config.yaml (new)"))
    err = gate_error("doctor --fix-routing")
    if err:
        raise err
    try:
        answer = input("\nType yes to write this change (comments in the file are not kept): ")
    except (EOFError, KeyboardInterrupt):
        print("\ninput closed; nothing written", file=sys.stderr)
        sys.exit(1)
    if answer.strip().lower() != "yes":
        print("nothing written")
        sys.exit(1)
    user, _ = human_identity()
    engine = open_registry(config_path, config)
    try:
        manage.atomic_write(config_path, new_text)
        with engine.reg.transaction():
            engine.reg.store_config_version("workspace", new_text, author=user, channel="tty", comment="Fix routing")
            engine.reg.add_audit(user, "tty", "config_changed", config_path.parent.name, reason="Fix routing")
    finally:
        engine.close()
    print(f"written: {len(fix['problems'])} roles now route to a CLI runner (stored in the config history)")


def cmd_doctor(args):
    import health
    config_path, config = load_config(args.dir)
    if args.fix_routing:
        fix_routing(config_path, config)
        return
    found, notes = health.doctor_problems(config_path, config, state_dir_of(config_path, config), args.check_models, model_problems)
    for note in notes:
        print(note)
    problems = [text for _, text in found]
    if problems:
        print("\n".join(f"- {p}" for p in problems))
        sys.exit(1)
    print("doctor: ok")


def cmd_sync_adapters(args):
    config_path, config = load_config(args.dir)
    workspace = config_path.parent
    if args.tool != "claude":
        subprocess.run([sys.executable, str(ROOT / "adapters/agents/sync.py"), "--config", str(config_path), "--tool", args.tool], check=True)
        update_gitignore(workspace, config["state"]["dir"])
        return
    out = Path(args.out) if args.out else workspace / ".claude" / "agents"
    subprocess.run(
        [sys.executable, str(ROOT / "adapters/claude/sync.py"), "--config", str(config_path), "--out", str(out), "--workspace", str(workspace)],
        check=True,
    )
    from paths import skills_dir
    installed = []
    for skill in sorted(p for p in skills_dir().iterdir() if (p / "SKILL.md").exists()):
        shutil.copytree(skill, workspace / ".claude" / "skills" / skill.name, dirs_exist_ok=True)
        installed.append(skill.name)
    deny_human_commands(workspace)
    print(f"agents written to {out}; skills written to .claude/skills: {', '.join(installed)}")


_HUMAN_SUBCOMMANDS = ["approve", "accept", "resolve", "run export", "run import", "dashboard", "notifications read", "backup restore",
                      "audit export", "pause", "unpause", "note", "service pause", "service resume", "doctor --fix-routing"]
HUMAN_ONLY_COMMANDS = (
    [f"Bash(sentinel {c}:*)" for c in _HUMAN_SUBCOMMANDS]
    # the global --dir option in front of the command, as `--dir X` and as `--dir=X` (an abbreviation such as `--di X` cannot be
    # matched by a pattern: the TTY check of each command is the real guard)
    + [f"Bash(sentinel --dir * {c} *)" for c in _HUMAN_SUBCOMMANDS]
    + [f"Bash(sentinel --dir=* {c} *)" for c in _HUMAN_SUBCOMMANDS]
    + ["Read(~/.config/sentinel/**)", "Read(//**/.config/sentinel/server.json)", "Bash(cat ~/.config/sentinel/*)"])


def _config_dir_rules():
    """Deny rules for the folder `sentinel dashboard` really uses (it follows XDG_CONFIG_HOME)."""
    from apiserver import userdir
    folder = str(userdir.config_dir())
    default = str(Path.home() / ".config" / "sentinel")
    if folder == default:
        return []
    return [f"Read({folder}/**)", f"Bash(cat {folder}/*)"]


def deny_human_commands(workspace):
    """Merge deny rules for the human-only commands into .claude/settings.json (keeps every other setting).

    The rules are advisory (other spellings of the command can slip past a pattern); the TTY check in
    `sentinel approve` is the real control. A file with an unexpected shape is left untouched.
    """
    path = workspace / ".claude" / "settings.json"
    try:
        settings = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        sys.exit(f"{path} is not valid JSON; fix it and run sync-adapters again")
    if not isinstance(settings, dict):
        sys.exit(f"{path} must hold a JSON object, not {type(settings).__name__}; fix it and run sync-adapters again")
    perms = settings.setdefault("permissions", {})
    if not isinstance(perms, dict):
        sys.exit(f"{path}: \"permissions\" must be an object; fix it and run sync-adapters again")
    deny = perms.setdefault("deny", [])
    if not isinstance(deny, list):
        sys.exit(f"{path}: \"permissions.deny\" must be a list; fix it and run sync-adapters again")
    for rule in HUMAN_ONLY_COMMANDS + _config_dir_rules():
        if rule not in deny:
            deny.append(rule)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")


def state_dir_of(config_path, config):
    return config_path.parent / (config.get("state") or {}).get("dir", ".sentinel")


def run_dir(config_path, config, slug):
    from paths import valid_slug
    valid_slug(slug)
    return state_dir_of(config_path, config) / "runs" / slug


def head_sha(path):
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() or None


def baseline_of(config_path, config, only=None):
    return {r["id"]: head_sha(config_path.parent / r["path"]) for r in config["repos"] if not only or r["id"] in only}


def claim_run(config_path, config, slug, adhoc):
    """Validate the slug, refuse a duplicate, take the slug lock (not for adhoc). Returns the run directory."""
    directory = run_dir(config_path, config, slug)
    if (directory / "state.json").exists():
        sys.exit(f"run {slug} already exists; use `sentinel resume {slug}`")
    if not adhoc:
        require_shared(config_path, config)
        from shared import Shared
        Shared(config_path.parent, config).acquire(slug, getpass.getuser())
    return directory


def open_registry(config_path, config):
    """Create or migrate the registry and index 0.1 runs; return the engine that owns it."""
    from engine import Engine
    return Engine(state_dir_of(config_path, config), config_path.parent, config)


def cmd_run_new(args):
    config_path, config = load_config(args.dir)
    legacy = args.legacy or bool(args.tier) or args.adhoc
    directory = claim_run(config_path, config, args.slug, args.adhoc) if legacy else None
    if not legacy:
        return new_v2_run(args, config_path, config)
    if not args.adhoc and not args.tier:
        sys.exit("--tier is required unless --adhoc")
    tier = args.tier or 1
    directory.mkdir(parents=True, exist_ok=True)
    state = {
        "slug": args.slug,
        "tier": tier,
        "initial_tier": tier,
        "adhoc": bool(args.adhoc),
        "stages": TIER_STAGES[tier],
        "completed": [],
        "sessions": {},
        "rounds": {"review": 0, "qa": 0, "release_check": 0},
        "baseline": baseline_of(config_path, config),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (directory / "state.json").write_text(json.dumps(state, indent=2))
    open_registry(config_path, config).close()
    print(json.dumps(state, indent=2))


def new_v2_run(args, config_path, config):
    from engine import RUN_TYPES
    if args.type is not None and args.type not in RUN_TYPES:
        raise SentinelError("E_VALIDATION", f"--type must be one of {', '.join(RUN_TYPES)}")
    run_dir(config_path, config, args.slug)
    only = [r for r in (args.repos or "").split(",") if r]
    unknown = [r for r in only if r not in {c["id"] for c in config["repos"]}]
    if unknown:
        raise SentinelError("E_VALIDATION", f"unknown repo(s): {', '.join(unknown)}")
    driver, request = getattr(args, "driver", "cli"), (getattr(args, "request", None) or "").strip() or None
    if driver == "engine" and not request:
        raise SentinelError("E_VALIDATION", "--driver engine needs --request: the engine's triage agent reads the request text")
    engine = open_registry(config_path, config)
    try:
        if engine.reg.get_run(args.slug):
            sys.exit(f"run {args.slug} already exists; use `sentinel resume {args.slug}`")
        claim_run(config_path, config, args.slug, False)
        try:
            engine.create_run(args.slug, "orchestrator", type=args.type, baseline=baseline_of(config_path, config, only),
                              request=request, driver=driver)
        except BaseException:
            if not engine.reg.get_run(args.slug):  # row not committed: nothing owns the lock
                from shared import Shared
                Shared(config_path.parent, config).release(args.slug)
            raise
        print((run_dir(config_path, config, args.slug) / "state.json").read_text())
    finally:
        engine.close()


def cmd_run_control(args):
    """pause | unpause | note: a person's factory controls. Refused inside a task process and without a terminal; audited."""
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        slug = check_slug(args.slug)
        user, _ = human_identity()
        err = gate_error(args.command)
        if err:
            engine.audit(user, "cli", f"{args.command}_refused", slug, reason=err.code)
            raise err
        if args.command == "note":
            engine.add_note(slug, args.text, user=user, channel="cli")
            print(f"note stored for the next agent task of {slug}")
        elif args.command == "pause":
            engine.pause_run(slug, args.comment, user=user, channel="cli")
            print(f"run {slug} paused: nothing new starts; running tasks finish")
        else:
            engine.unpause_run(slug, args.comment, user=user, channel="cli")
            print(f"run {slug} unpaused")
    finally:
        engine.close()


def cmd_triage(args):
    config_path, config = load_config(args.dir)
    factors = {}
    for item in (args.factors or "").split(","):
        if item.strip():
            key, sep, value = item.partition("=")
            if not sep:
                raise SentinelError("E_VALIDATION", f"factor {item!r} must look like key=value")
            factors[key.strip()] = value.strip()
    engine = open_registry(config_path, config)
    try:
        engine.triage(args.slug, factors, "orchestrator", requested=args.tier)
        print((run_dir(config_path, config, args.slug) / "state.json").read_text())
    finally:
        engine.close()


def read_state(config_path, config, slug):
    path = run_dir(config_path, config, slug) / "state.json"
    if not path.exists():
        sys.exit(f"no run named {slug}")
    return path, json.loads(path.read_text())


def refuse_if_v2(config_path, config, slug, command):
    engine = open_registry(config_path, config)
    try:
        if engine.is_v2(slug):
            raise SentinelError("E_TRANSITION", f"`{command}` only works on 0.1 runs; run {slug} is a version 2 run",
                                {"slug": slug})
    finally:
        engine.close()


def cmd_run_update(args):
    config_path, config = load_config(args.dir)
    refuse_if_v2(config_path, config, args.slug, "run update")
    path, state = read_state(config_path, config, args.slug)
    if args.stage and args.status == "done" and args.stage not in state["completed"]:
        state["completed"].append(args.stage)
    if args.session:
        key, _, value = args.session.partition("=")
        state["sessions"][key] = value
    if args.round:
        key, _, value = args.round.partition("=")
        state["rounds"][key] = int(value)
    if args.tier:
        if args.tier < state["tier"]:
            sys.exit("tier can only be raised after a run starts")
        state["tier"] = args.tier
        pending = [s for s in TIER_STAGES[args.tier] if s not in state["completed"]]
        state["stages"] = state["completed"] + pending
    path.write_text(json.dumps(state, indent=2))
    print(json.dumps(state, indent=2))


def cmd_resume(args):
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        if engine.is_v2(args.slug):
            raise SentinelError("E_TRANSITION", "version 2 runs are driven by the engine (`sentinel triage`, `sentinel next`, `sentinel task run`)",
                                {"slug": args.slug})
    finally:
        engine.close()
    _, state = read_state(config_path, config, args.slug)
    limits = config.get("limits") or {}
    capped = [
        name for name, cap in (("review", limits.get("review_rounds", 2)), ("qa", limits.get("qa_rounds", 3)), ("release_check", limits.get("release_check_rounds", 3)))
        if state["rounds"].get(name, 0) >= cap
    ]
    pending = [s for s in state["stages"] if s not in state["completed"]]
    print(json.dumps({"slug": state["slug"], "tier": state["tier"], "next": pending[0] if pending else None, "pending": pending, "sessions": state["sessions"], "rounds": state["rounds"], "capped": capped}, indent=2))


def cmd_scrub(args):
    sys.path.insert(0, str(ROOT / "scripts"))
    import scrub
    config_path, config = load_config(args.dir)
    workspace = config_path.parent
    state_dir = state_dir_of(config_path, config)
    scrubber = scrub.Scrubber(workspace, scrub.env_values(workspace))
    if args.check:
        targets = [state_dir / "shared"]
        problems = scrub.check_paths([t for t in targets if t.exists()], scrubber)
        for path, found in problems.items():
            print(f"{path}: {', '.join(found)}")
        sys.exit(1 if problems else 0)
    targets = [state_dir / "shared"] if args.shared else [state_dir / "runs", state_dir / "cache"]
    changed = scrub.scrub_paths([t for t in targets if t.exists()], scrubber)
    print(f"scrubbed {len(changed)} file(s)")


def is_tty():
    """A human at an interactive terminal: both stdin and stdout are a tty."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def human_identity():
    """(OS user, git name or None) of whoever runs the command."""
    from apiserver.osuser import approver_name_env, os_user
    user = os_user()
    name = approver_name_env()
    if name is None:
        try:
            out = subprocess.run(["git", "var", "GIT_AUTHOR_IDENT"], capture_output=True, text=True, timeout=10).stdout
            name = out.rsplit(" <", 1)[0].strip() or None if " <" in out else None
        except (OSError, subprocess.SubprocessError):
            pass
    return user, name


def refuse_without_tty(what):
    return SentinelError("E_NOT_TTY", f"{what} needs a human at an interactive terminal (stdin and stdout must be a tty)")


def cmd_run_finish(args):
    from shared import Shared
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        if engine.is_v2(args.slug):
            if not is_tty():
                engine.audit(human_identity()[0], "cli", "finish_refused", args.slug, reason="E_NOT_TTY")
                raise refuse_without_tty("`run finish` on a version 2 run")
            engine.finish(args.slug, args.outcome, "human")
            print(f"run {args.slug} {args.outcome}")
            return
        path, state = read_state(config_path, config, args.slug)
        state["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        state["outcome"] = args.outcome
        path.write_text(json.dumps(state, indent=2))
        if engine.reg.get_run(args.slug):
            execution, acceptance = legacy_statuses(args.outcome)
            engine.reg.update_run(args.slug, execution_status=execution, acceptance_status=acceptance)
    finally:
        engine.close()
    if state.get("adhoc"):
        print(f"run {args.slug} {args.outcome}")
        return
    Shared(config_path.parent, config).release(args.slug)
    print(f"run {args.slug} {args.outcome}; lock released")


def print_review(info, slug):
    print(f"{info['gate']} of {slug}: version {info['version']}, approval {info['approval_state']}, run {info['run_state']}")
    print(f"sha256: {info['sha256']}")
    print()
    if info["gate"] == "specification":
        print(info["text"].rstrip("\n"))
    else:
        for f in info["files"]:
            print(f"== {f['path']}")
        print()
        print("scenarios:")
        for sc in info["scenarios"]:
            print(f"  {sc['path']}:{sc['line']}  {sc['name']}  " + " ".join("@" + t for t in sc["tags"]))
        cov = info.get("coverage") or {}
        print()
        print("coverage:")
        for row in cov.get("rows", []):
            extra = f" ({row['reason']})" if row.get("reason") else ""
            print(f"  {row['category']:<18} {row['status']}{extra}")
        print(cov.get("summary", ""))
    print()
    print("validation errors:" + (" none" if not info["errors"] else ""))
    for e in info["errors"]:
        print(f"  - {e}")
    print("validation warnings:" + (" none" if not info["warnings"] else ""))
    for w in info["warnings"]:
        print(f"  - {w}")
    print()
    if info["diff"] is None:
        print("no previous reviewed version")
    else:
        print(f"diff from version {info['previous_version']} to version {info['version']}:")
        print(info["diff"].rstrip("\n") or "(no changes)")


def cmd_review(args):
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        info = engine.review(args.slug, args.gate)
        print_review(info, args.slug)
    finally:
        engine.close()


def cmd_approve(args):
    config_path, config = load_config(args.dir)
    gate = args.gate
    if not gate:
        sys.exit("usage: sentinel approve <slug> spec|gherkin [--request-changes|--reject] [-m comment]")
    if args.request_changes and args.reject:
        sys.exit("usage: choose one of --request-changes, --reject")
    decision = "changes" if args.request_changes else "reject" if args.reject else "approve"
    user, git_name = human_identity()
    engine = open_registry(config_path, config)
    try:
        try:
            if not is_tty():
                raise refuse_without_tty("`sentinel approve`")
            info = engine.pending_approval(args.slug, gate, decision, args.comment)
        except SentinelError as err:
            engine.audit_refused(args.slug, gate, err.code, user, "tty" if is_tty() else "cli")
            raise
        print(f"{info['gate']} of {args.slug}: version {info['version']}, decision: {decision}")
        print(f"sha256: {info['sha256']}")
        try:
            typed = input("Type the first 8 characters of the sha256 to confirm: ")
        except (EOFError, KeyboardInterrupt):
            print("\ninput closed; nothing stored", file=sys.stderr)
            sys.exit(1)
        run = engine.decide(args.slug, gate, decision, "human", prefix=typed, comment=args.comment,
                            approver=user, approver_name=git_name, channel="tty")
        print(f"{info['gate']} version {info['version']} {decision}; run {args.slug} is {run['state']}")
    finally:
        engine.close()



def check_slug(slug):
    from paths import slug_problem
    problem = slug_problem(slug)
    if problem:
        raise SentinelError("E_VALIDATION", problem)
    return slug


def print_step(step):
    """`sentinel next` for a person."""
    kind = step["kind"]
    if kind == "human":
        print(f"Human action: {step['reason']}")
        for command in step.get("commands") or []:
            print(f"  {command}")
        if step.get("fix"):
            print(f"  fix: {step['fix']}")
    elif kind == "task":
        print(f"Task {step['task']} ({step['role']}, {step['adapter']}): {step['label']}")
        print(f"  {step['command']}")
    elif kind == "orchestrator":
        print(f"Orchestrator: {step['action']}")
        if step.get("command"):
            print(f"  {step['command']}")
    elif kind == "wait":
        print(f"Wait: {step['reason']}" + (f" ({', '.join(step['tasks'])})" if step.get("tasks") else ""))
        if step.get("command"):
            print(f"  {step['command']}")
    else:
        print(f"Done: execution {step['execution']}, acceptance {step['acceptance']}")


def cmd_next(args):
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        step = engine.next_step(check_slug(args.slug))
        code = step.pop("exit")
        if args.json:
            print(json.dumps(step, indent=2))
        else:
            print_step(step)
        sys.exit(code)
    finally:
        engine.close()


def cmd_verify(args):
    """Run one verification round (engine only; the orchestrator calls it when `next` says so)."""
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        res = engine.verify(check_slug(args.slug), caller_task=os.environ.get("SENTINEL_TASK_ID"))
        for row in res["rows"]:
            word = {"pass": "pass", "fail": "fail"}.get(row["verdict"], row["verdict"])
            name = f" {row['name']}" if row.get("name") else ""
            print(f"{row['repo']} {row['kind']}{name}: {word}")
        if res.get("round") is None:
            print(f"VERIFICATION STOPPED: {res.get('reason')}")
        elif res["passed"]:
            print(f"VERIFICATION PASSED (round {res['round']})")
        else:
            print(f"VERIFICATION FAILED (round {res['round']}): {res.get('reason') or 'fix tasks queued: ' + ', '.join(res['fix_tasks'])}")
        sys.exit(res["exit"])
    finally:
        engine.close()


def gate_error(what, need_tty=True):
    """The refusal of a human decision command: E_ACTOR inside a task process, E_NOT_TTY without a terminal (when
    `need_tty`), else None."""
    task = os.environ.get("SENTINEL_TASK_ID")
    if task:
        return SentinelError("E_ACTOR", f"a task process may not run `sentinel {what}` (called from task {task})",
                             {"task": task, "command": what})
    if need_tty and not is_tty():
        return refuse_without_tty(f"`sentinel {what}`")
    return None


def human_gate(engine, slug, what, target=None):
    """A human decision command: refused inside a task process (E_ACTOR) and without a terminal (E_NOT_TTY); refusals are
    audited against the run, or against `target` when the command names no run yet (an import)."""
    user, git_name = human_identity()
    err = gate_error(what)
    if err:
        if target or engine.is_v2(slug):
            engine.audit(user, "tty" if is_tty() else "cli", f"{what.replace(' ', '_')}_refused" if what != "accept" else "acceptance_refused",
                         target or slug, reason=err.code)
        raise err
    return user, git_name


def audited_gate(args, what, action, target, need_tty=False):
    """The gate of `audit export`, `backup` and `backup restore` (no run to audit against): a refusal writes one
    `<action>_refused` row to the workspace registry, when there is one, and is raised. R1: the task-process check reads
    an environment variable, so a same-user process that clears it is not stopped (docs/security.md)."""
    err = gate_error(what, need_tty)
    if not err:
        return
    try:
        config_path, config = load_config(args.dir)
        if (state_dir_of(config_path, config) / "sentinel.db").is_file():
            reg = open_audit_registry(config_path, config)
            try:
                with reg.transaction():
                    reg.add_audit(human_identity()[0], "tty" if is_tty() else "cli", f"{action}_refused", str(target),
                                  reason=err.code)
            finally:
                reg.close()
    except Exception:  # the refusal itself must still reach the caller
        pass
    raise err


def cmd_accept(args):
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        slug = check_slug(args.slug)
        user, git_name = human_gate(engine, slug, "accept")
        decision = "reject" if args.reject else "accept"
        if args.reject and not (args.comment or "").strip():
            raise SentinelError("E_VALIDATION", "rejecting needs a comment: -m <comment>")
        try:
            info = engine.pending_acceptance(slug)
        except SentinelError as err:
            engine.audit(user, "tty", "acceptance_refused", slug, reason=err.code)
            raise
        print(f"Acceptance of {slug}: run {info['state']}, computed acceptance {info['acceptance']}, human decision: {info['human']}")
        print(f"report sha256: {info['sha256']}")
        for reason in info["reasons"]:
            print(f"  - {reason}")
        for dep in info["added_dependencies"]:
            print(f"  new dependency: {dep}")
        print(f"decision: {decision}")
        try:
            typed = input("Type the first 8 characters of the report sha256 to confirm: ")
        except (EOFError, KeyboardInterrupt):
            print("\ninput closed; nothing stored", file=sys.stderr)
            sys.exit(1)
        engine.accept(slug, decision, "human", prefix=typed, comment=args.comment, approver=user, approver_name=git_name, channel="tty")
        print(f"run {slug}: {decision} recorded")
    finally:
        engine.close()


def cmd_report(args):
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        slug = check_slug(args.slug)
        if not engine.is_v2(slug):
            if not engine.reg.get_run(slug):
                raise SentinelError("E_NOT_FOUND", f"no run named {slug}", {"slug": slug})
            raise SentinelError("E_TRANSITION", f"run {slug} is a 0.1 run; `sentinel report` only works on version 2 runs", {"slug": slug})
        engine.load_run(slug)
        res = engine.write_report(slug)
        if args.json:
            print(json.dumps(res["report"], indent=2))
        else:
            print(f"report of {slug}: sha256 {res['sha256']}")
        print(res["json"])
        print(res["md"])
    finally:
        engine.close()


def cmd_resolve(args):
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        slug = check_slug(args.slug)
        user, _ = human_gate(engine, slug, "resolve")
        if args.retry_now:
            ids = engine.retry_limited_now(slug)
            engine.audit(user, "tty", "retry_limit_now", slug, reason=", ".join(ids) or "no task waits for a usage limit")
            print(f"{len(ids)} task(s) of run {slug} may start now: {', '.join(ids)}" if ids else f"no task of run {slug} waits for a usage limit")
            return
        typed = None
        if args.refresh_config:
            info = engine.refresh_config_preview(slug, comment=args.comment)
            print(f"sentinel.config.yaml replaces the config snapshot of run {slug}; keys that change ({len(info['changed_keys'])}):")
            for line in info["diff"] or ["(none)"]:
                print(f"  {line}")
            print(f"new config sha256: {info['new_sha256']}")
            try:
                typed = input("Type the first 8 characters of the new config sha256 to confirm: ")
            except (EOFError, KeyboardInterrupt):
                print("\ninput closed; nothing stored", file=sys.stderr)
                sys.exit(1)
        run = engine.resolve(slug, user=user, channel="tty", comment=args.comment, waive=args.waive, approve_file=args.approve_file,
                             approve_clone=args.approve_clone, approve_security=args.approve_security, resume=not args.no_resume,
                             refresh_config=args.refresh_config, config_sha_prefix=typed)
        print(f"run {slug} is {run['state']}")
    finally:
        engine.close()


def cmd_run_export(args):
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        slug = check_slug(args.slug)
        user, _ = human_gate(engine, slug, "run export")
        if not engine.is_v2(slug):
            if not engine.reg.get_run(slug):
                raise SentinelError("E_NOT_FOUND", f"no run named {slug}", {"slug": slug})
            raise SentinelError("E_TRANSITION", f"run {slug} is a 0.1 run; only version 2 runs are exported", {"slug": slug})
        if not args.yes and input(f"Export run {slug} as a scrubbed bundle? [y/N] ").strip().lower() not in ("y", "yes"):
            print("nothing exported")
            sys.exit(1)
        res = engine.export_run(slug, out_dir=args.out, user=user)
        print(f"exported {slug} to {res['path']} (sha256 {res['sha256']}, {res['files']} files, {len(res['excluded'])} excluded)")
    finally:
        engine.close()


def cmd_run_import(args):
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        name = Path(args.bundle).name
        user, _ = human_gate(engine, None, "run import", target=name)
        if not args.yes and input(f"Import the run in {args.bundle}? [y/N] ").strip().lower() not in ("y", "yes"):
            print("nothing imported")
            sys.exit(1)
        try:
            run = engine.import_run(args.bundle, user=user)
        except SentinelError as err:
            engine.audit(user, "tty", "run_import_refused", name, reason=err.code)
            raise
        print(f"imported run {run['slug']} ({run['state']}, acceptance {run['acceptance_status']})")
    finally:
        engine.close()


def task_process_refusal(what):
    """E_ACTOR when called from a task process (SENTINEL_TASK_ID is set): human-only commands that need no terminal."""
    task = os.environ.get("SENTINEL_TASK_ID")
    if task:
        raise SentinelError("E_ACTOR", f"a task process may not run `sentinel {what}` (called from task {task})",
                            {"task": task, "command": what})


def usage_exit(parser, message):
    parser.print_usage(sys.stderr)
    print(f"sentinel: error: {message}", file=sys.stderr)
    sys.exit(2)


def open_audit_registry(config_path, config):
    from registry import Registry
    state = state_dir_of(config_path, config)
    if not (state / "sentinel.db").is_file():
        raise SentinelError("E_NOT_FOUND", "no registry in this workspace; nothing to read", exit_code=1)
    return Registry.open(state)


def cmd_audit_verify(args):
    import auditlog
    config_path, config = load_config(args.dir)
    if args.file:
        res = auditlog.verify_file(args.file, db=Path(args.db) if args.db else None)
    else:
        db = Path(args.db) if args.db else state_dir_of(config_path, config) / "sentinel.db"
        if not db.is_file():
            raise SentinelError("E_NOT_FOUND", f"no registry at {db}", exit_code=1)
        res = auditlog.verify_db(db)
    if not res["ok"]:
        raise SentinelError("E_INTEGRITY", res["message"], {"row": res["row"]}, exit_code=1)
    extra = []
    if res.get("scrubbed"):
        extra.append(f"{res['scrubbed']} scrubbed rows checked for their chain link only")
    if res.get("imported"):
        extra.append(f"{res['imported']} imported rows")
    if res.get("registry_checked"):
        extra.append("every row matches the registry")
    print(f"audit ok: {res['rows']} rows, head chain_sha {res['head']}" + (f" ({'; '.join(extra)})" if extra else ""))


def cmd_audit_export(args):
    import auditlog
    import scrub
    from datetime import datetime
    audited_gate(args, "audit export", "audit_export", args.out)
    config_path, config = load_config(args.dir)
    filters = {"from": auditlog.parse_day(args.date_from, "--from") if args.date_from else None,
               "to": auditlog.parse_day(args.date_to, "--to") if args.date_to else None,
               "actor": args.actor, "channel": args.channel, "action": args.action, "run": args.run}
    out = Path(args.out)
    try:
        reg = open_audit_registry(config_path, config)
    except SentinelError as err:
        if err.code == "E_LOCKED":
            err.exit_code = 1
        raise
    try:
        workspace = config_path.parent
        scrubber = scrub.Scrubber(workspace, scrub.env_values(workspace))
        user, _ = human_identity()
        tmp, digest, count, head = auditlog.export(reg, out, args.format, filters, scrubber,
                                                   (ROOT / "VERSION").read_text().strip(), workspace.name, workspace, args.force)
        try:
            with reg.transaction():
                reg.add_audit(user, "tty" if is_tty() else "cli", "audit_exported", str(out), after_sha=digest,
                              reason=json.dumps({k: v for k, v in filters.items() if v}, sort_keys=True))
            os.replace(tmp, out)
        except BaseException as e:
            Path(tmp).unlink(missing_ok=True)
            import sqlite3
            if isinstance(e, sqlite3.OperationalError) and "locked" in str(e):
                raise SentinelError("E_LOCKED", "the registry is locked for writing; try again", exit_code=1)
            raise
    finally:
        reg.close()
    print(json.dumps({"path": str(out), "rows": count, "head_chain_sha": head, "sha256": digest}))


def cmd_backup(args):
    import backup
    words = args.words
    if words and words[0] == "restore":
        if len(words) < 2:
            usage_exit(args.parser, "restore needs the backup file")
        if len(words) > 2:
            usage_exit(args.parser, f"unexpected argument {words[2]}")
        return cmd_backup_restore(args, words[1])
    if words:
        usage_exit(args.parser, f"unknown backup action {words[0]!r}; use `backup`, `backup --verify FILE` or `backup restore FILE`")
    if args.verify:
        info = backup.verify_backup(args.verify)
        print(json.dumps({k: v for k, v in info.items() if k != "registry_id"}))
        return
    audited_gate(args, "backup", "backup", args.out or ".sentinel/backups")
    config_path, config = load_config(args.dir)
    user, _ = human_identity()
    res = backup.create_backup(state_dir_of(config_path, config), args.out, user=user, allow_broken=args.force)
    for w in res["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    print(json.dumps(res))


def cmd_backup_restore(args, file):
    import backup
    from apiserver import userdir
    audited_gate(args, "backup restore", "restore", file, need_tty=True)
    config_path, config = load_config(args.dir)
    state = state_dir_of(config_path, config)
    info = backup.verify_backup(file)
    backup.check_workspace(state, info, Path(file).name)
    busy = backup.running_conflicts(state, userdir.config_dir())
    if busy:
        raise SentinelError("E_LOCKED", "cannot restore while something runs: " + "; ".join(t for t, _ in busy),
                            {"running": [d for _, d in busy]})
    print(f"restore {file} over {state / 'sentinel.db'} (schema {info['schema_version']}, counts {info['counts']})")
    print(f"sha256: {info['sha256']}")
    try:
        typed = input("Type the first 8 characters of the sha256 to confirm: ")
        if len(typed.strip()) >= 8 and info["sha256"].startswith(typed.strip().lower()):
            reasons = backup.unverified_reasons(info)
            for r in reasons:
                print(f"warning: {r}")
            if reasons and input("This copy is not verified. Type `restore anyway` to go on: ").strip() != "restore anyway":
                print("nothing restored", file=sys.stderr)
                sys.exit(1)
    except (EOFError, KeyboardInterrupt):
        print("\ninput closed; nothing restored", file=sys.stderr)
        sys.exit(1)
    if len(typed.strip()) < 8 or not info["sha256"].startswith(typed.strip().lower()):
        print("the typed value does not match; nothing restored", file=sys.stderr)
        sys.exit(1)
    user, _ = human_identity()
    res = backup.restore(state, file, user=user, expected_sha=info["sha256"], allow_unverified=bool(backup.unverified_reasons(info)))
    for w in res["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    print(f"restored {file}; the previous registry is in {state / 'backups'}")


def port_arg(text):
    try:
        port = int(text)
    except ValueError:
        port = 0
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("the port must be from 1024 to 65535")
    return port


def bind_arg(text):
    """`--bind` takes only 0.0.0.0, and only inside the Sentinel container image (SENTINEL_CONTAINER=1 and a container marker)."""
    from apiserver import netguard
    if text != "0.0.0.0":
        raise argparse.ArgumentTypeError("the only value is 0.0.0.0")
    if not netguard.container_ok():
        raise argparse.ArgumentTypeError("--bind 0.0.0.0 is allowed only inside the Sentinel container image "
                                         "(SENTINEL_CONTAINER=1 and a container); on a host the server listens on 127.0.0.1 only")
    return text


def peer_arg(text):
    """`--allow-peer` takes one IP address, the address a published port arrives from when it is not the container's gateway."""
    import ipaddress
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        raise argparse.ArgumentTypeError("use one IP address, for example 10.0.2.2") from None


def public_host_arg(text):
    """`--public-host` takes localhost:PORT or 127.0.0.1:PORT, the name a browser uses to reach a published port."""
    name, sep, port = text.lower().partition(":")
    if name not in ("localhost", "127.0.0.1") or not sep or not port.isdigit() or not 1024 <= int(port) <= 65535:
        raise argparse.ArgumentTypeError("use localhost:PORT or 127.0.0.1:PORT with a port from 1024 to 65535")
    return f"{name}:{int(port)}"


def pick_orchestrator(installed):
    """Numbered list of installed providers; Enter (or anything invalid) means none."""
    print("Which AI tool orchestrates dashboard runs?")
    for i, pid in enumerate(installed, 1):
        print(f"  {i}. {pid}")
    print("  Enter: none")
    try:
        answer = input("> ").strip()
    except EOFError:
        return None
    if answer in installed:
        return answer
    if answer.isdigit() and 1 <= int(answer) <= len(installed):
        return installed[int(answer) - 1]
    return None


def cmd_dashboard(args):
    """Start the local dashboard server, or attach to the one that runs. A human at a terminal only: both
    ways print a URL that holds the token."""
    if os.environ.get("SENTINEL_TASK_ID"):
        raise SentinelError("E_ACTOR", "a task process may not run `sentinel dashboard`",
                            {"task": os.environ["SENTINEL_TASK_ID"], "command": "dashboard"})
    if not is_tty():
        raise refuse_without_tty("`sentinel dashboard`")
    workspace = next((f for f in [Path(args.dir).resolve(), *Path(args.dir).resolve().parents]
                      if (f / CONFIG_NAME).exists()), None)
    from apiserver.lifecycle import run_dashboard
    import providers
    try:
        pconfig = load_config(args.dir)[1] if workspace else None
    except (SystemExit, SentinelError):
        pconfig = None
    valid = [p["id"] for p in providers.detect(pconfig)]
    installed = providers.installed_ids(pconfig)
    orchestrator = args.provider
    if orchestrator is not None:
        if orchestrator not in valid:
            raise SentinelError("E_VALIDATION", f"unknown provider {orchestrator!r}; valid: {', '.join(valid)}")
        if orchestrator not in installed:
            raise SentinelError("E_PRECONDITION", f"provider {orchestrator!r} is not installed; installed: {', '.join(installed) or 'none'}")
    elif os.environ.get("SENTINEL_ORCHESTRATOR"):
        orchestrator = os.environ["SENTINEL_ORCHESTRATOR"]
        if orchestrator.lower() == "none":
            orchestrator = None
        elif orchestrator not in installed:
            raise SentinelError("E_VALIDATION", f"SENTINEL_ORCHESTRATOR={orchestrator!r} is not an installed provider; installed: {', '.join(installed) or 'none'}")
    elif installed:
        orchestrator = pick_orchestrator(installed)
    # --bind is the container mode: the server is the container's main process, so it stays in the foreground
    if getattr(args, "foreground", False) or args.bind:
        from apiserver.lifecycle import run_dashboard
        sys.exit(run_dashboard(workspace, args.port, args.no_open, args.bind, args.public_host, args.allow_peer, orchestrator))
    else:
        from service import dashboard_ensure_and_open
        sys.exit(dashboard_ensure_and_open(workspace, args.port, args.no_open, args.bind, args.public_host, args.allow_peer, orchestrator))


def cmd_service(args):
    """sentinel service start|stop|status|run|autostart|pause|resume"""
    if os.environ.get("SENTINEL_TASK_ID"):
        raise SentinelError("E_ACTOR", "a task process may not run `sentinel service`",
                            {"task": os.environ["SENTINEL_TASK_ID"], "command": f"service {args.service_cmd}"})
    import service
    workspace = next((f for f in [Path(args.dir).resolve(), *Path(args.dir).resolve().parents]
                      if (f / CONFIG_NAME).exists()), None)
    if args.service_cmd == "run":
        orchestrator = getattr(args, "provider", None)
        sys.exit(service.service_run(
            workspace=workspace,
            port=getattr(args, "port", None),
            bind=getattr(args, "bind", None),
            public_host=getattr(args, "public_host", None),
            allow_peers=getattr(args, "allow_peer", ()),
            orchestrator=orchestrator,
        ))
    elif args.service_cmd == "start":
        sys.exit(service.service_start(
            workspace=workspace,
            port=getattr(args, "port", None),
            bind=getattr(args, "bind", None),
            public_host=getattr(args, "public_host", None),
            allow_peers=getattr(args, "allow_peer", ()),
        ))
    elif args.service_cmd == "stop":
        sys.exit(service.service_stop())
    elif args.service_cmd == "status":
        sys.exit(service.service_status(as_json=getattr(args, "json", False)))
    elif args.service_cmd == "autostart":
        sys.exit(service.service_autostart(args.action))
    elif args.service_cmd in ("pause", "resume"):
        err = gate_error(f"service {args.service_cmd}")
        if err:
            raise err
        user, _ = human_identity()
        sys.exit(service.factory_pause(args.service_cmd == "pause", user, args.comment))


def cmd_stop(args):
    """sentinel stop: alias of service stop"""
    if os.environ.get("SENTINEL_TASK_ID"):
        raise SentinelError("E_ACTOR", "a task process may not run `sentinel stop`",
                            {"task": os.environ["SENTINEL_TASK_ID"], "command": "stop"})
    import service
    sys.exit(service.service_stop())


def cmd_task(args):
    """task run | task complete. A task process (SENTINEL_TASK_ID set) is refused by the engine."""
    config_path, config = load_config(args.dir)
    engine = open_registry(config_path, config)
    try:
        caller = os.environ.get("SENTINEL_TASK_ID")
        if args.task_cmd == "run":
            result = engine.run_task(args.task_id, caller_task=caller)
        else:
            result = engine.complete_task(args.task_id, caller_task=caller)
        code = result.pop("exit")
        tail = result.pop("stderr_tail", None)
        print(json.dumps(result, indent=2))
        if result.get("blocked"):
            print(f"{result['reason']}; fix: {result['fix']}", file=sys.stderr)
        elif tail and result["state"] == "FAILED":
            print("----- runner stderr (tail)", file=sys.stderr)
            print(tail, file=sys.stderr)
        if result.get("retry"):
            print(f"retry queued: {result['retry']}", file=sys.stderr)
        for line in (result.get("completion") or {}).get("errors") or []:
            print(f"rejected: {line}", file=sys.stderr)
        sys.exit(code)
    finally:
        engine.close()


def cmd_sync(args):
    from shared import Shared
    import scrub
    config_path, config = load_config(args.dir)
    shared = Shared(config_path.parent, config)
    if args.sync_cmd == "pull":
        shared.pull()
        return
    if args.auto and not args.cont:
        engine = open_registry(config_path, config)
        try:
            v2 = engine.is_v2(args.slug)
        finally:
            engine.close()
        if v2:
            print("version 2 runs never push by themselves: run `sentinel sync push <slug> --yes` after the requester approved")
            return
    if args.cont:
        pass
    elif args.auto:
        if not (config.get("state") or {}).get("auto_sync_push", False):
            print("state.auto_sync_push is off: not pushing; ask the requester, then run with --yes")
            return
    elif not args.yes:
        sys.exit("push needs --yes after the requester has approved it, or --auto when state.auto_sync_push is on")
    workspace = config_path.parent
    scrubber = scrub.Scrubber(workspace, scrub.env_values(workspace))
    run_directory = run_dir(config_path, config, args.slug)
    check = lambda: scrub.check_paths([shared.dir], scrubber)
    if args.cont:
        shared.continue_push(args.slug, check)
    else:
        shared.push(args.slug, run_directory, check)


def cmd_spec_set(args):
    from shared import Shared
    config_path, config = load_config(args.dir)
    tests = [t for t in (args.tests or "").split(",") if t]
    Shared(config_path.parent, config).set_spec(args.slug, args.status, args.pr, tests)
    print(f"spec {args.slug} updated in index")


def cmd_metrics_record(args):
    config_path, config = load_config(args.dir)
    path = run_dir(config_path, config, args.slug) / "metrics.json"
    data = json.loads(path.read_text()) if path.exists() else {"stages": []}
    data["stages"].append({"stage": args.stage, "tokens": args.tokens, "seconds": args.seconds, "model": args.model, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    path.write_text(json.dumps(data, indent=2))
    print(f"recorded {args.stage} for {args.slug}")


def _stats_range(args):
    import analytics
    try:
        return analytics.check_range(args.from_day, args.to_day)
    except SentinelError as err:
        print(f"sentinel stats: argument --{err.details.get('field', 'from')}: {err.message}", file=sys.stderr)
        sys.exit(2)


def _legacy_in_range(state, start, end):
    if not (start or end):
        return True
    day = str(state.get("started") or "")[:10]
    return bool(day) and (not start or day >= start) and (not end or day <= end)


def cmd_stats(args):
    import analytics
    if getattr(args, "usage", False):
        since = args.since or args.from_day
        end = args.to_day
        from apiserver import userdir
        cfgdir = userdir.config_dir()
        sources = []
        try:
            p_data = userdir.load_projects(cfgdir)
            for p in p_data.get("projects", []):
                pid = p.get("id")
                ppath = Path(p.get("path") or "")
                if ppath.is_dir():
                    try:
                        cfg_p, cfg = load_config(ppath)
                        sdir = state_dir_of(cfg_p, cfg)
                        if (sdir / "sentinel.db").exists():
                            sources.append((pid, sdir / "sentinel.db"))
                    except Exception:
                        pass
        except Exception:
            pass

        if not sources or (args.project and not any(s[0] == args.project for s in sources)):
            try:
                cfg_p, cfg = load_config(args.dir)
                sdir = state_dir_of(cfg_p, cfg)
                pid = cfg.get("project", {}).get("name") or "default"
                if (sdir / "sentinel.db").exists():
                    sources.append((pid, sdir / "sentinel.db"))
            except Exception:
                pass

        if args.project:
            matched = [s for s in sources if s[0] == args.project]
            if not matched:
                raise SentinelError("E_NOT_FOUND", f"no project named {args.project!r}", {"project": args.project})
            sources = matched

        usage = analytics.compute_usage(sources, project=args.project, since=since, end=end)
        if args.format == "md":
            sys.stdout.write(analytics.markdown_usage(usage))
        else:
            print(json.dumps(usage, indent=2))
        return

    start, end = _stats_range(args)
    config_path, config = load_config(args.dir)
    state_dir = state_dir_of(config_path, config)
    v2 = analytics.compute(state_dir / "sentinel.db", start, end, providers=_runner_ids(config))
    if args.format == "md":
        sys.stdout.write(analytics.markdown(v2))
        return
    runs_dir = state_dir / "runs"
    states = []
    for p in sorted(runs_dir.glob("*/state.json")):
        state = json.loads(p.read_text())
        if "schema_version" not in state and _legacy_in_range(state, start, end):
            states.append(state)
    tiers, escalated, rounds = {}, 0, {"review": [], "qa": [], "release_check": []}
    stage_tokens, stage_seconds, outcomes = {}, {}, {}
    isolation = {"subagent": 0, "headless": 0, "inline": 0, "other": 0}
    for state in states:
        tiers[state["tier"]] = tiers.get(state["tier"], 0) + 1
        if state["tier"] != state.get("initial_tier", state["tier"]):
            escalated += 1
        for key in rounds:
            rounds[key].append(state["rounds"].get(key, 0))
        for how in (state.get("sessions") or {}).values():
            isolation[how if how in isolation else "other"] += 1
        outcome = state.get("outcome", "open")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        metrics = runs_dir / state["slug"] / "metrics.json"
        if metrics.exists():
            for entry in json.loads(metrics.read_text())["stages"]:
                stage_tokens[entry["stage"]] = stage_tokens.get(entry["stage"], 0) + (entry.get("tokens") or 0)
                stage_seconds[entry["stage"]] = stage_seconds.get(entry["stage"], 0) + (entry.get("seconds") or 0)
    average = lambda values: round(sum(values) / len(values), 2) if values else 0
    print(json.dumps({
        "runs": len(states), "by_tier": tiers, "escalated_runs": escalated, "outcomes": outcomes,
        "avg_rounds": {k: average(v) for k, v in rounds.items()}, "stage_isolation": isolation,
        "tokens_by_stage": stage_tokens, "seconds_by_stage": stage_seconds, "v2": v2,
    }, indent=2))


def cmd_notifications(args):
    """List or mark read the local notifications of every registered workspace (read state: ~/.config/sentinel/user.db)."""
    import notifications as N
    if args.action == "read" and os.environ.get("SENTINEL_TASK_ID"):
        raise SentinelError("E_ACTOR", "a task process may not run `sentinel notifications read`",
                            {"task": os.environ["SENTINEL_TASK_ID"], "command": "notifications read"})
    from apiserver.views import LIMIT_MAX
    if not 1 <= args.limit <= LIMIT_MAX:
        print(f"sentinel notifications: argument --limit: must be an integer from 1 to {LIMIT_MAX}, not {args.limit}", file=sys.stderr)
        sys.exit(2)
    sources = N.sources_from_registry(N.userdir.config_dir())
    path = N.user_db_path()
    try:
        if args.action == "read":
            if args.all:
                count = N.mark_all(sources, path)
                print(f"marked {count} notification{'' if count == 1 else 's'} read")
            elif args.target:
                n = N.mark_read(sources, path, args.target)
                print(f"marked {n['id']} read at {n['read_at']}")
            else:
                print("sentinel notifications read: give a notification id or --all", file=sys.stderr)
                sys.exit(2)
            return
        if args.target or args.all:
            print("sentinel notifications: use `read <id>` or `read --all` to mark notifications read", file=sys.stderr)
            sys.exit(2)
        result = N.compute(sources, path, project=args.project, limit=args.limit, unread_only=args.unread)
    except N.UserDbError as err:
        print(f"E_INTERNAL: {err.message}; fix: {err.fix}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    for n in result["items"]:
        print(f"{'*' if not n['read_at'] else ' '} {n['at'][:16].replace('T', ' ')}  {n['level']:<7}  {n['project']}  {n['text']}  [{n['id']}]")
        print(f"    {n['command']}")
    for u in result["unavailable"]:
        print(f"unavailable: {u['project']} ({u['reason']})", file=sys.stderr)
    if not result["items"] and not args.unread:
        print("No notifications.")


def _runner_ids(config):
    import analytics
    return analytics.runner_ids(config)


def cmd_clean(args):
    config_path, config = load_config(args.dir)
    if args.db and (config.get("qa") or {}).get("db_clone") not in (None, "none"):
        subprocess.run([sys.executable, str(ROOT / "scripts/qa_data.py"), "--config", str(config_path), "drop-all"], check=True)
    state_dir = state_dir_of(config_path, config)
    retention = (config.get("state") or {}).get("retention") or {}
    keep_runs = retention.get("runs", 20)
    cutoff = time.time() - retention.get("logs_days", 14) * 86400
    runs = sorted((state_dir / "runs").glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for old in runs[keep_runs:]:
        shutil.rmtree(old, ignore_errors=True)
        removed.append(str(old))
    cache = state_dir / "cache"
    if cache.exists():
        for item in cache.rglob("*"):
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink()
                removed.append(str(item))
    print(f"removed {len(removed)} item(s)")


def _kb_shared_dir(config_path, config):
    """Return the shared dir path used by knowledge commands."""
    from shared import Shared
    return str(Shared(config_path.parent, config).dir)


def _kb_scrubber(config_path):
    import scrub
    workspace = config_path.parent
    return scrub.Scrubber(workspace, scrub.env_values(workspace))


def cmd_kb_ingest(args):
    import knowledge
    config_path, config = load_config(args.dir)
    kc = knowledge.kb_config(config)
    if not kc["enabled"]:
        print("knowledge base is disabled (knowledge.enabled = false)")
        return
    require_shared(config_path, config)
    shared_dir = _kb_shared_dir(config_path, config)
    scrubber = _kb_scrubber(config_path)
    if getattr(args, "no_summarize", False):
        config = dict(config)
        kb_override = dict(config.get("knowledge") or {})
        kb_override["summarize"] = False
        config["knowledge"] = kb_override
    results = knowledge.ingest(
        shared_dir, str(config_path.parent), config,
        scrubber=scrubber,
        only_repo=args.repo,
        only_branch=args.branch,
        no_summarize=getattr(args, "no_summarize", False),
    )
    total = sum(c for repo in results.values() for c in repo.values())
    for repo_id, branches in results.items():
        for branch, count in branches.items():
            print(f"{repo_id}@{branch}: {count} change(s)")
    print(f"total: {total} change(s) ingested")
    if getattr(args, "publish", False):
        import kb_worker
        msg = f"sentinel: knowledge ingest for {args.repo}" if args.repo else "sentinel: knowledge ingest"
        outcome = kb_worker.publish_under_lock(config_path.parent, config, scrubber, msg)
        print(f"published: {outcome}")


def cmd_kb_snapshot(args):
    import knowledge
    config_path, config = load_config(args.dir)
    kc = knowledge.kb_config(config)
    if not kc["enabled"]:
        print("knowledge base is disabled (knowledge.enabled = false)")
        return
    require_shared(config_path, config)
    shared_dir = _kb_shared_dir(config_path, config)
    scrubber = _kb_scrubber(config_path)
    workspace = str(config_path.parent)
    repos = config.get("repos", [])
    if args.repo:
        repos = [r for r in repos if r.get("id") == args.repo]
        if not repos:
            sys.exit(f"repo not found in config: {args.repo}")
    for repo_cfg in repos:
        repo_path = (Path(workspace) / repo_cfg["path"]).resolve()
        if not repo_path.exists():
            continue
        knowledge.snapshot_repo(shared_dir, workspace, repo_cfg, config, scrubber=scrubber, force=args.force)
        print(f"snapshot completed for {repo_cfg['id']}")


def cmd_kb_backfill(args):
    import knowledge
    config_path, config = load_config(args.dir)
    kc = knowledge.kb_config(config)
    if not kc["enabled"]:
        print("knowledge base is disabled (knowledge.enabled = false)")
        return
    require_shared(config_path, config)
    shared_dir = _kb_shared_dir(config_path, config)
    estimate = knowledge.estimate_backfill(shared_dir, str(config_path.parent), config, since=args.since)
    total_est = sum(c for repo in estimate.values() for c in repo.values())
    print(f"estimated changes to backfill: {total_est}")
    for repo_id, branches in estimate.items():
        for branch, count in branches.items():
            print(f"  {repo_id}@{branch}: {count}")
    if not args.yes:
        try:
            answer = input("proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\naborted")
            return
        if answer not in ("y", "yes"):
            print("aborted")
            return
    # Clear cursors so ingest starts from backfill_months (or --since)
    if args.since:
        # Override backfill window via config override
        config = dict(config)
        # We compute the months difference roughly
        from datetime import datetime as _dt
        try:
            since_date = _dt.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            sys.exit(f"invalid date: {args.since}; use YYYY-MM-DD")
        diff_days = (_dt.now() - since_date).days
        kb_override = dict(config.get("knowledge") or {})
        kb_override["backfill_months"] = max(1, diff_days // 30 + 1)
        config["knowledge"] = kb_override
    scrubber = _kb_scrubber(config_path)
    results = knowledge.ingest(
        shared_dir, str(config_path.parent), config,
        scrubber=scrubber,
    )
    total = sum(c for repo in results.values() for c in repo.values())
    print(f"backfilled {total} change(s)")


def cmd_kb_status(args):
    import knowledge
    config_path, config = load_config(args.dir)
    kc = knowledge.kb_config(config)
    if not kc["enabled"]:
        print("knowledge base is disabled")
        return
    require_shared(config_path, config)
    shared_dir = _kb_shared_dir(config_path, config)
    knowledge.ensure_layout(shared_dir)
    info = knowledge.status(shared_dir, config)
    import kb_worker
    info["jobs"] = kb_worker.job_summary_from_db(state_dir_of(config_path, config) / "sentinel.db")
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"records: {info['records']['total']} total, {info['records']['active']} active, {info['records']['dropped']} dropped")
        for repo, count in info.get("by_repo", {}).items():
            print(f"  {repo}: {count}")
        for ck, cur in info.get("cursors", {}).items():
            sha = cur.get("sha", "?")[:8] if isinstance(cur, dict) else str(cur)[:8]
            print(f"cursor {ck}: {sha}")
        jobs = info["jobs"]
        if jobs:
            print(f"jobs: {jobs['queued']} queued")
            for label in ("last_success", "last_failure"):
                if jobs[label]:
                    print(f"  {label.replace('_', ' ')}: {jobs[label]['run']} at {jobs[label]['at']}" + (f" ({jobs[label]['error']})" if jobs[label]["error"] else ""))


def cmd_kb_worker(args):
    import kb_worker
    config_path, config = load_config(args.dir)
    if not kb_worker.knowledge_enabled(config):
        return
    handled = kb_worker.run_worker(config_path.parent)
    if handled is not None:
        print(f"knowledge worker handled {handled} job(s)")


PASSTHROUGH = {
    "release-check": {"script": "release_check.py", "config": True, "workspace": True},
    "qa-data": {"script": "qa_data.py", "config": True},
    "shared-check": {"script": "shared_ci.py"},
    "selftest": {"script": "selftest.py"},
    "stage render": {"script": "render_stage.py", "config": True, "workspace": True},
    "stage run": {"script": "run_stage.py", "config": True},
    "change-map collect": {"script": "change_map/collect_changes.py", "config": True},
    "change-map dump": {"script": "change_map/dump_diffs.py"},
    "change-map render": {"script": "change_map/render_map.py"},
}


def cmd_passthrough(args):
    spec = PASSTHROUGH[args.target]
    extra = list(args.extra)
    prefix = []
    if spec.get("config") and "--config" not in extra:
        config_path = find_config(args.dir)
        prefix += ["--config", str(config_path)]
        if spec.get("workspace") and "--workspace" not in extra:
            prefix += ["--workspace", str(config_path.parent)]
    sys.exit(subprocess.call([sys.executable, str(ROOT / "scripts" / spec["script"]), *prefix, *extra]))


def add_passthrough_commands(sub):
    for name in ("release-check", "qa-data", "shared-check", "selftest"):
        parser = sub.add_parser(name, add_help=False)
        parser.set_defaults(func=cmd_passthrough, target=name, passthrough=True)
    for group, members in (("stage", ("render", "run")), ("change-map", ("collect", "dump", "render"))):
        group_parser = sub.add_parser(group)
        group_sub = group_parser.add_subparsers(dest=f"{group}_cmd", required=True)
        for member in members:
            parser = group_sub.add_parser(member, add_help=False)
            parser.set_defaults(func=cmd_passthrough, target=f"{group} {member}", passthrough=True)


def main():
    parser = argparse.ArgumentParser(prog="sentinel")
    parser.add_argument("--dir", default=".")
    parser.add_argument("--version", action="version", version=(ROOT / "VERSION").read_text().strip())
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init")
    init.add_argument("--shape")
    init.add_argument("--non-interactive", action="store_true")
    init.add_argument("--force", action="store_true")
    init.add_argument("--set", action="append", help="id.path=..., id.profile=..., count=N")
    init.add_argument("--shared-repo", help="clone URL of your team's private shared repo (asked for when omitted in interactive mode)")
    init.add_argument("--local-only", action="store_true", help="no shared repo: keep rules, specs and regression tests only in .sentinel/shared on this machine")
    init.set_defaults(func=cmd_init)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--check-models", action="store_true", help="ask each runner whether it accepts the model set in routing")
    doctor.add_argument("--fix-routing", action="store_true", help="suggest a runner and model for every role that blocks engine runs and write it after a typed yes (human, interactive terminal only)")
    doctor.set_defaults(func=cmd_doctor)
    routing = sub.add_parser("routing", help="show which runner and model each stage will use")
    routing.add_argument("--stage")
    routing.add_argument("--repo")
    routing.add_argument("--json", action="store_true")
    routing.set_defaults(func=cmd_routing)

    sync = sub.add_parser("sync-adapters")
    sync.add_argument("--tool", default="claude", choices=["claude", "agents", "codex", "gemini", "cursor"])
    sync.add_argument("--out")
    sync.set_defaults(func=cmd_sync_adapters)

    run = sub.add_parser("run")
    run_sub = run.add_subparsers(dest="run_cmd", required=True)
    new = run_sub.add_parser("new")
    new.add_argument("slug")
    new.add_argument("--tier", type=int, choices=[1, 2, 3, 4])
    new.add_argument("--adhoc", action="store_true", help="single-stage run: no lock, no shared repo needed")
    new.add_argument("--legacy", action="store_true", help="create a 0.1 run (also implied by --tier and --adhoc)")
    new.add_argument("--type", help="run type for a version 2 run")
    new.add_argument("--repos", help="comma-separated repo ids a version 2 run covers (default: all)")
    new.add_argument("--driver", choices=["engine", "cli"], default="cli",
                     help="who drives a version 2 run: cli (you, or an AI tool with the /sentinel skill; default) or engine "
                          "(the Sentinel service runs it; needs --request and a CLI runner for every role)")
    new.add_argument("--request", help="the request text of a version 2 run (needed by --driver engine)")
    new.set_defaults(func=cmd_run_new)
    update = run_sub.add_parser("update")
    update.add_argument("slug")
    update.add_argument("--stage")
    update.add_argument("--status", default="done")
    update.add_argument("--session", help="stage=id")
    update.add_argument("--round", help="review|qa|release_check=N")
    update.add_argument("--tier", type=int, choices=[1, 2, 3, 4])
    update.set_defaults(func=cmd_run_update)

    finish = run_sub.add_parser("finish")
    finish.add_argument("slug")
    finish.add_argument("--outcome", choices=["passed", "stopped", "abandoned"], default="passed")
    finish.set_defaults(func=cmd_run_finish)

    export = run_sub.add_parser("export", help="write a scrubbed bundle of a version 2 run (human, interactive terminal only)")
    export.add_argument("slug")
    export.add_argument("--yes", action="store_true", help="skip the confirmation question")
    export.add_argument("--out", help="folder for the bundle (default: the workspace)")
    export.set_defaults(func=cmd_run_export)
    imp = run_sub.add_parser("import", help="import a run bundle (human, interactive terminal only)")
    imp.add_argument("bundle")
    imp.add_argument("--yes", action="store_true", help="skip the confirmation question")
    imp.set_defaults(func=cmd_run_import)

    review = sub.add_parser("review", help="show the specification or Gherkin set in review (read-only)")
    review.add_argument("slug")
    review.add_argument("gate", nargs="?", choices=["spec", "gherkin"])
    review.set_defaults(func=cmd_review)

    approve = sub.add_parser("approve", help="decide the specification or Gherkin set (human, interactive terminal only)")
    approve.add_argument("slug")
    approve.add_argument("gate", nargs="?", choices=["spec", "gherkin"])
    approve.add_argument("--request-changes", action="store_true")
    approve.add_argument("--reject", action="store_true")
    approve.add_argument("-m", "--comment")
    approve.set_defaults(func=cmd_approve)

    nxt = sub.add_parser("next", help="what is allowed now: a task, an orchestrator action, a human action, wait or done")
    nxt.add_argument("slug")
    nxt.add_argument("--json", action="store_true")
    nxt.set_defaults(func=cmd_next)

    accept = sub.add_parser("accept", help="confirm or reject the result of a completed run (human, interactive terminal only)")
    accept.add_argument("slug")
    accept.add_argument("--reject", action="store_true")
    accept.add_argument("-m", "--comment")
    accept.set_defaults(func=cmd_accept)

    report = sub.add_parser("report", help="write report.json and report.md of a version 2 run")
    report.add_argument("slug")
    report.add_argument("--json", action="store_true")
    report.set_defaults(func=cmd_report)

    resolve = sub.add_parser("resolve", help="record a human decision on a parked run and resume it (human, interactive terminal only)")
    resolve.add_argument("slug")
    resolve.add_argument("--waive", metavar="FINDING", help="waive an open finding (the run then completes rejected)")
    resolve.add_argument("--approve-file", metavar="PATH", help="approve a destructive migration file by its sha256")
    resolve.add_argument("--approve-clone", action="store_true", help="approve QA on a clone of real data")
    resolve.add_argument("--approve-security", action="store_true", help="approve the tier 4 security gate")
    resolve.add_argument("--refresh-config", action="store_true", help="re-snapshot sentinel.config.yaml into the run, then resume it")
    resolve.add_argument("--no-resume", action="store_true", help="record the decision but leave the run parked")
    resolve.add_argument("--retry-now", action="store_true", help="start the tasks that wait for a provider usage limit at once")
    resolve.add_argument("-m", "--comment")
    resolve.set_defaults(func=cmd_resolve)

    verify = sub.add_parser("verify", help="run one verification round of a version 2 run (engine checks; exit 0 passed, 1 failed, 6 human)")
    verify.add_argument("slug")
    verify.set_defaults(func=cmd_verify)

    task = sub.add_parser("task", help="run a queued task, or complete a native task (orchestrator)")
    task_sub = task.add_subparsers(dest="task_cmd", required=True)
    for name, text in (("run", "start a QUEUED task through its adapter"), ("complete", "a native task finished; the engine decides")):
        member = task_sub.add_parser(name, help=text)
        member.add_argument("task_id")
        member.set_defaults(func=cmd_task)

    dashboard = sub.add_parser("dashboard", help="start the local dashboard server, or attach to the running one (human, interactive terminal only)")
    dashboard.add_argument("provider", nargs="?", metavar="provider", help="runner id of the AI tool that orchestrates dashboard runs (claude, codex, gemini, agy, or one from config runners); asked in the terminal when omitted")
    dashboard.add_argument("--port", type=port_arg, help="port to listen on, 1024 to 65535 (default: a free port)")
    dashboard.add_argument("--no-open", action="store_true", help="do not open a browser")
    dashboard.add_argument("--foreground", action="store_true", help="run server in foreground; closing terminal stops server")
    dashboard.add_argument("--bind", type=bind_arg, metavar="0.0.0.0",
                           help="container image only (needs SENTINEL_CONTAINER=1): listen on all interfaces of the container; "
                                "publish the port on the host as 127.0.0.1:PORT only, never on another address")
    dashboard.add_argument("--public-host", type=public_host_arg, metavar="HOST:PORT",
                           help="also accept localhost:PORT or 127.0.0.1:PORT in Host and Origin (the published port) and print it in the URL; "
                                "outside a container its port must be the server's own --port")
    dashboard.add_argument("--allow-peer", type=peer_arg, action="append", default=[], metavar="IP",
                           help="with --bind: also answer this peer address (repeatable); loopback and the container's default gateway are always "
                                "answered, any other address is refused. For rootless Docker or Docker Desktop, where the published port arrives from another address")
    dashboard.set_defaults(func=cmd_dashboard)

    service_parser = sub.add_parser("service", help="manage the Sentinel background service")
    service_sub = service_parser.add_subparsers(dest="service_cmd", required=True)

    svc_start = service_sub.add_parser("start", help="start the Sentinel service detached in the background")
    svc_start.add_argument("--port", type=port_arg, help="port to listen on, 1024 to 65535 (default: a free port)")
    svc_start.add_argument("--bind", type=bind_arg, metavar="0.0.0.0", help=argparse.SUPPRESS)
    svc_start.add_argument("--public-host", type=public_host_arg, metavar="HOST:PORT", help=argparse.SUPPRESS)
    svc_start.add_argument("--allow-peer", type=peer_arg, action="append", default=[], metavar="IP", help=argparse.SUPPRESS)
    svc_start.set_defaults(func=cmd_service)

    svc_stop = service_sub.add_parser("stop", help="stop the running Sentinel service")
    svc_stop.set_defaults(func=cmd_service)

    svc_status = service_sub.add_parser("status", help="check Sentinel service status")
    svc_status.add_argument("--json", action="store_true", help="output JSON")
    svc_status.set_defaults(func=cmd_service)

    for name, text in (("pause", "pause the whole factory: no new agent task starts in any project; running tasks finish"),
                       ("resume", "resume the whole factory (runs keep their own pause)")):
        svc_flow = service_sub.add_parser(name, help=text)
        svc_flow.add_argument("-m", "--comment", help="why (kept in the audit log)")
        svc_flow.set_defaults(func=cmd_service)

    svc_run = service_sub.add_parser("run", help="run the Sentinel server in the foreground")
    svc_run.add_argument("provider", nargs="?", metavar="provider", help=argparse.SUPPRESS)
    svc_run.add_argument("--port", type=port_arg, help="port to listen on, 1024 to 65535 (default: a free port)")
    svc_run.add_argument("--bind", type=bind_arg, metavar="0.0.0.0", help=argparse.SUPPRESS)
    svc_run.add_argument("--public-host", type=public_host_arg, metavar="HOST:PORT", help=argparse.SUPPRESS)
    svc_run.add_argument("--allow-peer", type=peer_arg, action="append", default=[], metavar="IP", help=argparse.SUPPRESS)
    svc_run.set_defaults(func=cmd_service)

    svc_auto = service_sub.add_parser("autostart", help="manage systemd autostart (Linux)")
    svc_auto.add_argument("action", choices=["on", "off", "status"], help="enable (on), disable (off) or check (status) autostart")
    svc_auto.set_defaults(func=cmd_service)

    stop_parser = sub.add_parser("stop", help="stop the running Sentinel service (alias of service stop)")
    stop_parser.set_defaults(func=cmd_stop)

    for name, text in (("pause", "pause a version 2 run: the factory starts nothing more for it, running tasks finish"),
                       ("unpause", "let a paused version 2 run continue")):
        ctl = sub.add_parser(name, help=text + " (human, interactive terminal only)")
        ctl.add_argument("slug")
        ctl.add_argument("-m", "--comment", help="why")
        ctl.set_defaults(func=cmd_run_control, command=name)
    note = sub.add_parser("note", help="send a note to the next agent task of a version 2 run (human, interactive terminal only)")
    note.add_argument("slug")
    note.add_argument("text")
    note.set_defaults(func=cmd_run_control, command="note")

    triage = sub.add_parser("triage", help="submit triage factors for a version 2 run; the engine sets the tier")
    triage.add_argument("slug")
    triage.add_argument("--factors", default="", help="key=value,... (repos, files, migration, auth, security, regression, logic)")
    triage.add_argument("--tier", type=int, choices=[1, 2, 3, 4], help="requested tier; the engine may raise it")
    triage.set_defaults(func=cmd_triage)

    sync = sub.add_parser("sync")
    sync_sub = sync.add_subparsers(dest="sync_cmd", required=True)
    sync_sub.add_parser("pull").set_defaults(func=cmd_sync)
    push = sync_sub.add_parser("push")
    push.add_argument("slug")
    push.add_argument("--yes", action="store_true")
    push.add_argument("--continue", dest="cont", action="store_true", help="finish a push after resolving merge conflicts")
    push.add_argument("--auto", action="store_true", help="push only if state.auto_sync_push is on")
    push.set_defaults(func=cmd_sync)

    spec = sub.add_parser("spec")
    spec_sub = spec.add_subparsers(dest="spec_cmd", required=True)
    spec_set = spec_sub.add_parser("set")
    spec_set.add_argument("slug")
    spec_set.add_argument("--status", choices=["draft", "implemented", "superseded"])
    spec_set.add_argument("--pr")
    spec_set.add_argument("--tests", help="comma-separated file names under regression/")
    spec_set.set_defaults(func=cmd_spec_set)

    metrics = sub.add_parser("metrics")
    metrics_sub = metrics.add_subparsers(dest="metrics_cmd", required=True)
    record = metrics_sub.add_parser("record")
    record.add_argument("slug")
    record.add_argument("--stage", required=True)
    record.add_argument("--tokens", type=int)
    record.add_argument("--seconds", type=float)
    record.add_argument("--model")
    record.set_defaults(func=cmd_metrics_record)

    stats = sub.add_parser("stats", help="run statistics: the 0.1 keys plus a v2 section from the registry")
    stats.add_argument("--from", dest="from_day", metavar="YYYY-MM-DD", help="first run creation date (UTC, inclusive)")
    stats.add_argument("--to", dest="to_day", metavar="YYYY-MM-DD", help="last run creation date (UTC, inclusive)")
    stats.add_argument("--format", choices=("json", "md"), default="json", help="json (default) or a Markdown table of the v2 metrics")
    stats.add_argument("--usage", action="store_true", help="report usage metrics (tokens and cost by project, model, week, and totals)")
    stats.add_argument("--project", help="filter usage to this project")
    stats.add_argument("--since", metavar="YYYY-MM-DD", help="alias/start date for usage")
    stats.set_defaults(func=cmd_stats)

    notes = sub.add_parser("notifications", help="list local notifications, or mark them read with `read <id>` or `read --all`")
    notes.add_argument("action", nargs="?", choices=("read",))
    notes.add_argument("target", nargs="?", help="the notification id (<project>:<event number>) for `read`")
    notes.add_argument("--all", action="store_true", help="with `read`: mark every notification read")
    notes.add_argument("--unread", action="store_true", help="only unread notifications; prints nothing when there are none")
    notes.add_argument("--json", action="store_true")
    notes.add_argument("--project", help="only this project")
    notes.add_argument("--limit", type=int, default=50, help="most notifications to list (default 50)")
    notes.set_defaults(func=cmd_notifications)

    resume = sub.add_parser("resume")
    resume.add_argument("slug")
    resume.set_defaults(func=cmd_resume)

    shared_cmd = sub.add_parser("shared")
    shared_sub = shared_cmd.add_subparsers(dest="shared_cmd", required=True)
    shared_set = shared_sub.add_parser("set", help="set the team's shared repo URL and connect to it")
    shared_set.add_argument("url")
    shared_set.set_defaults(func=cmd_shared_set)
    shared_ci = shared_sub.add_parser("ci", help="write the CI workflow for the shared repo into .sentinel/shared (optional)")
    shared_ci.set_defaults(func=cmd_shared_ci)

    clean = sub.add_parser("clean")
    clean.add_argument("--db", action="store_true", help="also drop the throwaway QA schemas")
    clean.set_defaults(func=cmd_clean)

    scrub_cmd = sub.add_parser("scrub")
    scrub_cmd.add_argument("--check", action="store_true", help="verify .sentinel/shared is clean; non-zero exit on findings")
    scrub_cmd.add_argument("--shared", action="store_true", help="redact .sentinel/shared instead of runs and cache")
    scrub_cmd.set_defaults(func=cmd_scrub)

    audit = sub.add_parser("audit", help="verify the audit hash chain, or export the audit (human; no terminal needed)")
    audit_sub = audit.add_subparsers(dest="audit_cmd", required=True)
    a_verify = audit_sub.add_parser("verify", help="check the audit chain of the registry, a registry file or an export")
    a_verify.add_argument("--file", help="an exported audit file")
    a_verify.add_argument("--db", help="a registry file (default: this workspace); with --file, check every row of the file against it")
    a_verify.set_defaults(func=cmd_audit_verify)
    a_export = audit_sub.add_parser("export", help="write a scrubbed audit export (refused in a task process)")
    a_export.add_argument("--out", required=True)
    a_export.add_argument("--format", choices=["jsonl", "csv"], default="jsonl")
    a_export.add_argument("--from", dest="date_from", metavar="DATE")
    a_export.add_argument("--to", dest="date_to", metavar="DATE")
    a_export.add_argument("--actor")
    a_export.add_argument("--channel")
    a_export.add_argument("--action")
    a_export.add_argument("--run", metavar="SLUG")
    a_export.add_argument("--force", action="store_true", help="replace an existing file")
    a_export.set_defaults(func=cmd_audit_export)

    backup_cmd = sub.add_parser("backup", help="copy the workspace registry, check a copy (--verify FILE), or `restore FILE`")
    backup_cmd.add_argument("words", nargs="*", metavar="restore FILE")
    backup_cmd.add_argument("--out", help="folder for the copy (default: .sentinel/backups)")
    backup_cmd.add_argument("--verify", metavar="FILE", help="check an existing copy")
    backup_cmd.add_argument("--force", action="store_true", help="keep a copy whose audit chain is broken (recorded as chain_ok false)")
    backup_cmd.add_argument("--yes", action="store_true", help="accepted and ignored: restore always asks for the typed hash prefix")
    backup_cmd.set_defaults(func=cmd_backup, parser=backup_cmd)

    # -- kb (knowledge base) -------------------------------------------------
    kb = sub.add_parser("kb", help="knowledge base: ingest, backfill, status")
    kb_sub = kb.add_subparsers(dest="kb_cmd", required=True)

    kb_ingest = kb_sub.add_parser("ingest", help="ingest changes from tracked branches into the knowledge base")
    kb_ingest.add_argument("--repo", help="only this repo id")
    kb_ingest.add_argument("--branch", help="only this branch")
    kb_ingest.add_argument("--no-summarize", action="store_true", help="skip agent summarization (deterministic only)")
    kb_ingest.add_argument("--publish", action="store_true", help="publish changes under the knowledge lock after ingest")
    kb_ingest.set_defaults(func=cmd_kb_ingest)

    kb_snapshot = kb_sub.add_parser("snapshot", help="build snapshot summaries from branch tip")
    kb_snapshot.add_argument("--repo", help="only this repo id")
    kb_snapshot.add_argument("--force", action="store_true", help="force regeneration even if tree hash unchanged")
    kb_snapshot.set_defaults(func=cmd_kb_snapshot)

    kb_backfill = kb_sub.add_parser("backfill", help="backfill change records from history")
    kb_backfill.add_argument("--since", metavar="YYYY-MM-DD", help="backfill since this date instead of the default window")
    kb_backfill.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    kb_backfill.set_defaults(func=cmd_kb_backfill)

    kb_status_parser = kb_sub.add_parser("status", help="show knowledge base status")
    kb_status_parser.add_argument("--json", action="store_true")
    kb_status_parser.set_defaults(func=cmd_kb_status)

    kb_worker_parser = kb_sub.add_parser("worker", help="internal: process queued knowledge jobs")
    kb_worker_parser.set_defaults(func=cmd_kb_worker)

    add_passthrough_commands(sub)

    args, extra = parser.parse_known_args()
    if extra and not getattr(args, "passthrough", False):
        parser.error("unrecognized arguments: " + " ".join(extra))
    args.extra = extra
    if getattr(args, "public_host", None) and getattr(args, "port", None) != int(args.public_host.rpartition(":")[2]):
        from apiserver import netguard
        if not netguard.container_ok():
            parser.error("--public-host outside the Sentinel container must name the server's own port: give --port with the same port")
    try:
        args.func(args)
    except SentinelError as err:
        print(f"{err.code}: {err.message}", file=sys.stderr)
        if err.details:
            print(json.dumps(err.details), file=sys.stderr)
        sys.exit(err.exit_code)


if __name__ == "__main__":
    main()
