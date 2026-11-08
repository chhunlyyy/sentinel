#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CLI = [sys.executable, str(ROOT / "scripts" / "sentinel.py")]
ENV = {**os.environ, "GIT_AUTHOR_NAME": "selftest", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "selftest", "GIT_COMMITTER_EMAIL": "t@example.com"}
RESULTS = []
FAKE_JWT = "eyJ" + "hbGciOiJIUzI1NiJ9." + "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0." + "abcdefghijk"
FAKE_HOME = "/ho" + "me/someone"
FAKE_MAIL = "a@real-" + "domain.org"


def run(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=ENV)
    return result.returncode, result.stdout + result.stderr


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


def git_repo(path, marker):
    path.mkdir(parents=True)
    (path / marker).write_text("")
    run(["git", "init", "-q", "-b", "main"], cwd=path)
    run(["git", "add", "."], cwd=path)
    run(["git", "commit", "-q", "-m", "init"], cwd=path)


def write_config(ws, mutate):
    path = ws / "sentinel.config.yaml"
    config = yaml.safe_load(path.read_text())
    mutate(config)
    path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="sentinel-selftest-"))
    try:
        ws = tmp / "ws"
        ws.mkdir()
        git_repo(ws / "backend", "build.gradle")
        git_repo(ws / "frontend", "next.config.ts")
        remote = tmp / "shared.git"
        run(["git", "init", "-q", "--bare", "-b", "main", str(remote)])
        seed = tmp / "seed"
        run(["git", "clone", "-q", str(remote), str(seed)])
        (seed / "README.md").write_text("shared\n")
        run(["git", "add", "."], cwd=seed)
        run(["git", "commit", "-q", "-m", "init"], cwd=seed)
        run(["git", "push", "-q", "origin", "main"], cwd=seed)

        print("init and config")
        code, out = run(CLI + ["--dir", str(ws), "init", "--shape", "fullstack", "--non-interactive", "--shared-repo", str(remote)])
        check("init writes sentinel.config.yaml", code == 0 and (ws / "sentinel.config.yaml").exists(), out[-200:])
        config = yaml.safe_load((ws / "sentinel.config.yaml").read_text())
        profiles = [r["profile"] for r in config["repos"]]
        check("init detects stack profiles", profiles == ["spring-gradle", "nextjs"], str(profiles))
        try:
            import jsonschema
            jsonschema.validate(config, json.loads((ROOT / "core/schema/config.schema.json").read_text()))
            check("config validates against the schema", True)
        except ImportError:
            check("config validates against the schema (skipped, jsonschema not installed)", True)
        write_config(ws, lambda c: c["state"].update({"shared_repo": str(remote)}))
        code, out = run(CLI + ["--dir", str(ws), "doctor"])
        problems = [l for l in out.splitlines() if l.startswith("- ") and "runner CLI not installed" not in l and "command not found" not in l]
        check("doctor reports no config problems", not problems, "; ".join(problems))

        print("shared repo is required")
        bare = tmp / "no-shared"
        bare.mkdir()
        git_repo(bare / "app", "package.json")
        code, out = run(CLI + ["--dir", str(bare), "init", "--shape", "single", "--non-interactive"])
        check("init refuses to run without a shared repo", code != 0 and "shared repo is required" in out and not (bare / "sentinel.config.yaml").exists(), out[-160:])
        code, out = run(CLI + ["--dir", str(bare), "init", "--shape", "single", "--non-interactive", "--shared-repo", "not a url"])
        check("init rejects a value that is not a git URL", code != 0 and not (bare / "sentinel.config.yaml").exists(), out[-160:])
        empty = tmp / "empty.git"
        run(["git", "init", "-q", "--bare", "-b", "main", str(empty)])
        ews = tmp / "ws-empty"
        ews.mkdir()
        git_repo(ews / "app", "package.json")
        code, out = run(CLI + ["--dir", str(ews), "init", "--shape", "single", "--non-interactive", "--shared-repo", str(empty)])
        shared_dir = ews / ".sentinel/shared"
        committed = run(["git", "log", "--oneline"], cwd=shared_dir)[1].strip() if shared_dir.exists() else ""
        check("an empty shared repo is scaffolded with starter files", code == 0 and (shared_dir / "invariants.md").exists() and (shared_dir / "specs/index.json").exists() and bool(committed), out[-200:])
        check("the scaffold is not pushed without being asked", run(["git", "ls-remote", str(empty)])[1].strip() == "")
        check("the scaffold contains no workflow file (pushing one needs extra token scope)", not (shared_dir / ".github").exists())
        code, out = run(CLI + ["--dir", str(ews), "shared", "ci"])
        check("shared ci writes the optional workflow", code == 0 and (shared_dir / ".github/workflows/sentinel-shared.yml").exists() and "sentinel shared-check" in (shared_dir / ".github/workflows/sentinel-shared.yml").read_text(), out[-160:])
        uws = tmp / "ws-unreachable"
        uws.mkdir()
        git_repo(uws / "app", "package.json")
        code, out = run(CLI + ["--dir", str(uws), "init", "--shape", "single", "--non-interactive", "--shared-repo", str(tmp / "missing.git")])
        check("init still saves the config when the shared repo is unreachable, with a warning", code == 0 and "could not reach" in out and (uws / "sentinel.config.yaml").exists(), out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "doctor"])
        check("doctor fails until the shared repo is cloned", code != 0 and "not cloned" in out, out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "run", "new", "blocked", "--tier", "2"])
        check("run new refuses until the shared repo is cloned", code != 0 and "sync pull" in out, out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "shared", "set", str(remote)])
        check("shared set connects the workspace", code == 0 and (uws / ".sentinel/shared/.git").exists(), out[-200:])
        code, out = run(CLI + ["--dir", str(uws), "run", "new", "unblocked", "--tier", "2"])
        check("run new works once the shared repo is cloned", code == 0, out[-200:])
        run(CLI + ["--dir", str(uws), "run", "finish", "unblocked"])

        print("skills")
        sys.path.insert(0, str(ROOT / "scripts"))
        from paths import skills_dir
        skill_folders = sorted(p for p in skills_dir().iterdir() if p.is_dir())
        names = [p.name for p in skill_folders]
        check("the expected skills exist", {"sentinel", "sentinel-setup", "sentinel-resume", "sentinel-status", "sentinel-sync", "sentinel-change-map"} <= set(names), ", ".join(names))
        frontmatter_bad, path_bad, tool_bad, command_bad = [], [], [], []
        seen = set()
        for folder in skill_folders:
            text = (folder / "SKILL.md").read_text()
            m = re.match(r"---\nname: (\S+)\ndescription: (.+)\n---\n", text)
            if not m or m.group(1) != folder.name or ": " in m.group(2):
                frontmatter_bad.append(folder.name)
            if "/home/" in text or "Desktop/" in text or "{{" in text:
                path_bad.append(folder.name)
            if any(word in text for word in ("AskUserQuestion", "SendMessage", "subagent_type", "headroom")):
                tool_bad.append(folder.name)
            for first, second in re.findall(r"`sentinel ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?", text):
                key = (first, second if first in ("run", "sync", "spec", "metrics", "shared", "stage", "change-map") else "")
                if key in seen:
                    continue
                seen.add(key)
                args = [key[0]] + ([key[1]] if key[1] else []) + ["--help"]
                code, out = run(CLI + ["--dir", str(ws)] + args)
                if code != 0:
                    command_bad.append(" ".join(args))
        check("every skill has valid frontmatter (name matches the folder, description present)", not frontmatter_bad, ", ".join(frontmatter_bad))
        check("no skill contains a machine path or an unrendered placeholder", not path_bad, ", ".join(path_bad))
        check("no skill depends on one tool's private mechanics", not tool_bad, ", ".join(tool_bad))
        check("every sentinel command a skill mentions exists", not command_bad, "; ".join(command_bad))
        check("the pipeline contract ships with the main skill", (skills_dir() / "sentinel" / "pipeline.md").exists())
        main_skill = (skills_dir() / "sentinel" / "SKILL.md").read_text()
        check("the main skill makes isolated stages the rule and names how each tool does it", all(w in main_skill for w in ("invoke_subagent", "Agent tool", "sentinel stage run", "--runner", "--session S=subagent", "Inline, only if neither exists")), "")
        from run_stage import DEFAULT_RUNNERS
        check("the built-in agy runner can edit headlessly without the dangerous flag", "accept-edits" in DEFAULT_RUNNERS["agy"]["args"] and not DEFAULT_RUNNERS["agy"].get("unsafe_skip_permissions"), str(DEFAULT_RUNNERS["agy"]))
        code, out = run(CLI + ["--dir", str(ws), "doctor"])
        check("a config without routing or runners passes doctor", "runner" not in out or code == 0, out[-200:])

        print("prompts and adapters")
        shapes = {"single": 1, "fullstack": 2, "fullstack-mobile": 3}
        for shape, count in shapes.items():
            sws = tmp / f"shape-{shape}"
            sws.mkdir()
            for i in range(count):
                git_repo(sws / f"r{i}", "package.json")
            sets = []
            ids = {"single": ["app"], "fullstack": ["backend", "frontend"], "fullstack-mobile": ["backend", "frontend", "mobile"]}[shape]
            for i, rid in enumerate(ids):
                sets += ["--set", f"{rid}.path=./r{i}"]
            run(CLI + ["--dir", str(sws), "init", "--shape", shape, "--non-interactive", "--shared-repo", str(remote)] + sets)
            bad = []
            for stage in (ROOT / "core" / "stages").glob("*.md"):
                meta = yaml.safe_load(stage.read_text().split("---\n")[1])
                repos = ids if meta.get("per_repo") else [None]
                for rid in repos:
                    cmd = CLI + ["--dir", str(sws), "stage", "render", "--stage", stage.stem]
                    if rid:
                        cmd += ["--repo", rid]
                    c, o = run(cmd)
                    if c != 0 or "{{" in o:
                        bad.append(f"{stage.stem}/{rid}")
            check(f"all stage prompts render for shape {shape}", not bad, ", ".join(bad[:4]))
        for tool in ("claude", "agents", "gemini", "cursor"):
            code, out = run(CLI + ["--dir", str(ws), "sync-adapters", "--tool", tool])
            check(f"sync-adapters --tool {tool}", code == 0, out[-200:])
        agents = list((ws / ".claude" / "agents").glob("*.md"))
        ok = bool(agents) and all(re.match(r"---\nname: \S+\ndescription: .+\ntools: .+\nmodel: \S+\n---\n", a.read_text()) for a in agents)
        check("generated Claude agents have valid frontmatter", ok, f"{len(agents)} agents")
        skill = (ws / ".claude/skills/sentinel/SKILL.md").read_text()
        check("generated skill has no machine path or unrendered placeholder", "/home/" not in skill and "{{" not in skill and (ws / ".claude/skills/sentinel/pipeline.md").exists())
        check("generated skill uses the sentinel command, not file paths", "sentinel stage run" in skill and "sentinel release-check" in skill and ".py" not in skill)
        code, out = run(CLI + ["--version"])
        check("--version prints the packaged version", code == 0 and out.strip() == (ROOT / "VERSION").read_text().strip(), out.strip())
        before = (ws / "AGENTS.md").read_text()
        run(CLI + ["--dir", str(ws), "sync-adapters", "--tool", "agents"])
        check("AGENTS.md block is idempotent", (ws / "AGENTS.md").read_text() == before)
        check("AGENTS.md block does not depend on a checkout path", "SENTINEL_HOME" not in before and "sentinel stage run" in before)

        print("runs, locks and shared repo")
        code, out = run(CLI + ["--dir", str(ws), "sync", "pull"])
        check("sync pull clones the shared repo", code == 0 and (ws / ".sentinel/shared/.git").exists(), out[-200:])
        code, _ = run(CLI + ["--dir", str(ws), "run", "new", "demo", "--tier", "2"])
        check("run new takes a lock", code == 0)
        code, out = run(CLI + ["--dir", str(ws), "run", "new", "demo", "--tier", "2"])
        check("a second run with the same slug is refused", code != 0)
        run(CLI + ["--dir", str(ws), "run", "update", "demo", "--stage", "repro"])
        code, out = run(CLI + ["--dir", str(ws), "resume", "demo"])
        check("resume points at the next stage", code == 0 and json.loads(out)["next"] == "coder", out[-150:])
        code, out = run(CLI + ["--dir", str(ws), "run", "update", "demo", "--tier", "1"])
        check("a tier can only be raised", code != 0)
        run(CLI + ["--dir", str(ws), "run", "update", "demo", "--session", "reviewer=inline"])
        run(CLI + ["--dir", str(ws), "run", "update", "demo", "--session", "coder=subagent"])
        code, out = run(CLI + ["--dir", str(ws), "stats"])
        try:
            isolation = json.loads(out)["stage_isolation"]
        except Exception:
            isolation = {}
        check("stats shows how many stages ran inline, headless or as subagents", code == 0 and isolation.get("inline") == 1 and isolation.get("subagent") == 1, str(isolation))
        ws2 = tmp / "ws2"
        ws2.mkdir()
        git_repo(ws2 / "backend", "build.gradle")
        git_repo(ws2 / "frontend", "next.config.ts")
        run(CLI + ["--dir", str(ws2), "init", "--shape", "fullstack", "--non-interactive", "--shared-repo", str(remote)])
        write_config(ws2, lambda c: c["state"].update({"shared_repo": str(remote)}))
        run(CLI + ["--dir", str(ws2), "sync", "pull"])
        code, _ = run(CLI + ["--dir", str(ws), "run", "new", "lockdemo", "--tier", "2"])
        code2, out2 = run(CLI + ["--dir", str(ws2), "run", "new", "lockdemo", "--tier", "2"])
        check("a teammate's workspace cannot take a slug that is locked", code == 0 and code2 != 0 and "locked" in out2, out2[-160:])
        run(CLI + ["--dir", str(ws), "run", "finish", "lockdemo"])
        code3, out3 = run(CLI + ["--dir", str(ws2), "run", "new", "lockdemo", "--tier", "2"])
        check("the teammate can take the slug after it is released", code3 == 0, out3[-160:])
        run(CLI + ["--dir", str(ws2), "run", "finish", "lockdemo"])

        print("runner and write boundary")
        fake = tmp / "fake.sh"
        fake.write_text("#!/usr/bin/env bash\necho made > ok.txt\necho done\n")
        stray = tmp / "stray.sh"
        stray.write_text("#!/usr/bin/env bash\necho x > ../frontend/stray.txt\necho wrote elsewhere\n")
        committer = tmp / "commit.sh"
        committer.write_text("#!/usr/bin/env bash\ngit commit -q --allow-empty -m sneaky\necho committed\n")
        for f in (fake, stray, committer):
            f.chmod(0o755)
        write_config(ws, lambda c: c.setdefault("runners", {}).update({"fake": {"command": str(fake)}, "stray": {"command": str(stray)}, "commit": {"command": str(committer)}}))
        stage_cmd = CLI + ["--dir", str(ws), "stage", "run", "--slug", "demo", "--stage", "coder", "--repo", "backend"]
        code, out = run(stage_cmd + ["--runner", "fake"])
        check("a well-behaved stage passes", code == 0 and (ws / "backend/ok.txt").exists(), out[-200:])
        code, out = run(stage_cmd + ["--runner", "stray"])
        check("writing into another repo is caught (exit 3)", code == 3, f"exit {code}")
        (ws / "frontend/stray.txt").unlink(missing_ok=True)
        code, out = run(stage_cmd + ["--runner", "commit"])
        check("a commit by a stage is caught (exit 3)", code == 3, f"exit {code}")
        (ws / "backend/ok.txt").unlink(missing_ok=True)
        code, out = run(CLI + ["--dir", str(ws), "run", "finish", "demo"])
        locks = run(["git", "ls-remote", str(remote)])[1]
        check("run finish releases the lock", code == 0 and "refs/sentinel/locks/demo" not in locks, locks[-200:])

        print("release check and scrubber")
        rc = CLI + ["--dir", str(ws), "release-check", "--quick", "--repo", "frontend"]
        (ws / "frontend/app.ts").write_text("export const a = 1;\n")
        code, out = run(rc)
        check("release check passes on a clean change", code == 0, out[-200:])
        (ws / "frontend/app.ts").write_text('console.log("debug");\nexport const t = "' + FAKE_JWT + '";\n')
        code, out = run(rc)
        check("release check fails on debug output and a token", code == 1 and "debug output" in out and "secret" in out, out[-250:])
        sample = tmp / "log.txt"
        sample.write_text(f"token {FAKE_JWT} at {FAKE_HOME}/x\nmail {FAKE_MAIL}\n")
        run([sys.executable, str(ROOT / "scripts/scrub.py"), str(sample), "--workspace", str(ws)])
        cleaned = sample.read_text()
        check("scrubber removes tokens, home paths and emails", "eyJ" not in cleaned and FAKE_HOME not in cleaned and "real-domain" not in cleaned, cleaned)

        print("change map")
        code, out = run(CLI + ["--dir", str(ws), "change-map", "collect", "--out", str(tmp / "changes.json")])
        check("change map collects the changed files", code == 0 and json.loads((tmp / "changes.json").read_text())["nodes"], out[-200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
