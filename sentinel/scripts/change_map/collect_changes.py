#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
MAX_DIFF_LINES = 600
GENERIC_NAMES = {"route.ts", "index.ts", "index.tsx", "page.tsx", "layout.tsx", "loading.tsx", "error.tsx", "main.dart", "__init__.py"}
SECRET_NAME = re.compile(r"(^|/)(\.env(\..*)?|.*\.(pem|key|p12|pfx|jks|keystore)|id_rsa.*|.*credentials.*|.*secret.*)$", re.I)
JAVA_TOKEN = re.compile(r"\b[A-Z][A-Za-z0-9_]*\b")
TS_IMPORT = re.compile(r"(?:import|export)\s+(?:type\s+)?([\s\S]*?)\s+from\s+[\"']([^\"']+)[\"']")
TS_EXPORT = re.compile(r"export\s+(?:default\s+)?(?:async\s+)?(?:function|const|let|class|type|interface|enum)\s+(\w+)")
DART_IMPORT = re.compile(r"^\s*(?:import|export)\s+['\"]([^'\"]+)['\"]", re.M)
PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
SQL_TABLE = re.compile(r"(?:ALTER|CREATE)\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?", re.I)
JPA_TABLE = re.compile(r"@Table\s*\(\s*name\s*=\s*\"(\w+)\"")
CLASS_MAPPING = re.compile(r"@RequestMapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?\{?\s*\"([^\"]*)\"")
METHOD_MAPPING = re.compile(r"@(Get|Post|Put|Patch|Delete)Mapping\s*(?:\(\s*(?:value\s*=\s*|path\s*=\s*)?\{?\s*\"([^\"]*)\")?")
CODE_EXT = {".java", ".kt", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".dart", ".py"}


