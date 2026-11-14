#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
RENDER = ROOT / "scripts" / "render_stage.py"
FRONT = "---\n"

DESCRIPTIONS = {
    "coder": "Implements and answers questions about repo {repo} ({role}). Use for code changes in that repo only.",
    "cleaner": "Refactors recently changed code in repo {repo} for readability without changing behavior.",
    "hardener": "Runs mutation testing on recently changed code in repo {repo} and plugs test gaps.",
    "repro": "Writes a failing test or exact repro steps for a bug in repo {repo}, without fixing it.",
    "specifier": "Turns a request into one increment-scoped spec with Gherkin, QA procedure, and contract note. Never writes source.",
    "reviewer": "Read-only skeptical review of the increment against its spec, invariants, correctness, and security.",
    "qa": "Runs the QA procedure against the running system on throwaway data and reports triaged pass or fail.",
    "promotion": "Moves passing QA checks into the shared regression suite.",
    "docs": "Updates docs and changelog and drafts the PR text.",
    "rollout": "Collects deploy-time changes (env, flags, migrations, order) from the increment.",
    "retrospective": "Proposes new project-wide invariants from the run.",
}

TOOLS = {
    "coder": "Read, Grep, Glob, Bash, Edit, Write",
    "repro": "Read, Grep, Glob, Bash, Edit, Write",
    "cleaner": "Read, Grep, Glob, Bash, Edit",
    "hardener": "Read, Grep, Glob, Bash, Edit",
    "specifier": "Read, Grep, Glob, Write",
    "reviewer": "Read, Grep, Glob, Bash",
    "qa": "Read, Grep, Glob, Bash, Write",
    "promotion": "Read, Grep, Glob, Bash, Edit, Write",
    "docs": "Read, Grep, Glob, Edit, Write",
    "rollout": "Read, Grep, Glob, Write",
    "retrospective": "Read, Grep, Glob, Write",
}


def stage_meta(stage):
    text = (ROOT / "core" / "stages" / f"{stage}.md").read_text()
    return yaml.safe_load(text.split("---\n")[1])


def render(config_path, stage, repo_id, workspace):
    cmd = [sys.executable, str(RENDER), "--config", config_path, "--stage", stage, "--workspace", workspace]
    if repo_id:
        cmd += ["--repo", repo_id]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def model_for(config, stage):
    if config.get("single_model", True) is not False:
        return "inherit"
    route = (config.get("routing") or {}).get(stage) or {}
    return route.get("model", "inherit")


HUMAN_ONLY = "\n\nNever run `sentinel approve` or `sentinel accept`. Those are human decisions made at a terminal.\n"


def agent_file(name, description, tools, model, body):
    return f"---\nname: {name}\ndescription: {description}\ntools: {tools}\nmodel: {model}\n---\n\n{body}{HUMAN_ONLY}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--workspace", default=".")
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for stage in DESCRIPTIONS:
        meta = stage_meta(stage)
        targets = config["repos"] if meta.get("per_repo") else [None]
        for repo in targets:
            repo_id = repo["id"] if repo else None
            name = f"{repo['role']}-{stage}" if repo else f"{stage}-agent"
            body = render(args.config, stage, repo_id, args.workspace)
            description = DESCRIPTIONS[stage].format(repo=repo_id, role=repo["role"] if repo else "")
            path = out / f"{name}.md"
            path.write_text(agent_file(name, description, TOOLS[stage], model_for(config, stage), body))
            written.append(path.name)
    for name in written:
        print(name)


if __name__ == "__main__":
    main()
