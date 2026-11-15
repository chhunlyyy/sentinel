# Dashboard

The dashboard is a local web page for watching runs, reading what the engine recorded and making the human decisions of a version 2 run. It is a client of the engine: it holds no orchestration logic and cannot do anything the command line cannot. It works fully offline; every file it needs is served by the local server, and Node is not needed to use it. The UI is part of the release wheel; a git install has no UI (see [installation](installation.md#the-dashboard-ui)).

## Starting the dashboard

```bash
cd my-workspace
sentinel dashboard
```

`sentinel dashboard` needs an interactive terminal. It starts a server on `127.0.0.1` (a free port, or `--port 8750`), registers the workspace you started it in, prints a one-time **session URL** and opens your browser on it (`--no-open` prints the URL and does not open a browser). The URL holds a start token; the server exchanges it for a session cookie and redirects, so the token does not stay in the address bar. A second `sentinel dashboard` in another workspace attaches to the running server and registers that workspace too. Stop the server with Ctrl+C in its terminal. When it stops, or the cookie is gone, the page shows "Session ended"; run `sentinel dashboard` again and open the new URL.

The server listens on the loopback address only and accepts only requests for its own address. Read [the security notes](security.md#dashboard-token-and-residual-risk-r1) once: an agent that runs as your OS user can read the token file, which is residual risk R1.

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

## What is read only in 1.1.0

In 1.1.0 the dashboard shows projects, repositories and configuration **read only** (decision G-1). It points to the command or file for each change. A later release adds the forms.

| You want to | Do this |
|---|---|
| Create a project | `sentinel init` in the workspace, then `sentinel dashboard` there registers it |
| Add, edit, remove or reorder repos | Edit `repos` in `sentinel.config.yaml`, or run `sentinel init --force` |
| Change settings, policies, providers, agents or commands | Edit `sentinel.config.yaml`; `sentinel doctor` validates it (see [config](config.md)) |
| Restore an earlier configuration | Copy the version from the history in the Projects screen into `sentinel.config.yaml` |
| Import or export a project config | Copy the file |
| Change the Sentinel installation | Reinstall, see [installation](installation.md) |
| Generate agent configs and deny rules | `sentinel sync-adapters` |
| Test a provider | `sentinel doctor --check-models` |
| Publish specs and regression tests | `sentinel sync push` (version 2 runs never push by themselves) |
| Pause a run or request intervention | Not available in 1.1.0; you can cancel, resume and retry |

Approving a specification or Gherkin set, accepting a run, cancelling, resuming, retrying and creating a task all work in the dashboard, and each is recorded in the audit with the channel `dashboard`.
