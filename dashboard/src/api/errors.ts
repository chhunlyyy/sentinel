export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly details: Record<string, unknown>;
  /** the message the user reads */
  readonly text: string;
  /** the answer was not an error envelope */
  readonly unexpected: boolean;
  /** no answer at all (network failure or timeout) */
  readonly network: boolean;

  constructor(init: { status: number; code: string | null; message: string; details?: Record<string, unknown>; text: string; unexpected?: boolean; network?: boolean }) {
    super(init.message);
    this.status = init.status;
    this.code = init.code;
    this.details = init.details ?? {};
    this.text = init.text;
    this.unexpected = init.unexpected ?? false;
    this.network = init.network ?? false;
  }
}

function describe(code: string, message: string, details: Record<string, unknown>, status: number): string {
  switch (code) {
    case 'E_VALIDATION':
      return typeof details.field === 'string' ? `${message} (field ${details.field})` : message;
    case 'E_APPROVAL_STALE':
      return 'A newer version is in review. Reload it before deciding.';
    case 'E_TRANSITION':
      return message ? `Refused: the run moved on. ${message}` : 'Refused: the run moved on.';
    case 'E_PRECONDITION':
      return typeof details.fix === 'string' && details.fix ? `${message}. Fix: ${details.fix}` : message;
    case 'E_INTEGRITY':
      return 'The file changed after it was stored. Its content is not shown.';
    case 'E_INTERNAL':
      return 'Server error. See the terminal running sentinel dashboard.';
    default:
      return status >= 500 && !message ? 'Server error. See the terminal running sentinel dashboard.' : message;
  }
}

/** Turn any HTTP answer that is not a success into an ApiError. The body is never rendered as HTML. */
export function parseApiError(status: number, contentType: string | null, bodyText: string): ApiError {
  let parsed: unknown = null;
  if ((contentType ?? '').includes('json')) {
    try {
      parsed = JSON.parse(bodyText);
    } catch {
      parsed = null;
    }
  }
  const env = (parsed as { error?: { code?: unknown; message?: unknown; details?: unknown } } | null)?.error;
  if (env && typeof env.code === 'string' && typeof env.message === 'string') {
    const details = env.details && typeof env.details === 'object' ? (env.details as Record<string, unknown>) : {};
    return new ApiError({ status, code: env.code, message: env.message, details, text: describe(env.code, env.message, details, status) });
  }
  const text = `Unexpected answer (status ${status})`;
  return new ApiError({ status, code: null, message: text, text, unexpected: true });
}

export function networkError(): ApiError {
  return new ApiError({ status: 0, code: null, message: 'no answer', text: 'The server did not answer.', network: true });
}
