"""One HTTP status per error code (plan/v1.1/phaseF/README.md point 4)."""

ENGINE_STATUS = {
    "E_VALIDATION": 400,
    "E_ACTOR": 403, "E_POLICY": 403, "E_NOT_TTY": 403,
    "E_NOT_FOUND": 404,
    "E_TRANSITION": 409, "E_APPROVAL_STALE": 409, "E_LOCKED": 409, "E_INTEGRITY": 409,
    "E_PRECONDITION": 422, "E_APPROVAL_MISSING": 422, "E_SCOPE": 422, "E_RESULT_SCHEMA": 422, "E_PROVIDER": 422,
    "E_EXIT": 500, "E_TIMEOUT": 500, "E_AGENT": 500, "E_MIGRATION": 500,
}

HTTP_ONLY_STATUS = {
    "E_AUTH": 401, "E_CSRF": 403, "E_HOST": 403, "E_ORIGIN": 403, "E_METHOD": 405,
    "E_BODY_TOO_LARGE": 413, "E_MEDIA_TYPE": 415, "E_RATE_LIMIT": 429, "E_INTERNAL": 500,
}

INTERNAL_MESSAGE = "internal error; see the server log"


def status_for(code):
    return ENGINE_STATUS.get(code) or HTTP_ONLY_STATUS.get(code) or 500


class HttpError(Exception):
    """An answer the server itself gives (HTTP-only codes, or a validation failure before the engine runs)."""

    def __init__(self, code, message, details=None, status=None, headers=None):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.details = code, message, details or {}
        self.status = status or status_for(code)
        self.headers = headers or {}


def envelope(code, message, details=None):
    return {"error": {"code": code, "message": message, "details": details or {}}}
