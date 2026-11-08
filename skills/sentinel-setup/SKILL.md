---
name: sentinel-setup
description: Sets Sentinel up in a project by connecting the team's private shared repo, choosing the project shape, detecting each repo's stack and writing sentinel.config.yaml. Use when the user asks to set up, install, initialize or configure Sentinel, or when /sentinel reports that there is no config or no shared repo.
---

Set Sentinel up in the current workspace: the folder that holds the project's repos, or the repo itself for a single project.

1. Run `sentinel --version`. If the command is missing, tell the user to install it with `uv tool install git+https://github.com/chhunlyyy/sentinel` (or `pipx install` with the same URL) and stop until it works.
2. If `sentinel.config.yaml` already exists at the workspace root, do not re-initialize. Run `sentinel doctor` and fix what it reports. If the shared repo is the problem, ask for its URL (step 3) and run `sentinel shared set <url>`.
3. Look at the folders yourself first, then ask the user in one message for what you cannot find out:
   - The clone URL of the team's private shared repo (required). It must be an empty private git repository their team owns: it holds the project rules, specs and regression suite. For a quick local trial, a bare repo on disk (`git init --bare ~/sentinel-shared.git`) works.
   - The project shape: `single`, `fullstack` (backend and frontend), `fullstack-mobile`, or `custom`.
   - The folder of each repo, relative to the workspace. Propose what you see.
4. Run `sentinel init --shape <shape> --shared-repo <url> --non-interactive --set <id>.path=<folder> ...` with one `--set` per repo (ids are `app`, or `backend`, `frontend`, `mobile`). Stack profiles are detected from files such as `pubspec.yaml`, `package.json` and `build.gradle`; override one with `--set <id>.profile=<profile>`. For the `custom` shape, ask the user to run `sentinel init` themselves in a terminal, because it asks for each repo interactively.
5. If init says the shared repo was empty, it committed starter files locally and printed one push command. Show it and ask the user to run it, or to approve you running it.
6. Run `sentinel doctor` and report the result. Mention that `sentinel.config.yaml` can switch on team rules (`rules`), set up QA (`qa`) and point to guidelines, and offer to help, but change nothing without being asked.
7. Tell the user they can now use `/sentinel` for a task.
