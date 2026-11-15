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


def detect_profile(repo_path):
    for profile_file in sorted((ROOT / "profiles").glob("*.json")):
        profile = json.loads(profile_file.read_text())
        if any((repo_path / marker).exists() for marker in profile["detect"]):
            return profile["id"]
    return "generic"


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
    config = yaml.safe_load((ROOT / "templates" / CONFIG_NAME).read_text())
    config["shape"] = shape
    config["repos"] = repos
    if local_only:
        config["state"].pop("shared_repo", None)
        config["state"]["shared_mode"] = "local"
        config["state"]["auto_sync_push"] = False
    else:
        config["state"]["shared_repo"] = shared_url
    profiles = {r["profile"] for r in repos}
    drivers = {load_profile_driver(p) for p in profiles}
    config["qa"] = {"driver": "playwright" if "playwright" in drivers else sorted(drivers - {"none"})[0] if drivers - {"none"} else "none", "db_clone": "none", "fixtures": "sanitized"}
    target.write_text(yaml.safe_dump(config, sort_keys=False))
    state_dir = workspace / config["state"]["dir"]
    for sub in ("runs", "cache"):
        (state_dir / sub).mkdir(parents=True, exist_ok=True)
    update_gitignore(workspace, config["state"]["dir"])
    print(f"wrote {target}")
    connected = connect_shared(target, config)
    print("next: `sentinel doctor`" if connected else "next: fix access to the shared repo, `sentinel sync pull`, then `sentinel doctor`")
    print("then install the Sentinel skills into your AI tool: npx skills@latest add chhunlyyy/sentinel -a <agent>   (claude-code, antigravity-cli, codex, cursor, opencode, devin, windsurf, amp, pi, ...; leave -a off to choose)")


def load_profile_driver(name):
    path = ROOT / "profiles" / f"{name}.json"
    return json.loads(path.read_text()).get("qa_driver", "none") if path.exists() else "none"


def update_gitignore(workspace, state_dir):
    path = workspace / ".gitignore"
    existing = path.read_text().splitlines() if path.exists() else []
    wanted = [f"{state_dir}/cache/", f"{state_dir}/runs/", f"{state_dir}/shared/", f"{state_dir}/generated/"]
    missing = [line for line in wanted if line not in existing]
    if missing:
        path.write_text("\n".join(existing + missing) + "\n")


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


def cmd_doctor(args):
    import health
    config_path, config = load_config(args.dir)
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


HUMAN_ONLY_COMMANDS = ["Bash(sentinel approve:*)", "Bash(sentinel accept:*)", "Bash(sentinel resolve:*)",
                       "Bash(sentinel --dir * approve *)", "Bash(sentinel --dir * accept *)", "Bash(sentinel --dir * resolve *)",
                       "Bash(sentinel run export:*)", "Bash(sentinel run import:*)",
                       "Bash(sentinel --dir * run export *)", "Bash(sentinel --dir * run import *)",
                       "Read(~/.config/sentinel/**)", "Read(//**/.config/sentinel/server.json)",
                       "Bash(cat ~/.config/sentinel/*)", "Bash(sentinel dashboard:*)", "Bash(sentinel --dir * dashboard *)",
                       "Bash(sentinel backup restore:*)", "Bash(sentinel --dir * backup restore *)",
                       "Bash(sentinel audit export:*)", "Bash(sentinel --dir * audit export *)"]


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
    run_dir(config_path, config, args.slug)
    only = [r for r in (args.repos or "").split(",") if r]
    unknown = [r for r in only if r not in {c["id"] for c in config["repos"]}]
    if unknown:
        raise SentinelError("E_VALIDATION", f"unknown repo(s): {', '.join(unknown)}")
    engine = open_registry(config_path, config)
    try:
        if engine.reg.get_run(args.slug):
            sys.exit(f"run {args.slug} already exists; use `sentinel resume {args.slug}`")
        claim_run(config_path, config, args.slug, False)
        try:
            engine.create_run(args.slug, "orchestrator", type=args.type, baseline=baseline_of(config_path, config, only))
        except BaseException:
            if not engine.reg.get_run(args.slug):  # row not committed: nothing owns the lock
                from shared import Shared
                Shared(config_path.parent, config).release(args.slug)
            raise
        print((run_dir(config_path, config, args.slug) / "state.json").read_text())
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
    user = getpass.getuser()
    name = None
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


