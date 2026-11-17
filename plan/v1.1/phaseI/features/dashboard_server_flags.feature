@REQ-SEC-01 @REQ-SEC-02
Feature: Binding and public host options for the container
  "sentinel dashboard" still binds 127.0.0.1. The option "--bind 0.0.0.0" is accepted only when
  the environment variable SENTINEL_CONTAINER is "1" (set by the image). The option
  "--public-host HOST:PORT" adds one host name the server accepts in Host and Origin: only
  localhost:<port> or 127.0.0.1:<port>. Token, CSRF and cookie rules do not change.

  Background:
    Given HOME is a temporary folder for OS user "dev" and XDG_CONFIG_HOME is not set
    And a workspace "digital-hr" with a valid sentinel.config.yaml
    And no Sentinel server is running for user "dev"

  Rule: Bind refusal

    @AC-SEC-10a @security @P1 @cov-authz
    Scenario: --bind 0.0.0.0 is refused outside a container
      Given SENTINEL_CONTAINER is not set
      When a human at a terminal runs "sentinel dashboard --no-open --bind 0.0.0.0"
      Then it exits with code 2 with a message saying the option is allowed only inside the Sentinel container
      And no server is started and no server.json is written

    @AC-SEC-10b @security @P1 @cov-invalid-input
    Scenario Outline: Only 0.0.0.0 is accepted, and only in a container
      Given SENTINEL_CONTAINER is "<env>"
      When a human at a terminal runs "sentinel dashboard --no-open --bind <address>"
      Then it exits with code 2 and no server is started
      Examples:
        | env | address      |
        | 1   | 192.168.1.20 |
        | 1   | ::           |
        | 1   | localhost    |
        | 0   | 0.0.0.0      |
        | yes | 0.0.0.0      |
        |     | 0.0.0.0      |

    @AC-SEC-10c @security @P1 @cov-authz
    Scenario: The environment variable alone does not widen the bind
      Given SENTINEL_CONTAINER is "1"
      When a human at a terminal runs "sentinel dashboard --no-open"
      Then the listening socket address is exactly 127.0.0.1

    @AC-SEC-10d @security @P1 @cov-happy-path
    Scenario: In a container the flag binds all interfaces
      Given SENTINEL_CONTAINER is "1"
      When a human at a terminal runs "sentinel dashboard --no-open --bind 0.0.0.0 --port 8765"
      Then the listening socket address is 0.0.0.0 port 8765
      And the printed URL is "http://localhost:8765/auth?t=" followed by the token

  Rule: Public host

    @AC-SEC-10e @security @P1 @cov-authz
    Scenario Outline: Host and Origin accept the loopback names and the public host, nothing else
      Given the server runs with "--public-host localhost:8765" on port 8765
      When a request is sent with Host "<host>" and Origin "<origin>"
      Then the answer is <outcome>
      Examples:
        | host                | origin                      | outcome             |
        | localhost:8765      | http://localhost:8765       | not refused by Host or Origin |
        | 127.0.0.1:8765      | http://127.0.0.1:8765       | not refused by Host or Origin |
        | evil.example:8765   |                             | 403 E_HOST          |
        | localhost:9999      |                             | 403 E_HOST          |
        | 172.17.0.2:8765     |                             | 403 E_HOST          |
        | 0.0.0.0:8765        |                             | 403 E_HOST          |
        | localhost:8765      | http://evil.example:8765    | 403 E_ORIGIN        |
        | localhost:8765      | http://localhost:9999       | 403 E_ORIGIN        |
        | localhost           |                             | 403 E_HOST          |

    @AC-SEC-10f @security @P1 @cov-invalid-input
    Scenario Outline: --public-host takes only a loopback name with a valid port
      When a human at a terminal runs "sentinel dashboard --no-open --public-host <value>"
      Then it exits with code 2 and no server is started
      Examples:
        | value               |
        | example.com:8765    |
        | 192.168.1.20:8765   |
        | localhost           |
        | localhost:80        |
        | localhost:abc       |
        | 0.0.0.0:8765        |
        | localhost:8765/x    |

    @AC-SEC-10g @security @P1 @cov-regression
    Scenario: Token, CSRF and cookie rules are unchanged with the new options
      Given the server runs with "--bind 0.0.0.0 --public-host localhost:8765" and SENTINEL_CONTAINER "1"
      Then the session cookie is HttpOnly and SameSite=Strict, a mutating call without the CSRF value is refused, an /api call without a session is 401 and the token file keeps mode 0600
      And the token is new at every start

    @AC-SEC-10h @unit @P2 @cov-regression
    Scenario: Without the new options nothing changes
      When the server runs with no --bind and no --public-host
      Then only 127.0.0.1:<port> and localhost:<port> are accepted in Host and the printed URL names 127.0.0.1
