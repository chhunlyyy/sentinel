@REQ-OPS-01 @REQ-OPS-02 @REQ-TST-01
Feature: Tag-triggered release workflow
  .github/workflows/release.yml runs on a tag "v*". It runs the release gate, builds the wheel and
  sdist once, publishes them to PyPI by trusted publishing, then builds and pushes the image to
  GHCR. It is prepared in the repository and is never run by the work that adds it. The gate is
  not weakened and a pending manual check fails the workflow with a clear message.

  Background:
    Given the file .github/workflows/release.yml is parsed as YAML

  Rule: Trigger and gate

    @AC-OPS-08a @unit @P1 @cov-happy-path
    Scenario: Only a version tag triggers it
      Then the workflow "on" section has push tags "v*" and nothing else (no branch push, no pull_request)
      And the top-level permissions are "contents: read"

    @AC-OPS-08b @unit @P1 @cov-authz
    Scenario: The gate runs first and the publish jobs depend on it
      Then job "gate" runs "python tools/release_gate.py" without "--allow-dirty" and "--skip-*" options
      And the build, PyPI and image jobs each need "gate" directly or through "build"

    @AC-OPS-08c @unit @P1 @cov-errors
    Scenario: A pending manual check fails the workflow clearly
      Then the gate job reads release-evidence.json and fails with a message naming the pending owner checks unless "release_ready" is true

    @AC-OPS-08d @unit @P1 @cov-regression
    Scenario: The tag must equal the version
      Then a step fails when the tag is not "v" followed by the content of sentinel/VERSION

  Rule: PyPI

    @AC-OPS-08e @unit @P1 @cov-happy-path
    Scenario: The wheel and sdist are built once from the tested tree
      Then job "build" builds the dashboard with "npm ci" and "npm run build", then the wheel and sdist with SENTINEL_RELEASE=1, and uploads them as an artifact
      And the PyPI job downloads that artifact and builds nothing

    @AC-OPS-08f @security @P1 @cov-authz
    Scenario: Trusted publishing with the narrowest permissions
      Then the PyPI job uses "pypa/gh-action-pypi-publish" with no password or API token input
      And "id-token: write" appears only in that job and it names the environment "pypi"

  Rule: GHCR image

    @AC-OPS-08g @unit @P1 @cov-happy-path
    Scenario: The image is built and pushed with both tags
      Then the image job uses "docker/build-push-action" and "docker/login-action" with the registry "ghcr.io" and the GITHUB_TOKEN
      And it pushes "ghcr.io/chhunlyyy/sentinel" with tags from the version and "latest"
      And "packages: write" appears only in that job

    @AC-OPS-08h @unit @P1 @cov-perf-security
    Scenario: Actions are pinned
      Then every "uses:" names an exact version tag or a commit hash, never a branch, "latest" or a major-only tag
      And no step prints a secret or passes one on a command line

  Rule: Documentation

    @AC-OPS-08i @unit @P1 @cov-regression
    Scenario: The repository settings are documented
      When docs/operations.md is read
      Then it names the PyPI trusted publisher fields (project "sentinel-pipeline", repository, workflow "release.yml", environment "pypi"), the packages write permission and the public visibility of the package
      And its release checklist lists the tag step and the manual checks

    @AC-OPS-08j @unit @P2 @cov-regression
    Scenario: The earlier release gate covers phase I
      Then tools/release_gate.py lists phaseI, tests/release/phase_hashes.json pins its hash and IMPLEMENTATION_STATUS.md records it
