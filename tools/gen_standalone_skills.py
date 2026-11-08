import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STAGES = [
    dict(name="repro", stage="repro", repo=True, result="<repo>-repro-result.md",
         title="reproduce a bug",
         when='reproduce a bug with a failing test or exact steps, without fixing it. Use when asked to repro a bug, write a failing test for it, or confirm it is real.',
         needs="the bug report (symptoms, where it happens, expected behavior) and which repo it is in",
         after="The result file holds the failing test path or the exact steps. A fix is a separate step: `/sentinel-code`."),
    dict(name="spec", stage="specifier", repo=False, result="the spec in the shared repo (`specs/<slug>.md`)",
         title="turn a request into a spec",
         when='turn a request into one increment-scoped spec with Gherkin scenarios, a QA procedure and a contract note, without writing source. Use when asked to write or draft a spec, or to scope a request.',
         needs="the request in a paragraph and every decision already made (write them as `D1: <decision> (because <reason>)` lines in decisions.md)",
         after="If the spec says the request is too big, relay its slicing to the requester."),
    dict(name="code", stage="coder", repo=True, result="<repo>-coder-result.md",
         title="implement a change in one repo",
         when='implement a change in one repo, following its commands, guidelines and the active rules. Use when asked to implement, build or fix something in a specific repo without the full pipeline.',
         needs="what to build or fix, the repo, the files involved, and the spec or contract if there is one",
         after="The coder never commits or pushes."),
    dict(name="clean", stage="cleaner", repo=True, result="<repo>-cleaner-result.md",
         title="refactor recent changes for readability",
         when='refactor recently changed code in one repo for readability without changing behavior. Use when asked to clean up, tidy or simplify the code just written.',
         needs="the repo and, if not obvious from git, which changes to clean",
         after="Behavior must not change: the tests the cleaner ran are listed in the result."),
    dict(name="harden", stage="hardener", repo=True, result="<repo>-hardener-result.md",
         title="run mutation testing and plug test gaps",
         when='run mutation testing on recently changed code in one repo and plug test gaps. Use when asked to harden tests, run mutation testing, or check that tests really catch bugs.',
         needs="the repo and, if not obvious from git, which changes to cover",
         after="The result lists the mutation score, tests added and mutants left alive."),
    dict(name="review", stage="reviewer", repo=False, result="reviewer-result.md",
         title="review the current changes",
         when='review the current uncommitted changes skeptically against a spec or brief, the project invariants, correctness and security, without editing anything. Use when asked for a review, a second opinion, or a check before committing.',
         needs="what the change is supposed to do (a spec path, a short description, or just \"review the diff\"), which repos to look at, and any uncommitted files that are not part of this change",
         after="The reviewer writes nothing but the result file. Fixes go to `/sentinel-code`."),
    dict(name="qa", stage="qa", repo=False, result="qa-result.md",
         title="run QA against the running system",
         when='run the QA procedure against the running system on throwaway data and report triaged pass or fail. Use when asked to QA, test end to end, or run the regression suite.',
         needs="the QA procedure or spec to run, and whether this is targeted (only the new scenarios) or full (adds authorization probes, migrate-from-zero and the whole regression suite)",
         after="Ask the requester before any real-data clone. QA touches only the throwaway schemas, never real data."),
    dict(name="promote", stage="promotion", repo=False, result="promotion-result.md",
         title="move passing QA checks into the regression suite",
         when='move passing QA checks into the shared regression suite and register the spec. Use when asked to promote QA tests or add them to the regression suite.',
         needs="the slug of a passing QA run and its spec",
         after="Nothing is shared until `/sentinel-sync` pushes it, after approval."),
    dict(name="docs", stage="docs", repo=False, result="docs-result.md and pr-draft.md",
         title="update docs and draft the PR",
         when='update docs and the changelog for a change and draft the PR title and body. Use when asked to document a change or write a PR description.',
         needs="what changed (a spec, a diff, or a description) and the issue id if there is one",
         after="The PR draft is `pr-draft.md`; nothing is opened or committed."),
    dict(name="rollout", stage="rollout", repo=False, result="rollout-notes.md",
         title="collect the deploy-time changes",
         when='collect what a deploy needs for a change (env vars, flags, migrations, order). Use when asked for rollout notes or what to do on deploy.',
         needs="the changed repos and the coder result files, if any",
         after="Source is never edited."),
    dict(name="retro", stage="retrospective", repo=False, result="proposed-invariants.md",
         title="propose new project invariants from a change",
         when='propose new project-wide invariants from a change or a run. Use when asked what rules this work suggests or for a retrospective.',
         needs="the run or the change to look back on",
         after="It only proposes; adding an invariant is a pull request on the shared repo."),
]