def git(repo_dir, *args):
    result = subprocess.run(["git", "-C", str(repo_dir), *args], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed in {repo_dir}: {result.stderr.strip()}")
    return result.stdout


def load_profile(name):
    path = ROOT / "profiles" / f"{name}.json"
    if not path.exists():
        path = ROOT / "profiles" / "generic.json"
    return json.loads(path.read_text())


def lane_of(path, lanes):
    for lane in lanes:
        if any(re.search(pattern, path) for pattern in lane["match"]):
            return lane["id"]
    return "config"


def label_of(path):
    name = os.path.basename(path)
    if name in GENERIC_NAMES:
        return f"{os.path.basename(os.path.dirname(path))}/{name}"
    return name


def parse_diff(text):
    hunks, current = [], None
    for line in text.splitlines():
        if line.startswith("@@"):
            current = {"header": line, "lines": []}
            hunks.append(current)
        elif current is not None and not line.startswith("\\"):
            kind = {"+": "add", "-": "del"}.get(line[:1], "ctx")
            current["lines"].append([kind, line[1:] if line[:1] in "+- " else line])
    return hunks


def cap(hunks):
    total, kept = 0, []
    for hunk in hunks:
        room = MAX_DIFF_LINES - total
        if room <= 0:
            return kept, True
        if len(hunk["lines"]) > room:
            kept.append({"header": hunk["header"], "lines": hunk["lines"][:room]})
            return kept, True
        kept.append(hunk)
        total += len(hunk["lines"])
    return kept, False


def read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return None


def barrel_exports(content):
    lines = [l.strip() for l in (content or "").splitlines() if l.strip()]
    if not lines or not all(l.startswith("export") and " from " in l for l in lines):
        return None
    names = []
    for line in lines:
        inner = re.search(r"\{([^}]*)\}", line)
        if inner:
            names += [p.strip().split(" as ")[-1].replace("type ", "") for p in inner.group(1).split(",") if p.strip()]
        else:
            names.append("* from " + line.split(" from ")[-1].strip(" ;\"'"))
    return names


class Repo:
    def __init__(self, workspace, entry):
        self.id = entry["id"]
        self.dir = (workspace / entry["path"]).resolve()
        self.profile = load_profile(entry["profile"])
        self.lanes = self.profile["lanes"]
        self.http_server = self.profile.get("http_server")


def make_node(repo, path, status, content, hunks=(), added=0, removed=0, truncated=False, renamed_from=None, binary=False):
    node = {
        "id": f"{repo.id}:{path}", "repo": repo.id, "path": path, "name": os.path.basename(path), "label": label_of(path),
        "lane": lane_of(path, repo.lanes), "status": status, "renamed_from": renamed_from, "added": added,
        "removed": removed, "hunks": list(hunks), "truncated": truncated, "binary": binary, "_content": content or "",
    }
    exports = barrel_exports(content) if path.endswith((".ts", ".tsx")) else None
    if exports:
        node["barrel"] = exports
    return node


def collect_repo(repo, base):
    files = {}
    for line in git(repo.dir, "diff", "--name-status", "-M", base).splitlines():
        parts = line.split("\t")
        status = parts[0][0]
        files[parts[-1]] = {"status": {"A": "added", "D": "deleted", "R": "renamed"}.get(status, "modified"),
                            "renamed_from": parts[1] if status == "R" else None}
    for path in git(repo.dir, "ls-files", "--others", "--exclude-standard").splitlines():
        files.setdefault(path, {"status": "added", "renamed_from": None, "untracked": True})
    numstat = {}
    for line in git(repo.dir, "diff", "--numstat", "-M", base).splitlines():
        added, removed, path = line.split("\t", 2)
        if " => " in path:
            path = re.sub(r"\{[^{}]* => ([^{}]*)\}", r"\1", path).replace("//", "/").split(" => ")[-1]
        numstat[path] = (added, removed)
    out = []
    for path, info in sorted(files.items()):
        content = read(repo.dir / path) if info["status"] != "deleted" else None
        if info.get("untracked"):
            if content is None:
                out.append(make_node(repo, path, "added", None, binary=True))
                continue
            lines = content.splitlines()
            hunks = [{"header": f"@@ new file, {len(lines)} lines @@", "lines": [["add", l] for l in lines]}]
            added, removed, binary = len(lines), 0, False
        else:
            hunks = parse_diff(git(repo.dir, "diff", "-M", "-U3", base, "--", path))
            raw = numstat.get(path, ("0", "0"))
            added = int(raw[0]) if raw[0].isdigit() else 0
            removed = int(raw[1]) if raw[1].isdigit() else 0
            binary = raw[0] == "-"
        hunks, truncated = cap(hunks)
        out.append(make_node(repo, path, info["status"], content, hunks, added, removed, truncated, info["renamed_from"], binary))
    return out


def walk(base_dir, predicate):
    found = {}
    for directory, dirs, names in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "build", ".dart_tool", "__pycache__") and not d.startswith(".")]
        for name in names:
            rel = os.path.relpath(os.path.join(directory, name), base_dir)
            if predicate(rel):
                found[rel] = os.path.join(directory, name)
    return found


def path_regex(url, param):
    pieces = re.split(param, url)
    body = "".join(r"(?:\$\{[^}]+\}|[^/\"'`?\s]+)" if re.fullmatch(param, p) else re.escape(p) for p in pieces)
    return re.compile(r"(?:(?<=[\"'`}])|(?<=/api)|(?<=/v1))" + body + r"(?![\w/-])")


class Graph:
    def __init__(self, repos, nodes):
        self.repos = {r.id: r for r in repos}
        self.nodes = {n["id"]: n for n in nodes}
        self.ghosts = {}
        self.edges = {}

    def all(self):
        return list(self.nodes.values()) + list(self.ghosts.values())

    def known(self, node_id):
        return node_id in self.nodes or node_id in self.ghosts

    def ensure(self, repo_id, rel):
        node_id = f"{repo_id}:{rel}"
        if not self.known(node_id):
            repo = self.repos[repo_id]
            self.ghosts[node_id] = make_node(repo, rel, "context", read(repo.dir / rel))
        return node_id

    def add(self, src, dst, kind, label=None):
        if src == dst:
            return
        labels = self.edges.setdefault((src, dst, kind), set())
        if label:
            labels.add(label)


