"""Pure state-machine tables and checks (no I/O, no DB).

Source of truth: docs/contracts/state-transitions.md. Tables are data; the
check_* functions only look pairs up. Errors: E_TRANSITION for an unknown
state or a pair not in the table, E_ACTOR when the pair exists but the actor
is not allowed.

Ambiguity resolved: R12d (docs-only SPECIFICATION_APPROVED -> EXECUTING) is
only legal on a docs-only run, which this pure module cannot see. For any
actor other than the engine it therefore reports E_TRANSITION (not E_ACTOR),
as AC-ORC-01c requires for the orchestrator. The engine must itself check the
docs-only precondition.
"""
from errors import SentinelError

ENGINE, ORCHESTRATOR, HUMAN = "engine", "orchestrator", "human"
E, O, H = ENGINE, ORCHESTRATOR, HUMAN
ACTORS = (ENGINE, ORCHESTRATOR, HUMAN)

RUN_STATES = ("CREATED", "TRIAGED", "PLANNED", "SPECIFICATION_REVIEW", "SPECIFICATION_APPROVED",
              "GHERKIN_REVIEW", "GHERKIN_APPROVED", "EXECUTING", "VERIFYING", "REVIEWING",
              "NEEDS_HUMAN", "COMPLETED", "FAILED", "CANCELLED", "BLOCKED")
RUN_FINAL = {"COMPLETED", "FAILED", "CANCELLED"}
RUN_ACTIVE = set(RUN_STATES) - RUN_FINAL
TASK_STATES = ("CREATED", "QUEUED", "RUNNING", "WAITING_FOR_INPUT", "BLOCKED", "FAILED", "CANCELLED", "COMPLETED")
APPROVAL_STATES = ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "REJECTED", "APPROVED", "INVALIDATED")
CYCLE_STATES = ("PLANNED", "RED_RUNNING", "RED_VERIFIED", "GREEN_RUNNING", "GREEN_VERIFIED",
                "REFACTOR_RUNNING", "REFACTOR_VERIFIED", "CYCLE_ACCEPTED", "REJECTED")
EXECUTION_STATUSES = ("running", "completed", "failed", "cancelled")
ACCEPTANCE_STATUSES = ("pending", "accepted", "rejected")

_ACTIVE = sorted(RUN_ACTIVE, key=RUN_STATES.index)
_RESUME_TARGETS = [s for s in _ACTIVE if s not in ("NEEDS_HUMAN", "BLOCKED")]

# (rule, from states, to states, actors). Order matters: first rule whose actors
# include the caller wins, so specific rows precede "any active" rows.
RUN_ROWS = [
    ("R2", ["CREATED"], ["TRIAGED"], [O]),
    ("R3", ["TRIAGED"], ["PLANNED"], [O, E]),
    ("R4", ["PLANNED"], ["SPECIFICATION_REVIEW"], [E]),
    ("R5", ["SPECIFICATION_REVIEW"], ["SPECIFICATION_APPROVED"], [H]),
    ("R6", ["SPECIFICATION_REVIEW"], ["PLANNED"], [H]),
    ("R7", ["SPECIFICATION_REVIEW"], ["CANCELLED"], [H]),
    ("R8", ["SPECIFICATION_APPROVED"], ["GHERKIN_REVIEW"], [E]),
    ("R9", ["GHERKIN_REVIEW"], ["GHERKIN_APPROVED"], [H]),
    ("R10", ["GHERKIN_REVIEW"], ["SPECIFICATION_APPROVED"], [H]),
    ("R11", ["GHERKIN_REVIEW"], ["CANCELLED"], [H]),
    ("R12", ["GHERKIN_APPROVED"], ["EXECUTING"], [E]),
    ("R12d", ["SPECIFICATION_APPROVED"], ["EXECUTING"], [E]),
    ("R13", ["EXECUTING"], ["VERIFYING"], [E]),
    ("R14", ["VERIFYING"], ["REVIEWING"], [E]),
    ("R15", ["REVIEWING"], ["COMPLETED"], [E]),
    ("R16", ["VERIFYING", "REVIEWING"], ["EXECUTING"], [E]),
    ("R17", _ACTIVE, ["SPECIFICATION_REVIEW"], [E]),
    ("R18", ["GHERKIN_APPROVED", "EXECUTING", "VERIFYING", "REVIEWING"], ["GHERKIN_REVIEW"], [E]),
    ("R19", _ACTIVE, ["NEEDS_HUMAN"], [E]),
    ("R20", ["NEEDS_HUMAN"], _RESUME_TARGETS, [H]),   # engine checks the stored previous state
    ("R21", _ACTIVE, ["BLOCKED"], [E]),
    ("R22", ["BLOCKED"], _RESUME_TARGETS, [E, H]),    # engine checks the stored previous state
    ("R23", _ACTIVE, ["CANCELLED"], [H]),
    ("R24", _ACTIVE, ["FAILED"], [E]),
    ("R25", ["COMPLETED"], ["COMPLETED"], [H]),       # acceptance only
]
# Rules whose actor mismatch is reported as E_TRANSITION (path not visible without run context).
_HIDDEN_ACTOR_RULES = {"R12d"}

