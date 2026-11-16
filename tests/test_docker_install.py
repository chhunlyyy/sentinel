"""Phase I: the dashboard image (docker_dashboard.feature).

Static checks of the Dockerfile and .dockerignore always run. The tests that start the image need a usable docker daemon and
skip with the reason where there is none (the gate records those ids in tests/release/manual.json until they pass on a machine
with docker). They build the image once per run, run it with `-it` under a pseudo-terminal, publish on 127.0.0.1 only, and remove
every container, volume and image they made.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pb_helpers import SLUG  # noqa: E402
from sv_helpers import Http, SENTINEL, SV, TtyProc, free_port  # noqa: E402

DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
IMAGE_NAME = "ghcr.io/chhunlyyy/sentinel"
BUDGET = 250 * 1024 * 1024
URL = re.compile(r"http://localhost:(\d+)/auth\?t=([0-9a-f]{64})")


def instructions(text=DOCKERFILE):
    """[(INSTRUCTION, rest)] with line continuations joined and comments removed."""
    out, cur = [], ""
    for line in text.splitlines():
        if not cur and (not line.strip() or line.lstrip().startswith("#")):
            continue
        cur += line.rstrip("\\").strip() + " " if line.rstrip().endswith("\\") else line.strip()
        if line.rstrip().endswith("\\"):
            continue
        out.append(tuple(cur.split(None, 1)) if " " in cur else (cur, ""))
        cur = ""
    return [(a.upper(), b) for a, b in out]


def stages():
    """[[(INSTRUCTION, rest)]] one list per FROM."""
    res = []
    for ins in instructions():
        if ins[0] == "FROM":
            res.append([])
        res[-1].append(ins)
    return res


def documented_command():
    m = re.search(r"(?m)^docker run [^\n]*ghcr\.io/chhunlyyy/sentinel\s*$", (ROOT / "README.md").read_text())
    return m.group(0)


class Static(unittest.TestCase):
    def test_AC_OPS_07a_a_multi_stage_build_with_pinned_bases(self):
        st = stages()
        self.assertEqual(len(st), 3)
        node, wheel, final = st
        self.assertTrue(node[0][1].startswith("node:22.18.0-slim"))
        self.assertTrue(wheel[0][1].startswith("python:3.12-slim"))
        self.assertTrue(final[0][1].startswith("python:3.12-slim"))
        self.assertIn("npm ci", " ".join(r for i, r in node if i == "RUN"))
        self.assertIn("npm run build", " ".join(r for i, r in node if i == "RUN"))
        run = " ".join(r for i, r in wheel if i == "RUN")
        self.assertIn("SENTINEL_RELEASE=1", run)
        self.assertIn("build -t wheel", run)
        for stage in st:
            self.assertRegex(stage[0][1], r"^[\w./-]+:[\w.-]+( AS \w+)?$", stage[0][1])
            self.assertNotIn("latest", stage[0][1])
        copies = [r for i, r in final if i == "COPY"]
        self.assertTrue(copies)
        self.assertTrue(all(r.startswith("--from=wheel ") for r in copies), copies)
        users = [r for i, r in final if i == "USER"]
        self.assertEqual(users[-1], "sentinel")

    def test_AC_OPS_07b_the_build_context_is_small_and_clean(self):
        lines = [x.strip() for x in (ROOT / ".dockerignore").read_text().splitlines() if x.strip() and not x.startswith("#")]
        for want in ("**/node_modules", ".sentinel", ".claude", ".git", "plan", "tests", "release-evidence.json", "**/.env*", "**/.npmrc",
                     "**/*.pem", "**/.sentinel", "**/.claude", ".vscode", ".idea", "*.whl"):
            self.assertIn(want, lines)
        for needed in ("dashboard", "sentinel", "skills", "hatch_build.py", "pyproject.toml", "README.md", "LICENSE"):
            self.assertNotIn(needed, lines, needed)
            self.assertTrue((ROOT / needed).exists(), needed)

    def test_AC_OPS_07e_the_container_needs_no_browser(self):
        final = stages()[-1]
        cmd = [r for i, r in final if i == "CMD"][-1]
        self.assertIn('"--no-open"', cmd)
        self.assertEqual([r for i, r in final if i == "ENTRYPOINT"], ['["sentinel"]'])
        apt = [r for i, r in final if i == "RUN" and "apt-get install" in r]
        self.assertEqual(len(apt), 1)
        pkgs = re.search(r"apt-get install -y --no-install-recommends ([^&]+?)\s*&&", apt[0]).group(1).split()
        self.assertEqual(sorted(pkgs), ["ca-certificates", "git"])

    def test_AC_OPS_07j_git_trusts_the_mounted_workspace(self):
        final = stages()[-1]
        self.assertTrue(any("git config --system --add safe.directory /work" in r for i, r in final if i == "RUN"))
        self.assertEqual([r for i, r in final if i == "WORKDIR"][-1], "/work")

    def test_AC_OPS_07o_the_image_is_labelled(self):
        label = " ".join(r for i, r in stages()[-1] if i == "LABEL")
        version = (ROOT / "sentinel" / "VERSION").read_text().strip()
        self.assertIn(f'org.opencontainers.image.version="{version}"', label)
        self.assertIn('org.opencontainers.image.source="https://github.com/chhunlyyy/sentinel"', label)
        self.assertIn('org.opencontainers.image.licenses="MIT"', label)

    def test_AC_SEC_10j_every_documented_publish_option_names_127_0_0_1(self):
        files = [ROOT / "README.md", ROOT / "Dockerfile", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md")), ROOT / ".github" / "workflows" / "release.yml"]
        found = []
        for f in files:
            if not f.exists():
                continue
            for line in f.read_text().splitlines():
                if "docker run" not in line:
                    continue
                for m in re.finditer(r"(?:^|\s)(?:-p|--publish)[ =]+(\S+)", line):
                    found.append((f.name, m.group(1)))
                    self.assertTrue(m.group(1).startswith("127.0.0.1:"), f"{f.name}: {m.group(1)}")
        self.assertGreaterEqual(len(found), 3, found)
        dash = re.sub(r"\s+", " ", (ROOT / "docs" / "dashboard.md").read_text())
        self.assertIn("--user $(id -u):$(id -g)", dash)
        self.assertIn("0.0.0.0", dash)  # the guide says never to publish on it

    def test_review_the_image_user_can_be_any_uid(self):
        final = stages()[-1]
        run = " ".join(r for i, r in final if i == "RUN" and "useradd" in r)
        self.assertRegex(run, r"-m 0755 /home/sentinel /home/sentinel/\.config")
        self.assertRegex(run, r"-m 0700 /home/sentinel/\.config/sentinel")
        env = " ".join(r for i, r in final if i == "ENV")
        for want in ("USER=sentinel", "LOGNAME=sentinel", "HOME=/home/sentinel", "SENTINEL_CONTAINER=1"):
            self.assertIn(want, env)

    def test_review_no_expose_so_publish_all_cannot_open_a_port(self):
        self.assertEqual([r for i, r in instructions() if i == "EXPOSE"], [])
        dash = re.sub(r"\s+", " ", (ROOT / "docs" / "dashboard.md").read_text())
        self.assertIn("-P", dash)
        self.assertIn("--init", dash)

    def test_review_runtime_dependencies_are_pinned_to_the_gate_versions(self):
        run = " ".join(r for i, r in stages()[-1] if i == "RUN" and "pip install" in r)
        pins = dict(re.findall(r'"(\w+)==([\d.]+)"', run))
        self.assertEqual(set(pins), {"pyyaml", "jsonschema"})
        self.assertEqual(pins, {"pyyaml": "6.0.3", "jsonschema": "4.19.2"})  # the versions the release gate ran with
        deps = (ROOT / "pyproject.toml").read_text()
        self.assertIn('"pyyaml>=6"', deps)
        self.assertIn('"jsonschema>=4"', deps)

    def test_review_the_guide_recommends_init_and_a_private_config_folder(self):
        text = re.sub(r"\s+", " ", (ROOT / "docs" / "dashboard.md").read_text())
        self.assertIn("docker run --rm -it --init -p", text)
        self.assertIn("mkdir -m 700 -p", text)
        self.assertIn("SENTINEL_APPROVER_NAME", text)
        self.assertIn("--public-host localhost:9000", text)
        self.assertIn("-p 127.0.0.1:9000:8765", text)
        self.assertIn("/work", text)
        self.assertIn("--allow-peer", text)

    def test_review_the_migration_removes_the_old_git_tool(self):
        for f in ("docs/migration-1.1.md", "docs/installation.md"):
            text = (ROOT / f).read_text()
            with self.subTest(f=f):
                self.assertIn("uv tool uninstall sentinel && uv tool install sentinel-pipeline", text)
                self.assertIn("pipx uninstall sentinel && pipx install sentinel-pipeline", text)

    def test_AC_SEC_10k_the_help_states_the_rule(self):
        r = subprocess.run([sys.executable, SENTINEL, "dashboard", "--help"], capture_output=True, text=True, env={**os.environ, "NO_COLOR": "1", "COLUMNS": "200"})
        self.assertEqual(r.returncode, 0, r.stderr)
        text = re.sub(r"\s+", " ", re.sub(r"\x1b\[[0-9;]*m", "", r.stdout))
        for want in ("--bind", "--public-host", "127.0.0.1:PORT only"):
            self.assertIn(want, text)


def open_tree(path):
    """Make a workspace usable by any container uid (the runner is not necessarily uid 1000): a+rwX on the whole tree."""
    subprocess.run(["chmod", "-R", "a+rwX", str(path)], check=True)


def docker(*args, timeout=60, **kw):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, **kw)


def docker_problem():
    if not shutil.which("docker"):
        return "the docker command is not installed"
    try:
        r = docker("info", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"docker info failed: {e}"
    if r.returncode:
        return "no usable docker daemon: " + ((r.stderr or r.stdout).strip().splitlines() or ["docker info failed"])[0][:160]
    return None


_IMAGE = []


def image():
    if _IMAGE:
        return _IMAGE[0]
    tag = f"sentinel-test:{uuid.uuid4().hex[:10]}"
    r = docker("build", "-t", tag, str(ROOT), timeout=1800)
    if r.returncode:
        raise AssertionError("docker build failed:\n" + (r.stdout + r.stderr)[-1500:])
    unittest.addModuleCleanup(lambda: docker("rmi", "-f", tag))
    _IMAGE.append(tag)
    return tag


class H(Http):
    """The browser's view: Host is localhost:<published port>."""

    def req(self, *a, **kw):
        if kw.get("host", True) is True:
            kw["host"] = f"localhost:{self.port}"
        return super().req(*a, **kw)


