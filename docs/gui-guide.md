# Dashboard user guide

This guide shows how to use Sentinel from the browser, from the first start to an accepted change. For flags, Docker and security details of the dashboard itself, see the [dashboard reference](dashboard.md). For the same work in a terminal, see the [command-line guide](cli-guide.md).

## Start the dashboard

```bash
sentinel dashboard
```

This starts the Sentinel background service (or attaches to the one that runs), prints a one-time session link and opens your browser on it. The service keeps working when you close the browser or the terminal. Run `sentinel dashboard` again to get a new link, and `sentinel stop` to stop the service.

When no project exists yet, the dashboard opens on **Welcome to your software factory**: it shows the background service, the AI providers found on this machine, and a **Create a project** button. Once a project exists, the dashboard opens on the **Factory floor**. The overview is always at **Overview** in the menu.

## Create a project

Click **Create project** on the Projects screen (or **Create a project** on the welcome screen). The wizard has five steps; you can go **Back** at any time.

1. **Repositories.** Name the project and add one or more repository folders. Sentinel never moves them; agents work in branches you review.
2. **We looked at your repos.** For each repository Sentinel shows the detected stack, the test, build and lint commands, and the **Tracked branches** (the branches your team merges to, for example `develop` and `main`). Change only what is wrong. A repository without a test command can still take documentation tasks.
3. **Shared team knowledge.** Paste the clone URL of your team's private shared repository and click **Test access**: it shows whether Sentinel can read and push. For a quick trial, choose the local option instead. Optionally turn on **Build knowledge from history**: Sentinel then records the changes your team made in recent months, in the background, after it showed you the estimate.
4. **Your AI team.** Sentinel suggests a provider and model for each role: fast, cheap models for triage, scenarios, planning and knowledge summaries, stronger models for the spec, the code and reviews. Change any row. Every role must use a command-line AI tool, because the factory starts the agents itself.
5. **Ready to open the factory.** The checks run (repositories, shared repo, providers). Warnings, such as a missing lint command, do not stop you. Click **Create project**; Sentinel writes `sentinel.config.yaml` in the project folder and takes you to the project.

## The project home

The project page shows what is on the factory floor, what waits for you, the knowledge base, the repositories with their readiness, and recent tasks. Each tile links to the screen behind it.

## Create a task

Open **Tasks** and click **Create task** (or use **New task** in the menu).

- **Kind**: Feature, Bug fix or Docs only.
- **Request**: what you want, in plain words. Be concrete about who may do what and what must not change.
- **I already have a spec**: check this option to provide a pre-drafted specification (by pasting text or uploading a file). The spec goes in as draft v1 and the specifier stage is skipped, while triage and human approval remain required.
- **Priority**, **Tier** and **Ticket** are optional. Leave the tier on "Decided at triage" unless you want more rigor; a tier can only raise the triage result.

As you type the request text, the **Knowledge found** side panel updates (debounced) with related past change records and project invariants from the knowledge base, linking directly to the project's knowledge screen. A slots note ("Slots: N of M busy, position K in the queue") shows current factory floor occupancy from the factory snapshot. You can click **Save as draft** to store your work in progress in the browser (persisted per project across page reloads); drafts are automatically cleared once the task is created.

Click **Create task**. The run joins the factory: it starts at once when a slot is free (two tasks per project and four agents in total by default), otherwise it waits in the queue.

## Pause the whole factory

**Pause factory** in the header (after you confirm) stops every project from starting new agent work: tasks already running finish, nothing new starts. The header then says "Factory paused". **Resume factory** starts work again; runs you paused one by one stay paused. The same switch from a terminal: `sentinel service pause` and `sentinel service resume`.

## Read the factory floor

The factory floor draws the factory as a network of stations. Each task moves along it from left to right:

```
Intake > Triage > Spec > [you approve] > Scenarios > [you approve] > Build lanes > Verify > Report > [you accept] > Knowledge
```

- **Shapes** tell who works there: a circle is an AI agent, a rounded square is the engine, an amber diamond is you.
- **Colors and labels** tell the state: done, working (glowing, with a spinning ring), needs you (amber), paused, queued, next, or later. The state is also written in the side panel, so color is never the only signal.
- **Links** between stations show the flow. The link into the station that is working moves; finished links are solid; links not reached yet are faint.
- **Build** fans out into one lane per behavior. Each lane runs Red (a failing test), Green (make it pass) and Refactor, and joins again at Verify.
- **Knowledge** sits below the path. Its dotted links show it feeding the agents: repository and module summaries, team rules and recent related changes. The link to the agent working right now glows.
- Small colored chips on a station show which tasks are there. The chips at the top switch between tasks.

A station whose agent waits for a provider usage limit shows **Waiting for usage limit · retries 14:05** (your local time) with the paused look: it is not failed, and the task starts again by itself. `sentinel resolve <slug> --retry-now` starts it at once. A notification tells you when a limit is hit.

