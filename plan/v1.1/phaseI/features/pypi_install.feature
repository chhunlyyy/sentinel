@REQ-OPS-01 @REQ-OPS-02
Feature: One-command install from PyPI
  The release is published to PyPI as the distribution "sentinel-pipeline". The console script
  stays "sentinel" and the import package stays "sentinel". "uv tool install sentinel-pipeline"
  (or "pipx install sentinel-pipeline") installs the command with the dashboard build included.
  Nothing else needs to be built or downloaded by the user.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And the release wheel built with SENTINEL_RELEASE=1 from a fresh dashboard build

  Rule: Names

    @AC-OPS-06a @unit @P1 @cov-happy-path
    Scenario: Distribution, console script and import package names
      When pyproject.toml and the wheel METADATA are read
      Then the project name is "sentinel-pipeline"
      And the wheel file is named sentinel_pipeline-1.1.0-py3-none-any.whl and its METADATA says "Name: sentinel-pipeline" and "Version: 1.1.0"
      And the only console script is "sentinel" and the top-level package is "sentinel"

    @AC-OPS-06b @unit @P1 @cov-regression
    Scenario: Runtime dependencies and metadata are unchanged by the rename
      When the wheel METADATA is read
      Then Requires-Dist lists only pyyaml and jsonschema
      And Requires-Python is ">=3.10", the license is MIT and the project URLs point to github.com/chhunlyyy/sentinel

  Rule: Wheel contents

    @AC-OPS-06c @integration @P1 @cov-happy-path
    Scenario: The wheel carries the dashboard build
      When the wheel member list is read
      Then it holds sentinel/dashboard_dist/index.html, its assets and manifest.json
      And every file listed in manifest.json is in the wheel with the recorded hash

    @AC-OPS-06d @integration @P2 @cov-errors
    Scenario: A release build with a missing or stale dashboard stops
      Given sentinel/dashboard_dist is missing or does not match its manifest
      When the wheel is built with SENTINEL_RELEASE=1
      Then the build fails naming "npm run build"

    @AC-OPS-06e @unit @P2 @cov-happy-path
    Scenario: The sdist holds what is needed to rebuild
      When the sdist member list is read
      Then it holds sentinel, skills, docs, README.md, CHANGELOG.md, LICENSE, pyproject.toml, hatch_build.py and the dashboard build

  Rule: One command

    @AC-OPS-06f @integration @P1 @cov-happy-path
    Scenario Outline: Installing the wheel gives the sentinel command
      When "<install>" is run for the release wheel with the dependencies available
      Then "sentinel --version" prints "1.1.0" and exits 0
      And "sentinel --help" lists the "dashboard" command
      Examples:
        | install                                                     |
        | uv tool install sentinel-pipeline                           |
        | pip install sentinel-pipeline (in a virtual environment, as pipx does) |

    @AC-OPS-06g @e2e @P1 @cov-happy-path
    Scenario: The installed command serves the dashboard
      Given the wheel is installed
      When a human at a terminal runs "sentinel dashboard --no-open --port 8765" in a workspace
      Then GET / with a valid session returns the built index.html and not the "UI not installed" placeholder
      And the files named by index.html are served from the installed package

    @AC-OPS-06h @integration @P2 @cov-regression
    Scenario Outline: Upgrade and removal use the distribution name
      Then the documentation says "<command>"
      Examples:
        | command                                |
        | uv tool upgrade sentinel-pipeline      |
        | uv tool uninstall sentinel-pipeline    |
        | pipx upgrade sentinel-pipeline         |
        | pipx uninstall sentinel-pipeline       |

  Rule: Documentation

    @AC-OPS-06i @unit @P1 @cov-happy-path
    Scenario: The README quick start is two one-liners
      When README.md is read
      Then the quick start shows "uv tool install sentinel-pipeline" and the "docker run" command of the dashboard image
      And no documented install line names the distribution "sentinel" alone

    @AC-OPS-06j @unit @P2 @cov-regression
    Scenario: A git install is documented as the developer path
      When docs/installation.md is read
      Then it says that "uv tool install git+https://github.com/chhunlyyy/sentinel" has no dashboard build
      And it gives the build steps for a source install

    @AC-OPS-06k @unit @P2 @cov-regression
    Scenario: The host keeps the dashboard port rule
      When docs/dashboard.md is read
      Then it says that "sentinel dashboard" picks a free port and that "sentinel dashboard --port 8765" fixes it
      And port 8765 is valid under the rule 1024 to 65535
