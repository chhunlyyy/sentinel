"""Verification (PE-01): the checks the engine runs itself after R13, their evidence, rounds and routing.

VerifyOps is mixed into Engine. `verify(slug)` runs one round: every check of the run's tier and config snapshot in each
repo the run changed, each leaving one evidence row (written when the check finishes). A round counts only once it has a
"finished" record. All checks green: R14. Otherwise failures go to a human (policy gates, unjudgeable runs) or to one fix
task per failing repo. Source: plan/v1.1/phaseE/README.md points 1 to 9.
"""
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import adapters
import boundary
import classifier
import machines
import release_check
import scopes
from errors import SentinelError
from registry import _now
from tasks import retry_cap
from util import cap_of, sha_bytes

ALLOWED = ("mutation", "migration_check", "disabled", "extra")
DISABLEABLE = ("targeted", "build", "lint", "typecheck", "hygiene", "secret", "deps", "mutation", "migration", "extra",
               "docs_links", "docs_build")
DEFAULTS = {"mutation": "tier4", "migration_check": "auto", "disabled": [], "extra": []}
FIX_ROLES = ("tdd_green", "hardener")
ACTIVE_TASKS = ("RUNNING", "WAITING_FOR_INPUT")
PENDING_TASKS = ("CREATED", "QUEUED")
AGENT_FILES = re.compile(r"(^|/)AGENTS\.md$|(^|/)\.claude/(agents|skills)/")  # always a violation, whatever the write scopes say
TEXT_KINDS = ("lint", "secret", "typecheck", "build", "hygiene")
DESTRUCTIVE = [("DROP TABLE", re.compile(r"\bDROP\s+TABLE\b", re.I)), ("DROP COLUMN", re.compile(r"\bDROP\s+COLUMN\b", re.I)),
               ("TRUNCATE", re.compile(r"\bTRUNCATE\b", re.I)), ("RENAME", re.compile(r"\bRENAME\b", re.I)),
               ("DELETE without WHERE", re.compile(r"\bDELETE\s+FROM\b(?![^;]*\bWHERE\b)", re.I | re.S))]
_ACTIVE = set()  # (state dir, run id) of verifications running in this process


def settings(cfg):
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()}
    block = (cfg or {}).get("verification")
    if isinstance(block, dict):
        for k in ALLOWED:
            if k in block:
                out[k] = block[k]
    return out


def config_problems(cfg):
    """[(field, text)] for an invalid `verification` block (CFG-11)."""
    block = (cfg or {}).get("verification")
    if block is None:
        return []
    if not isinstance(block, dict):
        return [("verification", "verification: must be a mapping")]
    found = [("verification", f"verification: unknown key {k}") for k in block if k not in ALLOWED]
    if "mutation" in block and block["mutation"] not in ("tier4", "always", "never"):
        found.append(("verification.mutation", "verification.mutation: must be tier4, always or never"))
    if "migration_check" in block and block["migration_check"] not in ("auto", "always", "never"):
        found.append(("verification.migration_check", "verification.migration_check: must be auto, always or never"))
    if "disabled" in block:
        d = block["disabled"]
        bad = [x for x in d if x not in DISABLEABLE] if isinstance(d, list) else ["?"]
        if bad:
            found.append(("verification.disabled", f"verification.disabled: cannot disable {', '.join(map(str, bad))}; "
                          f"allowed: {', '.join(DISABLEABLE)} (test and scope always run)"))
    if "extra" in block and not (isinstance(block["extra"], list) and all(isinstance(x, dict) and x.get("name") and x.get("type") in ("added_lines", "changed_paths") for x in block["extra"])):
        found.append(("verification.extra", "verification.extra: must be a list of extra_checks rules"))
    return found


def migration_patterns(cfg, repo_id):
    repo = scopes._repo(cfg, repo_id) or {}
    lane = repo.get("migration_lane")
    if lane is None:
        from render_stage import load_profile
        prof = load_profile(repo["profile"]) if repo.get("profile") else {}
        for item in prof.get("lanes") or []:
            if item.get("id") in ("database", "migrations"):
                lane = item.get("match")
    return [lane] if isinstance(lane, str) else list(lane or [])


def split_statements(sql):
    text = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in text.split(";") if s.strip()]


def destructive_statements(sql):
    return [stmt.replace("\n", " ")[:160] for stmt in split_statements(sql) if any(rx.search(stmt) for _, rx in DESTRUCTIVE)]