def human_gate(engine, slug, what, target=None):
    """A human decision command: refused inside a task process (E_ACTOR) and without a terminal (E_NOT_TTY); refusals are
    audited against the run, or against `target` when the command names no run yet (an import)."""
    user, git_name = human_identity()
    task = os.environ.get("SENTINEL_TASK_ID")
    err = None
    if task:
        err = SentinelError("E_ACTOR", f"a task process may not run `sentinel {what}` (called from task {task})", {"task": task})
    elif not is_tty():
        err = refuse_without_tty(f"`sentinel {what}`")
    if err:
        if target or engine.is_v2(slug):
            engine.audit(user, "tty" if is_tty() else "cli", f"{what.replace(' ', '_')}_refused" if what != "accept" else "acceptance_refused",
                         target or slug, reason=err.code)
        raise err
    return user, git_name


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
        run = engine.resolve(slug, user=user, channel="tty", comment=args.comment, waive=args.waive, approve_file=args.approve_file,
                             approve_clone=args.approve_clone, approve_security=args.approve_security, resume=not args.no_resume)
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
        res = auditlog.verify_file(args.file)
    else:
        db = Path(args.db) if args.db else state_dir_of(config_path, config) / "sentinel.db"
        if not db.is_file():
            raise SentinelError("E_NOT_FOUND", f"no registry at {db}", exit_code=1)
        res = auditlog.verify_db(db)
    if not res["ok"]:
        raise SentinelError("E_INTEGRITY", res["message"], {"row": res["row"]}, exit_code=1)
    print(f"audit ok: {res['rows']} rows, head chain_sha {res['head']}")


def cmd_audit_export(args):
    import auditlog
    import scrub
    from datetime import datetime
    task_process_refusal("audit export")
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
    if args.verify is None and "--verify" in sys.argv[1:]:
        usage_exit(args.parser, "--verify needs the backup file")
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
    task_process_refusal("backup")
    config_path, config = load_config(args.dir)
    user, _ = human_identity()
    print(json.dumps(backup.create_backup(state_dir_of(config_path, config), args.out, user=user)))


def cmd_backup_restore(args, file):
    import backup
    from apiserver import userdir
    task_process_refusal("backup restore")
    if not is_tty():
        raise refuse_without_tty("`sentinel backup restore`")
    config_path, config = load_config(args.dir)
    state = state_dir_of(config_path, config)
    info = backup.verify_backup(file)
    busy = backup.running_conflicts(state, userdir.config_dir())
    if busy:
        raise SentinelError("E_LOCKED", "cannot restore while something runs: " + "; ".join(t for t, _ in busy),
                            {"running": [d for _, d in busy]})
    print(f"restore {file} over {state / 'sentinel.db'} (schema {info['schema_version']}, counts {info['counts']})")
    print(f"sha256: {info['sha256']}")
    try:
        typed = input("Type the first 8 characters of the sha256 to confirm: ")
    except (EOFError, KeyboardInterrupt):
        print("\ninput closed; nothing restored", file=sys.stderr)
        sys.exit(1)
    if len(typed.strip()) < 8 or not info["sha256"].startswith(typed.strip().lower()):
        print("the typed value does not match; nothing restored", file=sys.stderr)
        sys.exit(1)
    user, _ = human_identity()
    backup.restore(state, file, user=user)
    print(f"restored {file}; the previous registry is in {state / 'backups'}")


def port_arg(text):
    try:
        port = int(text)
    except ValueError:
        port = 0
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("the port must be from 1024 to 65535")
    return port


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
    sys.exit(run_dashboard(workspace, args.port, args.no_open))


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


def cmd_stats(args):
    config_path, config = load_config(args.dir)
    runs_dir = state_dir_of(config_path, config) / "runs"
    states = [json.loads(p.read_text()) for p in sorted(runs_dir.glob("*/state.json"))]
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
        "tokens_by_stage": stage_tokens, "seconds_by_stage": stage_seconds,
    }, indent=2))


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
    resolve.add_argument("--no-resume", action="store_true", help="record the decision but leave the run parked")
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
    dashboard.add_argument("--port", type=port_arg, help="port to listen on, 1024 to 65535 (default: a free port)")
    dashboard.add_argument("--no-open", action="store_true", help="do not open a browser")
    dashboard.set_defaults(func=cmd_dashboard)

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

    sub.add_parser("stats").set_defaults(func=cmd_stats)

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
    a_verify.add_argument("--db", help="a registry file (default: this workspace)")
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
    backup_cmd.add_argument("--yes", action="store_true", help="accepted for scripts; restore still needs the typed hash prefix")
    backup_cmd.set_defaults(func=cmd_backup, parser=backup_cmd)

    add_passthrough_commands(sub)

    args, extra = parser.parse_known_args()
    if extra and not getattr(args, "passthrough", False):
        parser.error("unrecognized arguments: " + " ".join(extra))
    args.extra = extra
    try:
        args.func(args)
    except SentinelError as err:
        print(f"{err.code}: {err.message}", file=sys.stderr)
        if err.details:
            print(json.dumps(err.details), file=sys.stderr)
        sys.exit(err.exit_code)


if __name__ == "__main__":
    main()