TEMPLATE = """---
name: sentinel-{name}
description: Runs only the Sentinel {stage} stage on its own, without the full pipeline, to {when} The full pipeline (/sentinel) runs this same stage.
---

You run one stage on its own: {title}. `/sentinel` runs the same stage inside the full pipeline, with the same instructions. `sentinel` below is the Sentinel command line tool; if it is not found, tell the requester to install it with `uv tool install git+https://github.com/chhunlyyy/sentinel` and stop.

## Steps

1. Run `sentinel doctor`. No `sentinel.config.yaml`: use the `sentinel-setup` skill first. Other problems: show them and continue only if this stage does not need them.
2. Pick the run. If the requester names an open run, use its slug and folder. Otherwise create a standalone one, which needs no lock and no shared repo: `sentinel run new {name}-$(date +%Y%m%d-%H%M) --adhoc`. Note the slug it prints.
3. Ask only for what is missing, in one round: {needs}. Write it to `.sentinel/runs/<slug>/{brief}-brief.md`, with the exact paths involved.
{repo_step}4. Run `sentinel stage render --stage {stage}{repo_flag} --slug <slug>`. It prints the complete instructions for this project. Do the stage in its own fresh context, not in this conversation, so the result is not marked by what you already know. Use the first of these your tool offers:
   - A subagent: give it the rendered instructions and the brief as its task. In Claude Code use the Agent tool with a general-purpose agent. In Antigravity call `invoke_subagent` with the built-in `self` subagent. In other tools use their subagent, delegate or task feature.
   - A fresh headless session: `sentinel stage run --stage {stage}{repo_flag} --slug <slug> --brief <brief file> --runner <claude|agy|codex|gemini>`. Exit 3 means the stage wrote outside its repo, committed or touched the config (show the files, revert nothing without agreement); exit 1 means the tool failed (retry once).
   - Inline, only if neither exists. Say so at once. {inline_rule}
5. Record how it ran: `sentinel run update <slug> --stage {stage} --session {stage}=subagent` (or `headless`, `inline`).
6. Read the result ({result}) in `.sentinel/runs/<slug>/` and check the claims yourself (re-run the failing test, the command, the finding) before you report. Show the requester the verdict and any findings. {after}
7. For a standalone run, close it: `sentinel run finish <slug> --outcome passed|stopped`.

## Rules

- This skill does not run any other stage. Findings that belong to another stage are reported, not fixed here.
- Never commit or push.
- The active rules in `sentinel.config.yaml` are already inside the rendered stage; follow them in your own output too.
"""


def render(item):
    repo_flag = " --repo <id>" if item["repo"] else ""
    repo_step = ("   Ask which repo (one of the `repos` ids in `sentinel.config.yaml`) if it is not obvious; for several repos, run the stage once per repo, in parallel if your tool can.\n" if item["repo"] else "")
    prefix = "<repo>-" + item["stage"] if item["repo"] else item["stage"]
    inline_rule = "Do not run this stage inline: ask the requester how to proceed." if item["stage"] in ("reviewer", "qa") else "State in your report that it ran in the same context."
    return TEMPLATE.format(name=item["name"], stage=item["stage"], when=item["when"], title=item["title"], needs=item["needs"],
                           brief=prefix, repo_flag=repo_flag, repo_step=repo_step, inline_rule=inline_rule,
                           result=item["result"], after=item["after"])


RELEASE = """---
name: sentinel-release-check
description: Runs only the Sentinel release check on its own, the production-readiness gate (build, lint, tests, secret scan, migration and dependency notices, project extra checks). Use when asked to check if the changes are ready to ship, run the release check, or verify a build. The full pipeline (/sentinel) runs the same gate.
---

You run the release check on its own. `/sentinel` runs the same gate inside the full pipeline. `sentinel` below is the Sentinel command line tool; if it is not found, tell the requester to install it with `uv tool install git+https://github.com/chhunlyyy/sentinel` and stop.

## Steps

1. Run `sentinel doctor`. No `sentinel.config.yaml`: use the `sentinel-setup` skill first.
2. Run `sentinel release-check`. Pass `--repo <id>` for each repo the change touched (the default checks every repo with uncommitted changes, including unrelated work in progress). Pass `--skip build` when a dev server is running on that repo, because a build overwrites its output folder.
3. Report `RELEASE CHECK PASSED` or each failure with its repo and output line. Do not fix failures here: send each to `/sentinel-code` for the owning repo, then run the check again.

## Rules

- Never commit or push.
- A failing check means the change is not ready to ship; say so plainly.
"""


def main():
    out = {}
    for item in STAGES:
        out[f"sentinel-{item['name']}"] = render(item)
    out["sentinel-release-check"] = RELEASE
    check = "--check" in sys.argv
    bad = []
    for name, text in out.items():
        path = ROOT / "skills" / name / "SKILL.md"
        if check:
            if not path.exists() or path.read_text() != text:
                bad.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if check:
        if bad:
            sys.exit("out of date: " + ", ".join(bad))
        print("standalone skills up to date")
    else:
        print(f"wrote {len(out)} skills")


if __name__ == "__main__":
    main()
