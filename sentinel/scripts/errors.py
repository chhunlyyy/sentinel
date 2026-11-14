"""Engine errors. Codes match docs/contracts/state-transitions.md section 5."""

CODES = {
    "E_TRANSITION", "E_ACTOR", "E_PRECONDITION", "E_APPROVAL_STALE", "E_APPROVAL_MISSING",
    "E_INTEGRITY", "E_SCOPE", "E_RESULT_SCHEMA", "E_LOCKED", "E_POLICY", "E_NOT_TTY",
    "E_VALIDATION", "E_NOT_FOUND", "E_MIGRATION",
    "E_EXIT", "E_TIMEOUT", "E_AGENT", "E_PROVIDER",
}

# CLI exit codes. 3 (boundary) and 4 (conflict) are kept from 0.1.
EXIT_REFUSED = 5
EXIT_HUMAN_REQUIRED = 6


class SentinelError(Exception):
    """A refused or failed engine operation. `details` is a JSON-safe dict."""

    def __init__(self, code, message, details=None, exit_code=EXIT_REFUSED):
        if code not in CODES:
            raise ValueError(f"unknown error code {code}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}
        self.exit_code = exit_code

    def to_dict(self):
        return {"error": self.code, "message": self.message, "details": self.details}
