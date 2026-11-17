import { describe, expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';
import { parseApiError } from '../../src/api/errors.ts';
import { ErrorView } from '../../src/components/ErrorView.tsx';

const envelope = (code: string, message: string, details: unknown) =>
  JSON.stringify({ error: { code, message, details } });

describe('AC-INS-05a error envelopes become actionable messages', () => {
  const rows: [number, string, string, unknown, string][] = [
    [400, 'E_VALIDATION', 'invalid slug', { field: 'slug' }, 'invalid slug (field slug)'],
    [409, 'E_APPROVAL_STALE', 'approval is stale', { current_sha256: '9b...' }, 'A newer version is in review. Reload it before deciding.'],
    [409, 'E_TRANSITION', 'not allowed in state COMPLETED', {}, 'Refused: the run moved on. not allowed in state COMPLETED'],
    [422, 'E_PRECONDITION', 'workspace missing', { fix: 'sentinel dashboard in the workspace' }, 'workspace missing. Fix: sentinel dashboard in the workspace'],
    [409, 'E_INTEGRITY', 'artifact changed on disk', { sha256: 'aa...' }, 'The file changed after it was stored. Its content is not shown.'],
    [500, 'E_INTERNAL', 'internal error', {}, 'Server error. See the terminal running sentinel dashboard.'],
    [418, 'E_SOMETHING_NEW', 'new thing', {}, 'new thing'],
  ];
  test.each(rows)('AC-INS-05a %i %s', (status, code, message, details, shown) => {
    const err = parseApiError(status, 'application/json', envelope(code, message, details));
    render(<ErrorView error={err} />);
    expect(screen.getByText(shown)).toBeInTheDocument();
    expect(screen.getByText(code)).toBeInTheDocument();
  });
});

describe('AC-INS-05b answers that are not an error envelope', () => {
  const rows: [number, string, string][] = [
    [502, 'text/html', '<h1>Bad gateway</h1>'],
    [500, 'application/json', ''],
    [400, 'application/json', JSON.stringify({ detail: 'x' })],
  ];
  test.each(rows)('AC-INS-05b %i %s', (status, type, body) => {
    const err = parseApiError(status, type, body);
    const { container } = render(<ErrorView error={err} />);
    expect(screen.getByText(`Unexpected answer (status ${status})`)).toBeInTheDocument();
    expect(container.querySelector('h1')).toBeNull();
  });
});
