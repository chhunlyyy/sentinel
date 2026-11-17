import { describe, expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';
import { NodeDetails } from '../../src/components/NodeDetails.tsx';

describe('AC-ANL-02c missing values are shown as missing', () => {
  const rows: [string, string][] = [
    ['model', 'runner does not report it'],
    ['tokens', 'runner does not report it'],
    ['cost', 'runner does not report it'],
    ['seconds', 'task has not finished'],
  ];
  test.each(rows)('AC-ANL-02c %s', (field, reason) => {
    const node = {
      id: 't1', role: 'tdd_green', repo: 'backend', state: 'RUNNING', adapter: 'cli', provider: 'codex', model: 'm', attempt: 1,
      retry_of: null, error_code: null, started_at: '2026-11-14T09:00:00Z', finished_at: null, seconds: 12, tokens: 100, cost: 0.5,
      [field]: null, reasons: { [field]: reason },
    };
    render(<NodeDetails node={node as never} />);
    const row = screen.getByTestId(`field-${field}`);
    expect(row).toHaveTextContent('Not reported');
    expect(row).toHaveTextContent(reason);
    expect(row.textContent).not.toMatch(/\d/);
  });
});