_TASK_NON_FINAL = [s for s in TASK_STATES if s not in ("COMPLETED", "FAILED", "CANCELLED")]
TASK_ROWS = [
    ("", ["CREATED"], ["QUEUED"], [E]),
    ("", ["QUEUED"], ["RUNNING"], [E]),
    ("", ["RUNNING"], ["WAITING_FOR_INPUT"], [E]),
    ("", ["WAITING_FOR_INPUT"], ["RUNNING"], [O, H]),
    ("", ["RUNNING", "WAITING_FOR_INPUT"], ["COMPLETED", "FAILED"], [E]),
    ("", ["RUNNING", "WAITING_FOR_INPUT"], ["BLOCKED"], [E]),
    ("", _TASK_NON_FINAL, ["CANCELLED"], [H, E]),
]
APPROVAL_ROWS = [
    ("", ["DRAFT"], ["IN_REVIEW"], [E]),
    ("", ["IN_REVIEW"], ["APPROVED", "CHANGES_REQUESTED", "REJECTED"], [H]),
    ("", ["IN_REVIEW", "APPROVED"], ["INVALIDATED"], [E]),   # IN_REVIEW row added by Phase B open point 9
    ("", ["CHANGES_REQUESTED"], ["DRAFT"], [E]),
]
_CYCLE_RUNNING = ["RED_RUNNING", "GREEN_RUNNING", "REFACTOR_RUNNING"]
CYCLE_ROWS = [
    ("", ["PLANNED"], ["RED_RUNNING"], [E]),
    ("", ["RED_RUNNING"], ["RED_VERIFIED"], [E]),
    ("", ["RED_RUNNING"], ["PLANNED"], [E]),
    ("", ["RED_VERIFIED"], ["GREEN_RUNNING"], [E]),
    ("", ["GREEN_RUNNING"], ["GREEN_VERIFIED"], [E]),
    ("", ["GREEN_VERIFIED"], ["REFACTOR_RUNNING"], [E]),
    ("", ["REFACTOR_RUNNING"], ["REFACTOR_VERIFIED"], [E]),
    ("", ["REFACTOR_VERIFIED"], ["CYCLE_ACCEPTED"], [E]),
    ("", _CYCLE_RUNNING, ["REJECTED"], [E]),
]


def _index(rows):
    """Expand rows to {(from, to): [(rule, actors), ...]}; self-pairs only if listed explicitly."""
    table = {}
    for rule, froms, tos, actors in rows:
        for f in froms:
            for t in tos:
                if f == t and rule != "R25":
                    continue
                table.setdefault((f, t), []).append((rule, tuple(actors)))
    return table


RUN_TABLE = _index(RUN_ROWS)
TASK_TABLE = _index(TASK_ROWS)
APPROVAL_TABLE = _index(APPROVAL_ROWS)
CYCLE_TABLE = _index(CYCLE_ROWS)


def _check(table, states, kind, frm, to, actor):
    details = {"from": frm, "to": to}
    if frm not in states or to not in states or (frm, to) not in table:
        raise SentinelError("E_TRANSITION", f"{kind} transition {frm} -> {to} is not defined", details)
    options = table[(frm, to)]
    for rule, actors in options:
        if actor in actors:
            return rule
    if all(rule in _HIDDEN_ACTOR_RULES for rule, _ in options):
        raise SentinelError("E_TRANSITION", f"{kind} transition {frm} -> {to} is not defined", details)
    allowed = sorted({a for rule, actors in options if rule not in _HIDDEN_ACTOR_RULES for a in actors})
    raise SentinelError("E_ACTOR", f"{actor} may not move {kind} {frm} -> {to}",
                        {**details, "actor": actor, "allowed": allowed})


def check_run(frm, to, actor):
    return _check(RUN_TABLE, RUN_STATES, "run", frm, to, actor)


def check_task(frm, to, actor):
    _check(TASK_TABLE, TASK_STATES, "task", frm, to, actor)


def check_approval(frm, to, actor):
    _check(APPROVAL_TABLE, APPROVAL_STATES, "approval", frm, to, actor)


