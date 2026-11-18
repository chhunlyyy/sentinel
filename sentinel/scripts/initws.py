"""Build and write a workspace config: the part of `sentinel init` that needs no prompts (also used by the dashboard)."""
import json
from pathlib import Path

import yaml

from paths import ROOT

CONFIG_NAME = "sentinel.config.yaml"


def detect_profile(repo_path):
    for profile_file in sorted((ROOT / "profiles").glob("*.json")):
        profile = json.loads(profile_file.read_text())
        if any((repo_path / marker).exists() for marker in profile["detect"]):
            return profile["id"]
    return "generic"


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


def build_config(shape, repos, shared_url=None, local_only=False, seed=None):
    """The config of a new workspace from the template. `seed` is a mapping of top-level keys (agents, providers) to add."""
    config = yaml.safe_load((ROOT / "templates" / CONFIG_NAME).read_text())
    config["shape"] = shape
    config["repos"] = repos
    if local_only:
        config["state"].pop("shared_repo", None)
        config["state"]["shared_mode"] = "local"
        config["state"]["auto_sync_push"] = False
    else:
        config["state"]["shared_repo"] = shared_url
    drivers = {load_profile_driver(p) for p in {r["profile"] for r in repos}}
    config["qa"] = {"driver": "playwright" if "playwright" in drivers else sorted(drivers - {"none"})[0] if drivers - {"none"} else "none",
                    "db_clone": "none", "fixtures": "sanitized"}
    for key, value in (seed or {}).items():
        config[key] = value
    return config


def write_workspace(workspace, config):
    """Write sentinel.config.yaml, the state folders and the .gitignore lines. Returns the config path."""
    workspace = Path(workspace)
    target = workspace / CONFIG_NAME
    target.write_text(yaml.safe_dump(config, sort_keys=False))
    state_dir = workspace / config["state"]["dir"]
    for sub in ("runs", "cache"):
        (state_dir / sub).mkdir(parents=True, exist_ok=True)
    update_gitignore(workspace, config["state"]["dir"])
    return target