PROBLEM = docker_problem()


@unittest.skipIf(PROBLEM, f"docker is not usable here ({PROBLEM}); pending owner run on a machine with docker, see tests/release/manual.json")
class Runtime(SV):
    """The image started for real."""

    @classmethod
    def setUpClass(cls):
        cls.tag = image()

    def setUp(self):
        super().setUp()
        self.me = f"{os.getuid()}:{os.getgid()}"
        self.cfgmount = Path(tempfile.mkdtemp(prefix="sentinel-cfg-"))
        self.cfgmount.chmod(0o700)
        self.addCleanup(shutil.rmtree, self.cfgmount, True)
        self.names, self.volumes = [], []
        self.addCleanup(self.remove_all)

    def remove_all(self):
        for n in self.names:
            docker("rm", "-f", n)
        for v in self.volumes:
            docker("volume", "rm", "-f", v)

    def name(self):
        n = "sentinel-test-" + uuid.uuid4().hex[:8]
        self.names.append(n)
        return n

    def start(self, *, user=True, config=None, args=None, host_port=None, extra=(), uid=None):
        """`docker run --rm -it` under a pseudo-terminal; returns (proc, host port, token)."""
        hp = host_port or free_port()
        name = self.name()
        cmd = ["docker", "run", "--rm", "-it", "--name", name, "-p", f"127.0.0.1:{hp}:8765", "-v", f"{self.ws}:/work",
               *([] if config is False else ["-v", config or f"{self.cfgmount}:/home/sentinel/.config/sentinel"]),
               *(["--user", uid or self.me] if user else []), *extra, self.tag,
               *(args or ["dashboard", "--no-open", "--bind", "0.0.0.0", "--port", "8765", "--public-host", f"localhost:{hp}"])]
        p = TtyProc(self, cmd)
        p.container = name
        end = time.time() + 60
        while not URL.search(p.text()) and time.time() < end:
            if not p.pump(0.2) and p.exited():
                break
        m = URL.search(p.text())
        self.assertTrue(m, p.text())
        self.assertEqual(int(m.group(1)), hp)
        return p, hp, m.group(2)

    def one_shot(self, *args, user=True, tty=False, mount=True):
        cmd = ["docker", "run", "--rm", *(["-it"] if tty else []), *(["--user", self.me] if user else []),
               *(["-v", f"{self.ws}:/work"] if mount else []), *args]
        return docker(*cmd, timeout=120)

    # ---- AC-OPS-07
    def test_AC_OPS_07c_the_image_size_stays_within_budget(self):
        size = int(docker("image", "inspect", "--format", "{{.Size}}", self.tag).stdout.strip())
        self.assertLessEqual(size, BUDGET, f"{size / 1e6:.0f} MB")

    def test_AC_OPS_07d_the_documented_docker_run_command_prints_the_login_url(self):
        self.spec_review(SLUG, 3)
        import socket
        open_tree(self.ws)
        with socket.socket() as probe:
            hp = free_port() if probe.connect_ex(("127.0.0.1", 8765)) == 0 else 8765
        vol = "sentinel-test-config-" + uuid.uuid4().hex[:8]
        self.volumes.append(vol)
        words = documented_command().split()
        # the documented command with this test's image, workspace, volume and (when 8765 is busy) host port
        cmd = [self.tag if w == IMAGE_NAME else w for w in words]
        cmd = [w.replace('"$PWD"', str(self.ws)).replace("$PWD", str(self.ws)).replace('"', "") for w in cmd]
        cmd = [w.replace("sentinel-config:", vol + ":") for w in cmd]
        cmd = [w.replace("127.0.0.1:8765:8765", f"127.0.0.1:{hp}:8765") for w in cmd]
        cmd[2:2] = ["--name", self.name()]
        if hp != 8765:
            cmd += ["dashboard", "--no-open", "--bind", "0.0.0.0", "--port", "8765", "--public-host", f"localhost:{hp}"]
        p = TtyProc(self, cmd)
        end = time.time() + 60
        while not URL.search(p.text()) and time.time() < end:
            if not p.pump(0.2) and p.exited():
                break
        m = URL.search(p.text())
        self.assertTrue(m, p.text())
        self.assertEqual(int(m.group(1)), hp)
        c = H(hp, m.group(2)).login()
        page = c.get("/")
        self.assertEqual(page.status, 200)
        self.assertIn('<div id="root">', page.text)
        self.assertNotIn("UI not installed", page.text)
        self.assertEqual([x["name"] for x in c.get("/api/v1/projects").json["projects"] if "name" in x], ["digital-hr"])

    def test_AC_OPS_07f_stopping_the_container_is_clean(self):
        p, hp, token = self.start()
        self.assertTrue((self.cfgmount / "server.json").exists())
        t0 = time.time()
        r = docker("stop", "-t", "10", p.container, timeout=40)
        code, out = p.finish(30)
        self.assertEqual((r.returncode, code), (0, 0), out)
        self.assertLess(time.time() - t0, 10)
        self.assertFalse((self.cfgmount / "server.json").exists())

    def test_AC_OPS_07g_config_and_token_live_in_the_named_volume_with_private_modes(self):
        open_tree(self.ws)
        vol = "sentinel-test-config-" + uuid.uuid4().hex[:8]
        self.volumes.append(vol)
        mount = f"{vol}:/home/sentinel/.config/sentinel"
        p, hp, token = self.start(user=False, config=mount)
        modes = docker("run", "--rm", "-v", f"{vol}:/c", "--entrypoint", "stat", self.tag, "-c", "%a %n", "/c", "/c/server.json", "/c/projects.json").stdout
        self.assertEqual(sorted(modes.split("\n")[:3]), sorted(["700 /c", "600 /c/server.json", "600 /c/projects.json"]), modes)
        docker("stop", "-t", "10", p.container, timeout=40)
        p.finish(30)
        p2, hp2, token2 = self.start(user=False, config=mount)
        self.assertNotEqual(token, token2)
        projects = H(hp2, token2).login().get("/api/v1/projects").json["projects"]
        self.assertEqual(len([x for x in projects if x.get("name") == "digital-hr"]), 1)
        listing = docker("run", "--rm", "-v", f"{vol}:/c", "--entrypoint", "cat", self.tag, "/c/projects.json").stdout
        self.assertEqual(listing.count("/work"), 1, listing)

    def test_AC_OPS_07h_the_container_runs_as_a_non_root_user(self):
        r = self.one_shot("--entrypoint", "id", self.tag, "-un", user=False, mount=False)
        self.assertEqual(r.stdout.strip(), "sentinel", r.stderr)
        r = self.one_shot("--entrypoint", "id", self.tag, "-u", user=False, mount=False)
        self.assertNotEqual(r.stdout.strip(), "0")

    def test_AC_OPS_07i_files_written_in_the_workspace_belong_to_the_host_user(self):
        # a uid that is neither the runner's nor the image user's (1000), so "belongs to the --user uid" proves the flag worked
        uid = 4321 if os.getuid() != 4321 else 4322
        subprocess.run(["git", "init", "-q", str(self.ws)], check=False)
        open_tree(self.ws)
        r = docker("run", "--rm", "--user", f"{uid}:{uid}", "-v", f"{self.ws}:/work", "--entrypoint", "sh", self.tag, "-c",
                   "touch /work/from-container.txt && git -C /work status --short", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("dubious ownership", r.stderr)
        self.assertEqual((self.ws / "from-container.txt").stat().st_uid, uid)
        self.assertNotEqual(uid, 1000)

    def test_review_any_uid_can_run_the_dashboard_with_a_private_config_folder(self):
        """`--user 4321:4321`: the uid has no passwd entry; HOME and USER come from the image, the config folder is a private mount."""
        open_tree(self.ws)
        mount = "/home/sentinel/.config/sentinel"
        p, hp, token = self.start(uid="4321:4321", config=False, extra=("--tmpfs", f"{mount}:mode=0700,uid=4321,gid=4321"))
        self.assertNotIn("Traceback", p.text())
        c = H(hp, token).login()
        self.assertEqual(c.get("/").status, 200)
        self.assertEqual(c.get("/api/v1/projects").status, 200)
        r = docker("exec", p.container, "id", "-u")
        self.assertEqual(r.stdout.strip(), "4321", r.stderr)

    def test_AC_OPS_07k_no_terminal_no_server(self):
        r = self.one_shot(self.tag, "dashboard", "--no-open")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("E_NOT_TTY", r.stdout + r.stderr)
        self.assertNotIn("auth?t=", r.stdout + r.stderr)
        r = self.one_shot(self.tag, "approve", SLUG, "spec")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("E_NOT_TTY", r.stdout + r.stderr)

    def test_AC_OPS_07l_a_dashboard_approval_needs_the_hash_prefix_as_in_phase_f(self):
        h = self.spec_review(SLUG, 3)
        p, hp, token = self.start()
        c = H(hp, token).login()
        url = f"/api/v1/tasks/{SLUG}/approvals"
        r = c.post(url, {"gate": "specification", "sha256": h, "decision": "approve"})
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)
        r = c.post(url, {"gate": "specification", "sha256": h, "confirmation": "", "decision": "approve"})
        self.assertEqual((r.status, r.code), (400, "E_VALIDATION"), r.text)
        self.assertEqual([a["state"] for a in self.approvals("specification")][-1], "IN_REVIEW")

    def test_AC_OPS_07m_no_ai_tool_cli_is_in_the_image(self):
        for tool in ("claude", "codex", "gemini", "aider", "opencode", "node", "npm"):
            with self.subTest(tool=tool):
                r = self.one_shot("--entrypoint", "sh", self.tag, "-c", f"command -v {tool}", user=False, mount=False)
                self.assertNotEqual(r.returncode, 0, r.stdout)
                self.assertEqual(r.stdout.strip(), "")

    def test_AC_OPS_07n_the_image_holds_no_secret(self):
        env = docker("image", "inspect", "--format", "{{json .Config.Env}}", self.tag).stdout
        hist = docker("history", "--no-trunc", "--format", "{{.CreatedBy}}", self.tag).stdout
        for text in (env, hist):
            self.assertNotRegex(text, r"(?i)(token|secret|password|passwd|api[_-]?key|credential)")
        r = self.one_shot("--entrypoint", "sh", self.tag, "-c",
                          "ls -A /home/sentinel/.config/sentinel; ls -A /home/sentinel | grep -v '^\\.\\(bash\\|profile\\|config\\)' ; "
                          "find / -xdev \\( -name .sentinel -o -name .claude -o -name .env -o -name 'credentials*' -o -name 'id_rsa*' \\) -not -path '/proc/*' -not -path '/usr/*' 2>/dev/null",
                          user=False, mount=False)
        self.assertEqual(r.stdout.strip(), "", r.stdout)

    def test_AC_SEC_10i_the_container_is_reachable_only_on_the_host_loopback(self):
        import socket
        p, hp, token = self.start()
        s = socket.create_connection(("127.0.0.1", hp), timeout=5)
        s.close()
        addrs = set()
        for line in subprocess.run(["ip", "-o", "-4", "addr"], capture_output=True, text=True).stdout.splitlines():
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", line)
            if m and not m.group(1).startswith("127."):
                addrs.add(m.group(1))
        for ip in addrs:
            with self.subTest(ip=ip):
                s = socket.socket()
                s.settimeout(3)
                self.assertNotEqual(s.connect_ex((ip, hp)), 0)
                s.close()
        # the container's own address is refused by the Host check
        r = Http(hp, token).req("GET", "/api/v1/session", host=f"172.17.0.2:{8765}")
        self.assertEqual((r.status, r.code), (403, "E_HOST"))


if __name__ == "__main__":
    unittest.main()