def sha_of(path):
    try:
        return sha_bytes(Path(path).read_bytes())
    except OSError:
        return None


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout


class VerifyOps:
    # ---- helpers
    def _vrounds(self, run):
        return self.reg.rows("verification_rounds", run_id=run["id"])

    def finished_round(self, run):
        """The latest finished, not interrupted verification round row of the run, or None."""
        rows = [r for r in self._vrounds(run) if r["finished_at"] and not r["interrupted"]]
        return max(rows, key=lambda r: r["round"]) if rows else None

    def round_rows(self, run, rnd):
        return [e for e in self.reg.rows("evidence", run_id=run["id"]) if e["round"] == rnd]

    def _db_error(self, err):
        return SentinelError("E_MIGRATION", f"database error during verification: {err}", {"error": str(err)}, exit_code=1)

    def _owner_alive(self, r, run):
        pid = r["owner_pid"]
        if not pid:
            return False
        if pid == os.getpid():
            return (str(self.state_dir), run["id"]) in _ACTIVE
        return adapters.process_alive(pid, r["owner_started_at"])

    # ---- entry
    def verify(self, slug, caller_task=None):
        """`sentinel verify`: one verification round. Returns a dict; "exit" is 0, 1 or 6."""
        self._refuse_agent(slug, "verify", caller_task)
        run = self._get(slug)
        if run["workflow_version"] != "2":
            raise SentinelError("E_TRANSITION", f"run {slug} is a 0.1 run; use `sentinel release-check` for its checks", {"slug": slug})
        self._sync(slug)
        key = None
        try:
            with self.reg.transaction():
                run = self._get_v2(slug)
                if run["state"] != "VERIFYING":
                    raise SentinelError("E_TRANSITION", f"verification needs a VERIFYING run, run is {run['state']}", {"state": run["state"]})
                busy = [t for t in self.reg.rows("tasks", run_id=run["id"]) if t["state"] in ACTIVE_TASKS + PENDING_TASKS]
                if busy:
                    raise SentinelError("E_PRECONDITION", f"task {busy[0]['id']} of the run is {busy[0]['state']}; verification waits",
                                        {"task": busy[0]["id"]})
                for r in self._vrounds(run):
                    if not r["finished_at"] and not r["interrupted"]:
                        if self._owner_alive(r, run):
                            raise SentinelError("E_LOCKED", f"verification round {r['round']} of {slug} is in progress", {"round": r["round"]})
                        self.reg.update_row("verification_rounds", r["id"], interrupted=1)
                        self._event(run, "verification.interrupted", machines.ENGINE, {"round": r["round"]})
                rnd = max([r["round"] for r in self._vrounds(run)], default=0) + 1
                plan = self._plan(run)
                if plan.get("human"):
                    self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=plan["human"])
                    out = {"exit": 6, "round": None, "passed": False, "state": "NEEDS_HUMAN", "reason": plan["human"], "rows": [], "summary": {}}
                    plan = None
                else:
                    self.reg.insert_row("verification_rounds", {
                        "run_id": run["id"], "round": rnd, "started_at": _now(), "interrupted": 0,
                        "owner_pid": os.getpid(), "owner_started_at": adapters.process_start_time(os.getpid())})
                    key = (str(self.state_dir), run["id"])
                    _ACTIVE.add(key)
            if plan is None:
                self._finish_up(slug, run)
                return out
            try:
                return self._run_round(run, rnd, plan)
            except sqlite3.Error as err:
                raise self._db_error(err) from err
        except sqlite3.Error as err:
            raise self._db_error(err) from err
        finally:
            if key:
                _ACTIVE.discard(key)

    # ---- plan
    def _repo_state(self, run, cfg, rr):
        rid = rr["repo_id"]
        path = self._repo_path(cfg, rid)
        info = {"id": rid, "path": path, "baseline": rr["baseline_sha"], "head": None, "paths": {}, "changed": [], "before": [],
                "dirty": json.loads(rr.get("baseline_dirty") or "{}")}
        if not (path / ".git").exists():
            return info
        state = boundary.changed_state(path)
        info["head"], info["paths"] = state["head"], state["paths"]
        sname = self.state_dir.name
        for p, sha in sorted(state["paths"].items()):
            if p == sname or p.startswith(sname + "/") or p in boundary.IGNORE_FILES:
                continue
            if p in info["dirty"] and info["dirty"][p] == sha:
                info["before"].append(p)
            else:
                info["changed"].append(p)
        return info

    def repo_fingerprint(self, path):
        """{"head", "paths": {path: sha256}} of a repo as it is now, without the sentinel folder and the git rule files."""
        state = boundary.changed_state(path)
        sname = self.state_dir.name
        return {"head": state["head"], "paths": {p: h for p, h in sorted(state["paths"].items())
                                                 if not (p == sname or p.startswith(sname + "/") or p in boundary.IGNORE_FILES)}}

    def _plan(self, run):
        cfg = self._run_config(run)
        st = settings(cfg)
        tier = run["tier"] or 1
        docs = run["type"] == "docs"
        repos = []
        for rr in self.reg.run_repos(run["id"]):
            info = self._repo_state(run, cfg, rr)
            info["is_changed"] = bool(info["changed"]) or (info["head"] is not None and info["head"] != rr["baseline_sha"])
            repos.append(info)
        plan = {"cfg": cfg, "st": st, "tier": tier, "docs": docs, "repos": repos}
        if not docs:
            for info in repos:
                if not info["is_changed"]:
                    continue
                tools = scopes.test_tools(cfg, info["id"])
                if not tools["test"]:
                    plan["human"] = f"test command missing for repo {info['id']}"
                    return plan
                if self._mutation_on(st, tier) and not self._command(cfg, info["id"], "mutate"):
                    plan["human"] = f"mutate command missing for repo {info['id']}"
                    return plan
        return plan

    @staticmethod
    def _mutation_on(st, tier):
        return st["mutation"] == "always" or (st["mutation"] == "tier4" and tier >= 4)

    def _command(self, cfg, repo_id, key):
        from render_stage import load_profile, repo_commands
        repo = scopes._repo(cfg, repo_id) or {}
        profile = load_profile(repo["profile"]) if repo.get("profile") else {}
        return repo_commands(repo, profile).get(key) or ""

    def _scope_union(self, run):
        union = []
        for t in self.reg.rows("tasks", run_id=run["id"]):
            if t["state"] == "COMPLETED":
                union += [g for g in self.task_scope(t["id"]) if g not in union]
        return union

    # ---- the round
    def _kinds(self, run, cfg, st, tier, info, docs):
        """The checks of a repo in this round, scope first: nothing the repo's own scripts run starts before it passed."""
        kinds = ["scope"]
        if info["is_changed"]:
            if docs:
                return kinds + ["docs_links", "docs_build"]
            kinds += ["targeted", "test", "build", "lint", "typecheck", "hygiene"]
            if tier >= 2:
                kinds += ["secret", "deps"]
            if self._mutation_on(st, tier):
                kinds.append("mutation")
            if st["migration_check"] == "always" or (st["migration_check"] == "auto" and self._migration_files(cfg, info)):
                kinds.append("migration")
            kinds += [("extra", r) for r in st["extra"] if r.get("repo") in (None, info["id"])]
        return kinds

    def _run_round(self, run, rnd, plan):
        cfg, st, tier = plan["cfg"], plan["st"], plan["tier"]
        union = self._scope_union(run)
        first = sorted(r["id"] for r in plan["repos"])[:1]
        summary = {"unchanged": [], "changed_before_run": [], "not_run": [], "claims": [], "plan": {}}
        rows = []
        for info in plan["repos"]:
            rid = info["id"]
            summary["changed_before_run"] += [f"{rid}/{p}" for p in info["before"]]
            if not info["is_changed"]:
                summary["unchanged"].append(rid)
            kinds = self._kinds(run, cfg, st, tier, info, plan["docs"])
            summary["plan"][rid] = [[k[0], k[1].get("name")] if isinstance(k, tuple) else [k, None] for k in kinds]
            scope_failed = False
            for item in kinds:
                kind, rule = item if isinstance(item, tuple) else (item, None)
                if kind in st["disabled"] and kind != "scope":
                    res = {"verdict": "disabled", "classification": "disabled"}
                elif scope_failed:
                    res = {"verdict": "not_run", "classification": "not_run", "reason": "the scope check of the repo failed"}
                else:
                    res = getattr(self, f"_chk_{kind}")(run, cfg, info, union=union, first=rid in first, rule=rule, tier=tier)
                rec = self._record(run, rnd, kind, rid, res, name=(rule or {}).get("name") if rule else None)
                rows.append(rec)
                scope_failed = scope_failed or (kind == "scope" and rec["verdict"] == "fail")
        summary["not_run"] = [f"{r['repo']} {r['kind']}" for r in rows if r["verdict"] in ("not_configured", "disabled", "not_run")]
        summary["repo_state"] = {i["id"]: self.repo_fingerprint(i["path"]) for i in plan["repos"] if (i["path"] / ".git").exists()}
        return self._judge_round(run, rnd, plan, rows, summary)

    def _record(self, run, rnd, kind, repo, res, name=None):
        """One evidence row, committed on its own so progress is visible; the output goes to a scrubbed file."""
        ran = res.get("ran")
        row = {"run_id": run["id"], "kind": kind, "repo_id": repo, "round": rnd, "name": name,
               "classification": res.get("classification"), "verdict": res["verdict"], "reason": res.get("reason"),
               "failing": json.dumps(res.get("failing") or []), "detail": json.dumps(res.get("detail") or {})}
        counts = res.get("counts")
        if counts:
            row.update(passed=counts[0], failed=counts[1], skipped=counts[2])
        text = ""
        if ran:
            text = self._scrubber().scrub_text(ran["output"])
            data = text.encode("utf-8")
            label = f"{repo}-{kind}" + (f"-{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}" if name else "")
            dest = self.run_dir(run["slug"]) / "verification" / f"round-{rnd}" / f"{label}.log"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            sha = sha_bytes(data)
            env = {"platform": sys.platform, "python": sys.version.split()[0], "os": platform.platform(),
                   "tools": (scopes._repo(self._run_config(run), repo) or {}).get("tool_versions") or {}}
            with self.reg.transaction():
                art = self.reg.insert_row("artifacts", {"run_id": run["id"], "kind": "verification_output", "version": rnd,
                                                        "path": dest.relative_to(self.state_dir).as_posix(), "sha256": sha,
                                                        "created_at": _now()})
                row.update(command=ran["command"], cwd=repo, exit_code=ran["exit_code"], started_at=ran["started_at"],
                           finished_at=ran["finished_at"], repo_sha=ran["repo_sha"], output_artifact_id=art, output_sha256=sha,
                           env=json.dumps(env))
                eid = self.reg.insert_row("evidence", row)
                self._evidence_event(run, row, eid)
        else:
            now = _now()
            row.update(started_at=now, finished_at=now, repo_sha=res.get("repo_sha"),
                       env=json.dumps({"platform": sys.platform, "python": sys.version.split()[0]}))
            with self.reg.transaction():
                eid = self.reg.insert_row("evidence", row)
                self._evidence_event(run, row, eid)
        return {"id": eid, "repo": repo, "kind": kind, "name": name, "verdict": res["verdict"],
                "classification": res.get("classification"), "failing": res.get("failing") or [], "detail": res.get("detail") or {},
                "human": res.get("human"), "text": text}

    def _evidence_event(self, run, row, eid):
        self._event(run, "evidence.recorded", machines.ENGINE, {
            "kind": row["kind"], "repo": row["repo_id"], "round": row["round"], "exit_code": row.get("exit_code"),
            "classification": row["classification"], "verdict": row["verdict"], "evidence": eid})

    # ---- individual checks. Each returns {verdict, classification, ran?, failing?, detail?, human?}
    def _chk_scope(self, run, cfg, info, union=(), first=False, **_):
        bad, workspace = [], []
        if info["head"] is not None and info["head"] != info["baseline"]:
            bad.append("HEAD moved")
        for p in info["changed"]:
            if AGENT_FILES.search(p) or not scopes.path_allowed(union, info["id"], p):
                bad.append(p)
        if first:
            cfg_file = self.workspace / "sentinel.config.yaml"
            snap = self.reg.get_config_version(run["config_snapshot_id"]) if run.get("config_snapshot_id") else None
            if cfg_file.is_file() and snap and sha_of(cfg_file) != snap["sha256"]:
                workspace.append("sentinel.config.yaml")
            try:
                was = json.loads(run.get("watched_baseline") or "null")
            except ValueError:
                was = None
            if was is not None:
                now = self.watched_files()
                workspace += [p for p in sorted(set(was) | set(now)) if was.get(p) != now.get(p)]
            bad += workspace
        return {"verdict": "fail" if bad else "pass", "classification": "scope_exceeded" if bad else "pass", "failing": bad,
                "detail": {"workspace": workspace}, "repo_sha": info["head"], "human": bad or None}

    def _chk_test(self, run, cfg, info, **_):
        rid = info["id"]
        tools = scopes.test_tools(cfg, rid)
        ran = self._run_tests(cfg, rid, tools["test"], tools)
        base_row = self.baseline(run, rid)
        base = json.loads(base_row["failing"] or "[]") if base_row else []
        cl = classifier.classify(ran["exit_code"], ran["output"], ran["report"], tools["failure_patterns"], baseline_failing=base,
                                 summary_patterns=tools.get("summary_patterns"))
        klass = cl["classification"]
        failing = cl["failing"]
        new = [t for t in failing if t not in base]
        detail = {"preexisting": [t for t in failing if t in base], "new_failures": new,
                  "fixed": [t for t in base if t not in failing] if ran["report"] is not None else []}
        res = {"ran": ran, "failing": failing, "detail": detail, "counts": (cl["passed"], cl["failed"], cl["skipped"])}
        if klass in ("environment", "missing_dependency"):
            return {**res, "verdict": "fail", "classification": "environment", "human": f"test run classified environment in repo {rid}"}
        if klass == "unknown":
            return {**res, "verdict": "fail", "classification": "unknown", "human": f"test run classified unknown in repo {rid}"}
        if klass == "compile":
            return {**res, "verdict": "fail", "classification": "compile"}
        ok = not new
        return {**res, "verdict": "pass" if ok else "fail", "classification": "pass" if ok else "assertion"}

    def _accepted_tests(self, run, rid):
        out, info = [], {}
        for c in self.live_cycles(run):
            if c["repo_id"] == rid and c["state"] == "CYCLE_ACCEPTED":
                out += [t for t in json.loads(c["tests"] or "[]") if t not in out]
                try:
                    info.update(json.loads(c["test_info"] or "{}"))
                except ValueError:
                    pass
        return out, info

    def _chk_targeted(self, run, cfg, info, **_):
        rid = info["id"]
        tools = scopes.test_tools(cfg, rid)
        tests, tinfo = self._accepted_tests(run, rid)
        if not tools.get("targeted_test") or not tests:
            return {"verdict": "not_configured", "classification": "not_configured",
                    "reason": "no targeted_test command" if not tools.get("targeted_test") else "no targeted tests"}
        try:
            ran = self._run_tests(cfg, rid, tools["targeted_test"], tools, tests, tinfo)
        except ValueError as err:
            return {"verdict": "fail", "classification": "unknown", "reason": str(err), "human": f"targeted tests cannot be selected in repo {rid}: {err}"}
        base_row = self.baseline(run, rid)
        base = json.loads(base_row["failing"] or "[]") if base_row else []
        cl = classifier.classify(ran["exit_code"], ran["output"], ran["report"], tools["failure_patterns"], new_tests=tests,
                                 baseline_failing=base, summary_patterns=tools.get("summary_patterns"))
        verdict, why = classifier.verify_green(cl, tests)
        res = {"ran": ran, "failing": [t for t in tests if t in cl["failing"]], "reason": why,
               "counts": (cl["passed"], cl["failed"], cl["skipped"]), "detail": {"tests": tests}}
        if cl["classification"] in ("environment", "missing_dependency") or verdict == "needs_human":
            klass = "environment" if cl["classification"] != "unknown" else "unknown"
            return {**res, "verdict": "fail", "classification": klass, "human": f"targeted run classified {klass} in repo {rid}"}
        return {**res, "verdict": "pass" if verdict == "accepted" else "fail", "classification": cl["classification"]}

    def _simple(self, run, cfg, info, key, kind_cls="fail"):
        command = self._command(cfg, info["id"], key)
        if not command:
            return {"verdict": "not_configured", "classification": "not_configured", "reason": f"no {key} command"}
        tools = {**scopes.test_tools(cfg, info["id"]), "test_report": None}
        ran = self._run_tests(cfg, info["id"], command, tools)
        ok = ran["exit_code"] == 0
        return {"ran": ran, "verdict": "pass" if ok else "fail", "classification": "pass" if ok else kind_cls}

    def _chk_build(self, run, cfg, info, **_):
        return self._simple(run, cfg, info, "build")

    def _chk_lint(self, run, cfg, info, **_):
        return self._simple(run, cfg, info, "lint")

    def _chk_typecheck(self, run, cfg, info, **_):
        return self._simple(run, cfg, info, "typecheck")

    def _chk_mutation(self, run, cfg, info, **_):
        return self._simple(run, cfg, info, "mutate", "survivors")

    def _chk_docs_build(self, run, cfg, info, **_):
        return self._simple(run, cfg, info, "docs")

    def _lines(self, info):
        skip = set(info["before"])
        return [(n, t) for n, t in release_check.added_lines(info["path"]) if n not in skip]

    def _chk_hygiene(self, run, cfg, info, **_):
        enabled = cfg.get("release_checks") or release_check.DEFAULT_CHECKS
        rules = cfg.get("rules") or {}
        lines = self._lines(info)
        source = [(n, t) for n, t in lines if not re.search(r"(^|/)(test|tests|spec|__tests__)/|\.(test|spec)\.", n)]
        hits = []
        if "debug_output" in enabled:
            hits += [f"debug output added: {h}" for h in release_check.scan(source, release_check.DEBUG_PATTERNS)]
        if "todo" in enabled:
            hits += [f"TODO/FIXME added: {n}: {t.strip()[:120]}" for n, t in source if re.search(r"\b(TODO|FIXME|XXX)\b", t)]
        if "comments" in enabled and rules.get("no_code_comments"):
            hits += [f"code comment added: {h}" for h in release_check.scan(lines, release_check.COMMENT_PATTERNS)]
        repo = scopes._repo(cfg, info["id"]) or {}
        if "test_infra" in enabled and rules.get("no_permanent_frontend_tests") and repo.get("role") in release_check.CLIENT_ROLES:
            status = git(info["path"], "status", "--porcelain", "--untracked-files=all").splitlines()
            # the approved test files of this run's TDD cycles are written by Red on purpose; every other test file or runner
            # config left behind is still flagged (the 0.1 release check, which sees no cycles, is unchanged)
            approved = set(self.approved_files(run, info["id"]))
            hits += [f"test infrastructure left behind: {s[3:]}" for s in status
                     if release_check.TEST_INFRA.search(s[3:]) and f"{info['id']}/{s[3:]}" not in approved]
        return {"verdict": "fail" if hits else "pass", "classification": "hygiene" if hits else "pass", "failing": hits,
                "detail": {"hits": hits}}

    def _chk_secret(self, run, cfg, info, **_):
        hits = release_check.scan_secrets(self._lines(info))
        if shutil.which("gitleaks"):
            r = subprocess.run(["gitleaks", "detect", "--no-banner", "--source", str(info["path"]), "--no-git"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                hits += r.stdout.splitlines()[:20]
        return {"verdict": "fail" if hits else "pass", "classification": "secret" if hits else "pass", "failing": hits,
                "detail": {"hits": hits}}

    def _chk_deps(self, run, cfg, info, **_):
        manifests = [p for p in info["changed"] if Path(p).name in release_check.MANIFESTS]
        if not manifests:
            return {"verdict": "pass", "classification": "no_manifest_change"}
        added = []
        for m in manifests:
            for line in git(info["path"], "diff", "HEAD", "--", m).splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    added.append(f"{m}: {line[1:].strip()}")
        res = self._simple(run, cfg, info, "audit", "vulnerable")
        res["detail"] = {"manifests": manifests, "added": added}
        return res

    def _migration_files(self, cfg, info):
        pats = migration_patterns(cfg, info["id"])
        return [p for p in info["changed"] if any(re.search(x, p) for x in pats)]

    def _chk_migration(self, run, cfg, info, **_):
        files = self._migration_files(cfg, info)
        destructive, approved, applied, ok = [], [], [], []
        for p in files:
            existed = subprocess.run(["git", "-C", str(info["path"]), "cat-file", "-e", f"{info['baseline']}:{p}"],
                                     capture_output=True).returncode == 0
            if existed:
                applied.append(p)
                continue
            full = info["path"] / p
            sha = sha_of(full)
            stmts = destructive_statements(full.read_text(encoding="utf-8", errors="replace")) if full.is_file() else []
            if not stmts:
                ok.append(p)
            elif self._migration_approved(run, sha):
                approved.append(p)
            else:
                destructive.append({"file": p, "sha256": sha, "statements": stmts})
        detail = {"files": files, "destructive": destructive, "approved": approved, "applied_changed": applied}
        if destructive:
            return {"verdict": "fail", "classification": "destructive", "failing": [s for d in destructive for s in d["statements"]],
                    "detail": detail, "human": "destructive migration needs human approval (policy destructive_migration)"}
        if applied:
            return {"verdict": "fail", "classification": "applied_migration_changed", "failing": applied, "detail": detail}
        return {"verdict": "pass", "classification": "destructive_approved" if approved else "pass", "detail": detail}

    def _migration_approved(self, run, sha):
        return any(a["state"] == "APPROVED" and a["sha256"] == sha for a in self.reg.rows("approvals", run_id=run["id"], gate="migration"))

    def _chk_extra(self, run, cfg, info, rule=None, **_):
        rid = info["id"]
        hits = []
        path_re = re.compile(rule["path_regex"]) if rule.get("path_regex") else None
        if rule["type"] == "added_lines":
            skip_path = re.compile(rule["exclude_path_regex"]) if rule.get("exclude_path_regex") else None
            skip_lines = [re.compile(p) for p in rule.get("exclude_line_regex") or []]
            pattern = re.compile(rule["pattern"])
            for name, text in self._lines(info):
                if (path_re and not path_re.search(name)) or (skip_path and skip_path.search(name)):
                    continue
                if any(s.search(text) for s in skip_lines) or not pattern.search(text):
                    continue
                hits.append(f"{name}: {text.strip()[:120]}")
        else:
            for entry in git(info["path"], "status", "--porcelain", "--untracked-files=all").splitlines():
                code, name = entry[:2], entry[3:]
                if path_re and not path_re.search(name):
                    continue
                wanted = rule.get("status", "any")
                if wanted == "modified" and "M" not in code:
                    continue
                if wanted == "added" and code.strip() not in ("??", "A"):
                    continue
                if rule.get("must_match") and re.search(rule["must_match"], name):
                    continue
                hits.append(name)
        return {"verdict": "fail" if hits else "pass", "classification": "extra" if hits else "pass", "failing": hits,
                "detail": {"hits": hits, "repo": rid}}

    def _chk_docs_links(self, run, cfg, info, **_):
        broken = []
        for p in info["changed"]:
            if not p.lower().endswith(".md"):
                continue
            full = info["path"] / p
            text = full.read_text(encoding="utf-8", errors="replace") if full.is_file() else ""
            for target in re.findall(r"\]\(([^)\s]+)\)", text):
                target = target.split("#")[0]
                if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                    continue
                if not (full.parent / target).exists():
                    broken.append(f"{p}: broken link {target}")
        return {"verdict": "fail" if broken else "pass", "classification": "broken_links" if broken else "pass", "failing": broken,
                "detail": {"hits": broken}}

    # ---- judging and routing
    def _located_in_approved_tests(self, run, rid, row):
        """True when a failure's text names an approved test file and no production file."""
        approved = self.approved_files(run, rid)
        if not approved or row["kind"] not in TEXT_KINDS:
            return None
        text = row["text"] + "\n" + "\n".join(row["failing"])
        hit = [p for p in approved if p in text or p.split("/", 1)[-1] in text]
        if not hit:
            return None
        cfg = self._run_config(run)
        prod = [g.split("/", 1)[-1] for g in scopes.scope_globs(cfg, rid, "production")]
        paths = set(re.findall(r"[\w./-]+\.\w+", text)) - set(hit) - {p.split("/", 1)[-1] for p in hit}
        if any(scopes.classify(cfg, rid, x.split(rid + "/", 1)[-1]) == "production" for x in paths) and prod:
            return None
        return hit[0]

    def _claims(self, run, rows):
        failed = {r["kind"] for r in rows if r["verdict"] == "fail"}
        flags = []
        for t in self.reg.rows("tasks", run_id=run["id"]):
            try:
                doc = json.loads((self.task_dir(run["slug"], t["id"]) / "result.json").read_text())
            except (OSError, ValueError):
                continue
            for claim in doc.get("claimed_commands") or []:
                if isinstance(claim, dict) and claim.get("exit_code") == 0 and failed & set(str(claim.get("command", "")).split()):
                    flags.append({"task": t["id"], "role": t["role"], "command": claim["command"], "flag": "contradicted by evidence"})
        return flags

    def _judge_round(self, run, rnd, plan, rows, summary):
        slug = run["slug"]
        cfg = plan["cfg"]
        failed = [r for r in rows if r["verdict"] == "fail"]
        summary["claims"] = self._claims(run, rows)
        # human conditions first: nothing here is ever routed to an agent
        human = None
        scope_bad = [r for r in failed if r["kind"] == "scope"]
        if scope_bad:
            parts = []
            for r in scope_bad:
                ws = r["detail"].get("workspace", [])
                for p in r["failing"]:
                    parts.append(f"{r['repo']}: HEAD moved" if p == "HEAD moved" else p if p in ws else f"{r['repo']}/{p}")
            human = "changes outside every task scope: " + ", ".join(parts)
        if not human:
            for r in failed:
                if r["human"] and r["kind"] != "scope":
                    human = r["human"] if isinstance(r["human"], str) else None
                    if human:
                        break
        if not human:
            for r in failed:
                hit = self._located_in_approved_tests(run, r["repo"], r)
                if hit:
                    human = f"fix needs a change to approved test file {hit}"
                    break
        cap = cap_of((cfg.get("limits") or {}).get("release_check_rounds"), 3)
        finished = len([x for x in self._vrounds(run) if x["finished_at"] and not x["interrupted"]]) + 1
        out = {"round": rnd, "rows": [{k: r[k] for k in ("repo", "kind", "name", "verdict", "classification")} for r in rows],
               "summary": summary, "passed": not failed, "fix_tasks": []}
        with self.reg.transaction():
            run = self._get_v2(slug)
            vr = [x for x in self._vrounds(run) if x["round"] == rnd][0]
            self.reg.update_row("verification_rounds", vr["id"], finished_at=_now(), passed=int(not failed),
                                summary=json.dumps(summary))
            self._event(run, "verification.finished", machines.ENGINE, {"round": rnd, "passed": not failed})
            if not failed:
                self._move(run, "REVIEWING", machines.ENGINE, reason=f"verification round {rnd} passed")
                self._resolve_findings(self._get_v2(slug))
                self._create_review_chain(self._get_v2(slug))
                out.update(exit=0, state="REVIEWING")
            elif human:
                self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=human)
                out.update(exit=6, state="NEEDS_HUMAN", reason=human)
            elif finished >= cap:
                why = f"verification failed after {finished} rounds: " + "; ".join(
                    f"{r['repo']} {r['kind']}" + (f" ({r['name']})" if r["name"] else "") for r in failed)
                self._move(run, "NEEDS_HUMAN", machines.ENGINE, reason=why)
                out.update(exit=6, state="NEEDS_HUMAN", reason=why)
            else:
                out["fix_tasks"] = self._route_failures(run, rnd, failed)
                out.update(exit=1, state="VERIFYING")
        self._finish_up(slug, run)
        return out

    def _route_failures(self, run, rnd, failed):
        """Inside a transaction: one fix task per failing repo, with every failure of that repo in its brief."""
        cfg = self._run_config(run)
        made = []
        for rid in dict.fromkeys(r["repo"] for r in failed):
            mine = [r for r in failed if r["repo"] == rid]
            role = "hardener" if all(r["kind"] == "mutation" for r in mine) else "tdd_green"
            lines = [f"Verification round {rnd} failed in repo {rid}. Fix the failures below. Approved test files are read-only.", ""]
            for r in mine:
                label = r["kind"] + (f" ({r['name']})" if r["name"] else "")
                lines += [f"### {label}: {r['classification']}"]
                tail = [ln for ln in (r["text"] or "").splitlines() if ln.strip()][-40:]
                lines += [f"    {ln}" for ln in tail]
                lines += [f"    {h}" for h in r["failing"][:40] if h not in tail]
                if r["kind"] == "migration":
                    lines += [f"    applied migration changed: {p}" for p in r["detail"].get("applied_changed", [])]
                lines.append("")
            write = scopes.scope_globs(cfg, rid, "tests" if role == "hardener" else "production")
            cap = cap_of(((cfg.get("agents") or {}).get(role) or {}).get("max_retries"), retry_cap(cfg, role), 0)
            task = self._make_task(run, role, f"Fix the verification failures of {rid} (round {rnd})", [rid], write=write,
                                   readonly_approved=self.approved_files(run, rid), brief="\n".join(lines) + "\n",
                                   max_retries=cap, queue=True)
            made.append(task["id"])
            for r in mine:
                self.reg.add_trace_link(run["id"], "evidence", r["id"], "task", task["id"])
                self.reg.add_event(run["id"], "finding.routed", machines.ENGINE,
                                   {"evidence": r["id"], "task": task["id"], "kind": r["kind"], "repo": rid, "round": rnd},
                                   task_id=task["id"])
        return made

    def link_fix_task_files(self, task_id):
        """After a fix task COMPLETED: task -> file trace links for what it changed."""
        t = self._task_row(task_id)
        if t["role"] not in FIX_ROLES or t["cycle_id"] or t["state"] != "COMPLETED":
            return
        with self.reg.transaction():
            for rec in self.reg.rows("changed_files", task_id=task_id):
                if rec["repo_id"]:
                    self.reg.add_trace_link(t["run_id"], "task", task_id, "file", f"{rec['repo_id']}/{rec['path']}")
