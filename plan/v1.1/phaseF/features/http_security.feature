@REQ-SEC-01 @REQ-SEC-02 @REQ-API-01
Feature: Host and Origin checks, session token, CSRF and the operation allow-list
  Every request is checked in a fixed order: Host and Origin first (DNS rebinding and cross-site
  defense), then the session cookie, then the route allow-list, then the CSRF header for
  mutating calls, then the body. The token is exchanged once for an HttpOnly, SameSite=Strict
  cookie and is never readable through the API. Only named operations exist; no endpoint takes
  a command, a shell string or a raw path.

  Background:
    Given HOME is a temporary folder for OS user "dev"
    And workspace "digital-hr" is registered as project "digital-hr" with a version 2 run "leave-balance"
    And a human at a pseudo-terminal started "sentinel dashboard --no-open" and the server listens on 127.0.0.1 port P with token T
    And a client authenticated through /auth?t=T holds session cookie S and read CSRF value C from GET /api/v1/session

  Rule: Host and Origin must be the server's own

    @AC-SEC-01l @security @P1 @cov-authz
    Scenario Outline: The Host header is checked on every request
      When GET /api/v1/projects is sent to 127.0.0.1 port P with cookie S and Host header <host>
      Then the status is <status>
      And for status 403 the error code is "E_HOST" and the body names no project
      Examples:
        | host                  | status |
        | "127.0.0.1:P"         | 200    |
        | "localhost:P"         | 200    |
        | "LOCALHOST:P"         | 200    |
        | "127.0.0.1"           | 403    |
        | "127.0.0.1:8"         | 403    |
        | "attacker.example:P"  | 403    |
        | "[::1]:P"             | 403    |
        | "127.0.0.1.nip.io:P"  | 403    |
        | missing               | 403    |

    @AC-SEC-01m @security @P1 @cov-authz
    Scenario Outline: The Origin header, when present, must match
      When POST /api/v1/tasks/leave-balance/control is sent with cookie S, CSRF header C, a valid body and Origin header <origin>
      Then the status is <status>
      Examples:
        | origin                        | status |
        | absent                        | 200    |
        | "http://127.0.0.1:P"          | 200    |
        | "http://localhost:P"          | 200    |
        | "http://attacker.example"     | 403    |
        | "null"                        | 403    |
        | "https://127.0.0.1:P"         | 403    |
        | "http://127.0.0.1:8"          | 403    |

    @AC-SEC-01n @security @P1 @cov-authz
    Scenario Outline: Host and Origin checks also guard the auth and event routes
      When <request> is sent with Host header "attacker.example:P"
      Then the status is 403 with error code "E_HOST"
      And no Set-Cookie header is sent and no event is streamed
      Examples:
        | request                         |
        | GET /auth?t=T                   |
        | GET /api/v1/events with cookie S |
        | GET /                           |

    @AC-SEC-01o @security @P2 @cov-perf-security
    Scenario: A rebinding page cannot read the API
      Given a page from "http://attacker.example:P" whose name now resolves to 127.0.0.1
      When that page fetches /api/v1/projects with the browser's cookies
      Then the request carries Host "attacker.example:P" and is answered 403 with error code "E_HOST"
      And the browser does not send cookie S because the cookie is bound to host 127.0.0.1

  Rule: The token is exchanged once for a session cookie

    @AC-SEC-01p @security @P1 @cov-authn
    Scenario: Exchanging the token sets a strict cookie and removes the token from the URL
      When a fresh client sends GET /auth?t=T
      Then the status is 302 with Location "/"
      And Set-Cookie sets "sentinel_session" with HttpOnly, SameSite=Strict and Path=/ and no Domain attribute
      And the response has Cache-Control "no-store" and Referrer-Policy "no-referrer"
      And following the redirect gives a URL that does not hold the token

    @AC-SEC-01q @security @P1 @cov-authn
    Scenario Outline: A wrong token gives no session
      When a fresh client sends GET /auth<query>
      Then the status is 401 with error code "E_AUTH"
      And no Set-Cookie header is sent
      Examples:
        | query                       |
        | ?t=                         |
        | (no query)                  |
        | ?t=00 followed by 62 zeros  |
        | ?t=T with one character changed |
        | ?t=T followed by "x"        |
        | ?token=T                    |

    @AC-SEC-01r @unit @P2 @cov-perf-security
    Scenario: Token, cookie and CSRF values are compared in constant time
      When the auth module compares a supplied token, cookie or CSRF value with the expected one
      Then it uses hmac.compare_digest on byte strings of the expected length

    @AC-SEC-01s @security @P1 @cov-authn
    Scenario Outline: Every API route needs the session cookie
      When <request> is sent with Host "127.0.0.1:P" and <credential>
      Then the status is 401 with error code "E_AUTH"
      And the body holds no project, run or event data
      Examples:
        | request                                   | credential                                  |
        | GET /api/v1/projects                      | no cookie                                   |
        | GET /api/v1/projects                      | cookie "sentinel_session=wrong"             |
        | GET /api/v1/projects                      | header "Authorization: Bearer T" and no cookie |
        | GET /api/v1/projects?t=T                  | no cookie                                   |
        | GET /api/v1/events                        | no cookie                                   |
        | GET /api/v1/session                       | no cookie                                   |
        | POST /api/v1/tasks/leave-balance/control  | CSRF header C and no cookie                 |

    @AC-SEC-01t @security @P1 @cov-authn
    Scenario: The server answers 401 before revealing whether a route exists
      When GET /api/v1/no-such-route is sent with no cookie
      Then the status is 401 with error code "E_AUTH", not 404

  Rule: Mutating calls need the CSRF header

    @AC-SEC-01u @security @P1 @cov-authz
    Scenario Outline: A POST without the right CSRF value is refused
      Given the run "leave-balance" is EXECUTING
      When POST /api/v1/tasks/leave-balance/control with body {"action": "cancel"} is sent with cookie S and <csrf>
      Then the status is 403 with error code "E_CSRF"
      And the run "leave-balance" is still EXECUTING and no event or audit row was written
      Examples:
        | csrf                                       |
        | no X-Sentinel-CSRF header                  |
        | X-Sentinel-CSRF ""                         |
        | X-Sentinel-CSRF "wrong"                    |
        | X-Sentinel-CSRF set to the token T         |
        | the CSRF value only in a form field "csrf" |

    @AC-SEC-01v @security @P2 @cov-boundary
    Scenario: Read calls do not need the CSRF header
      When GET /api/v1/tasks/leave-balance is sent with cookie S and no CSRF header
      Then the status is 200

    @AC-SEC-01w @security @P2 @cov-authn
    Scenario: The CSRF value is only served to an authenticated client
      When GET /api/v1/session is sent with cookie S
      Then the status is 200 with a "csrf" value of 64 hex characters that differs from the token T
      And the answer holds no token

  Rule: Only allow-listed operations exist

    @AC-API-01h @security @P1 @cov-authz
    Scenario Outline: Unknown operations are refused
      When <request> is sent with cookie S and CSRF header C
      Then the status is <status> with error code "<code>"
      And no engine function was called and nothing was written
      Examples:
        | request                                                        | status | code         |
        | GET /api/v1/shell                                              | 404    | E_NOT_FOUND  |
        | POST /api/v1/exec with body {"cmd": "ls"}                      | 404    | E_NOT_FOUND  |
        | GET /api/v2/projects                                           | 404    | E_NOT_FOUND  |
        | GET /api/v1/fs/dirs?path=/                                     | 404    | E_NOT_FOUND  |
        | POST /api/v1/projects with a project body                      | 404    | E_NOT_FOUND  |
        | PUT /api/v1/projects/digital-hr/configuration                  | 404    | E_NOT_FOUND  |
        | POST /api/v1/tasks/leave-balance/publish                       | 404    | E_NOT_FOUND  |
        | DELETE /api/v1/tasks/leave-balance                             | 405    | E_METHOD     |
        | PUT /api/v1/tasks/leave-balance/approvals                      | 405    | E_METHOD     |
        | POST /api/v1/projects/digital-hr/tasks/x/../../config          | 404    | E_NOT_FOUND  |

    @AC-API-01i @security @P2 @cov-authz
    Scenario: A 405 answer lists the allowed methods
      When DELETE /api/v1/tasks/leave-balance is sent with cookie S and CSRF header C
      Then the status is 405 and the Allow header is "GET"

    @AC-API-01j @security @P1 @cov-invalid-input
    Scenario Outline: Bodies with extra fields or command-like fields are refused
      When POST /api/v1/tasks/leave-balance/control is sent with cookie S, CSRF header C and body <body>
      Then the status is 400 with error code "E_VALIDATION" naming the field <field>
      And no engine function was called
      Examples:
        | body                                                 | field     |
        | {"action": "cancel", "command": "rm -rf /"}          | command   |
        | {"action": "cancel", "shell": "true"}                | shell     |
        | {"action": "cancel", "path": "/etc/passwd"}          | path      |
        | {"action": "cancel", "env": {"A": "1"}}              | env       |

    @AC-API-01k @security @P2 @cov-perf-security
    Scenario Outline: Other HTTP methods and CORS preflight are refused
      When <method> /api/v1/projects is sent with cookie S and Origin "http://attacker.example"
      Then the status is 403 or 405
      And no Access-Control-Allow-Origin, Access-Control-Allow-Credentials or Access-Control-Allow-Methods header is sent
      Examples:
        | method  |
        | OPTIONS |
        | TRACE   |
        | CONNECT |

  Rule: Request bodies are small JSON documents

    @AC-API-01l @security @P2 @cov-boundary
    Scenario Outline: Body size limit
      When POST /api/v1/tasks/leave-balance/control is sent with cookie S, CSRF header C and a JSON body of <size> bytes
      Then the status is <status>
      Examples:
        | size    | status |
        | 1048576 | 400    |
        | 1048577 | 413    |

    @AC-API-01m @security @P2 @cov-invalid-input
    Scenario Outline: Only JSON bodies are read
      When POST /api/v1/tasks/leave-balance/control is sent with cookie S, CSRF header C, Content-Type <type> and body <body>
      Then the status is <status> with error code "<code>"
      Examples:
        | type                           | body                    | status | code           |
        | "text/plain"                   | {"action": "cancel"}    | 415    | E_MEDIA_TYPE   |
        | "application/x-www-form-urlencoded" | action=cancel      | 415    | E_MEDIA_TYPE   |
        | "application/json"             | {"action": "cancel"     | 400    | E_VALIDATION   |
        | "application/json"             | ["cancel"]              | 400    | E_VALIDATION   |
        | "application/json"             | (empty)                 | 400    | E_VALIDATION   |

    @AC-API-01n @security @P3 @cov-missing-fields
    Scenario: A body without Content-Length is refused
      When POST /api/v1/tasks/leave-balance/control is sent with chunked transfer encoding, cookie S and CSRF header C
      Then the status is 400 with error code "E_VALIDATION" and message "Content-Length required"

  Rule: Responses carry protective headers and never expose the token

    @AC-SEC-01x @security @P1 @cov-perf-security
    Scenario: Security headers on every response
      When GET /, GET /api/v1/projects and an unauthenticated GET /api/v1/projects are sent
      Then every response has Content-Security-Policy "default-src 'self'; frame-ancestors 'none'"
      And every response has X-Content-Type-Options "nosniff"
      And every /api response has Cache-Control "no-store" and Content-Type "application/json; charset=utf-8"
      And no response has an Access-Control-Allow-Origin header

    @AC-SEC-02h @security @P1 @cov-perf-security
    Scenario: No answer holds the token
      When every GET route of Phase F is called with cookie S, including error answers for unknown ids
      Then no response body or header other than the Set-Cookie of /auth holds the token T
      And no response holds the content of server.json

    @AC-SEC-02i @security @P1 @cov-perf-security
    Scenario Outline: Path traversal cannot reach the token file or other files
      When GET <path> is sent with cookie S
      Then the status is 400 or 404 and the body holds no content of a file outside the run folder
      Examples:
        | path                                                                   |
        | /api/v1/tasks/leave-balance/artifacts/..%2F..%2F..%2F.config%2Fsentinel%2Fserver.json |
        | /api/v1/tasks/..%2F..%2Fetc/report                                     |
        | /api/v1/tasks/leave-balance/logs/..%2Fsentinel.db                      |
        | /..%2F..%2F.config/sentinel/server.json                                |
        | /static/../../.config/sentinel/server.json                             |

    @AC-SEC-02j @security @P2 @cov-perf-security
    Scenario: The server log holds no token or cookie value
      Given the server writes its request log to the terminal
      When a client authenticates and calls 20 API routes with cookie S and CSRF header C
      Then the request log holds the paths and statuses but not the token T, the cookie value or the CSRF value
      And the /auth line shows the query as "t=REDACTED"
