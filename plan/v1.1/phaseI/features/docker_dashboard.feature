@REQ-OPS-01 @REQ-SEC-01 @REQ-SEC-03
Feature: The dashboard in a container
  The image "ghcr.io/chhunlyyy/sentinel" (tags 1.1.0 and latest) serves only the dashboard and
  server use case. The AI-tool-facing CLI is installed on the host. One command starts it:
  docker run --rm -it -p 127.0.0.1:8765:8765 -v "$PWD":/work -v sentinel-config:/home/sentinel/.config/sentinel ghcr.io/chhunlyyy/sentinel
  It prints http://localhost:8765/auth?t=<token>; opening that shows the dashboard for the
  mounted workspace. The image holds no AI tool CLI and no secret and runs as a non-root user.

  Background:
    Given the image built from the Dockerfile of the checkout
    And a workspace "digital-hr" with a valid sentinel.config.yaml and a git repository

  Rule: Image build

    @AC-OPS-07a @integration @P1 @cov-happy-path
    Scenario: A multi-stage build with pinned bases
      When the Dockerfile is read
      Then it has a node stage that runs "npm ci" and "npm run build", and a python stage that builds the wheel with SENTINEL_RELEASE=1
      And the final stage is a slim python image that installs the wheel, copies no source tree and runs as USER "sentinel" (not root)
      And every FROM line names a version tag

    @AC-OPS-07b @unit @P2 @cov-boundary
    Scenario: The build context is small and clean
      When .dockerignore is read
      Then it excludes node_modules, .sentinel, .claude, .git, plan, tests and release evidence
      And it keeps dashboard, sentinel, skills, hatch_build.py, pyproject.toml, README.md and LICENSE in the context

    @AC-OPS-07c @performance @P2 @cov-perf-security
    Scenario: The image size stays within budget
      When the image is built
      Then its size is at most 250 MB

  Rule: One command

    @AC-OPS-07d @e2e @P1 @cov-happy-path
    Scenario: The documented docker run command prints the login URL
      When a human runs the documented command at a terminal
      Then it prints "http://localhost:8765/auth?t=" followed by a 64-character token
      And GET http://127.0.0.1:8765/auth?t=<token> sets the session cookie and GET / answers the built dashboard page
      And GET /api/v1/projects lists the project of the mounted workspace "digital-hr"

    @AC-OPS-07e @integration @P1 @cov-happy-path
    Scenario: The container needs no browser
      When the Dockerfile is read
      Then the image command passes --no-open and the only OS packages it installs are git and ca-certificates

    @AC-OPS-07f @integration @P1 @cov-regression
    Scenario: Stopping the container is clean
      When the container receives SIGTERM from "docker stop"
      Then it exits with code 0 within 10 seconds and server.json is removed from the config volume

  Rule: Persistence

    @AC-OPS-07g @integration @P1 @cov-data-integrity
    Scenario: Config and token live in the named volume with private modes
      When the container has started once
      Then /home/sentinel/.config/sentinel has mode 0700 and server.json and projects.json have mode 0600
      And a second container with the same volume still lists project "digital-hr" and starting twice in the same mounted workspace leaves one entry for /work in projects.json
      And the second container prints a different token

  Rule: Identity and files

    @AC-OPS-07h @security @P1 @cov-authz
    Scenario: The container runs as a non-root user
      When "id -u" runs in the image with no --user option
      Then the user is "sentinel" with a uid other than 0

    @AC-OPS-07i @integration @P1 @cov-happy-path
    Scenario: Files written in the workspace belong to the host user
      When the container runs with "--user $(id -u):$(id -g)" and a task changes files in /work
      Then those files are owned by the host user and git reports no dubious ownership

    @AC-OPS-07j @integration @P2 @cov-regression
    Scenario: git trusts the mounted workspace
      When the Dockerfile is read
      Then it runs "git config --system --add safe.directory /work" and sets WORKDIR /work

  Rule: Approvals stay with a human at a terminal

    @AC-OPS-07k @security @P1 @cov-authz
    Scenario: No terminal, no server
      When the image runs without "-t" and the dashboard command
      Then it exits with code 5 with error "E_NOT_TTY" and prints no token
      And "sentinel approve" run in the image without "-t" also exits with code 5 with error "E_NOT_TTY"

    @AC-OPS-07l @security @P1 @cov-authz
    Scenario: A dashboard approval needs the hash prefix as in Phase F
      Given the container serves a workspace with a task waiting for the specification approval
      When POST /api/v1/tasks/<slug>/approvals is sent without the 8-character confirmation
      Then it is refused with E_VALIDATION and no approval is recorded

  Rule: Contents

    @AC-OPS-07m @security @P1 @cov-perf-security
    Scenario Outline: No AI tool CLI is in the image
      When "command -v <tool>" runs in the image
      Then it finds nothing
      Examples:
        | tool     |
        | claude   |
        | codex    |
        | gemini   |
        | aider    |
        | opencode |
        | node     |
        | npm      |

    @AC-OPS-07n @security @P1 @cov-perf-security
    Scenario: The image holds no secret
      When the image environment, history and files are searched
      Then no variable or file holds a token, key, password or credential file
      And /home/sentinel holds no config before the first start and the image has no .sentinel, .claude or .env folder or file

    @AC-OPS-07o @unit @P2 @cov-regression
    Scenario: The image is labelled
      When the Dockerfile is read
      Then its labels give the version "1.1.0", the source repository and the licence MIT

  Rule: Publishing

    @AC-SEC-10i @security @P1 @cov-authz
    Scenario: The container is reachable only on the host loopback
      Given the documented command publishes "127.0.0.1:8765:8765"
      Then a connection to port 8765 on 127.0.0.1 of the host succeeds
      And a connection to port 8765 on any non-loopback address of the host is refused

    @AC-SEC-10j @unit @P1 @cov-authz
    Scenario: Every documented publish option names 127.0.0.1
      When README.md, docs/ and the image help are read
      Then each "-p" or "--publish" option in a docker command names "127.0.0.1:" and none uses "0.0.0.0", ":::" or a bare port
      And the documentation says to run with "--user $(id -u):$(id -g)" for file ownership

    @AC-SEC-10k @unit @P2 @cov-happy-path
    Scenario: The help states the rule
      When "sentinel dashboard --help" runs (the image entrypoint is "sentinel", so "docker run --rm <image> dashboard --help" prints the same)
      Then the help says to publish only on 127.0.0.1 and names the --bind and --public-host options