Click a station to see it in the side panel:

- **Who**: the role, the AI tool and the model, or "engine" or "you".
- **This task**: what happened there for this task.
- **Knowledge**: what that station reads from the knowledge base.
- **Next**: the station that follows.

A station that waits for you shows **Review specification** (or the matching review); the final gate links to the report. **Open the full run: logs, diffs, evidence** opens the run.

### Control a task

Under **Control** in the side panel:

- **Note**: write a hint for the next agent ("reuse ExportService, do not add a new class") and send it. The next agent task of that run reads it once.
- **Pause** stops the factory from starting anything new for that task; work already running finishes. **Resume** continues.
- **Cancel** stops the run after you confirm.

## Approve the spec and the scenarios

When a task reaches a gate, its station turns amber and **My Approvals** shows a badge. Open the review:

1. Read the specification (or the Gherkin scenarios). The diff shows what changed since the previous version. If the specification was imported from an external AI session, its provenance is displayed next to the version badge (`(imported from a session)`). The **Knowledge used** tab lists the change records, project invariants, and repository/module summaries that the agents read when creating the document.
2. Choose **Approve**, **Request changes** or **Reject**, and add a comment for the agent if you like.
3. Type the first 8 characters of the document's hash, shown on the page, and confirm.

The typed hash proves you approved exactly the version you read. Agents cannot approve: they have no session and no terminal.

## Review the result and accept

When the build and the engine's checks are done, the run waits at **You accept**. Open the run from the floor or from **Runs**:

- **Report**: what was built, the checks the engine ran itself (tests, lint, typecheck, build, write scopes, no new failing tests), and review findings.
- **Trace**: each requirement, its acceptance criterion, the cycle that built it and the test that proves it.
- **Changes**, **TDD cycles** and **Logs**: the diffs, the Red, Green and Refactor evidence, and every agent's output.

Type the report hash prefix and **Accept** (or reject). The changes stay on a branch in each repository with a pull request draft: nothing is merged for you. In the background, Sentinel records the accepted change in the team knowledge base.

## Knowledge

The **Knowledge** screen of a project shows:

- **Status**: change records, tracked branches, module summaries and the last publish.
- **Changes**: every recorded change, with filters (all, verified from accepted runs, from git) and search. Open a record to read it.
- **Ingest now** records new merges on the tracked branches; **Snapshot** refreshes the repository and module summaries. Both run in the background.
- **Backfill history…** records older changes: Sentinel first shows how many changes it found, and starts only after you confirm.
- **Capture work done outside Sentinel**: pick a repository and copy the CI workflow file. Added to that repository, it records every merge to a tracked branch, even when nobody runs Sentinel. The card lists the secrets the workflow needs.

See [the knowledge base guide](knowledge.md) for what a record contains and how it is published.

## Settings

- **Factory service**: whether the service runs, its address and process, and the commands to stop it or start it at login (`sentinel service autostart on`).
- **Providers** and **Agents**: the AI tools on this machine (with a **Test** button) and which provider and model does each role, for this project or as the default for new projects.
- **Project settings**: every setting of `sentinel.config.yaml` as a form: commands, limits, policies, knowledge and factory settings. **Preview the YAML change** shows the exact change; **Save** writes it and keeps the previous version in the history. You can still edit the file by hand.
- **Health checks**: the same checks as `sentinel doctor`.

The bell in the header lists notifications (a gate waiting, a failed task, a failed knowledge update). Opening one only takes you to the page; it never approves anything.

## Fix routing

When the project routing blocks engine-driven runs, a **Fix routing** banner appears on the project home and on the factory floor. **Fix routing** opens a dialog with one row per blocked role, with the runner and model Sentinel suggests (the same suggestion as the Create project wizard); change any of them. **Preview the YAML change** shows the diff of `sentinel.config.yaml`; **Save** writes it through the same path as Project settings, so the change is in the configuration history.

## When something does not move

- **A run stops right after Intake with a routing message.** A role has no command-line AI tool. Use **Fix routing** on the floor, or `sentinel doctor --fix-routing`.
- **A station says Waiting for usage limit.** The provider CLI reported a usage limit; the task retries at the time shown. Use `sentinel resolve <slug> --retry-now`, or set `routing.fallback` in the config.
- **(routing, continued)** A role has no command-line AI tool. Set one under Settings, Agents, then run `sentinel resolve <slug> --refresh-config -m "routing fixed"`, or let the factory pick the new settings up on its next pass.
- **A task stays in the queue.** All slots are busy, or the task is paused. Change the limits under Project settings (factory).
- **"Session ended".** The service stopped or the session expired. Run `sentinel dashboard` again.
- **Knowledge update failed.** A notification says why; the knowledge screen shows the failed job. Nothing is pushed when the secret scrub finds something.

More in [operations](operations.md) and the [dashboard reference](dashboard.md).
