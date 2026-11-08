#!/usr/bin/env python3
import argparse
import getpass
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
CONFIG_NAME = "sentinel.config.yaml"

TIER_STAGES = {
    1: ["coder"],
    2: ["repro", "coder", "release_check", "metrics", "changelog"],
    3: ["specifier", "retriage", "coder", "cleaner", "reviewer", "qa", "promotion", "release_check", "docs", "metrics"],
    4: ["specifier", "retriage", "coder", "cleaner", "hardener", "reviewer", "qa", "promotion", "release_check", "docs", "rollout", "retrospective", "metrics"],
}


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
        url = input("shared repo URL: ").strip()
        if looks_like_git_url(url):
            return url
        print("that does not look like a git URL (https://..., git@host:..., ssh://..., or a path)")


def connect_shared(config_path, config):
    from shared import Shared, verify_remote
    shared = Shared(config_path.parent, config)
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
    if not shared_url and interactive:
        shared_url = ask_shared_url()
    if not shared_url:
        sys.exit("a shared repo is required: pass --shared-repo <url> (an empty private git repository your team owns)")
    if not looks_like_git_url(shared_url):
        sys.exit(f"--shared-repo does not look like a git URL: {shared_url}")
    overrides = dict(item.split("=", 1) for item in (args.set or []))
    repos = build_repos(shape, workspace, interactive, overrides)
    config = yaml.safe_load((ROOT / "templates" / CONFIG_NAME).read_text())
    config["shape"] = shape
    config["repos"] = repos
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


def cmd_doctor(args):
    config_path, config = load_config(args.dir)
    workspace = config_path.parent
    problems = []
    try:
        import jsonschema
        schema = load_json("core/schema/config.schema.json")
        for error in jsonschema.Draft202012Validator(schema).iter_errors(config):
            problems.append(f"schema: {'/'.join(map(str, error.path))}: {error.message}")
    except ImportError:
        print("note: jsonschema not installed, schema check skipped")
    for tool in ("git", "python3"):
        if not shutil.which(tool):
            problems.append(f"missing tool: {tool}")
    for repo in config["repos"]:
        path = workspace / repo["path"]
        if not path.exists():
            problems.append(f"repo path missing: {repo['id']} -> {path}")
        elif not (path / ".git").exists():
            problems.append(f"not a git repo: {repo['id']}")
        profile = json.loads((ROOT / "profiles" / f"{repo['profile']}.json").read_text()) if (ROOT / "profiles" / f"{repo['profile']}.json").exists() else None
        if profile is None:
            problems.append(f"unknown profile for {repo['id']}: {repo['profile']}")
            continue
        commands = {**profile["commands"], **(repo.get("commands") or {})}
        for key, command in commands.items():
            if command and not shutil.which(command.split()[0]) and not command.startswith("./") and not command.startswith("npm") and not command.startswith("npx"):
                problems.append(f"{repo['id']}: {key} command not found: {command.split()[0]}")
    for stage, route in (config.get("routing") or {}).items():
        from run_stage import all_runners
        runner = all_runners(config).get(route["runner"])
        if not runner:
            problems.append(f"routing {stage}: runner not defined: {route['runner']}")
        elif not shutil.which(runner["command"].split()[0]):
            problems.append(f"runner CLI not installed: {runner['command'].split()[0]} (stage {stage})")
    shared_url = (config.get("state") or {}).get("shared_repo")
    if not shared_url:
        problems.append("state.shared_repo is required: ask your team for the URL of its private shared repo and run `sentinel shared set <url>`")
    elif not (state_dir_of(config_path, config) / "shared" / ".git").exists():
        problems.append(f"the shared repo ({shared_url}) is not cloned: run `sentinel sync pull`")
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
    print(f"agents written to {out}; skills written to .claude/skills: {', '.join(installed)}")


def state_dir_of(config_path, config):
    return config_path.parent / (config.get("state") or {}).get("dir", ".sentinel")


def run_dir(config_path, config, slug):
    return state_dir_of(config_path, config) / "runs" / slug


def head_sha(path):
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True)
    return result.stdout.strip() or None


def cmd_run_new(args):
    config_path, config = load_config(args.dir)
    directory = run_dir(config_path, config, args.slug)
    if (directory / "state.json").exists():
        sys.exit(f"run {args.slug} already exists; use `sentinel resume {args.slug}`")
    require_shared(config_path, config)
    from shared import Shared
    Shared(config_path.parent, config).acquire(args.slug, getpass.getuser())
    directory.mkdir(parents=True, exist_ok=True)
    state = {
        "slug": args.slug,
        "tier": args.tier,
        "initial_tier": args.tier,
        "stages": TIER_STAGES[args.tier],
        "completed": [],
        "sessions": {},
        "rounds": {"review": 0, "qa": 0, "release_check": 0},
        "baseline": {r["id"]: head_sha(config_path.parent / r["path"]) for r in config["repos"]},
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (directory / "state.json").write_text(json.dumps(state, indent=2))
    print(json.dumps(state, indent=2))


def read_state(config_path, config, slug):
    path = run_dir(config_path, config, slug) / "state.json"
    if not path.exists():
        sys.exit(f"no run named {slug}")
    return path, json.loads(path.read_text())


def cmd_run_update(args):
    config_path, config = load_config(args.dir)
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


def cmd_run_finish(args):
    from shared import Shared
    config_path, config = load_config(args.dir)
    path, state = read_state(config_path, config, args.slug)
    state["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    state["outcome"] = args.outcome
    path.write_text(json.dumps(state, indent=2))
    Shared(config_path.parent, config).release(args.slug)
    print(f"run {args.slug} {args.outcome}; lock released")


def cmd_sync(args):
    from shared import Shared
    import scrub
    config_path, config = load_config(args.dir)
    shared = Shared(config_path.parent, config)
    if args.sync_cmd == "pull":
        shared.pull()
        return
    if not args.yes:
        sys.exit("push needs --yes after the requester has approved it")
    workspace = config_path.parent
    scrubber = scrub.Scrubber(workspace, scrub.env_values(workspace))
    run_directory = run_dir(config_path, config, args.slug)
    shared.push(args.slug, run_directory, lambda: scrub.check_paths([shared.dir], scrubber))


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
    init.add_argument("--shared-repo", help="clone URL of your team's private shared repo (required; asked for when omitted in interactive mode)")
    init.set_defaults(func=cmd_init)

    sub.add_parser("doctor").set_defaults(func=cmd_doctor)

    sync = sub.add_parser("sync-adapters")
    sync.add_argument("--tool", default="claude", choices=["claude", "agents", "codex", "gemini", "cursor"])
    sync.add_argument("--out")
    sync.set_defaults(func=cmd_sync_adapters)

    run = sub.add_parser("run")
    run_sub = run.add_subparsers(dest="run_cmd", required=True)
    new = run_sub.add_parser("new")
    new.add_argument("slug")
    new.add_argument("--tier", type=int, choices=[1, 2, 3, 4], required=True)
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

    sync = sub.add_parser("sync")
    sync_sub = sync.add_subparsers(dest="sync_cmd", required=True)
    sync_sub.add_parser("pull").set_defaults(func=cmd_sync)
    push = sync_sub.add_parser("push")
    push.add_argument("slug")
    push.add_argument("--yes", action="store_true")
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

    add_passthrough_commands(sub)

    args, extra = parser.parse_known_args()
    if extra and not getattr(args, "passthrough", False):
        parser.error("unrecognized arguments: " + " ".join(extra))
    args.extra = extra
    args.func(args)


if __name__ == "__main__":
    main()