def link_http(graph):
    endpoints = []
    for repo in graph.repos.values():
        if repo.http_server != "spring":
            continue
        for rel, full in walk(repo.dir / "src/main/java", lambda r: r.endswith("Controller.java")).items():
            rel = os.path.join("src/main/java", rel)
            content = read(os.path.join(repo.dir, rel)) or ""
            base_match = CLASS_MAPPING.search(content)
            base = base_match.group(1) if base_match else ""
            for verb, sub in METHOD_MAPPING.findall(content):
                url = "/" + "/".join(p for p in (base + "/" + (sub or "")).split("/") if p)
                if url != "/":
                    endpoints.append((repo.id, rel, f"{verb.upper()} {url}", path_regex(url, r"(\{[^}]+\})")))
    for node in list(graph.nodes.values()):
        if node["lane"] == "tests":
            continue
        for repo_id, rel, label, pattern in endpoints:
            if node["repo"] != repo_id and pattern.search(node["_content"]):
                graph.add(node["id"], graph.ensure(repo_id, rel), "http", label)


def link_tables(graph):
    for repo in graph.repos.values():
        if repo.http_server != "spring":
            continue
        entities = {}
        for rel, full in walk(repo.dir / "src/main/java", lambda r: r.endswith(".java")).items():
            for table in JPA_TABLE.findall(read(full) or ""):
                entities.setdefault(table, []).append(os.path.join("src/main/java", rel))
        for node in list(graph.nodes.values()):
            if node["repo"] != repo.id or node["lane"] != "database":
                continue
            text = node["_content"] or "\n".join(l[1] for h in node["hunks"] for l in h["lines"])
            for table in set(SQL_TABLE.findall(text)):
                for rel in entities.get(table, []):
                    graph.add(graph.ensure(repo.id, rel), node["id"], "table", table)


def resolve_ts(source_path, spec, known):
    if spec.startswith("@/"):
        base = "src/" + spec[2:]
    elif spec.startswith("."):
        base = os.path.normpath(os.path.join(os.path.dirname(source_path), spec))
    else:
        return None
    for candidate in (base, base + ".ts", base + ".tsx", base + ".js", base + ".jsx", base + ".json", base + "/index.ts", base + "/index.tsx"):
        if candidate in known:
            return candidate
    return None


def link_code(graph):
    every = graph.all()
    by_repo = {}
    for node in every:
        by_repo.setdefault(node["repo"], []).append(node)
    for repo_id, nodes in by_repo.items():
        paths = {n["path"] for n in nodes}
        classes = {n["name"].rsplit(".", 1)[0]: n["id"] for n in nodes if n["name"].endswith((".java", ".kt"))}
        exported = {}
        for node in nodes:
            if node["name"].endswith((".ts", ".tsx", ".js", ".jsx")):
                for name in TS_EXPORT.findall(node["_content"]):
                    exported.setdefault(name, []).append(node["id"])
        dart_package = None
        pubspec = graph.repos[repo_id].dir / "pubspec.yaml"
        if pubspec.exists():
            match = re.search(r"^name:\s*(\S+)", pubspec.read_text(), re.M)
            dart_package = match.group(1) if match else None
        for node in nodes:
            ext = os.path.splitext(node["name"])[1]
            if ext in (".java", ".kt"):
                own = node["name"].rsplit(".", 1)[0]
                for token in set(JAVA_TOKEN.findall(node["_content"])):
                    if token in classes and token != own:
                        graph.add(node["id"], classes[token], "test" if node["lane"] == "tests" else "uses")
            elif ext in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
                for names, spec in TS_IMPORT.findall(node["_content"]):
                    target = resolve_ts(node["path"], spec, paths)
                    if target and target.endswith(".json"):
                        graph.add(node["id"], f"{repo_id}:{target}", "i18n")
                    elif target and not os.path.basename(target).startswith("index."):
                        graph.add(node["id"], f"{repo_id}:{target}", "uses")
                    for name in re.findall(r"\b\w+\b", names.replace(" as ", " ")):
                        for target_id in exported.get(name, []):
                            target_node = graph.nodes.get(target_id) or graph.ghosts.get(target_id)
                            if not target_node.get("barrel"):
                                graph.add(node["id"], target_id, "uses")
            elif ext == ".dart":
                for spec in DART_IMPORT.findall(node["_content"]):
                    if spec.startswith("package:") and dart_package and spec.startswith(f"package:{dart_package}/"):
                        target = "lib/" + spec[len(f"package:{dart_package}/"):]
                    elif not spec.startswith(("dart:", "package:")):
                        target = os.path.normpath(os.path.join(os.path.dirname(node["path"]), spec))
                    else:
                        continue
                    if target in paths:
                        graph.add(node["id"], f"{repo_id}:{target}", "test" if node["lane"] == "tests" else "uses")
            elif ext == ".py":
                for left, right in PY_IMPORT.findall(node["_content"]):
                    module = (left or right).replace(".", "/")
                    for candidate in (module + ".py", module + "/__init__.py", "src/" + module + ".py"):
                        if candidate in paths:
                            graph.add(node["id"], f"{repo_id}:{candidate}", "test" if node["lane"] == "tests" else "uses")
                            break


