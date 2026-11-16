# Phase I: One-command installation, dashboard image and release workflow (Gherkin for review)

Scope: OPS-01 and OPS-02 (installation and version), SEC-01 and SEC-02 (loopback bind, Host and Origin checks, token, kept in the container case), SEC-03 (approvals still need a human terminal or the typed hash prefix), TST-01 (the release gate covers this phase). Decisions used (owner, delegated to the orchestrator): PyPI distribution name `sentinel-pipeline` (console script `sentinel` and import package `sentinel` unchanged); `uv tool install sentinel-pipeline` or `pipx install sentinel-pipeline`; Docker image `ghcr.io/chhunlyyy/sentinel` (tags `1.1.0` and `latest`) for the dashboard and server use case only, the AI-tool-facing CLI stays on the host; port 8765 for Docker; the host CLI keeps the Phase F port rule (`sentinel dashboard` picks a free port, `--port` accepts 1024 to 65535, so `sentinel dashboard --port 8765` is valid and documented). Contracts: `docs/architecture/security-architecture.md` sections 2 to 4, Phase F `server_lifecycle.feature`.

- PI-01 features: `pypi_install.feature`, `docker_dashboard.feature`, `dashboard_server_flags.feature`, `release_automation.feature`.

Not in Phase I: running the release workflow, tagging, publishing to PyPI, pushing the image (all stay with the owner), AI tool CLIs in the image, running provider tasks inside the container, Windows or macOS install tests, image signing or SBOM, multi-architecture images.

## Files

| Feature | Scenarios | Outline rows | Main requirements |
|---|---|---|---|
| `features/pypi_install.feature` | 11 | 6 | OPS-01, OPS-02 |
| `features/docker_dashboard.feature` | 18 | 7 | OPS-01, SEC-01, SEC-03 |
| `features/dashboard_server_flags.feature` | 8 | 22 | SEC-01, SEC-02 |
| `features/release_automation.feature` | 10 | 0 | OPS-01, OPS-02, TST-01 |
| Total | 47 | 35 | |

By type: 20 `@unit`, 10 `@integration`, 14 `@security`, 2 `@e2e`, 1 `@performance`.

All four files load with `sentinel/scripts/artifacts.py` `parse_gherkin` with no errors; every scenario has one `@AC` tag, one type tag, one priority tag and one known `@cov-` tag.

New AC ids (checked with grep against Phases A to H, `tests/`, `sentinel/`, `docs/` and `SPEC.md`; none used): `AC-OPS-06a`-`k` (PyPI install), `AC-OPS-07a`-`o` (Docker image), `AC-OPS-08a`-`j` (release workflow), `AC-SEC-10a`-`k` (`--bind`, `--public-host`, publishing).

## Coverage table

| Category | Status |
|---|---|
| Happy path | covered (names, wheel contents, uv and pip install, installed dashboard, documented docker command, bind in a container, one-liners in the README) |
| Invalid input | covered (`--bind` values and environment values, `--public-host` values) |
| Boundary | covered (small build context, one project entry after two starts) |
| Authentication | covered (token printed, new at each start, cookie and CSRF unchanged) |
| Authorization | covered (bind refused on a host, environment alone does not widen, Host and Origin accept only the public host, no terminal no server, approval needs the hash prefix, non-root user, publish on 127.0.0.1 only, trusted publishing and job permissions) |
| Data integrity | covered (config volume modes 0700 and 0600, files owned by the host user, tag equals version) |
| Error handling | covered (release build with stale dashboard, pending manual checks fail the workflow) |
| Regression | covered (dependencies unchanged by the rename, git install documented, port rule kept, Phase F flags rule kept, gate covers phase I) |
| Performance / security | security covered (no AI CLI, no secret, no browser, pinned actions, no secrets on command lines); image size at most 250 MB |

## How the tests will run

