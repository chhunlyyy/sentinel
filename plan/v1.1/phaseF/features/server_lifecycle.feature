@REQ-SEC-01 @REQ-SEC-02 @REQ-SEC-05 @REQ-API-01
Feature: Starting, attaching to and stopping the local dashboard server
  "sentinel dashboard" starts one local API server per user. It binds 127.0.0.1 only, creates a
  new random token at every start, keeps that token in ~/.config/sentinel/server.json with mode
  0600, and registers the workspace in projects.json. A second call attaches to the live server
  instead of starting another one. Agents cannot start the server or obtain its token through it.

  Background:
    Given HOME is a temporary folder for OS user "dev" and XDG_CONFIG_HOME is not set
    And a workspace "digital-hr" with a valid sentinel.config.yaml whose project name is "digital-hr"
    And no Sentinel server is running for user "dev"

  Rule: The server binds the loopback interface only

    @AC-SEC-01a @integration @P1 @cov-happy-path
    Scenario: Starting the server at a terminal
      When a human at a terminal runs "sentinel dashboard --no-open" in workspace "digital-hr"
      Then the server listens on 127.0.0.1 at a free port P chosen by the operating system
      And the output shows "http://127.0.0.1:P/auth?t=" followed by the 64-character token of server.json
      And GET http://127.0.0.1:P/api/v1/runtime with a valid session answers 200 with the server pid, port P, the start time and project "digital-hr"
      And the process keeps running in the foreground until it is stopped

    @AC-SEC-01b @security @P1 @cov-perf-security
    Scenario: The listening socket is bound to 127.0.0.1 and nothing else
      When the server is started with "sentinel dashboard --no-open"
      Then the listening socket address is exactly 127.0.0.1 port P
      And no socket of the server process listens on 0.0.0.0, on :: or on any other address
      And a TCP connection to port P on a non-loopback address of the machine is refused

    @AC-SEC-01c @security @P1 @cov-invalid-input
    Scenario Outline: No option chooses another address
      When a human at a terminal runs "sentinel dashboard <args>"
      Then it exits with code 2 and prints the usage
      And no server is started and no server.json is written
      Examples:
        | args                          |
        | --host 0.0.0.0                |
        | --bind 192.168.1.20           |
        | --listen :: --no-open         |

    @AC-SEC-01d @security @P2 @cov-perf-security
    Scenario Outline: Environment variables and config keys cannot widen the bind address
      Given <setting>
      When the server is started with "sentinel dashboard --no-open"
      Then the listening socket address is exactly 127.0.0.1 port P
      Examples:
        | setting                                                                 |
        | the environment sets SENTINEL_HOST to "0.0.0.0"                         |
        | the environment sets HOST to "0.0.0.0"                                  |
        | sentinel.config.yaml holds an unknown key "dashboard.host" set to "::"  |

    @AC-API-01a @integration @P2 @cov-boundary
    Scenario Outline: Choosing the port
      When a human at a terminal runs "sentinel dashboard --no-open --port <port>"
      Then <outcome>
      Examples:
        | port  | outcome                                                                          |
        | 8765  | the server listens on 127.0.0.1 port 8765                                        |
        | 1024  | the server listens on 127.0.0.1 port 1024                                        |
        | 65535 | the server listens on 127.0.0.1 port 65535                                       |
        | 1023  | it exits with code 2 and the usage says the port must be from 1024 to 65535      |
        | 65536 | it exits with code 2 and the usage says the port must be from 1024 to 65535      |
        | 0     | it exits with code 2 and the usage says the port must be from 1024 to 65535      |
        | abc   | it exits with code 2 and the usage says the port must be from 1024 to 65535      |

    @AC-API-01b @integration @P2 @cov-external-failure
    Scenario: The requested port is taken by another program
      Given another program listens on 127.0.0.1 port 8765
      When a human at a terminal runs "sentinel dashboard --no-open --port 8765"
      Then it exits with code 1 with the message "port 8765 is in use"
      And no server.json is written and no lock is held

  Rule: Only a human at a terminal starts the server or sees its token

    @AC-SEC-02b @security @P1 @cov-authz
    Scenario: A task process cannot start or attach to the server
      Given SENTINEL_TASK_ID is set to "t-abc123" in the environment
      When "sentinel dashboard --no-open" is run at a pseudo-terminal
      Then it exits with code 5 with error "E_ACTOR"
      And no token or URL holding a token is printed
      And no server is started and server.json is not created or read

    @AC-SEC-02c @security @P1 @cov-authz
    Scenario Outline: Without an interactive terminal the command is refused
      Given <state>
      When "sentinel dashboard --no-open" is run with stdin from a pipe
      Then it exits with code 5 with error "E_NOT_TTY"
      And the output holds no token and no URL holding a token
      Examples:
        | state                                                   |
        | no Sentinel server is running for user "dev"            |
        | a Sentinel server for user "dev" is running on port P   |

    @AC-SEC-02d @security @P1 @cov-perf-security
    Scenario: The token never enters an environment
      Given the server was started with "sentinel dashboard --no-open"
      Then the environment of the server process holds no SENTINEL_DASHBOARD_TOKEN and no variable whose value is the token
      And the command line of the server process does not hold the token

  Rule: server.json and projects.json are private files of the user

    @AC-SEC-02e @security @P1 @cov-perf-security
    Scenario: The token file is created with mode 0600 in a 0700 folder
      When the server is started with "sentinel dashboard --no-open"
      Then ~/.config/sentinel has mode 0700
      And ~/.config/sentinel/server.json has mode 0600 and holds pid, port, token, started_at and version
      And the token is 64 lowercase hex characters from 32 random bytes
      And at no moment during the start does a server.json readable by group or others exist

    @AC-SEC-02f @security @P2 @cov-boundary
    Scenario: A folder with wider permissions is tightened
      Given ~/.config/sentinel exists with mode 0755 and holds projects.json with mode 0644
      When the server is started with "sentinel dashboard --no-open"
      Then ~/.config/sentinel has mode 0700 and projects.json has mode 0600
      And the output says that the permissions were tightened

    @AC-SEC-02g @unit @P2 @cov-boundary
    Scenario: XDG_CONFIG_HOME moves the user registry
      Given XDG_CONFIG_HOME is set to a temporary folder X
      When the server is started with "sentinel dashboard --no-open"
      Then server.json and projects.json are written in X/sentinel
      And nothing is written in ~/.config/sentinel

  Rule: The workspace is registered in projects.json

    @AC-API-01c @integration @P1 @cov-happy-path
    Scenario: Starting in a workspace registers it
      Given projects.json does not exist
      When the server is started with "sentinel dashboard --no-open" in workspace "digital-hr"
      Then projects.json holds version 1 and one project with id "digital-hr", name "digital-hr", the resolved workspace path and the time it was added
      And GET /api/v1/projects lists project "digital-hr"

    @AC-API-01d @integration @P2 @cov-duplicate
    Scenario: The same workspace is registered once
      Given projects.json already lists workspace "digital-hr" with id "digital-hr"
      When the server is started with "sentinel dashboard --no-open" through a symbolic link to the workspace folder
      Then projects.json still lists exactly one project for that resolved path

    @AC-API-01e @unit @P2 @cov-duplicate
    Scenario: Two workspaces with the same project name get distinct ids
      Given projects.json lists workspace "digital-hr" with id "digital-hr"
      And a second workspace at another path whose project name is also "digital-hr"
      When "sentinel dashboard --no-open" is run at a terminal in the second workspace
      Then projects.json lists the second workspace with id "digital-hr-2"

    @AC-API-01f @integration @P2 @cov-empty-null
    Scenario: Starting outside a workspace serves the projects already registered
      Given projects.json lists workspace "digital-hr"
      When the server is started with "sentinel dashboard --no-open" in a folder with no sentinel.config.yaml above it
      Then the server starts and GET /api/v1/projects lists project "digital-hr" only
      And projects.json is unchanged

    @AC-API-01g @integration @P2 @cov-errors
    Scenario: A broken projects.json is never overwritten
      Given projects.json holds the text "{not json"
      When the server is started with "sentinel dashboard --no-open"
      Then it exits with code 1 and names projects.json and the parse error
      And projects.json still holds "{not json"
      And no server.json is written

  Rule: One server per user

    @AC-SEC-01e @integration @P1 @cov-duplicate
    Scenario: A second call attaches to the live server
      Given a Sentinel server for user "dev" is running on port P
      When a human at a terminal runs "sentinel dashboard --no-open" in workspace "digital-hr"
      Then it prints "http://127.0.0.1:P/auth?t=" with the token of the running server and exits with code 0
      And no second server process is started
      And server.json is unchanged

    @AC-SEC-01f @integration @P2 @cov-happy-path
    Scenario: Attaching from a new workspace registers it for the running server
      Given a Sentinel server for user "dev" is running on port P
      And a workspace "payroll" with a valid sentinel.config.yaml that is not in projects.json
      When a human at a terminal runs "sentinel dashboard --no-open" in workspace "payroll"
      Then projects.json lists "payroll"
      And within 2 seconds GET /api/v1/projects on port P lists "payroll" without a restart

    @AC-SEC-01g @integration @P1 @cov-concurrency
    Scenario: Two starts at the same time give one server
      When two terminals run "sentinel dashboard --no-open" at the same time
      Then exactly one server process listens
      And the other call attaches to it, prints the same port and token and exits with code 0
      And ~/.config/sentinel/server.lock is held by the listening server only

    @AC-SEC-01h @integration @P1 @cov-errors
    Scenario Outline: A stale server.json is replaced
      Given server.json names pid <pid> and port 9999 with an old token
      And <condition>
      When the server is started with "sentinel dashboard --no-open"
      Then a new server starts with a new token and server.json names the new pid
      And the output says that a stale server.json was replaced
      Examples:
        | pid   | condition                                                                       |
        | 99999 | no process 99999 exists                                                         |
        | 4242  | process 4242 is alive but is not a Sentinel server and does not hold the lock   |

  Rule: Stopping the server and the token lifetime

    @AC-SEC-01i @integration @P1 @cov-happy-path
    Scenario Outline: Stopping the server removes server.json and releases the lock
      Given the server was started with "sentinel dashboard --no-open" and a client holds an open event stream
      When the server process receives <signal>
      Then the event stream is closed
      And server.json is removed and the lock is released
      And the process exits with code 0 within 5 seconds
      Examples:
        | signal  |
        | SIGINT  |
        | SIGTERM |

    @AC-SEC-01j @integration @P2 @cov-data-integrity
    Scenario: Stopping never removes another server's file
      Given the server was started and server.json was then rewritten to name another pid
      When the server process receives SIGTERM
      Then server.json is left in place

    @AC-SEC-01k @security @P1 @cov-authn
    Scenario: Every start rotates the token and the CSRF value
      Given the server was started, a client authenticated with token T1 and received CSRF value C1
      When the server is stopped and started again with "sentinel dashboard --no-open"
      Then server.json holds a new token T2 different from T1
      And GET /api/v1/runtime with the session cookie from T1 answers 401 with code "E_AUTH"
      And GET /auth?t=T1 answers 401 and sets no cookie
      And a POST with the cookie from T2 and CSRF value C1 answers 403 with code "E_CSRF"

    @AC-SEC-05a @integration @P3 @cov-authz
    Scenario: The local user is the only user and is Admin
      When GET /api/v1/runtime is called with a valid session
      Then the answer names user "dev" with role "admin"
      And no endpoint of Phase F creates, lists or switches users
