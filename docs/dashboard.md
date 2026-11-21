# Dashboard

The dashboard is a local web page for watching runs, reading what the engine recorded and making the human decisions of a version 2 run. It is a client of the engine: it holds no orchestration logic and cannot do anything the command line cannot. It works fully offline; every file it needs is served by the local server, and Node is not needed to use it. The UI is part of the PyPI wheel (`uv tool install sentinel-pipeline`); a git install has no UI (see [installation](installation.md#the-dashboard-ui)).

## Starting the dashboard

```bash
cd my-workspace
sentinel dashboard
```

`sentinel dashboard` needs an interactive terminal. It starts the Sentinel background service if it is not already running (listening on `127.0.0.1` on a free port, or the one you fix with `--port`, for example `sentinel dashboard --port 8765`; a port must be from 1024 to 65535), registers the workspace you started it in, prints a one-time **session URL** and opens your browser on it (`--no-open` prints the URL and does not open a browser). The URL holds a start token; the server exchanges it for a session cookie and redirects, so the token does not stay in the address bar. A second `sentinel dashboard` in another workspace attaches to the running server and registers that workspace too.

Closing the terminal no longer stops the factory: the service continues running in the background. To stop the service, run `sentinel stop` (or `sentinel service stop`). To run the server in the foreground as in earlier versions (stopping on Ctrl+C), pass `--foreground`:

```bash
sentinel dashboard --foreground
```

When the server stops, or the session cookie is gone, the page shows "Session ended"; run `sentinel dashboard` again and open the new URL. You can also inspect or manage the service directly with `sentinel service start|stop|status|run|autostart` (see [operations](operations.md#service-management)).

The server listens on the loopback address only and accepts only requests for its own address. Read [the security notes](security.md#dashboard-token-and-residual-risk-r1) once: an agent that runs as your OS user can read the token file, which is residual risk R1.

## Docker

The image `ghcr.io/chhunlyyy/sentinel` (tags `1.3.0` and `latest`) serves only the dashboard. The CLI your AI tool runs stays on the host (`uv tool install sentinel-pipeline`); the image has no AI tool CLI, no Node and no secret. One command, run in the workspace folder:

```bash
docker run --rm -it --init -p 127.0.0.1:8765:8765 -v "$PWD":/work -v sentinel-config:/home/sentinel/.config/sentinel ghcr.io/chhunlyyy/sentinel
```

It prints `http://localhost:8765/auth?t=<token>`; open that URL in your browser. The dashboard shows the project mounted at `/work` (always mount the workspace there); it is listed under the name `work`, the name of the mount folder, not the name of your folder on the host. The command includes `--init`: it runs a small init process in the container, so signals reach the server and no zombie process is left.

- **Publish on 127.0.0.1 only.** Always write `-p 127.0.0.1:8765:8765`. A bare `-p 8765:8765` or `-p 0.0.0.0:8765:8765` exposes the dashboard to your network, and its token is the only protection. The image has no `EXPOSE` on purpose: `docker run -P` would publish every exposed port on all interfaces, so with this image `-P` publishes nothing. Inside the container the server listens on all interfaces because Docker needs that. `--bind 0.0.0.0` is accepted only when the image sets `SENTINEL_CONTAINER=1` and the process really runs in a container (`/.dockerenv` or `/run/.containerenv` exists); on a host it is refused with exit code 2. Bound that way, the server answers only a loopback peer and the container's default gateway (where a port published on `127.0.0.1` arrives from) and refuses every other address with 403 before it reads the request. With rootless Docker or Docker Desktop the published port can arrive from another address; the refusal then shows in the browser, and you add `--allow-peer <ip>` (repeatable) to the command with the address of the gateway or proxy. It accepts only `localhost:PORT` and `127.0.0.1:PORT` in the `Host` and `Origin` headers (`--public-host`).
- **Another host port.** The server port stays 8765 inside the container; publish another host port and name it in `--public-host`. Because the command line replaces the image's default arguments, give the whole command:

  ```bash
  docker run --rm -it --init -p 127.0.0.1:9000:8765 -v "$PWD":/work -v sentinel-config:/home/sentinel/.config/sentinel ghcr.io/chhunlyyy/sentinel dashboard --no-open --bind 0.0.0.0 --port 8765 --public-host localhost:9000
  ```

  Outside a container `--public-host` must name the server's own `--port`; the different port is allowed only in the container.
- **A terminal is required.** `-it` gives the server the terminal it needs, as on the host; without `-t` it refuses to start. Approvals still need the hash prefix you type, in the dashboard or in `sentinel approve` on the host.
- **File ownership.** Add `--user $(id -u):$(id -g)` so files written in `/work` belong to you. The config folder in the named volume is created for the image user (uid 1000); with another uid, create a private folder you own and mount it instead of the named volume: `mkdir -m 700 -p "$HOME/.config/sentinel-docker"`, then `-v "$HOME/.config/sentinel-docker":/home/sentinel/.config/sentinel`. Create it first with that command: if Docker creates the folder, it belongs to root and the server cannot use it. Any uid works, also one with no entry in the image's user list.
- **Who approved.** Inside the container the operating system user is `sentinel`. To record your name as the approver of a dashboard approval, add `-e SENTINEL_APPROVER_NAME="$(git config user.name)"` to the command; it is honoured only in the container.
- **Persistence.** The config folder (`projects.json`, `server.json` with the token) lives in the volume `sentinel-config` with mode 0700 and 0600 files. The token is new at every start.
- **No browser, no tools.** The container never opens a browser (`--no-open`), and it cannot run a provider CLI. Runs are dispatched by the host. git trusts `/work` (`safe.directory`).
- **No health check.** The image has no `HEALTHCHECK`: every API route needs the session token and a check must not hold one.
- Stop it with Ctrl+C or `docker stop`.

## Screens

| Screen | What it shows |
|---|---|
| Overview | Setup readiness, runs that need you, recent runs of every registered project. |
| Projects | Every registered workspace: repos, configuration (effective values and where each comes from, version history and diffs), runs, audit rows. |
| Tasks | Runs of every project with filters, and **Create task**, which creates a version 2 run and queues it for the AI tool. Creating a task approves nothing. |
| My Approvals | The specification and Gherkin reviews waiting for you, with the text, the diff to the earlier version and the hash to confirm. Approve, request changes or reject here, as with `sentinel approve`. |
| Runs | One run: state and execution and acceptance status, the workflow graph, logs of each task, changes and diffs, TDD cycles with their evidence, verification and the trace from requirement to code. Cancel, resume and retry are engine transitions; `resolve` is CLI only (`sentinel resolve`). |
| Quality | Verification and regression results across runs. |
| Reports | Metrics from the registry: lead time, acceptance rate, approval wait, retries, provider failure rate, TDD cycles, verification pass rate, rework and the cost tasks reported. A value that cannot be computed shows "Not reported" with the reason. See [operations](operations.md#stats-and-analytics). |
| Settings | Installation and health checks (the same checks as `sentinel doctor`). |

The bell in the header lists notifications. Opening one only takes you to the page; it never approves anything. "Enable desktop notifications" asks the browser for permission once; see [operations](operations.md#notifications).

Every screen works with the keyboard alone, labels every control, and meets WCAG 2.1 AA in the automated checks. Everything that comes from runs, users or agents (specifications, logs, diffs, names, notification text) is shown as text; it is never interpreted as HTML and links in it are not followed.

## Projects, providers and agents

Since 1.2.0 you can set up most things in the dashboard. Settings > Providers lists the AI tools installed on this machine and picks the orchestrator; Settings > Agents routes each agent role to a provider and model. Projects has "Create project" (name, folder, one or more repositories, local or shared git) and "Register existing folder", and the Repositories tab adds and removes repositories.

| You want to | Do this |
|---|---|
| Create a project | "Create project" on the Projects screen, or `sentinel init` in the workspace, then `sentinel dashboard` there registers it |
| Add or remove repos | Repositories tab of the project (a project keeps at least one repository), or edit `repos` in `sentinel.config.yaml` |
| Delete a project | "Delete project" on the project page. It only removes the project from the dashboard; its folder, configuration and `.sentinel` state stay on disk. Refused while a run is active |
| Pick the provider that drives runs | `sentinel dashboard claude` (a runner id), the list shown when you give none, or Settings > Providers |
| Route an agent to a provider and model | Settings > Agents (this project or a global default), or `agents` in `sentinel.config.yaml` |
| Change other settings, policies or commands | Edit `sentinel.config.yaml`; `sentinel doctor` validates it (see [config](config.md)) |
| Restore an earlier configuration | Copy the version from the history in the Projects screen into `sentinel.config.yaml` |
| Import or export a project config | Copy the file |
| Change the Sentinel installation | Reinstall, see [installation](installation.md) |
| Generate agent configs and deny rules | `sentinel sync-adapters` |
| Test a provider | The Test button in Settings > Providers, or `sentinel doctor --check-models` |
| Publish specs and regression tests | `sentinel sync push` (version 2 runs never push by themselves) |
| Pause a run or request intervention | Not available; you can cancel, resume and retry |

A global default set under Settings > Agents is copied into the projects you create afterwards; the engine does not merge it at run time.

Approving a specification or Gherkin set, accepting a run, cancelling, resuming, retrying and creating a task all work in the dashboard, and each is recorded in the audit with the channel `dashboard`.

## The pictures in the README

The screenshots, the animated tour and the terminal picture in the README are generated, not drawn by hand. The dashboard ones come from its built-in sample data (two imaginary projects, the same data the browser tests use), and the terminal picture runs a short real session in a throwaway workspace. To make them again:

```bash
cd dashboard
npm ci && npm run build
python3 scripts/terminal_demo.py     # runs real commands, writes docs/images/.terminal.txt
node scripts/showcase.mjs            # screenshots and the frames of the tour
python3 scripts/frames_to_gif.py     # builds dashboard-tour.gif and shrinks the PNGs (needs Pillow)
```

The images are in `docs/images/`. The README links them by their address on the `main` branch, so that they show on the PyPI page as well.