def check_cycle(frm, to, actor):
    _check(CYCLE_TABLE, CYCLE_STATES, "cycle", frm, to, actor)


# --- triage (pipeline.md matrix) -------------------------------------------------

def _band(*ceilings):
    """Int factor: tier = 1 + number of ceilings the value exceeds."""
    return lambda v: 1 + sum(v > c for c in ceilings)


# Each factor: ("int", fn) or ("enum", {value: tier}).
FACTORS = {
    "repos": ("int", lambda v: 4 if v >= 2 else 1),
    "files": ("int", _band(1, 3, 8)),
    "migration": ("enum", {"no": 1, "additive": 3, "any": 4}),
    "auth": ("enum", {"no": 1, "existing_pattern": 3, "new_rules": 4}),
    "security": ("enum", {"none": 1, "low": 3, "medium": 4, "high": 4}),
    "regression": ("enum", {"none": 1, "low": 2, "medium": 3, "high": 4}),
    "logic": ("enum", {"trivial": 1, "simple": 2, "moderate": 3, "complex": 4}),
}


def compute_tier(factors, requested=None):
    """max(1, requested, highest tier any factor demands). Unknown key/value -> E_VALIDATION."""
    tier = 1
    if requested is not None:
        if isinstance(requested, bool) or not isinstance(requested, int) or not 1 <= requested <= 4:
            raise SentinelError("E_VALIDATION", f"requested tier must be 1-4, got {requested!r}")
        tier = max(tier, requested)
    for key, value in (factors or {}).items():
        if key not in FACTORS:
            raise SentinelError("E_VALIDATION", f"unknown factor {key!r}", {"factors": sorted(FACTORS)})
        kind, rule = FACTORS[key]
        if kind == "int":
            try:
                n = int(str(value).strip())
                if n < 0:
                    raise ValueError
            except ValueError:
                raise SentinelError("E_VALIDATION", f"factor {key} needs a non-negative integer, got {value!r}")
            tier = max(tier, rule(n))
        else:
            if str(value) not in rule:
                raise SentinelError("E_VALIDATION", f"factor {key} has unknown value {value!r}",
                                    {"allowed": sorted(rule)})
            tier = max(tier, rule[str(value)])
    return tier


def check_tier_change(current, new):
    if current is not None and new < current:
        raise SentinelError("E_POLICY", f"tier only rises: {current} -> {new} refused",
                            {"current": current, "new": new})
    return new


# --- execution / acceptance ------------------------------------------------------

_EXECUTION_BY_STATE = {"COMPLETED": "completed", "FAILED": "failed", "CANCELLED": "cancelled"}


def execution_status_for(state):
    return _EXECUTION_BY_STATE.get(state, "running")


def check_acceptance_change(current, new, actor):
    if actor != HUMAN:
        raise SentinelError("E_ACTOR", f"{actor} may not change acceptance status",
                            {"actor": actor, "allowed": [HUMAN]})
    for v in (current, new):
        if v not in ACCEPTANCE_STATUSES:
            raise SentinelError("E_VALIDATION", f"unknown acceptance status {v!r}",
                                {"allowed": list(ACCEPTANCE_STATUSES)})
    if current == "rejected" and new == "accepted":
        raise SentinelError("E_PRECONDITION", "a rejected run cannot become accepted",
                            {"current": current, "new": new})


def finish_outcome(state, outcome):
    """Legacy `run finish --outcome` (passed|stopped|abandoned) for version-2 runs, human actor.

    Returns (target_state, execution_status, acceptance_status or None for unchanged).
    stopped/abandoned: active run -> CANCELLED/cancelled/rejected; already final -> E_PRECONDITION.
    passed: only on COMPLETED (no change); anywhere else -> E_PRECONDITION.
    Other outcome -> E_VALIDATION.
    """
    if outcome not in ("passed", "stopped", "abandoned"):
        raise SentinelError("E_VALIDATION", f"unknown outcome {outcome!r}",
                            {"allowed": ["passed", "stopped", "abandoned"]})
    if state not in RUN_STATES:
        raise SentinelError("E_TRANSITION", f"unknown run state {state!r}", {"from": state})
    if outcome == "passed":
        if state != "COMPLETED":
            raise SentinelError("E_PRECONDITION", f"outcome passed needs a COMPLETED run, run is {state}",
                                {"state": state})
        return ("COMPLETED", "completed", None)
    if state in RUN_FINAL:
        raise SentinelError("E_PRECONDITION", f"run is already {state}", {"state": state})
    return ("CANCELLED", "cancelled", "rejected")
