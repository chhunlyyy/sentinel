---
name: sentinel-send
description: Sends an idea, request, or specification drafted in any AI session to Sentinel as a new task. Summarizes the conversation, writes request and optional spec files, and starts an engine-driven run.
---

Send an idea, request, or specification drafted in this conversation to Sentinel as a new task.

## Steps

1. **Summarize the request:** Summarize what was discussed or decided in this conversation into a clear request paragraph describing what should be built.
2. **Identify specification:** If this conversation drafted or agreed upon a specification (with problem statement, scope, functional requirements, and acceptance criteria), extract it as a Markdown specification.
3. **Select project and kind:**
   - Confirm the workspace or project directory (run `sentinel doctor` to verify Sentinel is set up).
   - Pick the kind: `feature`, `bug`, `refactor`, `docs`, or `chore`.
   - Pick a concise slug for the task (lower-case letters, digits, and single hyphens, e.g. `leave-balance-export`).
4. **Write to temporary files:**
   - Write the request text to a temporary file, e.g. `/tmp/sentinel-request-<slug>.txt`.
   - If a specification was produced, write it to a temporary file, e.g. `/tmp/sentinel-spec-<slug>.md`.
5. **Create the run:**
   - Run:
     ```bash
     sentinel run new <slug> --type <kind> --driver engine --request-file /tmp/sentinel-request-<slug>.txt
     ```
     or, when a specification is included:
     ```bash
     sentinel run new <slug> --type <kind> --driver engine --request-file /tmp/sentinel-request-<slug>.txt --spec-file /tmp/sentinel-spec-<slug>.md
     ```
6. **Clean up:** Delete the temporary files created in step 4.
7. **Report:**
   - Print the link to the dashboard factory floor: `http://localhost:34441/projects/<project>/floor` (or the active dashboard URL).
   - State clearly that the task has been created.
   - **Never approve anything.** Remind the user that the specification and Gherkin scenarios require human review and approval with their typed hash confirmation at the spec gate.
