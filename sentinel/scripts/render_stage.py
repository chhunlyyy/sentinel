#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
CLIENT_ROLES = {"frontend", "mobile"}


def load_config(path):
    return yaml.safe_load(Path(path).read_text())


def load_profile(name):
    path = ROOT / "profiles" / f"{name}.json"
    if not path.exists():
        path = ROOT / "profiles" / "generic.json"
    return json.loads(path.read_text())


def rule_text(name, review=False):
    suffix = ".review.md" if review else ".md"
    path = ROOT / "core" / "rules" / f"{name}{suffix}"
    return path.read_text().strip() if path.exists() else ""


def rules_blocks(config, repo):
    enabled = [k for k, v in (config.get("rules") or {}).items() if v]
    blocks = []
    for name in enabled:
        if name == "no_permanent_frontend_tests" and repo and repo["role"] not in CLIENT_ROLES:
            continue
        text = rule_text(name)
        if text:
            blocks.append(text)
    review = [rule_text(n, review=True) for n in enabled]
    return "\n\n".join(blocks), "\n".join(t for t in review if t)


def repo_commands(repo, profile):
    merged = dict(profile.get("commands", {}))
    merged.update(repo.get("commands") or {})
    return merged


def guidelines_text(config, repo, workspace, stage):
    paths = []
    if repo and repo.get("guidelines"):
        paths.append(repo["guidelines"])
    if stage and (config.get("stage_guidelines") or {}).get(stage):
        paths.append(config["stage_guidelines"][stage])
    parts = []
    for relative in paths:
        file = Path(workspace) / relative
        if file.exists():
            parts.append(file.read_text().strip())
        else:
            sys.stderr.write(f"warning: guidelines file not found: {relative}\n")
    return ("## Project guidelines\n\n" + "\n\n".join(parts)) if parts else ""


def build_context(config, repo, workspace, stage=None):
    state_dir = (config.get("state") or {}).get("dir", ".sentinel")
    qa = config.get("qa") or {}
    profile = load_profile(repo["profile"]) if repo else load_profile("generic")
    commands = repo_commands(repo, profile) if repo else {}
    rules_block, rules_review_block = rules_blocks(config, repo)
    others = [r["id"] for r in config["repos"] if not repo or r["id"] != repo["id"]]
    flat = {
        "workspace": str(workspace),
        "state_dir": state_dir,
        "run_dir": f"{state_dir}/runs/<slug>",
        "shared_dir": f"{state_dir}/shared",
        "repo_id": repo["id"] if repo else "",
        "repo_path": repo["path"] if repo else "",
        "repo_role": repo["role"] if repo else "",
        "repo_profile": repo["profile"] if repo else "",
        "other_repos": ", ".join(others) if others else "none",
        "repo_list": ", ".join(f"{r['id']} ({r['role']})" for r in config["repos"]),
        "profile_mutation_note": profile.get("mutation_note", ""),
        "rules_block": rules_block,
        "rules_review_block": rules_review_block,
        "qa.driver": qa.get("driver", "none"),
        "qa.ports": ", ".join(str(p) for p in qa.get("ports", [])) or "none configured",
        "guidelines_block": guidelines_text(config, repo, workspace, stage),
        "qa.start_commands": "\n".join(f"- {rid}: `{cmd.replace('{scripts}/qa-data', 'sentinel qa-data')}`" for rid, cmd in (qa.get("start_commands") or {}).items()) or "(none configured; work out how to start each service from its README)",
        "tracker.kind": (config.get("tracker") or {}).get("kind", "none"),
    }
    for key in ("build", "lint", "typecheck", "test", "mutate"):
        flat[f"commands.{key}"] = commands.get(key, "") or "(none)"
    return flat


def render(template, context):
    body = FRONT.sub("", template, count=1)

    def sub(match):
        key = match.group(1)
        if key not in context:
            raise KeyError(key)
        return context[key]

    out = PLACEHOLDER.sub(sub, body).strip() + "\n"
    if context.get("guidelines_block"):
        out += "\n" + context["guidelines_block"].strip() + "\n"
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--repo")
    parser.add_argument("--workspace", default=".")
    args = parser.parse_args()

    config = load_config(args.config)
    template = (ROOT / "core" / "stages" / f"{args.stage}.md").read_text()
    front = yaml.safe_load(FRONT.match(template).group(1))
    repo = None
    if front.get("per_repo"):
        if not args.repo:
            sys.exit(f"stage {args.stage} is per-repo; pass --repo <id>")
        matches = [r for r in config["repos"] if r["id"] == args.repo]
        if not matches:
            sys.exit(f"unknown repo id {args.repo}")
        repo = matches[0]
    try:
        sys.stdout.write(render(template, build_context(config, repo, args.workspace, args.stage)))
    except KeyError as missing:
        sys.exit(f"unresolved placeholder: {missing}")


if __name__ == "__main__":
    main()
