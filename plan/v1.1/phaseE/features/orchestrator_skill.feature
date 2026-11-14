@REQ-ARC-03 @REQ-VIS-05 @REQ-OPS-04 @REQ-VIS-01 @REQ-VIS-03
Feature: Orchestrator skill around sentinel next, and regenerated adapters
  The orchestrator skill drives a version 2 run by asking "sentinel next" what is allowed and
  doing only that. It no longer decides order, loops or acceptance. The 0.1 flow stays
  documented for runs created with --tier, --adhoc or --legacy. sync-adapters ships the new skill
  to every supported tool.

  Background:
    Given the Sentinel source tree with skills/sentinel/SKILL.md and skills/sentinel/pipeline.md as rewritten in Phase E

  Rule: The skill describes the next loop and nothing else decides

    @AC-ARC-03l @unit @P1 @cov-happy-path
    Scenario Outline: The skill says what to do for each kind of step
      When skills/sentinel/SKILL.md is read
      Then its section "Version 2 runs" tells the orchestrator, for a step of kind "<kind>", to <action>
      Examples:
        | kind         | action                                                                                                  |
        | task         | run "sentinel task run <task-id>" when the step's adapter is "cli"                                       |
        | task         | start a fresh subagent with the step's prompt file when the adapter is "native", then run "sentinel task complete <task-id>" |
        | orchestrator | run the exact command or write the exact file the step names, such as "sentinel triage", decisions.md or "sentinel verify" |
        | human        | show the requester the exact commands the step names and stop until they say they are done              |
        | wait         | wait for the running task named in the step and then run "sentinel next" again                          |
        | done         | run "sentinel report <slug>" and give the requester the report and the "sentinel accept" command         |

    @AC-ARC-03m @unit @P1 @cov-authz
    Scenario: The skill gives the orchestrator no authority over state or acceptance
      When skills/sentinel/SKILL.md is read
      Then its section "Version 2 runs" says the orchestrator never runs "sentinel approve" or "sentinel accept"
      And it says the orchestrator never retries, reorders or skips a step on its own and never edits files under .sentinel/runs/ or the registry
      And it does not tell the orchestrator to run "sentinel run update", "sentinel stage run" or "sentinel release-check" for a version 2 run
      And it does not tell the orchestrator to verify a task's result itself in place of "sentinel verify"

    @AC-ARC-03n @e2e @P1 @cov-happy-path
    Scenario: A scripted orchestrator that follows the skill completes a run
      Given a workspace with a valid sentinel.config.yaml, repo "backend" using the test profile "fake-junit", and single_model false with every role routed to runner "fake"
      And fake CLIs that make the specifier, test_designer, each TDD phase, every check and each review stage succeed
      And a scripted orchestrator that maps each step kind to the single action the skill table names, and a scripted human who approves at a pseudo-terminal whenever a "human" step is returned
      When the orchestrator creates "leave-balance" with "sentinel run new leave-balance --type feature" and follows the loop
      Then the run state is COMPLETED with acceptance "accepted"
      And the orchestrator called only "sentinel run new", "sentinel triage", "sentinel next", "sentinel task run", "sentinel task complete", "sentinel verify" and "sentinel report"
      And the orchestrator called nothing between a "human" step and the scripted human's decision
      And the scripted human made exactly two approvals, the specification first and then the Gherkin

    @AC-ARC-03o @e2e @P2 @cov-happy-path
    Scenario: The same loop works with native subagents
      Given the workspace of AC-ARC-03n with single_model true
      And a scripted orchestrator that runs each native task's prompt in a separate process and then calls "sentinel task complete"
      When the orchestrator follows the loop for "leave-native"
      Then the run state is COMPLETED with acceptance "accepted"
      And every task row has adapter "native"

    @AC-VIS-03d @unit @P1 @cov-regression
    Scenario: The version 2 section names no provider choice
      When skills/sentinel/SKILL.md is read
      Then its section "Version 2 runs" contains no "--runner" option and no "sentinel routing" call
      And it says the engine picks the adapter, provider and model of each task

    @AC-VIS-01b @unit @P1 @cov-authz
    Scenario: Stage isolation stays the rule for native tasks
      When skills/sentinel/SKILL.md is read
      Then it still names the Agent tool, "invoke_subagent" and "Inline, only if neither exists"
      And it says a reviewer or qa task never runs in a context that wrote code for the run

  Rule: The 0.1 flow stays documented and working

    @AC-VIS-05a @unit @P1 @cov-regression
    Scenario: The skill keeps a section for 0.1 runs
      When skills/sentinel/SKILL.md is read
      Then its section "Legacy runs (0.1)" names "sentinel run new <slug> --tier N", "--adhoc", "--legacy", "sentinel run update", "sentinel resume", "sentinel stage run", "sentinel release-check", "sentinel sync push" and "sentinel run finish"
      And it says which flow applies: a run created with --tier, --adhoc or --legacy is a 0.1 run, any other run is version 2
      And it tells the orchestrator how to tell them apart for an existing slug ("schema_version" 2 in state.json, or "sentinel next" refusing a 0.1 run)

    @AC-VIS-05b @unit @P1 @cov-regression
    Scenario: pipeline.md keeps the triage matrix and the 0.1 stage lists
      When skills/sentinel/pipeline.md is read
      Then its triage matrix table is byte-identical to the one at commit aa1481c
      And its "Pipeline by tier" block for 0.1 runs is still present
      And it adds the version 2 run states, the two approval gates and the stages per tier of docs/architecture/orchestration-architecture.md section 2

    @AC-VIS-05c @integration @P1 @cov-regression
    Scenario: The engine still reads the triage matrix from pipeline.md
      Given a version 2 run "leave-balance" in state CREATED
      When "sentinel triage leave-balance --factors repos=2,files=5,schema=additive" is run
      Then the tier is the one the matrix in skills/sentinel/pipeline.md gives

    @AC-TST-01d @integration @P1 @cov-regression
    Scenario: The baseline selftest and earlier phase tests stay green
      When "python3 sentinel/scripts/selftest.py" and "python3 -m unittest discover -s tests" are run
      Then every one of the 95 baseline selftest checks passes, including the skill checks on front matter, machine paths, stage ownership and isolation words
      And every Phase A to D test passes

    @AC-VIS-05d @unit @P2 @cov-regression
    Scenario Outline: Helper skills point version 2 runs to the engine
      When skills/<skill>/SKILL.md is read
      Then it tells the orchestrator to use <command> for a version 2 run
      And it keeps its 0.1 instructions
      Examples:
        | skill           | command                               |
        | sentinel-resume | "sentinel next <slug> --json"         |
        | sentinel-status | "sentinel report <slug>"              |

  Rule: sync-adapters ships the new skill to every tool

    @AC-OPS-04a @integration @P1 @cov-happy-path
    Scenario: Claude Code gets the new skill and unchanged stage agents
      Given a workspace with a valid sentinel.config.yaml and repo "backend"
      When "sentinel sync-adapters" is run
      Then .claude/skills/sentinel/SKILL.md and pipeline.md are byte-identical to the source files
      And the agent files in .claude/agents are byte-identical to those generated before Phase E for the same config
      And .claude/settings.json permissions.deny still holds the four human-only rules

    @AC-OPS-04b @integration @P1 @cov-happy-path
    Scenario Outline: Other tools get the new orchestrator text
      Given a workspace with a valid sentinel.config.yaml and repo "backend"
      When "sentinel sync-adapters --tool <tool>" is run
      Then it exits with code 0
      And .sentinel/generated/orchestrator.md equals the body of skills/sentinel/SKILL.md after its front matter
      And the Sentinel block of AGENTS.md names "sentinel next" with "--json", "sentinel task run" and "sentinel task complete", still names "sentinel stage run" for 0.1 runs, and still says agents never run "sentinel approve" or "sentinel accept"
      And <extra>
      Examples:
        | tool   | extra                                                         |
        | agents | no other file is written                                      |
        | codex  | no other file is written                                      |
        | gemini | GEMINI.md imports AGENTS.md                                   |
        | cursor | .cursor/rules/sentinel.mdc points to AGENTS.md and orchestrator.md |

    @AC-OPS-04c @integration @P2 @cov-duplicate
    Scenario: Running sync-adapters twice changes nothing
      Given a workspace where "sentinel sync-adapters --tool agents" and "sentinel sync-adapters" were run
      When both are run again
      Then AGENTS.md, .sentinel/generated/ and .claude/ are byte-identical to before
      And AGENTS.md holds exactly one Sentinel block

    @AC-OPS-04d @integration @P2 @cov-perf-security
    Scenario: Generated files hold no machine path or unrendered placeholder
      Given a workspace with a valid sentinel.config.yaml and repo "backend"
      When "sentinel sync-adapters" and "sentinel sync-adapters --tool agents" are run
      Then no generated file contains "/home/", "Desktop/" or "{{"