def test_subjects(graph):
    nodes = graph.all()
    by_name = {}
    for n in nodes:
        by_name.setdefault((n["repo"], n["name"]), n["id"])
    for node in nodes:
        if node["lane"] != "tests":
            continue
        name = node["name"]
        stem, ext = os.path.splitext(name)
        candidates = []
        if re.search(r"Tests?$", stem):
            candidates.append(re.sub(r"Tests?$", "", stem) + ext)
        if re.search(r"\.(test|spec)$", stem):
            candidates.append(re.sub(r"\.(test|spec)$", "", stem) + ext)
        if stem.endswith("_test"):
            candidates.append(stem[: -len("_test")] + ext)
        if stem.startswith("test_"):
            candidates.append(stem[len("test_"):] + ext)
        for candidate in candidates:
            match = by_name.get((node["repo"], candidate))
            if match:
                node["subject"] = match
                break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--base", action="append", default=[], help="repo_id=rev, defaults to HEAD")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = yaml.safe_load(config_path.read_text())
    workspace = config_path.parent
    bases = dict(item.split("=", 1) for item in args.base)

    repos = [Repo(workspace, entry) for entry in config["repos"]]
    nodes, repo_info = [], []
    lanes, seen = [], set()
    for repo in repos:
        for lane in repo.lanes:
            if lane["id"] not in seen:
                seen.add(lane["id"])
                lanes.append({"id": lane["id"], "label": lane["label"]})
        if not (repo.dir / ".git").exists():
            continue
        base = bases.get(repo.id, "HEAD")
        files = collect_repo(repo, base)
        nodes.extend(files)
        repo_info.append({"repo": repo.id, "branch": git(repo.dir, "rev-parse", "--abbrev-ref", "HEAD").strip(),
                          "base": git(repo.dir, "rev-parse", "--short", base).strip(), "files": len(files)})

    secrets = [n["id"] for n in nodes if SECRET_NAME.search(n["path"])]
    if secrets:
        print("STOP: these changed files look like secrets and must not go into the map:")
        for item in secrets:
            print("  " + item)
        print("Ask the requester how to proceed. Nothing was written.")
        sys.exit(2)

    graph = Graph(repos, nodes)
    link_http(graph)
    link_tables(graph)
    link_code(graph)
    test_subjects(graph)
    edges = [{"from": a, "to": b, "kind": k, "labels": sorted(v)}
             for (a, b, k), v in graph.edges.items() if graph.known(a) and graph.known(b)]
    linked = {e["from"] for e in edges} | {e["to"] for e in edges}
    ghosts = [g for g in graph.ghosts.values() if g["id"] in linked]
    for node in nodes + ghosts:
        node.pop("_content", None)
    data = {"repos": repo_info, "lanes": lanes, "nodes": nodes + ghosts, "edges": edges}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)

    print(f"Wrote {args.out}")
    for info in repo_info:
        print(f"  {info['repo']} ({info['branch']}, base {info['base']}): {info['files']} files")
    print(f"  unchanged context files: {len(ghosts)}; links: {len(edges)}")
    print("Files to note (id | lane | status | +/- | flags):")
    for node in nodes:
        flags = " ".join(f for f, on in (("barrel", node.get("barrel")), ("binary", node.get("binary"))) if on)
        print(f"  {node['id']} | {node['lane']} | {node['status']} | +{node['added']} -{node['removed']} | {flags}")
    if ghosts:
        print("Unchanged context files (usable as flow steps, no note needed):")
        for ghost in ghosts:
            print(f"  {ghost['id']} | {ghost['lane']}")


if __name__ == "__main__":
    main()