- `tests/test_dashboard_flags.py` (`AC-SEC-10a`-`h`): `sentinel dashboard` under a pseudo-terminal as in Phase F, with `SENTINEL_CONTAINER` set or not; sockets read from `/proc`.
- `tests/test_pypi_install.py` (`AC-OPS-06*`): the wheel of `tools/release_gate.py` (`SENTINEL_RELEASE=1`), installed by name from a local wheelhouse with `--no-index` (uv and pip); doc checks read the Markdown.
- `tests/test_docker_install.py`: static checks of `Dockerfile` and `.dockerignore` (`AC-OPS-07a`, `b`, `e`, `j`, `o`, `AC-SEC-10j`, `k`) always run. The checks that start the image (`AC-OPS-07c`, `d`, `f`-`i`, `k`-`n`, `AC-SEC-10i`) build it once, run it with `-it` under a pseudo-terminal, and skip with the reason where no docker daemon is usable. They remove every container, volume and image they made.
- `tests/test_release_workflow.py` (`AC-OPS-08*`): parses `.github/workflows/release.yml`; the workflow is never run by the tests.
- Gate: `tools/release_gate.py` lists `phaseI`; the pinned hash is in `tests/release/phase_hashes.json` and `IMPLEMENTATION_STATUS.md`. The docker runtime ids are recorded in `tests/release/manual.json` as pending owner until they pass on a machine with docker (the workflow's gate job runs on a runner that has it).

## Set hash

Command, run from `plan/v1.1/phaseI`:

```sh
find features -name '*.feature' | LC_ALL=C sort | while read f; do printf '%s\0' "$f"; cat "$f"; printf '\0'; done | sha256sum
```

Hash: `18b23bc34b26a39dfe0899fe9e96740e099926a811b0bd2a52a208d56ded7142`

## Open points for the reviewer

Each point is a choice made where the owner decisions leave room. Approving this set approves these choices.

1. **Wheel file name changes.** The distribution is `sentinel-pipeline`, so the wheel is `sentinel_pipeline-1.1.0-py3-none-any.whl` and the dist-info folder `sentinel_pipeline-1.1.0.dist-info`. This supersedes the file name in the Phase H scenarios `AC-OPS-02a` and `AC-OPS-01h` (wheel named `sentinel-1.1.0-...`); the Phase H tests and docs are updated to the new name, the Phase H Gherkin stays as approved (hash unchanged).
2. **`--bind` accepts only `0.0.0.0`, and only in a container (review decision, orchestrator).** Other values, and `0.0.0.0` unless `SENTINEL_CONTAINER=1` AND container evidence exists (`/.dockerenv` or `/run/.containerenv`), exit 2 with the usage. A server bound to `0.0.0.0` closes with 403 (before the body is parsed) every peer that is not loopback or the container's default gateway (`/proc/net/route`); `--allow-peer IP` (repeatable) is the override for rootless Docker and Docker Desktop. `ApiServer` itself refuses any bind but `127.0.0.1`, or `0.0.0.0` with the same container checks (the Phase F rule `AC-SEC-01c`, `--bind 192.168.1.20` exits 2, still holds). `--host` and `--listen` stay unknown options. The environment variable alone changes nothing.
3. **`--public-host` is `localhost:PORT` or `127.0.0.1:PORT`, port 1024 to 65535.** It adds that one value to the Host and Origin allow-list (case-insensitive) and sets the host name in the printed URL; the loopback names with the server's own port stay accepted. A host name for a remote machine is never accepted. Outside a container its port must equal the server's `--port`; inside a container it may differ (the published port), and docs pass it explicitly for a custom port. `sentinel dashboard` attaching to a running server prints the URL with it too.
4. **Docker port 8765 is fixed in the image command.** A different host port needs `-p 127.0.0.1:9000:8765` and the whole command `... ghcr.io/chhunlyyy/sentinel dashboard --no-open --bind 0.0.0.0 --port 8765 --public-host localhost:9000`. The image has no `EXPOSE` (so `-P` publishes nothing) and no `HEALTHCHECK` (every API route needs the token). The documented one-liner does not need it.
5. **Config volume and `--user`.** The named volume is initialised for uid 1000. With another uid the docs say to create a folder with `mkdir -m 700 -p` and mount it instead of the named volume. `/home/sentinel` and `.config` are 0755 and the image sets `USER`, `LOGNAME` and `HOME`, so any uid works; an unknown uid is recorded as `uid<N>`. `SENTINEL_APPROVER_NAME` (container only) sets the approver display name. No entrypoint script changes ownership.
6. **The image runs the dashboard only.** Dispatching a task from the dashboard needs a provider CLI, which the image does not have; the task stays queued until a host process runs it. The docs say so.
7. **No digests on base images.** `node:22-slim` and `python:3.12-slim` are pinned by tag; digest pinning needs a registry lookup and is left to the owner.
8. **Docker tests cannot run in every environment.** Where no docker daemon is usable (as on the machine that built this phase: the user is not in the `docker` group and rootless docker is blocked), the image runtime tests skip with the reason, the ids stay in `tests/release/manual.json` as pending owner, and the image build and size are unverified there. The static Dockerfile checks and the server flag tests always run.
9. **Workflow job order.** `gate` then `build` then `publish-pypi` then `publish-image`, so a failed PyPI upload never pushes an image. The image is built by Docker from the same tag, not from the PyPI artifact.
10. **Actions are pinned by exact version tag, not by commit hash.** The tests accept either form; the owner may replace tags with hashes.
11. **A fourth feature file.** `dashboard_server_flags.feature` holds the server option scenarios (`AC-SEC-10a`-`h`) that do not belong to the image or the install.
12. **Supersession of the Phase H wheel name (approved by the orchestrator under the owner's delegation).** Phase I renames the wheel to `sentinel_pipeline-1.1.0-py3-none-any.whl`. The Phase H scenarios `AC-OPS-02a` and `AC-OPS-01h` name `sentinel-1.1.0-py3-none-any.whl`; that text is superseded by this point. The Phase H `.feature` files are not edited (their hash stays).
13. **Node is pinned to `22.18.0`** in `dashboard/.nvmrc`, the workflow and the `Dockerfile` (the minimum of the dashboard's `engines`).
