#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
from paths import skills_dir  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
RENDER = ROOT / "scripts" / "render_stage.py"
BEGIN = "<!-- sentinel:begin -->"
END = "<!-- sentinel:end -->"
STAGES = ["coder", "cleaner", "hardener", "repro", "specifier", "reviewer", "qa", "promotion", "docs", "rollout", "retrospective"]

AGENTS_BLOCK = """{begin}
## Sentinel

This project uses Sentinel, a tiered build pipeline (triage, spec, code, clean, harden, review, QA, promotion, release check). Config: `sentinel.config.yaml`.

To implement a feature or fix a bug through Sentinel, first run `sentinel doctor`. If it says the shared repo is missing, stop and ask the requester for the clone URL of their team's private shared repo, then run `sentinel shared set <url>`.

1. Install the `sentinel` command (`uv tool install sentinel` from its repository, or `pipx install`), and run `sentinel sync-adapters --tool agents` once after cloning (it fills `.sentinel/generated/`).
2. Read `.sentinel/generated/orchestrator.md` and follow it. It tells you how to pick the effort tier and run each stage.
3. Stage prompts are in `.sentinel/generated/prompts/<name>.md`. Run a stage with `sentinel stage run --stage <stage> [--repo <id>] --slug <slug> --brief <file>`, or follow the prompt yourself when you are the only agent.
4. Run state lives in `.sentinel/runs/<slug>/state.json`; resume with `sentinel resume <slug>`.
5. Agents never run `sentinel approve` or `sentinel accept`. Those are human decisions made at a terminal.

Rules from `sentinel.config.yaml` apply to everything you write:
{rules}
{end}
"""

RULE_TEXT = {
    "no_code_comments": "- Write no code comments of any kind.",
    "no_em_dashes": "- Never use the em dash character.",
    "no_coauthor_trailer": "- Never add Co-Authored-By or AI attribution lines.",
    "agents_never_run_git": "- Never commit, push, stash, reset, or switch branches.",
    "no_permanent_frontend_tests": "- Client repos keep no permanent test suite; remove any test infrastructure you add.",
}


def render(config_path, stage, repo, workspace):
    cmd = [sys.executable, str(RENDER), "--config", str(config_path), "--stage", stage, "--workspace", str(workspace)]
    if repo:
        cmd += ["--repo", repo]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def stage_meta(stage):
    text = (ROOT / "core" / "stages" / f"{stage}.md").read_text()
    return yaml.safe_load(text.split("---\n")[1])


def upsert_block(path, block):
    existing = path.read_text() if path.exists() else ""
    if BEGIN in existing and END in existing:
        head = existing[: existing.index(BEGIN)]
        tail = existing[existing.index(END) + len(END):].lstrip("\n")
        path.write_text(head + block.rstrip("\n") + "\n" + (("\n" + tail) if tail else ""))
    else:
        path.write_text(existing + ("\n" if existing and not existing.endswith("\n\n") else "") + block)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--tool", default="agents", choices=["agents", "codex", "gemini", "cursor"])
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = yaml.safe_load(config_path.read_text())
    workspace = config_path.parent
    state_dir = (config.get("state") or {}).get("dir", ".sentinel")
    generated = workspace / state_dir / "generated"
    prompts = generated / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)

    for stage in STAGES:
        if stage_meta(stage).get("per_repo"):
            for repo in config["repos"]:
                (prompts / f"{repo['role']}-{stage}.md").write_text(render(config_path, stage, repo["id"], workspace))
        else:
            (prompts / f"{stage}.md").write_text(render(config_path, stage, None, workspace))

    skills = skills_dir()
    orchestrator = (skills / "sentinel" / "SKILL.md").read_text().split("---\n", 2)[2]
    change_map = (skills / "sentinel-change-map" / "SKILL.md").read_text().split("---\n", 2)[2]
    (generated / "orchestrator.md").write_text(orchestrator)
    (generated / "pipeline.md").write_text((skills / "sentinel" / "pipeline.md").read_text())
    (generated / "change-map.md").write_text(change_map)

    rules = "\n".join(RULE_TEXT[k] for k, v in (config.get("rules") or {}).items() if v and k in RULE_TEXT) or "- none enabled"
    block = AGENTS_BLOCK.format(begin=BEGIN, end=END, rules=rules)
    upsert_block(workspace / "AGENTS.md", block)
    written = ["AGENTS.md"]

    if args.tool == "gemini":
        upsert_block(workspace / "GEMINI.md", f"{BEGIN}\n@./AGENTS.md\n{END}\n")
        written.append("GEMINI.md")
    if args.tool == "cursor":
        rules_dir = workspace / ".cursor" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "sentinel.mdc").write_text("---\ndescription: Sentinel pipeline for implementing features and fixes\nalwaysApply: false\n---\n\nSee AGENTS.md (Sentinel section) and .sentinel/generated/orchestrator.md.\n")
        written.append(".cursor/rules/sentinel.mdc")
    print("wrote " + ", ".join(written) + f" and {len(list(prompts.glob('*.md')))} prompts in {generated}")


if __name__ == "__main__":
    main()
