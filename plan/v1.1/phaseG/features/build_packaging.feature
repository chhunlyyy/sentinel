@REQ-OPS-01 @REQ-DSH-06 @REQ-TST-01
Feature: Build into the wheel, offline use and contract fixtures
  The dashboard source lives in dashboard/ (React, TypeScript, Vite). It is built at release
  time into sentinel/dashboard_dist/, which the wheel carries. Node is needed to build and test,
  never at runtime. After "npm ci" every dashboard test runs without network. The fake API
  server used by the e2e tests serves fixtures that a Python test records from the real
  Phase F server, so the fixtures cannot drift from the API.

  Rule: Build and wheel

    @AC-OPS-01a @integration @P1 @cov-happy-path
    Scenario: The release build puts the assets into the package
      Given a clean checkout with Node at the version in dashboard/.nvmrc
      When "npm ci" and "npm run build" run in dashboard/
      Then sentinel/dashboard_dist/ holds index.html, hashed JavaScript and CSS files and a manifest of every file with its sha256
      And no file in it is larger than 2 MB and the total is under 5 MB
      And no file in it is a source map

    @AC-OPS-01b @integration @P1 @cov-happy-path
    Scenario: The installed wheel serves the dashboard without Node
      Given the wheel is built after the dashboard build
      And it is installed with "uv tool install" in a temporary HOME on a PATH without node or npm
      When "sentinel dashboard --no-open" is started under a pseudo-terminal and the browser opens the printed URL
      Then GET / answers 200 with the built index.html and every asset it names answers 200 from the installed package folder
      And the overview screen renders with data from the real server

    @AC-OPS-01c @integration @P1 @cov-regression
    Scenario: A wheel without built assets still serves the Phase F placeholder
      Given the wheel is built without sentinel/dashboard_dist/
      When the server is started and GET / is called with a valid session
      Then the Phase F placeholder page is served, as in AC-DSH-06d

    @AC-OPS-01d @integration @P2 @cov-data-integrity
    Scenario: The build is reproducible from the lockfile
      When "npm ci" and "npm run build" run twice in two clean checkouts of the same commit
      Then the manifests of sentinel/dashboard_dist/ are byte-identical

    @AC-OPS-01e @integration @P2 @cov-errors
    Scenario: The wheel build refuses stale or missing assets in release mode
      Given SENTINEL_RELEASE=1 and the manifest in sentinel/dashboard_dist/ names a source hash that differs from the hash of dashboard/src and dashboard/package-lock.json
      When the release wheel build runs
      Then it stops with a message naming "npm run build"

    @AC-OPS-01f @security @P2 @cov-perf-security
    Scenario: Static files are served only from the package folder
      Given the built assets are installed
      When GET /assets/../../server.json, GET /assets/%2e%2e/VERSION and GET /assets/no-such-file.js are called with a valid session
      Then each answers 404 and no file outside sentinel/dashboard_dist/ is read

  Rule: Offline

    @AC-DSH-06f @integration @P1 @cov-perf-security
    Scenario: The built bundle names no remote resource
      When the files in sentinel/dashboard_dist/ are scanned
      Then no file holds a URL starting with "http:", "https:" or "//" except the XML and SVG namespace URIs
      And no file references a font, stylesheet or script from another origin

    @AC-DSH-06g @integration @P1 @cov-perf-security
    Scenario: The dashboard tests run with the network off
      Given "npm ci" has completed in dashboard/
      When "npm test" and "npm run e2e" run in a network namespace with only the loopback interface
      Then both pass
      And no test, fixture or tool tried to reach a host other than 127.0.0.1

    @AC-DSH-06h @integration @P2 @cov-external-failure
    Scenario: A session with the network cable out
      Given the installed wheel runs "sentinel dashboard" on a machine with no network interface but loopback
      When the user opens every screen
      Then every screen renders and no request fails for a reason other than the fixture data

  Rule: Contract fixtures

    @AC-DSH-06i @contract @P1 @cov-data-integrity
    Scenario: Fake API fixtures equal real server answers
      Given the Python test "test_dashboard_fixtures" starts the real Phase F server against the fixture workspaces with fixed clocks and ids
      When it calls every route the fake API serves with the same requests
      Then each real answer equals the stored fixture after removing the fields listed as volatile (times, pids, ports)
      And the test fails, naming the route, when they differ

    @AC-DSH-06j @contract @P2 @cov-regression
    Scenario: The TypeScript API types follow the fixtures
      When "npm run typecheck" runs with the fixture files typed against dashboard/src/api/types.ts
      Then it passes
      And every route the app calls is listed in the route table shared with the fake API server

  Rule: Nothing else changes

    @AC-TST-01i @regression @P1 @cov-regression
    Scenario: Earlier tests stay green
      When the 95 selftest checks and the tests of Phases A to F run after Phase G is built
      Then all pass
      And the Python package declares no new runtime dependency

    @AC-TST-01j @regression @P2 @cov-regression
    Scenario: The CLI needs no dashboard assets
      Given sentinel/dashboard_dist/ is removed from the installed package
      When "sentinel next", "sentinel review" and "sentinel approve" run as in Phase B and C tests
      Then they behave as before Phase G
