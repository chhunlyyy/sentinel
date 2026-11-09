# Security policy

Sentinel runs AI agents with write access to your repositories and can copy databases for QA. Read [docs/security.md](docs/security.md) before using it on real systems.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting: the **Security** tab of this repository, then **Report a vulnerability**. Include the version (`sentinel --version`), what you did, and what you expected. You will get a first answer within a few days.

## Supported versions

Sentinel is in beta. Only the latest release receives fixes.

## What to know

- The skills are plain markdown that tells your agent to run commands. Read them before you install, and pin a release tag.
- Commands in `sentinel.config.yaml` (build, test, QA start commands) run in a shell, like a Makefile. Do not run Sentinel in a repository whose config you have not read.
- The shared repo holds tests that QA executes. Anyone who can write to it can run code on your machine, so keep it private and limit who can push.
- The log scrubber is a safety net, not a guarantee.
